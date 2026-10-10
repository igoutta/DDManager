"""Planning of "Apply order to local mod folders" (src/core/folder_order.py).

The plan: the
prefix is the 4-digit 1-based position in ``order.entries`` (disabled included), ONE
existing numeric prefix is stripped plus any previous ``_<n>_`` dedupe suffix,
collisions get ``_<n>_``, Workshop mods are never renamed and unchanged names are skipped.
"""

import random
import re
from collections.abc import Iterable

import pytest

from src.core.folder_order import (
    RenamePlan,
    RenameStep,
    plan_folder_renames,
    strip_order_prefix,
)
from src.core.ids import ModId, SourceKind
from src.core.load_order import LoadOrder
from src.core.model import ModInfo
from src.core.validation import Severity
from tests.support.factories import load_order, local_mod, workshop_mod

M = ModId
PREFIXED = re.compile(r"^(\d{4})_(.*)$")


def _mods(*infos: ModInfo) -> dict[ModId, ModInfo]:
    return {info.id: info for info in infos}


def _plan(order: LoadOrder, mods: dict[ModId, ModInfo]) -> RenamePlan:
    plan = plan_folder_renames(order, mods)
    assert isinstance(plan, RenamePlan)
    for step in plan.steps:
        assert isinstance(step, RenameStep)
        assert step.old_name == str(step.mod)
        assert step.old_name != step.new_name
        assert plan.rekey[step.mod] == M(step.new_name)
    renamed = {step.mod for step in plan.steps}
    for old, new in plan.rekey.items():
        if old != new:
            assert old in renamed, (old, new)
    return plan


def _new_names(plan: RenamePlan) -> dict[str, str]:
    return {step.old_name: step.new_name for step in plan.steps}


def reference_strip(mod: str) -> str:
    """Test-side reference for the plain prefix strip (no dedupe-suffix handling)."""
    stripped_name = mod
    if "_" in mod[:5]:
        prefix, remainder = mod.split("_", 1)
        if prefix.isdigit():
            stripped_name = remainder
    return stripped_name


# ----------------------------------------------------------------- the basics


def test_prefix_is_the_position_in_entries_and_workshop_mods_are_skipped() -> None:
    mods = _mods(local_mod("b"), local_mod("0005_a"), local_mod("c"), workshop_mod("2248772895"))
    order = load_order("b", "0005_a", "-c", "2248772895")
    plan = _plan(order, mods)
    assert plan.findings == ()
    assert [(s.old_name, s.new_name) for s in plan.steps] == [
        ("b", "0001_b"),
        ("0005_a", "0002_a"),
        ("c", "0003_c"),  # disabled mods still get their slot
    ]
    assert M("2248772895") not in plan.rekey or plan.rekey[M("2248772895")] == M("2248772895")
    changed = {old: new for old, new in plan.rekey.items() if old != new}
    assert changed == {M("b"): M("0001_b"), M("0005_a"): M("0002_a"), M("c"): M("0003_c")}


def test_workshop_mods_keep_their_position_number() -> None:
    mods = _mods(workshop_mod("111"), local_mod("x"), workshop_mod("222"), local_mod("y"))
    plan = _plan(load_order("111", "x", "222", "y"), mods)
    assert _new_names(plan) == {"x": "0002_x", "y": "0004_y"}


def test_unchanged_names_are_skipped() -> None:
    mods = _mods(local_mod("0001_a"), local_mod("b"), local_mod("0003_c"))
    plan = _plan(load_order("0001_a", "b", "0003_c"), mods)
    assert _new_names(plan) == {"b": "0002_b"}
    assert plan.findings == ()


def test_nothing_to_do_gives_an_empty_plan() -> None:
    mods = _mods(local_mod("0001_a"), workshop_mod("5"))
    plan = _plan(load_order("0001_a", "5"), mods)
    assert plan.steps == ()
    assert plan.findings == ()


def test_entries_without_mod_info_consume_their_position() -> None:
    mods = _mods(local_mod("a"), local_mod("b"))
    plan = _plan(load_order("ghost", "a", "-gone", "b"), mods)
    assert _new_names(plan) == {"a": "0002_a", "b": "0004_b"}
    assert M("ghost") not in plan.rekey or plan.rekey[M("ghost")] == M("ghost")
    assert not any(f.severity is Severity.ERROR for f in plan.findings)
    assert plan.findings, "entries without disk facts are at least reported"


