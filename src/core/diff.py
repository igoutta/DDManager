"""Membership and position diff between two sequences (Auto-Sort preview, patch preview)."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SequenceDiff[T]:
    """``added``/``moved`` in ``after`` order, ``removed`` in ``before`` order."""

    added: tuple[T, ...]
    removed: tuple[T, ...]
    moved: tuple[tuple[T, int, int], ...]
    """``(item, old_index, new_index)`` for items present in both sequences whose index changed."""

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.moved)


def _first_indexes[T](seq: Sequence[T]) -> dict[T, int]:
    indexes: dict[T, int] = {}
    for index, item in enumerate(seq):
        indexes.setdefault(item, index)
    return indexes


def sequence_diff[T](before: Sequence[T], after: Sequence[T]) -> SequenceDiff[T]:
    """Diff two sequences of hashable items (a repeated item counts by its first occurrence)."""
    before_index = _first_indexes(before)
    after_index = _first_indexes(after)
    added = tuple(item for item in after_index if item not in before_index)
    removed = tuple(item for item in before_index if item not in after_index)
    moved = tuple(
        (item, before_index[item], new_index)
        for item, new_index in after_index.items()
        if item in before_index and before_index[item] != new_index
    )
    return SequenceDiff(added, removed, moved)
