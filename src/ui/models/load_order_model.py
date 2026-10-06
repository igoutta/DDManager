"""The Load Order table: a never-filtered projection of the enabled order (row == rank - 1)."""

from collections.abc import Callable, Sequence
from enum import IntEnum
from itertools import groupby
from typing import Any, Final, override

from PySide6.QtCore import (
    QAbstractItemModel,
    QAbstractTableModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)

from src.core.ids import ModId
from src.ui.i18n import Translator
from src.ui.models.roles import (
    MIME_MOD_IDS,
    VM_ROLES,
    DragOrigin,
    Role,
    decode_payload,
    encode_payload,
)
from src.ui.models.runs import contiguous_runs
from src.ui.thumbnails import ThumbnailProvider
from src.ui.viewmodels import ModRowVM

type AnyIndex = QModelIndex | QPersistentModelIndex
_ROOT: Final = QModelIndex()
_DROP_ACTIONS: Final = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction
_ALIGN_RANK: Final = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class Col(IntEnum):
    RANK = 0
    TIER = 1
    TITLE = 2
    SOURCE = 3
    FINDINGS = 4


_HEADER_KEYS: Final = {
    Col.RANK: "ui.lo.col.rank",
    Col.TIER: "ui.lo.col.tier",
    Col.TITLE: "ui.lo.col.title",
    Col.SOURCE: "ui.lo.col.source",
    Col.FINDINGS: "ui.lo.col.findings",
}
_LAST_COL: Final = len(Col) - 1


