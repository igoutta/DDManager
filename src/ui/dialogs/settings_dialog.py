"""The settings dialog: priority direction, language, density, backup retention, plugin trust.

Every control applies at once (the same presenter calls the menu actions make); the dialog only
closes.  Backup retention and plugin trust take effect the next time DD Manager starts.
"""

from typing import TYPE_CHECKING, Final, override

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.load_order import PriorityDirection
from src.ui.dialogs.common import button_row, finish, make_button, set_button_text
from src.ui.dialogs.live_dialog import LiveDialog
from src.ui.dialogs.trust_section import TrustSection
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role
from src.ui.theme.tokens import DENSITY
from src.ui.widgets.actions import IconSet

if TYPE_CHECKING:
    from src.ui.presenters.settings import SettingsPresenter

DOCS_URL: Final = "https://github.com/igoutta/DDManager/blob/main/docs/load-order-semantics.md"
_KEEP_LAST_MAX: Final = 999
_KEEP_DAYS_MAX: Final = 3650
_MIN_KEEP_MAX: Final = 99


def density_slug(mode: str) -> str:
    return mode.lower().replace(" ", "_")


def set_quietly(widget: QCheckBox | QRadioButton | QSpinBox, value: bool | int) -> None:
    """Set a control's value without emitting its change signal."""
    widget.blockSignals(True)  # noqa: FBT003
    if isinstance(widget, QSpinBox):
        widget.setValue(int(value))
    else:
        widget.setChecked(bool(value))
    widget.blockSignals(False)  # noqa: FBT003


