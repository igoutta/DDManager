"""P12 (category editor) and P07 (assign a category): atomic Save/Cancel over core operations."""

import pytest
from PySide6.QtCore import QModelIndex, QPoint
from PySide6.QtWidgets import QMenu

from src.core.categories import (
    CATEGORY_COLOR_CYCLE,
    CATEGORY_COLORS,
    DEFAULT_CATEGORIES,
    get_categories,
)
from src.core.identity import category_memory_keys
from src.core.ids import ModId
from src.core.tiers import TierTable
from tests.ui.m5_support import (
    action_for,
    assert_no_raw_keys,
    construct,
    follow_language,
    load_attr,
    popup_actions,
)

ZEBRA, QUAGGA = "Zebra Mods", "Quagga Mods"
ZEBRA_MOD, TRINKET_MOD, UI_MOD = "chorus_class_mod", "swf_trinkets24_compat", "1739565783"
START_MEMORY = {
    "chorus_class_mod": ZEBRA,
    "norm:chorusclassmod": ZEBRA,
    "swf_trinkets24_compat": "Trinkets",
}


@pytest.fixture
def rig(rig_factory, fake_services):
    """Everything already classified (no silent start-up assignments), one custom category."""
    return rig_factory(
        window=True,
        categories={ZEBRA_MOD: ZEBRA, TRINKET_MOD: "Trinkets", UI_MOD: "UI"},
        attempted=list(fake_services.catalog),
        custom_categories=(ZEBRA,),
        category_colors={ZEBRA: "#112233"},
        category_memory=START_MEMORY,
    )


@pytest.fixture
def open_dialog(rig, qtbot):
    def make():
        dialog = construct(
            load_attr("src.ui.dialogs.categories_dialog", "CategoriesDialog"),
            presenter=rig.controller.categories,
            translator=rig.translator,
            icons=rig.window.icons,
            parent=rig.window,
        )
        qtbot.addWidget(dialog)
        dialog.show()
        return dialog

    return make


def select(dialog, name):
    dialog.select(dialog.list.names().index(name))


def save(dialog):
    dialog.save_button.click()


def written(rig, field):
    rig.controller.flush()
    return rig.state.written(field)


# ---------------------------------------------------------------------------- the list


def test_the_list_shows_every_category_in_editor_order_built_in_ones_marked(rig, open_dialog):
    dialog = open_dialog()
    doc = rig.controller.session.doc
    expected = get_categories(doc.category_order, doc.custom_categories, doc.categories.values())
    assert tuple(dialog.list.names()) == expected
    assert expected == (*DEFAULT_CATEGORIES, ZEBRA)
    suffix = rig.translator.tr("category_builtin_suffix")
    texts = [dialog.list.item(i).text() for i in range(dialog.list.count())]
    assert [t.endswith(f"({suffix})") for t in texts] == [True] * len(DEFAULT_CATEGORIES) + [False]
    assert texts[-1] == ZEBRA


def test_every_row_has_a_swatch_of_its_color(rig, open_dialog):
    dialog = open_dialog()
    for row, name in enumerate(dialog.list.names()):
        item = dialog.list.item(row)
        wanted = "#112233" if name == ZEBRA else CATEGORY_COLORS[name]
        assert not item.icon().isNull()
        assert item.foreground().color().name().upper() == wanted


def test_the_preview_shows_the_color_of_the_selected_row(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, ZEBRA)
    assert dialog.preview.text() == "#112233", "the swatch shows the colour: hex value only"
    assert dialog.preview.toolTip() == rig.translator.tr("category_editor_color", color="#112233")
    select(dialog, "UI")
    assert dialog.preview.text() == "#8FA6B8"
    assert "Color:" not in dialog.preview.text()


def test_every_text_of_the_dialog_is_in_the_catalog(rig, open_dialog):
    assert_no_raw_keys(open_dialog())


# ---------------------------------------------------------------------------- order


