"""Binary DSON codec for Darkest Dungeon 1 saves (``persist.game.json`` and friends).

Pure port of the module-level ``dson_*`` helpers of the legacy app (``dd2.py`` at commit
``31e85d6``, lines 315-1641).  Every function documents the legacy line it comes from.  The legacy
file had four copy-pasted serializers and two near-duplicate resize algorithms; here there is ONE
:func:`serialize` and ONE :func:`_splice` primitive that :func:`replace_name_source_object`,
:func:`insert_name_source_object` and :func:`patch_scalar_string` all go through.

Layout (``dson_parse_header`` dd2.py:683-698, ``dson_parse_meta1`` 701, ``dson_parse_meta2`` 715):

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
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from typing import Final

from src.core.errors import DsonFormatError, DsonUnsupportedError
from src.core.ids import SaveIdentity
from src.core.saves.format import DsonProblem, DsonScalar, SaveValidationReport

HEADER_SIZE: Final = 64
META1_SIZE: Final = 16
META2_SIZE: Final = 12
DSON_MAGIC: Final = b"\x01\xb1\x00\x00"
"""Expected magic. UNVERIFIED against real saves: only a STRICT-level check, never a legacy gate."""

_I32: Final = struct.Struct("<i")
_META1: Final = struct.Struct("<iiii")
_META2: Final = struct.Struct("<iii")
_MAX_NAME_LENGTH: Final = 0x1FF
_MAX_OBJECT_INDEX: Final = 0xFFFFF
_INFO_MASK: Final = 0x7FFFFFFF

# ------------------------------------------------------------------ value types


@dataclass(frozen=True, slots=True)
class DsonHeader:
    """The 64-byte header; ``raw`` keeps every byte verbatim (dd2.py:683-698)."""

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
        """Decode the first 64 bytes exactly like ``dson_parse_header`` (dd2.py:683)."""
        if len(raw) < HEADER_SIZE:
            raise DsonFormatError(
                "Save file is too small to contain a DSON header.", code="too_small", offset=0
            )
        head = bytes(raw[:HEADER_SIZE])

        def i32(off: int) -> int:
            return _I32.unpack_from(head, off)[0]

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
    """One object record, 16 bytes ``<iiii`` (dd2.py:701)."""

    parent: int
    meta2_index: int
    direct_children: int
    all_children: int


@dataclass(frozen=True, slots=True)
class Meta2:
    """One field record, 12 bytes ``<iii`` (dd2.py:715); bit layout of ``info`` per dd2.py:669."""

    hash: int
    offset: int
    info: int

    @property
    def is_object(self) -> bool:
        return bool(self.info & 1)

    @property
    def name_length(self) -> int:
        """Name length INCLUDING the NUL terminator (dd2.py:760)."""
        return ((self.info & _INFO_MASK) >> 2) & _MAX_NAME_LENGTH

    @property
    def object_index(self) -> int | None:
        """The meta1 index for an object field, ``None`` for a scalar (dd2.py:734)."""
        return object_index_from_info(self.info)


@dataclass(frozen=True, slots=True)
class DsonDocument:
    """A parsed save: header, both tables, the data block and a direct-children index.

    ``children[i]`` lists the direct child meta2 indices of field ``i`` (empty for scalars).  It is
    built by the same stack walk the validator performs, so fields of a subtree are always the
    contiguous meta2 range ``[i, subtree end)``.
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
        """First field with that name anywhere (legacy ``dson_find_meta2_by_name`` dd2.py:751).

        Diagnostics only: nested fields may share names with top-level ones.
        """
        for i in range(len(self.meta2)):
            if self.name_of(i) == name:
                return i
        return None


def meta2_name(data: bytes, entry: Meta2) -> str:
    """The NUL-terminated name at ``entry.offset`` decoded losslessly (dd2.py:728, 344)."""
    end = entry.offset + entry.name_length - 1
    return data[entry.offset : end].decode("utf-8", "surrogateescape")


# ------------------------------------------------------------------ bit helpers (verbatim ports)


def _i32_from_u32(value: int) -> int:
    """dd2.py:323 ``dson_i32_from_u32_bits``."""
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"32-bit metadata value is out of range: {value}")
    if value >= 0x80000000:
        return value - 0x100000000
    return value


def string_hash(name: str) -> int:
    """dd2.py:335 ``dson_string_hash``: ``h = (h * 53 + b) & 0xFFFFFFFF`` over UTF-8, signed."""
    hash_value = 0
    for byte in name.encode("utf-8"):
        hash_value = (hash_value * 53 + byte) & 0xFFFFFFFF
    if hash_value >= 0x80000000:
        hash_value -= 0x100000000
    return hash_value


def field_info(name: str, object_meta1_index: int | None = None) -> int:
    """dd2.py:669 ``dson_field_info``: ``(name_len << 2) | is_object | (meta1_index << 11)``."""
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
    """dd2.py:734 ``dson_object_index_from_info``."""
    info &= _INFO_MASK
    if not info & 1:
        return None
    return (info >> 11) & _MAX_OBJECT_INDEX


def set_object_index_in_info(info: int, object_index: int) -> int:
    """dd2.py:741 ``dson_set_object_index_in_info`` (keeps bit 31 as-is)."""
    if not 0 <= object_index <= _MAX_OBJECT_INDEX:
        raise ValueError(f"DSON object index is out of range: {object_index}")
    info_bits = info & 0xFFFFFFFF
    high_bit = info_bits & 0x80000000
    name_len_bits = info_bits & 0x7FC
    return _i32_from_u32(high_bit | 1 | name_len_bits | (object_index << 11))


# ------------------------------------------------------------------ payload helpers


def align_pad(relative_offset: int) -> int:
    """Zero bytes needed to reach the next 4-byte boundary of the data block (dd2.py:798).

    ``relative_offset`` is the data-relative offset right AFTER the NUL-terminated field name
    (the legacy helper took the offset before the name and added the name length itself).
    """
    return (-relative_offset) % 4


