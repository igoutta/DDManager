"""src/rules/__init__.py: the BUILTIN_RULES registry, and all built-in rules run together through
run_rules over the real patch-mod fixtures."""

from pathlib import Path

from src.core.ids import ModId
from src.core.validation import ModuleRule, Severity, run_rules
from src.rules import BUILTIN_RULES
from tests.support.factories import (
    context,
    load_order,
    local_mod,
    rules_json,
    sample_patch_mod,
    workshop_mod,
)

EXPECTED_IDS = {
    "core.missing_from_disk",
    "core.duplicate_identity",
    "core.multiple_overhauls",
    "core.patch_before_target",
    "core.file_overlap",
    "core.folder_key_collision",
}
SWF_TITLE = "SWF (V0.25) - 2goals, QOL, mermaids, sandwiches..."


def test_registry_is_a_tuple_of_module_rules_with_unique_core_ids() -> None:
    assert isinstance(BUILTIN_RULES, tuple)
    assert all(isinstance(r, ModuleRule) for r in BUILTIN_RULES)
    ids = [r.rule_id for r in BUILTIN_RULES]
    assert len(ids) == len(set(ids))
    assert all(rule_id.startswith("core.") for rule_id in ids)
    assert set(ids) >= EXPECTED_IDS
    assert "core.sort_cycle" not in ids  # documented only; emitted by sorting.auto_sort
    assert any(rule_id.startswith("core.declared_") for rule_id in ids)
    assert all(r.description for r in BUILTIN_RULES)


def test_all_rules_over_an_empty_setup_report_nothing() -> None:
    report = run_rules(BUILTIN_RULES, context(load_order(), []))
    assert report.findings == ()


def test_all_rules_over_a_clean_setup_report_nothing_blocking(sample_mods_dir: Path) -> None:
    coach_patch = sample_patch_mod(sample_mods_dir, "better_stage_coach_swf_compat")
    crusader_patch = sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat")
    swf = workshop_mod("1111111", title=SWF_TITLE)
    coach = local_mod("better_stage_coach", title="Better Stage Coach")
    hu = local_mod("hu_crusader", title="Heroes Unchained: Crusader")
    mods = [coach_patch, crusader_patch, swf, coach, hu]
    order = load_order(
        "crusader_hu_swf_compat",
        "better_stage_coach_swf_compat",
        "hu_crusader",
        "better_stage_coach",
        "1111111",
    )
    ctx = context(
        order,
        mods,
        tiers={
            "crusader_hu_swf_compat": "patch",
            "better_stage_coach_swf_compat": "patch",
            "1111111": "overhaul",
            "hu_crusader": "class",
        },
    )
    report = run_rules(BUILTIN_RULES, ctx)
    assert not report.blocking
    assert report.count(Severity.WARNING) == 0
    assert "internal.rule_failed" not in {f.rule_id for f in report.findings}


def test_all_rules_over_a_messy_setup_cover_several_rules(sample_mods_dir: Path) -> None:
    crusader_patch = sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat")
    swf = workshop_mod("1111111", title=SWF_TITLE)
    hu = local_mod("hu_crusader", title="Heroes Unchained: Crusader")
    chorus_ws = workshop_mod("2248772895", title="The Chorus")
    chorus_local = local_mod("chorus_class_mod", title="The Chorus")
    rules = rules_json(
        {
            "local:crusader hu swf compatibility patch": {
                "requires": ["title:superior wayfarer"],
                "incompatible": [{"ref": "key:chorus_class_mod", "reason": "test"}],
            }
        }
    )
    order = load_order(
        "1111111",
        "hu_crusader",
        "crusader_hu_swf_compat",
        "ghost",
        "chorus_class_mod",
        "2248772895",
    )
    ctx = context(
        order,
        [crusader_patch, swf, hu, chorus_ws, chorus_local],
        tiers={"1111111": "overhaul", "hu_crusader": "overhaul"},
        rules=rules,
    )
    report = run_rules(BUILTIN_RULES, ctx)
    seen = {f.rule_id for f in report.findings}
    assert "internal.rule_failed" not in seen
    assert {
        "core.missing_from_disk",
        "core.duplicate_identity",
        "core.multiple_overhauls",
        "core.patch_before_target",
        "core.declared_requires",
        "core.declared_incompatible",
    } <= seen
    assert report.blocking
    assert report.for_mod(ModId("ghost"))
