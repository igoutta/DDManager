"""Pane layouts in use: the Available list, the Load Order header, density and language trips."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QHeaderView

from src.ui.models.load_order_model import Col
from src.ui.theme.tokens import DENSITY
from src.ui.widgets.delegates import text_block_height
from src.ui.widgets.details_pane import MIN_WIDTH_PX
from src.ui.widgets.window_actions import LANGUAGES

FIT = (Col.TIER, Col.SOURCE, Col.FINDINGS)
STATUS_WIDGETS = ("profile", "save_path", "backup", "counts")


def settle() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.fixture
def rig(rig_factory, qtbot):
    rig = rig_factory(window=True)
    rig.window.show()
    qtbot.waitExposed(rig.window)
    settle()
    return rig


def header_fits(view) -> None:
    header = view.horizontalHeader()
    metrics = header.fontMetrics()
    for col in FIT:
        text = str(view.model().headerData(col, Qt.Orientation.Horizontal))
        assert header.sectionSize(col) >= metrics.horizontalAdvance(text), text


def status_apart(window) -> None:
    bar = window.status_bar
    rects = [(n, getattr(bar, n).geometry()) for n in STATUS_WIDGETS]
    for i, (n1, r1) in enumerate(rects):
        for n2, r2 in rects[i + 1 :]:
            assert not r1.intersects(r2), (n1, r1, n2, r2)


# ---------------------------------------------------------------------------- Available


def test_the_available_list_never_scrolls_sideways(rig):
    view = rig.window.available.view
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.textElideMode() == Qt.TextElideMode.ElideRight
    assert view.uniformItemSizes()
    assert view.model().rowCount() > 0
    assert view.sizeHintForColumn(0) <= view.viewport().width()
    assert not view.horizontalScrollBar().isVisible()


def test_the_filter_row_shows_the_whole_checkbox(rig):
    pane = rig.window.available
    box = pane.show_active
    assert box.isVisible()
    assert box.width() >= box.sizeHint().width()
    assert box.geometry().right() < pane.width()
    assert pane.source_combo.isVisible()


# ---------------------------------------------------------------------------- Load Order


def test_load_order_columns_fit_their_headers(rig):
    view = rig.window.load_order.view
    header = view.horizontalHeader()
    assert header.sectionResizeMode(Col.TITLE) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(Col.RANK) == QHeaderView.ResizeMode.Fixed
    for col in FIT:
        assert header.sectionResizeMode(col) == QHeaderView.ResizeMode.ResizeToContents, col
    header_fits(view)
    assert not view.horizontalScrollBar().isVisible()


# ---------------------------------------------------------------------------- round trips


def test_density_round_trip_keeps_rows_readable(rig):
    view = rig.window.available.view
    two_lines = text_block_height(view.font())
    for mode in (*DENSITY, "Comfortable"):
        rig.controller.set_density(mode)
        settle()
        assert view.sizeHintForRow(0) >= two_lines, mode
        assert view.sizeHintForRow(0) >= DENSITY[mode][1], mode
        assert not view.horizontalScrollBar().isVisible(), mode
        hub = rig.window.hub.actions
        assert sum(hub[k].isChecked() for k in hub if k.startswith("density_")) == 1


def test_language_round_trip_keeps_panes_and_status_bar_sane(rig, translator):
    window = rig.window
    for code in ("es_ES", "zh_CN", "pt_PT", "en"):
        translator.set_language(code)
        settle()
        assert window.details.width() >= MIN_WIDTH_PX, code
        assert window.details.stack.currentWidget() is window.details.placeholder
        status_apart(window)
        assert [c for c in LANGUAGES if window.hub[f"lang_{c}"].isChecked()] == [code]
        header_fits(window.load_order.view)
        assert not window.available.view.horizontalScrollBar().isVisible(), code
