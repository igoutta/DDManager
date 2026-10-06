"""P18: Apply order to local mod folders: plan, preview, rename, re-key the state, rescan."""

import pytest
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QListWidget, QTableWidget

from src.core.folder_order import plan_folder_renames
from src.core.ids import ModId, SourceKind
from src.services.errors import RenameFailedError
from tests.ui.m5_support import (
    action_for,
    assert_no_raw_keys,
    construct,
    find_button,
    follow_language,
    load_attr,
    trigger,
)

NICKNAMES = {"chorus_class_mod": "My Chorus", "2248772895": "Workshop Chorus"}
ATTEMPTED = ("chorus_class_mod", "swf_trinkets24_compat", "2248772895")


def types():
    dto = "src.ui.presenters.tools_dto"
    return (
        load_attr(dto, "RenamePreviewVM"),
        load_attr(dto, "RenameRowVM"),
        load_attr("src.ui.dialogs.apply_order_dialog", "ApplyOrderDialog"),
    )


def preview(rows=(), **fields):
    vm_cls, row_cls, _dialog = types()
    return vm_cls(rows=tuple(row_cls(ModId(m), t, o, n) for m, t, o, n in rows), **fields)


def make_dialog(vm, translator, icons, qtbot):
    dialog = construct(types()[2], vm=vm, translator=translator, icons=icons, parent=None)
    qtbot.addWidget(dialog)
    return dialog


@pytest.fixture
def rig(rig_factory):
    return rig_factory(window=True, nicknames=NICKNAMES, attempted=ATTEMPTED)


def planned(rig):
    """The plan core computes for the current order (what the flow must ask the renamer for)."""
    c = rig.controller
    return plan_folder_renames(c.order(), c.mods())


def rekeyed(mapping, rekey):
    return {rekey.get(mod, mod): value for mod, value in mapping.items()}


# ---------------------------------------------------------------------------- the preview dialog


def test_the_preview_lists_every_folder_old_and_new_and_the_count(qtbot, translator, icons):
    rows = [
        ("chorus_class_mod", "My Chorus", "chorus_class_mod", "0001_chorus_class_mod"),
        ("swf_trinkets24_compat", "SWF Trinkets", "swf_trinkets24_compat", "0003_swf_trinkets24"),
    ]
    dialog = make_dialog(preview(rows, skipped_workshop=2), translator, icons, qtbot)
    table = dialog.findChild(QTableWidget)
    cells = [
        [table.item(r, c).text() for c in range(table.columnCount())]
        for r in range(table.rowCount())
    ]
    assert cells == [[title, old, new] for _mod, title, old, new in rows]
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert translator.tr("ui.apply.summary", count=2) in labels
    assert translator.tr("ui.apply.skipped", count=2) in labels


def test_every_text_of_the_preview_is_in_the_catalog(qtbot, translator, icons):
    rows = [("a", "A", "a", "0001_a")]
    assert_no_raw_keys(make_dialog(preview(rows, skipped_workshop=1), translator, icons, qtbot))


def test_warnings_are_listed_and_hidden_when_there_are_none(qtbot, translator, icons):
    dialog = make_dialog(
        preview(warnings=("1 listed mod is not on disk",)), translator, icons, qtbot
    )
    dialog.show()
    qtbot.waitExposed(dialog)
    warnings = dialog.findChild(QListWidget)
    assert [warnings.item(i).text() for i in range(warnings.count())] == [
        "1 listed mod is not on disk"
    ]
    quiet = make_dialog(preview(), translator, icons, qtbot)
    quiet.show()
    qtbot.waitExposed(quiet)
    assert not quiet.findChild(QListWidget).isVisible()


def test_apply_accepts_and_cancel_rejects_and_cancel_is_the_default(qtbot, translator, icons):
    rows = [("a", "A", "a", "0001_a")]
    accepted = make_dialog(preview(rows), translator, icons, qtbot)
    accepted.show()
    qtbot.waitExposed(accepted)
    box = accepted.findChild(QDialogButtonBox)
    roles = {box.buttonRole(b): b for b in box.buttons()}
    assert roles[QDialogButtonBox.ButtonRole.RejectRole].isDefault()
    assert not roles[QDialogButtonBox.ButtonRole.AcceptRole].isDefault()
    roles[QDialogButtonBox.ButtonRole.AcceptRole].click()
    assert accepted.result() == accepted.DialogCode.Accepted
    rejected = make_dialog(preview(rows), translator, icons, qtbot)
    rejected.show()
    find_button(rejected, translator.tr("ui.dialog.cancel")).click()
    assert rejected.result() == rejected.DialogCode.Rejected


