"""Generic block reordering (src/core/reorder.py).

Contract: ``gap`` is the insertion point in the CURRENT view (0..len); the selection keeps its
relative order; non-contiguous selections gather at the gap; dropping inside a contiguous block's
own span is a no-op. Parity is proved against the pinned ``dd2.ModManager.reorder_visible_group``
(dd2.py:6684-6712) for upward moves; the downward overshoot of the legacy is locked as a
documented divergence. The legacy has no move-up/down buttons, so ``move_up``/``move_down``/
``move_to_top``/``move_to_bottom`` are checked against the contract and a reference simulation.
"""

import random
from collections.abc import Sequence
from types import ModuleType

import pytest

from src.core.reorder import (
    is_subsequence,
    move_block,
    move_down,
    move_to_bottom,
    move_to_top,
    move_up,
    splice,
)
from tools.legacy_oracle import LegacyOracle

ABCD = ("a", "b", "c", "d")
ABCDE = ("a", "b", "c", "d", "e")


# ----------------------------------------------------------------- reference simulations


def _ref_move_block(view: Sequence[str], selected: set[str], gap: int) -> tuple[str, ...]:
    """Insertion index in the remaining list = gap minus the selected items before the gap."""
    picked = [x for x in view if x in selected]
    rest = [x for x in view if x not in selected]
    at = gap - sum(1 for x in view[:gap] if x in selected)
    return (*rest[:at], *picked, *rest[at:])


def _ref_move_up(view: Sequence[str], selected: set[str]) -> tuple[str, ...]:
    """Every selected block swaps with the unselected item above it; a top-pinned block stays."""
    items = list(view)
    for i in range(1, len(items)):
        if items[i] in selected and items[i - 1] not in selected:
            items[i - 1], items[i] = items[i], items[i - 1]
    return tuple(items)


def _ref_move_down(view: Sequence[str], selected: set[str]) -> tuple[str, ...]:
    items = list(view)
    for i in range(len(items) - 2, -1, -1):
        if items[i] in selected and items[i + 1] not in selected:
            items[i], items[i + 1] = items[i + 1], items[i]
    return tuple(items)


def _random_case(rng: random.Random) -> tuple[list[str], set[str]]:
    n = rng.randint(1, 12)
    view = [f"m{i}" for i in range(n)]
    rng.shuffle(view)
    k = rng.randint(0, n)
    return view, set(rng.sample(view, k))


# ----------------------------------------------------------------- is_subsequence


def test_is_subsequence_examples() -> None:
    assert is_subsequence([], [])
    assert is_subsequence([], [1, 2])
    assert is_subsequence([1, 3], [1, 2, 3])
    assert is_subsequence([1, 2, 3], [1, 2, 3])
    assert not is_subsequence([3, 1], [1, 2, 3])
    assert not is_subsequence([1, 1], [1, 2])
    assert not is_subsequence([1], [])
    assert is_subsequence("ace", "abcde")
    assert not is_subsequence("aec", "abcde")


def test_is_subsequence_seeded_against_random_subsequences() -> None:
    rng = random.Random(4101)
    for _ in range(300):
        full = [rng.randint(0, 9) for _ in range(rng.randint(0, 15))]
        sub = [x for x in full if rng.random() < 0.5]
        assert is_subsequence(sub, full)
        assert not is_subsequence([*sub, 99], full)  # 99 never occurs in full
        if full:
            assert not is_subsequence([*full, full[0]], full)  # longer than full


# ----------------------------------------------------------------- move_block: contract examples


@pytest.mark.parametrize(
    ("gap", "expected"),
    [
        (0, ABCD),  # inside the block's own span: no-op
        (1, ABCD),  # inside the block's own span: no-op
        (2, ("b", "a", "c", "d")),
        (3, ("b", "c", "a", "d")),
        (4, ("b", "c", "d", "a")),
    ],
)
def test_move_block_single_item_at_every_gap(gap: int, expected: tuple[str, ...]) -> None:
    assert move_block(ABCD, {"a"}, gap) == expected


def test_move_block_fixes_legacy_downward_overshoot_contract_example() -> None:
    """Regression lock: legacy gives (b, c, d, a) for this drop; core gives (b, c, a, d)."""
    assert move_block(ABCD, {"a"}, 3) == ("b", "c", "a", "d")


@pytest.mark.parametrize(
    ("gap", "expected"),
    [
        (1, ABCDE),
        (2, ABCDE),
        (3, ABCDE),
        (0, ("b", "c", "a", "d", "e")),
        (4, ("a", "d", "b", "c", "e")),
        (5, ("a", "d", "e", "b", "c")),
    ],
)
def test_move_block_contiguous_block(gap: int, expected: tuple[str, ...]) -> None:
    assert move_block(ABCDE, {"b", "c"}, gap) == expected