def build_string_field(field_name: str, value: str, relative_offset: int) -> bytes:
    """dd2.py:803 ``dson_build_string_field``: name+NUL, pad to 4, i32 len incl. NUL, UTF-8, NUL.

    ``relative_offset`` is the data-relative offset at which the field starts.  The matching meta2
    record is ``Meta2(string_hash(field_name), relative_offset, field_info(field_name))``.
    """
    out = bytearray(field_name.encode("utf-8"))
    out.append(0)
    out.extend(b"\x00" * align_pad(relative_offset + len(out)))
    value_bytes = value.encode("utf-8") + b"\x00"
    out.extend(_I32.pack(len(value_bytes)))
    out.extend(value_bytes)
    return bytes(out)


def payload_layout(data: bytes, entry: Meta2, next_offset: int) -> tuple[bytes, int, int]:
    """dd2.py:758 ``dson_field_payload_layout``: ``(payload, payload_start, value_end)``.

    Objects have no payload; a 1-byte payload is unaligned; anything longer starts at the next
    4-byte boundary of the data block.
    """
    value_start = entry.offset + entry.name_length
    value_end = next_offset
    if entry.is_object or value_end <= value_start:
        return b"", value_start, value_end
    raw_value = data[value_start:value_end]
    if len(raw_value) == 1:
        return bytes(raw_value), value_start, value_end
    aligned_start = value_start + ((-value_start) % 4)
    if aligned_start > value_end:
        return b"", aligned_start, value_end
    return bytes(data[aligned_start:value_end]), aligned_start, value_end


def _decode_string_payload(payload: bytes) -> str | None:
    """Exact length-prefixed string check (replaces the ASCII-only guess of dd2.py:362)."""
    if len(payload) < 5:
        return None
    length = _I32.unpack_from(payload, 0)[0]
    if length < 1 or 4 + length != len(payload) or payload[-1] != 0:
        return None
    body = payload[4:-1]
    if 0 in body:
        return None
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


def decode_scalar(data: bytes, entry: Meta2, next_offset: int) -> DsonScalar:
    """Port of dd2.py:780 ``dson_decode_scalar_field`` with an exact, UTF-8 aware string check.

    1 byte -> bool; a well-formed length-prefixed string -> str; exactly 4 bytes -> int; anything
    else (floats, vectors, empty payloads) -> the raw payload bytes.  The legacy helper returned
    the first i32 of any longer payload and ``None`` for an empty one.
    """
    payload, _, _ = payload_layout(data, entry, next_offset)
    if len(payload) == 1:
        return bool(payload[0])
    text = _decode_string_payload(payload)
    if text is not None:
        return text
    if len(payload) == 4:
        return _I32.unpack_from(payload, 0)[0]
    return bytes(payload)


def rebuild_field_block(data: bytes, entry: Meta2, next_offset: int, new_offset: int) -> bytes:
    """dd2.py:910 ``dson_rebuild_existing_field_block``: re-pad a field for its new offset.

    Objects are their name only; a 1-byte payload is copied unaligned; any other payload is taken
    from its old 4-byte boundary and re-padded for the new one.
    """
    name_length = entry.name_length
    old_offset = entry.offset
    field_name_bytes = data[old_offset : old_offset + name_length]
    if entry.is_object:
        return bytes(field_name_bytes)
    old_data_start = old_offset + name_length
    old_data_size = next_offset - old_data_start
    if old_data_size == 1:
        return bytes(field_name_bytes) + bytes(data[old_data_start:next_offset])
    old_align = (-old_data_start) % 4
    payload_start = old_data_start + old_align
    payload = data[payload_start:next_offset]
    new_data_start = new_offset + name_length
    new_align = (-new_data_start) % 4
    return bytes(field_name_bytes) + (b"\x00" * new_align) + bytes(payload)


def _assert_shift_safe(doc: DsonDocument, i: int, new_offset: int) -> None:
    """Refuse fields that :func:`rebuild_field_block` would silently corrupt at ``new_offset``.

    The legacy rebuild copies a 1-byte payload verbatim; for anything else it keeps the bytes from
    the field's old 4-byte boundary on (the aligned payload of :func:`payload_layout`) and replaces
    whatever came before them with ``new_align`` zero bytes.  That is a faithful move only when

    * the bytes it drops are zero padding (non-zero bytes there are data we do not understand),
    * the old boundary lies inside the region (past it the payload is dropped and zeros added),
    * and, if the alignment actually changes, the aligned payload is a plausible aligned value of
      at least 4 bytes: a 0-3 byte "aligned payload" is no int, float or string, and moving it to
      another boundary changes its size or turns it into an unaligned bool.

    A move that keeps the alignment (``delta % 4 == 0``) reproduces the region byte for byte, so
    short payloads pass there, exactly as the legacy patcher left them alone.
    """
    entry = doc.meta2[i]
    if entry.is_object:
        return
    start = entry.offset + entry.name_length
    end = doc.field_end(i)
    size = end - start
    if size == 1:
        return
    old_align = (-start) % 4
    new_align = (-(new_offset + entry.name_length)) % 4
    payload, payload_start, _ = payload_layout(doc.data, entry, end)
    if old_align > size:
        reason = f"has a {size}-byte region that ends before its 4-byte boundary"
    elif any(doc.data[start:payload_start]):
        reason = "has non-zero bytes in its alignment padding"
    elif old_align != new_align and len(payload) < 4:
        reason = f"has a {len(payload)}-byte aligned payload that cannot be realigned safely"
    else:
        return
    raise DsonUnsupportedError(
        f"field {doc.name_of(i)!r} at {entry.offset} {reason}",
        code="unsafe_realign",
        field=doc.name_of(i),
        offset=entry.offset,
        size=len(payload),
        region=size,
    )


