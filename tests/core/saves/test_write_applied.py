"""DsonV1Format.write_applied: legacy byte parity, round trips, insert placement and refusals."""

import struct
from collections.abc import Sequence

import pytest

from src.core.errors import DsonFormatError, DsonUnsupportedError, RoundTripError
from src.core.saves import dson
from src.core.saves.dson import Meta1
from src.core.saves.dson_v1 import DsonV1Format
from tests.support import parity_matrix as pm
from tests.support.dson_builder import (
    ANCHOR_BLOCK,
    APPLIED_BLOCK,
    DLC_OBJECT,
    LOCAL,
    PERSISTENT_OBJECT,
    STEAM,
    TAIL_NODES,
    THREE_ENTRIES,
    Entry,
    I,
    Node,
    O,
    R,
    S,
    applied_object,
    build_save,
    find_layout,
    layout,
    sample_variants,
    standard_root,
    standard_save,
)
from tests.support.identities import identities
from tests.support.mutations import bump_root_all_children, swap_meta1_records
from tools.legacy_oracle import LegacyOracle

FMT = DsonV1Format()
CASE_IDS = [pm.case_id(n, m) for n, m in pm.CASES]


def test_format_descriptor() -> None:
    assert FMT.format_id == "dson.v1"
    assert FMT.writable is True
    assert FMT.applied_block == APPLIED_BLOCK
    assert FMT.anchor_block == ANCHOR_BLOCK
    # class constants, not dataclass fields: a format cannot be constructed with another identity
    assert DsonV1Format.format_id == "dson.v1"
    assert DsonV1Format.applied_block == APPLIED_BLOCK
    with pytest.raises(TypeError):
        DsonV1Format(format_id="zzz")  # ty: ignore[unknown-argument]


def _span(entries: Sequence[Entry] | None) -> int:
    """Size of the applied block for ``entries`` at its standard start offset (builder layout)."""
    if entries is None:
        return 0
    layouts = layout(standard_root(entries))
    anchor = find_layout(layouts, "base_root", ANCHOR_BLOCK)
    return anchor.offset - find_layout(layouts, "base_root", APPLIED_BLOCK).offset


# ---------------------------------------------------------------- parity with the pinned legacy


@pytest.mark.legacy
@pytest.mark.parametrize(("n", "m"), pm.CASES, ids=CASE_IDS)
def test_parity_matrix_against_legacy_patcher(legacy: LegacyOracle, n: int | None, m: int) -> None:
    dd2 = legacy.module("dd2")
    raw = pm.build_input(n)
    entries = pm.new_entries(m)
    keys, table = pm.stub_identities(entries)
    try:
        expected, count = dd2.dson_patch_mod_list_resize(raw, keys, legacy.stub_manager(table))
    except Exception as exc:  # noqa: BLE001 - the legacy raises plain ValueError/IndexError
        assert (n, m) in pm.EXPECTED_DIVERGENCE, f"new legacy divergence: {exc!r}"
        out = FMT.write_applied(raw, identities(entries))
        assert FMT.read_applied(out) == identities(entries)
        return
    assert (n, m) not in pm.EXPECTED_DIVERGENCE, "legacy no longer raises; prune the set"
    assert count == m
    assert FMT.write_applied(raw, identities(entries)) == expected


def test_matrix_covers_every_residue_mod_4_and_stays_strict_valid() -> None:
    """The residues come from the independent builder layout, not from the codec under test."""
    residues: set[int] = set()
    for n, m in pm.CASES:
        out = FMT.write_applied(pm.build_input(n), identities(pm.new_entries(m)))
        assert dson.validate(out).ok_strict, (n, m)
        residues.add((_span(pm.new_entries(m)) - _span(pm.existing_entries(n))) % 4)
    assert residues == {0, 1, 2, 3}