@pytest.mark.parametrize("language", ["es_ES", "pt_PT", "zh_CN"])
def test_the_preview_follows_the_language(qtbot, translator, icons, language):
    dialog = make_dialog(preview([("a", "A", "a", "0001_a")]), translator, icons, qtbot)
    assert follow_language(dialog, translator, language).checked >= 3


# ---------------------------------------------------------------------------- the flow


def test_the_renamer_gets_the_plan_core_computes_for_the_current_order(rig):
    expected = planned(rig)
    assert expected.steps, "the canned order has local mods to rename"
    trigger(rig.window, "apply_order")
    renamer = rig.services.renamer
    assert len(renamer.plans) == 1
    assert renamer.plans[0].steps == expected.steps
    assert dict(renamer.plans[0].rekey) == dict(expected.rekey)


def test_the_preview_shows_old_and_new_names_titles_and_skipped_workshop_mods(rig):
    expected = planned(rig)
    titles = {mod: row.title for mod, row in rig.controller.rows().items()}
    trigger(rig.window, "apply_order")
    (vm,) = rig.prompter.objects_of(types()[0])
    assert [(r.mod_id, r.old_name, r.new_name) for r in vm.rows] == [
        (step.mod, step.old_name, step.new_name) for step in expected.steps
    ]
    assert all(r.title == titles[r.mod_id] for r in vm.rows)
    assert vm.count == len(expected.steps)
    workshop = [m for m, i in rig.mods.items() if i.kind is SourceKind.WORKSHOP]
    assert vm.skipped_workshop == len(workshop) == 2


def test_accepting_rekeys_order_enabled_categories_nicknames_and_attempted(rig):
    before = rig.flush()
    expected = planned(rig)
    trigger(rig.window, "apply_order")
    after = rig.flush()
    rekey = expected.rekey
    assert after.order.entries == tuple(rekey.get(m, m) for m in before.order.entries)
    assert after.order.enabled == frozenset(rekey.get(m, m) for m in before.order.enabled)
    assert dict(after.categories) == rekeyed(before.categories, rekey)
    assert dict(after.nicknames) == rekeyed(before.nicknames, rekey)
    assert after.auto_category_attempted == frozenset(
        rekey.get(m, m) for m in before.auto_category_attempted
    ), "StateChanges.unattempted drops the old names: nothing stale lingers"
    raw = after.raw
    assert set(raw["auto_category_attempted"]) == set(after.auto_category_attempted)
    assert set(raw["enabled"]) == set(after.order.entries), "no stale enabled keys either"
    assert all(isinstance(flag, bool) for flag in raw["enabled"].values())
    for old in rekey:
        assert old not in after.categories and old not in raw["categories"]
        assert old not in after.nicknames and old not in raw["nicknames"]


def test_two_folders_that_trade_names_keep_each_others_labels(rig):
    """A swap (``a -> b``, ``b -> a``) must not unassign what it just moved."""
    from src.ui.controller_apply import rekey_order, rekey_pending

    a, b = ModId("chorus_class_mod"), ModId("swf_trinkets24_compat")
    rig.controller.set_category([b], "Trinkets")
    before = rig.flush()
    assert before.nicknames[a] == "My Chorus" and b not in before.nicknames
    assert {a, b} <= before.auto_category_attempted
    session = rig.controller.session
    rekey_pending(session, {a: b, b: a})
    session.order = rekey_order(session.order, {a: b, b: a})
    after = rig.flush()
    assert after.categories.get(b) == before.categories[a]
    assert after.categories.get(a) == before.categories[b] == "Trinkets"
    assert after.nicknames.get(b) == "My Chorus" and a not in after.nicknames
    assert after.auto_category_attempted == before.auto_category_attempted
    assert after.order.entries == tuple({a: b, b: a}.get(m, m) for m in before.order.entries)


