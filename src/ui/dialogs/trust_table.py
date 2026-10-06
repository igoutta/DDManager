"""The plugin / rule file table shared by the settings dialog and the approval dialog."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QTableWidget, QWidget

from src.ui.dialogs.common import make_table, set_cell
from src.ui.i18n import Translator

if TYPE_CHECKING:
    from src.ui.presenters.trust import TrustFileVM


def status_text(status: str, translator: Translator) -> str:
    key = f"ui.trust.status.{status}"
    return translator.tr(key) if translator.has(key) else status


def trust_headers(translator: Translator, *, with_kind: bool) -> list[str]:
    tr = translator.tr
    headers = [tr("ui.trust.col.file"), tr("ui.trust.col.status"), tr("ui.trust.col.sha256")]
    if with_kind:
        headers.insert(1, tr("ui.trust.col.kind"))
    return headers


def new_trust_table(parent: QWidget, translator: Translator, *, with_kind: bool) -> QTableWidget:
    """An empty, translated table owned by ``parent``."""
    return make_table(parent, trust_headers(translator, with_kind=with_kind))


def retitle_trust_table(table: QTableWidget, translator: Translator, *, with_kind: bool) -> None:
    table.setHorizontalHeaderLabels(trust_headers(translator, with_kind=with_kind))


def fill_trust_table(
    table: QTableWidget,
    rows: Sequence[TrustFileVM],
    translator: Translator,
    *,
    with_kind: bool,
) -> None:
    """One row per file: name, (kind,) status and the full sha256 (also as the tooltip)."""
    table.setRowCount(len(rows))
    for index, row in enumerate(rows):
        column = 0
        set_cell(table, index, column, row.name, row.name)
        if with_kind:
            column += 1
            set_cell(table, index, column, translator.tr(f"ui.trust.kind.{row.kind}"))
        set_cell(table, index, column + 1, status_text(row.status, translator))
        set_cell(table, index, column + 2, row.sha256, row.sha256)
    table.resizeColumnsToContents()


def selected_file(table: QTableWidget, rows: Sequence[TrustFileVM]) -> TrustFileVM | None:
    index = table.currentRow()
    return rows[index] if 0 <= index < len(rows) else None