def test_steps_follow_entry_order() -> None:
    mods = _mods(local_mod("z"), local_mod("y"), local_mod("x"))
    plan = _plan(load_order("z", "y", "x"), mods)
    assert [s.old_name for s in plan.steps] == ["z", "y", "x"]
    assert [s.new_name for s in plan.steps] == ["0001_z", "0002_y", "0003_x"]


# ----------------------------------------------------------------- stripping


def test_strips_one_numeric_prefix_and_only_a_short_dedupe_segment() -> None:
    """``12_bar`` loses its prefix; ``0001_0002_foo`` loses ONE prefix and keeps ``0002_``: a
    dedupe counter is written unpadded (``_1_``, ``_2_``), so a longer digit run is content."""
    mods = _mods(local_mod("0001_0002_foo"), local_mod("12_bar"), local_mod("baz"))
    plan = _plan(load_order("baz", "0001_0002_foo", "12_bar"), mods)
    assert _new_names(plan) == {
        "baz": "0001_baz",
        "0001_0002_foo": "0002_0002_foo",
        "12_bar": "0003_bar",
    }
    triple = _plan(load_order("0001_0002_0003_foo"), _mods(local_mod("0001_0002_0003_foo")))
    assert _new_names(triple) == {}  # already at position 1; ``0002_0003_foo`` is content


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("0005_1234567_mymod", "1234567_mymod"),  # a copied Workshop folder keeps its id
        ("0003_1_foo", "foo"),
        ("0007_12_bar", "bar"),
        ("0001_0002_foo", "0002_foo"),
        ("0001_123_x", "123_x"),
        ("0001_2_player_mod", "player_mod"),  # documented residual ambiguity
        ("12_bar", "bar"),
        ("foo", "foo"),
        ("1234567_mymod", "1234567_mymod"),  # underscore beyond the 5-char window: no prefix
        ("0001_", "0001_"),  # would become empty: unchanged
        ("2024", "2024"),
        ("_x", "_x"),
    ],
)
def test_strip_order_prefix(name: str, expected: str) -> None:
    assert strip_order_prefix(name) == expected


def test_copied_workshop_folder_names_keep_their_id_and_the_plan_is_idempotent() -> None:
    """``1234567_mymod`` (a Workshop folder copied to the local mods) is prefixed once and never
    loses its id segment on a second apply (the bug the dedupe strip could cause)."""
    names = ["foo", "0001_foo", "1234567_mymod", "0005_1234567_mymod"]
    mods = _mods(*(local_mod(n) for n in names))
    plan = _plan(LoadOrder(tuple(M(n) for n in names), frozenset()), mods)
    renamed = _new_names(plan)
    assert renamed["1234567_mymod"] == "0003_1234567_mymod"
    assert renamed["0005_1234567_mymod"] == "0004_1234567_mymod"
    final = [renamed.get(n, n) for n in names]
    again = _plan(LoadOrder(tuple(M(n) for n in final), frozenset()), _mods(*map(local_mod, final)))
    assert again.steps == ()


def test_strips_a_previous_dedupe_suffix() -> None:
    mods = _mods(local_mod("0003_1_foo"), local_mod("0007_12_bar"))
    plan = _plan(load_order("0003_1_foo", "0007_12_bar"), mods)
    assert _new_names(plan) == {"0003_1_foo": "0001_foo", "0007_12_bar": "0002_bar"}


def test_a_plain_prefix_strip_keeps_the_dedupe_suffix_the_plan_strips_it() -> None:
    """A plain prefix strip leaves ``1_foo`` in ``0003_1_foo``, so the name would keep growing."""
    assert reference_strip("0003_1_foo") == "1_foo"
    plan = _plan(load_order("0003_1_foo"), _mods(local_mod("0003_1_foo")))
    assert _new_names(plan) == {"0003_1_foo": "0001_foo"}


