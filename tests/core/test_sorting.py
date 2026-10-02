"""Auto-sort (src/core/sorting.py): stable tier sort + heap Kahn in precedence space.

Contract: active() is sorted by (tier_weight, current precedence position) in precedence space
(low -> high), then Kahn's algorithm with a min-heap keyed by that preferred rank gives the
lexicographically smallest topological order; cycles yield ONE ERROR Finding "core.sort_cycle"
(members sorted by preferred rank), their edges are dropped and the sort continues; the result is
mapped back to index space via the direction (FIRST_WINS: highest precedence at index 0).
Disabled entries keep their slots. Parity: the bucket order equals the pinned
``categories.get_category_priority`` buckets used by ``sorted_order_by_category``
(dd2.py:4327-4353) when no overhaul/patch tiers are involved.
"""

import random
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import pytest

from src.core.ids import ModId
from src.core.load_order import LoadOrder, PriorityDirection
from src.core.sorting import PrecedenceEdge, RankChange, SortResult, auto_sort
from src.core.tiers import TierTable
from src.core.validation import Finding, Severity
from tools.legacy_oracle import LegacyOracle

FIRST = PriorityDirection.FIRST_WINS
LAST = PriorityDirection.LAST_WINS
M = ModId
CYCLE_RULE = "core.sort_cycle"

# categories.py:31-41 and dd2.py:4333-4344 (inlined; see test_tiers.py)
DEFAULT_CATEGORIES = (
    "UI",
    "Districts",
    "Dungeons",
    "Quirks",
    "Trinkets",
    "Enemies",
    "Class Patch",
    "Class",
    "Skins",
)
BASE_PRIORITY = {
    "UI": 0,
    "Districts": 100,
    "Dungeons": 200,
    "Quirks": 250,
    "Trinkets": 300,
    "Enemies": 400,
    "Class Patch": 450,
    "Class": 500,
    "Skins": 600,
    "Unassigned": 700,
}
CUSTOM_POOL = ("Lore", "Music", "Fonts")


# ----------------------------------------------------------------- helpers


def _ids(spec: str) -> tuple[ModId, ...]:
    return tuple(ModId(tok.rstrip("*")) for tok in spec.split())


def _order(spec: str) -> LoadOrder:
    tokens = spec.split()
    entries = tuple(ModId(t.rstrip("*")) for t in tokens)
    return LoadOrder(entries, frozenset(ModId(t) for t in tokens if not t.endswith("*")))


Weights = Mapping[str, int] | Mapping[ModId, int]


def _weights(mapping: Weights, default: int = 500) -> Callable[[ModId], int]:
    def weight(m: ModId) -> int:
        return mapping.get(m, default)

    return weight


def _edge(low: str, high: str, reason: str = "test") -> PrecedenceEdge:
    return PrecedenceEdge(ModId(low), ModId(high), reason)


def _sort(
    order: LoadOrder,
    weights: Weights | None = None,
    edges: Iterable[PrecedenceEdge] = (),
    direction: PriorityDirection = FIRST,
) -> SortResult:
    return auto_sort(order, tier_weight=_weights(weights or {}), edges=edges, direction=direction)


def _expected_changes(before: LoadOrder, after: LoadOrder) -> set[RankChange]:
    old, new = before.ranks(), after.ranks()
    return {RankChange(m, old[m], new[m]) for m in old if old[m] != new[m]}


def _random_order(rng: random.Random, max_len: int = 12) -> LoadOrder:
    names = [f"m{i}" for i in range(rng.randint(1, max_len))]
    rng.shuffle(names)
    entries = tuple(ModId(x) for x in names)
    return LoadOrder(entries, frozenset(m for m in entries if rng.random() < 0.7))


def _random_edges(rng: random.Random, order: LoadOrder, count: int) -> list[PrecedenceEdge]:
    pool = list(order.entries)
    edges = []
    for i in range(count):
        low, high = rng.sample(pool, 2) if len(pool) >= 2 else (pool[0], pool[0])
        edges.append(PrecedenceEdge(low, high, f"e{i}"))
    return edges


def _finding_cores(findings: Iterable[Finding]) -> list[tuple[object, ...]]:
    """The contract-specified parts of each Finding; ``details`` (the edge listing) is compared as
    a set because the contract does not fix its order."""
    return [
        (f.rule_id, f.severity, f.mod_ids, f.message, f.fix, frozenset(f.details)) for f in findings
    ]


def _cycle_members(findings: Iterable[Finding]) -> list[frozenset[ModId]]:
    return [frozenset(f.mod_ids) for f in findings if f.rule_id == CYCLE_RULE]


