"""Never prune: absent mods stay as missing rows until the user forgets them, after a confirm."""

import pytest

from src.core.findings import Severity
from src.core.ids import ModId
from src.rules.missing_from_disk import RULE_ID
from tests.ui.m5_support import action_for

GONE_ENABLED = ModId("crusader_hu_swf_compat")
GONE_DISABLED = ModId("chorus_class_mod_testdrop_v3")
PRESENT = ModId("chorus_class_mod")


@pytest.fixture
def rig(rig_factory):
    """Two mods vanished from disk (one enabled, one not) and the folder was rescanned."""
    rig = rig_factory(window=True, nicknames={GONE_DISABLED: "Gone but kept"})
    catalog = {
        k: v for k, v in rig.services.catalog.items() if k not in {GONE_ENABLED, GONE_DISABLED}
    }
    rig.services.scanner.set_catalog(catalog)
    rig.controller.rescan()
    rig.messages.clear()
    return rig


def test_absent_mods_are_kept_as_missing_rows_never_pruned(rig):
    order = rig.controller.order()
    assert GONE_ENABLED in order.entries
    assert GONE_DISABLED in order.entries
    assert rig.controller.session.missing == {GONE_ENABLED, GONE_DISABLED}
    rows = rig.controller.rows()
    assert rows[GONE_ENABLED].missing and rows[GONE_DISABLED].missing
    assert not rows[PRESENT].missing
    doc = rig.flush()
    assert GONE_ENABLED in doc.order.entries, "the file keeps them too"
    assert doc.nicknames[GONE_DISABLED] == "Gone but kept", "their nicknames and categories stay"


def test_an_enabled_missing_mod_is_an_error_a_disabled_one_is_only_info(rig):
    found = {
        mod: f.severity
        for f in rig.controller.session.findings
        if f.rule_id == RULE_ID
        for mod in f.mod_ids
    }
    assert found == {GONE_ENABLED: Severity.ERROR, GONE_DISABLED: Severity.INFO}


def test_forgetting_asks_first_and_names_how_many(rig):
    rig.controller.forget_missing([GONE_ENABLED, GONE_DISABLED])
    (args, kwargs) = rig.prompter.calls_named("confirm")[0]
    assert args == ("ui.prompt.forget_missing",)
    assert kwargs == {"count": 2}


def test_confirming_removes_exactly_the_missing_mods_as_one_undoable_change(rig):
    before = rig.controller.order()
    rig.controller.forget_missing([GONE_ENABLED, GONE_DISABLED, PRESENT])
    after = rig.controller.order()
    assert GONE_ENABLED not in after.entries
    assert GONE_DISABLED not in after.entries
    assert PRESENT in after.entries, "a mod that is on disk is never forgotten"
    assert after.entries == tuple(
        m for m in before.entries if m not in {GONE_ENABLED, GONE_DISABLED}
    )
    assert rig.controller.undo_stack.count() == 1
    assert rig.flush().order.entries == after.entries
    rig.controller.undo()
    assert rig.controller.order() == before


def test_declining_forgets_nothing(rig_factory):
    rig = rig_factory(window=True, answers={"confirm": False})
    catalog = {k: v for k, v in rig.services.catalog.items() if k != GONE_DISABLED}
    rig.services.scanner.set_catalog(catalog)
    rig.controller.rescan()
    before = rig.controller.order()
    rig.controller.forget_missing([GONE_DISABLED])
    assert rig.controller.order() == before
    assert rig.controller.undo_stack.count() == 0


def test_mods_on_disk_are_not_even_asked_about(rig):
    rig.controller.forget_missing([PRESENT])
    assert rig.prompter.calls_named("confirm") == []
    assert PRESENT in rig.controller.order().entries


def test_the_menu_action_is_enabled_only_for_a_selection_with_a_missing_mod(rig):
    action = action_for(rig.window, "forget_missing")
    rig.controller.select([PRESENT])
    rig.window.refresh_actions()
    assert not action.isEnabled()
    rig.controller.select([GONE_DISABLED])
    rig.window.refresh_actions()
    assert action.isEnabled()
    rig.window.forget_missing()
    assert GONE_DISABLED not in rig.controller.order().entries
    assert GONE_ENABLED in rig.controller.order().entries, "only the selected mod goes"


def test_a_later_scan_does_not_bring_forgotten_mods_back_as_missing(rig):
    rig.controller.forget_missing([GONE_ENABLED, GONE_DISABLED])
    rig.controller.rescan()
    assert rig.controller.session.missing == frozenset()
    assert GONE_ENABLED not in rig.controller.order().entries