def test_nicknames_survive_the_rename(rig):
    trigger(rig.window, "apply_order")
    doc = rig.flush()
    assert doc.nicknames[ModId("0001_chorus_class_mod")] == "My Chorus"
    assert doc.nicknames[ModId("2248772895")] == "Workshop Chorus"  # workshop mods are not renamed
    assert rig.controller.rows()[ModId("0001_chorus_class_mod")].title == "My Chorus"


def test_the_active_order_keeps_its_sequence_and_the_models_follow_the_new_names(rig):
    rig.flush()
    before = list(rig.controller.load_order_model.order())
    expected = planned(rig)
    scans = rig.services.scanner.calls
    trigger(rig.window, "apply_order")
    assert rig.services.scanner.calls > scans, "the folders changed on disk: rescan"
    after = list(rig.controller.load_order_model.order())
    assert after == [expected.rekey.get(ModId(m), ModId(m)) for m in before]
    assert after[0] == "0001_chorus_class_mod"
    assert set(rig.controller.mods()) == set(rig.services.scanner.result.mods)
    assert not rig.controller.session.missing, "nothing is reported missing after a rename"


def test_every_local_folder_is_prefixed_with_its_position_in_the_order(rig):
    trigger(rig.window, "apply_order")
    entries = rig.flush().order.entries
    disk = rig.services.scanner.result.mods
    for position, mod in enumerate(entries, start=1):
        if disk[mod].kind is SourceKind.LOCAL:
            assert mod.startswith(f"{position:04d}_"), (position, mod)
        else:
            assert mod.isdigit(), "workshop folders keep their id"


def test_declining_the_preview_changes_nothing(rig_factory):
    rig = rig_factory(
        window=True, nicknames=NICKNAMES, attempted=ATTEMPTED, answers={"review_rename": False}
    )
    before = rig.flush()
    scans = rig.services.scanner.calls
    trigger(rig.window, "apply_order")
    assert rig.services.renamer.plans == []
    after = rig.flush()
    assert after.order == before.order
    assert dict(after.nicknames) == dict(before.nicknames)
    assert rig.services.scanner.calls == scans


def test_applying_twice_has_nothing_to_do_the_second_time(rig):
    trigger(rig.window, "apply_order")
    rig.flush()
    rig.messages.clear()
    shown = len(rig.prompter.objects_of(types()[0]))
    trigger(rig.window, "apply_order")
    assert len(rig.prompter.objects_of(types()[0])) == shown, "no empty preview"
    assert len(rig.services.renamer.plans) == 1
    assert rig.messages.with_key("ui.notice.apply_nothing"), rig.messages.keys()


def test_a_failed_rename_is_reported_with_the_stuck_folders_and_changes_no_state(rig):
    before = rig.flush()
    stuck = ["D:/mods/__temp__20260501__chorus_class_mod"]
    rig.services.renamer.raise_on_execute = RenameFailedError(
        "Renaming failed: access denied.", rolled_back=False, stuck=stuck
    )
    trigger(rig.window, "apply_order")
    errors = [m for m in rig.messages.log if m.level == "error"]
    assert len(errors) == 1, rig.messages.log
    assert stuck[0] in errors[0].text or stuck[0] in str(errors[0].params)
    after = rig.flush()
    assert after.order == before.order
    assert dict(after.categories) == dict(before.categories)
    assert dict(after.nicknames) == dict(before.nicknames)


def test_a_fully_rolled_back_failure_is_reported_too(rig):
    before = rig.flush()
    rig.services.renamer.raise_on_execute = RenameFailedError(
        "Renaming failed: access denied. Everything was put back.", rolled_back=True, stuck=[]
    )
    trigger(rig.window, "apply_order")
    assert len([m for m in rig.messages.log if m.level == "error"]) == 1
    assert rig.flush().order == before.order


def test_nothing_is_renamed_before_the_first_scan(rig_factory):
    rig = rig_factory(window=True, start=False)
    action = action_for(rig.window, "apply_order")
    if action.isEnabled():
        action.trigger()
    assert rig.services.renamer.plans == []