def _assert_edges_respected(
    result: SortResult, edges: Iterable[PrecedenceEdge], d: PriorityDirection
) -> None:
    cycles = _cycle_members(result.findings)
    active = set(result.order.active())
    for e in edges:
        if e.low == e.high or e.low not in active or e.high not in active:
            continue
        if any(e.low in c and e.high in c for c in cycles):
            continue
        assert result.order.wins(e.high, e.low, d), (e, result.order.active())


# ----------------------------------------------------------------- contract examples


def test_sorted_input_yields_no_changes_and_no_findings() -> None:
    order = _order("a b c")
    result = _sort(order)
    assert isinstance(result, SortResult)
    assert result.order == order
    assert result.changes == ()
    assert result.findings == ()


def test_tier_buckets_first_wins_puts_the_highest_weight_at_index_zero() -> None:
    order = _order("u1 c1 u2 s1")
    weights = {"u1": 100, "u2": 100, "c1": 800, "s1": 900}
    result = _sort(order, weights, direction=FIRST)
    assert result.order.active() == _ids("s1 c1 u1 u2")  # ui bucket keeps u1 before u2
    assert set(result.changes) == {
        RankChange(M("u1"), 1, 3),
        RankChange(M("u2"), 3, 4),
        RankChange(M("s1"), 4, 1),
    }
    assert result.findings == ()
    assert result.order.enabled == order.enabled


def test_tier_buckets_last_wins_puts_the_highest_weight_last() -> None:
    order = _order("u1 c1 u2 s1")
    weights = {"u1": 100, "u2": 100, "c1": 800, "s1": 900}
    result = _sort(order, weights, direction=LAST)
    assert result.order.active() == _ids("u1 u2 c1 s1")
    assert set(result.changes) == {RankChange(M("u2"), 3, 2), RankChange(M("c1"), 2, 3)}


def test_equal_weights_keep_the_current_order_in_both_directions() -> None:
    order = _order("c a b")
    for direction in (FIRST, LAST):
        result = _sort(order, direction=direction)
        assert result.order == order
        assert result.changes == ()


def test_edge_forces_the_high_side_to_win_with_the_smallest_topological_order() -> None:
    order = _order("a b c")
    result = _sort(order, edges=[_edge("a", "c")], direction=FIRST)
    # preferred (precedence space): c, b, a -> Kahn+heap: b, a, c -> index space: c, a, b
    assert result.order.active() == _ids("c a b")
    assert result.order.wins(M("c"), M("a"), FIRST)
    assert set(result.changes) == {
        RankChange(M("a"), 1, 2),
        RankChange(M("b"), 2, 3),
        RankChange(M("c"), 3, 1),
    }
    assert result.findings == ()
    already = _sort(order, edges=[_edge("a", "c")], direction=LAST)  # c already wins under LAST
    assert already.order == order
    assert already.changes == ()


def test_edge_that_already_holds_is_a_no_op() -> None:
    order = _order("c a b")
    result = _sort(order, edges=[_edge("a", "c")], direction=FIRST)
    assert result.order == order
    assert result.changes == ()


def test_edge_overrides_the_tier_weight() -> None:
    order = _order("a b")
    weights = {"a": 100, "b": 900}
    assert _sort(order, weights).order.active() == _ids("b a")
    pinned = _sort(order, weights, edges=[_edge("b", "a")])
    assert pinned.order.active() == _ids("a b")
    assert pinned.changes == ()
    assert pinned.findings == ()


def test_disabled_entries_keep_their_slots() -> None:
    order = _order("u1 x* c1 y* s1")
    weights = {"u1": 100, "c1": 800, "s1": 900}
    result = _sort(order, weights, direction=FIRST)
    assert result.order == _order("s1 x* c1 y* u1")
    assert set(result.changes) == {RankChange(M("u1"), 1, 3), RankChange(M("s1"), 3, 1)}


def test_edges_touching_inactive_or_unknown_ids_are_ignored() -> None:
    """Resolved ambiguity: resolve_rules produces edges over every known mod, so edges whose
    ends are not both active cannot constrain the sort and must not raise."""
    order = _order("a b* c")
    edges = [_edge("c", "b"), _edge("a", "zzz"), _edge("zzz", "a"), _edge("b", "a")]
    result = _sort(order, edges=edges)
    assert result.order == order
    assert result.changes == ()
    assert result.findings == ()


def test_empty_and_single_orders() -> None:
    empty = LoadOrder((), frozenset())
    assert _sort(empty) == SortResult(empty, (), ())
    single = _order("a")
    assert _sort(single, edges=[_edge("a", "a")]).order == single
    inactive_only = _order("a* b*")
    assert _sort(inactive_only).order == inactive_only