# ------------------------------------------------------------------ parsing


def _format_error(problem: DsonProblem) -> DsonFormatError:
    return DsonFormatError(problem.message, code=problem.code, offset=problem.offset)


def _problem_of(exc: DsonFormatError) -> DsonProblem:
    offset = exc.details.get("offset")
    return DsonProblem(exc.code, offset if isinstance(offset, int) else 0, exc.message)


def read_header(raw: bytes) -> DsonHeader:
    """Decode the header only (no validation beyond the 64-byte minimum)."""
    return DsonHeader.from_bytes(raw)


def _read_meta1(raw: bytes, header: DsonHeader) -> tuple[Meta1, ...]:
    """dd2.py:701 ``dson_parse_meta1``, with the same four separate ``<i`` reads per record.

    (Four reads and one ``<iiii`` read differ for a few negative offsets, and the legacy
    validator's verdict must be reproduced exactly.)
    """
    entries: list[Meta1] = []
    offset = header.meta1_offset
    try:
        for index in range(header.meta1_count):
            at = offset + index * META1_SIZE
            entries.append(
                Meta1(
                    _I32.unpack_from(raw, at)[0],
                    _I32.unpack_from(raw, at + 4)[0],
                    _I32.unpack_from(raw, at + 8)[0],
                    _I32.unpack_from(raw, at + 12)[0],
                )
            )
    except struct.error as exc:
        raise DsonFormatError(
            f"Meta1 table extends past the file: {exc}", code="meta1_truncated", offset=24
        ) from exc
    return tuple(entries)


def _read_meta2(raw: bytes, header: DsonHeader) -> tuple[Meta2, ...]:
    """dd2.py:715 ``dson_parse_meta2`` (three separate ``<i`` reads per record, see above)."""
    entries: list[Meta2] = []
    offset = header.meta2_offset
    try:
        for index in range(header.meta2_count):
            at = offset + index * META2_SIZE
            entries.append(
                Meta2(
                    _I32.unpack_from(raw, at)[0],
                    _I32.unpack_from(raw, at + 4)[0],
                    _I32.unpack_from(raw, at + 8)[0],
                )
            )
    except struct.error as exc:
        raise DsonFormatError(
            f"Meta2 table extends past the file: {exc}", code="meta2_truncated", offset=48
        ) from exc
    return tuple(entries)


def _read_tables(raw: bytes) -> tuple[DsonHeader, tuple[Meta1, ...], tuple[Meta2, ...]]:
    header = DsonHeader.from_bytes(raw)
    meta1 = _read_meta1(raw, header)
    meta2 = _read_meta2(raw, header)
    return header, meta1, meta2


# ------------------------------------------------------------------ LEGACY-level validation


class _RejectError(Exception):
    """Internal: carries the first problem the legacy validator would have raised on."""

    def __init__(self, problem: DsonProblem) -> None:
        super().__init__(problem.message)
        self.problem = problem


@dataclass(slots=True)
class _Frame:
    """An open object on the validator's stack (dd2.py:1286-1291).

    ``running`` is the object's running number (its position among object fields); only the
    tolerant :func:`_walk_tree` records it.
    """

    index: int
    object_index: int
    expected: int
    seen: int = 0
    running: int = -1


def _check_layout(raw: bytes, header: DsonHeader) -> None:
    """dd2.py:1208-1218: the four header/table layout checks, in order."""
    if header.data_offset + header.data_length != len(raw):
        raise _RejectError(
            DsonProblem(
                "file_size_mismatch", 60, "Header data offset/length does not match the file size."
            )
        )
    if header.meta1_size != header.meta1_count * META1_SIZE:
        raise _RejectError(
            DsonProblem("meta1_size_mismatch", 16, "Meta1 size does not match the object count.")
        )
    if header.meta2_offset != header.meta1_offset + header.meta1_size:
        raise _RejectError(
            DsonProblem(
                "meta2_offset_mismatch", 48, "Meta2 offset does not follow the meta1 block."
            )
        )
    if header.data_offset != header.meta2_offset + header.meta2_count * META2_SIZE:
        raise _RejectError(
            DsonProblem("data_offset_mismatch", 60, "Data offset does not follow the meta2 block.")
        )


def _check_offsets_sorted(meta2: tuple[Meta2, ...]) -> None:
    """dd2.py:1220-1222 (non-strict: equal offsets are accepted)."""
    offsets = [entry.offset for entry in meta2]
    if offsets != sorted(offsets):
        bad = next(k for k in range(1, len(offsets)) if offsets[k] < offsets[k - 1])
        raise _RejectError(
            DsonProblem("offsets_unsorted", offsets[bad], "Meta2 field offsets are not sorted.")
        )


def _check_field_name(data: bytes, entry: Meta2) -> str:
    """dd2.py:1229-1253: name length, termination, UTF-8 and hash; returns the decoded name.

    An empty name slice made the legacy raise ``IndexError``; that is a rejection here too.
    """
    offset = entry.offset
    name_length = entry.name_length
    if name_length <= 0:
        raise _RejectError(
            DsonProblem("name_length", offset, f"{offset}: Field name has invalid length.")
        )
    name_end = offset + name_length
    if name_end > len(data):
        raise _RejectError(
            DsonProblem(
                "name_past_data", offset, f"{offset}: Field name extends past the data block."
            )
        )
    name_bytes = data[offset:name_end]
    if not name_bytes or name_bytes[-1] != 0:
        raise _RejectError(
            DsonProblem(
                "name_not_terminated", offset, f"{offset}: Field name is not null-terminated."
            )
        )
    if 0 in name_bytes[:-1]:
        raise _RejectError(
            DsonProblem(
                "name_embedded_nul",
                offset,
                f"{offset}: Field name contains an unexpected null byte.",
            )
        )
    try:
        field_name = name_bytes[:-1].decode("utf-8")
    except UnicodeDecodeError:
        raise _RejectError(
            DsonProblem("name_not_utf8", offset, f"{offset}: Field name is not valid UTF-8.")
        ) from None
    if string_hash(field_name) != entry.hash:
        raise _RejectError(
            DsonProblem(
                "hash_mismatch", offset, f"{offset}: Field name hash mismatch for {field_name!r}."
            )
        )
    return field_name


