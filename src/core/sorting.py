"""Auto-Sort: a stable tier ordering that also honours declared precedence edges.

Replaces ``dd2.py:4327-4353`` (``sorted_order_by_category``: category bucket, then display name).
Documented divergence: within a tier the CURRENT order is kept (stable) instead of re-sorting
alphabetically, and declared edges (rules file, patch targets) are honoured through a Kahn
topological sort whose heap is keyed by the preferred rank, so the result is the lexicographically
smallest order that satisfies every edge. Everything happens in precedence space (``0`` loses every
conflict, see ``LoadOrder.precedence``) and is mapped back to index space via the direction.

Contradictory edges (cycles) are reported as ONE ``core.sort_cycle`` ERROR finding listing every
mod that lies on a cycle; the edges inside those cycles are dropped and the sort continues, so the
output is total and independent of the order the edges were given in.
"""

import heapq
from collections.abc import Callable, Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Final

from src.core.findings import Finding, Severity
from src.core.ids import ModId
from src.core.load_order import LoadOrder, PriorityDirection

SORT_CYCLE_RULE_ID: Final = "core.sort_cycle"

type _Edge = tuple[ModId, ModId]


@dataclass(frozen=True, slots=True)
class PrecedenceEdge:
    """``high`` must win conflicts against ``low`` (come later in precedence space)."""

    low: ModId
    high: ModId
    reason: str


@dataclass(frozen=True, slots=True)
class RankChange:
    mod: ModId
    old_rank: int
    new_rank: int


@dataclass(frozen=True, slots=True)
class SortResult:
    order: LoadOrder
    changes: tuple[RankChange, ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True, slots=True)
class _Graph:
    """Edges among active mods: ``successors[low]`` holds every ``high`` that must come after it."""

    nodes: tuple[ModId, ...]
    """Active mods in preferred order (index == preferred rank)."""
    successors: Mapping[ModId, frozenset[ModId]]
    reasons: Mapping[_Edge, str]

    def without(self, dropped: AbstractSet[_Edge]) -> _Graph:
        successors = {
            low: frozenset(high for high in highs if (low, high) not in dropped)
            for low, highs in self.successors.items()
        }
        return _Graph(self.nodes, successors, self.reasons)


def _build_graph(nodes: tuple[ModId, ...], edges: Iterable[PrecedenceEdge]) -> _Graph:
    """Keep edges between two distinct active mods; a duplicated edge merges its sorted reasons.

    Merging (instead of keeping the first reason) makes the cycle finding independent of the
    order the edges were given in.
    """
    active = set(nodes)
    successors: dict[ModId, set[ModId]] = {mod: set() for mod in nodes}
    reasons: dict[_Edge, set[str]] = {}
    for edge in edges:
        if edge.low == edge.high or edge.low not in active or edge.high not in active:
            continue
        successors[edge.low].add(edge.high)
        reasons.setdefault((edge.low, edge.high), set()).add(edge.reason)
    frozen = {low: frozenset(highs) for low, highs in successors.items()}
    merged = {key: "; ".join(sorted(texts)) for key, texts in reasons.items()}
    return _Graph(nodes, frozen, merged)


def _reachable(start: ModId, successors: Mapping[ModId, frozenset[ModId]]) -> set[ModId]:
    """Every mod reachable from ``start`` through one or more edges."""
    seen: set[ModId] = set()
    stack = list(successors[start])
    while stack:
        mod = stack.pop()
        if mod not in seen:
            seen.add(mod)
            stack.extend(successors[mod])
    return seen


def _cycle_edges(graph: _Graph) -> tuple[tuple[ModId, ...], frozenset[_Edge]]:
    """The mods lying on a cycle (preferred order) and every edge inside a cyclic component."""
    reach = {mod: _reachable(mod, graph.successors) for mod in graph.nodes}
    members = tuple(mod for mod in graph.nodes if mod in reach[mod])
    dropped = frozenset(
        (low, high)
        for low in members
        for high in graph.successors[low]
        if high in reach[high] and low in reach[high]
    )
    return members, dropped


def _cycle_finding(
    graph: _Graph, members: tuple[ModId, ...], dropped: AbstractSet[_Edge]
) -> Finding:
    rank = {mod: index for index, mod in enumerate(graph.nodes)}
    edges = sorted(dropped, key=lambda edge: (rank[edge[0]], rank[edge[1]]))
    listing = ", ".join(members)
    return Finding(
        rule_id=SORT_CYCLE_RULE_ID,
        severity=Severity.ERROR,
        message=f"Load-order rules contradict each other for {len(members)} mods: {listing}",
        mod_ids=members,
        message_key=SORT_CYCLE_RULE_ID,
        params=(("count", str(len(members))), ("mods", listing)),
        details=tuple(f"{low} -> {high}: {graph.reasons[low, high]}" for low, high in edges),
    )


def _kahn(graph: _Graph) -> list[ModId]:
    """Lexicographically smallest topological order (by preferred rank) of an acyclic graph."""
    indegree = dict.fromkeys(graph.nodes, 0)
    for highs in graph.successors.values():
        for high in highs:
            indegree[high] += 1
    rank = {mod: index for index, mod in enumerate(graph.nodes)}
    heap = [rank[mod] for mod in graph.nodes if indegree[mod] == 0]
    heapq.heapify(heap)
    output: list[ModId] = []
    while heap:
        mod = graph.nodes[heapq.heappop(heap)]
        output.append(mod)
        for high in graph.successors[mod]:
            indegree[high] -= 1
            if indegree[high] == 0:
                heapq.heappush(heap, rank[high])
    if len(output) != len(graph.nodes):
        raise RuntimeError("topological sort stalled on an acyclic graph")
    return output


def _rank_changes(before: LoadOrder, after: LoadOrder) -> tuple[RankChange, ...]:
    old = before.ranks()
    return tuple(
        RankChange(mod, old[mod], new_rank)
        for mod, new_rank in after.ranks().items()
        if old[mod] != new_rank
    )


def auto_sort(
    order: LoadOrder,
    *,
    tier_weight: Callable[[ModId], int],
    edges: Iterable[PrecedenceEdge],
    direction: PriorityDirection,
) -> SortResult:
    """Sort ``order.active()`` by tier weight, keeping the current order within a tier, then edges.

    The preferred sequence is ``active()`` stably sorted by ``(tier_weight, current precedence)``
    in precedence space (low -> high); the Kahn heap keyed by that preferred rank yields the
    lexicographically smallest order satisfying every edge. Cycles produce one ``core.sort_cycle``
    ERROR finding and their edges are dropped. ``FIRST_WINS`` maps the highest precedence to index
    0. Disabled entries keep their slots. Idempotent: an already sorted order yields no changes.
    """
    precedence = order.precedence(direction)
    weights = {mod: tier_weight(mod) for mod in precedence}
    preferred = tuple(sorted(precedence, key=lambda mod: (weights[mod], precedence[mod])))
    graph = _build_graph(preferred, edges)
    findings: tuple[Finding, ...] = ()
    members, dropped = _cycle_edges(graph)
    if members:
        findings = (_cycle_finding(graph, members, dropped),)
        graph = graph.without(dropped)
    sequence = _kahn(graph)
    if direction is PriorityDirection.FIRST_WINS:
        sequence.reverse()
    new_order = order.with_active_sequence(sequence)
    return SortResult(new_order, _rank_changes(order, new_order), findings)