@pytest.mark.parametrize(
    ("gap", "expected"),
    [
        (0, ("a", "c", "b", "d")),
        (1, ("a", "c", "b", "d")),
        (2, ("b", "a", "c", "d")),
        (3, ("b", "a", "c", "d")),
        (4, ("b", "d", "a", "c")),
    ],
)
def test_move_block_non_contiguous_selection_gathers_at_the_gap(
    gap: int, expected: tuple[str, ...]
) -> None:
    assert move_block(ABCD, {"a", "c"}, gap) == expected


def test_move_block_empty_selection_and_full_selection_are_no_ops() -> None:
    for gap in range(len(ABCD) + 1):
        assert move_block(ABCD, set(), gap) == ABCD
        assert move_block(ABCD, set(ABCD), gap) == ABCD
    assert move_block((), set(), 0) == ()


def test_move_block_accepts_lists_and_hashable_ints_and_returns_a_tuple() -> None:
    result = move_block([1, 2, 3, 4], {2, 4}, 0)
    assert result == (2, 4, 1, 3)
    assert isinstance(result, tuple)


def test_move_block_ignores_selected_items_absent_from_the_view() -> None:
    """Resolved ambiguity: ids that are not in the view have no effect (legacy filtered them)."""
    assert move_block(ABCD, {"a", "zzz"}, 4) == ("b", "c", "d", "a")


def test_move_block_seeded_invariants() -> None:
    rng = random.Random(20260929)
    for _ in range(500):
        view, selected = _random_case(rng)
        gap = rng.randint(0, len(view))
        result = move_block(view, selected, gap)
        assert sorted(result) == sorted(view), "permutation"
        assert [x for x in result if x in selected] == [x for x in view if x in selected]
        assert [x for x in result if x not in selected] == [x for x in view if x not in selected]
        assert result == _ref_move_block(view, selected, gap)
        if selected:
            first = min(i for i, x in enumerate(result) if x in selected)
            assert first == gap - sum(1 for x in view[:gap] if x in selected), "lands at the gap"
            last = max(i for i, x in enumerate(result) if x in selected)
            assert last - first + 1 == len(selected), "gathered into one block"


# ----------------------------------------------------------------- move_up / move_down


def test_move_up_examples() -> None:
    assert move_up(ABCDE, {"b", "d"}) == ("b", "a", "d", "c", "e")
    assert move_up(ABCDE, {"b", "c"}) == ("b", "c", "a", "d", "e")
    assert move_up(ABCDE, {"a", "c"}) == ("a", "c", "b", "d", "e")  # top-pinned a stays
    assert move_up(ABCDE, {"a", "b", "d"}) == ("a", "b", "d", "c", "e")
    assert move_up(ABCDE, {"a"}) == ABCDE
    assert move_up(ABCDE, set()) == ABCDE
    assert move_up(ABCDE, set(ABCDE)) == ABCDE
    assert move_up((), set()) == ()


def test_move_down_examples() -> None:
    assert move_down(ABCDE, {"b", "d"}) == ("a", "c", "b", "e", "d")
    assert move_down(ABCDE, {"b", "c"}) == ("a", "d", "b", "c", "e")
    assert move_down(ABCDE, {"c", "e"}) == ("a", "b", "d", "c", "e")  # bottom-pinned e stays
    assert move_down(ABCDE, {"b", "d", "e"}) == ("a", "c", "b", "d", "e")
    assert move_down(ABCDE, {"e"}) == ABCDE
    assert move_down(ABCDE, set()) == ABCDE
    assert move_down(ABCDE, set(ABCDE)) == ABCDE


def test_move_up_then_down_round_trips_when_nothing_is_pinned() -> None:
    view = ABCDE
    selected = {"b", "d"}
    assert move_down(move_up(view, selected), selected) == view


def test_move_up_and_down_seeded_against_reference() -> None:
    rng = random.Random(77)
    for _ in range(500):
        view, selected = _random_case(rng)
        up = move_up(view, selected)
        down = move_down(view, selected)
        assert up == _ref_move_up(view, selected)
        assert down == _ref_move_down(view, selected)
        for result in (up, down):
            assert sorted(result) == sorted(view)
            assert [x for x in result if x in selected] == [x for x in view if x in selected]


# ----------------------------------------------------------------- move_to_top / move_to_bottom


def test_move_to_top_and_bottom_examples() -> None:
    assert move_to_top(ABCDE, {"b", "d"}) == ("b", "d", "a", "c", "e")
    assert move_to_bottom(ABCDE, {"b", "d"}) == ("a", "c", "e", "b", "d")
    assert move_to_top(ABCDE, {"a", "b"}) == ABCDE
    assert move_to_bottom(ABCDE, {"d", "e"}) == ABCDE
    assert move_to_top(ABCDE, set()) == ABCDE
    assert move_to_bottom(ABCDE, set()) == ABCDE
    assert move_to_top(ABCDE, {"e"}) == ("e", "a", "b", "c", "d")
    assert move_to_bottom(ABCDE, {"a"}) == ("b", "c", "d", "e", "a")


