"""The mod_state.json schema (src/core/legacy_state.py).

The 22 legacy keys come from ``state.py:8-32``; ``legacy_migrate`` ports ``state.py:35-76``
verbatim and ``mod_metadata_is_complete`` ports ``dd2.py:557-573``.  ``parse_state`` is the
tolerant reader (migrate crashes on a non-dict root or badly typed values; the port must not) and
``render_state`` writes the file back with the legacy key semantics, an explicit bool per order
entry (``dd2.py:1754`` reads ``enabled_map.get(m, True)``) and an additive ``schema_version``.

Parity (marker ``legacy``): ``legacy_migrate`` vs ``state.migrate_state_data`` on seeded random
states; ``render_state`` output accepted by ``state.migrate_state_data`` and
``state.load_state_file`` with identical order/enabled; ``render_state_json`` byte-equal to
``state.save_state_file``.
"""

import copy
import json
import random
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from src.core.categories import DEFAULT_CATEGORIES
from src.core.ids import ModId, SaveIdentity
from src.core.legacy_state import (
    LEGACY_KEYS,
    SCHEMA_VERSION,
    VIEW_MODES,
    StateChanges,
    StateDoc,
    build_default_state,
    legacy_migrate,
    mod_metadata_is_complete,
    parse_state,
    render_state,
    render_state_json,
)
from src.core.load_order import LoadOrder
from src.core.validation import Finding, Severity
from tools.legacy_oracle import LegacyOracle

FIXTURE = Path(__file__).absolute().parent.parent / "fixtures" / "mod_state_v0.json"
EXPECTED_KEYS = (
    "language",
    "mods_path",
    "last_save_path",
    "last_backup_path",
    "last_output_path",
    "selected_profile_path",
    "manual_game_root",
    "manual_local_mods_path",
    "manual_workshop_mods_path",
    "first_run_summary_shown",
    "view_mode",
    "order",
    "categories",
    "category_order",
    "category_colors",
    "category_memory",
    "auto_category_attempted",
    "custom_categories",
    "enabled",
    "nicknames",
    "metadata",
    "mod_paths",
)
UNKNOWN_KEY = "window_geometry"
M = ModId


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _render(doc: StateDoc, changes: StateChanges) -> dict[str, Any]:
    """``render_state`` with the JSON value types loosened for assertion convenience."""
    return dict(render_state(doc, changes))


def _raw(doc: StateDoc) -> dict[str, Any]:
    return dict(doc.raw)


@pytest.fixture
def fixture_state() -> dict[str, Any]:
    return _fixture()


@pytest.fixture
def parsed(fixture_state: dict[str, Any]) -> StateDoc:
    doc, findings = parse_state(copy.deepcopy(fixture_state))
    assert findings == [], findings
    return doc


def _assert_state_findings(findings: Sequence[Finding]) -> None:
    for finding in findings:
        assert finding.rule_id.startswith("state."), finding
        assert finding.severity in (Severity.WARNING, Severity.ERROR, Severity.INFO)


# ----------------------------------------------------------------- constants and defaults


def test_legacy_keys_are_the_22_state_py_defaults() -> None:
    assert LEGACY_KEYS == EXPECTED_KEYS
    assert len(set(LEGACY_KEYS)) == 22
    assert SCHEMA_VERSION == 1
    assert VIEW_MODES == ("No Icons", "Compact", "Comfortable", "Visual")


def test_build_default_state_is_the_state_py_dict() -> None:
    state = build_default_state("en", DEFAULT_CATEGORIES)
    assert tuple(state) == LEGACY_KEYS
    assert state["language"] == "en"
    assert state["view_mode"] == "Comfortable"
    assert state["first_run_summary_shown"] is False
    assert state["category_order"] == list(DEFAULT_CATEGORIES)
    assert state["order"] == []
    for key in ("categories", "category_colors", "category_memory", "metadata", "mod_paths"):
        assert state[key] == {}
    assert state["custom_categories"] == []


