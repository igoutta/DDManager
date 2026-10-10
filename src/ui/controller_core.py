"""The controller's base: its signals, read access to the session and the task plumbing.

``MainController`` derives from ``ControllerCore`` and sets every attribute declared here in its
``__init__``; keeping the signals, the queries and the notice/busy/error plumbing in this module
leaves ``controller.py`` with construction, publishing and the user-facing entry points.
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from src.core.errors import DDManagerError
from src.core.ids import ModId, SaveIdentity
from src.core.load_order import LoadOrder, PrioritySetting
from src.core.model import ModInfo
from src.core.state_file import StateSettings
from src.core.tiers import Tier
from src.services.detection import InstallSnapshot
from src.services.ports import CancelToken
from src.services.save_slots import SaveSlot
from src.services.sources import ModSource
from src.ui.controller_save import last_save_settings
from src.ui.controller_status import status_vm
from src.ui.ports import Executor, PatchDecision, Prompter
from src.ui.viewmodels import FindingVM, ModRowVM, NoticeVM, PatchPreviewVM, StatusVM

if TYPE_CHECKING:
    from src.services.bootstrap import Services
    from src.ui.controller_findings import FindingsFlow
    from src.ui.controller_sync import StateSync
    from src.ui.i18n import Translator
    from src.ui.presenters.settings import SettingsPresenter
    from src.ui.session import Session


class ControllerCore(QObject):
    busyChanged = Signal(bool, str)
    statusChanged = Signal(object)
    findingsChanged = Signal(object)
    detailsChanged = Signal(object)
    selectModsRequested = Signal(list)
    notice = Signal(object)
    stateConflict = Signal()
    slotsChanged = Signal()
    densityChanged = Signal(str)

    services: Services
    translator: Translator
    settings: SettingsPresenter
    _s: Session
    _rows: dict[ModId, ModRowVM]
    _selection: tuple[ModId, ...]
    _sources: dict[str, ModSource]
    _prompter: Prompter | None
    _executor: Executor
    _busy: int
    _findings: FindingsFlow
    _sync: StateSync

    # ================================================================== read access

    @property
    def session(self) -> Session:
        return self._s

    @property
    def tr(self) -> Callable[..., str]:
        return self.translator.tr

    @property
    def has(self) -> Callable[[str], bool]:
        return self.translator.has

    @property
    def prompter(self) -> Prompter | None:
        return self._prompter

    def state_settings(self) -> StateSettings:
        return self._s.doc.settings

    def selection(self) -> tuple[ModId, ...]:
        return self._selection

    def ui_ini(self) -> Path:
        return self.services.paths.ui_settings_file

    def order(self) -> LoadOrder:
        return self._s.order

    def mods(self) -> Mapping[ModId, ModInfo]:
        return self._s.mods

    def priority(self) -> PrioritySetting:
        return self.settings.priority()

    def rows(self) -> Mapping[ModId, ModRowVM]:
        return self._rows

    def save_path(self) -> Path | None:
        return self._s.save_path

    def install(self) -> InstallSnapshot | None:
        return self._s.install

    def slot_list(self) -> tuple[SaveSlot, ...]:
        return self._s.slots

    def tier_of(self, mod: ModId) -> Tier:
        return self._s.tiers.get(mod) or self._s.table.unassigned()

    def titles(self) -> dict[ModId, str]:
        return {mod: row.title for mod, row in self._rows.items()}

    def identity_map(self) -> dict[ModId, SaveIdentity]:
        known = dict(self._s.doc.metadata_identities)
        known.update({mod: info.save_identity for mod, info in self._s.mods.items()})
        return known

    def title_for_identity(self, identity: SaveIdentity) -> str | None:
        for mod, info in self._s.mods.items():
            if info.save_identity == identity:
                return self._rows[mod].title if mod in self._rows else info.title
        return None

    def page_url(self, mod_id: ModId) -> str | None:
        info = self._s.mods.get(mod_id)
        source = self._sources.get(info.source_id) if info is not None else None
        return source.page_url(info) if source is not None and info is not None else None

    def status(self) -> StatusVM:
        return status_vm(
            self._s, self.priority(), self.tr, label=self.slot_label(), busy=self._busy > 0
        )

    def finding_vms(self) -> tuple[FindingVM, ...]:
        return self._findings.vms()

    def slot_label(self, path: Path | None = None) -> str:
        """The label of ``path`` (default: the selected save): slot and week when detected."""
        s = self._s
        save = path if path is not None else s.save_path
        if save is None:
            return self.tr("ui.slot.none")
        for slot in s.slots:
            if slot.save_path == save:
                return self.slot_text(slot.number, slot.week, slot.save_path)
        return self.slot_text(None, None, save)

    def slot_text(self, number: int | None, week: int | None, path: Path) -> str:
        base = (
            self.tr("ui.slot.numbered", number=number + 1)
            if number is not None
            else path.parent.name
        )
        return f"{base} · {self.tr('ui.slot.week', week=week)}" if week is not None else base

    # ================================================================== messages and tasks

    def post(self, key: str, level: str = "info", **params: object) -> None:
        self.notice.emit(NoticeVM(key, tuple(params.items()), level))  # ty: ignore[invalid-argument-type]

    def prompter_error(self, key: str, details: str, **params: object) -> None:
        if self._prompter is not None:
            self._prompter.error(key, details, **params)
        else:
            self.post(key, "error", **params)

    def review_patch(self, vm: PatchPreviewVM) -> PatchDecision | None:
        return self._prompter.review_patch(vm) if self._prompter is not None else None

    def report_error(self, exc: BaseException) -> None:
        """A typed domain error becomes a translated dialog; anything else is a bug (re-raised)."""
        if not isinstance(exc, DDManagerError):
            raise exc
        key = exc.message_key if self.translator.has(exc.message_key) else "ui.error.operation"
        self.prompter_error(key, exc.message)

    def require_save(self) -> Path | None:
        save = self._s.save_path
        if save is None or not save.is_file():
            self.prompter_error("ui.error.no_save", "")
            return None
        return save

    def run_task[T](
        self,
        fn: Callable[[CancelToken], T],
        on_ok: Callable[[T], None],
        *,
        busy_key: str,
        key: str | None = None,
        pool: str = "io",
    ) -> None:
        """Run ``fn`` off the GUI thread with a busy indicator; typed errors become dialogs."""
        self._set_busy(+1, busy_key)

        def done(result: T) -> None:
            self._set_busy(-1, busy_key)
            on_ok(result)

        def failed(exc: BaseException) -> None:
            self._set_busy(-1, busy_key)
            self.report_error(exc)

        self._executor.submit(fn, on_ok=done, on_err=failed, key=key, pool=pool)

    def emit_status(self) -> None:
        self.statusChanged.emit(self.status())

    def schedule_save(self) -> None:
        self._sync.schedule()

    def _set_busy(self, delta: int, key: str) -> None:
        self._busy = max(0, self._busy + delta)
        text = self.tr(key) if self._busy else ""
        self._s.busy_text = text
        self.busyChanged.emit(self._busy > 0, text)
        self.emit_status()

    def remember_save(self, save: Path, created: datetime, backup: Path) -> None:
        self._s.last_backup = created
        self._s.pending.settings.update(last_save_settings(save, backup))
        self.schedule_save()
        self.emit_status()
