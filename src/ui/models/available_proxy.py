"""Filter/sort proxy over the Available list."""

from collections.abc import Sequence
from typing import override

from PySide6.QtCore import (
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from src.core.ids import ModId
from src.ui.models.roles import DragOrigin, Role, encode_payload
from src.ui.qt_compat import refilter_rows

type AnyIndex = QModelIndex | QPersistentModelIndex


class AvailableFilterProxy(QSortFilterProxyModel):
    """Casefolded token AND over ``SEARCH_BLOB``, tier/source sets and a show-enabled switch."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tokens: tuple[str, ...] = ()
        self._tiers: frozenset[str] = frozenset()
        self._sources: frozenset[str] = frozenset()
        self._show_enabled = False
        self.setDynamicSortFilter(True)
        self.setSortRole(Role.SORT_KEY)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.sort(0, Qt.SortOrder.AscendingOrder)

    def set_query(self, text: str) -> None:
        tokens = tuple(text.casefold().split())
        if tokens != self._tokens:
            self._tokens = tokens
            refilter_rows(self)

    def set_tiers(self, tiers: frozenset[str]) -> None:
        if tiers != self._tiers:
            self._tiers = frozenset(tiers)
            refilter_rows(self)

    def set_sources(self, sources: frozenset[str]) -> None:
        if sources != self._sources:
            self._sources = frozenset(sources)
            refilter_rows(self)

    def set_show_enabled(self, show: bool) -> None:
        if show != self._show_enabled:
            self._show_enabled = show
            refilter_rows(self)

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: AnyIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        index = model.index(source_row, 0, source_parent)
        if not self._show_enabled and index.data(Role.ENABLED):
            return False
        if self._tiers and index.data(Role.TIER) not in self._tiers:
            return False
        if self._sources and index.data(Role.SOURCE) not in self._sources:
            return False
        if not self._tokens:
            return True
        blob = str(index.data(Role.SEARCH_BLOB) or "").casefold()
        return all(token in blob for token in self._tokens)

    @override
    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:
        """Dragged ids in VISIBLE order (the proxy's sort), deduplicated per row."""
        by_row = {i.row(): i for i in indexes if i.isValid()}
        ids = [ModId(str(by_row[row].data(Role.MOD_ID))) for row in sorted(by_row)]
        return encode_payload(DragOrigin.AVAILABLE, ids)