def _check_object_record(
    meta1: tuple[Meta1, ...], entry: Meta2, object_index: int, field_index: int, parent: int
) -> None:
    """dd2.py:1258-1272: the object's meta1 record must point back here and at the open parent."""
    offset = entry.offset
    if object_index >= len(meta1):
        raise _RejectError(
            DsonProblem(
                "object_index_range",
                offset,
                f"{offset}: Object index {object_index} is outside meta1.",
            )
        )
    record = meta1[object_index]
    if record.meta2_index != field_index:
        raise _RejectError(
            DsonProblem(
                "object_meta2_mismatch",
                offset,
                f"{offset}: Object metadata points to field {record.meta2_index}, "
                f"but this field is {field_index}.",
            )
        )
    if record.parent != parent:
        raise _RejectError(
            DsonProblem(
                "object_parent_mismatch",
                offset,
                f"{offset}: Object parent {record.parent} does not match current parent {parent}.",
            )
        )


def _note_child(
    data: bytes, meta2: tuple[Meta2, ...], stack: list[_Frame], entry: Meta2, is_object: bool
) -> None:
    """dd2.py:1276-1283: count this field against the open object, or require a root object."""
    if stack:
        top = stack[-1]
        top.seen += 1
        if top.seen > top.expected:
            raise _RejectError(
                DsonProblem(
                    "too_many_children",
                    entry.offset,
                    f"{entry.offset}: Object {meta2_name(data, meta2[top.index])!r} has too many"
                    " children.",
                )
            )
    elif not is_object:
        raise _RejectError(
            DsonProblem(
                "first_field_not_object",
                entry.offset,
                f"{entry.offset}: First field is not a root object.",
            )
        )


def _walk_fields(data: bytes, meta1: tuple[Meta1, ...], meta2: tuple[Meta2, ...]) -> int:
    """dd2.py:1224-1303: the stack walk over every field; returns the number of objects seen."""
    field_stack: list[_Frame] = []
    parent_stack = [-1]
    running_object_index = -1
    for field_index, entry in enumerate(meta2):
        _check_field_name(data, entry)
        object_index = entry.object_index
        if object_index is not None:
            _check_object_record(meta1, entry, object_index, field_index, parent_stack[-1])
            running_object_index += 1
        _note_child(data, meta2, field_stack, entry, object_index is not None)
        if object_index is not None:
            field_stack.append(
                _Frame(field_index, object_index, meta1[object_index].direct_children)
            )
            parent_stack.append(running_object_index)
        while field_stack and field_stack[-1].seen == field_stack[-1].expected:
            field_stack.pop()
            parent_stack.pop()
    if field_stack:
        top = field_stack[-1]
        raise _RejectError(
            DsonProblem(
                "children_incomplete",
                meta2[top.index].offset,
                f"Object {meta2_name(data, meta2[top.index])!r} has {top.seen} of "
                f"{top.expected} expected children.",
            )
        )
    return running_object_index + 1


def _legacy_problem(
    raw: bytes, header: DsonHeader, meta1: tuple[Meta1, ...], meta2: tuple[Meta2, ...]
) -> DsonProblem | None:
    """The first problem ``dson_validate_editor_compatible`` (dd2.py:1202-1309) would raise on.

    Every check, its order and its arithmetic (including Python slice semantics for odd header
    values) follow the legacy function so the accept/reject verdict is identical.
    """
    data = raw[header.data_offset : header.data_offset + header.data_length]
    try:
        _check_layout(raw, header)
        _check_offsets_sorted(meta2)
        object_count = _walk_fields(data, meta1, meta2)
    except _RejectError as exc:
        return exc.problem
    if object_count != header.meta1_count:
        return DsonProblem(
            "object_count_mismatch",
            20,
            f"Object count mismatch: parsed {object_count}, header says {header.meta1_count}.",
        )
    return None


# ------------------------------------------------------------------ STRICT-level validation


def _strict_header_problems(header: DsonHeader) -> list[DsonProblem]:
    out: list[DsonProblem] = []
    if header.header_length != HEADER_SIZE:
        out.append(
            DsonProblem(
                "header_length", 8, f"Header length is {header.header_length}, expected 64."
            )
        )
    if header.meta1_offset != HEADER_SIZE:
        out.append(
            DsonProblem("meta1_offset", 24, f"Meta1 offset is {header.meta1_offset}, expected 64.")
        )
    return out


def _strict_offset_problems(meta2: tuple[Meta2, ...]) -> list[DsonProblem]:
    return [
        DsonProblem(
            "offsets_not_increasing",
            meta2[k].offset,
            f"{meta2[k].offset}: Field offset does not increase past the previous field"
            f" at {meta2[k - 1].offset}.",
        )
        for k in range(1, len(meta2))
        if meta2[k].offset <= meta2[k - 1].offset
    ]


def _strict_root_problems(meta1: tuple[Meta1, ...]) -> list[DsonProblem]:
    roots = sum(1 for entry in meta1 if entry.parent == -1)
    if roots == 1:
        return []
    return [DsonProblem("root_count", 0, f"Expected exactly one root object, found {roots}.")]


@dataclass(frozen=True, slots=True)
class _ObjectVisit:
    """One object as :func:`_walk_tree` saw it: where it is and how many fields it really holds."""

    field_index: int
    object_index: int
    running_index: int
    descendants: int


