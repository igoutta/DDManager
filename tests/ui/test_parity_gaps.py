"""P01-P09 and P27 at window level: panes, buttons, selection and keys M4 left implicit."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QToolButton

from src.core.ids import ModId
from src.ui.models.roles import Role
from src.ui.theme.style import DropIndicatorStyle
from src.ui.widgets.details_pane import DetailsPane
from src.ui.widgets.mod_views import render_drag_badge
from tests.support.factories import local_mod
from tests.ui.conftest import ENABLED
from tests.ui.m5_support import action_for

DISABLED = ModId("chorus_class_mod_testdrop")
DISABLED_2 = ModId("chorus_class_mod_testdrop_v2")


@pytest.fixture
def rig(rig_factory, qtbot):
    rig = rig_factory(window=True)
    rig.window.show()
    qtbot.waitExposed(rig.window)
    qtbot.wait(300)  # the Available list is refreshed on a debounce
    return rig


def click_row(view, row, modifiers=Qt.KeyboardModifier.NoModifier):
    index = view.model().index(row, 0)
    point = view.visualRect(index).center()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, modifiers, point)


# ---------------------------------------------------------------------------- P01


def test_p01_three_panes_left_to_right_available_load_order_details(rig):
    splitter = rig.window.splitter
    assert [splitter.widget(i) for i in range(3)] == [
        rig.window.available,
        rig.window.load_order,
        rig.window.details,
    ]
    assert isinstance(splitter.widget(2), DetailsPane)


def test_p01_the_button_column_is_the_six_shared_actions_in_order(rig):
    buttons = [
        b for b in rig.window.load_order.findChildren(QToolButton) if b.defaultAction() is not None
    ]
    keys = [b.defaultAction().property("ddm_key") for b in buttons]
    assert keys == ["enable", "disable", "top", "up", "down", "bottom"]
    assert all(b.toolTip().strip() and b.toolTip() != b.text() for b in buttons)


def test_p01_enable_appends_the_selected_available_mods_and_disable_removes_them(rig):
    hub = rig.window.hub
    assert not hub["enable"].isEnabled(), "nothing selected in Available"
    rig.window.available.select([DISABLED, DISABLED_2])
    assert hub["enable"].isEnabled()
    hub["enable"].trigger()
    assert [str(m) for m in rig.controller.order().active()][-2:] == [DISABLED, DISABLED_2]
    rig.window.load_order.select([DISABLED])
    rig.window.refresh_actions()
    assert hub["disable"].isEnabled()
    hub["disable"].trigger()
    assert DISABLED not in rig.controller.order().active()
    assert DISABLED_2 in rig.controller.order().active()


# ---------------------------------------------------------------------------- P02


def test_p02_the_drag_badge_is_a_pill_that_grows_with_its_label(rig):
    view = rig.window.load_order.view
    one = render_drag_badge(view, 1, "Chorus")
    three = render_drag_badge(view, 3, "Chorus")
    assert not one.isNull()
    assert one.height() == three.height() == 28
    assert three.width() > one.width(), "the (+N) suffix is part of the badge"
    long = render_drag_badge(view, 1, "x" * 400)
    assert long.width() <= 320


def test_p02_the_load_order_draws_its_drop_position_as_one_row_line(rig):
    view = rig.window.load_order.view
    assert isinstance(view.style(), DropIndicatorStyle)
    assert view.showDropIndicator()
    assert view.dragDropMode() == QAbstractItemView.DragDropMode.DragDrop
    assert rig.window.available.view.dragDropMode() == QAbstractItemView.DragDropMode.DragDrop


# ---------------------------------------------------------------------------- P03


@pytest.mark.parametrize("pane", ["available", "load_order"])
def test_p03_both_lists_use_extended_selection(rig, pane):
    view = getattr(rig.window, pane).view
    assert view.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection


def test_p03_shift_selects_a_range_and_ctrl_toggles_single_rows(rig):
    view = rig.window.load_order.view
    selected = rig.window.load_order.selected_ids
    click_row(view, 1)
    click_row(view, 3, Qt.KeyboardModifier.ShiftModifier)
    assert selected() == [ModId(k) for k in ENABLED[1:4]]
    click_row(view, 5, Qt.KeyboardModifier.ControlModifier)
    assert selected() == [ModId(k) for k in (*ENABLED[1:4], ENABLED[5])]
    click_row(view, 2, Qt.KeyboardModifier.ControlModifier)
    assert selected() == [ModId(k) for k in (ENABLED[1], ENABLED[3], ENABLED[5])]


# ---------------------------------------------------------------------------- P04 / P05


def test_p04_activating_an_available_row_enables_it(rig):
    rig.window.available.select([DISABLED])
    view = rig.window.available.view
    view.activated.emit(view.selectionModel().selectedRows()[0])
    assert DISABLED in rig.controller.order().active()


def test_p05_space_enables_in_available_and_disables_in_the_load_order(rig):
    available = rig.window.available.view
    rig.window.available.select([DISABLED])
    available.setFocus()
    QTest.keyClick(available, Qt.Key.Key_Space)
    assert DISABLED in rig.controller.order().active()
    load_order = rig.window.load_order.view
    rig.window.load_order.select([DISABLED])
    load_order.setFocus()
    QTest.keyClick(load_order, Qt.Key.Key_Space)
    assert DISABLED not in rig.controller.order().active()


def test_p05_delete_disables_the_selection_of_the_load_order(rig):
    view = rig.window.load_order.view
    target = ModId(ENABLED[5])  # not written in the active save: no confirmation needed
    rig.window.load_order.select([target])
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert target not in rig.controller.order().active()


# ---------------------------------------------------------------------------- P08


def test_p08_a_row_shows_the_nickname_the_tier_badge_and_the_category(rig):
    rig.controller.set_nickname(ModId("chorus_class_mod"), "Chorus Nick")
    row = rig.controller.rows()[ModId("chorus_class_mod")]
    assert row.title == "Chorus Nick"
    assert row.tier_badge == rig.translator.tr("ui.tier.cls")
    assert row.category_label == rig.translator.tr("category_class")
    assert row.category_label in row.subtitle
    assert row.source_label in row.subtitle
    assert row.save_identity_text.endswith("mod_local_source")


def test_p08_a_mod_that_appears_on_disk_is_new_appended_disabled_and_nothing_resorts(
    rig_factory, fake_services
):
    rig = rig_factory(window=True, attempted=list(fake_services.catalog))
    before = rig.controller.order()
    catalog = {**rig.services.catalog, ModId("zz_fresh"): local_mod("zz_fresh")}
    rig.services.scanner.set_catalog(catalog)
    rig.controller.rescan()
    after = rig.controller.order()
    assert after.entries == (*before.entries, ModId("zz_fresh"))
    assert not after.is_enabled(ModId("zz_fresh"))
    assert after.active() == before.active()
    assert rig.controller.rows()[ModId("zz_fresh")].is_new
    assert not rig.controller.rows()[ModId(ENABLED[0])].is_new
    assert rig.translator.tr("ui.row.new") == "NEW"


def test_p08_the_new_pill_changes_what_the_row_paints(rig_factory, fake_services, qtbot):
    rig = rig_factory(window=True, attempted=list(fake_services.catalog))
    catalog = {**rig.services.catalog, ModId("zz_fresh"): local_mod("zz_fresh")}
    rig.services.scanner.set_catalog(catalog)
    rig.controller.rescan()
    rig.window.show()
    qtbot.waitExposed(rig.window)
    qtbot.wait(300)
    view = rig.window.available.view
    rig.window.available.search.setText("zz_fresh")
    qtbot.wait(400)
    assert view.model().rowCount() == 1
    with_pill = view.viewport().grab().toImage()
    rig.controller.session.new_ids = frozenset()
    rig.controller.rebuild()
    qtbot.wait(100)
    without = view.viewport().grab().toImage()
    assert with_pill != without, "the NEW pill is painted into the row"


# ---------------------------------------------------------------------------- P27


def test_p27_the_selection_survives_a_rescan_and_a_renamed_mod_gets_selected(rig):
    chosen = [ModId(ENABLED[1]), ModId(ENABLED[3])]
    rig.window.load_order.select(chosen)
    assert rig.window.load_order.selected_ids() == chosen
    rig.controller.rescan()
    assert rig.window.load_order.selected_ids() == chosen
    rig.controller.set_nickname(chosen[0], "Renamed")
    assert rig.window.load_order.selected_ids() == [chosen[0]]


def test_p27_a_move_keeps_the_moved_rows_selected(rig):
    mover = ModId(ENABLED[3])
    rig.window.load_order.select([mover])
    action_for(rig.window, "up").trigger()
    assert rig.window.load_order.selected_ids() == [mover]
    assert rig.controller.order().active()[2] == mover


# ---------------------------------------------------------------------------- P08: the NEW window


def fresh_rig(rig_factory, fake_services):
    """A started rig whose next scan finds one more local mod, ``zz_fresh``."""
    rig = rig_factory(window=True, attempted=list(fake_services.catalog))
    catalog = {**rig.services.catalog, ModId("zz_fresh"): local_mod("zz_fresh")}
    rig.services.scanner.set_catalog(catalog)
    return rig


def available_order(rig):
    model = rig.controller.available_model
    return [model.vm_at(row).mod_id for row in range(model.rowCount())]


def proxy_order(rig):
    proxy = rig.controller.available_proxy
    return [proxy.index(row, 0).data(Role.MOD_ID) for row in range(proxy.rowCount())]


def test_p08_the_new_pill_expires_after_the_highlight_window_without_a_resort(
    rig_factory, fake_services, qtbot
):
    from src.ui.controller_highlight import NEW_MOD_HIGHLIGHT_MS

    rig = fresh_rig(rig_factory, fake_services)
    highlight = rig.controller.highlight
    assert not highlight.timer.isActive(), "nothing is new after the first scan"
    rig.controller.rescan()
    assert rig.controller.rows()[ModId("zz_fresh")].is_new
    assert highlight.timer.isActive() and highlight.timer.isSingleShot()
    assert highlight.timer.interval() == NEW_MOD_HIGHLIGHT_MS == 15000
    available, load_order = rig.controller.available_model, rig.controller.load_order_model
    before = (available_order(rig), proxy_order(rig), list(load_order.order()))
    commands = rig.controller.undo_stack.count()
    with (
        qtbot.waitSignal(available.dataChanged, timeout=1000) as changed,
        qtbot.assertNotEmitted(available.layoutChanged),
        qtbot.assertNotEmitted(available.rowsMoved),
        qtbot.assertNotEmitted(load_order.layoutChanged),
        qtbot.assertNotEmitted(load_order.dataChanged),
    ):
        highlight.timer.timeout.emit()  # the 15 seconds are over
    assert not highlight.timer.isActive()
    assert rig.controller.session.new_ids == frozenset()
    assert not rig.controller.rows()[ModId("zz_fresh")].is_new
    top, bottom, _roles = changed.args
    assert top.row() == bottom.row() == available.row_of(ModId("zz_fresh")), "that row only"
    assert (available_order(rig), proxy_order(rig), list(load_order.order())) == before
    assert rig.controller.undo_stack.count() == commands, "losing the pill is not an edit"
    highlight.expire()  # a second expiry has nothing to do
    assert rig.controller.session.new_ids == frozenset()


def test_p08_a_scan_that_finds_nothing_new_ends_the_pill_and_its_timer(rig_factory, fake_services):
    rig = fresh_rig(rig_factory, fake_services)
    rig.controller.rescan()
    assert rig.controller.highlight.timer.isActive()
    rig.controller.rescan()  # zz_fresh is now a known entry of the order
    assert not rig.controller.highlight.timer.isActive()
    assert rig.controller.session.new_ids == frozenset()
    assert not rig.controller.rows()[ModId("zz_fresh")].is_new
    assert rig.controller.order().entries[-1] == ModId("zz_fresh"), "still appended, never sorted"
