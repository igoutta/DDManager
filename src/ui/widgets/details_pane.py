"""The right pane: everything known about the selected mod (read-only, from view models)."""

from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.findings import Severity
from src.core.ids import ModId
from src.ui.controller import MainController
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role
from src.ui.viewmodels import DetailsVM, FindingVM, MultiDetailsVM
from src.ui.widgets.actions import IconSet
from src.ui.widgets.elided_label import ElidedLabel
from src.ui.widgets.tier_chips import FlowLayout

THUMB_PX: Final = 256
_SEVERITY_TONE: Final = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "info",
}


def _clear(layout: QLayout) -> None:
    while (item := layout.takeAt(0)) is not None:
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def _label(text: str, role: str | None = None, *, selectable: bool = True) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if role:
        set_role(label, role)
    return label


class DetailsPane(QScrollArea):
    def __init__(
        self,
        controller: MainController,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._c = controller
        self._tr = translator
        self._icons = icons
        self._vm: DetailsVM | MultiDetailsVM | None = None
        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._body)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        controller.thumbnails.ready.connect(self._on_thumb)
        self.show_details(None)

    # ------------------------------------------------------------------ public

    def show_details(self, vm: DetailsVM | MultiDetailsVM | None) -> None:
        self._vm = vm
        _clear(self._layout)
        if isinstance(vm, DetailsVM):
            self._render_single(vm)
        elif isinstance(vm, MultiDetailsVM):
            self._render_multi(vm)
        else:
            self._layout.addWidget(_label(self._tr.tr("ui.details.empty"), "muted"))

    def retranslate_ui(self) -> None:
        self.show_details(self._vm)

    # ------------------------------------------------------------------ rendering

    def _render_multi(self, vm: MultiDetailsVM) -> None:
        tr = self._tr.tr
        self._layout.addWidget(_label(tr("ui.details.multi", count=vm.count), "heading"))
        for tier, count in vm.tier_breakdown:
            self._layout.addWidget(_label(f"{tier}: {count}", "muted"))

    def _render_single(self, vm: DetailsVM) -> None:
        tr = self._tr.tr
        self._thumb = QLabel()
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setMinimumHeight(THUMB_PX // 2)
        self._set_thumb(vm)
        self._layout.addWidget(self._thumb)
        self._layout.addWidget(_label(vm.title, "heading"))
        self._layout.addWidget(_label(vm.rank_text, "muted"))
        self._layout.addLayout(self._identity_row(vm))
        self._layout.addWidget(_label(tr("ui.details.folder", folder=vm.folder)))
        self._layout.addLayout(self._source_row(vm))
        if vm.version_text:
            self._layout.addWidget(_label(tr("ui.details.version", version=vm.version_text)))
        self._layout.addWidget(
            _label(tr("ui.details.tier", tier=vm.tier_label, category=vm.category_label))
        )
        self._layout.addWidget(self._tags(vm.tags))
        self._render_findings(vm.findings)

    def _set_thumb(self, vm: DetailsVM) -> None:
        pixmap = self._c.thumbnails.pixmap(vm.mod_id, vm.icon_path, vm.icon_stamp, THUMB_PX)
        if isinstance(pixmap, QPixmap):
            self._thumb.setPixmap(pixmap)
        else:
            self._thumb.setText(self._tr.tr("ui.details.no_preview"))
            set_role(self._thumb, "muted")

    def _on_thumb(self, mod_id: str) -> None:
        if isinstance(self._vm, DetailsVM) and self._vm.mod_id == ModId(mod_id):
            self._set_thumb(self._vm)

    def _identity_row(self, vm: DetailsVM) -> QHBoxLayout:
        row = QHBoxLayout()
        identity = ElidedLabel(vm.identity_text)
        identity.setToolTip(self._tr.tr("ui.details.identity.tip", identity=vm.identity_text))
        set_role(identity, "mono")
        copy = self._button("ui.details.copy", "ui.details.copy.tip", "check")
        copy.clicked.connect(lambda: self._copy(vm.identity_text))
        row.addWidget(identity, 1)
        row.addWidget(copy)
        return row

    def _source_row(self, vm: DetailsVM) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(_label(self._tr.tr("ui.details.source", source=vm.source_label)), 1)
        folder = self._button("ui.details.open_folder", "ui.details.open_folder.tip", "folder")
        folder.clicked.connect(lambda: self._c.open_folder(vm.mod_id))
        row.addWidget(folder)
        if vm.workshop_url:
            page = self._button("ui.details.open_page", "ui.details.open_page.tip", "link")
            page.clicked.connect(lambda: self._c.open_workshop_page(vm.mod_id))
            row.addWidget(page)
        return row

    def _tags(self, tags: tuple[str, ...]) -> QWidget:
        holder = QWidget()
        flow = FlowLayout(holder, spacing=4)
        for tag in tags:
            chip = QLabel(tag)
            chip.setToolTip(self._tr.tr("ui.details.tag.tip", tag=tag))
            chip.setStyleSheet(
                "padding: 1px 6px; border: 1px solid palette(mid); border-radius: 8px;"
            )
            flow.addWidget(chip)
        return holder

    def _render_findings(self, findings: tuple[FindingVM, ...]) -> None:
        tr = self._tr.tr
        self._layout.addWidget(_label(tr("ui.details.findings"), "heading"))
        if not findings:
            self._layout.addWidget(_label(tr("ui.lo.no_findings"), "muted"))
        for finding in findings:
            tone = _SEVERITY_TONE.get(finding.severity, "info")
            button = QToolButton()
            button.setAutoRaise(True)
            button.setIcon(self._icons.get(tone, tone))
            button.setText(finding.message)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setToolTip(tr("ui.details.finding.tip", rule=finding.rule_id))
            button.clicked.connect(lambda _c=False, key=finding.key: self._c.focus_finding(key))
            self._layout.addWidget(button)

    def _button(self, text_key: str, tip_key: str, icon: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(self._icons.get(icon))
        button.setText(self._tr.tr(text_key))
        button.setToolTip(self._tr.tr(tip_key))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        return button

    def _copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._c.post("ui.notice.copied")
