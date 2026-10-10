"""Bit 31 of a meta2 info word (an unknown game flag) survives write_applied per entry.

The game sets the bit sporadically on child objects, ``name`` and ``source`` words inside
``applied_ugcs_1_0`` and on scalars elsewhere.  The expected bytes here come from the independent
builder (``build_save(..., flag31=)``), never from the codec: a rewrite must equal the save the
builder makes for the new entry order with each entry's flags moved along with it.
"""

import random

import pytest

from src.core.ids import SaveIdentity
from src.core.saves import dson
from src.core.saves.dson.flags import NO_FLAGS, EntryFlags, carry_flags, has_flag, with_flag
from src.core.saves.dson_v1 import DsonV1Format
from tests.support import parity_matrix as pm
from tests.support.dson_builder import (
    ANCHOR_BLOCK,
    APPLIED_BLOCK,
    LOCAL,
    PERSISTENT_OBJECT,
    STEAM,
    THREE_ENTRIES,
    Entry,
    I,
    O,
    S,
    build_save,
    layout,
    standard_root,
)
from tests.support.identities import identities
from tests.support.mutations import info_bit31_indices, set_info_bit31
from tools.legacy_oracle import LegacyOracle

FMT = DsonV1Format()
A, B, C = THREE_ENTRIES
D: Entry = ("4444", STEAM)
type Path = tuple[str, ...]

# flags on fields outside the block: before it, on the anchor's child words and on the tail
OUTSIDE: frozenset[Path] = frozenset(
    {
        ("base_root",),
        ("base_root", "inraid"),
        ("base_root", "dlc", "0", "source"),
        ("base_root", ANCHOR_BLOCK, "0"),
        ("base_root", ANCHOR_BLOCK, "0", "name"),
        ("base_root", "never_again"),
        ("base_root", "nested", "b"),
    }
)


def words(k: int, *, child: bool = False, name: bool = False, source: bool = False) -> set[Path]:
    """The paths of applied entry ``k``'s three words that carry the flag."""
    base: Path = ("base_root", APPLIED_BLOCK, str(k))
    out: set[Path] = set()
    if child:
        out.add(base)
    if name:
        out.add((*base, "name"))
    if source:
        out.add((*base, "source"))
    return out


def flagged_save(entries: tuple[Entry, ...] | None, flagged: set[Path]) -> bytes:
    """A standard save with bit 31 set on exactly the fields at ``flagged`` (all must exist)."""
    root = standard_root(entries)
    indices = {e.meta2_index for e in layout(root) if e.path in flagged}
    assert len(indices) == len(flagged), flagged - {e.path for e in layout(root)}
    return build_save(root, flag31=indices.__contains__)


def block_words(raw: bytes) -> tuple[tuple[bool, bool, bool], ...]:
    """Per applied entry, bit 31 of (child, name, source), read through the codec's parse."""
    doc = dson.parse(raw)
    applied = doc.find_child(0, APPLIED_BLOCK)
    assert applied is not None
    out: list[tuple[bool, bool, bool]] = []
    for child in doc.children[applied]:
        name, source = doc.children[child]
        flags = doc.meta2[child].info < 0, doc.meta2[name].info < 0, doc.meta2[source].info < 0
        out.append(flags)
    return tuple(out)


# ---------------------------------------------------------------- the helpers themselves


def test_with_flag_and_has_flag() -> None:
    for info in (0, 1, 0x7FFFFFFF, dson.field_info("name"), dson.field_info("0", 5)):
        assert not has_flag(info)
        flagged = with_flag(info, True)
        assert flagged < 0 and has_flag(flagged)
        assert flagged & 0x7FFFFFFF == info
        assert with_flag(flagged, False) == info
        assert with_flag(flagged, True) == flagged
        assert with_flag(info, False) == info
        assert dson.object_index_from_info(flagged) == dson.object_index_from_info(info)
        assert dson.Meta2(0, 0, flagged).name_length == dson.Meta2(0, 0, info).name_length


