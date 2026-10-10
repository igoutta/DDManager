"""P29: Profile Manager > Import accepts a 0.2 ``dd_mod_loadout.json`` (order, then extras)."""

import json

import pytest

from src.core.ids import ModId
from src.core.loadorder_file import parse_loadout_v02, resolve_document
from tests.ui.m5_support import construct, load_attr

LOADOUT = {
    "mods_path": "C:/Games/Darkest Dungeon/mods",
    "order": [
        "swf_trinkets24_compat",
        "chorus_class_mod",
        "crusader_hu_swf_compat",
        "ghost_not_installed",
        "chorus_class_mod_testdrop",
    ],
    "enabled": {
        "swf_trinkets24_compat": True,
        "chorus_class_mod": True,
        "crusader_hu_swf_compat": False,
        "ghost_not_installed": True,
        "chorus_class_mod_testdrop": True,
    },
    "nicknames": {
        "chorus_class_mod": " Old   Chorus ",
        "crusader_hu_swf_compat": "   ",
        "ghost_not_installed": "Ghost",
    },
    "categories": {
        "chorus_class_mod": "Class",
        "swf_trinkets24_compat": "Trinkets",
        "crusader_hu_swf_compat": "Unassigned",
        "ghost_not_installed": "UI",
    },
    "category_memory": {"old remembered key": "Quirks"},
}