def _start_residue_inputs() -> list[tuple[str, int | None, bytes, int]]:
    """Saves whose applied block (or, without one, the anchor) starts at every residue mod 4.

    A string ``p`` of k bytes before the block ends k+1 bytes after its 4-aligned length prefix,
    so k = 0..3 walks the start offset through all four residues.
    """
    out: list[tuple[str, int | None, bytes, int]] = []
    for k in range(4):
        for n in (None, 3):
            root = standard_root(pm.existing_entries(n), before_applied=(S("p", "x" * k),))
            block = ANCHOR_BLOCK if n is None else APPLIED_BLOCK
            start = find_layout(layout(root), "base_root", block).offset
            out.append((f"k{k}_N{'none' if n is None else n}", n, build_save(root), start % 4))
    return out


START_RESIDUE_INPUTS = _start_residue_inputs()


def test_start_residue_inputs_cover_every_residue() -> None:
    assert {residue for _, _, _, residue in START_RESIDUE_INPUTS} == {0, 1, 2, 3}


@pytest.mark.parametrize("m", (0, 2, 5))
@pytest.mark.parametrize(
    ("n", "raw"),
    [(n, raw) for _, n, raw, _ in START_RESIDUE_INPUTS],
    ids=[name for name, _, _, _ in START_RESIDUE_INPUTS],
)
def test_rewrite_at_every_start_residue(n: int | None, raw: bytes, m: int) -> None:
    ids = identities(pm.new_entries(m))
    out = FMT.write_applied(raw, ids)
    assert FMT.read_applied(out) == ids
    assert dson.validate(out).ok_strict


@pytest.mark.legacy
@pytest.mark.parametrize("m", (0, 2, 5))
@pytest.mark.parametrize(
    "raw",
    [raw for _, _, raw, _ in START_RESIDUE_INPUTS],
    ids=[name for name, _, _, _ in START_RESIDUE_INPUTS],
)
def test_parity_at_every_start_residue(legacy: LegacyOracle, raw: bytes, m: int) -> None:
    dd2 = legacy.module("dd2")
    entries = pm.new_entries(m)
    keys, table = pm.stub_identities(entries)
    expected, count = dd2.dson_patch_mod_list_resize(raw, keys, legacy.stub_manager(table))
    assert count == m
    assert FMT.write_applied(raw, identities(entries)) == expected


# ---------------------------------------------------------------- round trips

REWRITE_INPUTS = {
    **{pm.case_id(n, 0): pm.build_input(n) for n in (0, 1, 3, 7)},
    **{k: v for k, v in sample_variants().items() if k not in {"no_applied", "deep"}},
}


@pytest.mark.parametrize("name", sorted(REWRITE_INPUTS))
def test_rewrite_identity(name: str) -> None:
    raw = REWRITE_INPUTS[name]
    assert FMT.write_applied(raw, FMT.read_applied(raw)) == raw


SPECIAL = (
    ("测试模组", LOCAL),
    ("y" * 333, LOCAL),
    ("Épée \U0001f525", LOCAL),
    ("7", STEAM),
)


@pytest.mark.parametrize("m", pm.M_VALUES)
@pytest.mark.parametrize("n", pm.N_VALUES, ids=lambda n: f"N{'none' if n is None else n}")
def test_read_back_equals_written(n: int | None, m: int) -> None:
    ids = identities([*pm.new_entries(m), *SPECIAL])
    out = FMT.write_applied(pm.build_input(n), ids)
    assert FMT.read_applied(out) == ids
    assert dson.validate(out).ok_strict


def test_read_back_1200_entries() -> None:
    entries = [(f"{k}", STEAM) if k % 3 else (f"Local {k}", LOCAL) for k in range(1200)]
    ids = identities(entries)
    out = FMT.write_applied(standard_save(None), ids)
    assert FMT.read_applied(out) == ids
    assert FMT.write_applied(out, ids) == out


