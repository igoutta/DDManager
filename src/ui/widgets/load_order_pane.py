"""The center pane: direction captions, the Load Order table and the move-button column."""

from collections.abc import Sequence
from typing import override

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.ids import ModId
from src.core.load_order import MoveOp
from src.ui.controller import MainController
from src.ui.i18n import Translator
from src.ui.models.load_order_model import Col
from src.ui.theme.style import install_drop_indicator
from src.ui.theme.theme import set_property
from src.ui.theme.tokens import DENSITY, ThemeTokens
from src.ui.viewmodels import StatusVM
from src.ui.widgets.delegates import FindingsBadgeDelegate, RankDelegate, TierBadgeDelegate
from src.ui.widgets.mod_views import LoadOrderView, select_ids, selected_ids

_RANK_PX = 48
# Badge and source columns follow their contents (header text included), the title stretches.
_FIT = (Col.TIER, Col.SOURCE, Col.FINDINGS)


class ChipLabel(QLabel):
    """A small clickable caption (the "winning end unverified" chip next to the top label)."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        set_property(self, "role", "chip")

    @override
    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class LoadOrderPane(QWidget):
    selectionChangedIds = Signal(list)
    unverifiedClicked = Signal()
    actionsStale = Signal()

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
        self._tokens = tokens
        self._buttons = QVBoxLayout()
        self._context_actions: Sequence[QAction | None] = ()
        self._build()
        self._wire()
        self.retranslate_ui()

    # ------------------------------------------------------------------ construction

    def _build(self) -> None:
        self.top_label = QLabel(self)
        self.bottom_label = QLabel(self)
        self.unverified = ChipLabel(self)
        self.view = LoadOrderView(self._tr.tr, self)
        self.view.setModel(self._c.load_order_model)
        install_drop_indicator(self.view, self._tokens.palette.gold)
        self.view.setItemDelegateForColumn(Col.RANK, RankDelegate(self.view, self._tokens))
        self.view.setItemDelegateForColumn(Col.TIER, TierBadgeDelegate(self.view, self._tokens))
        self.view.setItemDelegateForColumn(
            Col.FINDINGS, FindingsBadgeDelegate(self.view, self._tokens)
        )
        self._configure_header()
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        center = QVBoxLayout()
        top_row = QHBoxLayout()
        top_row.addWidget(self.top_label, 1)
        top_row.addWidget(self.unverified)
        center.addLayout(top_row)
        center.addWidget(self.view, 1)
        center.addWidget(self.bottom_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._buttons.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(self._buttons)
        layout.addLayout(center, 1)
        self.set_density("Comfortable")

    def _configure_header(self) -> None:
        header = self.view.horizontalHeader()
        if header is None:
            return
        header.setStretchLastSection(False)
        header.setSectionResizeMode(Col.TITLE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(Col.RANK, QHeaderView.ResizeMode.Fixed)
        self.view.setColumnWidth(Col.RANK, _RANK_PX)
        for col in _FIT:
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    def _wire(self) -> None:
        selection = self.view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._on_selection)
        self.view.set_key_handler(Qt.Key.Key_Space, self.disable_selection)
        self.view.set_key_handler(Qt.Key.Key_Delete, self.disable_selection)
        self.view.customContextMenuRequested.connect(self._popup)
        self.unverified.clicked.connect(self.unverifiedClicked)
        self._c.thumbnails.ready.connect(self._repaint)
        model = self._c.load_order_model
        model.rowsInserted.connect(self._on_rows)
        model.rowsRemoved.connect(self._on_rows)
        model.layoutChanged.connect(self._on_rows)

    # ------------------------------------------------------------------ actions

    def attach_actions(
        self,
        move_actions: Sequence[QAction],
        context_actions: Sequence[QAction | None],
        *,
        shortcut_actions: Sequence[QAction] = (),
    ) -> None:
        """Bind the button column to shared actions (``None`` in the context list = separator)."""
        for action in move_actions:
            button = QToolButton(self)
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setAutoRaise(True)
            self._buttons.addWidget(button)
        for action in shortcut_actions:
            self.addAction(action)
        self._context_actions = context_actions
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

    def _popup(self, point: QPoint) -> None:
        index = self.view.indexAt(point)
        selection = self.view.selectionModel()
        if index.isValid() and selection is not None and not selection.isSelected(index):
            self.view.selectRow(index.row())
        menu = QMenu(self.view)
        for action in self._context_actions:
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)
        menu.exec(self.view.viewport().mapToGlobal(point))

    def selected_rows(self) -> list[int]:
        selection = self.view.selectionModel()
        return sorted(i.row() for i in selection.selectedRows()) if selection else []

    def selected_ids(self) -> list[ModId]:
        return selected_ids(self.view)

    def select(self, ids: list[ModId]) -> None:
        select_ids(self.view, ids)

    def disable_selection(self) -> None:
        ids = self.selected_ids()
        if ids:
            self._c.disable(ids)

    def move_selection(self, op: MoveOp) -> None:
        ids = self.selected_ids()
        if ids:
            self._c.move(ids, op)

    def noop_flags(self) -> dict[str, bool]:
        """Which move directions would change nothing for the current selection."""
        rows = self.selected_rows()
        total = self._c.load_order_model.rowCount()
        count = len(rows)
        at_top = rows == list(range(count))
        at_bottom = rows == list(range(total - count, total))
        return {
            "none": not rows,
            "top": not rows or at_top,
            "up": not rows or at_top,
            "down": not rows or at_bottom,
            "bottom": not rows or at_bottom,
        }

    def refresh_actions(self) -> None:
        self.actionsStale.emit()

    def _repaint(self, *_args: object) -> None:
        self.view.viewport().update()

    def _on_rows(self, *_args: object) -> None:
        self.refresh_actions()

    def _on_selection(self, *_args: object) -> None:
        self.refresh_actions()
        self.selectionChangedIds.emit(self.selected_ids())

    # ------------------------------------------------------------------ rendering

    def set_density(self, mode: str) -> None:
        icon, row = DENSITY.get(mode, DENSITY["Comfortable"])
        self._c.load_order_model.set_icon_px(icon)
        vertical = self.view.verticalHeader()
        if vertical is not None:
            vertical.setDefaultSectionSize(row)
        self.view.setIconSize(QSize(icon, icon))

    def update_status(self, status: StatusVM) -> None:
        """Direction captions: the winning end is gold; unverified shows the warning chip."""
        tr = self._tr.tr
        self.top_label.setText(status.direction_top_label)
        self.bottom_label.setText(status.direction_bottom_label)
        wins_top = status.direction_top_label == tr("ui.dir.top_wins")
        wins_bottom = status.direction_bottom_label == tr("ui.dir.bottom_wins")
        set_property(self.top_label, "direction", "wins" if wins_top else "normal")
        set_property(self.bottom_label, "direction", "wins" if wins_bottom else "normal")
        self.unverified.setVisible(not status.direction_verified)

    def retranslate_ui(self) -> None:
        tr = self._tr.tr
        self.unverified.setText(tr("ui.dir.unverified_chip"))
        self.unverified.setToolTip(tr("ui.dir.unverified_tip"))
        self.view.setToolTip("")
        self.unverified.setStyleSheet(f"color: {self._tokens.palette.warning};")
