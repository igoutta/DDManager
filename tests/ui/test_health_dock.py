"""HealthDock: a re-validation keeps the groups open, the selected finding and the filters."""

import pytest
from PySide6.QtWidgets import QHeaderView, QToolButton

from src.core.findings import Severity
from src.ui.models.findings_model import FCol
from src.ui.widgets.health_dock import COLUMN_MODES
from tests.ui.helpers import make_finding


def findings(n_error=1, n_warning=3, n_info=2, salt=""):
    """Stable keys (e0, w0, ...) whose messages change with ``salt`` (a different set)."""
    groups = ((n_error, "e", Severity.ERROR), (n_warning, "w", Severity.WARNING))
    out = []
    for count, prefix, severity in (*groups, (n_info, "i", Severity.INFO)):
        out += [
            make_finding(f"{prefix}{i}", severity, message=f"{prefix}{i}{salt}")
            for i in range(count)
        ]
    return out


@pytest.fixture
def dock(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    main_window.dock.show()
    return main_window.dock


@pytest.fixture
def model(main_window):
    return main_window.test_controller.findings_model


def expanded(dock, model) -> list[bool]:
    return [dock.tree.isExpanded(model.index(g, 0)) for g in range(model.rowCount())]


def total_rows(model) -> int:
    return sum(model.rowCount(model.index(g, 0)) for g in range(model.rowCount()))


def filter_buttons(dock) -> list[QToolButton]:
    return [b for b in dock.findChildren(QToolButton) if b.isCheckable()]


def test_groups_stay_expanded_and_populated_after_set_findings_again(dock, model):
    model.set_findings(findings())
    assert expanded(dock, model) == [True, True, True]
    assert total_rows(model) == 6
    model.set_findings(findings(n_warning=5, salt="x"))
    assert expanded(dock, model) == [True, True, True]
    assert total_rows(model) == 8
    model.set_findings(findings(n_error=0, salt="y"))
    assert expanded(dock, model) == [True, True]
    assert total_rows(model) == 5


def test_the_selected_finding_and_the_severity_filter_survive_a_revalidation(dock, model):
    model.set_findings(findings())
    dock.tree.setCurrentIndex(model.index_for_key("w1"))
    assert model.finding_at(dock.tree.currentIndex()).key == "w1"
    info = filter_buttons(dock)[2]
    info.setChecked(False)
    assert model.rowCount() == 2, "the Info group is filtered out"
    model.set_findings(findings(n_warning=4, salt="z"))
    assert model.finding_at(dock.tree.currentIndex()).key == "w1"
    assert dock.tree.selectionModel().isSelected(dock.tree.currentIndex())
    assert not info.isChecked()
    assert model.rowCount() == 2
    assert expanded(dock, model) == [True, True]


def test_a_vanished_selection_is_simply_dropped(dock, model):
    model.set_findings(findings())
    dock.tree.setCurrentIndex(model.index_for_key("e0"))
    model.set_findings(findings(n_error=0, salt="q"))
    assert model.finding_at(dock.tree.currentIndex()) is None
    assert expanded(dock, model) == [True, True]


def test_the_message_column_stretches_and_the_others_fit_their_contents(dock):
    header = dock.tree.header()
    assert not header.stretchLastSection()
    for column, mode in COLUMN_MODES.items():
        assert header.sectionResizeMode(column) == mode, column
    assert header.sectionResizeMode(FCol.MESSAGE) == QHeaderView.ResizeMode.Stretch
    assert dock.tree.columnWidth(FCol.MODS) > 0
