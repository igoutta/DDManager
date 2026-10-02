"""src/rules/patch_before_target.py: a patch mod that loses a conflict against one of its targets.

Targets come from four sources (contract, cluster C table): ``patch_for`` refs, "Load this after:"
bullets (normalized-title prefix match, >= 5 chars), active mods whose normalized title (>= 5
chars) is a substring of the patch title, and mods sharing at least one OVERRIDE-policy file.
Fixtures: the real ``modding/*_swf_compat`` patch mods.
"""

from pathlib import Path

import pytest

from src.core.ids import ModId
from src.core.load_order import PriorityDirection
from src.core.model import ModInfo
from src.core.validation import MakeWin, Severity, ValidationContext
from src.rules import patch_before_target as rule
from tests.support.factories import (
    context,
    load_order,
    local_mod,
    only,
    rules_json,
    sample_patch_mod,
    workshop_mod,
)

RULE_ID = "core.patch_before_target"
FIRST, LAST = PriorityDirection.FIRST_WINS, PriorityDirection.LAST_WINS

SWF_TITLE = "SWF (V0.25) - 2goals, QOL, mermaids, sandwiches..."
STAGE_COACH = "better_stage_coach_swf_compat"
CRUSADER = "crusader_hu_swf_compat"


@pytest.fixture
def stage_coach_patch(sample_mods_dir: Path) -> ModInfo:
    return sample_patch_mod(sample_mods_dir, STAGE_COACH)


@pytest.fixture
def crusader_patch(sample_mods_dir: Path) -> ModInfo:
    return sample_patch_mod(sample_mods_dir, CRUSADER)


def _swf() -> ModInfo:
    return workshop_mod("1111111", title=SWF_TITLE)


def _assert_make_win(ctx: ValidationContext, patch: ModId, target: ModId) -> None:
    finding = only(rule.validate(ctx))
    assert finding.rule_id == RULE_ID
    assert finding.severity is Severity.WARNING
    assert finding.fix == MakeWin(winner=patch, over=target)
    assert {patch, target} <= set(finding.mod_ids)


def test_module_metadata() -> None:
    assert rule.RULE_ID == RULE_ID
    assert rule.DESCRIPTION.strip()


def test_fixture_facts_are_what_the_rule_relies_on(
    stage_coach_patch: ModInfo, crusader_patch: ModInfo
) -> None:
    assert "Patch" in stage_coach_patch.tags and "Compatibility" in stage_coach_patch.tags
    assert stage_coach_patch.load_after_hints == ("Better Stage Coach", SWF_TITLE)
    assert crusader_patch.load_after_hints == (
        SWF_TITLE,
        "Heroes Unchained: Crusader",
        "Fire Attacks: Crusader Patch (if used)",
    )
    assert "heroes/crusader/crusader.info.darkest" in crusader_patch.files


# ------------------------------------------------------------------ hint targets


def test_patch_losing_to_a_hinted_target_first_wins(stage_coach_patch: ModInfo) -> None:
    coach = local_mod("better_stage_coach", title="Better Stage Coach")
    ctx = context(load_order("better_stage_coach", STAGE_COACH), [coach, stage_coach_patch])
    _assert_make_win(ctx, stage_coach_patch.id, coach.id)


def test_patch_losing_to_a_hinted_target_last_wins(stage_coach_patch: ModInfo) -> None:
    coach = local_mod("better_stage_coach", title="Better Stage Coach")
    ctx = context(
        load_order(STAGE_COACH, "better_stage_coach"), [coach, stage_coach_patch], direction=LAST
    )
    _assert_make_win(ctx, stage_coach_patch.id, coach.id)


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_patch_already_winning_is_silent(
    stage_coach_patch: ModInfo, direction: PriorityDirection
) -> None:
    coach = local_mod("better_stage_coach", title="Better Stage Coach")
    spec = (STAGE_COACH, "better_stage_coach", "1111111")
    if direction is LAST:
        spec = tuple(reversed(spec))
    ctx = context(load_order(*spec), [coach, stage_coach_patch, _swf()], direction=direction)
    assert rule.validate(ctx) == []


