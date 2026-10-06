"""Item delegates: the Available row, the tier badge and the findings badge."""

from collections.abc import Callable
from typing import Final, override

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from src.core.findings import Severity
from src.ui.models.roles import Role
from src.ui.theme.tokens import ThemeTokens
from src.ui.thumbnails import ThumbnailProvider
from src.ui.viewmodels import ModRowVM

type AnyIndex = QModelIndex | QPersistentModelIndex
type Tr = Callable[..., str]

STRIPE_PX: Final = 4
PAD: Final = 6
CHECK_PX: Final = 16
PILL_PAD: Final = 6
_UNASSIGNED: Final = "unassigned"


def severity_color(tokens: ThemeTokens, severity: int) -> str:
    """The semantic palette color of a finding severity value."""
    if severity >= Severity.ERROR:
        return tokens.palette.error
    if severity >= Severity.WARNING:
        return tokens.palette.warning
    return tokens.palette.info


def draw_pill(painter: QPainter, rect: QRect, text: str, fill: str, ink: str) -> None:
    """A rounded label: ``fill`` background, ``ink`` text."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    painter.setPen(QColor(ink))
    painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
    painter.restore()


def pill_width(font: QFont, text: str) -> int:
    return QFontMetrics(font).horizontalAdvance(text) + 2 * PILL_PAD


class ModRowDelegate(QStyledItemDelegate):
    """Tier stripe, checkbox, thumbnail, title, muted second line, NEW pill, missing marker."""

    def __init__(
        self,
        parent: QWidget,
        thumbs: ThumbnailProvider,
        tokens: ThemeTokens,
        tr: Tr,
    ) -> None:
        super().__init__(parent)
        self._thumbs = thumbs
        self._tokens = tokens
        self._tr = tr
        self._icon_px = 0
        self._row_px = 46

    def set_density(self, icon_px: int, row_px: int) -> None:
        self._icon_px, self._row_px = icon_px, row_px

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: AnyIndex) -> QSize:
        return QSize(option.rect.width(), self._row_px)

    def _check_rect(self, rect: QRect) -> QRect:
        return QRect(
            rect.left() + STRIPE_PX + PAD, rect.center().y() - CHECK_PX // 2, CHECK_PX, CHECK_PX
        )

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex) -> None:
        vm = index.data(Role.VM)
        if not isinstance(vm, ModRowVM):
            super().paint(painter, option, index)
            return
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        painter.save()
        rect = option.rect
        painter.fillRect(QRect(rect.left(), rect.top(), STRIPE_PX, rect.height()), QColor(vm.color))
        self._paint_check(painter, option, vm)
        x = self._check_rect(rect).right() + PAD
        x = self._paint_thumb(painter, rect, vm, x)
        self._paint_text(
            painter, option, vm, QRect(x, rect.top(), rect.right() - x - PAD, rect.height())
        )
        painter.restore()

    def _paint_check(self, painter: QPainter, option: QStyleOptionViewItem, vm: ModRowVM) -> None:
        check = QStyleOptionViewItem(option)
        check.rect = self._check_rect(option.rect)
        check.state = QStyle.StateFlag.State_Enabled | (
            QStyle.StateFlag.State_On if vm.enabled else QStyle.StateFlag.State_Off
        )
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck, check, painter, option.widget
        )

    def _paint_thumb(self, painter: QPainter, rect: QRect, vm: ModRowVM, x: int) -> int:
        if self._icon_px <= 0:
            return x
        size = min(self._icon_px, rect.height() - 4)
        target = QRect(x, rect.top() + (rect.height() - size) // 2, size, size)
        pixmap = self._thumbs.pixmap(vm.mod_id, vm.icon_path, vm.icon_stamp, self._icon_px)
        if isinstance(pixmap, QPixmap):
            painter.drawPixmap(target, pixmap)
        else:
            painter.fillRect(target, QColor(self._tokens.palette.panel_deep))
        return x + size + PAD

    def _paint_text(
        self, painter: QPainter, option: QStyleOptionViewItem, vm: ModRowVM, area: QRect
    ) -> None:
        palette = self._tokens.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        main = palette.select_text if selected else (palette.muted if vm.enabled else palette.text)
        title_font = QFont(option.font)
        title_font.setBold(True)
        metrics = QFontMetrics(title_font)
        right = area.right()
        right = self._paint_pills(painter, option, vm, area.top() + 4, right)
        painter.setFont(title_font)
        painter.setPen(QColor(main))
        title_rect = QRect(area.left(), area.top() + 4, right - area.left(), metrics.height())
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(vm.title, Qt.TextElideMode.ElideRight, title_rect.width()),
        )
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(max(sub_font.pointSizeF() - 1, 7))
        painter.setFont(sub_font)
        painter.setPen(QColor(palette.select_text if selected else palette.muted))
        sub_rect = QRect(
            area.left(), title_rect.bottom() + 2, area.width(), QFontMetrics(sub_font).height()
        )
        painter.drawText(
            sub_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            QFontMetrics(sub_font).elidedText(
                vm.subtitle, Qt.TextElideMode.ElideRight, sub_rect.width()
            ),
        )

    def _paint_pills(
        self, painter: QPainter, option: QStyleOptionViewItem, vm: ModRowVM, top: int, right: int
    ) -> int:
        """Right-aligned markers; returns the new right edge available for the title."""
        palette = self._tokens.palette
        height = QFontMetrics(option.font).height()
        markers: list[tuple[str, str, str]] = []
        if vm.is_new:
            markers.append((self._tr("ui.row.new"), palette.gold, palette.ink))
        if vm.missing:
            markers.append((self._tr("ui.row.missing_pill"), palette.error, palette.ink))
        if vm.tier_id == _UNASSIGNED and not vm.missing:
            markers.append(("+", palette.border, palette.text))
        for text, fill, ink in markers:
            width = pill_width(option.font, text)
            draw_pill(painter, QRect(right - width, top, width, height), text, fill, ink)
            right -= width + PAD
        return right

    @override
    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: AnyIndex,
    ) -> bool:
        """A click on the checkbox asks the model to toggle ENABLED (the controller decides)."""
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and self._check_rect(option.rect).contains(event.position().toPoint())
        ):
            wanted = not bool(index.data(Role.ENABLED))
            state = Qt.CheckState.Checked if wanted else Qt.CheckState.Unchecked
            return model.setData(index, state, Qt.ItemDataRole.CheckStateRole)
        return super().editorEvent(event, model, option, index)


class TierBadgeDelegate(QStyledItemDelegate):
    """The tier column: a pill tinted with the row's tier color and the 3-letter badge."""

    def __init__(self, parent: QWidget, tokens: ThemeTokens) -> None:
        super().__init__(parent)
        self._tokens = tokens

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex) -> None:
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        color = index.data(Role.TIER_COLOR)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if not color or not text:
            return
        height = QFontMetrics(option.font).height() + 2
        rect = QRect(0, 0, min(option.rect.width() - 8, pill_width(option.font, text)), height)
        rect.moveCenter(option.rect.center())
        draw_pill(painter, rect, text, str(color), self._tokens.palette.ink)


