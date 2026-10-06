"""The two mod views. Both own ``startDrag`` so Qt never calls ``removeRows`` after a move."""

from collections.abc import Callable, Sequence
from typing import override

from PySide6.QtCore import QModelIndex, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QTableView, QWidget

from src.core.ids import ModId
from src.ui.models.roles import Role

type Tr = Callable[..., str]
_BADGE_H = 28
_BADGE_PAD = 12
_PLAIN = (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)


def selected_rows(view: QAbstractItemView) -> list[QModelIndex]:
    selection = view.selectionModel()
    return list(selection.selectedRows()) if selection is not None else []


def selected_ids(view: QAbstractItemView) -> list[ModId]:
    """The mod ids of the selected rows in display order."""
    rows = sorted(selected_rows(view), key=lambda index: index.row())
    return [ModId(str(index.data(Role.MOD_ID))) for index in rows]


def render_drag_badge(view: QAbstractItemView, count: int, label: str) -> QPixmap:
    """A small pill: the first title and "+N more"."""
    text = label if count <= 1 else f"{label}  (+{count - 1})"
    metrics = QFontMetrics(view.font())
    width = min(metrics.horizontalAdvance(text) + 2 * _BADGE_PAD, 320)
    pixmap = QPixmap(width, _BADGE_H)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    palette = view.palette()
    painter.setBrush(palette.color(palette.ColorRole.Highlight))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRect(0, 0, width, _BADGE_H), 6, 6)
    painter.setPen(QColor(palette.color(palette.ColorRole.HighlightedText)))
    elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, width - 2 * _BADGE_PAD)
    painter.drawText(QRect(0, 0, width, _BADGE_H), int(Qt.AlignmentFlag.AlignCenter), elided)
    painter.end()
    return pixmap


def start_mod_drag(view: QAbstractItemView, tr: Tr) -> None:
    """Run our own drag; mutations only happen through ``dropMimeData`` -> the controller."""
    rows = selected_rows(view)
    model = view.model()
    if not rows or model is None:
        return
    mime = model.mimeData(rows)
    if mime is None:
        return
    drag = QDrag(view)
    drag.setMimeData(mime)
    first = str(rows[0].data(Qt.ItemDataRole.DisplayRole) or tr("ui.drag.mods", count=len(rows)))
    drag.setPixmap(render_drag_badge(view, len(rows), first))
    drag.setHotSpot(QPoint(10, _BADGE_H // 2))
    drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)
    # Deliberately NOT super().startDrag(): QAbstractItemView would call removeRows() after a
    # MoveAction. Every change goes through dropMimeData -> controller.


class _KeyHandlers:
    """Space/Delete forwarding shared by both views."""

    def __init__(self) -> None:
        self.handlers: dict[int, Callable[[], None]] = {}

    def handle(self, event: QKeyEvent) -> bool:
        handler = self.handlers.get(event.key())
        if handler is None or event.modifiers() not in _PLAIN:
            return False
        handler()
        event.accept()
        return True


class ModListView(QListView):
    """The Available list: extended selection, drags out with origin AVAILABLE."""

    def __init__(self, tr: Tr, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tr = tr
        self._keys = _KeyHandlers()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def set_key_handler(self, key: int, handler: Callable[[], None]) -> None:
        self._keys.handlers[key] = handler

    @override
    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        del supportedActions
        start_mod_drag(self, self._tr)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._keys.handle(event):
            super().keyPressEvent(event)


class LoadOrderView(QTableView):
    """The never-filtered load order: drops land between rows, gold line indicator."""

    def __init__(self, tr: Tr, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tr = tr
        self._keys = _KeyHandlers()
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)
        self.setAutoScroll(True)
        self.setAutoScrollMargin(24)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setCornerButtonEnabled(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        vertical = self.verticalHeader()
        if vertical is not None:
            vertical.setVisible(False)

    def set_key_handler(self, key: int, handler: Callable[[], None]) -> None:
        self._keys.handlers[key] = handler

    @override
    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        del supportedActions
        start_mod_drag(self, self._tr)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._keys.handle(event):
            super().keyPressEvent(event)


def select_ids(view: QAbstractItemView, ids: Sequence[ModId]) -> None:
    """Select the rows of ``ids`` that the view's model shows and scroll to the first."""
    model, selection = view.model(), view.selectionModel()
    if model is None or selection is None:
        return
    wanted = set(ids)
    selection.clearSelection()
    first: QModelIndex | None = None
    for row in range(model.rowCount()):
        index = model.index(row, 0)
        if index.data(Role.MOD_ID) in wanted:
            selection.select(
                index,
                selection.SelectionFlag.Select | selection.SelectionFlag.Rows,
            )
            if first is None:
                first = index
    if first is not None:
        view.scrollTo(first)