def _walk_tree(
    meta1: Sequence[Meta1], meta2: Sequence[Meta2]
) -> tuple[tuple[tuple[int, ...], ...], tuple[_ObjectVisit, ...]]:
    """Tolerant pre-order walk (never raises) with the validator's stack discipline.

    Returns the direct-children index (``children[i]`` = direct child meta2 indices of field
    ``i``, empty for scalars) and one visit per object in field order.  On a legacy-valid document
    it sees exactly the tree :func:`_walk_fields` accepted; on anything else it degrades quietly
    (an object whose meta1 index is out of range is treated as a leaf, an object left open at the
    end owns the rest of the file).
    """
    children: list[list[int]] = [[] for _ in meta2]
    visits: list[_ObjectVisit] = []
    stack: list[_Frame] = []
    running = -1

    def close(frame: _Frame, last_index: int) -> None:
        visits.append(
            _ObjectVisit(frame.index, frame.object_index, frame.running, last_index - frame.index)
        )

    for index, entry in enumerate(meta2):
        if stack:
            top = stack[-1]
            children[top.index].append(index)
            top.seen += 1
        object_index = entry.object_index
        if object_index is not None:
            running += 1
            if 0 <= object_index < len(meta1):
                expected = meta1[object_index].direct_children
                stack.append(_Frame(index, object_index, expected, running=running))
        while stack and stack[-1].seen >= stack[-1].expected:
            close(stack.pop(), index)
    while stack:
        close(stack.pop(), len(meta2) - 1)
    visits.sort(key=lambda visit: visit.field_index)
    return tuple(tuple(c) for c in children), tuple(visits)


def _strict_walk_problems(
    data: bytes, meta1: tuple[Meta1, ...], meta2: tuple[Meta2, ...]
) -> list[DsonProblem]:
    """meta1 index == running object index, and exact ``all_children`` per object."""
    out: list[DsonProblem] = []
    _, visits = _walk_tree(meta1, meta2)
    for visit in visits:
        entry = meta2[visit.field_index]
        if visit.object_index != visit.running_index:
            out.append(
                DsonProblem(
                    "meta1_order",
                    entry.offset,
                    f"{entry.offset}: Object {meta2_name(data, entry)!r} uses meta1 index"
                    f" {visit.object_index} but is object number {visit.running_index}.",
                )
            )
        declared = meta1[visit.object_index].all_children
        if declared != visit.descendants:
            out.append(
                DsonProblem(
                    "all_children_mismatch",
                    entry.offset,
                    f"{entry.offset}: Object {meta2_name(data, entry)!r} declares"
                    f" all_children={declared} but has {visit.descendants} descendant fields.",
                )
            )
    return out


def validate(raw: bytes) -> SaveValidationReport:
    """Validate without raising.

    LEGACY level reproduces the verdict of ``dson_validate_editor_compatible`` (dd2.py:1202-1309):
    it accepts exactly what the legacy accepted.  STRICT level adds ``bad_magic``, the 64-byte
    header layout, strictly increasing meta2 offsets, meta1 index == running object index, exact
    ``all_children`` per object and exactly one root.
    """
    strict: list[DsonProblem] = []
    if raw[:4] != DSON_MAGIC:
        strict.append(
            DsonProblem(
                "bad_magic",
                0,
                f"Unexpected magic {bytes(raw[:4]).hex()!r}; expected {DSON_MAGIC.hex()!r}"
                " (the expected value is unverified against real saves).",
            )
        )
    try:
        header, meta1, meta2 = _read_tables(raw)
    except DsonFormatError as exc:
        return SaveValidationReport((_problem_of(exc),), tuple(strict))
    strict.extend(_strict_header_problems(header))
    legacy = _legacy_problem(raw, header, meta1, meta2)
    if legacy is not None:
        return SaveValidationReport((legacy,), tuple(strict))
    data = raw[header.data_offset : header.data_offset + header.data_length]
    strict.extend(_strict_offset_problems(meta2))
    strict.extend(_strict_root_problems(meta1))
    strict.extend(_strict_walk_problems(data, meta1, meta2))
    return SaveValidationReport((), tuple(strict))


# ------------------------------------------------------------------ documents


def _refresh_header(header: DsonHeader, n1: int, n2: int, data_length: int) -> DsonHeader:
    """``header.raw`` with the six size/offset fields recomputed (dd2.py:1160-1172)."""
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
            _I32.pack_into(raw, at, value)
    except struct.error as exc:
        raise DsonFormatError(
            f"Header field does not fit in 32 bits: {exc}", code="header_overflow", offset=16
        ) from exc
    return DsonHeader.from_bytes(bytes(raw))


def _make_document(
    header: DsonHeader, meta1: Sequence[Meta1], meta2: Sequence[Meta2], data: bytes
) -> DsonDocument:
    children, _ = _walk_tree(meta1, meta2)
    return DsonDocument(
        header=_refresh_header(header, len(meta1), len(meta2), len(data)),
        meta1=tuple(meta1),
        meta2=tuple(meta2),
        data=data,
        children=children,
    )


def parse(raw: bytes) -> DsonDocument:
    """Parse a legacy-valid save into a :class:`DsonDocument`.

    Raises :class:`DsonFormatError` on any layout problem: the legacy validator's checks plus the
    ``header_length == 64`` / ``meta1_offset == 64`` gate of the legacy patchers (dd2.py:1316).
    ``serialize(parse(raw)) == raw`` for every accepted input.
    """
    header, meta1, meta2 = _read_tables(raw)
    problem = _legacy_problem(raw, header, meta1, meta2)
    if problem is not None:
        raise _format_error(problem)
    if header.header_length != HEADER_SIZE or header.meta1_offset != HEADER_SIZE:
        raise DsonFormatError(
            "Unsupported DSON header layout.", code="unsupported_header_layout", offset=8
        )
    if header.meta1_count < 0 or header.meta2_count < 0:
        raise DsonFormatError("Negative table count in header.", code="negative_count", offset=20)
    data = bytes(raw[header.data_offset : header.data_offset + header.data_length])
    return _make_document(header, meta1, meta2, data)


