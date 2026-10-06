"""A label that elides its text in the middle and keeps the full text as its tooltip."""

from typing import override

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """``setText`` stores the full text; painting shows it elided in the middle."""

    doubleClicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self._mode = Qt.TextElideMode.ElideMiddle
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    @override
    def setText(self, text: str) -> None:
        self._full = text
        super().setText(text)
        self.update()

    def full_text(self) -> str:
        return self._full

    def elided_text(self) -> str:
        """The text as it would be painted at the current width."""
        return QFontMetrics(self.font()).elidedText(self._full, self._mode, max(self.width(), 0))

    @override
    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

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
