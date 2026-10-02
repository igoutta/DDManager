"""src/rules/multiple_overhauls.py: several active overhaul-tier mods that are not declared
compatible with each other."""

from pathlib import Path

import pytest

from src.core.ids import ModId
from src.core.load_order import PriorityDirection
from src.core.model import ModInfo
from src.core.validation import DisableMods, Severity
from src.rules import multiple_overhauls as rule
from tests.support.factories import (
    context,
    load_order,
    local_mod,
    only,
    rules_json,
    sample_patch_mod,
    workshop_mod,
)

RULE_ID = "core.multiple_overhauls"
FIRST, LAST = PriorityDirection.FIRST_WINS, PriorityDirection.LAST_WINS
SWF, BR, CC = ModId("1111111"), ModId("black_reliquary"), ModId("cc_overhaul")


def _mods() -> list[ModInfo]:
    return [
        workshop_mod("1111111", title="SWF (V0.25) - 2goals, QOL, mermaids, sandwiches..."),
        local_mod("black_reliquary", title="Black Reliquary"),
        local_mod("cc_overhaul", title="Crimson Court Overhaul"),
        local_mod("tiny_ui", title="Tiny UI Tweak"),
    ]


def test_module_metadata() -> None:
    assert rule.RULE_ID == RULE_ID
    assert rule.DESCRIPTION.strip()


def test_a_single_overhaul_is_fine() -> None:
    ctx = context(
        load_order("1111111", "black_reliquary", "tiny_ui"),
        _mods(),
        tiers={"1111111": "overhaul", "tiny_ui": "ui"},
    )
    assert rule.validate(ctx) == []


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_two_overhauls_warn_and_disable_the_lower_precedence_one(
    direction: PriorityDirection,
) -> None:
    ctx = context(
        load_order("1111111", "tiny_ui", "black_reliquary"),
        _mods(),
        tiers={"1111111": "overhaul", "black_reliquary": "overhaul", "tiny_ui": "ui"},
        direction=direction,
    )
    finding = only(rule.validate(ctx))
    assert finding.rule_id == RULE_ID
    assert finding.severity is Severity.WARNING
    assert set(finding.mod_ids) == {SWF, BR}
    loser = BR if direction is FIRST else SWF
    assert finding.fix == DisableMods(mods=(loser,))


def test_three_overhauls_keep_only_the_highest_precedence() -> None:
    ctx = context(
        load_order("cc_overhaul", "1111111", "black_reliquary"),
        _mods(),
        tiers={"1111111": "overhaul", "black_reliquary": "overhaul", "cc_overhaul": "overhaul"},
        direction=LAST,
    )
    finding = only(rule.validate(ctx))
    assert set(finding.mod_ids) == {SWF, BR, CC}
    assert isinstance(finding.fix, DisableMods)
    assert set(finding.fix.mods) == {CC, SWF}


def test_inactive_overhaul_does_not_count() -> None:
    ctx = context(
        load_order("1111111", "-black_reliquary"),
        _mods(),
        tiers={"1111111": "overhaul", "black_reliquary": "overhaul"},
    )
    assert rule.validate(ctx) == []


def test_declared_compatible_overhauls_are_allowed() -> None:
    rules = rules_json({"steam:1111111": {"compatible_with": ["key:black_reliquary"]}})
    ctx = context(
        load_order("1111111", "black_reliquary"),
        _mods(),
        tiers={"1111111": "overhaul", "black_reliquary": "overhaul"},
        rules=rules,
    )
    assert rule.validate(ctx) == []


def test_a_third_overhaul_outside_the_compatible_pair_still_warns() -> None:
    rules = rules_json({"steam:1111111": {"compatible_with": ["key:black_reliquary"]}})
    ctx = context(
        load_order("1111111", "black_reliquary", "cc_overhaul"),
        _mods(),
        tiers={"1111111": "overhaul", "black_reliquary": "overhaul", "cc_overhaul": "overhaul"},
        rules=rules,
    )
    findings = rule.validate(ctx)
    assert findings, "the undeclared overhaul must be reported"
    assert all(f.severity is Severity.WARNING for f in findings)
    assert CC in {m for f in findings for m in f.mod_ids}
    for finding in findings:
        assert isinstance(finding.fix, DisableMods)
        assert SWF not in finding.fix.mods  # the highest-precedence overhaul is kept


def test_real_patch_mod_between_two_overhauls_is_not_an_overhaul(sample_mods_dir: Path) -> None:
    """modding/crusader_hu_swf_compat (tier patch) sits between SWF and Black Reliquary: the
    finding names the two overhauls only and keeps the highest-precedence one."""
    patch = sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat")
    ctx = context(
        load_order("1111111", "crusader_hu_swf_compat", "black_reliquary"),
        [*_mods(), patch],
        tiers={"1111111": "overhaul", "black_reliquary": "overhaul", patch.id: "patch"},
    )
    finding = only(rule.validate(ctx))
    assert set(finding.mod_ids) == {SWF, BR}
    assert finding.fix == DisableMods(mods=(BR,))


def test_not_capped_when_unverified() -> None:
    ctx = context(
        load_order("1111111", "black_reliquary"),
        _mods(),
        tiers={"1111111": "overhaul", "black_reliquary": "overhaul"},
        verified=False,
    )
    assert only(rule.validate(ctx)).severity is Severity.WARNING
