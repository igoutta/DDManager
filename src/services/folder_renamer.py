"""Executing a :class:`~src.core.folder_order.RenamePlan` on disk, two-phase and reversible.

The execution half of "Apply order": every folder is first moved to
``__temp__<timestamp>__<old>`` and only then to its final name, because targets routinely equal
other steps' sources.  On ANY failure everything already moved (both phases) is moved back and
:class:`RenameFailedError` reports whether the rollback was complete (``details["rolled_back"]``)
and which folders could not be put back (``details["stuck"]``).  A plan whose
destination already exists on disk is refused BEFORE the first rename.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.core.folder_order import RenamePlan, RenameStep
from src.core.ids import ModId
from src.services.errors import RenameFailedError
from src.services.fsutil import backup_timestamp
from src.services.ports import Clock


@dataclass(frozen=True, slots=True)
class RenameResult:
    renamed: tuple[RenameStep, ...]
    rekey: Mapping[ModId, ModId]


@dataclass(slots=True)
class _Move:
    """One folder's journey: ``origin`` -> ``temp`` -> ``final``; ``where`` is where it is now."""

    step: RenameStep
    origin: Path
    temp: Path
    final: Path
    where: Path


class FolderRenamer:
    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    def execute(
        self, plan: RenamePlan, mods_root: Path, *, locations: Mapping[ModId, Path]
    ) -> RenameResult:
        """Rename every step of ``plan``; all of it or (after rollback) none of it."""
        if not plan.steps:
            return RenameResult((), dict(plan.rekey))
        moves = self._moves(plan, mods_root, locations)
        self._check(moves)
        self._run(moves)
        return RenameResult(plan.steps, dict(plan.rekey))

    # ------------------------------------------------------------------ preparation

    def _moves(
        self, plan: RenamePlan, mods_root: Path, locations: Mapping[ModId, Path]
    ) -> list[_Move]:
        token = backup_timestamp(self._clock.now())
        used: set[Path] = set()
        moves: list[_Move] = []
        for step in plan.steps:
            origin = locations.get(step.mod, mods_root / step.old_name)
            parent = origin.parent
            moves.append(
                _Move(
                    step,
                    origin,
                    self._temp_path(parent, token, step.old_name, used),
                    parent / step.new_name,
                    origin,
                )
            )
        return moves

    def _temp_path(self, parent: Path, token: str, old_name: str, used: set[Path]) -> Path:
        """``__temp__<ts>__<old>``, counter-suffixed while taken."""
        candidate = parent / f"__temp__{token}__{old_name}"
        counter = 2
        while candidate.exists() or candidate in used:
            candidate = parent / f"__temp__{token}__{counter}__{old_name}"
            counter += 1
        used.add(candidate)
        return candidate

    def _check(self, moves: list[_Move]) -> None:
        """Refuse before touching anything: missing sources and destinations already taken."""
        sources = {_key(move.origin) for move in moves}
        for move in moves:
            if not move.origin.is_dir():
                raise self._refused(f"Folder {move.origin} no longer exists.", move.origin)
            taken = move.final.exists() and _key(move.final) not in sources
            if taken:
                raise self._refused(f"{move.final} already exists.", move.final)

    def _refused(self, message: str, path: Path) -> RenameFailedError:
        return RenameFailedError(
            message + " No folder was renamed.", rolled_back=True, stuck=[], path=str(path)
        )

    # ------------------------------------------------------------------ execution

    def _run(self, moves: list[_Move]) -> None:
        try:
            for move in moves:
                _move(move, move.temp)
            for move in moves:
                _move(move, move.final)
        except OSError as exc:
            stuck = self._rollback(moves)
            raise RenameFailedError(
                f"Renaming failed: {exc}."
                + (
                    " Everything was put back."
                    if not stuck
                    else " Some folders could not be put back."
                ),
                rolled_back=not stuck,
                stuck=stuck,
            ) from exc

    def _rollback(self, moves: list[_Move]) -> list[str]:
        """Phase-2 results back to their temp names first, then every temp name to its origin."""
        stuck: list[str] = []
        for move in reversed(moves):
            if move.where == move.final:
                _try_move(move, move.temp, stuck)
        for move in reversed(moves):
            if move.where == move.temp:
                _try_move(move, move.origin, stuck)
        return stuck


def _key(path: Path) -> str:
    return str(path.absolute()).casefold()


def _move(move: _Move, destination: Path) -> None:
    move.where.rename(destination)
    move.where = destination


def _try_move(move: _Move, destination: Path, stuck: list[str]) -> None:
    try:
        _move(move, destination)
    except OSError:
        stuck.append(str(move.where))