class FindingsBadgeDelegate(QStyledItemDelegate):
    """A severity-colored dot with the finding count."""

    def __init__(self, parent: QWidget, tokens: ThemeTokens) -> None:
        super().__init__(parent)
        self._tokens = tokens

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex) -> None:
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        count = int(index.data(Role.FINDING_COUNT) or 0)
        if count <= 0:
            return
        color = severity_color(self._tokens, int(index.data(Role.WORST_SEVERITY) or 0))
        height = QFontMetrics(option.font).height() + 2
        text = str(count)
        rect = QRect(0, 0, max(height, pill_width(option.font, text)), height)
        rect.moveCenter(option.rect.center())
        draw_pill(painter, rect, text, color, self._tokens.palette.ink)


class RankDelegate(QStyledItemDelegate):
    """The # column: the model leaves the text empty, the rank is painted from ``Role.RANK``."""

    def __init__(self, parent: QWidget, tokens: ThemeTokens) -> None:
        super().__init__(parent)
        self._tokens = tokens

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex) -> None:
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setPen(
            QColor(self._tokens.palette.select_text if selected else self._tokens.palette.muted)
        )
        painter.drawText(
            option.rect.adjusted(0, 0, -PAD, 0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            str(index.data(Role.RANK) or ""),
        )
        painter.restore()
