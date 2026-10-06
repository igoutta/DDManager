"""P17: Generate Save Code shows the ``applied_ugcs_1_0`` block and copies it to the clipboard."""

import json

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QPlainTextEdit

from src.core.ids import ModId, SaveIdentity
from src.core.load_order import MoveOp
from src.core.saves.applied_text import render_applied_text
from tests.support.dson_builder import LOCAL, STEAM
from tests.support.identities import identities
from tests.ui.conftest import ENABLED
from tests.ui.m5_support import (
    action_for,
    assert_no_raw_keys,
    construct,
    find_button,
    follow_language,
    load_attr,
    tool_dialog,
    trigger,
)

ENTRIES = identities([("1234567890", STEAM), ("Local Mod", LOCAL), ("42", STEAM)])
BACKSLASH_NAME = 'He said "hi" \\ done'


def types():
    vm_cls = load_attr("src.ui.presenters.tools_dto", "SaveCodeVM")
    dialog_cls = load_attr("src.ui.dialogs.save_code_dialog", "SaveCodeDialog")
    return vm_cls, dialog_cls


def dialog_for(text, count, translator, icons, qtbot):
    vm_cls, dialog_cls = types()
    dialog = construct(
        dialog_cls,
        vm=vm_cls(text=text, count=count),
        translator=translator,
        icons=icons,
        parent=None,
    )
    qtbot.addWidget(dialog)
    return dialog


def test_the_text_is_shown_verbatim_and_read_only(qtbot, translator, icons):
    text = render_applied_text(ENTRIES)
    dialog = dialog_for(text, len(ENTRIES), translator, icons, qtbot)
    box = dialog.findChild(QPlainTextEdit)
    assert box is not None
    assert box.toPlainText() == text
    assert box.isReadOnly()
    assert box.toPlainText().splitlines()[0] == '        "applied_ugcs_1_0" : {'
    assert box.toPlainText().endswith("        },")


def test_every_text_of_the_dialog_is_in_the_catalog(qtbot, translator, icons):
    assert_no_raw_keys(dialog_for(render_applied_text(ENTRIES), 3, translator, icons, qtbot))


def test_copy_puts_the_exact_text_on_the_clipboard(qtbot, translator, icons):
    text = render_applied_text(ENTRIES)
    dialog = dialog_for(text, len(ENTRIES), translator, icons, qtbot)
    QGuiApplication.clipboard().setText("stale")
    dialog.show()
    qtbot.waitExposed(dialog)
    find_button(dialog, translator.tr("ui.savecode.copy")).click()
    assert QGuiApplication.clipboard().text() == text


def test_copied_text_is_valid_json_once_wrapped_even_with_quotes_and_cjk(qtbot, translator, icons):
    tricky = [SaveIdentity(BACKSLASH_NAME, LOCAL), SaveIdentity("天国のモッド", LOCAL)]
    dialog = dialog_for(render_applied_text(tricky), len(tricky), translator, icons, qtbot)
    find_button(dialog, translator.tr("ui.savecode.copy")).click()
    copied = QGuiApplication.clipboard().text()
    block = json.loads("{" + copied.rstrip(",") + "}")["applied_ugcs_1_0"]
    assert [block[str(i)]["name"] for i in range(2)] == [e.name for e in tricky]


def test_close_closes_the_dialog(qtbot, translator, icons):
    dialog = dialog_for(render_applied_text(ENTRIES), 3, translator, icons, qtbot)
    dialog.show()
    qtbot.waitExposed(dialog)
    find_button(dialog, translator.tr("ui.dialog.close")).click()
    assert not dialog.isVisible()


def test_the_heading_states_how_many_mods_are_in_the_block(qtbot, translator, icons):
    dialog = dialog_for(render_applied_text(ENTRIES), 3, translator, icons, qtbot)
    labels = {label.text() for label in dialog.findChildren(QLabel)}
    assert translator.tr("ui.savecode.heading", count=3) in labels


def test_the_action_builds_the_block_of_the_enabled_mods_in_load_order(rig_factory):
    rig = rig_factory(window=True)
    vm_cls, dialog_cls = types()
    dialog = tool_dialog(rig, "save_code", dialog_cls, vm_cls)
    expected = [rig.mods[ModId(key)].save_identity for key in ENABLED]
    assert dialog.text.toPlainText() == render_applied_text(expected)


def test_moving_a_mod_changes_the_block_and_disabled_mods_never_appear(rig_factory):
    rig = rig_factory(window=True)
    vm_cls, dialog_cls = types()
    rig.controller.move([ModId(ENABLED[4])], MoveOp.TOP)
    rig.controller.disable([ModId(ENABLED[5])])
    dialog = tool_dialog(rig, "save_code", dialog_cls, vm_cls)
    wanted = [ENABLED[4], *ENABLED[:4]]
    expected = [rig.mods[ModId(key)].save_identity for key in wanted]
    assert dialog.text.toPlainText() == render_applied_text(expected)


def test_nothing_enabled_shows_no_dialog_and_tells_the_user(rig_factory):
    rig = rig_factory(window=True, enabled=())
    action = action_for(rig.window, "save_code")
    if action.isEnabled():
        trigger(rig.window, "save_code")
        assert rig.driver.opened == []
        assert rig.prompter.objects_of(types()[0]) == []
        assert rig.messages.log, "the user must be told there is nothing to generate"
    else:
        assert not action.isEnabled()


@pytest.mark.parametrize("language", ["es_ES", "pt_PT", "zh_CN"])
def test_the_dialog_follows_the_language(qtbot, translator, icons, language):
    dialog = dialog_for(render_applied_text(ENTRIES), 3, translator, icons, qtbot)
    result = follow_language(dialog, translator, language)
    assert result.checked >= 3, "title, heading, copy and close must all be catalog texts"
    assert dialog.text.toPlainText() == render_applied_text(ENTRIES)  # the code never translates
