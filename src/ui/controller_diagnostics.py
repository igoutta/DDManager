"""The setup report of "Check Setup" / "Copy Debug Info": facts gathered here, text by ``core``.

The session facts are read on the GUI thread; the disk reads (is the mods folder there, does the
selected save carry an ``applied_ugcs_1_0`` block and how many entries) run in a worker.
"""

import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from src.__about__ import __version__
from src.core.diagnostics import DiagnosticsInput, diagnostics_lines
from src.services.save_slots import SaveSlotService
from src.ui.controller_tools import is_assigned
from src.ui.presenters.tools_dto import DiagnosticsVM

if TYPE_CHECKING:
    from src.ui.controller import MainController


APPLIED_UNREADABLE: Final = "save_slots.applied_unreadable"


@dataclass(frozen=True, slots=True)
class SetupProbe:
    """What a worker learned from the disk (``None`` fields: not checked)."""

    mods_path_valid: bool = False
    save_detected: bool = False
    has_applied_block: bool | None = None
    applied_count: int | None = None


def probe_setup(slots: SaveSlotService, save: Path | None, mods_path: str) -> SetupProbe:
    """Stat the mods folder and read the save's applied block (never raises).

    The slot service reports an unreadable block as a finding on the save's slot instead of
    raising, so "has the block" is "no such finding".
    """
    mods_valid = bool(mods_path) and Path(mods_path).is_dir()
    if save is None or not save.is_file():
        return SetupProbe(mods_path_valid=mods_valid)
    entries = slots.applied_entries(save)
    unreadable = any(
        finding.rule_id == APPLIED_UNREADABLE
        for slot in slots.slots([save])
        for finding in slot.findings
    )
    return SetupProbe(
        mods_valid,
        save_detected=True,
        has_applied_block=not unreadable,
        applied_count=None if unreadable else len(entries),
    )


def _first(paths: tuple[Path, ...]) -> str:
    return str(paths[0]) if paths else ""


def mods_path_of(c: MainController) -> str:
    s = c.session
    return str(s.pending.settings.get("mods_path", s.doc.settings.mods_path))


def build_input(c: MainController, probe: SetupProbe) -> DiagnosticsInput:
    s = c.session
    install = s.install
    priority = c.priority()
    return DiagnosticsInput(
        app_version=__version__,
        python_version=platform.python_version(),
        platform=f"{sys.platform} ({platform.platform()})",
        data_dir=str(c.services.paths.data_dir),
        mods_path=mods_path_of(c),
        mods_path_valid=probe.mods_path_valid,
        mod_count=len(s.mods),
        enabled_count=len(s.order.active()),
        uncategorized_count=sum(1 for mod in s.mods if not is_assigned(s.categories.get(mod))),
        selected_save=str(s.save_path) if s.save_path is not None else "",
        save_detected=probe.save_detected,
        save_has_applied_block=probe.has_applied_block,
        applied_count=probe.applied_count,
        last_backup=s.last_backup.isoformat(" ", "seconds") if s.last_backup else "",
        game_root=_first(install.game_roots) if install else "",
        workshop_dir=_first(install.workshop_dirs) if install else "",
        local_mods_dir=_first(install.local_mod_dirs) if install else "",
        priority_direction=priority.direction.value,
        priority_verified=priority.verified,
    )


def collect(c: MainController, on_ready: Callable[[DiagnosticsVM], None]) -> None:
    """Build the report in the background and hand the view model to ``on_ready`` (GUI thread)."""
    slots = c.services.slots
    save = c.save_path()
    mods_path = mods_path_of(c)

    def ready(probe: SetupProbe) -> None:
        lines = diagnostics_lines(build_input(c, probe))
        on_ready(DiagnosticsVM("\n".join(lines), lines))

    c.run_task(
        lambda _token: probe_setup(slots, save, mods_path),
        ready,
        busy_key="ui.busy.diagnostics",
    )