# ----------------------------------------------------------------- cycles


def test_cycle_reports_one_error_finding_drops_its_edges_and_continues() -> None:
    order = _order("a b c")
    edges = [_edge("a", "b"), _edge("b", "a"), _edge("b", "c")]
    result = _sort(order, edges=edges, direction=FIRST)
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.rule_id == CYCLE_RULE
    assert finding.severity == Severity.ERROR
    assert finding.mod_ids == (M("b"), M("a"))  # sorted by preferred rank; c is not a member
    assert "c" not in finding.mod_ids
    # the cycle's edges are dropped, b -> c is still honoured: preferred c, b, a -> b, c, a
    assert result.order.active() == _ids("a c b")
    assert result.order.wins(M("c"), M("b"), FIRST)
    assert result.order.enabled == order.enabled


def test_cycle_result_is_idempotent() -> None:
    order = _order("a b c")
    edges = [_edge("a", "b"), _edge("b", "a"), _edge("b", "c")]
    first = _sort(order, edges=edges)
    second = _sort(first.order, edges=edges)
    assert second.order == first.order
    assert second.changes == ()
    assert [f.mod_ids for f in second.findings] == [f.mod_ids for f in first.findings]


def test_two_disjoint_cycles_cover_exactly_their_members() -> None:
    order = _order("a b c d")
    edges = [_edge("a", "b"), _edge("b", "a"), _edge("c", "d"), _edge("d", "c")]
    result = _sort(order, edges=edges)
    assert 1 <= len(result.findings) <= 2
    assert all(f.rule_id == CYCLE_RULE and f.severity == Severity.ERROR for f in result.findings)
    members = [m for f in result.findings for m in f.mod_ids]
    assert sorted(members) == sorted(_ids("a b c d"))
    assert len(members) == 4
    assert result.order == order  # all edges dropped: the preferred order is the current one
    assert result.changes == ()


def test_cycle_members_are_listed_by_preferred_rank_not_by_edge_order() -> None:
    order = _order("x y z")
    weights = {"x": 100, "y": 900, "z": 500}
    edges = [_edge("y", "x"), _edge("x", "z"), _edge("z", "y")]  # x -> z -> y -> x
    result = _sort(order, weights, edges=edges, direction=FIRST)
    assert len(result.findings) == 1
    assert result.findings[0].mod_ids == (M("x"), M("z"), M("y"))
    assert result.order.active() == _ids("y z x")  # the cycle's edges are dropped, weights rule


def test_cycle_output_identical_over_100_edge_shuffles() -> None:
    """Edge order never leaks into the result: random edges plus a guaranteed two-cycle between
    two active mods, shuffled 100 times, give byte-identical order, changes and findings."""
    rng = random.Random(2024)
    order = _random_order(rng, max_len=10)
    while len(order.active()) < 2:
        order = _random_order(rng, max_len=10)
    weights = {m: rng.choice([100, 500, 900]) for m in order.entries}
    x, y = rng.sample(order.active(), 2)
    edges = [*_random_edges(rng, order, 12), _edge(x, y, "cycle"), _edge(y, x, "cycle")]
    baseline = _sort(order, weights, edges)
    assert baseline.findings, "the fixture must contain at least one cycle"
    assert any({x, y} <= members for members in _cycle_members(baseline.findings))
    for _ in range(100):
        shuffled = edges[:]
        rng.shuffle(shuffled)
        again = _sort(order, weights, shuffled)
        assert again.order == baseline.order
        assert again.changes == baseline.changes
        assert _finding_cores(again.findings) == _finding_cores(baseline.findings)


# ----------------------------------------------------------------- properties


def test_no_edges_seeded_weights_are_monotone_and_ties_are_stable() -> None:
    rng = random.Random(4327)
    for _ in range(200):
        order = _random_order(rng)
        weights = {m: rng.choice([0, 100, 300, 900, 1100]) for m in order.entries}
        for direction in (FIRST, LAST):
            result = _sort(order, weights, direction=direction)
            along = [weights[m] for m in result.order.active()]
            expected = sorted(along, reverse=direction is FIRST)
            assert along == expected
            for w in set(along):
                same_before = [m for m in order.active() if weights[m] == w]
                same_after = [m for m in result.order.active() if weights[m] == w]
                assert same_after == same_before
            assert result.findings == ()