def test_build_default_state_returns_fresh_containers() -> None:
    first: dict[str, Any] = build_default_state("en", DEFAULT_CATEGORIES)
    second: dict[str, Any] = build_default_state("en", DEFAULT_CATEGORIES)
    first["order"].append("x")
    first["category_order"].append("Custom")
    assert second["order"] == []
    assert second["category_order"] == list(DEFAULT_CATEGORIES)


def test_fixture_has_the_22_keys_plus_one_unknown() -> None:
    state = _fixture()
    assert set(LEGACY_KEYS) <= set(state)
    assert set(state) - set(LEGACY_KEYS) == {UNKNOWN_KEY}
    assert len(state["order"]) >= 5
    assert set(state["enabled"]) == set(state["order"])
    assert all(isinstance(v, bool) for v in state["enabled"].values())


# ----------------------------------------------------------------- mod_metadata_is_complete


def _complete_metadata() -> dict[str, Any]:
    return {
        "title": "T",
        "published_file_id": "",
        "save_name": "T",
        "save_source": "mod_local_source",
        "version_label": "",
        "updated_label": "",
        "black_reliquary": False,
        "metadata_path": "",
        "project_mtime": None,
        "localization_signature": "",
        "workshop_timeupdated": "",
    }


def test_mod_metadata_is_complete_requires_all_eleven_keys() -> None:
    meta = _complete_metadata()
    assert mod_metadata_is_complete(meta)
    for key in list(meta):
        partial = dict(meta)
        del partial[key]
        assert not mod_metadata_is_complete(partial), key


def test_mod_metadata_is_complete_ignores_values_and_extra_keys() -> None:
    meta = _complete_metadata()
    meta.update({"title": None, "project_mtime": None, "unexpected": 1})
    assert mod_metadata_is_complete(meta)


@pytest.mark.parametrize("value", [None, [], "", 0, "title", ("title",), {"title"}])
def test_mod_metadata_is_complete_rejects_non_dicts(value: object) -> None:
    assert not mod_metadata_is_complete(value)


# ----------------------------------------------------------------- legacy_migrate


def test_legacy_migrate_fills_defaults_and_keeps_order_of_existing_keys() -> None:
    state = {"view_mode": "Visual", "order": ["b", "a"], "zzz": 1}
    out = legacy_migrate(state, "fr", DEFAULT_CATEGORIES)
    assert list(out)[:3] == ["view_mode", "order", "zzz"]
    assert out["language"] == "fr"
    assert out["view_mode"] == "Visual"
    assert out["order"] == ["b", "a"]
    assert out["category_order"] == list(DEFAULT_CATEGORIES)
    assert out["zzz"] == 1
    assert set(LEGACY_KEYS) <= set(out)


def test_legacy_migrate_does_not_mutate_its_input() -> None:
    state: dict[str, Any] = {"categories": {"m": "Custom"}, "custom_categories": []}
    snapshot = copy.deepcopy(state)
    legacy_migrate(state, "en", DEFAULT_CATEGORIES)
    assert state == snapshot


def test_legacy_migrate_normalizes_colors_and_drops_invalid_ones() -> None:
    state = {"category_colors": {"UI": "abcdef", "Class": "#12AB34", "Bad": "red", "Empty": ""}}
    out = legacy_migrate(state, "en", DEFAULT_CATEGORIES)
    assert out["category_colors"] == {"UI": "#ABCDEF", "Class": "#12AB34"}


def test_legacy_migrate_category_order_dedupes_case_insensitively_and_drops_pseudo() -> None:
    state = {"category_order": ["Class", "class", "All", "Unassigned", "", "UI", "Extra"]}
    out: dict[str, Any] = legacy_migrate(state, "en", DEFAULT_CATEGORIES)
    assert out["category_order"][:3] == ["Class", "UI", "Extra"]
    rest = [c for c in DEFAULT_CATEGORIES if c not in ("Class", "UI")]
    assert out["category_order"] == ["Class", "UI", "Extra", *rest]