def test_empty_entries_are_allowed() -> None:
    for raw in (standard_save(THREE_ENTRIES), standard_save(None), standard_save([])):
        out = FMT.write_applied(raw, ())
        assert FMT.read_applied(out) == ()
        assert dson.validate(out).ok_strict
        doc = dson.parse(out)
        applied = doc.find_child(0, APPLIED_BLOCK)
        assert applied is not None
        index = doc.meta2[applied].object_index
        assert index is not None
        assert doc.meta1[index] == Meta1(0, applied, 0, 0)


# ---------------------------------------------------------------- insert / replace shapes


def test_insert_places_block_before_anchor_and_bumps_root() -> None:
    raw = standard_save(None)
    ids = identities(pm.new_entries(5))
    out = FMT.write_applied(raw, ids)
    before, after = dson.parse(raw), dson.parse(out)
    anchor_before = before.find_child(0, ANCHOR_BLOCK)
    applied = after.find_child(0, APPLIED_BLOCK)
    anchor_after = after.find_child(0, ANCHOR_BLOCK)
    assert anchor_before is not None and applied is not None and anchor_after is not None
    assert applied == anchor_before  # the block takes the anchor's meta2 slot
    assert anchor_after == applied + 1 + 3 * len(ids)
    assert after.field_offset(applied) == before.field_offset(anchor_before)
    assert after.meta1[0].direct_children == before.meta1[0].direct_children + 1
    assert after.meta1[0].all_children == before.meta1[0].all_children + 1 + 3 * len(ids)
    applied_m1 = after.meta2[applied].object_index
    assert applied_m1 == before.meta2[anchor_before].object_index
    assert applied_m1 is not None
    assert after.meta1[applied_m1] == Meta1(0, applied, len(ids), 3 * len(ids))
    for k, identity in enumerate(ids):
        child = applied + 1 + 3 * k
        assert after.name_of(child) == str(k)
        child_m1 = after.meta2[child].object_index
        assert child_m1 is not None
        assert after.meta1[child_m1] == Meta1(applied_m1, child, 2, 2)
        assert (after.name_of(child + 1), after.name_of(child + 2)) == ("name", "source")
        assert dson.read_name_source_object(after, applied)[k] == identity
    assert [after.name_of(i) for i in after.children[0]] == [
        *(before.name_of(i) for i in before.children[0][: anchor_before_position(before)]),
        APPLIED_BLOCK,
        *(before.name_of(i) for i in before.children[0][anchor_before_position(before) :]),
    ]
    assert dson.validate(out).ok_strict
    assert out[:8] == raw[:8]
    assert out[12:16] == raw[12:16] and out[28:44] == raw[28:44] and out[52:56] == raw[52:56]


def anchor_before_position(doc: dson.DsonDocument) -> int:
    anchor = doc.find_child(0, ANCHOR_BLOCK)
    assert anchor is not None
    return list(doc.children[0]).index(anchor)


def test_replace_rewrites_counts_and_ancestors() -> None:
    raw = standard_save(THREE_ENTRIES)
    ids = identities(pm.new_entries(12))
    out = FMT.write_applied(raw, ids)
    before, after = dson.parse(raw), dson.parse(out)
    applied = after.find_child(0, APPLIED_BLOCK)
    assert applied is not None and applied == before.find_child(0, APPLIED_BLOCK)
    applied_m1 = after.meta2[applied].object_index
    assert applied_m1 is not None
    assert after.meta1[applied_m1] == Meta1(0, applied, 12, 36)
    assert after.meta1[0].direct_children == before.meta1[0].direct_children
    assert after.meta1[0].all_children == before.meta1[0].all_children + 3 * (12 - 3)
    assert len(after.meta1) == len(before.meta1) + (12 - 3)
    assert len(after.meta2) == len(before.meta2) + 3 * (12 - 3)
    tail = [after.name_of(i) for i in after.children[0]]
    assert tail == [before.name_of(i) for i in before.children[0]]
    assert dson.read_scalars(out, ["tail_int", "never_again", "estatename"]) == {
        "tail_int": 0x7FFFFFFF,
        "never_again": False,
        "estatename": "Hamlet",
    }