def test_each_losing_target_gets_its_own_finding(crusader_patch: ModInfo) -> None:
    hu = local_mod("hu_crusader", title="Heroes Unchained: Crusader")
    ctx = context(load_order("1111111", "hu_crusader", CRUSADER), [_swf(), hu, crusader_patch])
    findings = rule.validate(ctx)
    assert {f.fix for f in findings} == {
        MakeWin(winner=crusader_patch.id, over=ModId("1111111")),
        MakeWin(winner=crusader_patch.id, over=hu.id),
    }
    assert all(f.severity is Severity.WARNING for f in findings)


def test_hint_longer_than_the_mod_title_matches_by_prefix(crusader_patch: ModInfo) -> None:
    fire = local_mod("fire_attacks_crusader", title="Fire Attacks: Crusader Patch")
    ctx = context(load_order("fire_attacks_crusader", CRUSADER), [fire, crusader_patch])
    _assert_make_win(ctx, crusader_patch.id, fire.id)


def test_mod_title_longer_than_the_hint_matches_by_prefix(stage_coach_patch: ModInfo) -> None:
    coach = local_mod("better_stage_coach_v2", title="Better Stage Coach (Updated)")
    ctx = context(load_order("better_stage_coach_v2", STAGE_COACH), [coach, stage_coach_patch])
    _assert_make_win(ctx, stage_coach_patch.id, coach.id)


def test_hint_shorter_than_five_characters_never_matches() -> None:
    patch = local_mod("swf_fix", title="SWF Fix", tags=("Patch",), hints=("SWF",))
    swf = local_mod("swf", title="SWF")
    ctx = context(load_order("swf", "swf_fix"), [swf, patch])
    assert rule.validate(ctx) == []


def test_inactive_target_is_ignored(stage_coach_patch: ModInfo) -> None:
    coach = local_mod("better_stage_coach", title="Better Stage Coach")
    ctx = context(load_order("-better_stage_coach", STAGE_COACH), [coach, stage_coach_patch])
    assert rule.validate(ctx) == []


def test_inactive_patch_is_ignored(stage_coach_patch: ModInfo) -> None:
    coach = local_mod("better_stage_coach", title="Better Stage Coach")
    ctx = context(load_order("better_stage_coach", f"-{STAGE_COACH}"), [coach, stage_coach_patch])
    assert rule.validate(ctx) == []


# ------------------------------------------------------------------ other target sources


def test_patch_for_ref_is_a_target() -> None:
    patch = local_mod("my_patch", title="My Patch", tags=("Patch",))
    base = workshop_mod("7777777", title="Some Base Mod")
    rules = rules_json({"key:my_patch": {"patch_for": ["steam:7777777"]}})
    ctx = context(load_order("7777777", "my_patch"), [base, patch], rules=rules)
    _assert_make_win(ctx, patch.id, base.id)


def test_mod_whose_title_is_inside_the_patch_title_is_a_target(crusader_patch: ModInfo) -> None:
    hu = local_mod("crusader_hu", title="Crusader HU")
    ctx = context(load_order("crusader_hu", CRUSADER), [hu, crusader_patch])
    _assert_make_win(ctx, crusader_patch.id, hu.id)


def test_substring_title_shorter_than_five_characters_is_not_a_target(
    crusader_patch: ModInfo,
) -> None:
    swf = local_mod("swf_short", title="SWF")  # "swf" is in the patch title but too short
    ctx = context(load_order("swf_short", CRUSADER), [swf, crusader_patch])
    assert rule.validate(ctx) == []


