"""The Available list: every discovered mod, enabled or not."""

from collections.abc import Collection, Sequence
from dataclasses import replace
from typing import Any, override

from PySide6.QtCore import (
    QAbstractItemModel,
    QAbstractListModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)

from src.core.ids import ModId
from src.ui.models.roles import (
    MIME_MOD_IDS,
    VM_ROLES,
    DragOrigin,
    Role,
    decode_payload,
    encode_payload,
)
from src.ui.models.runs import contiguous_runs
from src.ui.viewmodels import ModRowVM

type AnyIndex = QModelIndex | QPersistentModelIndex
_ROOT = QModelIndex()
_DROP_ACTIONS = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction


class AvailableModsModel(QAbstractListModel):
    """Projection of ALL mods; enabling/disabling only emits ``dataChanged``."""

    toggleRequested = Signal(list, bool)
    disableRequested = Signal(list)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[ModRowVM] = []
        self._row_of: dict[ModId, int] = {}

    # ---- read API --------------------------------------------------------
    def row_of(self, mod_id: ModId) -> int | None:
        return self._row_of.get(mod_id)

    def vm_at(self, row: int) -> ModRowVM | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _reindex(self) -> None:
        self._row_of = {vm.mod_id: row for row, vm in enumerate(self._rows)}

    @override
    def rowCount(self, parent: AnyIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._rows)

    @override
    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not self.checkIndex(index, QAbstractItemModel.CheckIndexOption.IndexIsValid):
            return None
        vm = self._rows[index.row()]
        getter = VM_ROLES.get(role)
        if getter is not None:
            return getter(vm)
        if role == Qt.ItemDataRole.DisplayRole:
            return vm.title
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{vm.title}\n{vm.folder}"
        if role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if vm.enabled else Qt.CheckState.Unchecked
        return None

    @override
    def setData(self, index: AnyIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        """A checkbox click is a request: the controller decides and calls ``set_enabled``."""
        if role != Qt.ItemDataRole.CheckStateRole or not index.isValid():
            return False
        checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value, True)
        self.toggleRequested.emit([self._rows[index.row()].mod_id], checked)
        return True

    @override
    def flags(self, index: AnyIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemNeverHasChildren
        )

    # ---- mutation (controller only) -------------------------------------------
    def set_rows(self, rows: Sequence[ModRowVM]) -> None:
        """Diff by id: remove vanished mods, append new ones, ``dataChanged`` for changed VMs."""
        new_ids = {vm.mod_id for vm in rows}
        if len(new_ids) != len(rows):
            raise ValueError("duplicate ModId in available rows")
        gone = [row for row, vm in enumerate(self._rows) if vm.mod_id not in new_ids]
        for first, last in reversed(contiguous_runs(gone)):
            self.beginRemoveRows(_ROOT, first, last)
            del self._rows[first : last + 1]
            self.endRemoveRows()
        self._reindex()
        fresh = [vm for vm in rows if vm.mod_id not in self._row_of]
        if fresh:
            start = len(self._rows)
            self.beginInsertRows(_ROOT, start, start + len(fresh) - 1)
            self._rows.extend(fresh)
            self.endInsertRows()
            self._reindex()
        self._replace_changed(rows)

    def _replace_changed(self, rows: Sequence[ModRowVM]) -> None:
        for vm in rows:
            row = self._row_of[vm.mod_id]
            if self._rows[row] != vm:
                self._rows[row] = vm
                index = self.index(row)
                self.dataChanged.emit(index, index, [])

    def set_enabled(self, ids: Collection[ModId], enabled: bool) -> None:
        """Flip the ENABLED flag of ``ids``; emits ``dataChanged`` for those rows only."""
        roles = [Role.ENABLED, Qt.ItemDataRole.CheckStateRole, Role.VM]
        for row in contiguous_runs(r for m in ids if (r := self._row_of.get(m)) is not None):
            for i in range(row[0], row[1] + 1):
                self._rows[i] = replace(self._rows[i], enabled=enabled)
            self.dataChanged.emit(self.index(row[0]), self.index(row[1]), roles)

    def set_enabled_ids(self, enabled_ids: Collection[ModId]) -> None:
        """Make the ENABLED flag of every row match ``enabled_ids`` (one dataChanged per run)."""
        wanted = set(enabled_ids)
        self.set_enabled(
            [vm.mod_id for vm in self._rows if vm.mod_id in wanted and not vm.enabled], True
        )
        self.set_enabled(
            [vm.mod_id for vm in self._rows if vm.mod_id not in wanted and vm.enabled], False
        )

    # ---- drag & drop ------------------------------------------------------------
    @override
    def mimeTypes(self) -> list[str]:
        return [MIME_MOD_IDS]

    @override
    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    @override
    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    @override
    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:
        rows = sorted({i.row() for i in indexes if i.isValid()})
        return encode_payload(DragOrigin.AVAILABLE, [self._rows[r].mod_id for r in rows])

    @override
    def canDropMimeData(
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: AnyIndex
    ) -> bool:
        payload = decode_payload(data)
        return payload is not None and payload.origin is DragOrigin.LOAD_ORDER

    @override
    def dropMimeData(
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: AnyIndex
    ) -> bool:
        payload = decode_payload(data)
        if (
            payload is None
            or payload.origin is not DragOrigin.LOAD_ORDER
            or not (action & _DROP_ACTIONS)
        ):
            return False
        self.disableRequested.emit(list(payload.ids))
        return True