def test_carry_flags_is_positional_among_duplicates() -> None:
    a, b = SaveIdentity(*A), SaveIdentity(*B)
    f1, f2, f3 = EntryFlags(child=True), EntryFlags(name=True), EntryFlags(source=True)
    old = [(a, f1), (b, f2), (a, f3)]
    assert carry_flags(old, [a, a]) == [f1, f3]
    assert carry_flags(old, [a, a, a]) == [f1, f3, NO_FLAGS]
    assert carry_flags(old, [b, a]) == [f2, f1]
    assert carry_flags(old, [SaveIdentity(*D), b]) == [NO_FLAGS, f2]
    assert carry_flags([], [a, b]) == [NO_FLAGS, NO_FLAGS]
    assert carry_flags(old, []) == []
    assert EntryFlags(False, False, False) == NO_FLAGS


# ---------------------------------------------------------------- the identity rewrite


@pytest.mark.parametrize("n", (1, 3, 7, 40), ids=lambda n: f"N{n}")
@pytest.mark.parametrize("seed", range(5))
def test_rewrite_identity_keeps_random_flags_inside_and_outside(n: int, seed: int) -> None:
    rng = random.Random(seed * 1000 + n)
    entries = tuple((f"{k * 7919}", STEAM) if k % 2 else (f"Local {k}", LOCAL) for k in range(n))
    root = standard_root(entries)
    flagged = frozenset(k for k in range(len(layout(root))) if rng.random() < 0.4)
    raw = build_save(root, flag31=flagged.__contains__)
    assert info_bit31_indices(raw) == flagged
    assert flagged, "the seed must flag something"
    assert dson.validate(raw).ok_strict
    assert dson.serialize(dson.parse(raw)) == raw
    assert FMT.read_applied(raw) == identities(entries)
    assert FMT.write_applied(raw, identities(entries)) == raw


def test_rewrite_identity_with_every_word_flagged() -> None:
    root = standard_root(THREE_ENTRIES)
    raw = build_save(root, flag31=lambda _index: True)
    assert len(info_bit31_indices(raw)) == len(layout(root))
    assert dson.validate(raw).ok_strict
    assert FMT.read_applied(raw) == identities(THREE_ENTRIES)
    assert FMT.write_applied(raw, identities(THREE_ENTRIES)) == raw


def test_flags_are_invisible_to_the_validator_and_the_reader() -> None:
    clean = flagged_save(THREE_ENTRIES, set())
    flagged = flagged_save(THREE_ENTRIES, {*OUTSIDE, *words(0, child=True, name=True, source=True)})
    assert flagged != clean
    assert set_info_bit31(flagged, info_bit31_indices(flagged), on=False) == clean
    for raw in (clean, flagged):
        report = dson.validate(raw)
        assert report.ok_strict and report.strict_errors == ()
        assert FMT.read_applied(raw) == identities(THREE_ENTRIES)
    assert block_words(flagged) == (
        (True, True, True),
        (False, False, False),
        (False, False, False),
    )


# ---------------------------------------------------------------- flags travel with their entry

OLD_FLAGS = {*OUTSIDE, *words(0, child=True, name=True), *words(1, source=True)}
OLD = flagged_save(THREE_ENTRIES, OLD_FLAGS)


def test_reordering_entries_moves_each_entry_flags_with_it() -> None:
    new = (C, B, A)
    expected = flagged_save(
        new, {*OUTSIDE, *words(1, source=True), *words(2, child=True, name=True)}
    )
    out = FMT.write_applied(OLD, identities(new))
    assert out == expected
    assert block_words(out) == ((False, False, False), (False, False, True), (True, True, False))
    assert FMT.read_applied(out) == identities(new)
    assert dson.validate(out).ok_strict


def test_a_new_entry_gets_clear_bits_and_a_removed_entry_drops_its_flags() -> None:
    new = (B, D, A)  # C removed, D new, A and B swapped
    expected = flagged_save(
        new, {*OUTSIDE, *words(0, source=True), *words(2, child=True, name=True)}
    )
    out = FMT.write_applied(OLD, identities(new))
    assert out == expected
    assert block_words(out) == ((False, False, True), (False, False, False), (True, True, False))
    # drop every flagged entry: the block is flag-free, the outside flags stay
    out = FMT.write_applied(OLD, identities((C, D)))
    assert out == flagged_save((C, D), set(OUTSIDE))
    assert block_words(out) == ((False, False, False), (False, False, False))
    # drop every entry: nothing inside to carry
    assert FMT.write_applied(OLD, ()) == flagged_save((), set(OUTSIDE))


