"""The right pane: everything known about the selected mod (read-only, from view models).

A stacked widget holds three pages: the placeholder, the multi-selection summary and the
single-mod sheet.  The sheet keeps one widget per field and only updates their texts, so
selecting mod after mod never leaves anything behind; the two variable parts (tags, findings)
are rebuilt with :func:`clear_layout`, which hides what it removes before Qt deletes it.
"""

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QScrollArea,
    QStackedWidget,
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
from src.ui.widgets.details_widgets import ThumbLabel, clear_layout, make_label, tag_chip
from src.ui.widgets.elided_label import ElidedLabel
from src.ui.widgets.tier_chips import FlowLayout

type Tr = Callable[..., str]

THUMB_PX: Final = 256
MIN_WIDTH_PX: Final = 220
_SEVERITY_TONE: Final = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "info",
}
_BUTTONS: Final = (
    ("copy", "ui.details.copy", "ui.details.copy.tip", "check"),
    ("folder", "ui.details.open_folder", "ui.details.open_folder.tip", "folder"),
    ("page", "ui.details.open_page", "ui.details.open_page.tip", "link"),
)


class DetailsPane(QWidget):
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
        self.setMinimumWidth(MIN_WIDTH_PX)
        self._build()
        controller.thumbnails.ready.connect(self._on_thumb)
        self.show_details(None)

    # ------------------------------------------------------------------ construction

    def _build(self) -> None:
        self.stack = QStackedWidget(self)
        self.placeholder = make_label("", "muted")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.multi_page = QWidget()
        multi = QVBoxLayout(self.multi_page)
        multi.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.multi_title = make_label("", "heading")
        self.multi_breakdown = make_label("", "muted")
        multi.addWidget(self.multi_title)
        multi.addWidget(self.multi_breakdown)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sheet = QWidget()
        self._build_sheet(self.sheet)
        self.scroll_area.setWidget(self.sheet)
        for page in (self.placeholder, self.multi_page, self.scroll_area):
            self.stack.addWidget(page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

    def _build_sheet(self, sheet: QWidget) -> None:
        layout = QVBoxLayout(sheet)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.thumb = ThumbLabel(THUMB_PX)
        self.title = make_label("", "heading")
        self.rank = make_label("", "muted")
        self.identity = ElidedLabel("")
        set_role(self.identity, "mono")
        self.folder = make_label("")
        self.source = make_label("")
        self.version = make_label("")
        self.tier = make_label("")
        self.buttons: dict[str, QToolButton] = {}
        actions = QWidget()
        flow = FlowLayout(actions, spacing=4)
        for name, _text, _tip, icon in _BUTTONS:
            button = QToolButton()
            button.setObjectName(f"details_{name}")
            button.setIcon(self._icons.get(icon))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            flow.addWidget(button)
            self.buttons[name] = button
        self.buttons["copy"].clicked.connect(self._copy)
        self.buttons["folder"].clicked.connect(self._open_folder)
        self.buttons["page"].clicked.connect(self._open_page)
        self.tags = QWidget()
        self._tags_flow = FlowLayout(self.tags, spacing=4)
        self.findings_title = make_label("", "heading")
        self.findings = QWidget()
        self._findings_box = QVBoxLayout(self.findings)
        self._findings_box.setContentsMargins(0, 0, 0, 0)
        for widget in (
            self.thumb,
            self.title,
            self.rank,
            self.identity,
            self.folder,
            self.source,
            self.version,
            self.tier,
            actions,
            self.tags,
            self.findings_title,
            self.findings,
        ):
            layout.addWidget(widget)  # fmt: skip

    # ------------------------------------------------------------------ public

    def show_details(self, vm: DetailsVM | MultiDetailsVM | None) -> None:
        self._vm = vm
        if isinstance(vm, DetailsVM):
            self._render_single(vm)
            self.stack.setCurrentWidget(self.scroll_area)
        elif isinstance(vm, MultiDetailsVM):
            self._render_multi(vm)
            self.stack.setCurrentWidget(self.multi_page)
        else:
            self.stack.setCurrentWidget(self.placeholder)

    def retranslate_ui(self) -> None:
        tr = self._tr.tr
        self.placeholder.setText(tr("ui.details.empty"))
        for name, text_key, tip_key, _icon in _BUTTONS:
            self.buttons[name].setText(tr(text_key))
            self.buttons[name].setToolTip(tr(tip_key))
        self.findings_title.setText(tr("ui.details.findings"))
        self.show_details(self._vm)

    # ------------------------------------------------------------------ rendering

    def _render_multi(self, vm: MultiDetailsVM) -> None:
        tr = self._tr.tr
        self.multi_title.setText(tr("ui.details.multi", count=vm.count))
        self.multi_breakdown.setText("\n".join(f"{tier}: {n}" for tier, n in vm.tier_breakdown))

    def _render_single(self, vm: DetailsVM) -> None:
        tr = self._tr.tr
        self._set_thumb(vm)
        self.title.setText(vm.title)
        self.rank.setText(vm.rank_text)
        self.identity.setText(vm.identity_text)
        self.identity.setToolTip(tr("ui.details.identity.tip", identity=vm.identity_text))
        self.folder.setText(tr("ui.details.folder", folder=vm.folder))
        self.source.setText(tr("ui.details.source", source=vm.source_label))
        self.version.setText(tr("ui.details.version", version=vm.version_text))
        self.version.setVisible(bool(vm.version_text))
        self.tier.setText(tier_text(tr, vm.tier_label, vm.category_label))
        self.buttons["page"].setVisible(bool(vm.workshop_url))
        self._render_tags(vm.tags)
        self._render_findings(vm.findings)

    def _set_thumb(self, vm: DetailsVM) -> None:
        pixmap = self._c.thumbnails.pixmap(vm.mod_id, vm.icon_path, vm.icon_stamp, THUMB_PX)
        if isinstance(pixmap, QPixmap):
            self.thumb.set_source(pixmap)
        else:
            self.thumb.set_source(None, self._tr.tr("ui.details.no_preview"))

    def _on_thumb(self, mod_id: str) -> None:
        if isinstance(self._vm, DetailsVM) and self._vm.mod_id == ModId(mod_id):
            self._set_thumb(self._vm)

    def _render_tags(self, tags: tuple[str, ...]) -> None:
        clear_layout(self._tags_flow)
        for tag in tags:
            self._tags_flow.addWidget(tag_chip(tag, self._tr.tr("ui.details.tag.tip", tag=tag)))
        self.tags.setVisible(bool(tags))
        self.tags.updateGeometry()

    def _render_findings(self, findings: tuple[FindingVM, ...]) -> None:
        tr = self._tr.tr
        clear_layout(self._findings_box)
        if not findings:
            self._findings_box.addWidget(make_label(tr("ui.lo.no_findings"), "muted"))
        for finding in findings:
            tone = _SEVERITY_TONE.get(finding.severity, "info")
            button = QToolButton()
            button.setAutoRaise(True)
            button.setIcon(self._icons.get(tone, tone))
            button.setText(finding.message)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setToolTip(tr("ui.details.finding.tip", rule=finding.rule_id))
            button.clicked.connect(lambda _c=False, key=finding.key: self._c.focus_finding(key))
            self._findings_box.addWidget(button)

    # ------------------------------------------------------------------ button slots

    def _single(self) -> DetailsVM | None:
        return self._vm if isinstance(self._vm, DetailsVM) else None

    def _copy(self) -> None:
        vm = self._single()
        if vm is not None:
            QGuiApplication.clipboard().setText(vm.identity_text)
            self._c.post("ui.notice.copied")

    def _open_folder(self) -> None:
        vm = self._single()
        if vm is not None:
            self._c.open_folder(vm.mod_id)

    def _open_page(self) -> None:
        vm = self._single()
        if vm is not None:
            self._c.open_workshop_page(vm.mod_id)


def tier_text(tr: Tr, tier: str, category: str) -> str:
    """``Tier: X (Y)``, or just ``Tier: X`` when the category label says the same thing."""
    if not category or category == tier:
        return tr("ui.details.tier_only", tier=tier)
    return tr("ui.details.tier", tier=tier, category=category)
