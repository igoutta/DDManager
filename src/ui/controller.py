"""The main controller: owns the session, the models and every user-visible decision.

It imports QtCore/QtGui only (never QtWidgets) so it runs without a window, and it is the one
UI module that talks to services (with the presenters). Behaviour lives in the ``controller_*``
helpers (read access and task plumbing in ``ControllerCore``, the one-line entry points of the
window actions in ``ControllerCommands``); every disable goes through ``EditFlows.commit``,
which runs the active-save guard.
"""

import dataclasses
from collections.abc import Iterable, Sequence
from typing import Final

from PySide6.QtCore import QObject, Qt, QTimer

from src.core.ids import ModId
from src.core.load_order import LoadOrder, MoveOp
from src.core.tiers import TierTable
from src.services.bootstrap import Services
from src.ui.catalog import RowBuilder
from src.ui.controller_actions import PlatformFlows
from src.ui.controller_boot import ScanFlow
from src.ui.controller_commands import ControllerCommands
from src.ui.controller_edits import EditFlows
from src.ui.controller_findings import FindingsFlow
from src.ui.controller_highlight import NewHighlight
from src.ui.controller_labels import LabelFlows
from src.ui.controller_save import SaveFlows
from src.ui.controller_scan import configured_save
from src.ui.controller_sync import StateSync
from src.ui.i18n import Translator
from src.ui.models.available_model import AvailableModsModel
from src.ui.models.available_proxy import AvailableFilterProxy
from src.ui.models.findings_model import FindingsModel
from src.ui.models.load_order_model import LoadOrderModel
from src.ui.ports import Executor, Prompter
from src.ui.presenters.categories import CategoriesPresenter
from src.ui.presenters.paths import PathsPresenter
from src.ui.presenters.profiles import ProfilesPresenter
from src.ui.presenters.settings import SettingsPresenter
from src.ui.presenters.tools import ToolsPresenter
from src.ui.session import Session
from src.ui.thumbnails import ThumbnailProvider
from src.ui.undo import OrderUndoStack
from src.ui.viewmodels import ModRowVM

VALIDATE_DELAY_MS: Final = 250


