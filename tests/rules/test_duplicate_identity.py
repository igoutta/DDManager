"""src/rules/duplicate_identity.py: (a) one SaveIdentity written twice among the active mods,
(b) local + workshop copies of the same mod (legacy dd2.py:4092-4158 grouping)."""

import random
from collections.abc import Iterable
from pathlib import Path

import pytest

from src.core.ids import ModId, SourceKind
from src.core.load_order import PriorityDirection
from src.core.model import ModInfo
from src.core.validation import DisableMods, Finding, Severity
from src.rules import duplicate_identity as rule
from tests.support.factories import (
    context,
    load_order,
    local_mod,
    only,
    sample_patch_mod,
    with_severity,
    workshop_mod,
)

RULE_ID = "core.duplicate_identity"
FIRST, LAST = PriorityDirection.FIRST_WINS, PriorityDirection.LAST_WINS


def _disabled(finding: Finding) -> set[ModId]:
    assert isinstance(finding.fix, DisableMods), finding
    return set(finding.fix.mods)


def test_module_metadata() -> None:
    assert rule.RULE_ID == RULE_ID
    assert rule.DESCRIPTION.strip()


def test_distinct_identities_yield_nothing() -> None:
    mods = [
        workshop_mod("2248772895", title="The Chorus"),
        local_mod("better_stage_coach", title="Better Stage Coach"),
        local_mod("crusader_hu", title="Heroes Unchained: Crusader"),
    ]
    ctx = context(load_order(*(m.id for m in mods)), mods)
    assert rule.validate(ctx) == []


# ------------------------------------------------------------------ (a) identical SaveIdentity


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_same_identity_twice_is_an_error_keeping_the_highest_precedence_copy(
    direction: PriorityDirection,
) -> None:
    first = workshop_mod("1111111", title="SWF")
    second = workshop_mod("1111111_renamed", title="SWF copy", workshop_id="1111111")
    assert first.save_identity == second.save_identity
    ctx = context(
        load_order("1111111", "x", "1111111_renamed"),
        [first, second, local_mod("x")],
        direction=direction,
    )
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.ERROR
    assert set(finding.mod_ids) == {first.id, second.id}
    loser = second.id if direction is FIRST else first.id
    assert _disabled(finding) == {loser}


def test_three_way_identity_clash_disables_all_but_one() -> None:
    mods = [
        local_mod("a_chorus", title="The Chorus"),
        local_mod("b_chorus", title="The Chorus"),
        local_mod("c_chorus", title="The Chorus"),
    ]
    ctx = context(load_order("c_chorus", "a_chorus", "b_chorus"), mods, direction=LAST)
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.ERROR
    assert set(finding.mod_ids) == {m.id for m in mods}
    assert _disabled(finding) == {ModId("c_chorus"), ModId("a_chorus")}


def test_inactive_duplicate_does_not_count() -> None:
    mods = [local_mod("a_chorus", title="The Chorus"), local_mod("b_chorus", title="The Chorus")]
    ctx = context(load_order("a_chorus", "-b_chorus"), mods)
    assert with_severity(rule.validate(ctx), Severity.ERROR) == []


def test_identity_clash_is_not_capped_when_unverified() -> None:
    mods = [local_mod("a_chorus", title="The Chorus"), local_mod("b_chorus", title="The Chorus")]
    ctx = context(load_order("a_chorus", "b_chorus"), mods, verified=False)
    assert only(rule.validate(ctx)).severity is Severity.ERROR


# ------------------------------------------------------------------ (b) local + workshop copies


def test_real_patch_mod_installed_locally_and_from_the_workshop(sample_mods_dir: Path) -> None:
    """modding/crusader_hu_swf_compat as the local copy plus a Workshop upload with the same
    title: paired through the normalized-title key, the local copy is the one to disable."""
    local = sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat")
    uploaded = workshop_mod("3123456789", title=local.title, files=local.files)
    assert local.save_identity != uploaded.save_identity
    ctx = context(load_order("3123456789", "crusader_hu_swf_compat"), [local, uploaded])
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.WARNING
    assert set(finding.mod_ids) == {local.id, uploaded.id}
    assert _disabled(finding) == {local.id}
    assert with_severity(rule.validate(ctx), Severity.ERROR) == []


def test_local_copy_of_a_workshop_mod_is_a_warning_disabling_the_local() -> None:
    ws = workshop_mod("2248772895", title="The Chorus")
    local = local_mod("chorus_class_mod", title="The Chorus")
    ctx = context(load_order("chorus_class_mod", "2248772895"), [ws, local])
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.WARNING
    assert set(finding.mod_ids) == {ws.id, local.id}
    assert _disabled(finding) == {local.id}


def test_local_copy_matched_by_folder_name_against_the_workshop_title() -> None:
    ws = workshop_mod("2248772895", title="The Chorus")
    local = local_mod("the_chorus", title="Chorus Backup Copy")  # folder key is the title
    ctx = context(load_order("2248772895", "the_chorus"), [ws, local])
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.WARNING
    assert _disabled(finding) == {local.id}