def test_legacy_migrate_discovers_custom_categories_from_assignments() -> None:
    state = {
        "categories": {"a": "Overhaul", "b": "overhaul", "c": "Unassigned", "d": "All", "e": ""},
        "custom_categories": ["Patch"],
    }
    out = legacy_migrate(state, "en", DEFAULT_CATEGORIES)
    assert out["custom_categories"] == ["Patch", "Overhaul"]
    assert out["category_order"] == [*DEFAULT_CATEGORIES, "Patch", "Overhaul"]


def test_legacy_migrate_is_idempotent_on_the_fixture(fixture_state: dict[str, Any]) -> None:
    once = legacy_migrate(fixture_state, "en", DEFAULT_CATEGORIES)
    assert once == fixture_state
    assert list(once) == list(fixture_state)
    assert legacy_migrate(once, "en", DEFAULT_CATEGORIES) == once


def _random_category_name(rng: random.Random) -> str:
    pool = [*DEFAULT_CATEGORIES, "Overhaul", "Patch", "All", "Unassigned", "", "ui", "class", "Mix"]
    return rng.choice(pool)


def _random_state(rng: random.Random) -> dict[str, Any]:
    """A migrate-safe random state: containers typed as migrate expects, contents messy."""
    state: dict[str, Any] = {}
    if rng.random() < 0.8:
        state["category_order"] = [_random_category_name(rng) for _ in range(rng.randint(0, 12))]
    if rng.random() < 0.8:
        state["custom_categories"] = [_random_category_name(rng) for _ in range(rng.randint(0, 4))]
    if rng.random() < 0.8:
        state["categories"] = {
            f"mod{i}": _random_category_name(rng) for i in range(rng.randint(0, 8))
        }
    if rng.random() < 0.8:
        colors = ["#ABCDEF", "abcdef", "#abc", "red", "", "123456", "#12345G", " #A1B2C3 "]
        state["category_colors"] = {
            _random_category_name(rng) or "X": rng.choice(colors) for _ in range(rng.randint(0, 5))
        }
    for key in ("language", "view_mode", "mods_path"):
        if rng.random() < 0.5:
            state[key] = rng.choice(["", "en", "es", "Compact", "x"])
    if rng.random() < 0.5:
        state["order"] = [f"mod{rng.randint(0, 9)}" for _ in range(rng.randint(0, 6))]
    if rng.random() < 0.3:
        state["unknown_key"] = rng.randint(0, 9)
    return state


@pytest.mark.legacy
def test_legacy_migrate_matches_state_py_on_seeded_random_states(legacy: LegacyOracle) -> None:
    state_mod = legacy.module("state")
    dd2 = legacy.module("dd2")
    rng = random.Random(20250914)
    for _ in range(300):
        state = _random_state(rng)
        expected = state_mod.migrate_state_data(
            copy.deepcopy(state), "en", list(DEFAULT_CATEGORIES), dd2.normalize_hex_color
        )
        actual = legacy_migrate(copy.deepcopy(state), "en", DEFAULT_CATEGORIES)
        assert actual == expected, state
        assert list(actual) == list(expected), state


MIXED_NAME_STATES: dict[str, dict[str, Any]] = {
    "custom_none": {"custom_categories": [None]},
    "custom_int": {"custom_categories": [5]},
    "custom_empty": {"custom_categories": [""]},
    "order_falsy_skipped": {"category_order": [None, "", 0, "Mix"]},
    "order_int": {"category_order": [5]},
    "assigned_falsy_skipped": {"categories": {"m": None, "n": "Mix", "o": ""}},
    "assigned_int": {"categories": {"m": 5}},
    "colors_mixed": {"category_colors": {"UI": None, "Class": 0, "Skins": "#abcdef"}},
}