def serialize(doc: DsonDocument) -> bytes:
    """THE only serializer (replaces dd2.py:987-1003, 1160-1187, 1439-1466, 1603-1630).

    ``header.raw`` with the six size/offset fields recomputed, then meta1, meta2 and the data.
    """
    header = _refresh_header(doc.header, len(doc.meta1), len(doc.meta2), len(doc.data))
    try:
        meta1 = b"".join(
            _META1.pack(e.parent, e.meta2_index, e.direct_children, e.all_children)
            for e in doc.meta1
        )
        meta2 = b"".join(_META2.pack(e.hash, e.offset, e.info) for e in doc.meta2)
    except struct.error as exc:
        raise DsonFormatError(
            f"Table value does not fit in 32 bits: {exc}", code="table_overflow", offset=64
        ) from exc
    return header.raw + meta1 + meta2 + doc.data


# ------------------------------------------------------------------ tree helpers


def _entry(doc: DsonDocument, i: int) -> Meta2:
    if not 0 <= i < len(doc.meta2):
        raise DsonFormatError(
            f"Field index {i} is out of range.", code="index_out_of_range", offset=0
        )
    return doc.meta2[i]


def _object_meta1_index(doc: DsonDocument, i: int) -> int:
    entry = _entry(doc, i)
    object_index = entry.object_index
    if object_index is None:
        raise DsonFormatError(
            f"{doc.name_of(i)!r} is not marked as an object in metadata.",
            code="not_an_object",
            offset=entry.offset,
        )
    if object_index >= len(doc.meta1):
        raise DsonFormatError(
            f"{doc.name_of(i)!r} points outside the meta1 table.",
            code="object_index_range",
            offset=entry.offset,
        )
    return object_index


def _subtree_end(doc: DsonDocument, i: int) -> int:
    """One past the last descendant field of ``i`` (fields are in pre-order)."""
    end = i + 1
    stack = [i]
    while stack:
        node = stack.pop()
        for child in doc.children[node]:
            end = max(end, child + 1)
            stack.append(child)
    return end


def _parent_map(doc: DsonDocument) -> list[int]:
    """meta2 index -> parent meta2 index (-1 for top-level fields)."""
    parents = [-1] * len(doc.meta2)
    for parent, kids in enumerate(doc.children):
        for child in kids:
            parents[child] = parent
    return parents


# ------------------------------------------------------------------ the splice primitive


@dataclass(frozen=True, slots=True)
class _Span:
    """The region a splice replaces: meta1 ``[m1_start, m1_end)`` and meta2 ``[m2_start, m2_end)``.

    The data region is implied: from ``field_offset(m2_start)`` to ``field_offset(m2_end)``.
    """

    m1_start: int
    m1_end: int
    m2_start: int
    m2_end: int


def _bump_ancestors(meta1: list[Meta1], node: int, *, direct_delta: int, all_delta: int) -> None:
    """dd2.py:1400-1403 / 1119-1120: parent ``direct_children``, ancestors' ``all_children``."""
    remaining = len(meta1) + 1
    while node >= 0:
        remaining -= 1
        if remaining < 0:
            raise DsonFormatError("Parent pointers form a cycle.", code="parent_cycle", offset=0)
        if node >= len(meta1):
            raise DsonFormatError(
                f"Parent pointer {node} is outside the meta1 table.",
                code="parent_out_of_range",
                offset=0,
            )
        entry = meta1[node]
        meta1[node] = replace(
            entry,
            direct_children=entry.direct_children + direct_delta,
            all_children=entry.all_children + all_delta,
        )
        direct_delta = 0
        node = entry.parent


def _rebuild_tail(
    doc: DsonDocument, span: _Span, cursor: int, meta1_delta: int, *, renumber_objects: bool
) -> tuple[list[bytes], list[Meta2]]:
    """dd2.py:1419-1433: rebuild every field after the span at its new offset.

    With ``renumber_objects`` every object at or past ``span.m1_end`` gets its meta1 index shifted
    by ``meta1_delta`` through :func:`set_object_index_in_info`, which also normalises the info
    word (only bit 31, bit 0, the name length and the index survive).  The legacy resize/insert
    paths did that even for a zero delta (dd2.py:1109, 1425); the scalar patch (dd2.py:971-985)
    copied every info verbatim, so it passes ``False``.
    """
    parts: list[bytes] = []
    tail: list[Meta2] = []
    for j in range(span.m2_end, len(doc.meta2)):
        entry = doc.meta2[j]
        _assert_shift_safe(doc, j, cursor)
        rebuilt = rebuild_field_block(doc.data, entry, doc.field_end(j), cursor)
        object_index = entry.object_index
        info = entry.info
        if renumber_objects and object_index is not None and object_index >= span.m1_end:
            info = set_object_index_in_info(info, object_index + meta1_delta)
        tail.append(Meta2(entry.hash, cursor, info))
        parts.append(rebuilt)
        cursor += len(rebuilt)
    return parts, tail


