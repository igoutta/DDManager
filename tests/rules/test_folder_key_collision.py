"""src/rules/folder_key_collision.py: a mod folder shadowed by a same-key folder elsewhere."""

from pathlib import Path, PurePosixPath

from src.core.ids import ModId
from src.core.validation import Severity
from src.rules import folder_key_collision as rule
from tests.support.factories import (
    LOCAL_ROOT,
    WORKSHOP_ROOT,
    context,
    load_order,
    local_mod,
    mentions,
    only,
    sample_patch_mod,
)

RULE_ID = "core.folder_key_collision"


def test_module_metadata() -> None:
    assert rule.RULE_ID == RULE_ID
    assert rule.DESCRIPTION.strip()


def test_no_shadowed_paths_means_no_findings() -> None:
    ctx = context(load_order("a", "b"), [local_mod("a"), local_mod("b")])
    assert rule.validate(ctx) == []


def test_shadowed_mod_gets_a_warning_naming_the_hidden_copy() -> None:
    hidden = PurePosixPath("D:/other mods/chorus_class_mod")
    info = local_mod("chorus_class_mod", shadowed=(hidden,))
    ctx = context(load_order("chorus_class_mod", "x"), [info, local_mod("x")])
    finding = only(rule.validate(ctx))
    assert finding.rule_id == RULE_ID
    assert finding.severity is Severity.WARNING
    assert finding.mod_ids == (ModId("chorus_class_mod"),)
    assert mentions(finding, "other mods") or mentions(finding, hidden.as_posix())


def test_real_patch_mod_shadowed_in_a_second_root(sample_mods_dir: Path) -> None:
    """modding/crusader_hu_swf_compat installed twice (local root first, Workshop copy ignored)."""
    hidden = WORKSHOP_ROOT / "crusader_hu_swf_compat"
    patch = sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat", shadowed=(hidden,))
    target = local_mod("hu_crusader", title="Heroes Unchained: Crusader")
    ctx = context(load_order("crusader_hu_swf_compat", "hu_crusader"), [patch, target])
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.WARNING
    assert finding.mod_ids == (patch.id,)
    assert mentions(finding, patch.title) or mentions(finding, str(patch.id))
    assert mentions(finding, hidden.as_posix()) or mentions(finding, str(hidden))


def test_one_finding_per_shadowed_mod_even_when_unverified() -> None:
    a = local_mod("a", shadowed=(LOCAL_ROOT / "dup" / "a",))
    b = local_mod("b", shadowed=(LOCAL_ROOT / "dup" / "b", LOCAL_ROOT / "dup2" / "b"))
    ctx = context(load_order("a", "b", "c"), [a, b, local_mod("c")], verified=False)
    findings = rule.validate(ctx)
    assert sorted(f.mod_ids for f in findings) == [(ModId("a"),), (ModId("b"),)]
    assert all(f.severity is Severity.WARNING for f in findings)
