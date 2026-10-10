"""Managed save backups, kept OUTSIDE the Steam Cloud folder.

DD Manager 0.2.x wrote ``persist.game.backup.<ts>.json`` next to the save, inside the folder
Steam Cloud syncs, and never pruned them.  New backups go to
``<data>/backups/<save dir name>-<hash>/`` with the same file name pattern plus an ``index.json``;
the backups beside the save are still listed (never pruned, never deleted).

``restore`` validates the backup first, backs up what it is about to overwrite and writes through
the atomic path, so the restored file has a FRESH mtime (a plain ``shutil.copy2`` would preserve
the old one, which hides the restore from Steam).
"""

import builtins
import hashlib
import logging
import re
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from src.core.errors import DDManagerError
from src.core.findings import Finding
from src.core.saves import SaveFormatRegistry
from src.services.app_paths import AppPaths
from src.services.backup_index import (
    IndexEntry,
    read_index,
    reconcile_index,
    write_index_quietly,
)
from src.services.errors import (
    BackupInvalidError,
    BackupNotFoundError,
    GameRunningError,
    SaveNotFoundError,
)
from src.services.fsutil import atomic_write_bytes, backup_timestamp, unique_path
from src.services.ports import Clock, ProcessProbe, RunState
from src.services.settings_repo import RetentionPolicy

_LOG: Final = logging.getLogger(__name__)

BESIDE_SAVE_BACKUP_RE: Final = re.compile(
    r"^persist\.game\.backup\.(\d{8}-\d{6})(?:-(\d+))?\.json$"
)
GAME_IMAGES: Final = frozenset({"darkest.exe", "darkestdungeon.exe", "darkest"})
_STAMP_FORMAT: Final = "%Y%m%d-%H%M%S"


class BackupReason(StrEnum):
    PRE_PATCH = "pre-patch"
    PRE_RESTORE = "pre-restore"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class BackupRecord:
    path: Path
    save_path: Path
    created: datetime
    reason: BackupReason | None
    size: int
    sha256: str | None
    location: Literal["managed", "beside_save"]


@dataclass(frozen=True, slots=True)
class RestoreResult:
    target: Path
    pre_restore_backup: BackupRecord
    restored_from: BackupRecord


@dataclass(frozen=True, slots=True)
class PruneReport:
    deleted: tuple[Path, ...]
    kept: tuple[Path, ...]
    findings: tuple[Finding, ...]


def _reason(value: str | None) -> BackupReason | None:
    try:
        return BackupReason(value) if value else None
    except ValueError:
        return None


