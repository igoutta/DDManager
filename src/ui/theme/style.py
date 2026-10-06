"""A proxy style that draws the drop indicator as one gold line across the whole row."""

from typing import override

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QProxyStyle,
    QStyle,
    QStyleOption,
    QWidget,
)

LINE_WIDTH = 2


class DropIndicatorStyle(QProxyStyle):
    """Fusion draws the table drop indicator around one cell; this paints a 2 px full-row line."""

    def __init__(self, color: str, base: str = "Fusion") -> None:
        super().__init__(base)
        self._color = QColor(color)

    @override
    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        if (
            element != QStyle.PrimitiveElement.PE_IndicatorItemViewItemDrop
            or not isinstance(widget, QAbstractItemView)
            or widget.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.OnItem
        ):
            super().drawPrimitive(element, option, painter, widget)
            return
        below = widget.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem
        y = option.rect.bottom() if below else option.rect.top()
        y = max(y, LINE_WIDTH // 2)
        painter.save()
        painter.setPen(QPen(self._color, LINE_WIDTH))
        painter.drawLine(0, y, widget.viewport().width(), y)
        painter.restore()


def install_drop_indicator(view: QAbstractItemView, color: str) -> DropIndicatorStyle:
    """Give ``view`` the gold row indicator; the style is parented to the view so it lives on."""
    style = DropIndicatorStyle(color)
    style.setParent(view)
    view.setStyle(style)
    return style
