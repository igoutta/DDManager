"""The Health tree: severity groups containing findings."""

from collections.abc import Iterable
from enum import IntEnum
from typing import Any, Final, override

from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from src.core.findings import Severity
from src.ui.i18n import Translator
from src.ui.models.roles import Role
from src.ui.viewmodels import FindingVM

type AnyIndex = QModelIndex | QPersistentModelIndex
_ROOT: Final = QModelIndex()
_GROUPS: Final = (Severity.ERROR, Severity.WARNING, Severity.INFO)
_GROUP_KEYS: Final = {
    Severity.ERROR: "ui.health.group.errors",
    Severity.WARNING: "ui.health.group.warnings",
    Severity.INFO: "ui.health.group.info",
}
_SEVERITY_KEYS: Final = {
    Severity.ERROR: "ui.health.severity.error",
    Severity.WARNING: "ui.health.severity.warning",
    Severity.INFO: "ui.health.severity.info",
}


class FCol(IntEnum):
    SEVERITY = 0
    RULE = 1
    MESSAGE = 2
    MODS = 3


_HEADER_KEYS: Final = {
    FCol.SEVERITY: "ui.health.col.severity",
    FCol.RULE: "ui.health.col.rule",
    FCol.MESSAGE: "ui.health.col.message",
    FCol.MODS: "ui.health.col.mods",
}


def group_of(severity: int) -> Severity:
    """The group a severity value belongs to (>= ERROR, >= WARNING, else INFO)."""
    if severity >= Severity.ERROR:
        return Severity.ERROR
    return Severity.WARNING if severity >= Severity.WARNING else Severity.INFO


class FindingsModel(QAbstractItemModel):
    """Two levels: non-empty severity groups, then their findings.

    Internal id ``0`` marks a group row; a finding row stores ``group_position + 1``.
    """

    def __init__(self, tr: Translator, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tr = tr
        self._all: tuple[FindingVM, ...] = ()
        self._shown: frozenset[Severity] = frozenset(_GROUPS)
        self._groups: list[tuple[Severity, list[FindingVM]]] = []
        tr.languageChanged.connect(self._on_language_changed)

    # ---- mutation ---------------------------------------------------------------
    def set_findings(self, findings: Iterable[FindingVM]) -> None:
        self.beginResetModel()
        self._all = tuple(findings)
        self._rebuild()
        self.endResetModel()

    def set_severity_filter(self, shown: Iterable[Severity]) -> None:
        """Show only the given severity groups (all of them by default)."""
        self.beginResetModel()
        self._shown = frozenset(shown)
        self._rebuild()
        self.endResetModel()

    def _rebuild(self) -> None:
        self._groups = []
        for severity in _GROUPS:
            if severity not in self._shown:
                continue
            members = [f for f in self._all if group_of(f.severity) == severity]
            if members:
                self._groups.append((severity, members))

    # ---- read API -------------------------------------------------------------------
    def counts(self) -> tuple[int, int, int]:
        """(errors, warnings, infos) over ALL findings, ignoring the filter."""
        tally = dict.fromkeys(_GROUPS, 0)
        for finding in self._all:
            tally[group_of(finding.severity)] += 1
        return (tally[Severity.ERROR], tally[Severity.WARNING], tally[Severity.INFO])

    def finding_at(self, index: AnyIndex) -> FindingVM | None:
        if not index.isValid() or index.internalId() == 0:
            return None
        return self._groups[int(index.internalId()) - 1][1][index.row()]

    def index_for_key(self, key: str) -> QModelIndex:
        for g, (_sev, members) in enumerate(self._groups):
            for row, finding in enumerate(members):
                if finding.key == key:
                    return self.index(row, 0, self.index(g, 0))
        return QModelIndex()

    @override
    def rowCount(self, parent: AnyIndex = _ROOT) -> int:
        if not parent.isValid():
            return len(self._groups)
        if parent.internalId() != 0 or parent.column() != 0:
            return 0
        return len(self._groups[parent.row()][1])

    @override
    def columnCount(self, parent: AnyIndex = _ROOT) -> int:
        return len(FCol)

    @override
    def index(self, row: int, column: int, parent: AnyIndex = _ROOT) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, 0)
        return self.createIndex(row, column, parent.row() + 1)

    @override
    def parent(self, child: AnyIndex | None = None) -> Any:
        if child is None:  # QObject.parent()
            return super().parent()
        if not child.isValid() or child.internalId() == 0:
            return QModelIndex()
        return self.createIndex(int(child.internalId()) - 1, 0, 0)

    @override
    def flags(self, index: AnyIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.internalId() != 0:
            flags |= Qt.ItemFlag.ItemNeverHasChildren
        return flags

    @override
    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._tr.tr(_HEADER_KEYS[FCol(section)]) if 0 <= section < len(FCol) else None

    @override
    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not self.checkIndex(index, QAbstractItemModel.CheckIndexOption.IndexIsValid):
            return None
        finding = self.finding_at(index)
        if finding is None:
            return self._group_data(index, role)
        return self._finding_data(finding, FCol(index.column()), role)

    def _group_data(self, index: AnyIndex, role: int) -> Any:
        severity, members = self._groups[index.row()]
        if role == Role.WORST_SEVERITY:
            return int(severity)
        if role == Qt.ItemDataRole.DisplayRole and index.column() == FCol.SEVERITY:
            return self._tr.tr(_GROUP_KEYS[severity], count=len(members))
        return None

    def _finding_data(self, finding: FindingVM, col: FCol, role: int) -> Any:
        if role == Role.VM:
            return finding
        if role == Role.WORST_SEVERITY:
            return int(finding.severity)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self._finding_text(finding, col, tooltip=role == Qt.ItemDataRole.ToolTipRole)
        return None

    def _finding_text(self, finding: FindingVM, col: FCol, *, tooltip: bool) -> str:
        if tooltip:
            return "\n".join((finding.message, *finding.details))
        texts = {
            FCol.SEVERITY: lambda: self._tr.tr(_SEVERITY_KEYS[group_of(finding.severity)]),
            FCol.RULE: lambda: finding.rule_id,
            FCol.MESSAGE: lambda: finding.message,
            FCol.MODS: lambda: ", ".join(finding.mod_ids),
        }
        return texts[col]()

    def _on_language_changed(self, _code: str) -> None:
        if not self._groups:
            return
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(FCol) - 1)
        last = self.index(len(self._groups) - 1, len(FCol) - 1)
        self.dataChanged.emit(self.index(0, 0), last, [Qt.ItemDataRole.DisplayRole])
