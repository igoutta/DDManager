"""Immutable view models: built only by the controller/presenters, rendered by widgets."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from src.core.ids import ModId


@dataclass(frozen=True, slots=True)
class FindingVM:
    key: str
    rule_id: str
    severity: int
    message: str
    mod_ids: tuple[ModId, ...] = ()
    fix_label: str | None = None
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModRowVM:
    """One mod as the list models and delegates see it."""

    mod_id: ModId
    title: str
    subtitle: str
    folder: str
    source_id: str
    source_label: str
    save_identity_text: str
    tier_id: str
    tier_badge: str
    tier_label: str
    category_label: str = ""
    color: str = "#82786B"
    enabled: bool = False
    is_new: bool = False
    missing: bool = False
    worst_severity: int = 0
    finding_count: int = 0
    finding_summary: str = ""
    search_blob: str = ""
    sort_key: str = ""
    icon_path: Path | None = None
    icon_stamp: int | None = None
    black_reliquary: bool = False
    version_label: str = ""
    updated_label: str = ""


@dataclass(frozen=True, slots=True)
class DetailsVM:
    mod_id: ModId
    title: str
    rank_text: str
    identity_text: str
    folder: str
    source_label: str
    workshop_url: str | None
    path: Path
    version_text: str = ""
    category_label: str = ""
    tier_label: str = ""
    tags: tuple[str, ...] = ()
    findings: tuple[FindingVM, ...] = ()
    icon_path: Path | None = None
    icon_stamp: int | None = None


@dataclass(frozen=True, slots=True)
class MultiDetailsVM:
    count: int
    tier_breakdown: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class StatusVM:
    profile_label: str
    save_path: Path | None = None
    last_backup: datetime | None = None
    counts: tuple[int, int, int] = (0, 0, 0)  # errors, warnings, infos
    summary_text: str = ""
    busy: bool = False
    busy_text: str = ""
    conflict: bool = False
    direction_top_label: str = ""
    direction_bottom_label: str = ""
    direction_verified: bool = True


@dataclass(frozen=True, slots=True)
class OrderDiffRow:
    mod_id: ModId
    title: str
    old_rank: int | None
    new_rank: int | None


@dataclass(frozen=True, slots=True)
class OrderDiffVM:
    rows: tuple[OrderDiffRow, ...] = ()
    moved_count: int = 0
    total: int = 0
    added: int = 0
    removed: int = 0


@dataclass(frozen=True, slots=True)
class PatchPreviewVM:
    save_path: Path
    slot_label: str
    backup_dir: Path
    before: tuple[str, ...]
    after: tuple[str, ...]
    diff: OrderDiffVM
    findings: tuple[FindingVM, ...] = ()
    required_acks: tuple[tuple[str, str], ...] = ()  # (ack id, i18n key)
    blocking: bool = False


@dataclass(frozen=True, slots=True)
class NoticeVM:
    """A transient, translated status-bar message (or error) raised by the controller."""

    key: str
    params: tuple[tuple[str, object], ...] = ()
    level: Literal["info", "warning", "error"] = "info"
