"""The profile manager: save slots, load-order profiles and backups."""

from typing import override

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from src.ui.dialogs.common import button_row, finish, make_button, set_button_text
from src.ui.dialogs.live_dialog import LiveDialog
from src.ui.dialogs.profile_tabs import BackupsTab, ProfilesTab, SlotsTab
from src.ui.i18n import Translator
from src.ui.presenters.dto import ProfilesPort
from src.ui.widgets.actions import IconSet

_TAB_KEYS = ("slots", "profiles", "backups")


class ProfileManagerDialog(LiveDialog):
    def __init__(
        self,
        port: ProfilesPort,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(translator, parent)
        self.setObjectName("dialog_profiles")
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self.slots_tab = SlotsTab(port, translator, self)
        self.profiles_tab = ProfilesTab(port, translator, self)
        self.backups_tab = BackupsTab(port, translator, self)
        self.tabs.addTab(self.slots_tab, icons.get("folder"), "")
        self.tabs.addTab(self.profiles_tab, icons.get("profiles"), "")
        self.tabs.addTab(self.backups_tab, icons.get("backup"), "")
        self.tabs.currentChanged.connect(self._refresh_current)
        self.close_button = make_button(self, "", "")
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(button_row(self.close_button))
        self.retranslate_ui()
        finish(self, self.windowTitle(), 820, 520, translator.tr)

    @override
    def retranslate_ui(self) -> None:
        """Title, tab names and the Close button, then every tab (labels and rendered data)."""
        tr = self._translator.tr
        self.setWindowTitle(tr("ui.manager.title"))
        for index, key in enumerate(_TAB_KEYS):
            self.tabs.setTabText(index, tr(f"ui.manager.{key}"))
        set_button_text(self.close_button, tr("ui.dialog.close"), tr("ui.dialog.close.tip"))
        for tab in (self.slots_tab, self.profiles_tab, self.backups_tab):
            tab.retranslate_ui()

    def _refresh_current(self, index: int) -> None:
        tab = self.tabs.widget(index)
        refresh = getattr(tab, "refresh", None)
        if callable(refresh):
            refresh()
