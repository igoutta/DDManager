"""Backups of the active save slot: list managed and beside-save ones, restore, open the folder."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from src.services.backup import BackupRecord, RestoreResult
from src.ui.presenters.dto import BackupVM

if TYPE_CHECKING:
    from src.ui.controller import MainController

_DATE_FORMAT = "%Y-%m-%d %H:%M"
_KIB = 1024


def size_text(size: int) -> str:
    return f"{size / _KIB:.0f} KiB" if size >= _KIB else f"{size} B"


class BackupsPresenter(QObject):
    """Everything behind the Backups tab; restoring confirms first and runs in a worker."""

    def __init__(self, controller: MainController) -> None:
        super().__init__(controller)
        self._c = controller
        self._records: dict[Path, BackupRecord] = {}

    def listing(self) -> list[BackupVM]:
        """Managed and beside-save backups of the active save, newest first."""
        save = self._c.save_path()
        self._records.clear()
        if save is None:
            return []
        records = self._c.services.backups.list(save)
        self._records = {record.path: record for record in records}
        return [self._vm(record) for record in records]

    def _vm(self, record: BackupRecord) -> BackupVM:
        created: datetime = record.created
        reason = record.reason.value if record.reason is not None else ""
        return BackupVM(
            path=record.path,
            created_text=created.strftime(_DATE_FORMAT),
            reason_text=reason,
            size_text=size_text(record.size),
            location=record.location,
        )

    def restore(self, path: Path, on_done: Callable[[], None] | None = None) -> None:
        """Replace the active save with the backup at ``path`` (validated, pre-restore backup).

        The user confirms first; ``on_done`` runs on the GUI thread after a successful restore.
        """
        c = self._c
        record = self._records.get(path)
        save = c.save_path()
        prompter = c.prompter
        if record is None or save is None or prompter is None:
            return
        if not prompter.confirm("ui.backups.restore_confirm", name=path.name):
            return
        backups = c.services.backups
        c.run_task(
            lambda _token: backups.restore(record, target=save),
            lambda result: self._restored(result, on_done),
            busy_key="ui.busy.restoring",
        )

    def _restored(self, result: RestoreResult, on_done: Callable[[], None] | None) -> None:
        c = self._c
        before = result.pre_restore_backup
        c.remember_save(before.save_path, before.created, before.path)
        c.post("ui.notice.restored", name=result.restored_from.path.name)
        c.slotsChanged.emit()
        if on_done is not None:
            on_done()

    def open_folder(self) -> None:
        self._c.open_backup_folder()