def test_up_and_down_move_the_selected_row_and_keep_it_selected(rig, open_dialog):
    dialog = open_dialog()
    start = list(dialog.list.names())
    select(dialog, "Quirks")
    dialog.buttons["up"].click()
    names = dialog.list.names()
    assert names[:5] == ["UI", "Districts", "Quirks", "Dungeons", "Trinkets"]
    assert names[dialog.list.currentRow()] == "Quirks"
    dialog.buttons["down"].click()
    dialog.buttons["down"].click()
    names = dialog.list.names()
    assert names.index("Quirks") == start.index("Quirks") + 1
    assert names[dialog.list.currentRow()] == "Quirks"


def test_up_on_the_first_row_and_down_on_the_last_do_nothing(rig, open_dialog):
    dialog = open_dialog()
    start = list(dialog.list.names())
    dialog.select(0)
    dialog.buttons["up"].click()
    dialog.select(dialog.list.count() - 1)
    dialog.buttons["down"].click()
    assert dialog.list.names() == start


def test_dragging_a_row_reorders_the_draft_and_save_persists_it(rig, open_dialog):
    dialog = open_dialog()
    start = list(dialog.list.names())
    moved = dialog.list.model().moveRow(QModelIndex(), 7, QModelIndex(), 1)  # what a drop does
    assert moved
    wanted = [start[0], start[7], *start[1:7], *start[8:]]
    assert dialog.list.names() == wanted
    assert list(rig.controller.categories.state.categories) == wanted
    save(dialog)
    assert list(rig.flush().category_order) == wanted


# ---------------------------------------------------------------------------- colors


def test_set_color_stores_uppercase_hex_starting_from_the_current_color(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, "UI")
    rig.prompts.colors.append("#abcdef")
    dialog.buttons["set_color"].click()
    assert rig.prompts.colors_asked[-1].upper() == "#8FA6B8"
    assert rig.controller.categories.color_of("UI") == "#ABCDEF"
    assert (
        dialog.list.item(dialog.list.currentRow()).foreground().color().name().upper() == "#ABCDEF"
    )
    assert dialog.preview.text() == "#ABCDEF"
    save(dialog)
    assert rig.flush().category_colors["UI"] == "#ABCDEF"


def test_cancelling_the_color_chooser_changes_nothing(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, "UI")
    rig.prompts.colors.append(None)
    dialog.buttons["set_color"].click()
    assert rig.controller.categories.color_of("UI") == "#8FA6B8"
    save(dialog)
    assert "UI" not in rig.flush().category_colors


def test_reset_color_drops_the_override(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, ZEBRA)
    assert rig.controller.categories.color_of(ZEBRA) == "#112233"
    dialog.buttons["reset_color"].click()
    assert ZEBRA not in rig.controller.categories.state.category_colors
    save(dialog)
    assert ZEBRA not in rig.flush().category_colors


# ---------------------------------------------------------------------------- add


def test_add_appends_a_custom_category_with_the_chosen_color(rig, open_dialog):
    dialog = open_dialog()
    rig.prompts.text_answers.append("  New   Cat ")
    rig.prompts.colors.append("#336699")
    dialog.buttons["add"].click()
    assert dialog.list.names()[-1] == "New Cat"
    assert dialog.list.names()[dialog.list.currentRow()] == "New Cat"
    save(dialog)
    doc = rig.flush()
    assert doc.custom_categories == (ZEBRA, "New Cat")
    assert doc.category_order[-1] == "New Cat"
    assert doc.category_colors["New Cat"] == "#336699"


def test_add_without_a_chosen_color_takes_the_next_cycle_color(rig, open_dialog):
    dialog = open_dialog()
    rig.prompts.text_answers.append("Plain")
    rig.prompts.colors.append(None)
    dialog.buttons["add"].click()
    save(dialog)
    assert rig.flush().category_colors["Plain"] == CATEGORY_COLOR_CYCLE[0]


@pytest.mark.parametrize(
    ("typed", "key", "params"),
    [
        ("   ", "ui.categories.empty", {}),
        ("all", "ui.categories.reserved", {"name": "all"}),
        ("Unassigned", "ui.categories.reserved", {"name": "Unassigned"}),
        ("zebra MODS", "ui.categories.exists", {}),
        ("ui", "ui.categories.exists", {}),
    ],
)
def test_add_refuses_empty_reserved_and_duplicate_names(rig, open_dialog, typed, key, params):
    dialog = open_dialog()
    before = list(dialog.list.names())
    rig.prompts.text_answers.append(typed)
    dialog.buttons["add"].click()
    assert dialog.list.names() == before
    assert rig.prompts.colors_asked == [], "no color is asked for a refused name"
    assert [m.text for m in rig.messages.log] == [rig.translator.tr(key, **params)]


