"""The "Load Order Health" dock: findings tree, severity filters, re-run, copy report, fixes."""

from typing import Final

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QHBoxLayout,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from src.core.findings import Severity
from src.ui.controller import MainController
from src.ui.i18n import Translator
from src.ui.models.findings_model import FindingsModel
from src.ui.viewmodels import FindingVM
from src.ui.widgets.actions import IconSet

_FILTERS: Final = (
    (Severity.ERROR, "error", "ui.health.severity.error"),
    (Severity.WARNING, "warning", "ui.health.severity.warning"),
    (Severity.INFO, "info", "ui.health.severity.info"),
)


def report_text(findings: tuple[FindingVM, ...], translator: Translator) -> str:
    """A plain-text report suitable for pasting into a bug report."""
    names = {s: translator.tr(key) for s, _tone, key in _FILTERS}
    lines: list[str] = []
    for finding in findings:
        level = names.get(Severity(max(Severity.INFO, min(finding.severity, Severity.ERROR))), "")
        lines.append(f"[{level}] {finding.rule_id}: {finding.message}")
        lines.extend(f"    {detail}" for detail in finding.details)
    return "\n".join(lines)


class HealthDock(QDockWidget):
    def __init__(
        self,
        controller: MainController,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dock_health")
        self._c = controller
        self._tr = translator
        self._model: FindingsModel = controller.findings_model
        self._filters: dict[Severity, QToolButton] = {}
        self._build(icons)
        self.retranslate_ui()

    def _build(self, icons: IconSet) -> None:
        body = QWidget(self)
        layout = QVBoxLayout(body)
        bar = QHBoxLayout()
        for severity, tone, _key in _FILTERS:
            button = QToolButton(body)
            button.setCheckable(True)
            button.setChecked(True)
            button.setIcon(icons.get(tone, tone))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.toggled.connect(self._apply_filter)
            self._filters[severity] = button
            bar.addWidget(button)
        bar.addStretch(1)
        self.fix_button = QToolButton(body)
        self.fix_button.setIcon(icons.get("check"))
        self.fix_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.rerun_button = QToolButton(body)
        self.rerun_button.setIcon(icons.get("rescan"))
        self.rerun_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.copy_button = QToolButton(body)
        self.copy_button.setIcon(icons.get("patch"))
        self.copy_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for button in (self.fix_button, self.rerun_button, self.copy_button):
            bar.addWidget(button)
        self.tree = QTreeView(body)
        self.tree.setModel(self._model)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addLayout(bar)
        layout.addWidget(self.tree, 1)
        self.setWidget(body)
        self.tree.activated.connect(self._activate)
        selection = self.tree.selectionModel()
        if selection is not None:
            selection.currentChanged.connect(self._on_current)
        self.rerun_button.clicked.connect(self._c.validate)
        self.copy_button.clicked.connect(self._copy)
        self.fix_button.clicked.connect(self._fix)
        self._model.modelReset.connect(self._on_reset)

    def _current(self) -> FindingVM | None:
        return self._model.finding_at(self.tree.currentIndex())

    def _apply_filter(self) -> None:
        self._model.set_severity_filter(
            s for s, button in self._filters.items() if button.isChecked()
        )

    def _on_reset(self) -> None:
        self.tree.expandAll()
        for column in range(self._model.columnCount()):
            self.tree.resizeColumnToContents(column)
        self._refresh_fix()
        self._update_titles()

    def _on_current(self, *_args: object) -> None:
        self._refresh_fix()

    def _refresh_fix(self) -> None:
        finding = self._current()
        label = finding.fix_label if finding is not None else None
        self.fix_button.setEnabled(label is not None)
        self.fix_button.setText(label or self._tr.tr("ui.health.fix"))

    def _activate(self, index: QModelIndex) -> None:
        finding = self._model.finding_at(index)
        if finding is not None:
            self._c.focus_finding(finding.key)

    def _fix(self) -> None:
        finding = self._current()
        if finding is not None and finding.fix_label is not None:
            self._c.apply_fix(finding.key)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(report_text(self._c.finding_vms(), self._tr))
        self._c.post("ui.notice.report_copied")

    def _update_titles(self) -> None:
        errors, warnings, infos = self._model.counts()
        tally = {Severity.ERROR: errors, Severity.WARNING: warnings, Severity.INFO: infos}
        for severity, _tone, key in _FILTERS:
            self._filters[severity].setText(f"{self._tr.tr(key)} ({tally[severity]})")

    def retranslate_ui(self) -> None:
        tr = self._tr.tr
        self.setWindowTitle(tr("ui.health.title"))
        self.toggleViewAction().setToolTip(tr("ui.action.health.tip"))
        self.rerun_button.setText(tr("ui.health.rerun"))
        self.rerun_button.setToolTip(tr("ui.health.rerun.tip"))
        self.copy_button.setText(tr("ui.health.copy"))
        self.copy_button.setToolTip(tr("ui.health.copy.tip"))
        self.fix_button.setToolTip(tr("ui.health.fix.tip"))
        for severity, _tone, key in _FILTERS:
            self._filters[severity].setToolTip(tr("ui.health.filter.tip", severity=tr(key)))
        self._refresh_fix()
        self._update_titles()
