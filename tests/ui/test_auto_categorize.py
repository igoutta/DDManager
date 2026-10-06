"""P22: Auto Categorize (summary, nickname-aware, never reorders) and the silent classify."""

import pytest

from src.core.classify import suggest_category
from src.core.identity import category_memory_keys
from src.core.ids import ModId
from tests.support.factories import local_mod, workshop_mod
from tests.ui.m5_support import action_for

# (key, kwargs) of the mods the scenarios use; classification is title/tag based and offline.
INFOS = {
    "trinket_pack": local_mod("trinket_pack", tags=("trinkets",)),
    "skinny_pack": local_mod("skinny_pack", tags=("skin",)),
    "plain_mod": local_mod("plain_mod"),
    "nick_target": local_mod("nick_target", title="plain_thing"),
    "done_quirks": local_mod("done_quirks", tags=("skin",)),  # would be Skins, is Quirks
    "in_zebra": local_mod("in_zebra", tags=("trinkets",)),  # would be Trinkets, is custom
    "literal_unassigned": local_mod("literal_unassigned", tags=("trinkets",)),
    "3000000001": workshop_mod("3000000001", title="Better Tooltips", tags=("tooltips",)),
}
CATALOG = {ModId(k): v for k, v in INFOS.items()}
NICKNAMES = {"nick_target": "Super Tooltip"}
CATEGORIES = {"done_quirks": "Quirks", "in_zebra": "Zebra Mods", "literal_unassigned": "Unassigned"}
TARGETS = (
    "trinket_pack",
    "skinny_pack",
    "plain_mod",
    "nick_target",
    "literal_unassigned",
    "3000000001",
)


def expected_suggestions():
    out = {}
    for key in TARGETS:
        nickname = NICKNAMES.get(key)
        out[ModId(key)] = suggest_category(INFOS[key], nickname=nickname)
    return out


@pytest.fixture
def rig(rig_factory):
    """Every mod already tried by the silent classifier and left unassigned, one ghost entry."""
    keys = list(INFOS)
    return rig_factory(
        window=True,
        catalog=CATALOG,
        enabled=("trinket_pack", "plain_mod"),
        categories=CATEGORIES,
        nicknames=NICKNAMES,
        attempted=keys,
        custom_categories=("Zebra Mods",),
        extra={
            "order": [*keys, "ghost_mod"],
            "enabled": {**dict.fromkeys(keys, False), "trinket_pack": True, "ghost_mod": True},
        },
    )


def run(rig):
    action_for(rig.window, "auto_categorize").trigger()


# ---------------------------------------------------------------------------- the action


def test_the_scenario_has_known_suggestions():
    suggestions = expected_suggestions()
    assert suggestions[ModId("trinket_pack")] == "Trinkets"
    assert suggestions[ModId("skinny_pack")] == "Skins"
    assert suggestions[ModId("plain_mod")] is None
    assert suggestions[ModId("nick_target")] == "UI", "the nickname decides this one"
    assert suggest_category(INFOS["nick_target"]) is None
    assert suggestions[ModId("3000000001")] == "UI"


def test_it_assigns_every_confident_suggestion_to_the_unassigned_mods(rig):
    run(rig)
    doc = rig.flush()
    want = {mod: cat for mod, cat in expected_suggestions().items() if cat}
    assert {mod: doc.categories[mod] for mod in want} == want
    assert ModId("plain_mod") not in doc.categories, "no confident match: stays unassigned"
    assert rig.controller.rows()[ModId("trinket_pack")].category_label == "Trinkets"


def test_it_leaves_categorized_mods_alone_even_in_custom_categories(rig):
    run(rig)
    doc = rig.flush()
    assert doc.categories[ModId("done_quirks")] == "Quirks"
    assert doc.categories[ModId("in_zebra")] == "Zebra Mods"
    assert ModId("done_quirks") not in set(rig.state.written("attempted")[-1])


def test_a_literal_unassigned_counts_as_unassigned(rig):
    run(rig)
    assert rig.flush().categories[ModId("literal_unassigned")] == "Trinkets"


def test_it_uses_the_nickname(rig):
    run(rig)
    assert rig.flush().categories[ModId("nick_target")] == "UI"


def test_it_includes_mods_the_silent_classifier_already_tried(rig):
    # the fixture marks every mod as attempted; the manual action must not honor that
    assert ModId("skinny_pack") in rig.controller.session.doc.auto_category_attempted
    run(rig)
    assert rig.flush().categories[ModId("skinny_pack")] == "Skins"