def test_cancelling_the_name_prompt_adds_nothing(rig, open_dialog):
    dialog = open_dialog()
    before = list(dialog.list.names())
    rig.prompts.text_answers.append(None)
    dialog.buttons["add"].click()
    assert dialog.list.names() == before
    assert rig.messages.log == []


# ---------------------------------------------------------------------------- rename


def test_rename_moves_the_assignments_color_and_memory_to_the_new_name(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, ZEBRA)
    rig.prompts.text_answers.append(QUAGGA)
    dialog.buttons["rename"].click()
    assert rig.prompts.texts_asked[-1][2] == ZEBRA, "the prompt starts from the current name"
    assert dialog.list.names()[-1] == QUAGGA
    save(dialog)
    doc = rig.flush()
    assert doc.categories[ModId(ZEBRA_MOD)] == QUAGGA
    assert doc.categories[ModId(TRINKET_MOD)] == "Trinkets"
    assert doc.custom_categories == (QUAGGA,)
    assert doc.category_order == (*DEFAULT_CATEGORIES, QUAGGA)
    assert doc.category_colors == {QUAGGA: "#112233"}
    assert dict(doc.category_memory) == {
        "chorus_class_mod": QUAGGA,
        "norm:chorusclassmod": QUAGGA,
        "swf_trinkets24_compat": "Trinkets",
    }


def test_rename_to_the_same_name_is_not_an_error_and_changes_nothing(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, ZEBRA)
    rig.prompts.text_answers.append(ZEBRA)
    dialog.buttons["rename"].click()
    assert rig.messages.log == []
    assert dialog.list.names()[-1] == ZEBRA


def test_rename_refuses_a_name_another_category_has(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, ZEBRA)
    rig.prompts.text_answers.append("trinkets")
    dialog.buttons["rename"].click()
    assert dialog.list.names()[-1] == ZEBRA
    assert [m.text for m in rig.messages.log] == [rig.translator.tr("ui.categories.exists")]


def test_built_in_categories_can_be_moved_but_not_renamed_or_removed(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, "UI")
    before = rig.controller.categories.state
    dialog.buttons["rename"].click()
    dialog.buttons["remove"].click()
    assert rig.prompts.texts_asked == [], "no name is asked for a built-in category"
    assert rig.messages.texts() == [
        rig.translator.tr("ui.categories.builtin_rename"),
        rig.translator.tr("ui.categories.builtin_remove"),
    ]
    assert not [m for m in rig.messages.log if m.name == "question"], "nothing to confirm"
    assert rig.controller.categories.state == before


# ---------------------------------------------------------------------------- remove


def test_remove_unassigns_its_mods_and_purges_the_memory_after_confirming(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, ZEBRA)
    dialog.buttons["remove"].click()
    asked = [m for m in rig.messages.log if m.name == "question"]
    assert len(asked) == 1
    assert ZEBRA in asked[0].text
    assert ZEBRA not in dialog.list.names()
    save(dialog)
    doc = rig.flush()
    assert ModId(ZEBRA_MOD) not in doc.categories
    assert doc.categories[ModId(TRINKET_MOD)] == "Trinkets"
    assert doc.custom_categories == ()
    assert doc.category_order == DEFAULT_CATEGORIES
    assert ZEBRA not in doc.category_colors
    assert dict(doc.category_memory) == {"swf_trinkets24_compat": "Trinkets"}


def test_declining_the_confirmation_removes_nothing(rig, open_dialog):
    rig.messages.confirm_answer = False
    dialog = open_dialog()
    select(dialog, ZEBRA)
    dialog.buttons["remove"].click()
    assert dialog.list.names()[-1] == ZEBRA
    assert rig.controller.categories.state.removed == ()


# ---------------------------------------------------------------------------- Save / Cancel


