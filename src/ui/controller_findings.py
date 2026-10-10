"""Validation and findings of the controller (rules run in a worker on in-memory data)."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from src.core.findings import Finding, SetTier
from src.core.validation import (
    ValidationContext,
    ValidationReport,
    apply_fix,
    run_rules,
    sort_findings,
)
from src.ui.catalog import finding_vm
from src.ui.viewmodels import FindingVM

if TYPE_CHECKING:
    from src.ui.controller import MainController


class FindingsFlow:
    def __init__(self, controller: MainController) -> None:
        self._c = controller

    def validate(self) -> None:
        c = self._c
        s = c.session
        if not s.mods and not s.order.entries:
            self.apply(())
            return
        ctx = ValidationContext.build(
            order=s.order,
            mods=s.mods,
            tiers={mod: c.tier_of(mod) for mod in s.order.entries},
            rules=s.resolved,
            priority=c.priority(),
            default_tier=s.table.unassigned(),
        )
        rules = c.services.registry.rules
        c.run_task(
            lambda _token: run_rules(rules, ctx),
            self._on_report,
            busy_key="ui.busy.validating",
            key="validate",
        )

    def _on_report(self, report: ValidationReport) -> None:
        self.apply(report.findings)

    def apply(self, found: Sequence[Finding]) -> None:
        c = self._c
        s = c.session
        s.findings = sort_findings((*s.base_findings, *s.scan_findings, *found), s.order)
        c.rebuild()
        self.emit()
        c.emit_status()

    def emit(self) -> None:
        vms = self.vms()
        self._c.findings_model.set_findings(vms)
        self._c.findingsChanged.emit(vms)

    def vms(self) -> tuple[FindingVM, ...]:
        c = self._c
        return tuple(finding_vm(f, c.tr, c.has) for f in c.session.findings)

    def _find(self, key: str) -> Finding | None:
        return next((f for f in self._c.session.findings if f.key == key), None)

    def focus(self, key: str) -> None:
        finding = self._find(key)
        if finding is not None and finding.mod_ids:
            self._c.select_requested(list(finding.mod_ids))

    def apply_fix(self, key: str) -> None:
        c = self._c
        finding = self._find(key)
        if finding is None or finding.fix is None:
            return
        if isinstance(finding.fix, SetTier):
            self._set_tier(finding.fix)
            return
        after = apply_fix(c.session.order, finding.fix, c.priority().direction)
        c.commit_order(after, "ui.undo.fix")

    def _set_tier(self, fix: SetTier) -> None:
        c = self._c
        s = c.session
        tier = next((t for t in s.table.tiers if t.id == fix.tier_id), None)
        if tier is None or tier.category is None:
            return
        s.categories[fix.mod] = tier.category
        s.pending.categories[fix.mod] = tier.category
        s.tiers[fix.mod] = tier
        c.schedule_save()
        c.rebuild()
        self.validate()