@pytest.mark.parametrize("state", [{"custom_categories": [None]}, {"custom_categories": [5]}])
def test_legacy_migrate_raises_on_non_text_custom_categories(state: dict[str, Any]) -> None:
    """state.py:56 calls ``.lower()`` on every custom name; the port raises instead of inventing
    the names ``'None'`` / ``'5'``.  ``parse_state`` stays the tolerant path."""
    with pytest.raises(TypeError):
        legacy_migrate(state, "en", DEFAULT_CATEGORIES)
    doc, findings = parse_state(state)
    assert doc.custom_categories == ()
    assert any(f.rule_id == "state.bad_entry" for f in findings)


@pytest.mark.legacy
@pytest.mark.parametrize("name", list(MIXED_NAME_STATES))
def test_legacy_migrate_failure_modes_match_state_py(legacy: LegacyOracle, name: str) -> None:
    """Where the legacy crashes on a value the port raises ``TypeError``; where the legacy skips
    a falsy name silently the port does too."""
    state = MIXED_NAME_STATES[name]
    state_mod = legacy.module("state")
    dd2 = legacy.module("dd2")
    try:
        expected = state_mod.migrate_state_data(
            copy.deepcopy(state), "en", list(DEFAULT_CATEGORIES), dd2.normalize_hex_color
        )
    except AttributeError, TypeError:
        with pytest.raises(TypeError):
            legacy_migrate(copy.deepcopy(state), "en", DEFAULT_CATEGORIES)
        return
    actual = legacy_migrate(copy.deepcopy(state), "en", DEFAULT_CATEGORIES)
    assert actual == expected, name
    assert list(actual) == list(expected), name


@pytest.mark.legacy
def test_legacy_migrate_matches_state_py_on_the_fixture(
    legacy: LegacyOracle, fixture_state: dict[str, Any]
) -> None:
    state_mod = legacy.module("state")
    dd2 = legacy.module("dd2")
    expected = state_mod.migrate_state_data(
        copy.deepcopy(fixture_state), "en", list(DEFAULT_CATEGORIES), dd2.normalize_hex_color
    )
    assert legacy_migrate(fixture_state, "en", DEFAULT_CATEGORIES) == expected


# ----------------------------------------------------------------- parse_state


def test_parse_state_raw_is_the_migrated_file_and_a_private_copy(
    fixture_state: dict[str, Any],
) -> None:
    source = copy.deepcopy(fixture_state)
    doc, findings = parse_state(source)
    assert findings == []
    assert dict(doc.raw) == legacy_migrate(fixture_state, "en", DEFAULT_CATEGORIES)
    assert list(doc.raw) == list(fixture_state)
    source["order"].append("late")
    source["metadata"]["2248772895"]["title"] = "mutated"
    assert "late" not in _raw(doc)["order"]
    assert _raw(doc)["metadata"]["2248772895"]["title"] == "The Chorus"


def test_parse_state_order_and_enabled(parsed: StateDoc, fixture_state: dict[str, Any]) -> None:
    assert isinstance(parsed.order, LoadOrder)
    assert parsed.order.entries == tuple(M(m) for m in fixture_state["order"])
    expected_enabled = {M(m) for m in fixture_state["order"] if fixture_state["enabled"][m]}
    assert parsed.order.enabled == frozenset(expected_enabled)
    assert not parsed.order.is_enabled(M("1739565783"))
    assert parsed.order.is_enabled(M("Mi_Mod_Español"))


def test_parse_state_enabled_uses_legacy_truthiness_with_default_true() -> None:
    state = {
        "order": ["a", "b", "c", "d", "e", "f"],
        "enabled": {"a": 0, "b": "", "c": "no", "d": 1, "e": None},
    }
    doc, _ = parse_state(state)
    assert doc.order.active() == (M("c"), M("d"), M("f"))
    assert doc.order.inactive() == (M("a"), M("b"), M("e"))


def test_parse_state_mappings(parsed: StateDoc, fixture_state: dict[str, Any]) -> None:
    assert dict(parsed.categories) == fixture_state["categories"]
    assert dict(parsed.nicknames) == fixture_state["nicknames"]
    assert parsed.category_order == tuple(fixture_state["category_order"])
    assert parsed.custom_categories == ("Overhaul", "Patch")
    assert dict(parsed.category_colors) == fixture_state["category_colors"]
    assert dict(parsed.category_memory) == fixture_state["category_memory"]
    assert parsed.auto_category_attempted == frozenset(
        M(m) for m in fixture_state["auto_category_attempted"]
    )


