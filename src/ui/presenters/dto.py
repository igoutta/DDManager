"""Plain data the profile dialog renders, and the port it drives (no services imported)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SlotVM:
    path: Path
    label: str
    date_text: str
    week_text: str
    applied_text: str
    active: bool


@dataclass(frozen=True, slots=True)
class ProfileVM:
    name: str
    count_text: str
    created_text: str
    problem: str = ""


@dataclass(frozen=True, slots=True)
class BackupVM:
    path: Path
    created_text: str
    reason_text: str
    size_text: str
    location: str


class ProfilesPort(Protocol):
    """What :class:`~src.ui.dialogs.profile_manager_dialog.ProfileManagerDialog` calls."""

    def slots(self) -> Sequence[SlotVM]: ...

    def use_slot(self, path: Path) -> None: ...

    def import_order_from_save(self, path: Path) -> None: ...

    def profiles(self) -> Sequence[ProfileVM]: ...

    def save_profile_as(self, name: str) -> bool: ...

    def apply_profile(self, name: str) -> None: ...

    def import_file(self, path: Path) -> None: ...

    def export(self, name: str, dest: Path) -> None: ...

    def rename(self, old: str, new: str) -> bool: ...

    def delete(self, name: str) -> bool: ...

    def backups_for_active(self) -> Sequence[BackupVM]: ...

    def restore(self, path: Path) -> None: ...

    def open_slot_folder(self, path: Path) -> None: ...

    def open_backup_folder(self) -> None: ...

    def choose_save_file(self) -> None: ...

    def choose_mods_folder(self) -> None: ...
