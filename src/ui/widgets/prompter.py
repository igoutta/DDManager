"""The Qt implementation of the controller's ``Prompter`` port (message boxes and dialogs)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QPushButton, QWidget

from src.ui.dialogs.order_diff_dialog import OrderDiffDialog
from src.ui.dialogs.patch_preview_dialog import PatchPreviewDialog
from src.ui.i18n import Translator
from src.ui.ports import PatchDecision
from src.ui.theme.theme import set_role
from src.ui.viewmodels import OrderDiffVM, PatchPreviewVM

_MAX_TITLES = 12


class QtPrompter:
    """Everything the controller asks the user goes through here (tests use a fake)."""

    def __init__(self, parent: QWidget, translator: Translator) -> None:
        self._parent = parent
        self._tr = translator

    # ------------------------------------------------------------------ helpers

    def _box(self, icon: QMessageBox.Icon, title: str, text: str, detail: str = "") -> QMessageBox:
        box = QMessageBox(icon, title, text, QMessageBox.StandardButton.NoButton, self._parent)
        if detail:
            box.setInformativeText(detail)
        return box

    def _add(self, box: QMessageBox, key: str, role: QMessageBox.ButtonRole) -> QPushButton:
        button = box.addButton(self._tr.tr(key), role)
        button.setToolTip(self._tr.tr(f"{key}.tip"))
        return button

    # ------------------------------------------------------------------ port

    def confirm_disable_active(self, titles: Sequence[str], slot_label: str) -> bool:
        tr = self._tr.tr
        shown = "\n".join(f"- {title}" for title in titles[:_MAX_TITLES])
        if len(titles) > _MAX_TITLES:
            shown += "\n" + tr("ui.prompt.more", count=len(titles) - _MAX_TITLES)
        box = self._box(
            QMessageBox.Icon.Warning,
            tr("ui.prompt.disable_active.title"),
            tr("ui.prompt.disable_active", count=len(titles), slot=slot_label),
            shown,
        )
        yes = self._add(box, "ui.prompt.disable_active.yes", QMessageBox.ButtonRole.AcceptRole)
        no = self._add(box, "ui.dialog.cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        return box.clickedButton() is yes

    def review_order_change(self, vm: OrderDiffVM, title_key: str) -> bool:
        dialog = OrderDiffDialog(vm, self._tr.tr(title_key), self._tr, self._parent)
        return dialog.exec() == OrderDiffDialog.DialogCode.Accepted

    def review_patch(self, vm: PatchPreviewVM) -> PatchDecision:
        dialog = PatchPreviewDialog(vm, self._tr, self._parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return PatchDecision(proceed=False, acknowledged=frozenset(), override_errors=False)
        return dialog.decision()

    def resolve_state_conflict(self) -> Literal["reload", "overwrite", "cancel"]:
        tr = self._tr.tr
        box = self._box(
            QMessageBox.Icon.Warning, tr("ui.prompt.conflict.title"), tr("ui.prompt.conflict")
        )
        reload = self._add(box, "ui.status.reload", QMessageBox.ButtonRole.AcceptRole)
        mine = self._add(box, "ui.status.keep_mine", QMessageBox.ButtonRole.DestructiveRole)
        cancel = self._add(box, "ui.dialog.cancel", QMessageBox.ButtonRole.RejectRole)
        set_role(mine, "danger")
        box.setDefaultButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reload:
            return "reload"
        return "overwrite" if clicked is mine else "cancel"

    def info(self, key: str, **params: object) -> None:
        box = self._box(
            QMessageBox.Icon.Information, self._tr.tr("app_title"), self._tr.tr(key, **params)
        )
        self._add(box, "ui.dialog.close", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def error(self, key: str, details: str = "", **params: object) -> None:
        box = self._box(
            QMessageBox.Icon.Critical,
            self._tr.tr("ui.prompt.error"),
            self._tr.tr(key, **params),
            details,
        )
        self._add(box, "ui.dialog.close", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def pick_save_file(self, start_dir: Path | None) -> Path | None:
        tr = self._tr.tr
        path, _filter = QFileDialog.getOpenFileName(
            self._parent,
            tr("ui.pick.save"),
            str(start_dir) if start_dir else "",
            tr("ui.pick.save_filter"),
        )
        return Path(path) if path else None

    def pick_folder(self, start_dir: Path | None) -> Path | None:
        path = QFileDialog.getExistingDirectory(
            self._parent, self._tr.tr("ui.pick.folder"), str(start_dir) if start_dir else ""
        )
        return Path(path) if path else None

    def pick_profile_file(self, save: bool) -> Path | None:
        tr = self._tr.tr
        if save:
            path, _filter = QFileDialog.getSaveFileName(
                self._parent, tr("ui.profiles.export"), "", tr("ui.profiles.file_filter")
            )
        else:
            path, _filter = QFileDialog.getOpenFileName(
                self._parent, tr("ui.profiles.import"), "", tr("ui.profiles.file_filter")
            )
        return Path(path) if path else None
