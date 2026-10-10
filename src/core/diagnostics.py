"""The "Check Setup" / "Copy Debug Info" text .

Deliberately English only: users paste it into bug reports.  The services layer gathers the
facts into a :class:`DiagnosticsInput` (nothing here reads the filesystem, the clock or
the widgets); this module only formats ``Label: value`` lines in a fixed order.  A
capture timestamp, when wanted, goes in ``extra`` because core has no clock.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiagnosticsInput:
    """Everything the setup report shows; ``None`` means "not checked"."""

    app_version: str
    python_version: str
    platform: str
    data_dir: str
    mods_path: str
    mods_path_valid: bool
    mod_count: int
    enabled_count: int
    uncategorized_count: int
    selected_save: str
    save_detected: bool
    save_has_applied_block: bool | None
    applied_count: int | None
    last_backup: str
    game_root: str
    workshop_dir: str
    local_mods_dir: str
    priority_direction: str
    priority_verified: bool
    extra: tuple[tuple[str, str], ...] = ()


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "Not checked"
    return "Yes" if value else "No"


def _or(value: str, placeholder: str) -> str:
    return value or placeholder


def _app_lines(info: DiagnosticsInput) -> tuple[str, ...]:
    return (
        f"DD Manager version: {info.app_version}",
        f"Python: {info.python_version}",
        f"Platform: {info.platform}",
        f"App data folder: {_or(info.data_dir, '(not set)')}",
    )


def _folder_lines(info: DiagnosticsInput) -> tuple[str, ...]:
    """The auto-detected folder summary lines."""
    return (
        f"Game install: {_or(info.game_root, '(not found)')}",
        f"Local mods folder: {_or(info.local_mods_dir, '(not found)')}",
        f"Workshop mods folder: {_or(info.workshop_dir, '(not found)')}",
        f"Mods folder valid: {_yes_no(info.mods_path_valid)}",
        f"Mods folder: {_or(info.mods_path, '(not set)')}",
    )


def _mod_lines(info: DiagnosticsInput) -> tuple[str, ...]:
    """counts, with the uncategorised count instead of the metadata one."""
    return (
        f"Mods loaded: {info.mod_count}",
        f"Enabled mods: {info.enabled_count}",
        f"Disabled mods: {info.mod_count - info.enabled_count}",
        f"Uncategorized mods: {info.uncategorized_count}",
        f"Priority direction: {info.priority_direction}",
        f"Priority verified: {_yes_no(info.priority_verified)}",
    )


def _save_lines(info: DiagnosticsInput) -> tuple[str, ...]:
    """The selected save and its ``applied_ugcs_1_0`` block."""
    applied = "Not checked" if info.applied_count is None else str(info.applied_count)
    return (
        f"Selected save: {_or(info.selected_save, '(not selected)')}",
        f"Save detected: {_yes_no(info.save_detected)}",
        f"Save has applied_ugcs_1_0: {_yes_no(info.save_has_applied_block)}",
        f"Applied mods in save: {applied}",
        f"Last backup: {_or(info.last_backup, '(none)')}",
    )


def diagnostics_lines(info: DiagnosticsInput) -> tuple[str, ...]:
    """The report as ``Label: value`` lines in a deterministic order; ``extra`` pairs last."""
    extra = tuple(f"{label}: {value}" for label, value in info.extra)
    return (*_app_lines(info), *_folder_lines(info), *_mod_lines(info), *_save_lines(info), *extra)
