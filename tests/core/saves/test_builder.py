"""The builder is the independent reference: prove it by hand, and against src."""

import itertools
import struct

import pytest

from src.core.saves import dson
from tests.support.dson_builder import (
    ANCHOR_BLOCK,
    APPLIED_BLOCK,
    DSON_MAGIC,
    THREE_ENTRIES,
    TINY_ROOT,
    build_save,
    find_layout,
    layout,
    sample_variants,
    standard_root,
    standard_save,
)

VARIANTS = sample_variants()
# Structurally valid (STRUCTURAL ignores magic and payload bytes); STRICT may disagree.
STRUCTURAL_ONLY_VARIANTS = {
    "nonzero_padding": standard_save(THREE_ENTRIES, pad_byte=0xFF),
    "zero_magic": build_save(standard_root(THREE_ENTRIES), magic=b"\x00\x00\x00\x00"),
}


def test_tiny_save_bytes_by_hand() -> None:
    raw = build_save(TINY_ROOT, filler=0xAA)
    header = bytearray([0xAA] * 64)
    header[0:4] = DSON_MAGIC
    header[4:8] = b"\x00\x00\x00\x00"
    numbers = ((8, 64), (16, 32), (20, 2), (24, 64), (44, 4), (48, 96), (56, 19), (60, 144))
    for at, value in numbers:
        struct.pack_into("<i", header, at, value)
    meta1 = struct.pack("<iiii", -1, 0, 2, 3) + struct.pack("<iiii", 0, 2, 1, 1)
    meta2 = (
        struct.pack("<iii", 114, 0, (2 << 2) | 1)  # "r": object, meta1 index 0
        + struct.pack("<iii", 98, 2, 2 << 2)  # "b": one unaligned bool byte
        + struct.pack("<iii", 99, 5, (2 << 2) | 1 | (1 << 11))  # "c": object, meta1 index 1
        + struct.pack("<iii", 97 * 53 + 98, 7, 3 << 2)  # "ab": string, padded to offset 12
    )
    data = b"r\x00b\x00\x01c\x00ab\x00\x00\x00" + struct.pack("<i", 3) + b"xy\x00"
    assert raw == bytes(header) + meta1 + meta2 + data
    assert len(raw) == 163


@pytest.mark.parametrize("filler", [0xAA, 0x00, 0x5C])
def test_unknown_header_bytes_carry_the_filler(filler: int) -> None:
    raw = build_save(TINY_ROOT, filler=filler)
    assert raw[12:16] == bytes([filler]) * 4
    assert raw[28:44] == bytes([filler]) * 16
    assert raw[52:56] == bytes([filler]) * 4


def test_layout_matches_the_emitted_meta2() -> None:
    root = standard_root(THREE_ENTRIES)
    raw = build_save(root)
    data_offset = struct.unpack_from("<i", raw, 60)[0]
    meta2_offset = struct.unpack_from("<i", raw, 48)[0]
    data = raw[data_offset:]
    layouts = layout(root)
    assert [entry.meta2_index for entry in layouts] == list(range(len(layouts)))
    for entry in layouts:
        offset = struct.unpack_from("<i", raw, meta2_offset + 12 * entry.meta2_index + 4)[0]
        assert offset == entry.offset
        name = entry.path[-1].encode("utf-8") + b"\x00"
        assert data[entry.offset : entry.offset + len(name)] == name
        assert entry.payload_start == entry.offset + len(name)
    for current, following in itertools.pairwise(layouts):
        assert current.payload_end == following.offset
    assert layouts[-1].payload_end == len(data)
    assert find_layout(layouts, "base_root", "inraid").region_size == 1
    assert find_layout(layouts, "base_root", "dlc").region_size == 0


def test_standard_root_keeps_applied_and_anchor_adjacent() -> None:
    root = standard_root(THREE_ENTRIES)
    layouts = layout(root)
    applied = find_layout(layouts, "base_root", APPLIED_BLOCK)
    anchor = find_layout(layouts, "base_root", ANCHOR_BLOCK)
    assert anchor.meta2_index == applied.meta2_index + 1 + 3 * len(THREE_ENTRIES)
    raw = build_save(root)
    data = raw[struct.unpack_from("<i", raw, 60)[0] :]
    # a block name must follow a NUL to be found by a byte scan
    assert data[applied.offset - 1] == 0
    assert data[anchor.offset - 1] == 0


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_variants_pass_src_validate_at_both_levels(name: str) -> None:
    report = dson.validate(VARIANTS[name])
    assert report.structural_errors == ()
    assert report.strict_errors == ()
    assert report.ok
    assert report.ok_strict


@pytest.mark.parametrize("name", sorted(STRUCTURAL_ONLY_VARIANTS))
def test_structural_only_variants_pass_src_validate_at_structural_level(name: str) -> None:
    report = dson.validate(STRUCTURAL_ONLY_VARIANTS[name])
    assert report.structural_errors == ()
    assert report.ok
