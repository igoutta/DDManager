"""Patching the applied-mods block of a save: ``plan()`` computes, ``apply()`` writes.

The order is compute -> backup -> temp file -> re-validate -> ``os.replace``, with both gates
explicit and the backup made from the EXACT bytes that were patched:

1. ``plan`` reads the save, detects its format, validates it, patches IN MEMORY (the format's
   ``write_applied`` runs its own input/output/round-trip gates) and lists the risks;
2. ``apply`` refuses without every acknowledgement, refuses while the game runs, re-reads the
   save (its sha256 must still be the planned one), backs up those bytes, then writes through
   :func:`~src.services.fsutil.atomic_write_bytes`, re-reading the temp file FROM DISK and
   checking format validity plus the exact applied entries before it replaces the save.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Final

from src.core.diff import SequenceDiff, sequence_diff
from src.core.errors import RoundTripError, SaveFormatError
from src.core.findings import Finding, Severity
from src.core.ids import SaveIdentity
from src.core.saves import SaveFormat, SaveFormatRegistry
from src.services.backup import GAME_IMAGES, BackupReason, BackupRecord, BackupService
from src.services.detection import is_steam_cloud_path
from src.services.errors import (
    GameRunningError,
    SaveLockedError,
    SaveNotFoundError,
    StaleSaveError,
    UnacknowledgedRiskError,
)
from src.services.fsutil import FileFingerprint, atomic_write_bytes
from src.services.ports import ProcessProbe, RunState

ACK_STEAM_CLOUD: Final = "steam_cloud"
ACK_DUPLICATE_IDENTITY: Final = "duplicate_identity"
ACK_NON_DEFAULT_FILENAME: Final = "non_default_filename"
ACK_GAME_STATE_UNKNOWN: Final = "game_state_unknown"
DEFAULT_SAVE_NAME: Final = "persist.game.json"


@dataclass(frozen=True, slots=True)
class PatchPlan:
    """Everything ``apply`` needs; computing it writes nothing."""

    save_path: Path
    format_id: str
    original: FileFingerprint
    before: tuple[SaveIdentity, ...]
    after: tuple[SaveIdentity, ...]
    diff: SequenceDiff[SaveIdentity]
    findings: tuple[Finding, ...]
    required_acks: frozenset[str]
    patched: bytes = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class PatchResult:
    save_path: Path
    backup: BackupRecord
    before: tuple[SaveIdentity, ...]
    after: tuple[SaveIdentity, ...]
    findings: tuple[Finding, ...]


def read_save_bytes(save_path: Path) -> tuple[bytes, FileFingerprint]:
    """The save's bytes and the fingerprint of exactly those bytes."""
    try:
        with save_path.open("rb") as handle:
            raw = handle.read()
            stat = save_path.stat()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as exc:
        raise SaveNotFoundError(f"Save file not found: {save_path}", path=str(save_path)) from exc
    except OSError as exc:
        raise SaveLockedError(f"Cannot read {save_path}: {exc}", path=str(save_path)) from exc
    return raw, FileFingerprint.of_bytes(raw, stat)


def _duplicates(entries: Sequence[SaveIdentity]) -> list[SaveIdentity]:
    seen: set[SaveIdentity] = set()
    repeated: dict[SaveIdentity, None] = {}
    for entry in entries:
        if entry in seen:
            repeated[entry] = None
        seen.add(entry)
    return list(repeated)