def test_nothing_is_written_until_save_and_then_it_is_one_change(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, "Quirks")
    dialog.buttons["up"].click()
    rig.prompts.text_answers.append("Fresh")
    rig.prompts.colors.append("#445566")
    dialog.buttons["add"].click()
    select(dialog, "UI")
    rig.prompts.colors.append("#778899")
    dialog.buttons["set_color"].click()
    rig.controller.flush()
    assert rig.state.written("category_order") == [], "an open editor writes nothing"
    assert rig.state.written("custom_categories") == []
    writes = len(rig.state.saves)
    save(dialog)
    rig.controller.flush()
    assert len(rig.state.saves) == writes + 1
    change = rig.state.saves[-1]
    assert change.category_order is not None
    assert change.custom_categories is not None
    assert change.category_colors is not None
    assert change.category_memory is not None
    assert list(change.category_order)[2] == "Quirks"
    assert change.custom_categories == (ZEBRA, "Fresh")
    assert change.category_colors["Fresh"] == "#445566"
    assert change.category_colors["UI"] == "#778899"


def test_cancel_discards_every_edit(rig, open_dialog):
    dialog = open_dialog()
    start = tuple(dialog.list.names())
    select(dialog, "Quirks")
    dialog.buttons["up"].click()
    rig.prompts.text_answers.append("Doomed")
    rig.prompts.colors.append(None)
    dialog.buttons["add"].click()
    dialog.cancel_button.click()
    assert not dialog.isVisible()
    rig.controller.flush()
    for field in ("category_order", "custom_categories", "category_colors", "category_memory"):
        assert rig.state.written(field) == [], field
    assert rig.controller.session.doc.category_order == (*DEFAULT_CATEGORIES, ZEBRA)
    assert tuple(open_dialog().list.names()) == start, "the next editor starts from the saved state"


def test_escape_cancels_like_the_cancel_button(rig, open_dialog):
    dialog = open_dialog()
    dialog.buttons["up"].click()
    dialog.reject()
    rig.controller.flush()
    assert rig.state.written("category_order") == []


def test_saving_an_untouched_editor_keeps_the_categories(rig, open_dialog):
    before = rig.controller.session.doc
    save(open_dialog())
    doc = rig.flush()
    assert doc.category_order == before.category_order
    assert dict(doc.categories) == dict(before.categories)
    assert doc.custom_categories == before.custom_categories


# ---------------------------------------------------------------------------- after Save


def test_after_save_the_rows_tiers_and_colors_follow(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, "UI")
    rig.prompts.colors.append("#123456")
    dialog.buttons["set_color"].click()
    select(dialog, ZEBRA)
    rig.prompts.text_answers.append(QUAGGA)
    dialog.buttons["rename"].click()
    select(dialog, "Trinkets")
    dialog.buttons["up"].click()
    save(dialog)
    rows = rig.controller.rows()
    assert rows[ModId(UI_MOD)].color == "#123456"
    assert rows[ModId(ZEBRA_MOD)].category_label == QUAGGA
    assert rows[ModId(ZEBRA_MOD)].tier_id == f"custom:{QUAGGA}"
    session = rig.controller.session
    assert session.table == TierTable.from_legacy(
        session.doc.category_order, session.doc.custom_categories
    )
    assert session.table != TierTable.from_legacy(DEFAULT_CATEGORIES, (ZEBRA,))
    assert rig.messages.with_key("ui.notice.categories_updated")


def test_removing_a_category_sends_its_mods_to_unassigned_in_the_rows(rig, open_dialog):
    dialog = open_dialog()
    select(dialog, ZEBRA)
    dialog.buttons["remove"].click()
    save(dialog)
    row = rig.controller.rows()[ModId(ZEBRA_MOD)]
    assert row.tier_id == "unassigned"
    assert row.category_label == rig.translator.tr("category_unassigned")


def test_the_window_action_opens_the_editor_and_save_applies_it(rig):
    action_for(rig.window, "categories")
    categories = load_attr("src.ui.dialogs.categories_dialog", "CategoriesDialog")

    def script(dialog):
        dialog.select(dialog.list.names().index("Quirks"))
        dialog.buttons["up"].click()
        dialog.save_button.click()

    rig.driver.on(categories, script)
    action_for(rig.window, "categories").trigger()
    assert rig.driver.names() == ["CategoriesDialog"]
    assert list(rig.flush().category_order)[2] == "Quirks"