def test_seeded_invariants_idempotence_and_mirror() -> None:
    rng = random.Random(20260929)
    for _ in range(150):
        order = _random_order(rng)
        weights = {m: rng.choice([0, 100, 300, 900, 1100]) for m in order.entries}
        edges = _random_edges(rng, order, rng.randint(0, 8))
        for direction in (FIRST, LAST):
            result = _sort(order, weights, edges, direction)
            assert sorted(result.order.entries) == sorted(order.entries)
            assert result.order.enabled == order.enabled
            for i, m in enumerate(order.entries):
                if not order.is_enabled(m):
                    assert result.order.entries[i] == m
            assert set(result.changes) == _expected_changes(order, result.order)
            assert len(result.changes) == len(set(result.changes))
            _assert_edges_respected(result, edges, direction)
            again = _sort(result.order, weights, edges, direction)
            assert again.order == result.order
            assert again.changes == ()
        mirrored = LoadOrder(tuple(reversed(order.entries)), order.enabled)
        first = _sort(order, weights, edges, FIRST)
        last = _sort(mirrored, weights, edges, LAST)
        assert first.order.active() == tuple(reversed(last.order.active()))
        assert [f.mod_ids for f in first.findings] == [f.mod_ids for f in last.findings]


def test_result_types_are_frozen_values() -> None:
    edge = _edge("a", "b", "because")
    assert edge == PrecedenceEdge(M("a"), M("b"), "because")
    change = RankChange(M("a"), 1, 2)
    with pytest.raises((AttributeError, TypeError)):
        change.new_rank = 3  # ty: ignore[invalid-assignment]
    with pytest.raises((AttributeError, TypeError)):
        edge.reason = "x"  # ty: ignore[invalid-assignment]


# ----------------------------------------------------------------- legacy parity


def _bucket_fn(
    assigned: Mapping[ModId, str], priority: Mapping[str, int]
) -> Callable[[ModId], tuple[int, int]]:
    """The bucket part of the legacy sort key (dd2.py:4346-4351), used only to PROJECT an order
    onto its bucket sequence; the legacy sort itself runs in the oracle."""

    def key(mod: ModId) -> tuple[int, int]:
        cat = assigned.get(mod, "Unassigned")
        return (1 if cat == "Unassigned" else 0, priority.get(cat, 700))

    return key


def _table_weight_fn(table: TierTable, assigned: Mapping[ModId, str]) -> Callable[[ModId], int]:
    return lambda mod: table.for_category(assigned.get(mod)).weight


def _legacy_manager(dd2: Any, state: dict[str, Any]) -> Any:
    """``sorted_order_by_category`` (dd2.py:4327-4353) reads ``self.state``,
    ``self.get_category_priority`` and ``self.sort_name``; the identity sort name makes its
    within-bucket tie-break the mod key."""
    manager = object.__new__(dd2.ModManager)
    manager.state = state
    manager.sort_name = lambda mod: mod
    return manager


@pytest.mark.legacy
def test_bucket_order_matches_legacy_sorted_order_by_category(legacy: LegacyOracle) -> None:
    """Resolved ambiguity: the legacy top-to-bottom order (UI first ... Unassigned last) is the
    precedence-space order, i.e. LAST_WINS index space; FIRST_WINS is its mirror. Only bucket
    sequences are compared because the legacy breaks ties by sort_name and core by current
    position."""
    categories = legacy.module("categories")
    dd2 = legacy.module("dd2")
    rng = random.Random(4327)
    for _ in range(120):
        category_order = list(DEFAULT_CATEGORIES)
        rng.shuffle(category_order)
        customs = rng.sample(CUSTOM_POOL, rng.randint(0, len(CUSTOM_POOL)))
        order = _random_order(rng, max_len=16)
        choices = [*category_order, *customs, "Unassigned", "Unassigned"]
        assigned = {m: rng.choice(choices) for m in order.entries}
        state: dict[str, Any] = {
            "order": list(order.entries),
            "category_order": category_order,
            "custom_categories": customs,
            "categories": {m: c for m, c in assigned.items() if c != "Unassigned"},
        }
        legacy_sorted = _legacy_manager(dd2, state).sorted_order_by_category(
            list(order.active()), state["categories"]
        )
        assert sorted(legacy_sorted) == sorted(order.active())
        bucket = _bucket_fn(
            state["categories"], categories.get_category_priority(state, BASE_PRIORITY, 700)
        )
        legacy_sequence = [bucket(m) for m in legacy_sorted]
        assert legacy_sequence == sorted(legacy_sequence)
        table = TierTable.from_legacy(category_order, customs)
        weight = _table_weight_fn(table, state["categories"])
        last = auto_sort(order, tier_weight=weight, edges=(), direction=LAST)
        assert [bucket(m) for m in last.order.active()] == legacy_sequence
        first = auto_sort(order, tier_weight=weight, edges=(), direction=FIRST)
        assert [bucket(m) for m in first.order.active()] == legacy_sequence[::-1]
        assert last.findings == () and first.findings == ()
