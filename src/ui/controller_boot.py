"""Start-up and rescans: scan in a worker, reconcile, classify silently, first-run notices."""

import functools
from typing import TYPE_CHECKING

from src.core.json_values import JsonValue
from src.core.rules_data import resolve_rules
from src.ui import controller_scan as scanning

if TYPE_CHECKING:
    from src.ui.controller import MainController


class ScanFlow:
    def __init__(self, controller: MainController) -> None:
        self._c = controller

    def rescan(self) -> None:
        c = self._c
        c.run_task(
            functools.partial(scanning.run_scan, c.services, c.session.doc.settings),
            self.on_scanned,
            busy_key="ui.busy.scanning",
            key="scan",
        )

    def on_scanned(self, outcome: scanning.ScanOutcome) -> None:
        c = self._c
        s = c.session
        s.install, s.slots = outcome.install, outcome.slots
        s.mods = outcome.scan.mods
        s.save_path, s.last_backup = outcome.save_path, outcome.last_backup
        had_order = bool(s.order.entries)
        reconciled = s.order.reconcile(s.mods)
        s.order = reconciled.order
        s.new_ids = frozenset(reconciled.added) if had_order else frozenset()
        s.missing = frozenset(reconciled.missing)
        s.resolved = resolve_rules(c.services.rules, s.mods)
        self.reclassify()
        s.scan_findings = (*outcome.install.findings, *outcome.scan.findings)
        self._first_run(outcome)
        c.rebuild()
        c.schedule_save()
        c.validate()
        c.slotsChanged.emit()

    def reclassify(self) -> None:
        s = self._c.session
        result = scanning.classify_new(s.mods, s.doc)
        s.categories.update(result.categories)
        s.pending.categories.update(result.categories)
        s.pending.attempted |= result.attempted
        s.pending.memory.update(result.memory)
        s.tiers = scanning.build_tiers(s.table, s.mods, s.categories, s.resolved)

    def _first_run(self, outcome: scanning.ScanOutcome) -> None:
        c = self._c
        s = c.session
        settings: dict[str, JsonValue] = s.pending.settings
        primary = outcome.install.primary_mods_dir
        saved = scanning.optional_path(s.doc.settings.mods_path)
        if primary is None:
            c.post("ui.notice.no_mods_folder", "warning")
        elif saved is None or not saved.is_dir():
            settings["mods_path"] = str(primary)
        if s.doc.settings.first_run_summary_shown or settings.get("first_run_summary_shown"):
            return
        settings["first_run_summary_shown"] = True
        if outcome.save_path is not None and not s.doc.settings.selected_profile_path:
            settings["selected_profile_path"] = str(outcome.save_path)
        c.post(
            "ui.notice.first_run",
            mods=len(s.mods),
            saves=len(outcome.install.save_files),
            folder=str(primary or ""),
        )