def _splice(
    doc: DsonDocument,
    span: _Span,
    block_data: bytes,
    block_meta1: Sequence[Meta1],
    block_meta2: Sequence[Meta2],
    *,
    parent_meta1: int,
    parent_direct_delta: int,
) -> DsonDocument:
    """Replace ``span`` with a prebuilt block and repair everything after it.

    This is the common core of ``dson_patch_mod_list_resize`` (dd2.py:1312), ``dson_insert_missing
    _applied_ugcs`` (1054), ``dson_patch_named_name_source_object`` (1481) and
    ``dson_patch_scalar_string_field`` (937):

    * preserved meta1 records with ``parent >= m1_end`` / ``meta2_index >= m2_end`` shift by the
      meta1 / meta2 count deltas (dd2.py:1385-1389, 1104-1110);
    * ``parent_meta1`` gets ``direct_children += parent_direct_delta`` and every ancestor from it
      upwards gets ``all_children += meta2 delta`` (dd2.py:1400-1403, 1119-1120);
    * every field after the span is rebuilt for its new offset with :func:`rebuild_field_block`
      (guarded by :func:`_assert_shift_safe`) and, when the splice touches meta1 at all, object
      fields pointing at or past ``m1_end`` get their meta1 index rewritten (dd2.py:1419-1433).
    """
    block_meta1 = tuple(block_meta1)
    block_meta2 = tuple(block_meta2)
    d1 = len(block_meta1) - (span.m1_end - span.m1_start)
    d2 = len(block_meta2) - (span.m2_end - span.m2_start)
    # The legacy rewrote later objects' info in every path that edits meta1 (resize, insert), even
    # when the count did not change, but never in the scalar patch: mirror that exactly.
    renumber_objects = bool(block_meta1) or span.m1_start != span.m1_end

    def shifted(entry: Meta1) -> Meta1:
        parent = entry.parent + d1 if entry.parent >= span.m1_end else entry.parent
        meta2_index = (
            entry.meta2_index + d2 if entry.meta2_index >= span.m2_end else entry.meta2_index
        )
        return Meta1(parent, meta2_index, entry.direct_children, entry.all_children)

    meta1 = [
        *(shifted(e) for e in doc.meta1[: span.m1_start]),
        *block_meta1,
        *(shifted(e) for e in doc.meta1[span.m1_end :]),
    ]
    parent = parent_meta1 + d1 if parent_meta1 >= span.m1_end else parent_meta1
    _bump_ancestors(meta1, parent, direct_delta=parent_direct_delta, all_delta=d2)

    start = doc.field_offset(span.m2_start)
    parts, tail = _rebuild_tail(
        doc, span, start + len(block_data), d1, renumber_objects=renumber_objects
    )
    data = b"".join([doc.data[:start], block_data, *parts])
    meta2 = [*doc.meta2[: span.m2_start], *block_meta2, *tail]
    return _make_document(doc.header, meta1, meta2, data)


def _build_name_source_block(
    name_bytes: bytes,
    entries: Sequence[SaveIdentity],
    *,
    data_start: int,
    object_meta1: int,
    object_meta2: int,
    parent_meta1: int,
    object_entry: Meta2,
) -> tuple[bytes, list[Meta1], list[Meta2]]:
    """Build an object ``{ "0": {name, source}, ... }`` block (dd2.py:866 and 1012 merged).

    ``name_bytes`` is the object's NUL-terminated name.  Child ``k`` gets meta1 index
    ``object_meta1 + 1 + k`` and meta2 index ``object_meta2 + 1 + 3k``; each child is
    ``Meta1(object_meta1, ..., 2, 2)`` and the object itself ``(parent, object_meta2, N, 3N)``
    (dd2.py:1044-1049, 1084-1089, 1397-1398).
    """
    data = bytearray(name_bytes)
    count = len(entries)
    meta1 = [Meta1(parent_meta1, object_meta2, count, count * 3)]
    meta2 = [object_entry]
    for k, identity in enumerate(entries):
        child_name = str(k)
        child_offset = data_start + len(data)
        data.extend(child_name.encode("utf-8"))
        data.append(0)
        child_info = field_info(child_name, object_meta1 + 1 + k)
        meta2.append(Meta2(string_hash(child_name), child_offset, child_info))
        meta1.append(Meta1(object_meta1, object_meta2 + 1 + 3 * k, 2, 2))

        name_offset = data_start + len(data)
        data.extend(build_string_field("name", identity.name, name_offset))
        meta2.append(Meta2(string_hash("name"), name_offset, field_info("name")))

        source_offset = data_start + len(data)
        data.extend(build_string_field("source", identity.source, source_offset))
        meta2.append(Meta2(string_hash("source"), source_offset, field_info("source")))
    return bytes(data), meta1, meta2


# ------------------------------------------------------------------ public edits


def _read_child_identity(doc: DsonDocument, child: int, object_name: str) -> SaveIdentity:
    entry = doc.meta2[child]
    if not entry.is_object:
        raise DsonFormatError(
            f"Child {doc.name_of(child)!r} of {object_name!r} is not an object.",
            code="name_source_shape",
            offset=entry.offset,
        )
    values: dict[str, str] = {}
    for field in doc.children[child]:
        field_entry = doc.meta2[field]
        field_name = doc.name_of(field)
        if field_entry.is_object or field_name not in ("name", "source"):
            continue
        value = decode_scalar(doc.data, field_entry, doc.field_end(field))
        if isinstance(value, str):
            values.setdefault(field_name, value)
    if "name" not in values or "source" not in values:
        raise DsonFormatError(
            f"Child {doc.name_of(child)!r} of {object_name!r} lacks string fields name/source.",
            code="name_source_shape",
            offset=entry.offset,
        )
    return SaveIdentity(values["name"], values["source"])


def read_name_source_object(doc: DsonDocument, i: int) -> tuple[SaveIdentity, ...]:
    """Read object ``i`` whose children ``"0".."N-1"`` each hold string fields name and source.

    Replaces the heuristic byte scanner (dd2.py:395-484) and ``dson_parse_named_name_source_object``
    (dd2.py:821): UTF-8 throughout, no ASCII / 300-byte / 999-entry limits.  Child order is data
    order; child names are not interpreted.  Raises :class:`DsonFormatError` when a child is not
    an object or lacks a string ``name`` or ``source``.
    """
    _object_meta1_index(doc, i)
    object_name = doc.name_of(i)
    return tuple(_read_child_identity(doc, child, object_name) for child in doc.children[i])