# ---------------------------------------------------------------- refusals and divergences

NESTED_ONLY = build_save(
    O(
        "base_root",
        [
            I("version", 5),
            DLC_OBJECT,
            O("nested", [applied_object([("1", STEAM)])]),
            PERSISTENT_OBJECT,
            *TAIL_NODES,
        ],
    )
)
NO_ANCHOR = build_save(O("base_root", [I("version", 5), DLC_OBJECT, *TAIL_NODES]))
SCALAR_ANCHOR = build_save(
    O("base_root", [I("version", 5), DLC_OBJECT, S(ANCHOR_BLOCK, "not an object"), *TAIL_NODES])
)
SCALAR_APPLIED = build_save(
    O(
        "base_root",
        [I("version", 5), DLC_OBJECT, S(APPLIED_BLOCK, "oops"), PERSISTENT_OBJECT, *TAIL_NODES],
    )
)
APPLIED_WITHOUT_ANCHOR = build_save(
    O("base_root", [I("version", 5), DLC_OBJECT, applied_object(THREE_ENTRIES), *TAIL_NODES])
)
DECOY = standard_save(THREE_ENTRIES, before_applied=(S("decoy", APPLIED_BLOCK),))
NEW_IDS = identities(pm.new_entries(2))


def _nested_span_save() -> bytes:
    """THREE_ENTRIES with the meta1 records of applied child "2" and "nested" swapped.

    The applied block's descendants then sit at meta1 [4, 5, 9] instead of [4, 5, 6]; the legacy
    resize took min..max of them and corrupted the file, the codec refuses.
    """
    root = standard_root(THREE_ENTRIES)
    layouts = layout(root)
    child = find_layout(layouts, "base_root", APPLIED_BLOCK, "2")
    nested = find_layout(layouts, "base_root", "nested")
    return swap_meta1_records(build_save(root), child, nested)


NESTED_SPAN = _nested_span_save()

# input -> the DsonUnsupportedError reason code the service layer will match on
REFUSALS: dict[str, tuple[bytes, str]] = {
    "nested_only_applied": (NESTED_ONLY, "applied_not_at_root"),
    "no_anchor": (NO_ANCHOR, "no_anchor"),
    "scalar_anchor": (SCALAR_ANCHOR, "no_anchor"),
    "scalar_applied": (SCALAR_APPLIED, "applied_not_object"),
    "nested_object_span": (NESTED_SPAN, "nested_object_span"),
}


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_refuses_layouts_it_cannot_patch_safely(name: str) -> None:
    raw, code = REFUSALS[name]
    report = dson.validate(raw)
    assert report.ok
    if name == "nested_object_span":
        assert [p.code for p in report.strict_errors] == ["meta1_order", "meta1_order"]
    else:
        assert report.ok_strict
    with pytest.raises(DsonUnsupportedError) as info:
        FMT.write_applied(raw, NEW_IDS)
    assert info.value.code == code
    assert info.value.details["code"] == code
    assert type(info.value).family == "dson_unsupported"


def test_nested_only_applied_block_is_not_read_as_the_root_list() -> None:
    assert FMT.read_applied(NESTED_ONLY) == ()


def test_scalar_applied_block_is_refused_by_read_and_write_alike() -> None:
    with pytest.raises(DsonUnsupportedError) as info:
        FMT.read_applied(SCALAR_APPLIED)
    assert info.value.code == "applied_not_object"


def test_nested_span_input_still_reads() -> None:
    assert FMT.read_applied(NESTED_SPAN) == identities(THREE_ENTRIES)


