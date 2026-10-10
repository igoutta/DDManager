"""Small building blocks of the Details pane: the scaling thumbnail, labels, chips, clearing."""

from typing import override

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QLayout, QSizePolicy

from src.ui.theme.theme import set_role


def clear_layout(layout: QLayout) -> None:
    """Remove every item, nested layouts included; widgets are hidden now and deleted later.

    Hiding first matters: ``deleteLater`` only runs once control is back in the event loop,
    and until then a merely removed widget would still be painted where it last was.
    """
    while (item := layout.takeAt(0)) is not None:
        child = item.layout()
        if child is not None:
            clear_layout(child)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()


def make_label(text: str, role: str | None = None, *, selectable: bool = True) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if role:
        set_role(label, role)
    return label


def tag_chip(tag: str, tooltip: str) -> QLabel:
    chip = QLabel(tag)
    chip.setToolTip(tooltip)
    chip.setStyleSheet("padding: 1px 6px; border: 1px solid palette(mid); border-radius: 8px;")
    return chip


class ThumbLabel(QLabel):
    """A centred preview that scales to the width it is given (never above ``max_px``).

    The label asks for no minimum width, so a narrow pane shrinks the picture instead of
    growing a horizontal scrollbar; the height follows the width to keep the aspect ratio.
    """

    def __init__(self, max_px: int) -> None:
        super().__init__()
        self._max = max_px
        self._source = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(max_px // 4)

    def set_source(self, pixmap: QPixmap | None, placeholder: str = "") -> None:
        self._source = pixmap if pixmap is not None else QPixmap()
        if self._source.isNull():
            self.setText(placeholder)
            set_role(self, "muted")
        else:
            self._rescale()
        self.updateGeometry()

    def source(self) -> QPixmap:
        return self._source

    def target_width(self, width: int | None = None) -> int:
        """The width the picture gets at label width ``width`` (the current one by default)."""
        available = self.width() if width is None else width
        return max(1, min(self._max, available, self._source.width() or self._max))

    def _rescale(self) -> None:
        if self._source.isNull():
            return
        scaled = self._source.scaled(
            self.target_width(),
            self._max,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

    @override
    def hasHeightForWidth(self) -> bool:
        return not self._source.isNull()

    @override
    def heightForWidth(self, width: int) -> int:
        if self._source.isNull() or self._source.width() <= 0:
            return super().heightForWidth(width)
        return -(-self._source.height() * self.target_width(width) // self._source.width())

    @override
    def sizeHint(self) -> QSize:
        if self._source.isNull():
            return super().sizeHint()
        width = self.target_width(self._max)
        return QSize(width, self.heightForWidth(width))

    @override
    def minimumSizeHint(self) -> QSize:
        if self._source.isNull():
            return super().minimumSizeHint()
        return QSize(0, self.minimumHeight())

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self._source.isNull() and (
            self.pixmap().isNull() or self.pixmap().width() != self.target_width()
        ):
            self._rescale()
