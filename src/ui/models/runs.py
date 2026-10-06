"""Row-range helpers shared by the models."""

from collections.abc import Iterable


def contiguous_runs(rows: Iterable[int]) -> list[tuple[int, int]]:
    """Inclusive ``(first, last)`` runs of the distinct row numbers, ascending."""
    runs: list[tuple[int, int]] = []
    for row in sorted(set(rows)):
        if runs and runs[-1][1] == row - 1:
            runs[-1] = (runs[-1][0], row)
        else:
            runs.append((row, row))
    return runs
