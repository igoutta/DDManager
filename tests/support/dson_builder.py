"""Independent DSON builder: build binary Darkest Dungeon saves from a small node tree.

This module is the test-side ground truth for the byte format and shares NO code with ``src``.
Every rule below comes from the format description, never from the codec under test:

* header, 64 bytes: magic[0:4], revision[4:8], i32 header_length@8 (64), i32 meta1_size@16,
  i32 meta1_count@20, i32 meta1_offset@24 (64), i32 meta2_count@44, i32 meta2_offset@48,
  i32 data_length@56, i32 data_offset@60. Bytes 12-15, 28-43 and 52-55 are unknown and are
  filled with ``filler`` so pass-through is provable;
* meta1, one 16-byte ``<iiii`` record per OBJECT in pre-order: parent meta1 index (-1 for the
  root), meta2 index, direct child count, count of ALL descendant fields;
* meta2, one 12-byte ``<iii`` record per FIELD in data order: name hash, offset of the name
  relative to the data block, info = (name_length_incl_nul << 2) | is_object | (meta1_index << 11);
* name hash: h = h * 53 + byte over the UTF-8 bytes, masked to 32 bits, then signed;
* data: each field starts with its NUL-terminated name; objects carry no payload; a 1-byte
  payload (bool) follows the name immediately; any other payload is padded to the next 4-byte
  boundary relative to the data block; strings are i32 length (incl. NUL) + UTF-8 + NUL; ints
  are 4-byte little-endian;
* bit 31 of info is an unknown flag the game sets on some fields; ``build_save(..., flag31=)``
  sets it on the meta2 words whose index the predicate accepts.
"""

import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass

DSON_MAGIC = b"\x01\xb1\x00\x00"
ZERO_REVISION = b"\x00\x00\x00\x00"
HEADER_SIZE = 64
META1_SIZE = 16
META2_SIZE = 12
INFO_FLAG_BIT = 0x80000000

type Flag31 = Callable[[int], bool]
"""Called with a meta2 index; ``True`` sets bit 31 of that field's info word."""

APPLIED_BLOCK = "applied_ugcs_1_0"
ANCHOR_BLOCK = "persistent_ugcs"
STEAM = "Steam"
LOCAL = "mod_local_source"


@dataclass(frozen=True, slots=True)
class O:  # noqa: E742 - the spec names the node types O/S/B/I/R
    """An object field: no payload, its children follow in pre-order."""

    name: str
    children: Sequence[Node] = ()


@dataclass(frozen=True, slots=True)
class S:
    """A string field: i32 length including the NUL, UTF-8 bytes, NUL (4-byte aligned)."""

    name: str
    value: str


@dataclass(frozen=True, slots=True)
class B:
    """A bool field: one byte written immediately after the name (unaligned)."""

    name: str
    value: bool


@dataclass(frozen=True, slots=True)
class I:  # noqa: E742 - the spec names the node types O/S/B/I/R
    """A 32-bit little-endian signed int field (4-byte aligned)."""

    name: str
    value: int


@dataclass(frozen=True, slots=True)
class R:
    """An opaque payload: 1 byte is unaligned, 0 bytes is nothing, otherwise 4-byte aligned."""

    name: str
    payload: bytes


type Node = O | S | B | I | R
type Entry = tuple[str, str]


@dataclass(frozen=True, slots=True)
class FieldLayout:
    """Where one field landed in the data block (all offsets relative to the data block)."""

    path: tuple[str, ...]
    meta2_index: int
    meta1_index: int | None
    offset: int
    payload_start: int  # first byte after the NUL of the name (padding, if any, starts here)
    payload_end: int  # next field's offset, or the end of the data block

    @property
    def region_size(self) -> int:
        return self.payload_end - self.payload_start


def string_hash(name: str) -> int:
    value = 0
    for byte in name.encode("utf-8"):
        value = (value * 53 + byte) & 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def field_info(name: str, meta1_index: int | None, *, flag31: bool = False) -> int:
    info = (len(name.encode("utf-8")) + 1) << 2
    if meta1_index is not None:
        info |= 1 | (meta1_index << 11)
    if flag31:
        info |= INFO_FLAG_BIT
    return info - 0x100000000 if info >= 0x80000000 else info