class SettingsDialog(LiveDialog):
    def __init__(
        self,
        presenter: SettingsPresenter,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(translator, parent)
        self._p = presenter
        self._icons = icons
        self.setObjectName("dialog_settings")
        self.tabs = QTabWidget(self)
        self.general_tab = self._build_general()
        self.backups_tab = self._build_backups()
        self.plugins_tab = self._build_plugins()
        for tab in (self.general_tab, self.backups_tab, self.plugins_tab):
            self.tabs.addTab(tab, "")
        self.close_button = make_button(self, "close", "close.tip", role="primary")
        self.close_button.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(button_row(self.close_button))
        self._load_values()
        self.retranslate_ui()
        finish(self, self.windowTitle(), 760, 560, translator.tr)

    # ------------------------------------------------------------------ construction

    def _build_general(self) -> QWidget:
        page = QWidget(self)
        self.priority_box = QGroupBox(page)
        self.first_radio = QRadioButton(self.priority_box)
        self.last_radio = QRadioButton(self.priority_box)
        group = QButtonGroup(self)
        group.addButton(self.first_radio)
        group.addButton(self.last_radio)
        self.verified_box = QCheckBox(self.priority_box)
        self.docs_button = make_button(self.priority_box, "docs", "docs.tip")
        inner = QVBoxLayout(self.priority_box)
        for widget in (self.first_radio, self.last_radio, self.verified_box):
            inner.addWidget(widget)
        inner.addLayout(button_row(self.docs_button, stretch_first=False))
        self.interface_box = QGroupBox(page)
        self.language_label = QLabel(self.interface_box)
        self.language_combo = QComboBox(self.interface_box)
        self.density_label = QLabel(self.interface_box)
        self.density_combo = QComboBox(self.interface_box)
        form = QFormLayout(self.interface_box)
        form.addRow(self.language_label, self.language_combo)
        form.addRow(self.density_label, self.density_combo)
        layout = QVBoxLayout(page)
        layout.addWidget(self.priority_box)
        layout.addWidget(self.interface_box)
        layout.addStretch(1)
        self.first_radio.toggled.connect(self._on_priority)
        self.verified_box.toggled.connect(self._on_priority)
        self.docs_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOCS_URL)))
        self.language_combo.activated.connect(self._on_language_picked)
        self.density_combo.activated.connect(self._on_density_picked)
        return page

    def _build_backups(self) -> QWidget:
        page = QWidget(self)
        self.backups_box = QGroupBox(page)
        self.keep_last = self._spin(1, _KEEP_LAST_MAX)
        self.keep_days = self._spin(0, _KEEP_DAYS_MAX)
        self.min_keep = self._spin(0, _MIN_KEEP_MAX)
        self.keep_last_label = QLabel(self.backups_box)
        self.keep_days_label = QLabel(self.backups_box)
        self.min_keep_label = QLabel(self.backups_box)
        self.backups_note = QLabel(page)
        self.backups_note.setWordWrap(True)
        set_role(self.backups_note, "muted")
        form = QFormLayout(self.backups_box)
        form.addRow(self.keep_last_label, self.keep_last)
        form.addRow(self.keep_days_label, self.keep_days)
        form.addRow(self.min_keep_label, self.min_keep)
        layout = QVBoxLayout(page)
        layout.addWidget(self.backups_box)
        layout.addWidget(self.backups_note)
        layout.addStretch(1)
        return page

    def _spin(self, low: int, high: int) -> QSpinBox:
        spin = QSpinBox(self.backups_box)
        spin.setRange(low, high)
        spin.valueChanged.connect(self._on_retention)
        return spin

    def _build_plugins(self) -> QWidget:
        page = QWidget(self)
        trust = self._p.trust
        self.plugins_section = TrustSection(trust, "plugins", self._translator, page)
        self.rules_section = TrustSection(trust, "rules", self._translator, page)
        self.security_note = QLabel(page)
        self.security_note.setWordWrap(True)
        set_role(self.security_note, "warning")
        layout = QVBoxLayout(page)
        layout.addWidget(self.plugins_section, 1)
        layout.addWidget(self.rules_section, 1)
        layout.addWidget(self.security_note)
        return page

    # ------------------------------------------------------------------ values

    def _load_values(self) -> None:
        priority = self._p.priority()
        first = priority.direction is PriorityDirection.FIRST_WINS
        set_quietly(self.first_radio, first)
        set_quietly(self.last_radio, not first)
        set_quietly(self.verified_box, priority.verified)
        policy = self._p.retention()
        set_quietly(self.keep_last, policy.keep_last)
        set_quietly(self.keep_days, policy.keep_days)
        set_quietly(self.min_keep, policy.min_keep)

    def _on_priority(self, *_args: object) -> None:
        direction = (
            PriorityDirection.FIRST_WINS
            if self.first_radio.isChecked()
            else PriorityDirection.LAST_WINS
        )
        self._p.set_priority(direction, verified=self.verified_box.isChecked())

    def _on_language_picked(self, index: int) -> None:
        code = self.language_combo.itemData(index)
        if code:
            self._p.set_language(str(code))

    def _on_density_picked(self, index: int) -> None:
        mode = self.density_combo.itemData(index)
        if mode:
            self._p.set_density(str(mode))

    def _on_retention(self, *_args: object) -> None:
        self._p.set_retention(
            keep_last=self.keep_last.value(),
            keep_days=self.keep_days.value(),
            min_keep=self.min_keep.value(),
        )

    # ------------------------------------------------------------------ language

    def _fill_combos(self) -> None:
        tr = self._translator.tr
        self.language_combo.blockSignals(True)  # noqa: FBT003
        self.language_combo.clear()
        for code in self._p.languages():
            self.language_combo.addItem(tr(f"ui.action.lang_{code}"), code)
        current = self.language_combo.findData(self._p.language())
        self.language_combo.setCurrentIndex(max(0, current))
        self.language_combo.blockSignals(False)  # noqa: FBT003
        self.density_combo.blockSignals(True)  # noqa: FBT003
        self.density_combo.clear()
        for mode in DENSITY:
            self.density_combo.addItem(tr(f"ui.action.density_{density_slug(mode)}"), mode)
        self.density_combo.setCurrentIndex(max(0, self.density_combo.findData(self._p.density())))
        self.density_combo.blockSignals(False)  # noqa: FBT003

    @override
    def retranslate_ui(self) -> None:
        tr = self._translator.tr
        self.setWindowTitle(tr("ui.settings.title"))
        for index, key in enumerate(("general", "backups", "plugins")):
            self.tabs.setTabText(index, tr(f"ui.settings.tab.{key}"))
            self.tabs.setTabToolTip(index, tr(f"ui.settings.tab.{key}.tip"))
        self.priority_box.setTitle(tr("ui.settings.priority"))
        for button, key in (
            (self.first_radio, "prio_first"),
            (self.last_radio, "prio_last"),
            (self.verified_box, "prio_verified"),
        ):
            button.setText(tr(f"ui.action.{key}"))
            button.setToolTip(tr(f"ui.action.{key}.tip"))
        set_button_text(self.docs_button, tr("ui.settings.docs"), tr("ui.settings.docs.tip"))
        self.interface_box.setTitle(tr("ui.settings.interface"))
        self.language_label.setText(tr("language"))
        self.density_label.setText(tr("ui.menu.density"))
        self.language_combo.setToolTip(tr("ui.menu.language.tip"))
        self.density_combo.setToolTip(tr("ui.menu.density.tip"))
        self._fill_combos()
        self._retranslate_backups()
        self.security_note.setText(tr("ui.trust.security_note"))
        self.plugins_section.retranslate_ui()
        self.rules_section.retranslate_ui()
        set_button_text(self.close_button, tr("ui.dialog.close"), tr("ui.dialog.close.tip"))

    def _retranslate_backups(self) -> None:
        tr = self._translator.tr
        self.backups_box.setTitle(tr("ui.settings.backups"))
        for label, spin, key in (
            (self.keep_last_label, self.keep_last, "keep_last"),
            (self.keep_days_label, self.keep_days, "keep_days"),
            (self.min_keep_label, self.min_keep, "min_keep"),
        ):
            label.setText(tr(f"ui.settings.{key}"))
            spin.setToolTip(tr(f"ui.settings.{key}.tip"))
        self.backups_note.setText(tr("ui.settings.restart_note"))