class MainController(ControllerCommands):
    def __init__(
        self,
        services: Services,
        executor: Executor,
        translator: Translator,
        thumbnails: ThumbnailProvider,
        prompter: Prompter | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.services = services
        self.translator = translator
        self.thumbnails = thumbnails
        self._executor = executor
        self._prompter = prompter
        self._busy = 0
        self._selection: tuple[ModId, ...] = ()
        self._rows: dict[ModId, ModRowVM] = {}
        self._sources = {source.source_id: source for source in services.registry.mod_sources}
        self._builder = RowBuilder(
            translator.tr,
            translator.has,
            {sid: source.display_name for sid, source in self._sources.items()},
            lambda info: self.page_url(info.id),
        )
        self._s = self._new_session()
        self.available_model = AvailableModsModel(self)
        self.available_proxy = AvailableFilterProxy(self)
        self.available_proxy.setSourceModel(self.available_model)
        self.load_order_model = LoadOrderModel(thumbnails, translator, self)
        self.findings_model = FindingsModel(translator, self)
        self.undo_stack = OrderUndoStack(self, self)
        self.profiles = ProfilesPresenter(self)
        self.settings = SettingsPresenter(self)
        self.tools = ToolsPresenter(self)
        self.labels = LabelFlows(self)
        self.categories = CategoriesPresenter(self)
        self.paths = PathsPresenter(self)
        self._edits = EditFlows(self)
        self._findings = FindingsFlow(self)
        self._sync = StateSync(self)
        self._flows = SaveFlows(self)
        self._scan = ScanFlow(self)
        self._platform = PlatformFlows(self)
        self.highlight = NewHighlight(self)
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(VALIDATE_DELAY_MS)
        self._validate_timer.timeout.connect(self.validate)
        self._wire_models()
        translator.languageChanged.connect(self._on_language_changed)

    def _wire_models(self) -> None:
        """Drop and toggle requests arrive from inside Qt event handlers: always queue them."""
        queued = Qt.ConnectionType.QueuedConnection
        self.available_model.toggleRequested.connect(self._on_toggle, queued)
        self.available_model.disableRequested.connect(self.disable, queued)
        self.load_order_model.moveRequested.connect(self.move_to, queued)
        self.load_order_model.enableRequested.connect(self.enable, queued)
        self.load_order_model.disableRequested.connect(self.disable, queued)

    def _new_session(self) -> Session:
        snapshot = self.services.state.load()
        doc = snapshot.doc
        findings = (
            *snapshot.findings,
            *self.services.startup_findings,
            *self.services.rule_findings,
        )
        return Session(
            doc=doc,
            fingerprint=snapshot.fingerprint,
            order=doc.order,
            table=TierTable.from_categories(doc.category_order, doc.custom_categories),
            categories=dict(doc.categories),
            base_findings=findings,
            save_path=configured_save(doc.settings),
        )

    def attach_prompter(self, prompter: Prompter) -> None:
        self._prompter = prompter

    # ================================================================== rows / publishing

    def rebuild(self) -> None:
        """Recompute every row from the session and push it into the models and the panes."""
        self._rows = self._builder.build_all(self._s)
        self._publish()
        self.emit_status()
        self.emit_details()

    def rebuild_rows(self, ids: Iterable[ModId]) -> None:
        """Recompute the rows of ``ids`` only and publish them: ``dataChanged``, never a re-sort."""
        self._rows.update(self._builder.build_some(ids, self._s))
        self._publish()
        self.emit_details()

    def _publish(self) -> None:
        order = self._s.order
        rows = self._rows
        self.available_model.set_rows([rows[mod] for mod in order.entries])
        self.load_order_model.apply_rows([rows[mod] for mod in order.active()])

    def apply_order(self, order: LoadOrder) -> None:
        """Make ``order`` current: used by undo/redo, profiles, auto-sort and every edit."""
        previous = self._s.order
        self._s.order = order
        if set(order.entries) != set(previous.entries):
            self._rows = self._builder.build_all(self._s)
        else:
            for mod in previous.enabled ^ order.enabled:
                flag = order.is_enabled(mod)
                self._rows[mod] = dataclasses.replace(self._rows[mod], enabled=flag)
        self._publish()
        self.schedule_save()
        self._validate_timer.start()
        self.emit_status()
        self.emit_details()

    def _on_language_changed(self, _code: str) -> None:
        self.rebuild()
        self._findings.emit()

    def emit_details(self) -> None:
        self.detailsChanged.emit(self._builder.details(self._selection, self._s, self._rows))

    def select(self, ids: Sequence[ModId]) -> None:
        self._selection = tuple(ids)
        self.emit_details()

    def select_requested(self, ids: list[ModId]) -> None:
        """Ask the panes to select ``ids`` (a finding was activated)."""
        self._selection = tuple(ids)
        self.selectModsRequested.emit(ids)
        self.emit_details()

    def priority_changed(self) -> None:
        self.rebuild()
        self.validate()

    # ================================================================== edits (see EditFlows)

    def commit_order(self, after: LoadOrder, undo_key: str) -> bool:
        return self._edits.commit(after, undo_key)

    def review_and_commit(self, after: LoadOrder, title_key: str, undo_key: str) -> bool:
        return self._edits.review_and_commit(after, title_key, undo_key)

    def move(self, ids: Sequence[ModId], op: MoveOp) -> None:
        self._edits.move(ids, op)

    def move_to(self, ids: Sequence[ModId], row: int) -> None:
        self._edits.move_to(ids, row)

    def enable(self, ids: Sequence[ModId], at_row: int | None = None) -> None:
        self._edits.enable(ids, at_row)

    def disable(self, ids: Sequence[ModId]) -> None:
        self._edits.disable(ids)

    def forget_missing(self, ids: Sequence[ModId]) -> None:
        self._edits.forget_missing(ids)

    def set_category(self, ids: Sequence[ModId], name: str | None) -> None:
        """Assign a category (``None`` unassigns) to mods, remembering it for their identities."""
        self.labels.set_category(ids, name)

    def set_nickname(self, mod: ModId, text: str) -> bool:
        """Give ``mod`` a nickname; the default display name (or nothing) clears it."""
        return self.labels.set_nickname(mod, text)

    def _on_toggle(self, ids: list[ModId], checked: bool) -> None:
        (self.enable if checked else self.disable)(ids)

    def undo(self) -> None:
        self._edits.step(forward=False)

    def redo(self) -> None:
        self._edits.step(forward=True)

    def auto_sort(self) -> None:
        self._edits.auto_sort()

    # ================================================================== findings

    def validate(self) -> None:
        self._findings.validate()

    def focus_finding(self, key: str) -> None:
        self._findings.focus(key)

    def apply_fix(self, key: str) -> None:
        self._findings.apply_fix(key)

    # ================================================================== state file

    def validate_now(self) -> None:
        """Run a due (debounced) validation at once, so the findings match the current order."""
        if self._validate_timer.isActive():
            self._validate_timer.stop()
            self.validate()

    def flush(self) -> bool:
        """Write pending changes and run a due validation now (tests, shutdown)."""
        self.validate_now()
        return self._sync.flush()

    def reload_state(self) -> None:
        self._sync.reload()

    def keep_mine(self) -> None:
        self._sync.keep_mine()

    def can_close(self) -> bool:
        return self.flush()
