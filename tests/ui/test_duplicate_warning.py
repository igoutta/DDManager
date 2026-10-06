"""P25: one summary notice for local and Workshop copies of the same mod, after the first scan."""

import pytest

from src.core.findings import Severity
from src.core.ids import ModId
from src.rules.duplicate_identity import RULE_ID
from tests.support.factories import local_mod, workshop_mod

NOTICE = "ui.notice.duplicates"
TITLES = ("Alpha Tweak", "Bravo Tweak", "Charlie Tweak", "Delta Tweak", "Echo Tweak")


def pairs(titles):
    catalog = {}
    for index, title in enumerate(titles, start=1):
        local = local_mod(f"local_{index}", title=title)
        workshop = workshop_mod(f"30000000{index:02d}", title=title)
        catalog[local.id] = local
        catalog[workshop.id] = workshop
    return catalog


def rig_for(rig_factory, catalog, *, enabled=None):
    keys = tuple(str(k) for k in catalog) if enabled is None else enabled
    return rig_factory(window=True, catalog=catalog, enabled=keys, categories={}, start=False)


def group_text(rig, title):
    return rig.translator.tr("ui.notice.duplicates.group", locals=title, workshop=title)


@pytest.fixture
def rig(rig_factory):
    return rig_for(rig_factory, pairs(TITLES[:1]))


def test_a_pair_with_both_copies_enabled_gets_one_warning_after_the_first_scan(rig):
    assert rig.messages.log == [], "nothing before the scan"
    rig.controller.start()
    note = rig.messages.only(NOTICE)
    assert note.level == "warning"
    assert note.params == {"count": 1, "groups": group_text(rig, TITLES[0])}
    assert note.text == rig.translator.tr(NOTICE, count=1, groups=group_text(rig, TITLES[0]))


def test_the_warning_is_shown_only_once(rig):
    rig.controller.start()
    rig.controller.rescan()
    rig.controller.validate()
    rig.controller.disable([ModId("local_1")])
    rig.controller.enable([ModId("local_1")])
    assert len(rig.messages.with_key(NOTICE)) == 1


def test_several_pairs_are_listed_in_name_order_and_counted(rig_factory):
    rig = rig_for(rig_factory, pairs(TITLES[:3]))
    rig.controller.start()
    note = rig.messages.only(NOTICE)
    assert note.params["count"] == 3
    assert note.params["groups"] == "; ".join(group_text(rig, t) for t in TITLES[:3])


def test_a_long_list_is_cut_at_three_pairs_with_the_rest_counted(rig_factory):
    rig = rig_for(rig_factory, pairs(TITLES))
    rig.controller.start()
    note = rig.messages.only(NOTICE)
    more = rig.translator.tr("ui.notice.duplicates.more", count=2)
    assert note.params["count"] == 5
    assert note.params["groups"] == ("; ".join(group_text(rig, t) for t in TITLES[:3]) + " " + more)


def test_the_summary_does_not_replace_the_findings_in_the_health_panel(rig):
    rig.controller.start()
    findings = [f for f in rig.controller.session.findings if f.rule_id == RULE_ID]
    assert [f.severity for f in findings] == [Severity.WARNING]
    assert {str(m) for m in findings[0].mod_ids} == {"local_1", "3000000001"}
    assert any(vm.rule_id == RULE_ID for vm in rig.controller.finding_vms())


def test_a_copy_that_is_not_enabled_is_not_reported(rig_factory):
    catalog = pairs(TITLES[:1])
    rig = rig_for(rig_factory, catalog, enabled=("local_1",))
    rig.controller.start()
    assert rig.messages.with_key(NOTICE) == []


def test_two_local_copies_are_an_error_finding_not_a_duplicate_notice(rig_factory):
    first = local_mod("copy_one", title="Same Title")
    second = local_mod("copy_two", title="Same Title")
    rig = rig_for(rig_factory, {first.id: first, second.id: second})
    rig.controller.start()
    assert rig.messages.with_key(NOTICE) == []
    assert any(f.severity is Severity.ERROR for f in rig.controller.session.findings)


def test_unrelated_mods_produce_no_notice(rig_factory):
    catalog = {
        mod.id: mod
        for mod in (local_mod("one_mod", title="One Mod"), workshop_mod("3000000009", title="Two"))
    }
    rig = rig_for(rig_factory, catalog)
    rig.controller.start()
    assert rig.messages.with_key(NOTICE) == []


def test_the_window_shows_the_notice_in_its_status_bar(rig):
    rig.controller.start()
    note = rig.messages.only(NOTICE)
    assert rig.window.status_bar.currentMessage() == note.text
    assert "Alpha Tweak" in note.text