def replace_name_source_object(
    doc: DsonDocument, i: int, entries: Sequence[SaveIdentity]
) -> DsonDocument:
    """Rewrite object ``i`` as ``{ "0": {name, source}, ... }`` for ``entries``.

    Byte-parity with ``dson_patch_mod_list_resize`` (dd2.py:1312-1478) and
    ``dson_patch_named_name_source_object`` (1481-1641) on well-formed saves: the object's own
    meta2 record and name bytes are kept verbatim, its meta1 becomes ``(parent, i, N, 3N)``, the
    old subtree is dropped, ancestors get ``all_children += delta`` and later fields are rebuilt.
    Raises :class:`DsonUnsupportedError` (``nested_object_span``) when the subtree's meta1
    records are not the contiguous range right after the object's own record.
    """
    wanted = tuple(entries)
    object_meta1 = _object_meta1_index(doc, i)
    entry = doc.meta2[i]
    end = _subtree_end(doc, i)
    descendants = sorted(
        index for j in range(i + 1, end) if (index := doc.meta2[j].object_index) is not None
    )
    expected = list(range(object_meta1 + 1, object_meta1 + 1 + len(descendants)))
    if descendants != expected:
        raise DsonUnsupportedError(
            f"object {doc.name_of(i)!r} has descendant objects at meta1 {descendants} instead of"
            f" the contiguous range {expected}",
            code="nested_object_span",
            field=doc.name_of(i),
            offset=entry.offset,
        )
    parent_meta1 = doc.meta1[object_meta1].parent
    name_bytes = doc.data[entry.offset : entry.offset + entry.name_length]
    block, meta1, meta2 = _build_name_source_block(
        name_bytes,
        wanted,
        data_start=entry.offset,
        object_meta1=object_meta1,
        object_meta2=i,
        parent_meta1=parent_meta1,
        object_entry=entry,
    )
    span = _Span(object_meta1, object_meta1 + 1 + len(descendants), i, end)
    return _splice(doc, span, block, meta1, meta2, parent_meta1=parent_meta1, parent_direct_delta=0)


def insert_name_source_object(
    doc: DsonDocument, *, before: int, name: str, entries: Sequence[SaveIdentity]
) -> DsonDocument:
    """Insert a new ``{ "0": {name, source}, ... }`` object right before object ``before``.

    Parity with ``dson_insert_missing_applied_ugcs`` (dd2.py:1054-1199): the new object takes the
    anchor's meta1 index, meta2 index and data offset (the anchor and everything after it shift),
    the anchor's parent gets ``direct_children += 1`` and ``all_children += 1 + 3N``.  Raises
    :class:`DsonUnsupportedError` (``no_anchor``) when ``before`` is not an object or has no
    parent object (inserting before the root would create a second root).
    """
    if "\x00" in name:
        raise ValueError("DSON field name must not contain NUL")
    wanted = tuple(entries)
    entry = _entry(doc, before)
    anchor_meta1 = entry.object_index
    if anchor_meta1 is None or anchor_meta1 >= len(doc.meta1):
        raise DsonUnsupportedError(
            f"{doc.name_of(before)!r} is not marked as an object in metadata.",
            code="no_anchor",
            field=doc.name_of(before),
            offset=entry.offset,
        )
    parent_meta1 = doc.meta1[anchor_meta1].parent
    if parent_meta1 < 0:
        raise DsonUnsupportedError(
            f"{doc.name_of(before)!r} is a root object; the new object needs a parent object.",
            code="no_anchor",
            field=doc.name_of(before),
            offset=entry.offset,
        )
    object_entry = Meta2(string_hash(name), entry.offset, field_info(name, anchor_meta1))
    block, meta1, meta2 = _build_name_source_block(
        name.encode("utf-8") + b"\x00",
        wanted,
        data_start=entry.offset,
        object_meta1=anchor_meta1,
        object_meta2=before,
        parent_meta1=parent_meta1,
        object_entry=object_entry,
    )
    span = _Span(anchor_meta1, anchor_meta1, before, before)
    return _splice(doc, span, block, meta1, meta2, parent_meta1=parent_meta1, parent_direct_delta=1)


def patch_scalar_string(doc: DsonDocument, i: int, value: str) -> DsonDocument:
    """Replace scalar field ``i`` with a string payload (port of dd2.py:937-1009).

    The meta2 record is rebuilt from ``field_info(name)`` like the legacy helper did (a set bit 31
    is dropped), no meta1 record changes, and later fields are rebuilt for their new offsets.
    """
    entry = _entry(doc, i)
    if entry.is_object:
        raise DsonFormatError(
            f"{doc.name_of(i)!r} is an object field, not a scalar string field.",
            code="not_a_scalar",
            offset=entry.offset,
        )
    name = doc.name_of(i)
    block = build_string_field(name, value, entry.offset)
    meta2 = [Meta2(string_hash(name), entry.offset, field_info(name))]
    parent = _parent_map(doc)[i]
    parent_meta1 = doc.meta2[parent].object_index if parent >= 0 else None
    span = _Span(0, 0, i, i + 1)
    return _splice(
        doc,
        span,
        block,
        (),
        meta2,
        parent_meta1=-1 if parent_meta1 is None else parent_meta1,
        parent_direct_delta=0,
    )


def read_scalars(raw: bytes, names: Collection[str]) -> dict[str, DsonScalar]:
    """Decode the scalar fields called ``names`` (replaces dd2.py:2740 ``read_scalar_dson_fields``).

    Raises :class:`DsonFormatError` on an invalid save instead of returning ``{}``.  Like the
    legacy, a name that occurs several times yields its last occurrence; object fields are skipped.
    """
    doc = parse(raw)
    wanted = set(names)
    out: dict[str, DsonScalar] = {}
    if not wanted:
        return out
    for i, entry in enumerate(doc.meta2):
        if entry.is_object:
            continue
        name = doc.name_of(i)
        if name in wanted:
            out[name] = decode_scalar(doc.data, entry, doc.field_end(i))
    return out
