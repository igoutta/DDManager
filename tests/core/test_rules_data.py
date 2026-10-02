"""src/core/rules_data.py: the community rules file ("ddmanager.rules" v1), merging, ref matching
and resolution into precedence edges (contract: m2_contract.md, cluster C)."""

import json
import random
from collections.abc import Mapping

import pytest

from src.core.ids import ModId
from src.core.rules_data import (
    EMPTY_RULES,
    ModRule,
    OverlapPolicy,
    ResolvedRules,
    RulesData,
    dump_rules_data,
    match_ref,
    merge_rules,
    parse_rules_data,
    resolve_rules,
)
from src.core.validation import Finding, Severity
from tests.support.factories import (
    DEFAULT_IGNORE,
    DEFAULT_MERGE,
    local_mod,
    rules_json,
    with_severity,
    workshop_mod,
)

EXAMPLE = """{
  "format": "ddmanager.rules", "format_version": 1,
  "overlap": { "ignore": ["project.xml", "modfiles.txt", "preview_icon.*", "*.bak"],
               "merge": ["localization/*.string_table.xml"] },
  "mods": {
    "steam:2248772895": { "title_hint": "The Chorus", "tier": "class" },
    "local:crusader hu swf compat": {
      "tier": "patch",
      "requires": ["title:superior wayfarer"],
      "load_after": ["title:superior wayfarer"],
      "incompatible": [{ "ref": "steam:1", "reason": "both replace heroes/crusader" }]
    }
  }
}
"""

PATCH_KEY = "crusader_hu_swf_compat"
PATCH_TITLE = "Crusader HU + SWF Compatibility Patch"


def _rule(ref: str, **fields: object) -> ModRule:
    base: dict[str, object] = {
        "ref": ref,
        "tier": None,
        "requires": (),
        "load_after": (),
        "patch_for": (),
        "incompatible": (),
        "compatible_with": (),
        "title_hint": "",
    }
    base.update(fields)
    return ModRule(**base)


def _assert_rules_findings(findings: list[Finding]) -> None:
    assert isinstance(findings, list)
    for item in findings:
        assert isinstance(item, Finding)
        assert item.rule_id.startswith("rules."), item


# ------------------------------------------------------------------ parsing


def test_parses_the_contract_example_document() -> None:
    data, findings = parse_rules_data(EXAMPLE)
    assert findings == []
    assert data.overlap_ignore == DEFAULT_IGNORE
    assert data.overlap_merge == DEFAULT_MERGE
    by_ref = {rule.ref: rule for rule in data.mods}
    assert set(by_ref) == {"steam:2248772895", "local:crusader hu swf compat"}
    assert by_ref["steam:2248772895"] == _rule(
        "steam:2248772895", tier="class", title_hint="The Chorus"
    )
    assert by_ref["local:crusader hu swf compat"] == _rule(
        "local:crusader hu swf compat",
        tier="patch",
        requires=("title:superior wayfarer",),
        load_after=("title:superior wayfarer",),
        incompatible=(("steam:1", "both replace heroes/crusader"),),
    )


def test_empty_rules_constant() -> None:
    assert RulesData(mods=(), overlap_ignore=(), overlap_merge=()) == EMPTY_RULES


def test_minimal_document_without_mods_or_overlap_is_valid() -> None:
    data, findings = parse_rules_data('{"format": "ddmanager.rules", "format_version": 1}')
    assert with_severity(findings, Severity.ERROR) == []
    assert data.mods == ()
    assert (data.overlap_ignore, data.overlap_merge) == ((), ())


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json at all",
        "[]",
        "null",
        "42",
        '"ddmanager.rules"',
        '{"format": "something.else", "format_version": 1, "mods": {}}',
        '{"format_version": 1, "mods": {}}',
        '{"format": "ddmanager.rules", "format_version": 2, "mods": {}}',
        '{"format": "ddmanager.rules", "format_version": 99}',
    ],
    ids=[
        "empty",
        "garbage",
        "list_root",
        "null_root",
        "number_root",
        "string_root",
        "wrong_format",
        "missing_format",
        "newer_version",
        "much_newer_version",
    ],
)
def test_unusable_documents_yield_empty_rules_and_an_error(text: str) -> None:
    data, findings = parse_rules_data(text)
    assert data == EMPTY_RULES
    _assert_rules_findings(findings)
    assert with_severity(findings, Severity.ERROR), findings