def test_parse_state_metadata_identities_only_for_complete_entries(parsed: StateDoc) -> None:
    identities = dict(parsed.metadata_identities)
    assert identities[M("2248772895")] == SaveIdentity("2248772895", "Steam")
    assert identities[M("0001_Superior_Wayfarer")] == SaveIdentity(
        "Superior Wayfarer", "mod_local_source"
    )
    assert identities[M("0003_1_Black_Reliquary")] == SaveIdentity(
        "Black Reliquary", "mod_local_source"
    )
    assert M("3012345678") not in identities  # incomplete metadata (dd2.py:557-573)
    assert M("Mi_Mod_Español") not in identities  # no metadata at all


def test_parse_state_settings(parsed: StateDoc, fixture_state: dict[str, Any]) -> None:
    s = parsed.settings
    assert s.language == "es"
    assert s.mods_path == fixture_state["mods_path"]
    assert s.last_save_path == fixture_state["last_save_path"]
    assert s.last_backup_path == fixture_state["last_backup_path"]
    assert s.last_output_path == fixture_state["last_output_path"]
    assert s.selected_profile_path == fixture_state["selected_profile_path"]
    assert s.manual_game_root == ""
    assert s.manual_local_mods_path == ""
    assert s.manual_workshop_mods_path == fixture_state["manual_workshop_mods_path"]
    assert s.first_run_summary_shown is True
    assert s.view_mode == "Compact"


def test_parse_state_empty_dict_is_the_default_state() -> None:
    doc, findings = parse_state({}, default_language="fr")
    assert findings == []
    assert dict(doc.raw) == build_default_state("fr", DEFAULT_CATEGORIES)
    assert doc.order.entries == ()
    assert doc.settings.language == "fr"
    assert doc.settings.view_mode == "Comfortable"
    assert doc.category_order == DEFAULT_CATEGORIES


@pytest.mark.parametrize("root", [None, [], "text", 7, [{"order": []}], True])
def test_parse_state_non_dict_root_yields_defaults_and_a_warning(root: object) -> None:
    doc, findings = parse_state(root)
    assert dict(doc.raw) == build_default_state("en", DEFAULT_CATEGORIES)
    assert findings, "a non-dict root must be reported"
    _assert_state_findings(findings)
    assert any(f.severity >= Severity.WARNING for f in findings)


def test_parse_state_drops_duplicate_and_invalid_order_keys_with_findings() -> None:
    state = {"order": ["a", "b", "a", "", 3, None, "..", "x/y", "c"], "enabled": {"a": False}}
    doc, findings = parse_state(state)
    assert doc.order.entries == (M("a"), M("b"), M("c"))
    assert doc.order.enabled == frozenset({M("b"), M("c")})
    assert findings
    _assert_state_findings(findings)


@pytest.mark.parametrize(
    "key",
    [
        "order",
        "categories",
        "category_order",
        "category_colors",
        "category_memory",
        "auto_category_attempted",
        "custom_categories",
        "enabled",
        "nicknames",
        "metadata",
        "mod_paths",
    ],
)
@pytest.mark.parametrize("bad", [None, 5, "str", True])
def test_parse_state_bad_container_falls_back_to_default_with_warning(
    key: str, bad: object
) -> None:
    doc, findings = parse_state({key: bad})
    defaults = build_default_state("en", DEFAULT_CATEGORIES)
    assert doc.raw[key] == defaults[key]
    assert findings, key
    _assert_state_findings(findings)


