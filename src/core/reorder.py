"""Generic selection moves over a visible sequence, and the splice back into the full order.

Ports the shape of ``dd2.py:6684-6712`` (``ModManager.reorder_visible_group``): the UI edits a
*view* (the active list, or one side of the legacy two-list layout) and the result is spliced
back into the full order so that filtered-out / other-side items keep their slots (:func:`splice`).

:func:`move_block` fixes the legacy overshoot. The legacy removed the moved items first and then
inserted them at the ORIGINAL gap index (``dd2.py:6689-6697``), so a downward drag landed one row
per moved item too low: ``[a, b, c, d]`` with ``{a}`` dropped at gap 3 became ``(b, c, d, a)``.
Here the gap is interpreted in the coordinates of the current view and the same drop yields
``(b, c, a, d)``, i.e. the item lands where the drop indicator was drawn.

All functions are pure, total for in-range input and generic over any hashable item type.
"""

from collections import Counter
from collections.abc import Sequence
from collections.abc import Set as AbstractSet


def is_subsequence[T](sub: Sequence[T], full: Sequence[T]) -> bool:
    """True when the items of ``sub`` occur in ``full`` in the same relative order.

    The items need not be adjacent in ``full``; an empty ``sub`` is a subsequence of anything.
    """
    remaining = iter(full)
    return all(item in remaining for item in sub)


def _clamp_gap[T](view: Sequence[T], gap: int) -> int:
    """Clamp an insertion point into ``0..len(view)`` like the legacy did (``dd2.py:6691-6694``)."""
    return min(max(gap, 0), len(view))


def move_block[T](view: Sequence[T], selected: AbstractSet[T], gap: int) -> tuple[T, ...]:
    """Move the selected items of ``view`` to the insertion point ``gap``.

    ``gap`` counts positions in the CURRENT view (``0`` = before the first item, ``len(view)`` =
    after the last one) and is clamped into that range. Selected items keep their relative order
    and gather at the gap; unselected items before the gap stay before it and the others stay
    after it, so dropping a contiguous block inside its own span is a no-op. Items of ``selected``
    that are not in ``view`` are ignored.
    """
    gap = _clamp_gap(view, gap)
    before = tuple(item for item in view[:gap] if item not in selected)
    moved = tuple(item for item in view if item in selected)
    after = tuple(item for item in view[gap:] if item not in selected)
    return before + moved + after


def move_up[T](view: Sequence[T], selected: AbstractSet[T]) -> tuple[T, ...]:
    """Move every contiguous block of selected items one step up; a block already at the top stays.

    Sweeping top-down and swapping each selected item with the unselected item right above it
    moves a whole block by exactly one step and leaves a block that is pinned at the top (or that
    sits directly under a pinned block) where it is.
    """
    items = list(view)
    for index in range(1, len(items)):
        if items[index] in selected and items[index - 1] not in selected:
            items[index - 1], items[index] = items[index], items[index - 1]
    return tuple(items)


def move_down[T](view: Sequence[T], selected: AbstractSet[T]) -> tuple[T, ...]:
    """Mirror of :func:`move_up`: every selected block moves one step down; a bottom block stays."""
    items = list(view)
    for index in range(len(items) - 2, -1, -1):
        if items[index] in selected and items[index + 1] not in selected:
            items[index], items[index + 1] = items[index + 1], items[index]
    return tuple(items)


def move_to_top[T](view: Sequence[T], selected: AbstractSet[T]) -> tuple[T, ...]:
    """Gather the selected items at the top, keeping their relative order."""
    return move_block(view, selected, 0)


def move_to_bottom[T](view: Sequence[T], selected: AbstractSet[T]) -> tuple[T, ...]:
    """Gather the selected items at the bottom, keeping their relative order."""
    return move_block(view, selected, len(view))


def splice[T](full: Sequence[T], slots: AbstractSet[T], new_seq: Sequence[T]) -> tuple[T, ...]:
    """Refill the positions that ``slots`` occupy in ``full`` with ``new_seq``, left to right.

    ``dd2.py:6700-6712`` semantics: items outside ``slots`` keep their positions and the slot
    positions are filled with ``new_seq`` in order. ``new_seq`` must be a rearrangement of the
    items of ``full`` that belong to ``slots``; otherwise ``ValueError`` is raised (the legacy
    would have raised ``StopIteration`` or silently dropped items).
    """
    occupied = [item for item in full if item in slots]
    if Counter(new_seq) != Counter(occupied):
        raise ValueError("new_seq must be a permutation of the items occupying the slots")
    replacements = iter(new_seq)
    return tuple(next(replacements) if item in slots else item for item in full)