def test_move_to_top_and_bottom_seeded_invariants() -> None:
    rng = random.Random(1010)
    for _ in range(300):
        view, selected = _random_case(rng)
        picked = [x for x in view if x in selected]
        rest = [x for x in view if x not in selected]
        assert move_to_top(view, selected) == (*picked, *rest)
        assert move_to_bottom(view, selected) == (*rest, *picked)
        assert move_to_top(view, selected) == move_block(view, selected, 0)
        assert move_to_bottom(view, selected) == move_block(view, selected, len(view))


# ----------------------------------------------------------------- splice


FULL = ("a", "B", "c", "D", "e")  # upper-case = slots that are not part of the view


def test_splice_refills_only_the_slot_positions_left_to_right() -> None:
    assert splice(FULL, {"a", "c", "e"}, ("e", "a", "c")) == ("e", "B", "a", "D", "c")
    assert splice(FULL, {"a", "c", "e"}, ("a", "c", "e")) == FULL
    assert splice(FULL, set(), ()) == FULL
    assert splice((), set(), ()) == ()


@pytest.mark.parametrize(
    "new_seq",
    [("a",), ("a", "a"), ("a", "x"), ("a", "c", "e"), ("a", "B")],
)
def test_splice_rejects_non_permutations(new_seq: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        splice(FULL, {"a", "c"}, new_seq)


def test_splice_seeded_keeps_every_non_slot_position_fixed() -> None:
    rng = random.Random(5)
    for _ in range(300):
        n = rng.randint(0, 12)
        full = [f"m{i}" for i in range(n)]
        rng.shuffle(full)
        slots = {x for x in full if rng.random() < 0.6}
        view = [x for x in full if x in slots]
        permuted = view[:]
        rng.shuffle(permuted)
        result = splice(full, slots, permuted)
        assert len(result) == n
        assert [x for x in result if x in slots] == permuted
        for i, x in enumerate(full):
            if x not in slots:
                assert result[i] == x


# ----------------------------------------------------------------- legacy parity


def _legacy_reorder(
    dd2: ModuleType,
    full: Sequence[str],
    visible: Sequence[str],
    moved: Sequence[str],
    target: int,
) -> tuple[str, ...]:
    """``reorder_visible_group`` (dd2.py:6684-6712) reads only ``self.state["order"]`` when an
    explicit ``visible_mods`` list is passed."""
    mgr = object.__new__(dd2.ModManager)
    mgr.state = {"order": list(full)}
    mgr.reorder_visible_group("enabled", list(moved), target, visible_mods=list(visible))
    return tuple(mgr.state["order"])


def _random_parity_case(rng: random.Random) -> tuple[list[str], list[str], list[str]]:
    n = rng.randint(1, 14)
    full = [f"m{i}" for i in range(n)]
    rng.shuffle(full)
    visible = [x for x in full if rng.random() < 0.7] or [full[0]]
    moved = [x for x in visible if rng.random() < 0.4] or [rng.choice(visible)]
    return full, visible, moved


@pytest.mark.legacy
def test_reorder_legacy_downward_overshoot_lock(legacy: LegacyOracle) -> None:
    """Documented divergence: the legacy inserts at the gap of the REMAINING list, so a downward
    drop lands one slot too far per selected item above the gap."""
    dd2 = legacy.module("dd2")
    assert _legacy_reorder(dd2, ABCD, ABCD, ["a"], 3) == ("b", "c", "d", "a")
    assert move_block(ABCD, {"a"}, 3) == ("b", "c", "a", "d")
    # upward drops agree
    assert _legacy_reorder(dd2, ABCD, ABCD, ["d"], 0) == move_block(ABCD, {"d"}, 0)


@pytest.mark.legacy
def test_reorder_parity_for_upward_moves(legacy: LegacyOracle) -> None:
    """Whenever no selected item sits above the gap, core == legacy (including the splice back
    into the full order around filtered-out or opposite-side mods)."""
    dd2 = legacy.module("dd2")
    rng = random.Random(6684)
    checked = 0
    for _ in range(600):
        full, visible, moved = _random_parity_case(rng)
        first = min(visible.index(m) for m in moved)
        gap = rng.randint(0, first)
        expected = _legacy_reorder(dd2, full, visible, moved, gap)
        got = splice(full, set(visible), move_block(visible, set(moved), gap))
        assert got == expected
        checked += 1
    assert checked == 600


@pytest.mark.legacy
def test_reorder_legacy_overshoots_downward_moves_by_the_selection_size(
    legacy: LegacyOracle,
) -> None:
    """Characterisation: for a drop below the whole selection, legacy(target) == core(target +
    len(selection)) whenever that gap exists, i.e. the legacy lands |selection| rows too low."""
    dd2 = legacy.module("dd2")
    rng = random.Random(6712)
    for _ in range(600):
        full, visible, moved = _random_parity_case(rng)
        last = max(visible.index(m) for m in moved)
        # legacy targets whose core counterpart (target + |moved|) lies below the whole selection
        target = rng.randint(max(0, last - len(moved) + 1), len(visible) - len(moved))
        gap = target + len(moved)
        assert last < gap <= len(visible)
        expected = _legacy_reorder(dd2, full, visible, moved, target)
        assert splice(full, set(visible), move_block(visible, set(moved), gap)) == expected