def test_every_targeted_mod_is_marked_attempted_and_nothing_else(rig):
    run(rig)
    rig.controller.flush()
    attempted = set(rig.state.written("attempted")[-1])
    assert attempted == {ModId(k) for k in TARGETS}
    assert ModId("ghost_mod") not in attempted
    assert ModId("done_quirks") not in attempted


def test_the_category_memory_gets_every_identity_key_of_each_assigned_mod(rig):
    run(rig)
    doc = rig.flush()
    expected = {}
    for mod, category in expected_suggestions().items():
        if category:
            expected.update(dict.fromkeys(category_memory_keys(CATALOG[mod]), category))
    assert dict(doc.category_memory) == expected
    assert "norm:skinny pack" in doc.category_memory


def test_the_summary_counts_assigned_and_ambiguous(rig):
    run(rig)
    note = rig.messages.only("ui.notice.auto_categorized_review")
    wanted = sum(1 for cat in expected_suggestions().values() if cat)
    assert note.params == {"assigned": wanted, "ambiguous": len(TARGETS) - wanted}
    assert note.level == "info"
    assert note.text, "the notice renders"


def test_without_ambiguous_mods_the_summary_is_the_plain_one(rig_factory):
    rig = rig_factory(
        window=True,
        catalog={ModId("trinket_pack"): INFOS["trinket_pack"]},
        enabled=("trinket_pack",),
        categories={},
        attempted=["trinket_pack"],
    )
    run(rig)
    assert rig.messages.only("ui.notice.auto_categorized").params == {
        "assigned": 1,
        "ambiguous": 0,
    }


def test_it_never_reorders_and_pushes_no_undo_step(rig):
    order = rig.controller.order()
    run(rig)
    rig.controller.flush()
    assert rig.controller.order() == order
    assert rig.controller.undo_stack.count() == 0
    assert all(c.order is None or c.order.entries == order.entries for c in rig.state.saves)


def test_a_second_run_finds_nothing_new_and_assigns_nothing(rig):
    run(rig)
    rig.flush()
    rig.messages.clear()
    run(rig)
    assert rig.messages.only("ui.notice.auto_categorized_review").params["assigned"] == 0


def test_a_missing_mod_is_skipped(rig):
    run(rig)
    assert ModId("ghost_mod") not in rig.flush().categories


def test_with_nothing_loaded_it_only_warns(rig_factory):
    rig = rig_factory(window=True, start=False)
    rig.controller.session.order = type(rig.controller.session.order)((), frozenset())
    run(rig)
    assert rig.messages.only("ui.notice.no_mods_loaded").level == "warning"
    assert rig.state.saves == []


# ---------------------------------------------------------------------------- silent start-up


@pytest.fixture
def fresh(rig_factory):
    """Nothing attempted yet: what a first start-up scan sees."""
    return rig_factory(
        window=True,
        catalog=CATALOG,
        enabled=("plain_mod", "skinny_pack", "trinket_pack"),
        categories={"done_quirks": "Quirks"},
        category_memory={"norm:plain mod": "Enemies"},
    )


def test_the_start_up_classifier_assigns_and_remembers_but_never_reorders(fresh):
    doc = fresh.flush()
    assert doc.categories[ModId("trinket_pack")] == "Trinkets"
    assert doc.categories[ModId("skinny_pack")] == "Skins"
    assert doc.categories[ModId("done_quirks")] == "Quirks"
    assert fresh.controller.order().active() == (
        ModId("plain_mod"),
        ModId("skinny_pack"),
        ModId("trinket_pack"),
    ), "category order would put Trinkets and Skins differently: the start-up never re-sorts"
    assert fresh.controller.undo_stack.count() == 0
    assert doc.category_memory["norm:skinny pack"] == "Skins"


def test_the_remembered_category_wins_over_the_suggestion(fresh):
    assert suggest_category(INFOS["plain_mod"]) is None
    assert fresh.flush().categories[ModId("plain_mod")] == "Enemies"


def test_ambiguous_mods_are_marked_attempted_and_not_tried_again_on_rescan(rig_factory):
    rig = rig_factory(window=True, catalog=CATALOG, enabled=("plain_mod",), categories={})
    doc = rig.flush()
    assert ModId("nick_target") in doc.auto_category_attempted
    assert ModId("nick_target") not in doc.categories
    rig.controller.set_nickname(ModId("nick_target"), "Super Tooltip")
    rig.controller.rescan()
    assert ModId("nick_target") not in rig.flush().categories, "the silent pass never retries"
    run(rig)
    assert rig.flush().categories[ModId("nick_target")] == "UI"
