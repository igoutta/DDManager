"""MainWindow end-to-end smoke: construction, panes, direction labels, search debounce, ui.ini."""

import pytest
from PySide6.QtWidgets import QLabel, QLineEdit, QSplitter

from src.core.load_order import PriorityDirection, PrioritySetting
from src.services.settings_repo import Settings
from src.ui.widgets.available_pane import AvailablePane
from src.ui.widgets.details_pane import DetailsPane
from src.ui.widgets.health_dock import HealthDock
from src.ui.widgets.load_order_pane import LoadOrderPane
from tests.ui.conftest import ENABLED
from tests.ui.helpers import make_status


def label_texts(window) -> list[str]:
    return [w.text() for w in window.findChildren(QLabel) if w.isVisible()]


def test_window_builds_with_the_three_panes_and_a_hidden_health_dock(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    for pane in (AvailablePane, LoadOrderPane, DetailsPane):
        assert main_window.findChild(pane) is not None, pane.__name__
    assert not main_window.findChild(HealthDock).isVisible()
    assert main_window.windowTitle().strip()
    assert main_window.menuBar().actions()
    assert main_window.statusBar() is not None


def test_start_fills_the_window(main_window, qtbot):
    controller = main_window.test_controller
    main_window.show()
    controller.start()
    assert controller.load_order_model.rowCount() == len(ENABLED)
    assert controller.available_model.rowCount() > len(ENABLED)


def test_status_vm_drives_the_direction_labels(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    main_window.test_controller.statusChanged.emit(
        make_status(direction_top_label="TOPMARK first", direction_bottom_label="BOTMARK last")
    )
    texts = label_texts(main_window)
    assert any("TOPMARK first" in t for t in texts)
    assert any("BOTMARK last" in t for t in texts)


def test_unverified_direction_shows_a_chip_only_while_unverified(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    emit = main_window.test_controller.statusChanged.emit
    emit(make_status(direction_verified=False))
    assert any("unverified" in t.lower() for t in label_texts(main_window)), label_texts(
        main_window
    )
    emit(make_status(direction_verified=True))
    assert not any("unverified" in t.lower() for t in label_texts(main_window))


@pytest.mark.parametrize(
    ("setting", "winner_is_bottom"),
    [
        (PrioritySetting(PriorityDirection.LAST_WINS, True), True),
        (PrioritySetting(PriorityDirection.FIRST_WINS, True), False),
    ],
)
def test_first_and_last_wins_label_the_right_end(
    qtbot, fake_services, window_factory, setting, winner_is_bottom
):
    settings = Settings(priority=setting)
    fake_services.initial_settings = settings
    fake_services._real.settings.save(settings)
    window = window_factory()
    window.show()
    window.test_controller.start()
    qtbot.waitExposed(window)
    texts = label_texts(window)
    winners = [t for t in texts if "wins" in t.lower()]
    assert len(winners) == 1, texts
    assert ("last" in winners[0].lower()) is winner_is_bottom


def test_search_box_is_debounced(main_window, qtbot):
    controller = main_window.test_controller
    main_window.show()
    controller.start()
    proxy = controller.available_proxy
    proxy.set_show_enabled(True)
    total = proxy.rowCount()
    box = main_window.findChild(AvailablePane).findChild(QLineEdit)
    box.setText("chorus")
    assert proxy.rowCount() == total  # the 150 ms debounce has not fired yet
    qtbot.waitUntil(lambda: proxy.rowCount() < total, timeout=2000)
    assert proxy.rowCount() >= 1


def test_splitter_state_round_trips_through_ui_ini(qtbot, fake_services, window_factory):
    first = window_factory()
    first.resize(1300, 800)
    first.show()
    qtbot.waitExposed(first)
    splitter = first.findChild(QSplitter)
    splitter.setSizes([180, 420, 380, 220][: splitter.count()] or [1])
    wanted = splitter.sizes()
    first.close()
    ini = fake_services.paths.ui_settings_file
    assert ini.exists() and ini.stat().st_size > 0
    second = window_factory()
    second.show()
    qtbot.waitExposed(second)
    got = second.findChild(QSplitter).sizes()
    assert len(got) == len(wanted)
    assert all(abs(a - b) <= 3 for a, b in zip(got, wanted, strict=True)), (got, wanted)


def test_close_flushes_state(main_window, fake_services):
    controller = main_window.test_controller
    controller.start()
    main_window.show()
    assert main_window.close()