class BackupService:
    def __init__(
        self,
        paths: AppPaths,
        formats: SaveFormatRegistry,
        *,
        clock: Clock,
        probe: ProcessProbe,
        policy: RetentionPolicy = RetentionPolicy(),  # noqa: B008 - frozen value object
    ) -> None:
        self._paths = paths
        self._formats = formats
        self._clock = clock
        self._probe = probe
        self._policy = policy

    # ------------------------------------------------------------------ locations

    def slot_dir(self, save_path: Path) -> Path:
        """``backups/<save dir name>-<sha1(casefold(abs dir))[:8]>`` (stable per save folder)."""
        save_dir = save_path.absolute().parent
        digest = hashlib.sha1(str(save_dir).casefold().encode("utf-8"), usedforsecurity=False)
        return self._paths.backups_dir / f"{save_dir.name}-{digest.hexdigest()[:8]}"

    # ------------------------------------------------------------------ create

    def create(
        self, save_path: Path, *, reason: BackupReason, raw: bytes | None = None
    ) -> BackupRecord:
        """Write a backup of ``raw`` (the exact bytes about to be replaced) or of the file."""
        data = raw if raw is not None else self._read(save_path)
        slot = self.slot_dir(save_path)
        slot.mkdir(parents=True, exist_ok=True)
        now = self._clock.now()
        target = unique_path(slot / f"persist.game.backup.{backup_timestamp(now)}.json")
        atomic_write_bytes(target, data)
        entry = IndexEntry(
            target.name, now.isoformat(), reason.value, len(data), hashlib.sha256(data).hexdigest()
        )
        entries = self._index_add(slot, save_path, entry)
        record = self._managed_record(target, save_path, entry)
        managed = [self._managed_record(slot / e.file, save_path, e) for e in entries.values()]
        report = self._prune_records(save_path, managed, protect=(record.path,), dry_run=False)
        for finding in report.findings:
            _LOG.warning("%s", finding.message)
        return record

    def _read(self, save_path: Path) -> bytes:
        try:
            return save_path.read_bytes()
        except FileNotFoundError as exc:
            raise SaveNotFoundError(
                f"Save file not found: {save_path}", path=str(save_path)
            ) from exc
        except OSError as exc:
            raise SaveNotFoundError(f"Cannot read {save_path}: {exc}", path=str(save_path)) from exc

    def _index_add(self, slot: Path, save_path: Path, entry: IndexEntry) -> dict[str, IndexEntry]:
        entries = self._live_entries(slot)
        entries[entry.file] = entry
        write_index_quietly(slot, save_path, entries)
        return entries

    def _live_entries(self, slot: Path) -> dict[str, IndexEntry]:
        """The index rebuilt against the directory listing (the listing is the truth)."""
        return reconcile_index(slot, self._matching(slot), self._stamp)

    # ------------------------------------------------------------------ list

    def list(
        self, save_path: Path, *, include_beside_save: bool = True
    ) -> builtins.list[BackupRecord]:
        """Newest first; managed records carry index metadata, beside-save ones sit by the save."""
        records = self._managed(save_path)
        if include_beside_save:
            records.extend(self._beside_save(save_path))
        return sorted(records, key=self._sort_key, reverse=True)

    def latest(self, save_path: Path) -> BackupRecord | None:
        records = self.list(save_path)
        return records[0] if records else None

    def _sort_key(self, record: BackupRecord) -> tuple[datetime, int, str]:
        match = BESIDE_SAVE_BACKUP_RE.match(record.path.name)
        counter = int(match.group(2) or 1) if match else 1
        return (record.created, counter, record.path.name)

    def _managed(self, save_path: Path) -> builtins.list[BackupRecord]:
        slot = self.slot_dir(save_path)
        index, _ = read_index(slot)
        records: list[BackupRecord] = []
        for path in self._matching(slot):
            entry = index.get(path.name)
            if entry is None:
                entry = IndexEntry(path.name, "", None, 0, None)
            records.append(self._managed_record(path, save_path, entry))
        return records

    def _beside_save(self, save_path: Path) -> builtins.list[BackupRecord]:
        records: list[BackupRecord] = []
        for path in self._matching(save_path.absolute().parent):
            created = self._stamp(path.name) or self._clock.now()
            records.append(
                BackupRecord(path, save_path, created, None, _size(path), None, "beside_save")
            )
        return records

    def _matching(self, directory: Path) -> builtins.list[Path]:
        try:
            names = sorted(entry for entry in directory.iterdir() if entry.is_file())
        except OSError:
            return []
        return [path for path in names if BESIDE_SAVE_BACKUP_RE.match(path.name)]

    def _managed_record(self, path: Path, save_path: Path, entry: IndexEntry) -> BackupRecord:
        created = self._parse_created(entry.created) or self._stamp(path.name) or self._clock.now()
        size = entry.size or _size(path)
        return BackupRecord(
            path, save_path, created, _reason(entry.reason), size, entry.sha256, "managed"
        )

    def _parse_created(self, text: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(text) if text else None
        except ValueError:
            return None
        if parsed is not None and parsed.tzinfo is None:
            return parsed.replace(tzinfo=self._clock.now().tzinfo)
        return parsed

    def _stamp(self, name: str) -> datetime | None:
        match = BESIDE_SAVE_BACKUP_RE.match(name)
        if match is None:
            return None
        naive = datetime.strptime(match.group(1), _STAMP_FORMAT)  # noqa: DTZ007 - tz set below
        return naive.replace(tzinfo=self._clock.now().tzinfo)

    # ------------------------------------------------------------------ verify

    def verify(self, record: BackupRecord) -> builtins.list[Finding]:
        """ERROR findings when the backup is missing, altered or no longer a valid save."""
        try:
            raw = record.path.read_bytes()
        except OSError as exc:
            return [
                Finding.error("backup.missing", f"Backup {record.path.name} is unreadable: {exc}")
            ]
        findings: list[Finding] = []
        if record.sha256 and hashlib.sha256(raw).hexdigest() != record.sha256:
            findings.append(
                Finding.error(
                    "backup.altered", f"Backup {record.path.name} changed since creation."
                )
            )
        try:
            self._formats.detect(raw).check(raw)
        except DDManagerError as exc:
            findings.append(
                Finding.error(
                    "backup.invalid", f"Backup {record.path.name} is not a valid save: {exc}"
                )
            )
        return findings

    # ------------------------------------------------------------------ prune

    def prune(
        self, save_path: Path, *, protect: Collection[Path] = (), dry_run: bool = False
    ) -> PruneReport:
        """Delete managed backups outside ALL of: newest ``keep_last``, newest ``min_keep``, newer
        than ``keep_days``, ``protect``.  Beside-save backups are never touched."""
        return self._prune_records(save_path, self._managed(save_path), protect, dry_run)

    def _prune_records(
        self,
        save_path: Path,
        records: builtins.list[BackupRecord],
        protect: Collection[Path],
        dry_run: bool,
    ) -> PruneReport:
        managed = sorted(records, key=self._sort_key, reverse=True)
        protected = {p.absolute() for p in protect}
        now = self._clock.now()
        deleted: list[Path] = []
        kept: list[Path] = []
        findings: list[Finding] = []
        for rank, record in enumerate(managed):
            if self._must_keep(rank, record, protected, now):
                kept.append(record.path)
            elif dry_run or self._delete(record.path, findings):
                deleted.append(record.path)
            else:
                kept.append(record.path)
        if deleted and not dry_run:
            self._index_drop(save_path)
        return PruneReport(tuple(deleted), tuple(kept), tuple(findings))

    def _must_keep(
        self, rank: int, record: BackupRecord, protected: set[Path], now: datetime
    ) -> bool:
        if rank < max(self._policy.keep_last, self._policy.min_keep):
            return True
        if record.path.absolute() in protected:
            return True
        return now - record.created < timedelta(days=self._policy.keep_days)

    def _delete(self, path: Path, findings: builtins.list[Finding]) -> bool:
        try:
            path.unlink()
        except OSError as exc:
            findings.append(Finding.warning("backup.prune_failed", f"Cannot delete {path}: {exc}"))
            return False
        return True

    def _index_drop(self, save_path: Path) -> None:
        slot = self.slot_dir(save_path)
        write_index_quietly(slot, save_path, self._live_entries(slot))

    # ------------------------------------------------------------------ restore

    def restore(self, record: BackupRecord, *, target: Path | None = None) -> RestoreResult:
        """Validate the backup, back up the current target, then atomically replace it."""
        destination = target if target is not None else record.save_path
        if self._probe.find(GAME_IMAGES) is RunState.RUNNING:
            raise GameRunningError("Darkest Dungeon is running; close it before restoring a save.")
        raw = self._read_backup(record)
        check = self._checker(raw, record)
        pre = self.create(destination, reason=BackupReason.PRE_RESTORE)
        atomic_write_bytes(destination, raw, verify=check)
        return RestoreResult(destination, pre, record)

    def _read_backup(self, record: BackupRecord) -> bytes:
        try:
            return record.path.read_bytes()
        except OSError as exc:
            raise BackupNotFoundError(
                f"Backup {record.path} cannot be read: {exc}", path=str(record.path)
            ) from exc

    def _checker(self, raw: bytes, record: BackupRecord) -> Callable[[bytes], None]:
        try:
            fmt = self._formats.detect(raw)
            fmt.check(raw)
        except DDManagerError as exc:
            raise BackupInvalidError(
                f"Backup {record.path.name} is not a valid save: {exc}", path=str(record.path)
            ) from exc
        return fmt.check


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