def test_short_or_different_titles_do_not_pair() -> None:
    ws = workshop_mod("2248772895", title="Chorus")
    local = local_mod("chorus_class_mod", title="The Chorus")
    tiny_ws = workshop_mod("3333333", title="Abc")
    tiny_local = local_mod("abc", title="Abc")
    mods = [ws, local, tiny_ws, tiny_local]
    ctx = context(load_order(*(m.id for m in mods)), mods)
    assert rule.validate(ctx) == []


def test_two_workshop_copies_with_the_same_title_are_not_a_local_workshop_pair() -> None:
    mods = [
        workshop_mod("1111111", title="Same Title Here"),
        workshop_mod("2222222", title="Same Title Here"),
    ]
    ctx = context(load_order("1111111", "2222222"), mods)
    assert rule.validate(ctx) == []


def test_pair_needs_both_sides_active() -> None:
    ws = workshop_mod("2248772895", title="The Chorus")
    local = local_mod("chorus_class_mod", title="The Chorus")
    for spec in (("-chorus_class_mod", "2248772895"), ("chorus_class_mod", "-2248772895")):
        assert rule.validate(context(load_order(*spec), [ws, local])) == []


def test_pair_warning_is_not_capped_when_unverified() -> None:
    ws = workshop_mod("2248772895", title="The Chorus")
    local = local_mod("chorus_class_mod", title="The Chorus")
    ctx = context(load_order("chorus_class_mod", "2248772895"), [ws, local], verified=False)
    assert only(rule.validate(ctx)).severity is Severity.WARNING


# ------------------------------------------------------------------ legacy parity (grouping)

TITLES = (
    "The Chorus",
    "Chorus",
    "Better Stage Coach",
    "SWF",
    "Abcd",
    "Heroes Unchained: Crusader",
    "Crusader HU",
    "2248772895",
    "Trinkets 8, 24 Inventory, 10 Quirks",
)
WORKSHOP_KEYS = ("2248772895", "1111111", "9999999", "123", "1111111_renamed", "2248772895_old")
LOCAL_KEYS = (
    "chorus_class_mod",
    "0001_chorus_class_mod",
    "2248772895_copy",
    "better_stage_coach",
    "crusader_hu",
    "abc",
    "1111111",
    "0002_swf",
)


def _workshop_id_of(key: str) -> str:
    """Numeric folder, else a leading >=7-digit part (dd2.py:3968-3985 under the workshop)."""
    if key.isdigit():
        return key
    return next((p for p in key.split("_")[:2] if p.isdigit() and len(p) >= 7), "")


def _random_setup(rng: random.Random) -> tuple[list[ModInfo], dict[str, dict[str, str]]]:
    ws_keys = rng.sample(WORKSHOP_KEYS, rng.randint(1, 3))
    local_keys = rng.sample([k for k in LOCAL_KEYS if k not in ws_keys], rng.randint(1, 4))
    infos: list[ModInfo] = []
    metadata: dict[str, dict[str, str]] = {}
    for key in ws_keys:
        title = rng.choice(TITLES)
        wid = _workshop_id_of(key)
        infos.append(workshop_mod(key, title=title, workshop_id=wid))
        metadata[key] = {"published_file_id": wid, "title": title, "save_name": wid or title}
    for key in local_keys:
        title = rng.choice(TITLES)
        infos.append(local_mod(key, title=title))
        metadata[key] = {"published_file_id": "", "title": title, "save_name": title}
    rng.shuffle(infos)
    return infos, metadata


def _legacy_groups(
    dd2: object, metadata: dict[str, dict[str, str]], workshop: Iterable[str]
) -> set[tuple[frozenset[str], frozenset[str]]]:
    """``ModManager.detect_local_workshop_duplicates`` on a bare instance (no Tk, no disk).

    The method reads ``self.state["metadata"]`` through ``duplicate_detection_keys`` and calls
    ``self.mod_is_workshop`` / ``self.sort_name``; both would hit the filesystem, so they are
    shadowed by instance attributes.
    """
    workshop_keys = set(workshop)
    manager = object.__new__(dd2.ModManager)  # ty: ignore[unresolved-attribute]
    manager.state = {"metadata": metadata, "nicknames": {}, "mod_paths": {}}
    manager.mod_is_workshop = lambda mod: mod in workshop_keys
    manager.sort_name = lambda mod: mod.lower()
    groups = manager.detect_local_workshop_duplicates(list(metadata))
    return {(frozenset(g["locals"]), frozenset(g["workshop"])) for g in groups}


@pytest.mark.legacy
def test_local_workshop_pairs_match_legacy_detect_local_workshop_duplicates(legacy) -> None:
    dd2 = legacy.module("dd2")
    rng = random.Random(0x5EED_D0B1)
    for _ in range(80):
        infos, metadata = _random_setup(rng)
        workshop = {m.id for m in infos if m.kind is SourceKind.WORKSHOP}
        expected = _legacy_groups(dd2, metadata, workshop)
        ctx = context(load_order(*(m.id for m in infos)), infos)
        warnings = with_severity(rule.validate(ctx), Severity.WARNING)
        got = {
            (frozenset(_disabled(f)), frozenset(set(f.mod_ids) - _disabled(f))) for f in warnings
        }
        assert got == expected, metadata