def _payload(node: S | B | I | R) -> bytes:
    if isinstance(node, S):
        value = node.value.encode("utf-8") + b"\x00"
        return struct.pack("<i", len(value)) + value
    if isinstance(node, B):
        return b"\x01" if node.value else b"\x00"
    if isinstance(node, I):
        return struct.pack("<i", node.value)
    return node.payload


class _Emitter:
    def __init__(self, pad_byte: int, flag31: Flag31 | None) -> None:
        self.pad_byte = pad_byte
        self.flag31 = flag31
        self.data = bytearray()
        self.meta1: list[list[int]] = []
        self.meta2: list[tuple[int, int, int]] = []
        self.layouts: list[FieldLayout] = []

    def emit(self, node: Node, parent_meta1: int, path: tuple[str, ...]) -> None:
        offset = len(self.data)
        meta2_index = len(self.meta2)
        name_bytes = node.name.encode("utf-8") + b"\x00"
        flagged = self.flag31 is not None and self.flag31(meta2_index)
        if isinstance(node, O):
            meta1_index = len(self.meta1)
            record = [parent_meta1, meta2_index, 0, 0]
            self.meta1.append(record)
            info = field_info(node.name, meta1_index, flag31=flagged)
            self.meta2.append((string_hash(node.name), offset, info))
            self.data += name_bytes
            slot = len(self.layouts)
            first_child_meta2 = len(self.meta2)
            for child in node.children:
                self.emit(child, meta1_index, (*path, child.name))
            record[2] = len(node.children)
            record[3] = len(self.meta2) - first_child_meta2
            after_name = offset + len(name_bytes)
            self.layouts.insert(
                slot, FieldLayout(path, meta2_index, meta1_index, offset, after_name, after_name)
            )
            return
        info = field_info(node.name, None, flag31=flagged)
        self.meta2.append((string_hash(node.name), offset, info))
        self.data += name_bytes
        payload = _payload(node)
        if len(payload) > 1:
            self.data += bytes([self.pad_byte]) * (-len(self.data) % 4)
        self.data += payload
        self.layouts.append(
            FieldLayout(path, meta2_index, None, offset, offset + len(name_bytes), len(self.data))
        )


def _emit(root: O, pad_byte: int, flag31: Flag31 | None = None) -> _Emitter:
    emitter = _Emitter(pad_byte, flag31)
    emitter.emit(root, -1, (root.name,))
    return emitter


def build_save(
    root: O,
    *,
    magic: bytes = DSON_MAGIC,
    revision: bytes = ZERO_REVISION,
    filler: int = 0xAA,
    pad_byte: int = 0,
    flag31: Flag31 | None = None,
) -> bytes:
    """Serialize ``root`` as a complete DSON file (header + meta1 + meta2 + data).

    ``flag31(meta2_index)`` picks the info words that get bit 31 set (none by default); the
    layout is the same either way, so ``layout(root)`` still says where every field is.
    """
    if len(magic) != 4 or len(revision) != 4:
        raise ValueError("magic and revision are 4 bytes each")
    emitter = _emit(root, pad_byte, flag31)
    meta1_count, meta2_count = len(emitter.meta1), len(emitter.meta2)
    meta2_offset = HEADER_SIZE + META1_SIZE * meta1_count
    data_offset = meta2_offset + META2_SIZE * meta2_count
    header = bytearray([filler] * HEADER_SIZE)
    header[0:4] = magic
    header[4:8] = revision
    for at, value in (
        (8, HEADER_SIZE),
        (16, META1_SIZE * meta1_count),
        (20, meta1_count),
        (24, HEADER_SIZE),
        (44, meta2_count),
        (48, meta2_offset),
        (56, len(emitter.data)),
        (60, data_offset),
    ):
        struct.pack_into("<i", header, at, value)
    meta1 = b"".join(struct.pack("<iiii", *record) for record in emitter.meta1)
    meta2 = b"".join(struct.pack("<iii", *record) for record in emitter.meta2)
    return bytes(header) + meta1 + meta2 + bytes(emitter.data)


def layout(root: O, *, pad_byte: int = 0) -> tuple[FieldLayout, ...]:
    """Pre-order layout of every field, as ``build_save`` would place it."""
    return tuple(_emit(root, pad_byte).layouts)


