"""A wrapping row of checkable, tier-tinted chips ("Class (12)")."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QLayout,
    QLayoutItem,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from src.ui.theme.theme import set_role


class FlowLayout(QLayout):
    """Lays items left to right and wraps to the next line (the classic Qt flow layout)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    @override
    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    @override
    def count(self) -> int:
        return len(self._items)

    @override
    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    @override
    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    @override
    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    @override
    def hasHeightForWidth(self) -> bool:
        return True

    @override
    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    @override
    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    @override
    def sizeHint(self) -> QSize:
        return self.minimumSize()

    @override
    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row_height = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and row_height > 0:
                x, y, row_height = area.x(), y + row_height + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + margins.bottom()


@dataclass(frozen=True, slots=True)
class ChipSpec:
    tier_id: str
    label: str
    color: str
    count: int


class TierChips(QWidget):
    """One checkable chip per tier; an empty selection means every tier."""

    selectionChanged = Signal(frozenset)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = FlowLayout(self)
        self._buttons: dict[str, QToolButton] = {}
        self._tooltip = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def selected(self) -> frozenset[str]:
        return frozenset(tier for tier, button in self._buttons.items() if button.isChecked())

    def set_chip_tooltip(self, text: str) -> None:
        self._tooltip = text
        for button in self._buttons.values():
            button.setToolTip(f"{button.property('chip_label')}: {text}")

    def set_chips(self, specs: Sequence[ChipSpec]) -> None:
        """Rebuild the chips, keeping the checked state of tiers that remain."""
        keep = self.selected()
        for button in self._buttons.values():
            self._layout.removeWidget(button)
            button.deleteLater()
        self._buttons = {}
        for spec in specs:
            self._add(spec, checked=spec.tier_id in keep)
        self.updateGeometry()
        if self.selected() != keep:
            self.selectionChanged.emit(self.selected())

    def _add(self, spec: ChipSpec, *, checked: bool) -> None:
        button = QToolButton(self)
        button.setCheckable(True)
        button.setChecked(checked)
        button.setText(f"{spec.label} ({spec.count})")
        button.setProperty("chip_label", spec.label)
        button.setToolTip(f"{spec.label}: {self._tooltip}" if self._tooltip else spec.label)
        button.setStyleSheet(f"QToolButton[role='chip'] {{ border-color: {spec.color}; }}")
        set_role(button, "chip")
        button.toggled.connect(lambda _on: self.selectionChanged.emit(self.selected()))
        self._layout.addWidget(button)
        self._buttons[spec.tier_id] = button