def test_duplicate_identities_match_positionally() -> None:
    old = (A, A, A)
    raw = flagged_save(old, {*words(0, child=True), *words(1, name=True), *words(2, source=True)})
    assert block_words(raw) == ((True, False, False), (False, True, False), (False, False, True))
    out = FMT.write_applied(raw, identities((A, A)))
    assert out == flagged_save((A, A), {*words(0, child=True), *words(1, name=True)})
    out = FMT.write_applied(raw, identities((A, A, A, A)))
    expected = {*words(0, child=True), *words(1, name=True), *words(2, source=True)}
    assert out == flagged_save((A, A, A, A), expected)
    assert block_words(out)[3] == (False, False, False)
    out = FMT.write_applied(raw, identities((B, A)))
    assert out == flagged_save((B, A), words(1, child=True))


def test_insert_path_writes_clear_bits_and_keeps_the_outside_flags() -> None:
    outside = set(OUTSIDE)  # no path under the block: the save has none
    raw = flagged_save(None, outside)
    assert FMT.read_applied(raw) == ()
    new = (A, B)
    out = FMT.write_applied(raw, identities(new))
    assert out == flagged_save(new, outside)
    assert block_words(out) == ((False, False, False), (False, False, False))
    assert dson.validate(out).ok_strict


def test_a_malformed_old_child_contributes_no_flags() -> None:
    """A child without a string name/source has no identity to match; the well-formed sibling
    still carries its flags (the block is rebuilt, so the broken child is dropped anyway)."""
    broken = O(
        APPLIED_BLOCK,
        [O("0", [S("name", "n"), I("source", 1)]), O("1", [S("name", A[0]), S("source", A[1])])],
    )
    root = O("base_root", [I("version", 5), broken, PERSISTENT_OBJECT])
    flagged = {
        e.meta2_index for e in layout(root) if len(e.path) > 2 and e.path[1] == APPLIED_BLOCK
    }
    raw = build_save(root, flag31=flagged.__contains__)
    assert len(flagged) == 6
    out = FMT.write_applied(raw, identities((("n", "1"), A)))
    assert FMT.read_applied(out) == identities((("n", "1"), A))
    assert block_words(out) == ((False, False, False), (True, True, True))


# ---------------------------------------------------------------- the divergence from the legacy


@pytest.mark.legacy
def test_legacy_clears_the_bits_the_codec_carries(legacy: LegacyOracle) -> None:
    """The pinned patcher rebuilt every word of the block from ``dson_field_info`` (dd2.py:866),
    clearing bit 31 on child, name and source words alike; outside the block both agree.  The
    divergence is listed exactly: ours == legacy with the carried words set, nothing else."""
    dd2 = legacy.module("dd2")
    new = (C, B, A, D)
    keys, table = pm.stub_identities(new)
    expected, count = dd2.dson_patch_mod_list_resize(OLD, keys, legacy.stub_manager(table))
    assert count == len(new)
    ours = FMT.write_applied(OLD, identities(new))
    doc = dson.parse(ours)
    applied = doc.find_child(0, APPLIED_BLOCK)
    assert applied is not None
    inside = set(range(applied + 1, applied + 1 + 3 * len(new)))
    carried = {applied + 1 + 3 * 1 + 2, applied + 1 + 3 * 2, applied + 1 + 3 * 2 + 1}
    assert info_bit31_indices(expected) & inside == set()
    assert info_bit31_indices(ours) & inside == carried
    assert info_bit31_indices(ours) - inside == info_bit31_indices(expected) - inside
    assert set_info_bit31(ours, carried, on=False) == expected
    assert set_info_bit31(expected, carried, on=True) == ours
    assert ours != expected


def test_carried_positions_table_matches_the_matrix() -> None:
    """``pm.CARRIED_POSITIONS`` is the hand-written list of matrix cells where the codec diverges
    from the legacy on a flagged save; check it against the entries the matrix actually uses."""
    for n, m in pm.CASES:
        existing = list(pm.existing_entries(n) or ())
        carried = []
        for k, entry in enumerate(pm.new_entries(m)):
            if entry in existing:
                existing.remove(entry)
                carried.append(k)
        assert tuple(carried) == pm.CARRIED_POSITIONS.get((n, m), ()), (n, m)