def find_layout(layouts: Sequence[FieldLayout], *path: str) -> FieldLayout:
    for entry in layouts:
        if entry.path == path:
            return entry
    raise KeyError("/".join(path))


# ---------------------------------------------------------------- realistic save skeleton


def name_source_object(name: str, entries: Sequence[Entry]) -> O:
    """``name: {"0": {name, source}, "1": {...}, ...}`` - the applied_ugcs_1_0 / dlc shape."""
    return O(
        name,
        [O(str(k), [S("name", n), S("source", s)]) for k, (n, s) in enumerate(entries)],
    )


def applied_object(entries: Sequence[Entry]) -> O:
    return name_source_object(APPLIED_BLOCK, entries)


DLC_OBJECT = name_source_object("dlc", [("crimson_court", "dlc")])
PERSISTENT_OBJECT = name_source_object(ANCHOR_BLOCK, [("1234567890", STEAM)])
TAIL_NODES: tuple[Node, ...] = (
    B("never_again", False),
    I("tail_int", 0x7FFFFFFF),
    O("nested", [S("x", "nested value"), B("b", True), I("z", -7)]),
)


def standard_root(
    applied: Sequence[Entry] | None,
    *,
    extra_after: bool = True,
    before_applied: Sequence[Node] = (),
    between: Sequence[Node] = (),
    after_persistent: Sequence[Node] = (),
) -> O:
    """A realistic ``base_root``.

    Field order: version:I, estatename:S, inraid:B, raiddungeon:S, dlc:O, ``before_applied``,
    applied_ugcs_1_0 (omitted when ``applied`` is None), ``between``, persistent_ugcs,
    ``after_persistent``, then (when ``extra_after``) never_again:B, tail_int:I,
    nested:O{x:S, b:B, z:I}.

    A byte scan only finds a block name preceded by a NUL, so ``before_applied`` should end in a
    NUL-terminated payload (an S or an O) when one is used.  ``between`` is the one place
    where nothing resets the alignment between the applied block and a later field, so it is
    where realignment can be observed.
    """
    children: list[Node] = [
        I("version", 5),
        S("estatename", "Hamlet"),
        B("inraid", True),
        S("raiddungeon", "crypts"),
        DLC_OBJECT,
        *before_applied,
    ]
    if applied is not None:
        children.append(applied_object(applied))
    children.extend(between)
    children.append(PERSISTENT_OBJECT)
    children.extend(after_persistent)
    if extra_after:
        children.extend(TAIL_NODES)
    return O("base_root", children)


def standard_save(
    applied: Sequence[Entry] | None,
    *,
    extra_after: bool = True,
    before_applied: Sequence[Node] = (),
    between: Sequence[Node] = (),
    after_persistent: Sequence[Node] = (),
    pad_byte: int = 0,
) -> bytes:
    return build_save(
        standard_root(
            applied,
            extra_after=extra_after,
            before_applied=before_applied,
            between=between,
            after_persistent=after_persistent,
        ),
        pad_byte=pad_byte,
    )


THREE_ENTRIES: tuple[Entry, ...] = (
    ("1234567890", STEAM),
    ("Local Mod", LOCAL),
    ("99", STEAM),
)

# Small enough to check byte by byte by hand (see tests/core/saves/test_builder.py).
TINY_ROOT = O("r", [B("b", True), O("c", [S("ab", "xy")])])

DEEP_ROOT = O(
    "base_root",
    [
        O(
            "a",
            [
                O("b", [O("c", [S("s", "x"), B("b", True)]), I("i", 1)]),
                R("r", bytes(range(8))),
                O("empty", []),
            ],
        ),
        S("t", "end"),
    ],
)


def sample_variants() -> dict[str, bytes]:
    """Well-formed saves that every validator level must accept."""
    return {
        "no_applied": standard_save(None),
        "empty_applied": standard_save([]),
        "three": standard_save(THREE_ENTRIES),
        "no_tail": standard_save(THREE_ENTRIES, extra_after=False),
        "cjk": standard_save([("测试模组", LOCAL), ("42", STEAM)]),
        "deep": build_save(DEEP_ROOT),
        "zero_filler": build_save(standard_root(THREE_ENTRIES), filler=0x00),
        "forty": standard_save([(f"{k * 7919}", STEAM) for k in range(40)]),
    }