@pytest.mark.parametrize("key", ["language", "mods_path", "view_mode", "first_run_summary_shown"])
def test_parse_state_bad_scalar_falls_back_to_default_with_warning(key: str) -> None:
    doc, findings = parse_state({key: {"nested": 1}})
    defaults = build_default_state("en", DEFAULT_CATEGORIES)
    assert doc.raw[key] == defaults[key]
    assert getattr(doc.settings, key) == defaults[key]
    assert findings, key
    _assert_state_findings(findings)


_SCALARS: tuple[Callable[[random.Random], Any], ...] = (
    lambda _rng: None,
    lambda rng: rng.choice([True, False]),
    lambda rng: rng.randint(-5, 5),
    lambda rng: rng.choice(["", "a", "All", "#ABCDEF", "..", "x/y", "Ñ", "0001_m"]),
    lambda rng: rng.random(),
    lambda rng: rng.choice(["m1", "m2", ""]) * rng.randint(0, 3),
)


def _garbage(rng: random.Random, depth: int = 0) -> Any:
    kind = rng.randint(0, 7 if depth < 3 else 5)
    if kind < len(_SCALARS):
        return _SCALARS[kind](rng)
    if kind == 6:
        return [_garbage(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    keys = [*LEGACY_KEYS, "junk", "m1", "m2", ""]
    return {rng.choice(keys): _garbage(rng, depth + 1) for _ in range(rng.randint(0, 6))}


def _garbage_state(rng: random.Random) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for key in LEGACY_KEYS:
        if rng.random() < 0.6:
            state[key] = _garbage(rng)
    if rng.random() < 0.3:
        state["junk"] = _garbage(rng)
    return state


def test_parse_state_never_raises_on_garbage() -> None:
    rng = random.Random(4242)
    for _ in range(400):
        obj = _garbage_state(rng) if rng.random() < 0.8 else _garbage(rng)
        doc, findings = parse_state(obj)
        assert isinstance(doc, StateDoc)
        assert isinstance(doc.order, LoadOrder)
        assert set(LEGACY_KEYS) <= set(doc.raw)
        _assert_state_findings(findings)
        # whatever was read back is itself renderable and parseable again
        rendered = render_state(doc, StateChanges())
        json.dumps(rendered)
        doc2, _ = parse_state(rendered)
        assert doc2.order == doc.order


# ----------------------------------------------------------------- render_state


def test_render_state_round_trips_the_fixture_with_schema_version_appended(
    fixture_state: dict[str, Any],
) -> None:
    doc, _ = parse_state(copy.deepcopy(fixture_state))
    out = _render(doc, StateChanges())
    assert out == {**fixture_state, "schema_version": SCHEMA_VERSION}
    assert list(out) == [*fixture_state, "schema_version"]
    assert out[UNKNOWN_KEY] == fixture_state[UNKNOWN_KEY]


def test_render_state_minimal_change_only_order_enabled_and_schema_version(
    fixture_state: dict[str, Any],
) -> None:
    messy = copy.deepcopy(fixture_state)
    messy["order"].append("2248772895")  # duplicate -> dropped from order
    del messy["enabled"]["Mi_Mod_Español"]  # implicit True -> written explicitly
    doc, findings = parse_state(copy.deepcopy(messy))
    assert findings
    out = _render(doc, StateChanges())
    changed = {k for k in set(out) | set(messy) if out.get(k) != messy.get(k)}
    assert changed == {"order", "enabled", "schema_version"}
    assert out["order"] == fixture_state["order"]
    assert out["enabled"]["Mi_Mod_Español"] is True
    assert all(isinstance(out["enabled"][m], bool) for m in out["order"])
    assert set(out["enabled"]) >= set(out["order"])


def test_render_state_result_is_independent_of_the_doc(parsed: StateDoc) -> None:
    out = _render(parsed, StateChanges())
    out["metadata"]["2248772895"]["title"] = "mutated"
    out["order"].append("late")
    assert _raw(parsed)["metadata"]["2248772895"]["title"] == "The Chorus"
    assert "late" not in _raw(parsed)["order"]
    again = _render(parsed, StateChanges())
    assert again["metadata"]["2248772895"]["title"] == "The Chorus"


def test_render_state_order_change_writes_explicit_bools(parsed: StateDoc) -> None:
    new_order = LoadOrder(
        entries=(M("new_mod"), M("2248772895"), M("crusader_hu_swf_compat")),
        enabled=frozenset({M("2248772895")}),
    )
    out = _render(parsed, StateChanges(order=new_order))
    assert out["order"] == ["new_mod", "2248772895", "crusader_hu_swf_compat"]
    assert out["enabled"]["new_mod"] is False
    assert out["enabled"]["2248772895"] is True
    assert out["enabled"]["crusader_hu_swf_compat"] is False
    assert out["metadata"] == parsed.raw["metadata"]


def test_render_state_drops_enabled_keys_of_mods_that_left_the_order(parsed: StateDoc) -> None:
    """A renamed folder or a forgotten mod leaves no stale ``enabled`` key behind."""
    gone, *kept = parsed.order.entries
    shorter = LoadOrder(entries=tuple(kept), enabled=parsed.order.enabled & frozenset(kept))
    out = _render(parsed, StateChanges(order=shorter))
    assert out["order"] == list(kept)
    assert set(out["enabled"]) == set(kept)
    flags = parsed.raw["enabled"]
    assert isinstance(flags, dict) and str(gone) in flags, "it was there before"
    assert all(out["enabled"][m] == parsed.order.is_enabled(M(m)) for m in kept)


def test_render_state_categories_and_nicknames_none_unassigns(parsed: StateDoc) -> None:
    out = _render(
        parsed,
        StateChanges(
            categories={M("2248772895"): "UI", M("0001_Superior_Wayfarer"): None},
            nicknames={M("crusader_hu_swf_compat"): None, M("2248772895"): "Chorus"},
        ),
    )
    assert out["categories"]["2248772895"] == "UI"
    assert out["categories"].get("0001_Superior_Wayfarer", "Unassigned") == "Unassigned"
    assert out["categories"]["crusader_hu_swf_compat"] == "Class Patch"  # untouched
    assert "crusader_hu_swf_compat" not in out["nicknames"]
    assert out["nicknames"]["2248772895"] == "Chorus"
    assert out["nicknames"]["Mi_Mod_Español"] == "Español ★"  # untouched


def test_render_state_category_editor_keys(parsed: StateDoc) -> None:
    out = _render(
        parsed,
        StateChanges(
            category_order=("Patch", "UI", "Class"),
            custom_categories=("Patch",),
            category_colors={"Patch": "#A66A4A"},
            category_memory_updates={"norm:new mod": "UI"},
        ),
    )
    assert out["category_order"] == ["Patch", "UI", "Class"]
    assert out["custom_categories"] == ["Patch"]
    assert out["category_colors"] == {"Patch": "#A66A4A"}
    assert out["category_memory"]["norm:new mod"] == "UI"
    assert out["category_memory"]["norm:the chorus"] == "Class"  # merged, not replaced


def test_render_state_attempted_mod_paths_and_settings(parsed: StateDoc) -> None:
    out = _render(
        parsed,
        StateChanges(
            attempted=[M("Mi_Mod_Español")],
            mod_paths={M("Mi_Mod_Español"): "D:/mods/Mi_Mod_Español"},
            settings={"view_mode": "Visual", "first_run_summary_shown": False, "language": "en"},
        ),
    )
    assert out["auto_category_attempted"]["Mi_Mod_Español"] is True
    assert out["auto_category_attempted"]["2248772895"] is True  # kept
    assert out["mod_paths"]["Mi_Mod_Español"] == "D:/mods/Mi_Mod_Español"
    assert out["view_mode"] == "Visual"
    assert out["first_run_summary_shown"] is False
    assert out["language"] == "en"


def test_render_state_never_touches_metadata(parsed: StateDoc) -> None:
    out = _render(parsed, StateChanges(order=LoadOrder((M("only"),), frozenset())))
    assert out["metadata"] == parsed.raw["metadata"]


def test_render_state_json_byte_style() -> None:
    doc = {"language": "es", "nicknames": {"m": "Español ★"}, "order": ["m"]}
    text = render_state_json(doc)
    assert text == json.dumps(doc, indent=2)
    assert not text.endswith("\n")
    assert "\\u00f1" in text  # default ensure_ascii, like state.py:123
    assert json.loads(text) == doc


# ----------------------------------------------------------------- render parity vs state.py


def _legacy_load(
    legacy: LegacyOracle, tmp_path: Path, text: str
) -> tuple[dict[str, Any], list[Any]]:
    state_mod = legacy.module("state")
    dd2 = legacy.module("dd2")
    tmp_path.mkdir(parents=True, exist_ok=True)
    state_file = tmp_path / "mod_state.json"
    state_file.write_text(text, encoding="utf-8")
    return state_mod.load_state_file(
        str(state_file), str(tmp_path), "en", list(DEFAULT_CATEGORIES), dd2.normalize_hex_color
    )


@pytest.mark.legacy
def test_rendered_state_is_accepted_by_legacy_load_and_migrate(
    legacy: LegacyOracle, tmp_path: Path, fixture_state: dict[str, Any]
) -> None:
    doc, _ = parse_state(copy.deepcopy(fixture_state))
    new_order = doc.order.disable({M("2248772895")}).enable([M("1739565783")])
    rendered = render_state(doc, StateChanges(order=new_order, nicknames={M("2248772895"): "C"}))
    loaded, notices = _legacy_load(legacy, tmp_path, render_state_json(rendered))
    assert notices == []
    assert loaded["order"] == list(new_order.entries)
    enabled_map = loaded["enabled"]
    assert [m for m in loaded["order"] if enabled_map.get(m, True)] == list(new_order.active())
    assert loaded["schema_version"] == SCHEMA_VERSION
    migrated = legacy.module("state").migrate_state_data(
        copy.deepcopy(rendered),
        "en",
        list(DEFAULT_CATEGORIES),
        legacy.module("dd2").normalize_hex_color,
    )
    assert migrated == rendered  # the rendered file is already in migrated form


@pytest.mark.legacy
def test_render_state_json_matches_legacy_save_state_file_bytes(
    legacy: LegacyOracle, tmp_path: Path, fixture_state: dict[str, Any]
) -> None:
    doc, _ = parse_state(copy.deepcopy(fixture_state))
    rendered = render_state(doc, StateChanges())
    state_file = tmp_path / "mod_state.json"
    legacy.module("state").save_state_file(rendered, str(state_file), str(tmp_path))
    assert state_file.read_text(encoding="utf-8") == render_state_json(rendered)


@pytest.mark.legacy
def test_render_parity_over_seeded_random_changes(
    legacy: LegacyOracle, tmp_path: Path, fixture_state: dict[str, Any]
) -> None:
    rng = random.Random(7)
    doc, _ = parse_state(copy.deepcopy(fixture_state))
    entries = list(doc.order.entries)
    for i in range(40):
        rng.shuffle(entries)
        enabled = frozenset(m for m in entries if rng.random() < 0.6)
        order = LoadOrder(tuple(entries), enabled)
        rendered = render_state(doc, StateChanges(order=order))
        loaded, notices = _legacy_load(legacy, tmp_path / str(i), render_state_json(rendered))
        assert notices == []
        assert loaded["order"] == list(order.entries)
        assert [m for m in loaded["order"] if loaded["enabled"].get(m, True)] == list(
            order.active()
        )
        reparsed, _ = parse_state(loaded)
        assert reparsed.order == order


@pytest.mark.legacy
def test_legacy_load_state_file_and_parse_state_agree_on_the_fixture(
    legacy: LegacyOracle, tmp_path: Path
) -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    loaded, notices = _legacy_load(legacy, tmp_path, text)
    assert notices == []
    doc, findings = parse_state(json.loads(text))
    assert findings == []
    assert dict(doc.raw) == loaded
    assert list(doc.raw) == list(loaded)