def test_names_that_merely_look_numeric_are_not_mangled() -> None:
    mods = _mods(local_mod("2024"), local_mod("_x"), local_mod("a_1"), local_mod("b_12_c"))
    plan = _plan(load_order("2024", "_x", "a_1", "b_12_c"), mods)
    assert _new_names(plan) == {
        "2024": "0001_2024",
        "_x": "0002__x",
        "a_1": "0003_a_1",
        "b_12_c": "0004_b_12_c",
    }


def test_strip_matches_the_reference_strip_on_seeded_names_without_dedupe_suffixes() -> None:
    rng = random.Random(1234)
    words = ["foo", "Bar", "mod name", "ñandú", "x_y", "a-b", "class_patch", "Z"]
    for _ in range(200):
        base = rng.choice(words)
        prefix = rng.choice(["", "", f"{rng.randint(0, 9999):04d}_", f"{rng.randint(0, 99)}_"])
        name = prefix + base  # no word starts with digits, so no dedupe-suffix shapes here
        mods = _mods(local_mod(name))
        plan = _plan(load_order(name), mods)
        expected = f"0001_{reference_strip(name)}"
        actual = _new_names(plan).get(name, name)
        assert actual == expected, name


# ----------------------------------------------------------------- dedupe


def _casefold_names(names: Iterable[str]) -> list[str]:
    return [n.casefold() for n in names]


def test_new_names_never_collide_with_names_that_stay() -> None:
    """A planned name is unique among the plan and never the name of an unchanged mod."""
    mods = _mods(
        local_mod("0002_foo"),
        local_mod("0001_foo"),
        local_mod("0003_bar"),
        local_mod("0004_1_bar"),
        workshop_mod("5"),
    )
    plan = _plan(load_order("0002_foo", "0001_foo", "0003_bar", "0004_1_bar", "5"), mods)
    renamed = _new_names(plan)
    assert renamed == {"0002_foo": "0001_foo", "0001_foo": "0002_foo", "0004_1_bar": "0004_bar"}
    final = [renamed.get(str(m), str(m)) for m in mods]
    assert len(set(_casefold_names(final))) == len(final)


def test_final_folder_names_are_unique_casefold() -> None:
    rng = random.Random(777)
    stems = ["foo", "Foo", "bar", "baz", "qux"]
    for _ in range(100):
        count = rng.randint(1, 8)
        names: list[str] = []
        for _ in range(count):
            stem = rng.choice(stems)
            prefix = rng.choice(["", f"{rng.randint(1, 8):04d}_", f"{rng.randint(1, 8):04d}_1_"])
            candidate = prefix + stem
            if candidate.casefold() not in _casefold_names(names):
                names.append(candidate)
        mods = _mods(*(local_mod(n) for n in names))
        plan = _plan(LoadOrder(tuple(M(n) for n in names), frozenset()), mods)
        renamed = _new_names(plan)
        final = [renamed.get(n, n) for n in names]
        assert len(set(_casefold_names(final))) == len(final), (names, renamed)
        assert len(set(renamed.values())) == len(renamed)


# ----------------------------------------------------------------- invariants over random orders


def _random_mods(rng: random.Random) -> tuple[LoadOrder, dict[ModId, ModInfo]]:
    count = rng.randint(1, 30)
    infos: list[ModInfo] = []
    entries: list[ModId] = []
    for i in range(count):
        kind = rng.choice([SourceKind.LOCAL, SourceKind.LOCAL, SourceKind.WORKSHOP])
        if kind is SourceKind.WORKSHOP:
            name = str(1_000_000_000 + i)
            infos.append(workshop_mod(name))
        else:
            stem = rng.choice(["alpha", "beta", "gamma", "delta", "1234567_eps"]) + str(i)
            prefix = rng.choice(
                ["", "", f"{rng.randint(1, 40):04d}_", f"{rng.randint(1, 40):04d}_3_"]
            )
            name = prefix + stem
            if rng.random() < 0.85:
                infos.append(local_mod(name))
        entries.append(M(name))
    rng.shuffle(entries)
    enabled = frozenset(e for e in entries if rng.random() < 0.7)
    return LoadOrder(tuple(entries), enabled), _mods(*infos)


