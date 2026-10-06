"""Worker-side scan and the pure steps after it (classify, tiers); no Qt."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.core.classify import suggest_category
from src.core.identity import category_memory_keys
from src.core.ids import ModId
from src.core.legacy_state import StateDoc, StateSettings
from src.core.model import ModInfo
from src.core.rules_data import ResolvedRules
from src.core.tiers import Tier, TierTable, resolve_tier
from src.services.bootstrap import Services
from src.services.detection import InstallSnapshot, ManualPaths
from src.services.ports import CancelToken
from src.services.save_slots import SaveSlot
from src.services.scan import ScanResult


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    install: InstallSnapshot
    scan: ScanResult
    slots: tuple[SaveSlot, ...]
    save_path: Path | None
    last_backup: datetime | None


@dataclass(frozen=True, slots=True)
class Classified:
    """Silent first-time categorisation; it never touches the order."""

    categories: dict[ModId, str] = field(default_factory=dict)
    attempted: set[ModId] = field(default_factory=set)
    memory: dict[str, str] = field(default_factory=dict)


def optional_path(text: str) -> Path | None:
    return Path(text) if text.strip() else None


def manual_paths(settings: StateSettings) -> ManualPaths:
    return ManualPaths(
        game_root=optional_path(settings.manual_game_root),
        local_mods=optional_path(settings.manual_local_mods_path),
        workshop_mods=optional_path(settings.manual_workshop_mods_path),
    )


def configured_save(settings: StateSettings) -> Path | None:
    """The state's selected save, else its last save, when the file still exists."""
    for text in (settings.selected_profile_path, settings.last_save_path):
        candidate = optional_path(text)
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def choose_save(
    services: Services, settings: StateSettings, install: InstallSnapshot
) -> Path | None:
    """The configured save, else the newest detected one."""
    return configured_save(settings) or services.slots.latest(install.save_files)


def run_scan(services: Services, settings: StateSettings, token: CancelToken) -> ScanOutcome:
    """Detect, scan, list the save slots and find the last backup (a worker-thread function)."""
    install = services.detector.detect(manual_paths(settings), optional_path(settings.mods_path))
    scan = services.scanner.scan(install, cancel=token)
    slots = tuple(services.slots.slots(install.save_files))
    save = choose_save(services, settings, install)
    record = services.backups.latest(save) if save is not None else None
    return ScanOutcome(install, scan, slots, save, record.created if record else None)


def _remembered(info: ModInfo, memory: Mapping[str, str]) -> str | None:
    return next((memory[key] for key in category_memory_keys(info) if key in memory), None)


def classify_new(mods: Mapping[ModId, ModInfo], doc: StateDoc) -> Classified:
    """Assign a category to every mod that has none and was never attempted."""
    result = Classified()
    for mod, info in mods.items():
        if mod in doc.categories or mod in doc.auto_category_attempted:
            continue
        result.attempted.add(mod)
        category = _remembered(info, doc.category_memory) or suggest_category(
            info, nickname=doc.nicknames.get(mod)
        )
        if category:
            result.categories[mod] = category
            result.memory.update(dict.fromkeys(category_memory_keys(info), category))
    return result


def build_tiers(
    table: TierTable,
    mods: Mapping[ModId, ModInfo],
    categories: Mapping[ModId, str],
    resolved: ResolvedRules,
) -> dict[ModId, Tier]:
    return {
        mod: resolve_tier(
            rules_tier=resolved.tier_overrides.get(mod),
            legacy_category=categories.get(mod),
            suggestion=None,
            table=table,
        ).tier
        for mod in mods
    }