def test_unknown_top_level_field_is_a_warning_and_the_rest_still_parses() -> None:
    data, findings = parse_rules_data(
        rules_json({"steam:1": {"tier": "ui"}}, extra={"unexpected": {"a": 1}})
    )
    _assert_rules_findings(findings)
    assert with_severity(findings, Severity.ERROR) == []
    assert with_severity(findings, Severity.WARNING), findings
    assert [rule.ref for rule in data.mods] == ["steam:1"]


def test_unknown_mod_field_skips_that_entry_with_a_warning() -> None:
    data, findings = parse_rules_data(
        rules_json({"steam:1": {"tier": "ui", "bogus": 1}, "steam:2": {"tier": "ui"}})
    )
    _assert_rules_findings(findings)
    assert with_severity(findings, Severity.ERROR) == []
    assert len(with_severity(findings, Severity.WARNING)) == 1
    assert [rule.ref for rule in data.mods] == ["steam:2"]


@pytest.mark.parametrize(
    "ref", ["bogus:1", "steam", "", "2248772895", "steam:", "title:", "local:"]
)
def test_bad_entry_ref_skips_that_entry_with_a_warning(ref: str) -> None:
    data, findings = parse_rules_data(rules_json({ref: {"tier": "ui"}, "steam:2": {}}))
    _assert_rules_findings(findings)
    assert with_severity(findings, Severity.ERROR) == []
    assert with_severity(findings, Severity.WARNING), findings
    assert [rule.ref for rule in data.mods] == ["steam:2"]


def test_bad_ref_inside_a_relation_list_skips_the_entry() -> None:
    data, findings = parse_rules_data(rules_json({"steam:1": {"requires": ["bogus:2"]}}))
    assert with_severity(findings, Severity.WARNING), findings
    assert data.mods == ()


def test_key_refs_are_accepted_only_when_allowed() -> None:
    text = rules_json({"key:my_folder": {"tier": "patch"}, "steam:1": {"patch_for": ["key:x"]}})
    allowed, allowed_findings = parse_rules_data(text)
    assert allowed_findings == []
    assert {rule.ref for rule in allowed.mods} == {"key:my_folder", "steam:1"}

    restricted, findings = parse_rules_data(text, allow_key_refs=False)
    _assert_rules_findings(findings)
    assert with_severity(findings, Severity.WARNING), findings
    assert restricted.mods == ()


def test_all_relation_fields_round_trip_through_parse() -> None:
    text = rules_json(
        {
            "title:foo bar": {
                "tier": "class_patch",
                "requires": ["steam:1", "local:baz"],
                "load_after": ["steam:1"],
                "patch_for": ["title:quux"],
                "incompatible": [
                    {"ref": "steam:7", "reason": "same hero"},
                    {"ref": "local:other", "reason": ""},
                ],
                "compatible_with": ["steam:8"],
                "title_hint": "Foo Bar",
            }
        },
        overlap={"ignore": ["*.bak"], "merge": []},
    )
    data, findings = parse_rules_data(text)
    assert findings == []
    assert data == RulesData(
        mods=(
            _rule(
                "title:foo bar",
                tier="class_patch",
                requires=("steam:1", "local:baz"),
                load_after=("steam:1",),
                patch_for=("title:quux",),
                incompatible=(("steam:7", "same hero"), ("local:other", "")),
                compatible_with=("steam:8",),
                title_hint="Foo Bar",
            ),
        ),
        overlap_ignore=("*.bak",),
        overlap_merge=(),
    )


@pytest.mark.parametrize(
    "document",
    [
        {"format": "ddmanager.rules", "format_version": 1, "mods": []},
        {"format": "ddmanager.rules", "format_version": 1, "mods": "steam:1"},
        {"format": "ddmanager.rules", "format_version": 1, "mods": {"steam:1": "patch"}},
        {"format": "ddmanager.rules", "format_version": 1, "mods": {"steam:1": None}},
        {"format": "ddmanager.rules", "format_version": 1, "overlap": "project.xml"},
        {"format": "ddmanager.rules", "format_version": 1, "overlap": {"ignore": "a", "merge": 3}},
        {"format": "ddmanager.rules", "format_version": "1", "mods": {}},
        {"format": "ddmanager.rules", "format_version": None, "mods": {}},
        {"format": "ddmanager.rules", "format_version": 1, "mods": {"steam:1": {"tier": 5}}},
        {"format": "ddmanager.rules", "format_version": 1, "mods": {"steam:1": {"requires": 5}}},
        {
            "format": "ddmanager.rules",
            "format_version": 1,
            "mods": {"steam:1": {"incompatible": ["steam:2", 3, None, {"reason": "x"}]}},
        },
        {"format": "ddmanager.rules", "format_version": 1, "mods": {"steam:1": {"title_hint": 1}}},
    ],
)
def test_wrong_shapes_never_raise(document: Mapping[str, object]) -> None:
    data, findings = parse_rules_data(json.dumps(document))
    assert isinstance(data, RulesData)
    _assert_rules_findings(findings)