@pytest.mark.parametrize("language", ["es_ES", "pt_PT", "zh_CN"])
def test_the_editor_follows_the_language_live(rig, open_dialog, language):
    dialog = open_dialog()
    select(dialog, ZEBRA)
    result = follow_language(dialog, rig.translator, language)
    assert result.checked >= 8, "title, 7 buttons, save and cancel are catalog texts"
    assert result.changed >= 8, "the legacy catalog translates the editor in every language"
    assert dialog.list.names()[dialog.list.currentRow()] == ZEBRA, "the selection survives"


# ---------------------------------------------------------------------------- P07: assign


def mod_ids(*keys):
    return [ModId(k) for k in keys]


def test_assigning_writes_the_category_and_remembers_it_for_every_identity_key(rig):
    info = rig.mods[ModId("crusader_hu_swf_compat")]
    rig.controller.set_category(mod_ids("crusader_hu_swf_compat"), "Skins")
    doc = rig.flush()
    assert doc.categories[ModId("crusader_hu_swf_compat")] == "Skins"
    assert set(category_memory_keys(info)) <= set(doc.category_memory)
    assert all(doc.category_memory[k] == "Skins" for k in category_memory_keys(info))
    assert rig.controller.rows()[ModId("crusader_hu_swf_compat")].category_label == "Skins"


def test_assigning_to_several_mods_at_once_and_a_custom_category(rig):
    keys = ("crusader_hu_swf_compat", "better_stage_coach_swf_compat")
    assert rig.controller.labels.set_category(mod_ids(*keys), ZEBRA) == 2
    doc = rig.flush()
    assert {doc.categories[ModId(k)] for k in keys} == {ZEBRA}
    note = rig.messages.only("ui.notice.category_set")
    assert note.params["count"] == 2
    assert note.params["category"] == ZEBRA


@pytest.mark.parametrize("pseudo", [None, "Unassigned", "All", ""])
def test_unassigning_removes_the_category(rig, pseudo):
    rig.controller.set_category(mod_ids(TRINKET_MOD), pseudo)
    doc = rig.flush()
    assert ModId(TRINKET_MOD) not in doc.categories
    assert rig.controller.rows()[ModId(TRINKET_MOD)].tier_id == "unassigned"


def test_assigning_never_reorders_and_ignores_unknown_mods(rig):
    order = rig.controller.order()
    count = rig.controller.labels.set_category(mod_ids("not_installed_anywhere"), "Skins")
    assert count == 0
    rig.controller.set_category(mod_ids(TRINKET_MOD, "not_installed_anywhere"), "Skins")
    assert rig.controller.order() == order
    assert rig.controller.undo_stack.count() == 0


def test_the_assign_submenu_lists_the_categories_then_unassigned_and_assigns(rig):
    controller = rig.controller
    controller.select(mod_ids("crusader_hu_swf_compat", "better_stage_coach_swf_compat"))
    action = action_for(rig.window, "assign_category")
    assert action.isEnabled()
    menu = action.menu()
    assert isinstance(menu, QMenu)
    menu.aboutToShow.emit()
    entries = [a for a in menu.actions() if not a.isSeparator()]
    labels = [a.text() for a in entries]
    expected = [c.label for c in controller.labels.category_choices()]
    assert labels == [*expected, rig.translator.tr("category_unassigned")]
    assert "Trinkets" in labels
    assert ZEBRA in labels
    next(a for a in entries if a.text() == "Trinkets").trigger()
    doc = rig.flush()
    assert doc.categories[ModId("crusader_hu_swf_compat")] == "Trinkets"
    assert doc.categories[ModId("better_stage_coach_swf_compat")] == "Trinkets"


def test_assign_needs_a_selection_and_both_lists_offer_it_in_their_context_menu(rig):
    rig.window.show()
    rig.controller.select([])
    assert not action_for(rig.window, "assign_category").isEnabled()
    available = {a.property("ddm_key") for a in rig.window.available.view.actions()}
    assert {"assign_category", "nickname"} <= available
    view = rig.window.load_order.view
    shown = popup_actions(lambda: view.customContextMenuRequested.emit(QPoint(4, 4)))
    assert {"assign_category", "nickname"} <= {a.property("ddm_key") for a in shown}