def test_prefixes_are_monotonic_positions_over_random_orders() -> None:
    rng = random.Random(2025)
    for _ in range(150):
        order, mods = _random_mods(rng)
        plan = _plan(order, mods)
        assert not any(f.severity is Severity.ERROR for f in plan.findings)
        position = {m: i + 1 for i, m in enumerate(order.entries)}
        last = 0
        for step in plan.steps:
            info = mods[step.mod]
            assert info.kind is SourceKind.LOCAL
            match = PREFIXED.match(step.new_name)
            assert match, step.new_name
            prefix = int(match.group(1))
            assert prefix == position[step.mod]
            assert prefix > last
            last = prefix
        # every local mod with info ends up with its position prefix (renamed or already there)
        renamed = _new_names(plan)
        for mod in order.entries:
            info = mods.get(mod)
            if info is None or info.kind is not SourceKind.LOCAL:
                continue
            final = renamed.get(str(mod), str(mod))
            assert final.startswith(f"{position[mod]:04d}_"), (mod, final)


def test_plan_is_idempotent() -> None:
    rng = random.Random(99)
    for _ in range(60):
        order, mods = _random_mods(rng)
        plan = _plan(order, mods)
        renamed = _new_names(plan)
        new_entries = tuple(M(renamed.get(str(m), str(m))) for m in order.entries)
        new_enabled = frozenset(M(renamed.get(str(m), str(m))) for m in order.enabled)
        new_mods = {
            M(renamed.get(str(k), str(k))): (local_mod(renamed[str(k)]) if str(k) in renamed else v)
            for k, v in mods.items()
        }
        again = _plan(LoadOrder(new_entries, new_enabled), new_mods)
        assert again.steps == (), (order, plan.steps, again.steps)


# ----------------------------------------------------------------- limits


def test_more_than_9999_entries_is_an_error_and_an_empty_plan() -> None:
    names = [f"m{i}" for i in range(10_000)]
    mods = {M(n): local_mod(n) for n in names[:3]}
    plan = plan_folder_renames(LoadOrder(tuple(M(n) for n in names), frozenset()), mods)
    assert plan.steps == ()
    assert not any(old != new for old, new in plan.rekey.items())
    assert any(f.severity is Severity.ERROR for f in plan.findings)


def test_exactly_9999_entries_is_fine() -> None:
    names = [f"m{i}" for i in range(9_999)]
    mods = {M(names[0]): local_mod(names[0]), M(names[-1]): local_mod(names[-1])}
    plan = plan_folder_renames(LoadOrder(tuple(M(n) for n in names), frozenset()), mods)
    assert not any(f.severity is Severity.ERROR for f in plan.findings)
    assert _new_names(plan) == {names[0]: f"0001_{names[0]}", names[-1]: f"9999_{names[-1]}"}


@pytest.mark.parametrize("name", ["0001_a", "a"])
def test_single_entry(name: str) -> None:
    plan = _plan(load_order(name), _mods(local_mod(name)))
    assert _new_names(plan) == ({} if name == "0001_a" else {"a": "0001_a"})


# ----------------------------------------------------------------- two-phase execution


def test_plan_says_when_targets_collide_with_sources() -> None:
    """``foo -> 0001_foo`` while ``0001_foo -> 0002_foo``: a sequential rename would hit an
    existing folder, so the plan flags the two-phase (temp names) execution."""
    chained = _plan(load_order("foo", "0001_foo"), _mods(local_mod("foo"), local_mod("0001_foo")))
    assert [(s.old_name, s.new_name) for s in chained.steps] == [
        ("foo", "0001_foo"),
        ("0001_foo", "0002_foo"),
    ]
    assert chained.requires_two_phase
    swapped = _plan(load_order("0002_x", "0001_x"), _mods(local_mod("0002_x"), local_mod("0001_x")))
    assert swapped.requires_two_phase  # a pure cycle
    case_only = _plan(
        load_order("0002_X", "0001_x"), _mods(local_mod("0002_X"), local_mod("0001_x"))
    )
    assert case_only.requires_two_phase  # Windows folders are case-insensitive
    plain = _plan(load_order("a", "b"), _mods(local_mod("a"), local_mod("b")))
    assert not plain.requires_two_phase
    assert not RenamePlan((), {}, ()).requires_two_phase