# ------------------------------------------------------------------ totality (seeded fuzz)

FIELD_NAMES = (
    "format",
    "format_version",
    "overlap",
    "ignore",
    "merge",
    "mods",
    "tier",
    "requires",
    "load_after",
    "patch_for",
    "incompatible",
    "compatible_with",
    "title_hint",
    "ref",
    "reason",
    "steam:1",
    "local:x y",
    "title:some title",
    "key:folder",
    "bogus:q",
    "ddmanager.rules",
)
RANDOM_STRINGS = (*FIELD_NAMES, "", "x" * 300, "☃", "\ud800")


def _random_json(rng: random.Random, depth: int = 0) -> object:
    kind = rng.randrange(8)
    if depth > 3 or kind == 0:
        return None
    scalars = (
        lambda: rng.random() < 0.5,
        lambda: rng.randint(-5, 5),
        lambda: rng.random() * 100,
        lambda: rng.choice(RANDOM_STRINGS),
    )
    if kind <= 4:
        return scalars[kind - 1]()
    if kind == 5:
        return [_random_json(rng, depth + 1) for _ in range(rng.randrange(4))]
    return {rng.choice(FIELD_NAMES): _random_json(rng, depth + 1) for _ in range(rng.randrange(5))}


def _mutated_example(rng: random.Random) -> object:
    document = json.loads(EXAMPLE)
    for _ in range(rng.randrange(1, 4)):
        target = document
        while isinstance(target, dict) and target and rng.random() < 0.6:
            key = rng.choice(sorted(target))
            if not isinstance(target[key], dict):
                break
            target = target[key]
        if isinstance(target, dict):
            target[rng.choice((*FIELD_NAMES, *target))] = _random_json(rng)
    return document


def test_parse_is_total_over_random_documents() -> None:
    rng = random.Random(0xC0FFEE)
    for _ in range(300):
        document = _mutated_example(rng) if rng.random() < 0.5 else _random_json(rng)
        try:
            text = json.dumps(document, ensure_ascii=False)
        except ValueError:  # lone surrogates cannot be dumped; feed the repr instead
            text = repr(document)
        data, findings = parse_rules_data(text)
        assert isinstance(data, RulesData)
        _assert_rules_findings(findings)


def test_parse_is_total_over_random_text() -> None:
    rng = random.Random(0xBADF00D)
    alphabet = '{}[]":,\n \t\\0123456789abcdefmods_formatversioné中'
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 80)))
        data, findings = parse_rules_data(text)
        assert isinstance(data, RulesData)
        _assert_rules_findings(findings)
    raw = bytes(rng.randrange(256) for _ in range(400)).decode("latin-1")
    data, findings = parse_rules_data(raw)
    assert isinstance(data, RulesData)
    _assert_rules_findings(findings)


# ------------------------------------------------------------------ dump / merge


def test_dump_round_trips_through_parse() -> None:
    data, _ = parse_rules_data(EXAMPLE)
    text = dump_rules_data(data)
    document = json.loads(text)
    assert document["format"] == "ddmanager.rules"
    assert document["format_version"] == 1
    again, findings = parse_rules_data(text)
    assert findings == []
    assert again == data


def test_dump_of_empty_rules_parses_back_to_empty() -> None:
    again, findings = parse_rules_data(dump_rules_data(EMPTY_RULES))
    assert findings == []
    assert again == EMPTY_RULES


def test_dump_keeps_every_relation_field() -> None:
    rule = _rule(
        "steam:5",
        tier="patch",
        requires=("steam:1",),
        load_after=("steam:2",),
        patch_for=("title:base",),
        incompatible=(("steam:3", "why"),),
        compatible_with=("steam:4",),
        title_hint="Five",
    )
    data = RulesData(mods=(rule,), overlap_ignore=("*.bak",), overlap_merge=("localization/*",))
    again, findings = parse_rules_data(dump_rules_data(data))
    assert findings == []
    assert again == data


