"""The load order value type: ``mod_state.json`` "order" plus the enabled set, with pure edits.

``entries`` mirrors the legacy ``state["order"]`` list (interleaved; disabled and missing mods
keep their slots) and :meth:`LoadOrder.active` is the sequence the save patcher writes as
``applied_ugcs_1_0`` (the legacy ``enabled_mods`` filter, ``dd2.py:1754``). Every edit acts on
``active()`` through :mod:`src.core.reorder` and is spliced back over the active slots, so
inactive entries never move (the legacy ``reorder_visible_group`` splice, ``dd2.py:6700-6712``).

Documented divergences from the legacy:

* :meth:`LoadOrder.enable` with ``at=None`` appends after the LAST active entry (the legacy click
  toggle re-enabled a mod in its remembered slot); with a gap it matches the legacy cross-side
  drag ``move_selection_between_sides`` (``dd2.py:6742-6766``).
* :meth:`LoadOrder.disable` keeps the slot in ``entries`` (the legacy re-slotted the mod at the
  end of the disabled list).
* :meth:`LoadOrder.reconcile` never prunes nor re-sorts (``dd2.py:6044-6050`` dropped saved mods
  missing from disk); new folders are appended sorted by ``casefold`` (legacy: ``str.lower``).
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from src.core import reorder
from src.core.ids import ModId, SaveIdentity


class PriorityDirection(StrEnum):
    """Which end of the active list wins a file conflict."""

    FIRST_WINS = "first_wins"
    LAST_WINS = "last_wins"


@dataclass(frozen=True, slots=True)
class PrioritySetting:
    """The configured direction and whether the user has verified it in game."""

    direction: PriorityDirection = PriorityDirection.FIRST_WINS
    verified: bool = True


class MoveOp(StrEnum):
    """Selection moves offered by the UI, all over ``active()``."""

    TOP = "top"
    UP = "up"
    DOWN = "down"
    BOTTOM = "bottom"


type _Move = Callable[[Sequence[ModId], AbstractSet[ModId]], tuple[ModId, ...]]

_MOVES: Final[Mapping[MoveOp, _Move]] = {
    MoveOp.TOP: reorder.move_to_top,
    MoveOp.UP: reorder.move_up,
    MoveOp.DOWN: reorder.move_down,
    MoveOp.BOTTOM: reorder.move_to_bottom,
}


def _unique(ids: Iterable[ModId]) -> tuple[ModId, ...]:
    """The ids in first-seen order without repeats."""
    return tuple(dict.fromkeys(ids))


def _casefold_key(mod: ModId) -> tuple[str, str]:
    return (mod.casefold(), mod)


@dataclass(frozen=True, slots=True)
class LoadOrder:
    """An immutable load order: ``entries`` (unique) and the ``enabled`` subset of them."""

    entries: tuple[ModId, ...]
    enabled: frozenset[ModId]

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        enabled = frozenset(self.enabled)
        if len(set(entries)) != len(entries):
            raise ValueError("load order entries must be unique")
        unknown = enabled - set(entries)
        if unknown:
            raise ValueError(f"enabled ids missing from entries: {', '.join(sorted(unknown))}")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "enabled", enabled)

    # ------------------------------------------------------------------ views

    def active(self) -> tuple[ModId, ...]:
        """Enabled entries in order (``dd2.py:1754``): what gets written into the save."""
        return tuple(mod for mod in self.entries if mod in self.enabled)

    def inactive(self) -> tuple[ModId, ...]:
        return tuple(mod for mod in self.entries if mod not in self.enabled)

    def is_enabled(self, mod: ModId) -> bool:
        return mod in self.enabled

    def rank(self, mod: ModId) -> int | None:
        """1-based position in ``active()``; ``None`` when inactive or absent."""
        return self.ranks().get(mod)

    def ranks(self) -> dict[ModId, int]:
        return {mod: index + 1 for index, mod in enumerate(self.active())}

    def precedence(self, direction: PriorityDirection) -> dict[ModId, int]:
        """Conflict strength per active mod: ``0`` loses every conflict.

        ``FIRST_WINS`` gives rank 1 the highest value; ``LAST_WINS`` gives it ``0``.
        """
        ranks = self.ranks()
        count = len(ranks)
        if direction is PriorityDirection.FIRST_WINS:
            return {mod: count - rank for mod, rank in ranks.items()}
        return {mod: rank - 1 for mod, rank in ranks.items()}

    def wins(self, a: ModId, b: ModId, direction: PriorityDirection) -> bool:
        """True when active ``a`` beats active ``b``; False whenever either one is not active."""
        precedence = self.precedence(direction)
        return a in precedence and b in precedence and precedence[a] > precedence[b]

    # ------------------------------------------------------------------ edits

    def move(self, ids: AbstractSet[ModId], op: MoveOp) -> LoadOrder:
        """Apply a selection move over ``active()`` and splice it back into ``entries``."""
        return self.with_active_sequence(_MOVES[op](self.active(), ids))

    def move_to(self, ids: AbstractSet[ModId], gap: int) -> LoadOrder:
        """Drop the selection at insertion point ``gap`` of ``active()`` (see ``move_block``)."""
        return self.with_active_sequence(reorder.move_block(self.active(), ids, gap))

    def enable(self, ids: Sequence[ModId], at: int | None = None) -> LoadOrder:
        """Enable ``ids`` (in the given order) at active gap ``at``, or after the last active entry.

        Port of ``dd2.py:6742-6766`` + ``6684-6712`` for a disabled -> enabled drag: the gap is
        clamped into ``0..len(active())`` and the moved ids are spliced over the slots of the
        active mods plus their own. Unknown ids raise ``ValueError``; already-enabled ids are
        ignored. ``at=None`` appends (documented divergence from the legacy click toggle).
        """
        ordered = _unique(ids)
        unknown = [mod for mod in ordered if mod not in self.entries]
        if unknown:
            raise ValueError(f"unknown mod ids: {', '.join(unknown)}")
        new = tuple(mod for mod in ordered if mod not in self.enabled)
        if not new:
            return self
        active = self.active()
        gap = len(active) if at is None else min(max(at, 0), len(active))
        sequence = (*active[:gap], *new, *active[gap:])
        enabled = self.enabled | frozenset(new)
        return LoadOrder(reorder.splice(self.entries, enabled, sequence), enabled)

    def disable(self, ids: AbstractSet[ModId]) -> LoadOrder:
        """Disable ``ids``, keeping their slots in ``entries``; inactive/unknown ids are ignored."""
        return LoadOrder(self.entries, self.enabled.difference(ids))

    def with_active_sequence(self, seq: Sequence[ModId]) -> LoadOrder:
        """Replace ``active()`` by ``seq`` (a permutation of it, else ``ValueError``) in place."""
        return LoadOrder(reorder.splice(self.entries, self.enabled, seq), self.enabled)

    def forget(self, ids: AbstractSet[ModId]) -> LoadOrder:
        """Remove ``ids`` from ``entries`` (the only way the order shrinks); unknown ids ignored."""
        entries = tuple(mod for mod in self.entries if mod not in ids)
        return LoadOrder(entries, self.enabled.difference(ids))

    def reconcile(self, present: Iterable[ModId]) -> Reconciliation:
        """Merge the folders found on disk (``dd2.py:6044-6050``) without pruning or re-sorting.

        Known entries keep their order and flags; unknown present ids are appended, disabled and
        sorted by ``casefold`` (ties broken by the raw id so the result is deterministic).
        ``missing`` lists the entries that are not present, in entries order.
        """
        on_disk = frozenset(present)
        known = set(self.entries)
        added = tuple(sorted((mod for mod in on_disk if mod not in known), key=_casefold_key))
        missing = tuple(mod for mod in self.entries if mod not in on_disk)
        order = LoadOrder((*self.entries, *added), self.enabled)
        return Reconciliation(order, added, missing)


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Result of :meth:`LoadOrder.reconcile`: the merged order plus what changed on disk."""

    order: LoadOrder
    added: tuple[ModId, ...]
    missing: tuple[ModId, ...]


def applied_entries(
    order: LoadOrder,
    identities: Mapping[ModId, SaveIdentity],
    *,
    missing: AbstractSet[ModId] = frozenset(),
) -> tuple[SaveIdentity, ...]:
    """``active()`` without ``missing`` mapped to save identities.

    ``missing`` holds the mods whose folder is not on disk: they are never written into a save,
    not even from a cached identity (contract §4).  ``ValueError`` names every other active id
    without an identity.
    """
    active = missing_active(order, missing, present=True)
    unknown = [mod for mod in active if mod not in identities]
    if unknown:
        raise ValueError(f"applied entries: no identity known for mods {', '.join(unknown)}")
    return tuple(identities[mod] for mod in active)


def missing_active(
    order: LoadOrder, missing: AbstractSet[ModId], *, present: bool = False
) -> tuple[ModId, ...]:
    """The active mods that are in ``missing`` (or, with ``present``, those that are not)."""
    return tuple(mod for mod in order.active() if (mod in missing) != present)