class SavePatchService:
    GAME_IMAGES: ClassVar[frozenset[str]] = GAME_IMAGES

    def __init__(
        self, formats: SaveFormatRegistry, backups: BackupService, *, probe: ProcessProbe
    ) -> None:
        self._formats = formats
        self._backups = backups
        self._probe = probe

    # ------------------------------------------------------------------ plan

    def plan(self, save_path: Path, entries: Sequence[SaveIdentity]) -> PatchPlan:
        """Compute the patched bytes in memory; ``required_acks`` lists the risks to accept."""
        raw, fingerprint = read_save_bytes(save_path)
        fmt = self._formats.detect(raw)
        fmt.check(raw)
        if not fmt.writable:
            raise SaveFormatError(
                f"The {fmt.format_id} format is read-only.", code="read_only_format"
            )
        wanted = tuple(entries)
        before = fmt.read_applied(raw)
        patched = fmt.write_applied(raw, wanted)
        after = fmt.read_applied(patched)
        findings, acks = self._risks(save_path, wanted)
        return PatchPlan(
            save_path=save_path,
            format_id=fmt.format_id,
            original=fingerprint,
            before=before,
            after=after,
            diff=sequence_diff(before, after),
            findings=tuple(findings),
            required_acks=frozenset(acks),
            patched=patched,
        )

    def _risks(
        self, save_path: Path, entries: tuple[SaveIdentity, ...]
    ) -> tuple[list[Finding], set[str]]:
        findings: list[Finding] = []
        acks: set[str] = set()
        if not entries:
            findings.append(
                Finding.warning(
                    "save.empty_entries", "No mods are active: the save will list none."
                )
            )
        if is_steam_cloud_path(save_path):
            acks.add(ACK_STEAM_CLOUD)
            findings.append(
                Finding.warning(
                    "save.steam_cloud",
                    "This save lives in the Steam Cloud folder; Steam may overwrite the patch.",
                )
            )
        duplicates = _duplicates(entries)
        if duplicates:
            acks.add(ACK_DUPLICATE_IDENTITY)
            names = tuple(f"{d.name} | {d.source}" for d in duplicates)
            findings.append(
                Finding.at(
                    Severity.WARNING,
                    "save.duplicate_identity",
                    "Several mods share one save identity; the game will treat them as one.",
                    details=names,
                )
            )
        if save_path.name != DEFAULT_SAVE_NAME:
            acks.add(ACK_NON_DEFAULT_FILENAME)
            findings.append(
                Finding.warning(
                    "save.non_default_filename",
                    f"The file is not called {DEFAULT_SAVE_NAME}; the game will not read it.",
                )
            )
        self._game_findings(findings, acks)
        return findings, acks

    def _game_findings(self, findings: list[Finding], acks: set[str]) -> None:
        state = self._probe.find(GAME_IMAGES)
        if state is RunState.RUNNING:
            findings.append(
                Finding.error("save.game_running", "Darkest Dungeon is running; close it first.")
            )
        elif state is RunState.UNKNOWN:
            acks.add(ACK_GAME_STATE_UNKNOWN)
            findings.append(
                Finding.warning(
                    "save.game_state_unknown", "Could not tell whether the game is running."
                )
            )

    # ------------------------------------------------------------------ apply

    def apply(self, plan: PatchPlan, *, acknowledged: frozenset[str] = frozenset()) -> PatchResult:
        """Write ``plan.patched``; every gate runs before the first byte of the save changes."""
        state = self._probe.find(GAME_IMAGES)
        if state is RunState.RUNNING:
            raise GameRunningError("Darkest Dungeon is running; close it before patching a save.")
        required = set(plan.required_acks)
        if state is RunState.UNKNOWN:
            required.add(ACK_GAME_STATE_UNKNOWN)
        missing = required - acknowledged
        if missing:
            raise UnacknowledgedRiskError(
                "Risks were not acknowledged: " + ", ".join(sorted(missing)), missing=missing
            )
        raw, _ = read_save_bytes(plan.save_path)
        if hashlib.sha256(raw).hexdigest() != plan.original.sha256:
            raise StaleSaveError(
                "The save changed since the plan was made; plan again.", path=str(plan.save_path)
            )
        fmt = self._formats.get(plan.format_id)
        backup = self._backups.create(plan.save_path, reason=BackupReason.PRE_PATCH, raw=raw)
        atomic_write_bytes(plan.save_path, plan.patched, verify=_verifier(fmt, plan.after))
        return PatchResult(plan.save_path, backup, plan.before, plan.after, plan.findings)

    def dry_run_diff(self, plan: PatchPlan) -> SequenceDiff[SaveIdentity]:
        return plan.diff


def _verifier(fmt: SaveFormat, expected: tuple[SaveIdentity, ...]) -> Callable[[bytes], None]:
    def verify(data: bytes) -> None:
        fmt.check(data)
        if fmt.read_applied(data) != expected:
            raise RoundTripError(
                "The bytes written to disk do not read back the planned entries.",
                code="entries_mismatch",
            )

    return verify
