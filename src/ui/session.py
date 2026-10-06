"""The controller's mutable working state (never shared with widgets)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.core.findings import Finding
from src.core.ids import ModId
from src.core.json_values import JsonValue
from src.core.legacy_state import StateDoc
from src.core.load_order import LoadOrder
from src.core.model import ModInfo
from src.core.rules_data import ResolvedRules
from src.core.tiers import Tier, TierTable
from src.services.detection import InstallSnapshot
from src.services.fsutil import FileFingerprint
from src.services.save_slots import SaveSlot


@dataclass(frozen=True, slots=True)
class CategoryLayout:
    """A category-editor commit waiting for the write: the four stored values it replaces."""

    order: tuple[str, ...]
    custom: tuple[str, ...]
    colors: Mapping[str, str]
    memory: Mapping[str, str]


@dataclass(slots=True)
class Pending:
    """State changes waiting for the debounced write."""

    categories: dict[ModId, str | None] = field(default_factory=dict)
    attempted: set[ModId] = field(default_factory=set)
    memory: dict[str, str] = field(default_factory=dict)
    settings: dict[str, JsonValue] = field(default_factory=dict)
    nicknames: dict[ModId, str | None] = field(default_factory=dict)
    layout: CategoryLayout | None = None
    unattempted: set[ModId] = field(default_factory=set)

    def any(self) -> bool:
        return bool(
            self.categories
            or self.attempted
            or self.unattempted
            or self.memory
            or self.settings
            or self.nicknames
            or self.layout is not None
        )

    def clear(self) -> None:
        self.categories.clear()
        self.attempted.clear()
        self.memory.clear()
        self.settings.clear()
        self.nicknames.clear()
        self.unattempted.clear()
        self.layout = None


@dataclass(slots=True)
class Session:
    doc: StateDoc
    fingerprint: FileFingerprint | None
    order: LoadOrder
    table: TierTable
    categories: dict[ModId, str] = field(default_factory=dict)
    mods: Mapping[ModId, ModInfo] = field(default_factory=dict)
    install: InstallSnapshot | None = None
    slots: tuple[SaveSlot, ...] = ()
    save_path: Path | None = None
    last_backup: datetime | None = None
    resolved: ResolvedRules = field(default_factory=ResolvedRules)
    tiers: dict[ModId, Tier] = field(default_factory=dict)
    new_ids: frozenset[ModId] = frozenset()
    missing: frozenset[ModId] = frozenset()
    base_findings: tuple[Finding, ...] = ()
    scan_findings: tuple[Finding, ...] = ()
    findings: tuple[Finding, ...] = ()
    pending: Pending = field(default_factory=Pending)
    conflict: bool = False
    busy_text: str = ""