def test_mod_sharing_an_override_file_is_a_target(crusader_patch: ModInfo) -> None:
    rework = local_mod(
        "crusader_rework",
        title="Zzz Rework",
        files=("heroes/crusader/crusader.info.darkest",),
    )
    ctx = context(load_order("crusader_rework", CRUSADER), [rework, crusader_patch])
    _assert_make_win(ctx, crusader_patch.id, rework.id)


def test_sharing_only_merge_or_ignore_files_is_not_a_target() -> None:
    patch = local_mod(
        "loc_patch",
        title="Localization Patch",
        tags=("Patch",),
        files=("localization/x.string_table.xml", "preview_icon.png"),
    )
    other = local_mod(
        "zzz_other",
        title="Zzz Other",
        files=("localization/x.string_table.xml", "preview_icon.png"),
    )
    ctx = context(load_order("zzz_other", "loc_patch"), [other, patch])
    assert rule.validate(ctx) == []


# ------------------------------------------------------------------ patch detection


def test_plain_mod_sharing_a_file_is_not_a_patch() -> None:
    a = local_mod("alpha", title="Alpha Rework", files=("heroes/x/x.info.darkest",))
    b = local_mod("beta", title="Beta Rework", files=("heroes/x/x.info.darkest",))
    ctx = context(load_order("alpha", "beta"), [a, b])
    assert rule.validate(ctx) == []


@pytest.mark.parametrize("tier_id", ["patch", "class_patch"])
def test_patch_tier_alone_marks_a_patch(tier_id: str) -> None:
    patch = local_mod("quiet", title="Quiet Mod", files=("heroes/x/x.info.darkest",))
    base = local_mod("base", title="Base Mod", files=("heroes/x/x.info.darkest",))
    ctx = context(load_order("base", "quiet"), [base, patch], tiers={"quiet": tier_id})
    _assert_make_win(ctx, patch.id, base.id)


@pytest.mark.parametrize("tag", ["Patch", "compatibility", "Class Tweaks"])
def test_patch_tags_mark_a_patch_case_insensitively(tag: str) -> None:
    patch = local_mod("quiet", title="Quiet Mod", tags=(tag,), files=("heroes/x/x.info.darkest",))
    base = local_mod("base", title="Base Mod", files=("heroes/x/x.info.darkest",))
    ctx = context(load_order("base", "quiet"), [base, patch])
    _assert_make_win(ctx, patch.id, base.id)


@pytest.mark.parametrize(
    "title",
    [
        "Crusader Patch",
        "SWF Compat",
        "SWF Compatibility",
        "Chorus Fix",
        "Chorus Fixes",
        "Stage Coach Addon",
        "Stage Coach Add-on",
        "Trinket Tweak",
        "Trinket Tweaks",
    ],
)
def test_patch_like_titles_mark_a_patch(title: str) -> None:
    patch = local_mod("quiet", title=title, files=("heroes/x/x.info.darkest",))
    base = local_mod("base", title="Base Mod", files=("heroes/x/x.info.darkest",))
    ctx = context(load_order("base", "quiet"), [base, patch])
    _assert_make_win(ctx, patch.id, base.id)


@pytest.mark.parametrize("title", ["Dispatcher", "Fixated Hero", "Compatriots", "Patchwork Quilt"])
def test_title_words_only_match_at_word_boundaries(title: str) -> None:
    quiet = local_mod("quiet", title=title, files=("heroes/x/x.info.darkest",))
    base = local_mod("base", title="Base Mod", files=("heroes/x/x.info.darkest",))
    ctx = context(load_order("base", "quiet"), [base, quiet])
    assert rule.validate(ctx) == []


# ------------------------------------------------------------------ cap


def test_capped_to_info_while_the_direction_is_unverified(stage_coach_patch: ModInfo) -> None:
    coach = local_mod("better_stage_coach", title="Better Stage Coach")
    ctx = context(
        load_order("better_stage_coach", STAGE_COACH), [coach, stage_coach_patch], verified=False
    )
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.INFO
    assert finding.fix == MakeWin(winner=stage_coach_patch.id, over=coach.id)