def test_merge_replaces_entries_wholesale_and_unions_overlap_lists_user_last() -> None:
    default = RulesData(
        mods=(
            _rule("steam:1", tier="ui", title_hint="Default One"),
            _rule("steam:2", tier="class"),
        ),
        overlap_ignore=("a", "b"),
        overlap_merge=("m1",),
    )
    user = RulesData(
        mods=(_rule("steam:1", tier="patch"), _rule("steam:3", title_hint="Three")),
        overlap_ignore=("b", "c"),
        overlap_merge=("m2", "m1"),
    )
    merged = merge_rules(default, user)
    by_ref = {rule.ref: rule for rule in merged.mods}
    assert set(by_ref) == {"steam:1", "steam:2", "steam:3"}
    assert by_ref["steam:1"] == _rule("steam:1", tier="patch")  # wholesale: no title_hint left
    assert by_ref["steam:2"] == _rule("steam:2", tier="class")
    assert by_ref["steam:3"] == _rule("steam:3", title_hint="Three")
    assert merged.overlap_ignore == ("a", "b", "c")
    assert merged.overlap_merge == ("m1", "m2")


def test_merge_with_empty_sides_is_identity() -> None:
    data, _ = parse_rules_data(EXAMPLE)
    assert merge_rules(EMPTY_RULES, data) == data
    assert merge_rules(data, EMPTY_RULES) == data


# ------------------------------------------------------------------ match_ref


def test_match_ref_by_kind() -> None:
    chorus_ws = workshop_mod("2248772895", title="The Chorus")
    chorus_local = local_mod("chorus_class_mod", title="The Chorus")
    patch = local_mod(PATCH_KEY, title=PATCH_TITLE)

    assert match_ref("steam:2248772895", chorus_ws)
    assert not match_ref("steam:2248772895", chorus_local)
    assert not match_ref("steam:1", chorus_ws)

    assert match_ref("local:the chorus", chorus_local)
    assert not match_ref("local:the chorus", chorus_ws)
    assert match_ref("local:crusader hu swf compatibility patch", patch)  # save name normalized
    assert not match_ref("local:crusader hu swf compat", patch)  # folder name is not the save name

    assert match_ref("title:the chorus", chorus_ws)
    assert match_ref("title:the chorus", chorus_local)
    assert match_ref("title:crusader hu swf compatibility patch", patch)
    assert not match_ref("title:chorus", chorus_ws)

    assert match_ref("key:chorus_class_mod", chorus_local)
    assert match_ref("key:2248772895", chorus_ws)
    assert not match_ref("key:chorus_class_mod", chorus_ws)


@pytest.mark.parametrize("ref", ["", "bogus:x", "steam", ":", "steam:", "title:"])
def test_match_ref_never_matches_malformed_refs(ref: str) -> None:
    assert not match_ref(ref, workshop_mod("2248772895", title="The Chorus"))
    assert not match_ref(ref, local_mod("chorus_class_mod", title="The Chorus"))


# ------------------------------------------------------------------ resolve_rules


def _installed() -> dict[ModId, object]:
    mods = [
        local_mod(PATCH_KEY, title=PATCH_TITLE),
        workshop_mod("1111111", title="Superior Wayfarer"),
        local_mod("hu_crusader", title="Heroes Unchained: Crusader"),
        workshop_mod("2248772895", title="The Chorus"),
    ]
    return {info.id: info for info in mods}


def test_resolve_edges_from_load_after_patch_for_and_requires() -> None:
    mods = _installed()
    data, findings = parse_rules_data(
        rules_json(
            {
                f"key:{PATCH_KEY}": {
                    "load_after": ["title:superior wayfarer"],
                    "requires": ["title:superior wayfarer", "steam:999"],
                    "patch_for": ["key:hu_crusader"],
                }
            }
        )
    )
    assert findings == []
    resolved = resolve_rules(data, mods)  # ty: ignore[invalid-argument-type]
    assert isinstance(resolved, ResolvedRules)
    patch, swf, hu = ModId(PATCH_KEY), ModId("1111111"), ModId("hu_crusader")
    assert {(edge.low, edge.high) for edge in resolved.edges} == {(swf, patch), (hu, patch)}
    assert all(isinstance(edge.reason, str) and edge.reason for edge in resolved.edges)
    assert resolved.requires[patch] == ("title:superior wayfarer", "steam:999")
    assert resolved.requires_resolved[patch] == (swf,)
    assert resolved.declares_override(patch, swf)
    assert resolved.declares_override(patch, hu)
    assert not resolved.declares_override(swf, patch)
    assert not resolved.declares_override(patch, ModId("2248772895"))


