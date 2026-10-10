"""P23: nicknames. The default display name (or nothing) clears; the save never sees a nickname."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from src.core.display import display_name
from src.core.ids import ModId
from tests.ui.m5_support import (
    action_for,
    assert_no_raw_keys,
    construct,
    follow_language,
    load_attr,
)

MOD = ModId("crusader_hu_swf_compat")
OTHER = ModId("swf_trinkets24_compat")


@pytest.fixture
def rig(rig_factory, fake_services):
    return rig_factory(window=True, attempted=list(fake_services.catalog))


def default_name(rig, mod=MOD):
    return display_name(rig.mods[mod], None)


def title(rig, mod=MOD):
    return rig.controller.rows()[mod].title


def nicknames_written(rig):
    rig.controller.flush()
    return rig.state.written("nicknames")


# ---------------------------------------------------------------------------- the rule


def test_a_nickname_replaces_the_title_everywhere_the_row_shows_it(rig):
    assert title(rig) == default_name(rig)
    assert rig.controller.set_nickname(MOD, "Fancy Name") is True
    row = rig.controller.rows()[MOD]
    assert row.title == "Fancy Name"
    assert "fancy name" in row.search_blob
    assert row.sort_key == "fancy name"
    assert rig.flush().nicknames[MOD] == "Fancy Name"


def test_the_nickname_is_saved_as_typed_with_whitespace_collapsed(rig):
    rig.controller.set_nickname(MOD, "  Fancy \t  Name  ")
    assert rig.flush().nicknames[MOD] == "Fancy Name"
    assert nicknames_written(rig)[-1] == {MOD: "Fancy Name"}


def test_the_default_display_name_clears_an_existing_nickname(rig):
    rig.controller.set_nickname(MOD, "Fancy Name")
    rig.flush()
    rig.messages.clear()
    assert rig.controller.set_nickname(MOD, default_name(rig)) is True
    assert MOD not in rig.flush().nicknames
    assert nicknames_written(rig)[-1] == {MOD: None}
    assert title(rig) == default_name(rig)
    assert rig.messages.only("status_nickname_cleared").level == "info"


def test_empty_text_clears_the_nickname(rig):
    rig.controller.set_nickname(MOD, "Fancy Name")
    assert rig.controller.set_nickname(MOD, "   ") is True
    assert MOD not in rig.flush().nicknames


def test_the_default_display_name_without_a_nickname_changes_nothing(rig):
    before = len(rig.state.saves)
    assert rig.controller.set_nickname(MOD, default_name(rig)) is False
    assert rig.controller.set_nickname(MOD, f"  {default_name(rig)}  ") is False
    assert rig.controller.set_nickname(MOD, "") is False
    rig.controller.flush()
    assert len(rig.state.saves) == before
    assert rig.messages.log == []


def test_repeating_the_saved_nickname_changes_nothing(rig):
    rig.controller.set_nickname(MOD, "Fancy Name")
    rig.flush()
    writes = len(rig.state.saves)
    rig.messages.clear()
    assert rig.controller.set_nickname(MOD, "Fancy   Name") is False
    rig.controller.flush()
    assert len(rig.state.saves) == writes
    assert rig.messages.log == []


def test_setting_a_nickname_says_so_and_keeps_the_mod_selected(rig):
    rig.controller.set_nickname(MOD, "Fancy Name")
    note = rig.messages.only("status_nickname_set")
    assert note.params == {"nickname": "Fancy Name"}
    assert rig.translator.tr("status_nickname_set", nickname="Fancy Name") in note.text
    assert rig.controller.selection() == (MOD,)


def test_a_mod_that_is_not_installed_cannot_get_a_nickname(rig):
    assert rig.controller.set_nickname(ModId("not_installed_anywhere"), "Ghost") is False
    assert nicknames_written(rig) == []


def test_two_mods_keep_separate_nicknames(rig):
    rig.controller.set_nickname(MOD, "One")
    rig.controller.set_nickname(OTHER, "Two")
    doc = rig.flush()
    assert (doc.nicknames[MOD], doc.nicknames[OTHER]) == ("One", "Two")
    rig.controller.set_nickname(MOD, "")
    assert MOD not in rig.flush().nicknames
    assert rig.flush().nicknames[OTHER] == "Two"


def test_a_nickname_never_changes_the_order_or_what_the_save_gets(rig):
    order = rig.controller.order()
    rig.controller.patch_save()
    rig.controller.set_nickname(MOD, "Fancy Name")
    rig.controller.patch_save()
    first, second = rig.services.patcher.plans
    assert first[1] == second[1], "the save identities are the same with and without nicknames"
    assert rig.controller.order() == order
    assert rig.controller.undo_stack.count() == 0


# ---------------------------------------------------------------------------- the dialog


def make_dialog(rig, qtbot, mod=MOD):
    dialog = construct(
        load_attr("src.ui.dialogs.nickname_dialog", "NicknameDialog"),
        vm=rig.controller.labels.nickname_vm(mod),
        translator=rig.translator,
        icons=rig.window.icons,
        parent=rig.window,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_the_dialog_starts_from_the_default_name_selected(rig, qtbot):
    dialog = make_dialog(rig, qtbot)
    assert dialog.edit.text() == default_name(rig)
    assert dialog.edit.selectedText() == default_name(rig)
    assert_no_raw_keys(dialog)


def test_the_dialog_starts_from_the_saved_nickname(rig, qtbot):
    rig.controller.set_nickname(MOD, "Fancy Name")
    dialog = make_dialog(rig, qtbot)
    assert dialog.edit.text() == "Fancy Name"


def test_enter_accepts_and_the_text_is_collapsed(rig, qtbot):
    dialog = make_dialog(rig, qtbot)
    dialog.edit.setText("  Fancy    Name ")
    assert dialog.save_button.isDefault()
    QTest.keyClick(dialog.edit, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.text() == "Fancy Name"


def test_cancel_and_escape_reject(rig, qtbot):
    dialog = make_dialog(rig, qtbot)
    dialog.cancel_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    again = make_dialog(rig, qtbot)
    QTest.keyClick(again, Qt.Key.Key_Escape)
    assert again.result() == QDialog.DialogCode.Rejected


@pytest.mark.parametrize("language", ["es_ES", "pt_PT", "zh_CN"])
def test_the_dialog_follows_the_language(rig, qtbot, language):
    dialog = make_dialog(rig, qtbot)
    result = follow_language(dialog, rig.translator, language)
    assert result.changed >= 3, "title, prompt, save and cancel are translated base keys"
    assert dialog.edit.text() == default_name(rig), "the typed text is the user's, never translated"


# ---------------------------------------------------------------------------- the action


def test_the_action_opens_the_dialog_for_the_single_selected_mod(rig):
    rig.controller.select([MOD])
    dialog_cls = load_attr("src.ui.dialogs.nickname_dialog", "NicknameDialog")

    def script(dialog):
        assert dialog.edit.text() == default_name(rig)
        dialog.edit.setText("Window Nick")
        dialog.save_button.click()

    rig.driver.on(dialog_cls, script)
    action_for(rig.window, "nickname").trigger()
    assert rig.driver.names() == ["NicknameDialog"]
    assert title(rig) == "Window Nick"
    assert rig.flush().nicknames[MOD] == "Window Nick"


def test_cancelling_the_dialog_keeps_the_nickname(rig):
    rig.controller.select([MOD])
    rig.driver.on("NicknameDialog", lambda d: (d.edit.setText("Nope"), d.cancel_button.click()))
    action_for(rig.window, "nickname").trigger()
    assert title(rig) == default_name(rig)
    assert nicknames_written(rig) == []


def test_the_action_needs_exactly_one_mod(rig):
    action = action_for(rig.window, "nickname")
    rig.controller.select([])
    assert not action.isEnabled()
    rig.controller.select([MOD, OTHER])
    assert not action.isEnabled()
    rig.controller.select([MOD])
    assert action.isEnabled()


def test_asking_with_two_selected_mods_warns_instead_of_opening_a_dialog(rig):
    manager = rig.window.findChild(load_attr("src.ui.widgets.manage_actions", "ManageDialogs"))
    rig.controller.select([MOD, OTHER])
    manager.open_nickname()
    assert rig.driver.opened == []
    assert rig.messages.only("select_one_mod_to_nickname").level == "warning"
    assert nicknames_written(rig) == []
