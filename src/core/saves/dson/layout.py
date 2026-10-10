"""Byte layout of a DSON save: constants, bit helpers, table records and the document type.

Layout:

* 64-byte header: magic ``[0:4]``, revision ``[4:8]``, then little-endian i32 fields at 8
  (header_length), 16 (meta1_size), 20 (meta1_count), 24 (meta1_offset), 44 (meta2_count),
  48 (meta2_offset), 56 (data_length), 60 (data_offset).  Bytes 12, 28-43 and 52 are unknown and
  are passed through verbatim.
* meta1: one 16-byte ``<iiii`` record per OBJECT: parent (meta1 index, -1 for the root),
  meta2_index, direct_children, all_children (every descendant field).
* meta2: one 12-byte ``<iii`` record per FIELD in data order: name hash, data-relative offset,
  info (bit 0 = is_object, bits 2-10 = name length incl. NUL, bits 11-30 = meta1 index).
* data: each field starts with its NUL-terminated name at ``offset``; objects have no payload;
  a 1-byte payload (bool) is unaligned, anything longer starts at the next 4-byte boundary
  relative to the data block; a string is an i32 length (incl. NUL) + UTF-8 bytes + NUL.
"""

import struct
from dataclasses import dataclass
from typing import Final

from src.core.errors import DsonFormatError

HEADER_SIZE: Final = 64
META1_SIZE: Final = 16
META2_SIZE: Final = 12
DSON_MAGIC: Final = b"\x01\xb1\x00\x00"
"""Expected magic. UNVERIFIED against real saves: only a STRICT-level check, never a parse gate."""

I32: Final = struct.Struct("<i")
META1_STRUCT: Final = struct.Struct("<iiii")
META2_STRUCT: Final = struct.Struct("<iii")
_MAX_NAME_LENGTH: Final = 0x1FF
_MAX_OBJECT_INDEX: Final = 0xFFFFF
_INFO_MASK: Final = 0x7FFFFFFF

# ------------------------------------------------------------------ bit helpers


def _i32_from_u32(value: int) -> int:
    """Reinterpret unsigned 32 bits as a signed i32."""
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"32-bit metadata value is out of range: {value}")
    if value >= 0x80000000:
        return value - 0x100000000
    return value


def string_hash(name: str) -> int:
    """The field-name hash: ``h = (h * 53 + b) & 0xFFFFFFFF`` over UTF-8, signed."""
    hash_value = 0
    for byte in name.encode("utf-8"):
        hash_value = (hash_value * 53 + byte) & 0xFFFFFFFF
    if hash_value >= 0x80000000:
        hash_value -= 0x100000000
    return hash_value


def field_info(name: str, object_meta1_index: int | None = None) -> int:
    """The info word of a field: ``(name_len << 2) | is_object | (meta1_index << 11)``."""
    name_length = len(name.encode("utf-8")) + 1
    if name_length > _MAX_NAME_LENGTH:
        raise ValueError(f"DSON field name is too long: {name!r}")
    info = name_length << 2
    if object_meta1_index is not None:
        if not 0 <= object_meta1_index <= _MAX_OBJECT_INDEX:
            raise ValueError(f"DSON object index is out of range: {object_meta1_index}")
        info |= 1
        info |= object_meta1_index << 11
    return _i32_from_u32(info)


def object_index_from_info(info: int) -> int | None:
    """The meta1 index stored in an object field's info word."""
    info &= _INFO_MASK
    if not info & 1:
        return None
    return (info >> 11) & _MAX_OBJECT_INDEX


def set_object_index_in_info(info: int, object_index: int) -> int:
    """Store a new meta1 index in an info word (keeps bit 31 as-is)."""
    if not 0 <= object_index <= _MAX_OBJECT_INDEX:
        raise ValueError(f"DSON object index is out of range: {object_index}")
    info_bits = info & 0xFFFFFFFF
    high_bit = info_bits & 0x80000000
    name_len_bits = info_bits & 0x7FC
    return _i32_from_u32(high_bit | 1 | name_len_bits | (object_index << 11))


# ------------------------------------------------------------------ value types


@dataclass(frozen=True, slots=True)
class DsonHeader:
    """The 64-byte header; ``raw`` keeps every byte verbatim."""

    raw: bytes
    magic: bytes
    revision: bytes
    header_length: int
    meta1_size: int
    meta1_count: int
    meta1_offset: int
    meta2_count: int
    meta2_offset: int
    data_length: int
    data_offset: int

    @classmethod
    def from_bytes(cls, raw: bytes) -> DsonHeader:
        """Decode the first 64 bytes."""
        if len(raw) < HEADER_SIZE:
            raise DsonFormatError(
                "Save file is too small to contain a DSON header.", code="too_small", offset=0
            )
        head = bytes(raw[:HEADER_SIZE])

        def i32(off: int) -> int:
            return I32.unpack_from(head, off)[0]

        return cls(
            raw=head,
            magic=head[0:4],
            revision=head[4:8],
            header_length=i32(8),
            meta1_size=i32(16),
            meta1_count=i32(20),
            meta1_offset=i32(24),
            meta2_count=i32(44),
            meta2_offset=i32(48),
            data_length=i32(56),
            data_offset=i32(60),
        )


@dataclass(frozen=True, slots=True)
class Meta1:
    """One object record, 16 bytes ``<iiii``."""

    parent: int
    meta2_index: int
    direct_children: int
    all_children: int