def test_resolve_requires_edge_alone_makes_the_dependent_win() -> None:
    mods = _installed()
    data, _ = parse_rules_data(rules_json({f"key:{PATCH_KEY}": {"requires": ["key:hu_crusader"]}}))
    resolved = resolve_rules(data, mods)  # ty: ignore[invalid-argument-type]
    assert {(e.low, e.high) for e in resolved.edges} == {(ModId("hu_crusader"), ModId(PATCH_KEY))}


def test_resolve_incompatible_compatible_and_tier_overrides() -> None:
    mods = _installed()
    data, findings = parse_rules_data(
        rules_json(
            {
                f"key:{PATCH_KEY}": {
                    "incompatible": [
                        {"ref": "key:hu_crusader", "reason": "same hero"},
                        {"ref": "steam:404", "reason": "not installed"},
                    ],
                    "compatible_with": ["steam:2248772895"],
                    "tier": "class_patch",
                },
                "steam:2248772895": {"tier": "class"},
                "steam:404": {"tier": "ui"},
            }
        )
    )
    assert findings == []
    resolved = resolve_rules(data, mods)  # ty: ignore[invalid-argument-type]
    patch, hu, chorus = ModId(PATCH_KEY), ModId("hu_crusader"), ModId("2248772895")
    assert {frozenset((a, b)): reason for a, b, reason in resolved.incompatible} == {
        frozenset((patch, hu)): "same hero"
    }
    assert frozenset((patch, chorus)) in resolved.compatible
    assert dict(resolved.tier_overrides) == {patch: "class_patch", chorus: "class"}
    assert resolved.edges == ()


def test_resolve_ignores_rules_for_mods_that_are_not_installed() -> None:
    data, _ = parse_rules_data(
        rules_json({"steam:404": {"load_after": ["steam:2248772895"], "requires": ["steam:1"]}})
    )
    resolved = resolve_rules(data, _installed())  # ty: ignore[invalid-argument-type]
    assert resolved.edges == ()
    assert dict(resolved.requires) == {}
    assert dict(resolved.requires_resolved) == {}


def test_resolve_of_empty_rules() -> None:
    resolved = resolve_rules(EMPTY_RULES, {})
    assert resolved.edges == ()
    assert dict(resolved.requires) == {}
    assert resolved.incompatible == ()
    assert resolved.compatible == frozenset()
    assert dict(resolved.tier_overrides) == {}
    assert resolved.overlap_policy("project.xml") is OverlapPolicy.OVERRIDE
    assert not resolved.declares_override(ModId("a"), ModId("b"))


def test_overlap_policy_uses_fnmatchcase_on_manifest_paths() -> None:
    data, _ = parse_rules_data(EXAMPLE)
    resolved = resolve_rules(data, {})
    assert resolved.overlap_ignore == DEFAULT_IGNORE
    assert resolved.overlap_merge == DEFAULT_MERGE
    assert resolved.overlap_policy("project.xml") is OverlapPolicy.IGNORE
    assert resolved.overlap_policy("modfiles.txt") is OverlapPolicy.IGNORE
    assert resolved.overlap_policy("preview_icon.png") is OverlapPolicy.IGNORE
    assert resolved.overlap_policy("heroes/old.bak") is OverlapPolicy.IGNORE  # * spans "/"
    assert resolved.overlap_policy("localization/x.string_table.xml") is OverlapPolicy.MERGE
    assert resolved.overlap_policy("localization/x.xml") is OverlapPolicy.OVERRIDE
    assert (
        resolved.overlap_policy("heroes/crusader/crusader.info.darkest") is OverlapPolicy.OVERRIDE
    )
    # fnmatch has no directory awareness: a root-only pattern does not match nested paths
    assert resolved.overlap_policy("sub/preview_icon.png") is OverlapPolicy.OVERRIDE


def test_ignore_beats_merge() -> None:
    data = RulesData(
        mods=(),
        overlap_ignore=("localization/*",),
        overlap_merge=("localization/*.string_table.xml",),
    )
    resolved = resolve_rules(data, {})
    assert resolved.overlap_policy("localization/x.string_table.xml") is OverlapPolicy.IGNORE


def test_overlap_policy_enum_values() -> None:
    assert (OverlapPolicy.OVERRIDE, OverlapPolicy.MERGE, OverlapPolicy.IGNORE) == (
        "override",
        "merge",
        "ignore",
    )
