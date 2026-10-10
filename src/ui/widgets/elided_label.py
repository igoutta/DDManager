"""A label that elides its text in the middle and keeps the full text as its tooltip."""

from typing import override

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

ELLIPSIS = "…"


class ElidedLabel(QLabel):
    """``setText`` stores the full text; painting shows it elided in the middle.

    The label asks a layout for the full text width (bounded by its maximum width), accepts
    anything down to ``minimum_px`` (at least an ellipsis) and never paints past its own rect,
    so it can share a row with other widgets without overlapping them.
    """

    doubleClicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None, minimum_px: int = 0) -> None:
        super().__init__(parent)
        self._full = ""
        self._minimum_px = minimum_px
        self._mode = Qt.TextElideMode.ElideMiddle
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setText(text)

    @override
    def setText(self, text: str) -> None:
        self._full = text
        super().setText(text)
        self.updateGeometry()
        self.update()

    def full_text(self) -> str:
        return self._full

    def elided_text(self) -> str:
        """The text as it would be painted at the current width."""
        return QFontMetrics(self.font()).elidedText(self._full, self._mode, max(self.width(), 0))

    def _text_width(self, text: str) -> int:
        margin = 2 * self.margin()
        return QFontMetrics(self.font()).horizontalAdvance(text) + margin

    @override
    def minimumSizeHint(self) -> QSize:
        width = max(self._minimum_px, self._text_width(ELLIPSIS))
        return QSize(min(width, self.maximumWidth()), super().minimumSizeHint().height())

    @override
    def sizeHint(self) -> QSize:
        width = max(self._text_width(self._full), self.minimumSizeHint().width())
        return QSize(min(width, self.maximumWidth()), super().sizeHint().height())

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = QRect(QPoint(0, 0), self.size())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(rect, int(self.alignment()), self.elided_text())

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.update()

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)
