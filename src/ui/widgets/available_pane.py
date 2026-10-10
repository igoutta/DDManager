"""The left pane: search, tier chips, source filter and the Available mod list."""

from collections import Counter

from PySide6.QtCore import QModelIndex, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.ids import ModId
from src.ui.controller import MainController
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role
from src.ui.theme.tokens import DENSITY, ThemeTokens, tier_token
from src.ui.widgets.delegates import ModRowDelegate
from src.ui.widgets.mod_views import ModListView, select_ids, selected_ids
from src.ui.widgets.tier_chips import ChipSpec, TierChips

DEBOUNCE_MS = 150
MIN_WIDTH_PX = 280
_ALL_SOURCES = ""
_COMBO_CHARS = 10


class AvailablePane(QWidget):
    selectionChangedIds = Signal(list)

    def __init__(
        self,
        controller: MainController,
        translator: Translator,
        tokens: ThemeTokens,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._c = controller
        self._tr = translator
        self._chip_specs: list[ChipSpec] = []
        self._source_map: dict[str, str] = {}
        self._build(tokens)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._apply_query)
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(0)
        self._refresh.timeout.connect(self._rebuild_filters)
        self._wire()
        self.retranslate_ui()

    # ------------------------------------------------------------------ construction

    def _build(self, tokens: ThemeTokens) -> None:
        tr = self._tr.tr
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel(self)
        set_role(self._title, "heading")
        self.search = QLineEdit(self)
        self.search.setClearButtonEnabled(True)
        self.chips = TierChips(self)
        self.source_combo = QComboBox(self)
        # The combo yields first: its minimum is a few characters, so the checkbox next to it
        # always keeps its full width (it was clipped at the pane's edge before).
        self.source_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.source_combo.setMinimumContentsLength(_COMBO_CHARS)
        self.show_active = QCheckBox(self)
        self.count_label = QLabel(self)
        set_role(self.count_label, "muted")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, tokens.spacing.xs, 0)
        row.addWidget(self.source_combo, 1)
        row.addWidget(self.show_active, 0)
        self.setMinimumWidth(MIN_WIDTH_PX)
        self.view = ModListView(tr, self)
        self.view.setModel(self._c.available_proxy)
        self.delegate = ModRowDelegate(self.view, self._c.thumbnails, tokens, tr)
        self.view.setItemDelegate(self.delegate)
        for widget in (self._title, self.search, self.chips):
            layout.addWidget(widget)
        layout.addLayout(row)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.count_label)
        self.set_density("Comfortable")

    def _wire(self) -> None:
        self.search.textChanged.connect(lambda _text: self._debounce.start())
        self.chips.selectionChanged.connect(self._c.available_proxy.set_tiers)
        self.source_combo.currentIndexChanged.connect(self._on_source)
        self.show_active.toggled.connect(self._c.available_proxy.set_show_enabled)
        self.view.activated.connect(self._on_activated)
        self.view.set_key_handler(Qt.Key.Key_Space, self.toggle_selection)
        selection = self.view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._on_view_selection)
        self._c.thumbnails.ready.connect(self._repaint)
        for model in (self._c.available_model, self._c.available_proxy):
            model.modelReset.connect(self._refresh.start)
            model.rowsInserted.connect(self._refresh.start)
            model.rowsRemoved.connect(self._refresh.start)
            model.dataChanged.connect(self._refresh.start)
            model.layoutChanged.connect(self._refresh.start)

    # ------------------------------------------------------------------ behaviour

    def focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def set_density(self, mode: str) -> None:
        icon, row = DENSITY.get(mode, DENSITY["Comfortable"])
        self.delegate.set_density(icon, row)
        self.view.doItemsLayout()
        self.view.viewport().update()

    def selected_ids(self) -> list[ModId]:
        return selected_ids(self.view)

    def select(self, ids: list[ModId]) -> None:
        select_ids(self.view, ids)

    def _apply_query(self) -> None:
        self._c.available_proxy.set_query(self.search.text())

    def _on_source(self) -> None:
        source = self.source_combo.currentData()
        self._c.available_proxy.set_sources(frozenset({source}) if source else frozenset())

    def _on_activated(self, _index: QModelIndex) -> None:
        self.enable_selection()

    def enable_selection(self) -> None:
        ids = self.selected_ids()
        if ids:
            self._c.enable(ids)

    def toggle_selection(self) -> None:
        """Space: disable when every selected mod is enabled, else enable the selection."""
        ids = self.selected_ids()
        if not ids:
            return
        rows = self._c.rows()
        if all(rows[mod].enabled for mod in ids if mod in rows):
            self._c.disable(ids)
        else:
            self._c.enable([mod for mod in ids if mod in rows and not rows[mod].enabled])

    def _on_view_selection(self, *_args: object) -> None:
        self.selectionChangedIds.emit(self.selected_ids())

    def _repaint(self, *_args: object) -> None:
        self.view.viewport().update()

    # ------------------------------------------------------------------ filters from the model

    def _rebuild_filters(self) -> None:
        model = self._c.available_model
        rows = [vm for i in range(model.rowCount()) if (vm := model.vm_at(i)) is not None]
        tally = Counter((vm.tier_id, vm.tier_label) for vm in rows)
        specs = [
            ChipSpec(tier, label, tier_token(tier).color, count)
            for (tier, label), count in sorted(tally.items(), key=lambda kv: kv[0][1])
        ]
        if specs != self._chip_specs:
            self._chip_specs = specs
            self.chips.set_chips(specs)
        sources = {vm.source_id: vm.source_label for vm in rows if vm.source_id}
        if sources != self._source_map:
            self._source_map = sources
            self._rebuild_sources(sources)
        proxy = self._c.available_proxy
        self.count_label.setText(
            self._tr.tr("ui.available.count", shown=proxy.rowCount(), total=model.rowCount())
        )

    def _rebuild_sources(self, sources: dict[str, str]) -> None:
        current = self.source_combo.currentData()
        self.source_combo.blockSignals(True)  # noqa: FBT003
        self.source_combo.clear()
        self.source_combo.addItem(self._tr.tr("ui.available.all_sources"), _ALL_SOURCES)
        for source_id, label in sorted(sources.items(), key=lambda kv: kv[1]):
            self.source_combo.addItem(label, source_id)
        index = self.source_combo.findData(current)
        self.source_combo.setCurrentIndex(max(index, 0))
        self.source_combo.blockSignals(False)  # noqa: FBT003
        self._on_source()

    # ------------------------------------------------------------------ language

    def retranslate_ui(self) -> None:
        tr = self._tr.tr
        self._title.setText(tr("ui.available.title"))
        self.search.setPlaceholderText(tr("ui.available.search"))
        self.search.setToolTip(tr("ui.available.search.tip"))
        self.chips.set_chip_tooltip(tr("ui.available.chip.tip"))
        self.source_combo.setToolTip(tr("ui.available.source.tip"))
        self.show_active.setText(tr("ui.available.show_active"))
        self.show_active.setToolTip(tr("ui.available.show_active.tip"))
        self._chip_specs, self._source_map = [], {}
        self._rebuild_filters()