@dataclass(frozen=True, slots=True)
class Meta2:
    """One field record, 12 bytes ``<iii``; see ``field_info`` for the bit layout of ``info``."""

    hash: int
    offset: int
    info: int

    @property
    def is_object(self) -> bool:
        return bool(self.info & 1)

    @property
    def name_length(self) -> int:
        """Name length INCLUDING the NUL terminator."""
        return ((self.info & _INFO_MASK) >> 2) & _MAX_NAME_LENGTH

    @property
    def object_index(self) -> int | None:
        """The meta1 index for an object field, ``None`` for a scalar."""
        return object_index_from_info(self.info)


def meta2_name(data: bytes, entry: Meta2) -> str:
    """The NUL-terminated name at ``entry.offset`` decoded losslessly."""
    end = entry.offset + entry.name_length - 1
    return data[entry.offset : end].decode("utf-8", "surrogateescape")


@dataclass(frozen=True, slots=True)
class DsonDocument:
    """A parsed save: header, both tables, the data block and a direct-children index.

    ``children[i]`` lists the direct child meta2 indices of field ``i`` (empty for scalars).  It is
    built by the same stack walk the validator performs (:mod:`.walk`), so fields of a subtree are
    always the contiguous meta2 range ``[i, subtree end)``.
    """

    header: DsonHeader
    meta1: tuple[Meta1, ...]
    meta2: tuple[Meta2, ...]
    data: bytes
    children: tuple[tuple[int, ...], ...]

    def name_of(self, i: int) -> str:
        """The field name (without NUL) decoded losslessly (``surrogateescape``)."""
        return meta2_name(self.data, self.meta2[i])

    def field_offset(self, i: int) -> int:
        """Data-relative start of field ``i``; ``len(data)`` one past the last field."""
        return self.meta2[i].offset if i < len(self.meta2) else len(self.data)

    def field_end(self, i: int) -> int:
        """Data-relative end of field ``i`` (start of the next field, or the data end)."""
        return self.field_offset(i + 1)

    def find_child(self, parent: int, name: str) -> int | None:
        """Direct-child PATH lookup under object ``parent`` (the root object is meta2 index 0)."""
        if not 0 <= parent < len(self.children):
            return None
        for child in self.children[parent]:
            if self.name_of(child) == name:
                return child
        return None

    def find_anywhere(self, name: str) -> int | None:
        """First field with that name anywhere.

        Diagnostics only: nested fields may share names with top-level ones.
        """
        for i in range(len(self.meta2)):
            if self.name_of(i) == name:
                return i
        return None


# ------------------------------------------------------------------ table readers


def read_header(raw: bytes) -> DsonHeader:
    """Decode the header only (no validation beyond the 64-byte minimum)."""
    return DsonHeader.from_bytes(raw)


def _read_meta1(raw: bytes, header: DsonHeader) -> tuple[Meta1, ...]:
    """Read the meta1 table with four separate ``<i`` reads per record.

    (Four reads and one ``<iiii`` read differ for a few negative offsets, and the STRUCTURAL
    verdict is defined by the four-read form.)
    """
    entries: list[Meta1] = []
    offset = header.meta1_offset
    try:
        for index in range(header.meta1_count):
            at = offset + index * META1_SIZE
            entries.append(
                Meta1(
                    I32.unpack_from(raw, at)[0],
                    I32.unpack_from(raw, at + 4)[0],
                    I32.unpack_from(raw, at + 8)[0],
                    I32.unpack_from(raw, at + 12)[0],
                )
            )
    except struct.error as exc:
        raise DsonFormatError(
            f"Meta1 table extends past the file: {exc}", code="meta1_truncated", offset=24
        ) from exc
    return tuple(entries)


def _read_meta2(raw: bytes, header: DsonHeader) -> tuple[Meta2, ...]:
    """Read the meta2 table (three separate ``<i`` reads per record, see above)."""
    entries: list[Meta2] = []
    offset = header.meta2_offset
    try:
        for index in range(header.meta2_count):
            at = offset + index * META2_SIZE
            entries.append(
                Meta2(
                    I32.unpack_from(raw, at)[0],
                    I32.unpack_from(raw, at + 4)[0],
                    I32.unpack_from(raw, at + 8)[0],
                )
            )
    except struct.error as exc:
        raise DsonFormatError(
            f"Meta2 table extends past the file: {exc}", code="meta2_truncated", offset=48
        ) from exc
    return tuple(entries)


def data_block(raw: bytes, header: DsonHeader) -> bytes:
    """The data slice (Python slice semantics for odd header values)."""
    return bytes(raw[header.data_offset : header.data_offset + header.data_length])


def read_tables(raw: bytes) -> tuple[DsonHeader, tuple[Meta1, ...], tuple[Meta2, ...]]:
    """Header plus both tables, exactly as the structural validator reads them (no validation)."""
    header = DsonHeader.from_bytes(raw)
    meta1 = _read_meta1(raw, header)
    meta2 = _read_meta2(raw, header)
    return header, meta1, meta2


def refresh_header(header: DsonHeader, n1: int, n2: int, data_length: int) -> DsonHeader:
    """``header.raw`` with the six size/offset fields recomputed."""
    raw = bytearray(header.raw)
    if len(raw) != HEADER_SIZE:
        raise DsonFormatError(
            f"Header must be exactly {HEADER_SIZE} bytes, got {len(raw)}.",
            code="header_size",
            offset=0,
        )
    meta1_size = n1 * META1_SIZE
    meta2_offset = HEADER_SIZE + meta1_size
    fields = (
        (16, meta1_size),
        (20, n1),
        (44, n2),
        (48, meta2_offset),
        (56, data_length),
        (60, meta2_offset + n2 * META2_SIZE),
    )
    try:
        for at, value in fields:
            I32.pack_into(raw, at, value)
    except struct.error as exc:
        raise DsonFormatError(
            f"Header field does not fit in 32 bits: {exc}", code="header_overflow", offset=16
        ) from exc
    return DsonHeader.from_bytes(bytes(raw))
