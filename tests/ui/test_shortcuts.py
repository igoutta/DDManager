"""Shortcut hygiene: no clashes per context, move actions scoped to the list, Ctrl+Up works."""

from collections import defaultdict

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest

from src.ui.widgets.mod_views import LoadOrderView

MOVE_KEYS = {
    "Ctrl+Home": "top",
    "Ctrl+Up": "up",
    "Ctrl+Down": "down",
    "Ctrl+End": "bottom",
}


def window_actions(window):
    return [a for a in window.findChildren(QAction) if a.property("ddm_key")]


def test_no_duplicate_key_sequence_within_a_context(main_window):
    seen = defaultdict(list)
    for action in window_actions(main_window):
        for seq in action.shortcuts():
            seen[(action.shortcutContext(), seq.toString())].append(action.property("ddm_key"))
    clashes = {k: v for k, v in seen.items() if len(set(v)) > 1}
    assert not clashes, clashes
    assert len(seen) >= 10


def test_expected_global_shortcuts_exist(main_window):
    bound = {
        seq.toString(): a.property("ddm_key")
        for a in window_actions(main_window)
        for seq in a.shortcuts()
    }
    for text in ("F5", "Ctrl+Shift+A", "F7", "Ctrl+B", "Ctrl+Shift+P", "Ctrl+P", "Ctrl+F", "F1"):
        assert QKeySequence(text).toString() in bound, text


def test_move_actions_are_scoped_to_the_list(main_window):
    found = {}
    for action in window_actions(main_window):
        for seq in action.shortcuts():
            if seq.toString() in MOVE_KEYS:
                found[seq.toString()] = action
    assert set(found) == set(MOVE_KEYS)
    for action in found.values():
        assert action.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut


def _prepare(main_window, qtbot, row):
    controller = main_window.test_controller
    controller.start()
    main_window.show()
    qtbot.waitExposed(main_window)
    view = main_window.findChild(LoadOrderView)
    view.setFocus()
    view.selectRow(row)
    return controller, view


def test_move_up_action_moves_the_selected_row(main_window, qtbot):
    controller, _ = _prepare(main_window, qtbot, 3)
    before = controller.load_order_model.order()
    action = next(
        a for a in window_actions(main_window) if QKeySequence("Ctrl+Up") in a.shortcuts()
    )
    assert action.isEnabled()
    action.trigger()
    after = controller.load_order_model.order()
    assert after[2] == before[3] and after[3] == before[2]


def test_ctrl_up_key_event_moves_the_selected_row(main_window, qtbot):
    controller, view = _prepare(main_window, qtbot, 3)
    before = controller.load_order_model.order()
    qtbot.waitUntil(view.hasFocus, timeout=2000)
    QTest.keyClick(view, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    after = controller.load_order_model.order()
    assert after[2] == before[3] and after[3] == before[2]


@pytest.mark.parametrize("key", ["Ctrl+Home", "Ctrl+End"])
def test_edge_moves_are_disabled_when_they_would_do_nothing(main_window, qtbot, key):
    _prepare(main_window, qtbot, 0 if key == "Ctrl+Home" else 5)
    action = next(a for a in window_actions(main_window) if QKeySequence(key) in a.shortcuts())
    assert not action.isEnabled()