@pytest.mark.legacy
def test_legacy_patches_the_nested_block_instead(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    keys, table = pm.stub_identities(pm.new_entries(2))
    patched, count = dd2.dson_patch_mod_list_resize(NESTED_ONLY, keys, legacy.stub_manager(table))
    assert count == 2
    doc = dson.parse(patched)
    assert doc.find_child(0, APPLIED_BLOCK) is None
    assert doc.find_anywhere(APPLIED_BLOCK) is not None


@pytest.mark.legacy
@pytest.mark.parametrize(
    "raw", [NESTED_SPAN, SCALAR_APPLIED], ids=["nested_object_span", "scalar_applied"]
)
def test_legacy_raises_where_the_codec_refuses(legacy: LegacyOracle, raw: bytes) -> None:
    dd2 = legacy.module("dd2")
    keys, table = pm.stub_identities(pm.new_entries(2))
    with pytest.raises(ValueError):
        dd2.dson_patch_mod_list_resize(raw, keys, legacy.stub_manager(table))


def test_replace_does_not_need_the_anchor() -> None:
    out = FMT.write_applied(APPLIED_WITHOUT_ANCHOR, NEW_IDS)
    assert FMT.read_applied(out) == NEW_IDS
    assert dson.validate(out).ok_strict


def test_decoy_string_value_is_ignored_by_the_path_lookup() -> None:
    out = FMT.write_applied(DECOY, NEW_IDS)
    assert FMT.read_applied(out) == NEW_IDS
    assert dson.read_scalars(out, ["decoy"]) == {"decoy": APPLIED_BLOCK}
    assert dson.validate(out).ok_strict


@pytest.mark.legacy
@pytest.mark.parametrize(
    "raw", [DECOY, APPLIED_WITHOUT_ANCHOR], ids=["decoy_value", "applied_without_anchor"]
)
def test_legacy_heuristic_scanner_fails_where_core_succeeds(
    legacy: LegacyOracle, raw: bytes
) -> None:
    dd2 = legacy.module("dd2")
    keys, table = pm.stub_identities(pm.new_entries(2))
    with pytest.raises(ValueError):
        dd2.dson_patch_mod_list_resize(raw, keys, legacy.stub_manager(table))


# ---------------------------------------------------------------- the realignment guard


def _shifting_entries(existing: Sequence[Entry] | None) -> tuple[Entry, ...]:
    """New entries whose block size differs from the old one by a non-multiple of 4."""
    old = _span(existing)
    for m in (1, 2, 3, 5):
        candidate = pm.new_entries(m)
        if (_span(candidate) - old) % 4:
            return candidate
    raise AssertionError("no candidate shifts the alignment")


def _non_shifting_entries(existing: Sequence[Entry] | None) -> tuple[Entry, ...]:
    """New entries whose block size differs from the old one by a NON-ZERO multiple of 4."""
    old = _span(existing)
    for m in range(len(pm.M_VALUES) + 8):
        candidate = pm.new_entries(m)
        delta = _span(candidate) - old
        if delta and delta % 4 == 0:
            return candidate
    raise AssertionError("no candidate keeps the alignment")


def _region(raw: bytes, name: str) -> bytes:
    """The bytes between the NUL of root field ``name`` and the next field."""
    doc = dson.parse(raw)
    i = doc.find_child(0, name)
    assert i is not None
    entry = doc.meta2[i]
    return doc.data[entry.offset + entry.name_length : doc.field_end(i)]


def _short_field(payload: bytes) -> tuple[Node, ...]:
    """A field after the anchor whose payload starts on a 4-byte boundary (no padding)."""
    for name in ("q", "qq", "qqq", "qqqq"):
        nodes: tuple[Node, ...] = (R(name, payload), S("guard", "g"))
        root = standard_root(THREE_ENTRIES, after_persistent=nodes)
        probe = find_layout(layout(root), "base_root", name)
        if probe.payload_start % 4 == 0:
            assert probe.region_size == len(payload)
            return nodes
    raise AssertionError("no candidate name lands the payload on a 4-byte boundary")


def _between_probe(payload: bytes, *, padded: bool) -> tuple[Node, ...]:
    """``R(name, payload)`` between the applied block and the anchor.

    ``padded`` picks a name that puts the payload behind 1-3 zero padding bytes (the raw region is
    longer than the aligned payload) instead of right on a 4-byte boundary.
    """
    for name in ("q", "qq", "qqq", "qqqq"):
        nodes: tuple[Node, ...] = (R(name, payload),)
        probe = find_layout(layout(standard_root(THREE_ENTRIES, between=nodes)), "base_root", name)
        if (probe.payload_start % 4 != 0) == padded:
            return nodes
    raise AssertionError("no candidate name gives that padding")


SHORT_PAYLOADS = [b"", b"\x01\x02", b"\x01\x02\x03"]
SHORT_IDS = ["0_bytes", "2_bytes", "3_bytes"]


@pytest.mark.parametrize("payload", SHORT_PAYLOADS, ids=SHORT_IDS)
def test_short_payloads_after_the_anchor_are_never_realigned(payload: bytes) -> None:
    """persistent_ugcs ends in a string whose i32 + "Steam\\0" payload pins the residue of every
    later field, so no rewrite of the applied block can change the alignment there and the
    region is copied byte for byte (the legacy did the same, see the parity companion)."""
    nodes = _short_field(payload)
    raw = standard_save(THREE_ENTRIES, after_persistent=nodes)
    assert dson.validate(raw).ok
    assert FMT.write_applied(raw, identities(THREE_ENTRIES)) == raw
    for entries in (_shifting_entries(THREE_ENTRIES), _non_shifting_entries(THREE_ENTRIES)):
        out = FMT.write_applied(raw, identities(entries))
        assert FMT.read_applied(out) == identities(entries)
        assert dson.validate(out).ok_strict
        assert _region(out, nodes[0].name) == payload
        assert dson.read_scalars(out, ["guard"]) == {"guard": "g"}


@pytest.mark.legacy
@pytest.mark.parametrize("payload", SHORT_PAYLOADS, ids=SHORT_IDS)
def test_legacy_parity_for_short_payloads_after_the_anchor(
    legacy: LegacyOracle, payload: bytes
) -> None:
    dd2 = legacy.module("dd2")
    raw = standard_save(THREE_ENTRIES, after_persistent=_short_field(payload))
    for entries in (
        THREE_ENTRIES,
        _shifting_entries(THREE_ENTRIES),
        _non_shifting_entries(THREE_ENTRIES),
    ):
        keys, table = pm.stub_identities(tuple(entries))
        expected, _ = dd2.dson_patch_mod_list_resize(raw, keys, legacy.stub_manager(table))
        assert FMT.write_applied(raw, identities(entries)) == expected
    assert dd2.dson_patch_mod_list_resize(raw, *_legacy_args(legacy, THREE_ENTRIES))[0] == raw


def _legacy_args(legacy: LegacyOracle, entries: Sequence[Entry]) -> tuple[list[str], object]:
    keys, table = pm.stub_identities(tuple(entries))
    return keys, legacy.stub_manager(table)


@pytest.mark.parametrize("padded", [False, True], ids=["pad_0", "padded"])
@pytest.mark.parametrize("payload", SHORT_PAYLOADS[1:], ids=SHORT_IDS[1:])
def test_refuses_realigning_a_short_payload_between_applied_and_anchor(
    payload: bytes, padded: bool
) -> None:
    """Between the applied block and the anchor nothing resets the alignment, so a delta that is
    not a multiple of 4 would move the 2/3-byte aligned payload to another boundary (the legacy
    rebuild would re-pad it; the guard classifies by the ALIGNED payload, not the raw region)."""
    nodes = _between_probe(payload, padded=padded)
    raw = standard_save(THREE_ENTRIES, between=nodes)
    assert dson.validate(raw).ok_strict
    with pytest.raises(DsonUnsupportedError) as info:
        FMT.write_applied(raw, identities(_shifting_entries(THREE_ENTRIES)))
    assert info.value.code == "unsafe_realign"
    assert info.value.details["field"] == nodes[0].name
    assert info.value.details["size"] == len(payload)


@pytest.mark.parametrize("padded", [False, True], ids=["pad_0", "padded"])
@pytest.mark.parametrize("payload", SHORT_PAYLOADS[1:], ids=SHORT_IDS[1:])
def test_non_shifting_rewrite_keeps_a_short_payload_between_applied_and_anchor(
    payload: bytes, padded: bool
) -> None:
    nodes = _between_probe(payload, padded=padded)
    raw = standard_save(THREE_ENTRIES, between=nodes)
    assert FMT.write_applied(raw, identities(THREE_ENTRIES)) == raw
    entries = _non_shifting_entries(THREE_ENTRIES)
    out = FMT.write_applied(raw, identities(entries))
    assert FMT.read_applied(out) == identities(entries)
    assert dson.validate(out).ok_strict
    assert _region(out, nodes[0].name) == _region(raw, nodes[0].name)
    assert _region(out, nodes[0].name).endswith(payload)


def test_zero_byte_region_between_applied_and_anchor() -> None:
    """A 0-byte region on a boundary survives a non-shifting rewrite; one that ends before its
    boundary is refused even by the identity rewrite (the rebuild would grow it with zeros)."""
    aligned = standard_save(THREE_ENTRIES, between=_between_probe(b"", padded=False))
    assert FMT.write_applied(aligned, identities(THREE_ENTRIES)) == aligned
    out = FMT.write_applied(aligned, identities(_non_shifting_entries(THREE_ENTRIES)))
    assert dson.validate(out).ok_strict
    with pytest.raises(DsonUnsupportedError) as info:
        FMT.write_applied(aligned, identities(_shifting_entries(THREE_ENTRIES)))
    assert info.value.code == "unsafe_realign"

    unaligned = standard_save(THREE_ENTRIES, between=_between_probe(b"", padded=True))
    assert dson.validate(unaligned).ok_strict
    with pytest.raises(DsonUnsupportedError) as info:
        FMT.write_applied(unaligned, identities(THREE_ENTRIES))
    assert info.value.code == "unsafe_realign"


@pytest.mark.parametrize(
    "payload", [b"\x07", b"\x01\x02\x03\x04", b"\x01\x02\x03\x04\x05\x06\x07\x08"]
)
def test_one_byte_and_aligned_payloads_after_the_splice_are_fine(payload: bytes) -> None:
    probe: tuple[Node, ...] = (R("ok", payload),)
    for raw in (
        standard_save(THREE_ENTRIES, between=probe),
        standard_save(THREE_ENTRIES, after_persistent=probe),
    ):
        for entries in (_shifting_entries(THREE_ENTRIES), _non_shifting_entries(THREE_ENTRIES)):
            ids = identities(entries)
            out = FMT.write_applied(raw, ids)
            assert FMT.read_applied(out) == ids
            assert dson.validate(out).ok_strict
            assert _region(out, "ok").endswith(payload)


def test_odd_payloads_before_the_splice_point_are_copied_verbatim() -> None:
    raw = standard_save(THREE_ENTRIES, before_applied=(R("two", b"\x01\x02"), S("guard", "g")))
    ids = identities(_shifting_entries(THREE_ENTRIES))
    out = FMT.write_applied(raw, ids)
    assert FMT.read_applied(out) == ids
    assert dson.validate(out).ok
    assert _region(out, "two") == b"\x01\x02"


def _padded_after_anchor(root: O) -> list[str]:
    layouts = layout(root)
    anchor = find_layout(layouts, "base_root", ANCHOR_BLOCK)
    return [
        e.path[-1]
        for e in layouts
        if e.meta2_index > anchor.meta2_index and e.region_size > 1 and e.payload_start % 4
    ]


def test_refuses_nonzero_padding_after_the_splice_point() -> None:
    """Non-zero "padding" is data we do not understand: refused for ANY delta, since the rebuild
    zeroes it whether or not the field moves to another boundary."""
    root = standard_root(THREE_ENTRIES)
    assert _padded_after_anchor(root), "the standard tail must contain a padded scalar"
    raw = build_save(root, pad_byte=0xFF)
    assert dson.validate(raw).ok
    for entries in (THREE_ENTRIES, _shifting_entries(THREE_ENTRIES)):
        with pytest.raises(DsonUnsupportedError) as info:
            FMT.write_applied(raw, identities(entries))
        assert info.value.code == "unsafe_realign"
        assert info.value.details["field"] == _padded_after_anchor(root)[0]


@pytest.mark.legacy
def test_legacy_silently_zeroes_padding_after_the_splice_point(legacy: LegacyOracle) -> None:
    """dd2.py:910-934 re-pads every moved field with zeros, so the legacy rewrote bytes it did
    not understand; padding before the splice point was copied verbatim (still 0xFF)."""
    dd2 = legacy.module("dd2")
    raw = standard_save(THREE_ENTRIES, pad_byte=0xFF)
    patched, count = dd2.dson_patch_mod_list_resize(raw, *_legacy_args(legacy, THREE_ENTRIES))
    assert count == 3
    assert patched != raw
    doc = dson.parse(patched)
    anchor = doc.find_child(0, ANCHOR_BLOCK)
    applied = doc.find_child(0, APPLIED_BLOCK)
    assert anchor is not None and applied is not None
    seen_after = seen_before = 0
    for i, entry in enumerate(doc.meta2):
        if entry.is_object:
            continue
        start = entry.offset + entry.name_length
        _, payload_start, _ = dson.payload_layout(doc.data, entry, doc.field_end(i))
        padding = doc.data[start:payload_start]
        if not padding:
            continue
        if i > anchor:
            seen_after += 1
            assert padding == bytes(len(padding)), doc.name_of(i)
        elif i < applied:
            seen_before += 1
            assert padding == b"\xff" * len(padding), doc.name_of(i)
    assert seen_after and seen_before


# ---------------------------------------------------------------- input and output gates

CORRUPT_HASH = bytearray(standard_save(THREE_ENTRIES))
CORRUPT_HASH[struct.unpack_from("<i", CORRUPT_HASH, 48)[0]] ^= 0x01  # low byte of meta2[0].hash


@pytest.mark.parametrize(
    ("raw", "problem"),
    [(b"", "too_small"), (b"garbage", "too_small"), (bytes(CORRUPT_HASH), "hash_mismatch")],
    ids=["empty", "garbage", "hash_mismatch"],
)
def test_rejects_invalid_input(raw: bytes, problem: str) -> None:
    with pytest.raises(DsonFormatError) as info:
        FMT.write_applied(raw, NEW_IDS)
    assert info.value.code == "input_invalid"
    assert info.value.details["problem"] == problem
    with pytest.raises(DsonFormatError) as info:
        FMT.check(raw)
    assert info.value.code == problem
    report = FMT.validate(raw)
    assert not report.ok
    assert report.legacy_errors[0].code == problem


def test_check_accepts_valid_input() -> None:
    assert FMT.check(standard_save(THREE_ENTRIES)) is None
    assert FMT.validate(standard_save(THREE_ENTRIES)).ok_strict


def test_round_trip_gates_report_their_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forge the serializer's output to trip each post-write gate (they are unreachable through
    a correct codec, which is the point of having them)."""
    raw = standard_save(THREE_ENTRIES)
    good = FMT.write_applied(raw, NEW_IDS)
    forged = {
        "output_invalid": good[:-1],
        "strict_regression": bump_root_all_children(good),
        "entries_mismatch": FMT.write_applied(raw, identities(pm.new_entries(5))),
    }
    for code, output in forged.items():
        monkeypatch.setattr(dson, "serialize", lambda doc, output=output: output)
        with pytest.raises(RoundTripError) as info:
            FMT.write_applied(raw, NEW_IDS)
        assert info.value.code == code, code
        assert type(info.value).family == "round_trip"
    monkeypatch.undo()
    assert FMT.write_applied(raw, NEW_IDS) == good