@pytest.fixture
def loadout_file(tmp_path):
    path = tmp_path / "dd_mod_loadout.json"
    path.write_text(json.dumps(LOADOUT, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def rig(rig_factory, fake_services):
    return rig_factory(window=True, attempted=list(fake_services.catalog))


def import_through_the_manager(rig, qtbot, path):
    """Profile Manager > Load-order profiles > Import..., choosing ``path`` in the file dialog."""
    dialog = construct(
        load_attr("src.ui.dialogs.profile_manager_dialog", "ProfileManagerDialog"),
        port=rig.controller.profiles,
        translator=rig.translator,
        icons=rig.window.icons,
        parent=rig.window,
    )
    qtbot.addWidget(dialog)
    rig.prompts.files.append(str(path))
    dialog.profiles_tab.buttons["import"].click()
    return dialog


def expected_result(rig):
    doc, extras, findings = parse_loadout_v02(LOADOUT)
    assert not findings
    assert doc is not None
    return resolve_document(doc, rig.controller.mods(), rig.controller.order()), extras


# ---------------------------------------------------------------------------- the order


def test_the_order_is_previewed_and_adopted_as_one_undoable_change(rig, qtbot, loadout_file):
    before = rig.controller.order()
    result, _extras = expected_result(rig)
    import_through_the_manager(rig, qtbot, loadout_file)
    (args, _kwargs) = rig.prompter.calls_named("review_order_change")[-1]
    assert args[1] == "ui.title.import_loadout"
    assert [str(row.mod_id) for row in args[0].rows if row.new_rank is not None] == [
        str(m) for m in result.order.active()
    ]
    assert rig.controller.order() == result.order
    assert rig.controller.undo_stack.count() == 1
    rig.controller.undo()
    assert rig.controller.order() == before


def test_the_active_mods_follow_the_file_and_disabled_or_unknown_ones_do_not_count(
    rig, qtbot, loadout_file
):
    import_through_the_manager(rig, qtbot, loadout_file)
    active = [str(m) for m in rig.controller.order().active()]
    assert active[:3] == ["swf_trinkets24_compat", "chorus_class_mod", "chorus_class_mod_testdrop"]
    assert "crusader_hu_swf_compat" not in active, "disabled in the loadout"
    assert "ghost_not_installed" not in rig.controller.order().entries


def test_entries_that_match_no_installed_mod_are_counted_in_a_warning(rig, qtbot, loadout_file):
    result, _extras = expected_result(rig)
    import_through_the_manager(rig, qtbot, loadout_file)
    note = rig.messages.only("ui.notice.import_unmatched")
    assert note.level == "warning"
    assert note.params == {"count": len(result.unresolved)} == {"count": 1}


# ---------------------------------------------------------------------------- the extras


def test_nicknames_categories_and_memory_are_applied_after_the_preview(rig, qtbot, loadout_file):
    import_through_the_manager(rig, qtbot, loadout_file)
    doc = rig.flush()
    assert dict(doc.nicknames) == {ModId("chorus_class_mod"): "Old Chorus"}
    assert doc.categories[ModId("chorus_class_mod")] == "Class"
    assert doc.categories[ModId("swf_trinkets24_compat")] == "Trinkets"
    assert doc.category_memory["old remembered key"] == "Quirks"
    assert rig.controller.rows()[ModId("chorus_class_mod")].title == "Old Chorus"


def test_extras_of_unknown_mods_and_pseudo_categories_are_ignored(rig, qtbot, loadout_file):
    import_through_the_manager(rig, qtbot, loadout_file)
    doc = rig.flush()
    assert ModId("ghost_not_installed") not in doc.nicknames
    assert ModId("ghost_not_installed") not in doc.categories
    assert ModId("crusader_hu_swf_compat") not in doc.nicknames, "a blank nickname is skipped"
    assert doc.categories.get(ModId("crusader_hu_swf_compat")) != "Unassigned"


def test_the_summary_counts_what_was_applied(rig, qtbot, loadout_file):
    import_through_the_manager(rig, qtbot, loadout_file)
    note = rig.messages.only("ui.notice.loadout_imported")
    assert note.params == {"categories": 2, "nicknames": 1}


def test_the_nicknames_reach_the_state_file_as_one_delta(rig, qtbot, loadout_file):
    import_through_the_manager(rig, qtbot, loadout_file)
    rig.controller.flush()
    assert rig.state.written("nicknames") == [{ModId("chorus_class_mod"): "Old Chorus"}]
    assert rig.state.written("order")[-1] == rig.controller.order()


# ---------------------------------------------------------------------------- declined / odd


def test_declining_the_preview_applies_nothing_at_all(rig_factory, fake_services, qtbot, tmp_path):
    rig = rig_factory(
        window=True,
        attempted=list(fake_services.catalog),
        answers={"review_order_change": False},
    )
    path = tmp_path / "dd_mod_loadout.json"
    path.write_text(json.dumps(LOADOUT), encoding="utf-8")
    before_order = rig.controller.order()
    before = rig.flush()
    import_through_the_manager(rig, qtbot, path)
    assert rig.controller.order() == before_order
    assert rig.controller.undo_stack.count() == 0
    after = rig.flush()
    assert dict(after.nicknames) == dict(before.nicknames)
    assert dict(after.categories) == dict(before.categories)
    assert "old remembered key" not in after.category_memory
    assert rig.messages.with_key("ui.notice.loadout_imported") == []


def test_a_loadout_equal_to_the_current_order_skips_the_preview_but_applies_the_extras(
    rig, qtbot, tmp_path
):
    current = rig.controller.order()
    same = {
        "order": [str(m) for m in current.entries],
        "enabled": {str(m): current.is_enabled(m) for m in current.entries},
        "nicknames": {"chorus_class_mod": "Same Order"},
    }
    path = tmp_path / "dd_mod_loadout.json"
    path.write_text(json.dumps(same), encoding="utf-8")
    import_through_the_manager(rig, qtbot, path)
    assert rig.prompter.calls_named("review_order_change") == []
    assert rig.controller.undo_stack.count() == 0
    assert rig.flush().nicknames[ModId("chorus_class_mod")] == "Same Order"


@pytest.mark.parametrize(
    "text", ['{"order": ["a"]}', '{"enabled": {}}', "[1, 2, 3]", "not json at all"]
)
def test_a_file_that_is_not_a_loadout_is_refused_with_an_error(rig, qtbot, tmp_path, text):
    path = tmp_path / "broken.json"
    path.write_text(text, encoding="utf-8")
    order = rig.controller.order()
    before = rig.flush()
    import_through_the_manager(rig, qtbot, path)
    assert [m.level for m in rig.messages.log] == ["error"]
    assert rig.controller.order() == order
    assert dict(rig.flush().nicknames) == dict(before.nicknames)


def test_the_loadout_is_also_kept_as_a_profile_and_importing_again_replaces_it(
    rig, qtbot, loadout_file
):
    import_through_the_manager(rig, qtbot, loadout_file)
    assert rig.messages.only("ui.notice.profile_saved").params == {"name": "dd_mod_loadout"}
    assert [p.name for p in rig.services.profiles.list()] == ["dd_mod_loadout"]
    rig.controller.undo()
    import_through_the_manager(rig, qtbot, loadout_file)
    assert [p.name for p in rig.services.profiles.list()] == ["dd_mod_loadout"]
    assert not [m for m in rig.messages.log if m.level == "error"]


def test_a_native_profile_file_imports_without_extras(rig, qtbot, tmp_path):
    rig.controller.profiles.save_profile_as("Mine")
    exported = tmp_path / "mine.loadorder.json"
    rig.controller.profiles.export("Mine", exported)
    rig.messages.clear()
    order = rig.controller.order()
    import_through_the_manager(rig, qtbot, exported)
    assert rig.messages.with_key("ui.notice.loadout_imported") == []
    assert rig.controller.order() == order
