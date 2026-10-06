"""The profile manager: save slots, load-order profiles and backups."""

from PySide6.QtWidgets import QDialog, QTabWidget, QVBoxLayout, QWidget

from src.ui.dialogs.common import button_row, finish, make_button
from src.ui.dialogs.profile_tabs import BackupsTab, ProfilesTab, SlotsTab
from src.ui.i18n import Translator
from src.ui.presenters.dto import ProfilesPort
from src.ui.widgets.actions import IconSet


class ProfileManagerDialog(QDialog):
    def __init__(
        self,
        port: ProfilesPort,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        tr = translator.tr
        self.setObjectName("dialog_profiles")
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self.slots_tab = SlotsTab(port, translator, self)
        self.profiles_tab = ProfilesTab(port, translator, self)
        self.backups_tab = BackupsTab(port, translator, self)
        self.tabs.addTab(self.slots_tab, icons.get("folder"), tr("ui.manager.slots"))
        self.tabs.addTab(self.profiles_tab, icons.get("profiles"), tr("ui.manager.profiles"))
        self.tabs.addTab(self.backups_tab, icons.get("backup"), tr("ui.manager.backups"))
        self.tabs.currentChanged.connect(self._refresh_current)
        self.close_button = make_button(self, tr("ui.dialog.close"), tr("ui.dialog.close.tip"))
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(button_row(self.close_button))
        finish(self, tr("ui.manager.title"), 820, 520, tr)

    def _refresh_current(self, index: int) -> None:
        tab = self.tabs.widget(index)
        refresh = getattr(tab, "refresh", None)
        if callable(refresh):
            refresh()
