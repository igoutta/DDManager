"""P10: the four view modes (density) change row height and thumbnail size; kept as view_mode."""

import pytest
from PySide6.QtCore import QSize, Qt

from src.core.ids import ModId
from src.ui.models.load_order_model import Col
from src.ui.theme.tokens import DENSITY
from tests.ui.m5_support import action_for

MODES = ("No Icons", "Compact", "Comfortable", "Visual")
ICON_PX = {"No Icons": 0, "Compact": 28, "Comfortable": 40, "Visual": 52}
ROW_PX = {"No Icons": 24, "Compact": 32, "Comfortable": 46, "Visual": 60}


def slug(mode):
    return mode.lower().replace(" ", "_")


@pytest.fixture
def rig(rig_factory):
    return rig_factory(window=True)


@pytest.fixture
def requested_px(thumbs, monkeypatch):
    """Every thumbnail size the model asks the provider for."""
    asked: list[int] = []
    original = thumbs.pixmap

    def spy(mod_id, path, stamp, px=0):
        asked.append(px)
        return original(mod_id, path, stamp, px)

    monkeypatch.setattr(thumbs, "pixmap", spy)
    return asked


def choose(rig, mode):
    action = action_for(rig.window, f"density_{slug(mode)}")
    action.setChecked(False)
    action.trigger()
    return action


def title_decoration(rig, row=0):
    model = rig.controller.load_order_model
    return model.data(model.index(row, int(Col.TITLE)), Qt.ItemDataRole.DecorationRole)


# ---------------------------------------------------------------------------- the table


def test_the_four_canonical_modes_and_their_sizes():
    assert tuple(DENSITY) == MODES
    assert {mode: DENSITY[mode][0] for mode in MODES} == ICON_PX
    assert {mode: DENSITY[mode][1] for mode in MODES} == ROW_PX


def test_every_mode_has_a_checkable_action_with_a_tip(rig):
    for mode in MODES:
        action = action_for(rig.window, f"density_{slug(mode)}")
        assert action.isCheckable()
        assert action.toolTip() != action.text()
        assert action.property("ddm_key") == f"density_{slug(mode)}"


# ---------------------------------------------------------------------------- choosing


@pytest.mark.parametrize("mode", MODES)
def test_choosing_a_mode_persists_it_under_its_canonical_key(rig, mode):
    other = "Visual" if mode != "Visual" else "Compact"
    choose(rig, other)
    choose(rig, mode)
    assert rig.controller.density() == mode
    assert rig.settings_written()["view_mode"] == mode
    assert rig.controller.settings.density() == mode


@pytest.mark.parametrize("mode", MODES)
def test_the_load_order_rows_take_the_mode_height_and_icon_size(rig, mode):
    choose(rig, mode)
    view = rig.window.load_order.view
    assert view.verticalHeader().defaultSectionSize() == ROW_PX[mode]
    assert view.iconSize() == QSize(ICON_PX[mode], ICON_PX[mode])


@pytest.mark.parametrize("mode", MODES)
def test_the_available_rows_take_the_mode_height_but_never_less_than_two_lines(rig, mode):
    from src.ui.widgets.delegates import text_block_height

    choose(rig, mode)
    view = rig.window.available.view
    rig.window.show()
    two_lines = text_block_height(view.font())
    assert view.sizeHintForRow(0) == max(ROW_PX[mode], two_lines)
    assert view.sizeHintForRow(0) >= two_lines, "title + subtitle must never overlap the next row"


@pytest.mark.parametrize("mode", MODES)
def test_the_model_asks_for_thumbnails_of_the_mode_size_or_none(rig, requested_px, mode):
    choose(rig, "Comfortable" if mode != "Comfortable" else "Compact")
    requested_px.clear()
    choose(rig, mode)
    assert title_decoration(rig) is None  # the fake provider has no pixmaps
    if ICON_PX[mode] == 0:
        assert requested_px == [], "No Icons never asks for a thumbnail"
    else:
        assert requested_px == [ICON_PX[mode]]


def test_exactly_one_mode_is_checked_and_it_follows_the_choice(rig):
    for mode in MODES:
        choose(rig, mode)
        checked = [m for m in MODES if action_for(rig.window, f"density_{slug(m)}").isChecked()]
        assert checked == [mode]


def test_the_signal_carries_the_mode(rig, qtbot):
    with qtbot.waitSignal(rig.controller.densityChanged) as blocker:
        rig.controller.set_density("Compact")
    assert blocker.args == ["Compact"]


def test_changing_the_density_never_touches_the_order_or_the_undo_stack(rig):
    order = rig.controller.order()
    for mode in MODES:
        choose(rig, mode)
    assert rig.controller.order() == order
    assert rig.controller.undo_stack.count() == 0
    rig.controller.flush()
    assert all(change.order is None or change.order == order for change in rig.state.saves)


def test_the_list_data_is_the_same_in_every_mode(rig):
    titles = {mod: row.title for mod, row in rig.controller.rows().items()}
    for mode in MODES:
        choose(rig, mode)
        assert {mod: row.title for mod, row in rig.controller.rows().items()} == titles
        assert rig.controller.load_order_model.rowCount() == len(rig.controller.order().active())


# ---------------------------------------------------------------------------- persistence


@pytest.mark.parametrize("mode", MODES)
def test_a_window_opened_on_a_saved_mode_starts_in_it(rig_factory, mode):
    rig = rig_factory(window=True, extra={"view_mode": mode})
    assert rig.controller.density() == mode
    assert action_for(rig.window, f"density_{slug(mode)}").isChecked()
    assert rig.window.load_order.view.verticalHeader().defaultSectionSize() == ROW_PX[mode]


def test_an_unknown_saved_mode_falls_back_to_comfortable_without_rewriting_the_file(rig_factory):
    rig = rig_factory(window=True, extra={"view_mode": "Gigantic"})
    assert action_for(rig.window, "density_comfortable").isChecked()
    assert rig.window.load_order.view.verticalHeader().defaultSectionSize() == ROW_PX["Comfortable"]
    assert "view_mode" not in rig.settings_written()


def test_the_settings_presenter_ignores_modes_that_do_not_exist(rig):
    rig.controller.settings.set_density("Gigantic")
    assert rig.controller.density() == "Comfortable"
    rig.controller.settings.set_density("Visual")
    assert rig.controller.density() == "Visual"


def test_the_choice_survives_a_restart_through_the_state_file(rig_factory):
    first = rig_factory(window=True)
    choose(first, "Visual")
    saved = first.flush()
    assert saved.settings.view_mode == "Visual"
    second = rig_factory(window=True, extra={"view_mode": saved.settings.view_mode})
    assert second.controller.density() == "Visual"
    assert ModId("chorus_class_mod") in second.controller.rows()
