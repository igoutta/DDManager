"""In-memory doubles of the services the controller drives (no disk besides tmp, no Steam)."""

import builtins
import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.diff import sequence_diff
from src.core.ids import ModId, SaveIdentity
from src.core.legacy_state import StateChanges, StateDoc, parse_state
from src.core.model import ModInfo
from src.services.backup import BackupReason, BackupRecord
from src.services.detection import InstallSnapshot
from src.services.fsutil import FileFingerprint
from src.services.save_patch import PatchPlan, PatchResult
from src.services.save_slots import SaveSlot
from src.services.scan import ScanResult
from src.services.sources import ModLocation
from src.services.state_repo import StateSnapshot
from tests.support.factories import local_mod, workshop_mod

NOW = datetime(2026, 5, 1, 12, 0).astimezone()


def fingerprint(seed: str) -> FileFingerprint:
    return FileFingerprint(hashlib.sha256(seed.encode()).hexdigest(), len(seed), 1)


def build_catalog(mods_dir: Path) -> dict[ModId, ModInfo]:
    """One ``ModInfo`` per folder of ``modding/`` plus two workshop mods."""
    catalog: dict[ModId, ModInfo] = {}
    for folder in sorted(p.name for p in mods_dir.iterdir() if p.is_dir()):
        info = local_mod(folder)
        catalog[info.id] = info
    for key, title in (("2248772895", "The Chorus Workshop"), ("1739565783", "Better UI")):
        info = workshop_mod(key, title=title)
        catalog[info.id] = info
    return catalog


def build_state(
    catalog: Mapping[ModId, ModInfo],
    *,
    enabled: Sequence[str],
    mods_path: Path,
    save_path: Path,
    categories: Mapping[str, str] | None = None,
) -> StateDoc:
    """A ``mod_state.json`` document whose order lists ``enabled`` first, the rest disabled."""
    rest = [key for key in catalog if key not in enabled]
    order = [*enabled, *rest]
    obj = {
        "order": order,
        "enabled": {key: key in enabled for key in order},
        "categories": dict(categories or {}),
        "mods_path": str(mods_path),
        "last_save_path": str(save_path),
        "selected_profile_path": str(save_path.parent),
        "first_run_summary_shown": True,
        "language": "en",
    }
    doc, _ = parse_state(obj)
    return doc


class FakeScanner:
    def __init__(self, catalog: Mapping[ModId, ModInfo]) -> None:
        self.calls = 0
        self.result = ScanResult(
            mods=dict(catalog),
            findings=(),
            shadowed={},
            locations={
                key: ModLocation(info.source_id, key, Path(info.path), Path(info.root))
                for key, info in catalog.items()
            },
        )

    def scan(
        self, install: object, *, cancel: object = None, progress: object = None
    ) -> ScanResult:
        self.calls += 1
        return self.result


class FakeDetector:
    def __init__(self, mods_dir: Path, save_path: Path) -> None:
        self.snapshot = InstallSnapshot(
            steam_roots=(),
            libraries=(),
            game_roots=(),
            local_mod_dirs=(mods_dir,),
            workshop_dirs=(),
            primary_mods_dir=mods_dir,
            mod_roots=(mods_dir,),
            acf_files=(),
            save_files=(save_path,),
            findings=(),
        )

    def detect(self, manual: object, current_mods_path: object) -> InstallSnapshot:
        return self.snapshot


class FakeState:
    """A ``StateRepository`` double: records every ``StateChanges``; can raise on save."""

    def __init__(self, doc: StateDoc) -> None:
        self.doc = doc
        self.fp = fingerprint("state-0")
        self.saves: list[StateChanges] = []
        self.raise_on_save: BaseException | None = None

    def load(self) -> StateSnapshot:
        return StateSnapshot(self.doc, self.fp, "main", True, ())

    def save(
        self, base: StateDoc, changes: StateChanges, *, expected: Any, force: bool = False
    ) -> FileFingerprint:
        if self.raise_on_save is not None and not force:
            raise self.raise_on_save
        self.saves.append(changes)
        self.fp = fingerprint(f"state-{len(self.saves)}")
        return self.fp

    def changed_since(self, fp: object) -> bool:
        return False

    def ensure_pre_upgrade_copy(self) -> bool:
        return False

    def read_language(self) -> str | None:
        return "en"

    def last_order(self):
        for changes in reversed(self.saves):
            if changes.order is not None:
                return changes.order
        return None


class FakeSlots:
    """``SaveSlotService`` double: ``applied`` is what the active save currently lists."""

    def __init__(self, save_path: Path, applied: Sequence[SaveIdentity]) -> None:
        self.save_path = save_path
        self.applied = tuple(applied)
        self.applied_calls = 0

    def slots(self, save_files: Sequence[Path]) -> list[SaveSlot]:
        return [SaveSlot(p, p.parent, 0, "01/05", 32, NOW, False) for p in save_files]

    def applied_entries(self, save_path: Path) -> tuple[SaveIdentity, ...]:
        self.applied_calls += 1
        return self.applied

    def read_week(self, save_path: Path) -> int | None:
        return 32

    def latest(self, save_files: Sequence[Path]) -> Path | None:
        return save_files[0] if save_files else None


class FakeBackups:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.created: list[Path] = []

    def slot_dir(self, save_path: Path) -> Path:
        return self.directory

    def record(self, save_path: Path) -> BackupRecord:
        path = self.directory / f"persist.game.backup.{len(self.created):04d}.json"
        return BackupRecord(path, save_path, NOW, BackupReason.PRE_PATCH, 1, None, "managed")

    def create(
        self, save_path: Path, *, reason: BackupReason, raw: bytes | None = None
    ) -> BackupRecord:
        rec = self.record(save_path)
        self.created.append(rec.path)
        return rec

    def list(self, save_path: Path, *, include_legacy: bool = True) -> builtins.list[BackupRecord]:
        return []

    def latest(self, save_path: Path) -> BackupRecord | None:
        return None


class FakePatcher:
    def __init__(self, backups: FakeBackups, applied: Sequence[SaveIdentity]) -> None:
        self.backups = backups
        self.applied = tuple(applied)
        self.plans: list[tuple[Path, tuple[SaveIdentity, ...]]] = []
        self.applies: list[tuple[PatchPlan, frozenset[str]]] = []

    def plan(self, save_path: Path, entries: Sequence[SaveIdentity]) -> PatchPlan:
        after = tuple(entries)
        self.plans.append((save_path, after))
        return PatchPlan(
            save_path=save_path,
            format_id="fake",
            original=fingerprint("save"),
            before=self.applied,
            after=after,
            diff=sequence_diff(self.applied, after),
            findings=(),
            required_acks=frozenset(),
            patched=b"patched",
        )

    def apply(self, plan: PatchPlan, *, acknowledged: frozenset[str] = frozenset()) -> PatchResult:
        self.applies.append((plan, acknowledged))
        backup = self.backups.create(plan.save_path, reason=BackupReason.PRE_PATCH)
        return PatchResult(plan.save_path, backup, plan.before, plan.after, ())

    def dry_run_diff(self, plan: PatchPlan):
        return plan.diff


class FakeServices:
    """The real ``Services`` for everything not faked; fakes are plain attributes."""

    def __init__(self, real: object, **fakes: object) -> None:
        self._real = real
        self.__dict__.update(fakes)

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)
