"""The three tabs of the profile manager: save slots, load-order profiles, backups."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.dialogs.common import button_row, make_button, make_table, set_cell
from src.ui.i18n import Translator
from src.ui.presenters.dto import ProfilesPort
from src.ui.theme.theme import set_role

_PATH_ROLE = Qt.ItemDataRole.UserRole


def _selected_path(table: QTableWidget) -> Path | None:
    row = table.currentRow()
    item = table.item(row, 0) if row >= 0 else None
    data = item.data(_PATH_ROLE) if item is not None else None
    return Path(str(data)) if data else None


class SlotsTab(QWidget):
    def __init__(self, port: ProfilesPort, translator: Translator, parent: QWidget) -> None:
        super().__init__(parent)
        self._port, self._tr = port, translator
        tr = translator.tr
        self.table = make_table(
            self,
            [tr("ui.slots.col.slot"), tr("ui.slots.col.date"), tr("ui.slots.col.week"),
             tr("ui.slots.col.applied"), tr("ui.slots.col.path")],
        )  # fmt: skip
        self.use_button = make_button(
            self, tr("ui.slots.use"), tr("ui.slots.use.tip"), role="primary"
        )
        self.import_button = make_button(self, tr("ui.slots.import"), tr("ui.slots.import.tip"))
        self.folder_button = make_button(self, tr("ui.slots.folder"), tr("ui.slots.folder.tip"))
        self.save_button = make_button(
            self, tr("ui.slots.choose_save"), tr("ui.slots.choose_save.tip")
        )
        self.mods_button = make_button(
            self, tr("ui.slots.choose_mods"), tr("ui.slots.choose_mods.tip")
        )
        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(
            button_row(self.use_button, self.import_button, self.folder_button, stretch_first=False)
        )
        layout.addLayout(button_row(self.save_button, self.mods_button, stretch_first=False))
        self.use_button.clicked.connect(lambda: self._with_path(port.use_slot, refresh=True))
        self.import_button.clicked.connect(lambda: self._with_path(port.import_order_from_save))
        self.folder_button.clicked.connect(lambda: self._with_path(port.open_slot_folder))
        self.save_button.clicked.connect(lambda: (port.choose_save_file(), self.refresh()))
        self.mods_button.clicked.connect(port.choose_mods_folder)
        self.refresh()

    def _with_path(self, action: Callable[[Path], None], *, refresh: bool = False) -> None:
        path = _selected_path(self.table)
        if path is not None:
            action(path)
            if refresh:
                self.refresh()

    def refresh(self) -> None:
        slots = list(self._port.slots())
        self.table.setRowCount(len(slots))
        for row, slot in enumerate(slots):
            label = f"{slot.label} *" if slot.active else slot.label
            set_cell(self.table, row, 0, label).setData(_PATH_ROLE, str(slot.path))
            set_cell(self.table, row, 1, slot.date_text)
            set_cell(self.table, row, 2, slot.week_text)
            set_cell(self.table, row, 3, slot.applied_text)
            set_cell(self.table, row, 4, str(slot.path))
        self.table.resizeColumnsToContents()


class ProfilesTab(QWidget):
    def __init__(self, port: ProfilesPort, translator: Translator, parent: QWidget) -> None:
        super().__init__(parent)
        self._port, self._tr = port, translator
        tr = translator.tr
        self.listing = QListWidget(self)
        names = ("save", "apply", "import", "export", "rename", "delete")
        self.buttons = {
            name: make_button(self, tr(f"ui.profiles.{name}"), tr(f"ui.profiles.{name}.tip"))
            for name in names
        }
        set_role(self.buttons["apply"], "primary")
        layout = QVBoxLayout(self)
        layout.addWidget(self.listing, 1)
        layout.addLayout(button_row(*self.buttons.values(), stretch_first=False))
        handlers = {
            "save": self._save, "apply": self._apply, "import": self._import,
            "export": self._export, "rename": self._rename, "delete": self._delete,
        }  # fmt: skip
        for name, handler in handlers.items():
            self.buttons[name].clicked.connect(handler)
        self.refresh()

    def refresh(self) -> None:
        self.listing.clear()
        for profile in self._port.profiles():
            text = f"{profile.name}  -  {profile.count_text}  {profile.created_text}".rstrip()
            item = QListWidgetItem(text)
            item.setData(_PATH_ROLE, profile.name)
            item.setToolTip(profile.problem or profile.name)
            self.listing.addItem(item)

    def _name(self) -> str | None:
        item = self.listing.currentItem()
        return str(item.data(_PATH_ROLE)) if item is not None else None

    def _ask(self, title_key: str, default: str = "") -> str | None:
        tr = self._tr.tr
        text, ok = QInputDialog.getText(
            self, tr(title_key), tr("ui.profiles.name_prompt"), QLineEdit.EchoMode.Normal, default
        )
        return text.strip() if ok and text.strip() else None

    def _save(self) -> None:
        name = self._ask("ui.profiles.save")
        if name is not None and self._port.save_profile_as(name):
            self.refresh()

    def _apply(self) -> None:
        name = self._name()
        if name is not None:
            self._port.apply_profile(name)

    def _import(self) -> None:
        tr = self._tr.tr
        path, _filter = QFileDialog.getOpenFileName(
            self, tr("ui.profiles.import"), "", tr("ui.profiles.file_filter")
        )
        if path:
            self._port.import_file(Path(path))
            self.refresh()

    def _export(self) -> None:
        name = self._name()
        if name is None:
            return
        tr = self._tr.tr
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("ui.profiles.export"), f"{name}.loadorder.json", tr("ui.profiles.file_filter")
        )
        if path:
            self._port.export(name, Path(path))

    def _rename(self) -> None:
        name = self._name()
        new = self._ask("ui.profiles.rename", name or "") if name else None
        if name is not None and new is not None and self._port.rename(name, new):
            self.refresh()

    def _delete(self) -> None:
        name = self._name()
        tr = self._tr.tr
        if name is None:
            return
        answer = QMessageBox.question(
            self, tr("ui.profiles.delete"), tr("ui.profiles.delete_confirm", name=name)
        )
        if answer == QMessageBox.StandardButton.Yes and self._port.delete(name):
            self.refresh()


class BackupsTab(QWidget):
    def __init__(self, port: ProfilesPort, translator: Translator, parent: QWidget) -> None:
        super().__init__(parent)
        self._port, self._tr = port, translator
        tr = translator.tr
        self.table = make_table(
            self,
            [tr("ui.backups.col.created"), tr("ui.backups.col.reason"), tr("ui.backups.col.size"),
             tr("ui.backups.col.location")],
        )  # fmt: skip
        self.restore_button = make_button(
            self, tr("ui.backups.restore"), tr("ui.backups.restore.tip"), role="danger"
        )
        self.folder_button = make_button(self, tr("ui.backups.folder"), tr("ui.backups.folder.tip"))
        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(button_row(self.restore_button, self.folder_button, stretch_first=False))
        self.restore_button.clicked.connect(self._restore)
        self.folder_button.clicked.connect(port.open_backup_folder)
        self.refresh()

    def refresh(self) -> None:
        backups = list(self._port.backups_for_active())
        self.table.setRowCount(len(backups))
        for row, backup in enumerate(backups):
            set_cell(self.table, row, 0, backup.created_text, str(backup.path)).setData(
                _PATH_ROLE, str(backup.path)
            )
            set_cell(self.table, row, 1, backup.reason_text)
            set_cell(self.table, row, 2, backup.size_text)
            set_cell(self.table, row, 3, backup.location)
        self.table.resizeColumnsToContents()

    def _restore(self) -> None:
        path = _selected_path(self.table)
        tr = self._tr.tr
        if path is None:
            return
        answer = QMessageBox.question(
            self, tr("ui.backups.restore"), tr("ui.backups.restore_confirm", name=path.name)
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._port.restore(path)
