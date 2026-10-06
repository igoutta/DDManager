"""Backup and patch flows of the controller: plan in a worker, review, apply in a worker."""

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.findings import Severity
from src.core.ids import ModId, SaveIdentity
from src.core.load_order import applied_entries
from src.services.backup import GAME_IMAGES, BackupReason, BackupRecord
from src.services.ports import CancelToken, RunState
from src.services.save_patch import ACK_GAME_STATE_UNKNOWN, PatchPlan, PatchResult
from src.ui.catalog import finding_vm
from src.ui.ports import PatchDecision
from src.ui.viewmodels import OrderDiffRow, OrderDiffVM, PatchPreviewVM

if TYPE_CHECKING:
    from src.ui.controller import MainController


def _diff_vm(before: Sequence[str], after: Sequence[str]) -> OrderDiffVM:
    old = {item: index + 1 for index, item in reversed(list(enumerate(before)))}
    new = {item: index + 1 for index, item in reversed(list(enumerate(after)))}
    shown = [*new, *(item for item in old if item not in new)]
    rows = tuple(OrderDiffRow(ModId(item), item, old.get(item), new.get(item)) for item in shown)
    return OrderDiffVM(
        rows=rows,
        moved_count=sum(1 for item in new if item in old and old[item] != new[item]),
        total=len(new),
        added=sum(1 for item in new if item not in old),
        removed=sum(1 for item in old if item not in new),
    )


class SaveFlows:
    """Everything that reads or writes the selected save, driven by the controller."""

    def __init__(self, controller: MainController) -> None:
        self._c = controller

    # ------------------------------------------------------------------ backup

    def backup(self) -> None:
        save = self._c.require_save()
        if save is None:
            return
        backups = self._c.services.backups
        self._c.run_task(
            lambda _token: backups.create(save, reason=BackupReason.MANUAL),
            self._backed_up,
            busy_key="ui.busy.backup",
        )

    def _backed_up(self, record: BackupRecord) -> None:
        self._c.remember_save(record.save_path, record.created, record.path)
        self._c.post("ui.notice.backup_done", name=record.path.name)

    # ------------------------------------------------------------------ patch

    def patch(self, save: Path | None = None) -> None:
        """Patch the selected save, or ``save`` (Patch other file / Patch latest detected)."""
        if save is None:
            save = self._c.require_save()
            if save is None:
                return
        try:
            entries = applied_entries(self._c.order(), self._c.identity_map())
        except ValueError as exc:
            self._c.prompter_error("ui.error.identity_missing", str(exc))
            return
        services = self._c.services

        def plan_task(_token: CancelToken) -> tuple[PatchPlan, RunState]:
            state = services.probe.find(GAME_IMAGES)
            return services.patcher.plan(save, entries), state

        self._c.run_task(plan_task, self._planned, busy_key="ui.busy.planning")

    def patch_other(self) -> None:
        """Pick any save file and patch it through the preview; the selected slot stays."""
        c = self._c
        current = c.save_path()
        prompter = c.prompter
        picked = prompter.pick_save_file(current.parent if current else None) if prompter else None
        if picked is not None:
            self.patch(picked)

    def patch_latest(self) -> None:
        """Patch the most recently changed detected save file, after confirming which one."""
        c = self._c
        install = c.install()
        latest = c.services.slots.latest(install.save_files) if install is not None else None
        if latest is None:
            c.post("ui.notice.no_save_detected", "warning")
            return
        prompter = c.prompter
        if prompter is not None and prompter.confirm(
            "ui.prompt.patch_latest", file=str(latest), slot=c.slot_label(latest)
        ):
            self.patch(latest)

    def _planned(self, planned: tuple[PatchPlan, RunState]) -> None:
        plan, state = planned
        if state is RunState.RUNNING:
            self._c.prompter_error("ui.error.game_running", "")
            return
        vm = self._preview(plan, unknown=state is RunState.UNKNOWN)
        decision = self._c.review_patch(vm)
        if (
            decision is None
            or not decision.proceed
            or (vm.blocking and not decision.override_errors)
        ):
            return
        self._apply(plan, decision)

    def _apply(self, plan: PatchPlan, decision: PatchDecision) -> None:
        patcher = self._c.services.patcher
        acknowledged = decision.acknowledged
        self._c.run_task(
            lambda _token: patcher.apply(plan, acknowledged=acknowledged),
            self._patched,
            busy_key="ui.busy.patching",
        )

    def _patched(self, result: PatchResult) -> None:
        self._c.remember_save(result.save_path, result.backup.created, result.backup.path)
        self._c.post("ui.notice.patched", count=len(result.after))

    def _label(self, identity: SaveIdentity) -> str:
        title = self._c.title_for_identity(identity)
        return (
            f"{title}  [{identity.name} | {identity.source}]"
            if title
            else (f"{identity.name} | {identity.source}")
        )

    def _preview(self, plan: PatchPlan, *, unknown: bool) -> PatchPreviewVM:
        c = self._c
        before = tuple(self._label(e) for e in plan.before)
        after = tuple(self._label(e) for e in plan.after)
        acks = set(plan.required_acks)
        if unknown:
            acks.add(ACK_GAME_STATE_UNKNOWN)
        return PatchPreviewVM(
            save_path=plan.save_path,
            slot_label=c.slot_label(),
            backup_dir=c.services.backups.slot_dir(plan.save_path),
            before=before,
            after=after,
            diff=_diff_vm(before, after),
            findings=tuple(finding_vm(f, c.tr, c.has) for f in plan.findings),
            required_acks=tuple((ack, f"ui.ack.{ack}") for ack in sorted(acks)),
            blocking=any(f.severity >= Severity.ERROR for f in plan.findings),
        )


def last_save_settings(save: Path, backup: Path) -> dict[str, str]:
    """``dd2.py:1778-1782``: remember the save and its backup in the state."""
    return {
        "last_save_path": str(save),
        "last_backup_path": str(backup),
        "last_output_path": str(save),
    }
