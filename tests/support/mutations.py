"""Byte-level surgery on built saves: strict-only and refusal inputs, independent of ``src``.

Every helper edits the tables with ``struct`` and the header offsets alone, so each result is what
a differently-behaved writer could have produced rather than anything the codec would build.  All
of them keep the file STRUCTURAL-valid (the validator accepts it); the docstrings name the
STRICT problem each one provokes.
"""

import struct
from collections.abc import Iterable

from tests.support.dson_builder import (
    HEADER_SIZE,
    META1_SIZE,
    META2_SIZE,
    FieldLayout,
    field_info,
    string_hash,
)

_OBJECT_INDEX_BITS = 0xFFFFF << 11


def _i32(raw: bytes | bytearray, at: int) -> int:
    return struct.unpack_from("<i", raw, at)[0]


def _signed(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def with_i32(raw: bytes, at: int, value: int) -> bytes:
    out = bytearray(raw)
    struct.pack_into("<i", out, at, value)
    return bytes(out)


def bump_root_all_children(raw: bytes, delta: int = 1) -> bytes:
    """Root ``all_children`` off by ``delta``: STRUCTURAL never checks it (STRICT-only)."""
    at = HEADER_SIZE + 12
    return with_i32(raw, at, _i32(raw, at) + delta)


def swap_meta1_records(raw: bytes, a: FieldLayout, b: FieldLayout) -> bytes:
    """Swap the meta1 records of two objects and re-point their meta2 infos at the new slots.

    Each record still describes its object (parent, meta2 index and counts travel with it) and the
    STRUCTURAL validator compares parents with running object numbers, so it accepts the result;
    only the meta1 ORDER no longer follows the field order (STRICT ``meta1_order``).  Records of
    other objects that name ``a`` or ``b`` as their parent are left alone on purpose.
    """
    assert a.meta1_index is not None and b.meta1_index is not None
    out = bytearray(raw)
    meta2_offset = _i32(raw, 48)
    at_a = HEADER_SIZE + META1_SIZE * a.meta1_index
    at_b = HEADER_SIZE + META1_SIZE * b.meta1_index
    out[at_a : at_a + META1_SIZE] = raw[at_b : at_b + META1_SIZE]
    out[at_b : at_b + META1_SIZE] = raw[at_a : at_a + META1_SIZE]
    for field, new_index in ((a, b.meta1_index), (b, a.meta1_index)):
        at = meta2_offset + META2_SIZE * field.meta2_index + 8
        info = _i32(raw, at) & ~_OBJECT_INDEX_BITS
        struct.pack_into("<i", out, at, _signed(info | (new_index << 11)))
    return bytes(out)


def duplicate_meta2_record(raw: bytes, field: FieldLayout) -> bytes:
    """Insert a second copy of a root-level scalar's meta2 record right after it (same offset).

    The root gains one direct child and one descendant, later objects' meta2 indices move up by
    one and the header grows by one record.  Equal offsets are "sorted" for STRUCTURAL, which
    accepts the file (STRICT ``offsets_not_increasing``).
    """
    assert field.meta1_index is None and len(field.path) == 2
    meta1_count, meta2_count = _i32(raw, 20), _i32(raw, 44)
    meta2_offset, data_offset = _i32(raw, 48), _i32(raw, 60)
    at = meta2_offset + META2_SIZE * field.meta2_index
    out = bytearray(raw[: at + META2_SIZE] + raw[at : at + META2_SIZE] + raw[at + META2_SIZE :])
    struct.pack_into("<i", out, 44, meta2_count + 1)
    struct.pack_into("<i", out, 60, data_offset + META2_SIZE)
    for k in range(meta1_count):
        record = HEADER_SIZE + META1_SIZE * k
        meta2_index = _i32(out, record + 4)
        if meta2_index > field.meta2_index:
            struct.pack_into("<i", out, record + 4, meta2_index + 1)
    struct.pack_into("<i", out, HEADER_SIZE + 8, _i32(out, HEADER_SIZE + 8) + 1)
    struct.pack_into("<i", out, HEADER_SIZE + 12, _i32(out, HEADER_SIZE + 12) + 1)
    return bytes(out)


def with_second_root(raw: bytes, name: str) -> bytes:
    """Append a second top-level object (parent -1) after the first root's subtree.

    The structural walk lets a new object open once the root has closed and only requires its parent
    to be -1, so the file stays structurally valid (STRICT ``root_count``).
    """
    meta1_count, meta2_count = _i32(raw, 20), _i32(raw, 44)
    meta1_offset, meta2_offset = _i32(raw, 24), _i32(raw, 48)
    data_offset, data_length = _i32(raw, 60), _i32(raw, 56)
    data = raw[data_offset : data_offset + data_length]
    meta1 = raw[meta1_offset:meta2_offset] + struct.pack("<iiii", -1, meta2_count, 0, 0)
    meta2 = raw[meta2_offset:data_offset] + struct.pack(
        "<iii", string_hash(name), len(data), field_info(name, meta1_count)
    )
    data += name.encode("utf-8") + b"\x00"
    header = bytearray(raw[:HEADER_SIZE])
    for at, value in (
        (16, len(meta1)),
        (20, meta1_count + 1),
        (44, meta2_count + 1),
        (48, HEADER_SIZE + len(meta1)),
        (56, len(data)),
        (60, HEADER_SIZE + len(meta1) + len(meta2)),
    ):
        struct.pack_into("<i", header, at, value)
    return bytes(header) + meta1 + meta2 + data


def set_info_bit31(raw: bytes, meta2_indices: Iterable[int], *, on: bool) -> bytes:
    """Set (``on``) or clear bit 31 of the info word of the given meta2 records, nothing else.

    Bit 31 is outside every field of the format, so the STRUCTURAL validator is blind to
    it; this is how a test states "the same file, with the unknown flag flipped here".
    """
    meta2_offset = _i32(raw, 48)
    out = bytearray(raw)
    for k in meta2_indices:
        at = meta2_offset + META2_SIZE * k + 8
        info = _i32(raw, at) & 0x7FFFFFFF
        struct.pack_into("<i", out, at, _signed(info | 0x80000000 if on else info))
    return bytes(out)


def info_bit31_indices(raw: bytes) -> frozenset[int]:
    """The meta2 indices whose info word has bit 31 set, read with ``struct`` alone."""
    meta2_count, meta2_offset = _i32(raw, 44), _i32(raw, 48)
    return frozenset(
        k for k in range(meta2_count) if _i32(raw, meta2_offset + META2_SIZE * k + 8) < 0
    )


def or_object_infos(raw: bytes, mask: int) -> bytes:
    """OR ``mask`` into the info word of every object field (spare bits the format never reads).

    Bit 1 and bit 31 are outside the name-length / object-index / is-object fields, so the
    STRUCTURAL validator accepts the file and STRICT has nothing to say either.
    """
    meta2_count, meta2_offset = _i32(raw, 44), _i32(raw, 48)
    out = bytearray(raw)
    for k in range(meta2_count):
        at = meta2_offset + META2_SIZE * k + 8
        info = _i32(raw, at)
        if info & 1:
            struct.pack_into("<i", out, at, _signed(info | mask))
    return bytes(out)