class LoadOrderModel(QAbstractTableModel):
    """Row N is position N of the real enabled order; it never filters.

    User gestures become ``*Requested`` signals; the controller computes the new order in core
    and calls :meth:`apply_rows`, the only mutation entry point besides :meth:`moveRows`.
    """

    moveRequested = Signal(list, int)
    enableRequested = Signal(list, int)
    disableRequested = Signal(list)

    def __init__(
        self, thumbs: ThumbnailProvider, tr: Translator, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._rows: list[ModRowVM] = []
        self._row_of: dict[ModId, int] = {}
        self._thumbs = thumbs
        self._tr = tr
        self._icon_px = 0
        thumbs.ready.connect(self._on_thumb_ready)
        tr.languageChanged.connect(self._on_language_changed)

    # ---- read API ------------------------------------------------------------
    def order(self) -> tuple[ModId, ...]:
        return tuple(vm.mod_id for vm in self._rows)

    def row_of(self, mod_id: ModId) -> int | None:
        return self._row_of.get(mod_id)

    def vm_at(self, row: int) -> ModRowVM | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def set_icon_px(self, px: int) -> None:
        """Thumbnail size from the density setting (0 = no icons)."""
        if px != self._icon_px:
            self._icon_px = px
            self._emit_block(
                0, len(self._rows) - 1, Col.TITLE, Col.TITLE, [Qt.ItemDataRole.DecorationRole]
            )

    def _reindex(self) -> None:
        self._row_of = {vm.mod_id: row for row, vm in enumerate(self._rows)}

    @override
    def rowCount(self, parent: AnyIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._rows)

    @override
    def columnCount(self, parent: AnyIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(Col)

    @override
    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        if not 0 <= section < len(Col):
            return None
        return self._tr.tr(_HEADER_KEYS[Col(section)])

    @override
    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not self.checkIndex(index, QAbstractItemModel.CheckIndexOption.IndexIsValid):
            return None
        row, col = index.row(), Col(index.column())
        vm = self._rows[row]
        if role == Role.RANK:
            return row + 1
        getter = VM_ROLES.get(role)
        if getter is not None:
            return getter(vm)
        handler = self._text_roles().get(role)
        return handler(vm, col, row) if handler is not None else None

    def _text_roles(self) -> dict[int, Callable[[ModRowVM, Col, int], Any]]:
        return {
            Qt.ItemDataRole.DisplayRole: self._display,
            Qt.ItemDataRole.ToolTipRole: self._tooltip,
            Qt.ItemDataRole.DecorationRole: self._decoration,
            Qt.ItemDataRole.TextAlignmentRole: self._alignment,
            Qt.ItemDataRole.AccessibleTextRole: self._accessible,
        }

    @staticmethod
    def _display(vm: ModRowVM, col: Col, row: int) -> str:
        texts = {
            Col.RANK: "",  # rank varies with position: see Role.RANK
            Col.TIER: vm.tier_badge,
            Col.TITLE: vm.title,
            Col.SOURCE: vm.source_label,
            Col.FINDINGS: str(vm.finding_count) if vm.finding_count else "",
        }
        return texts[col]

    def _tooltip(self, vm: ModRowVM, col: Col, row: int) -> str:
        tr = self._tr.tr
        tips = {
            Col.RANK: lambda: tr("ui.lo.rank_tip", rank=row + 1, total=len(self._rows), entry=row),
            Col.TIER: lambda: tr("ui.lo.tier_tip", tier=vm.tier_label, category=vm.category_label),
            Col.SOURCE: lambda: f"{vm.source_label} - {vm.save_identity_text}",
            Col.FINDINGS: lambda: vm.finding_summary or tr("ui.lo.no_findings"),
            Col.TITLE: lambda: f"{vm.title}\n{vm.folder}",
        }
        return tips[col]()

    def _decoration(self, vm: ModRowVM, col: Col, row: int) -> Any:
        del row
        if col != Col.TITLE or self._icon_px <= 0:
            return None
        return self._thumbs.pixmap(vm.mod_id, vm.icon_path, vm.icon_stamp, self._icon_px)

    @staticmethod
    def _alignment(vm: ModRowVM, col: Col, row: int) -> int | None:
        del vm, row
        return _ALIGN_RANK if col == Col.RANK else None

    def _accessible(self, vm: ModRowVM, col: Col, row: int) -> str:
        del col
        return self._tr.tr(
            "ui.lo.accessible",
            rank=row + 1,
            title=vm.title,
            tier=vm.tier_label,
            source=vm.source_label,
        )

    @override
    def flags(self, index: AnyIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled  # drops land BETWEEN rows, never on one
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemNeverHasChildren
        )

    # ---- drag and drop ----------------------------------------------------------
    @override
    def mimeTypes(self) -> list[str]:
        return [MIME_MOD_IDS]

    @override
    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    @override
    def supportedDropActions(self) -> Qt.DropAction:
        return _DROP_ACTIONS

    @override
    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:
        rows = sorted({i.row() for i in indexes if i.isValid()})
        return encode_payload(DragOrigin.LOAD_ORDER, [self._rows[r].mod_id for r in rows])

    @override
    def canDropMimeData(
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: AnyIndex
    ) -> bool:
        return decode_payload(data) is not None

    @override
    def dropMimeData(
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: AnyIndex
    ) -> bool:
        """Emit the request and return True WITHOUT mutating: the controller owns the order."""
        payload = decode_payload(data)
        if payload is None or not (action & _DROP_ACTIONS):
            return False
        target = row if row >= 0 else (parent.row() if parent.isValid() else len(self._rows))
        target = min(max(target, 0), len(self._rows))
        if payload.origin is DragOrigin.LOAD_ORDER:
            self.moveRequested.emit(list(payload.ids), target)
        else:
            self.enableRequested.emit(list(payload.ids), target)
        return True

    # ---- structure ----------------------------------------------------------------
    @override
    def moveRows(
        self,
        sourceParent: AnyIndex,
        sourceRow: int,
        count: int,
        destinationParent: AnyIndex,
        destinationChild: int,
    ) -> bool:
        n = len(self._rows)
        src, dst = sourceRow, destinationChild
        if sourceParent.isValid() or destinationParent.isValid() or count <= 0:
            return False
        if src < 0 or src + count > n or not 0 <= dst <= n:
            return False
        if src <= dst <= src + count:  # beginMoveRows no-op contract
            return False
        if not self.beginMoveRows(_ROOT, src, src + count - 1, _ROOT, dst):
            return False
        block = self._rows[src : src + count]
        del self._rows[src : src + count]
        at = dst - count if dst > src else dst
        self._rows[at:at] = block
        self._reindex()
        self.endMoveRows()
        self._emit_ranks(min(src, at), max(src + count, dst) - 1)
        return True

    def apply_rows(self, rows: Sequence[ModRowVM]) -> None:
        """Make the model equal ``rows``: range inserts/removes, one layout change, dataChanged."""
        new_ids = [vm.mod_id for vm in rows]
        if len(set(new_ids)) != len(new_ids):
            raise ValueError("duplicate ModId in load order")
        removed = self._remove_missing(set(new_ids))
        permuted = self._permute(new_ids)
        inserted = self._insert_new(rows)
        self._replace_payloads(rows)
        if (removed or permuted or inserted) and self._rows:
            self._emit_ranks(0, len(self._rows) - 1)

    def _remove_missing(self, keep: set[ModId]) -> bool:
        gone = [row for row, vm in enumerate(self._rows) if vm.mod_id not in keep]
        for first, last in reversed(contiguous_runs(gone)):
            self.beginRemoveRows(_ROOT, first, last)
            del self._rows[first : last + 1]
            self.endRemoveRows()
        if gone:
            self._reindex()
        return bool(gone)

    def _permute(self, new_ids: Sequence[ModId]) -> bool:
        target = [mod for mod in new_ids if mod in self._row_of]
        old_order = self.order()
        if list(old_order) == target:
            return False
        self.layoutAboutToBeChanged.emit()
        olds = self.persistentIndexList()
        by_id = {vm.mod_id: vm for vm in self._rows}
        self._rows = [by_id[mod] for mod in target]
        self._reindex()
        news = [self.index(self._row_of[old_order[i.row()]], i.column()) for i in olds]
        self.changePersistentIndexList(olds, news)
        self.layoutChanged.emit()
        return True

    def _insert_new(self, rows: Sequence[ModRowVM]) -> bool:
        present = set(self._row_of)
        position = 0
        inserted = False
        for is_new, group in groupby(rows, key=lambda vm: vm.mod_id not in present):
            block = list(group)
            if is_new:
                self.beginInsertRows(_ROOT, position, position + len(block) - 1)
                self._rows[position:position] = block
                self._reindex()
                self.endInsertRows()
                inserted = True
            position += len(block)
        return inserted

    def _replace_payloads(self, rows: Sequence[ModRowVM]) -> None:
        changed = [i for i, vm in enumerate(rows) if self._rows[i] != vm]
        for i in changed:
            self._rows[i] = rows[i]
        for first, last in contiguous_runs(changed):
            self._emit_block(first, last, 0, _LAST_COL, [])

    # ---- signals ---------------------------------------------------------------------
    def _emit_ranks(self, first: int, last: int) -> None:
        roles = [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, Role.RANK]
        self._emit_block(first, last, Col.RANK, Col.RANK, roles)

    def _emit_block(
        self, first_row: int, last_row: int, first_col: int, last_col: int, roles: Sequence[int]
    ) -> None:
        """``dataChanged`` over a rectangle (empty ``roles`` = every role)."""
        if self._rows:
            top = self.index(first_row, first_col)
            self.dataChanged.emit(top, self.index(last_row, last_col), list(roles))

    def _on_thumb_ready(self, mod_id: str) -> None:
        row = self._row_of.get(ModId(mod_id))
        if row is not None:
            index = self.index(row, Col.TITLE)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])

    def _on_language_changed(self, _code: str) -> None:
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, _LAST_COL)
        roles = [Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.AccessibleTextRole]
        self._emit_block(0, len(self._rows) - 1, 0, _LAST_COL, roles)
