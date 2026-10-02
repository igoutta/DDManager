"""The shareable "ddmanager.loadorder" v1 document (src/core/loadorder_file.py).

Covers the dump/parse byte contract, parser totality on garbage, document_from_order,
resolve_document's matching ladder (exact save identity > workshop id > folder > unique
normalized title) and the legacy ``dd_mod_loadout.json`` importer (legacy_loadout.py:30-46 shape,
84-118 import rules), with a parity test against the pinned ``legacy_loadout.load_loadout``.
"""

import json
import random
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.core.ids import ModId, SaveIdentity, SaveSource
from src.core.load_order import LoadOrder, PriorityDirection, PrioritySetting
from src.core.loadorder_file import (
    FORMAT,
    FORMAT_VERSION,
    LegacyLoadoutExtras,
    LoadOrderDocument,
    LoadOrderEntry,
    ResolveResult,
    document_from_order,
    dump_load_order,
    parse_legacy_loadout,
    parse_load_order,
    resolve_document,
)
from src.core.model import ModInfo
from src.core.validation import Finding, Severity
from tests.support.factories import load_order, local_mod, workshop_mod
from tools.legacy_oracle import LegacyOracle

M = ModId
STEAM = SaveSource.STEAM
LOCAL = SaveSource.LOCAL
CREATED = datetime(2025, 9, 14, 21, 5, 12, tzinfo=UTC)


def _entry(
    name: str,
    source: str = LOCAL,
    *,
    enabled: bool = True,
    title: str | None = None,
    folder: str | None = None,
    workshop_id: str | None = None,
    tier: str | None = None,
    extra: tuple[tuple[str, Any], ...] = (),
) -> LoadOrderEntry:
    return LoadOrderEntry(
        save_identity=SaveIdentity(name, source),
        enabled=enabled,
        title=name if title is None else title,
        folder=folder,
        workshop_id=workshop_id,
        tier=tier,
        extra=extra,
    )


def _doc(*entries: LoadOrderEntry, **overrides: Any) -> LoadOrderDocument:
    fields: dict[str, Any] = {
        "name": "Weekly run",
        "game": "darkest_dungeon_1",
        "priority": PrioritySetting(),
        "created_with": "DD Manager 1.0.0",
        "created_at": CREATED,
        "notes": "",
        "entries": tuple(entries),
    }
    fields.update(overrides)
    return LoadOrderDocument(**fields)


def _mods(*infos: ModInfo) -> dict[ModId, ModInfo]:
    return {info.id: info for info in infos}


def _errors(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity is Severity.ERROR]


def _warnings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity is Severity.WARNING]


# ----------------------------------------------------------------- dump


def test_constants() -> None:
    assert FORMAT == "ddmanager.loadorder"
    assert FORMAT_VERSION == 1


def test_dump_key_order_and_byte_style() -> None:
    doc = _doc(
        _entry("2248772895", STEAM, title="The Chorus", workshop_id="2248772895", tier="class"),
        _entry("Español ★", enabled=False, folder="Mi_Mod_Español", extra=(("note", "ñ"),)),
        _entry("Superior Wayfarer", folder="0001_Superior_Wayfarer", tier="class"),
        notes="first wins",
        extra=(("author", "GA"),),
    )
    text = dump_load_order(doc)
    assert text.endswith("\n")
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
    assert "Español ★" in text  # ensure_ascii=False
    data = json.loads(text)
    assert list(data) == [
        "format",
        "format_version",
        "name",
        "game",
        "priority_direction",
        "verified",
        "created_with",
        "created_at",
        "notes",
        "mods",
        "author",
    ]
    assert data["format"] == FORMAT
    assert data["format_version"] == 1
    assert data["name"] == "Weekly run"
    assert data["game"] == "darkest_dungeon_1"
    assert data["priority_direction"] == "first_wins"
    assert data["verified"] is True
    assert data["created_with"] == "DD Manager 1.0.0"
    assert datetime.fromisoformat(data["created_at"]) == CREATED
    assert data["notes"] == "first wins"
    assert data["author"] == "GA"


def test_dump_entry_shape_ranks_enabled_only() -> None:
    doc = _doc(
        _entry("2248772895", STEAM, title="The Chorus", workshop_id="2248772895", tier="class"),
        _entry("Español ★", enabled=False, folder="Mi_Mod_Español", extra=(("note", "ñ"),)),
        _entry("Superior Wayfarer", folder="0001_Superior_Wayfarer", tier="class"),
    )
    mods = json.loads(dump_load_order(doc))["mods"]
    assert len(mods) == 3
    assert list(mods[0]) == [
        "rank",
        "enabled",
        "title",
        "save_identity",
        "workshop_id",
        "folder",
        "tier",
    ]
    assert mods[0] == {
        "rank": 1,
        "enabled": True,
        "title": "The Chorus",
        "save_identity": {"name": "2248772895", "source": "Steam"},
        "workshop_id": "2248772895",
        "folder": None,
        "tier": "class",
    }
    assert "rank" not in mods[1]
    assert mods[1]["enabled"] is False
    assert mods[1]["save_identity"] == {"name": "Español ★", "source": "mod_local_source"}
    assert mods[1]["note"] == "ñ"
    assert list(mods[1])[-1] == "note"  # extra keys after the canonical ones
    assert mods[2]["rank"] == 2  # ranks count enabled entries only
    assert mods[2]["workshop_id"] is None


def test_dump_null_created_at_and_last_wins() -> None:
    doc = _doc(
        created_at=None,
        priority=PrioritySetting(direction=PriorityDirection.LAST_WINS, verified=False),
    )
    data = json.loads(dump_load_order(doc))
    assert data["created_at"] is None
    assert data["priority_direction"] == "last_wins"
    assert data["verified"] is False
    assert data["mods"] == []


def test_dump_created_at_is_iso_8601_with_offset() -> None:
    data = json.loads(dump_load_order(_doc()))
    assert data["created_at"] == CREATED.isoformat()


# ----------------------------------------------------------------- parse


def _full_doc() -> LoadOrderDocument:
    return _doc(
        _entry("2248772895", STEAM, title="The Chorus", workshop_id="2248772895", tier="class"),
        _entry("Español ★", enabled=False, folder="Mi_Mod_Español", extra=(("note", "ñ"),)),
        _entry("Superior Wayfarer", folder="0001_Superior_Wayfarer", tier="class"),
        notes="first wins",
        extra=(("author", "GA"), ("tags", ["a", 1, None])),
    )


def test_parse_round_trips_dump() -> None:
    doc = _full_doc()
    parsed, findings = parse_load_order(dump_load_order(doc))
    assert findings == []
    assert parsed == doc
    assert parsed is not None
    assert dump_load_order(parsed) == dump_load_order(doc)


def test_parse_minimal_document() -> None:
    text = json.dumps({"format": FORMAT, "format_version": 1, "mods": []})
    parsed, findings = parse_load_order(text)
    assert parsed is not None
    assert _errors(findings) == []
    assert parsed.entries == ()
    assert parsed.priority == PrioritySetting()
    assert parsed.created_at is None
    assert parsed.name == ""
    assert parsed.notes == ""


def test_parse_preserves_unknown_keys_in_extra() -> None:
    text = json.dumps(
        {
            "format": FORMAT,
            "format_version": 1,
            "name": "x",
            "custom_top": {"deep": [1, 2]},
            "mods": [
                {
                    "enabled": True,
                    "title": "A",
                    "save_identity": {"name": "A", "source": LOCAL},
                    "custom_entry": 3.5,
                }
            ],
        }
    )
    parsed, findings = parse_load_order(text)
    assert parsed is not None
    assert _errors(findings) == []
    assert dict(parsed.extra) == {"custom_top": {"deep": [1, 2]}}
    assert dict(parsed.entries[0].extra) == {"custom_entry": 3.5}
    again, _ = parse_load_order(dump_load_order(parsed))
    assert again == parsed


@pytest.mark.parametrize(
    "text",
    [
        "",
        "null",
        "[]",
        '"string"',
        "{}",
        '{"format": "something.else", "format_version": 1, "mods": []}',
        '{"format_version": 1, "mods": []}',
        "{not json",
    ],
)
def test_parse_wrong_format_is_none_plus_error(text: str) -> None:
    parsed, findings = parse_load_order(text)
    assert parsed is None
    assert _errors(findings)
    assert all(f.rule_id for f in findings)


def test_parse_newer_format_version_is_rejected_with_a_newer_message() -> None:
    text = json.dumps({"format": FORMAT, "format_version": 2, "mods": []})
    parsed, findings = parse_load_order(text)
    assert parsed is None
    errors = _errors(findings)
    assert len(errors) == 1
    assert "newer" in errors[0].message.lower()


def test_parse_rank_mismatch_warns_and_array_order_wins() -> None:
    text = json.dumps(
        {
            "format": FORMAT,
            "format_version": 1,
            "mods": [
                {"rank": 2, "enabled": True, "save_identity": {"name": "A", "source": LOCAL}},
                {"rank": 1, "enabled": True, "save_identity": {"name": "B", "source": LOCAL}},
                {"rank": 9, "enabled": False, "save_identity": {"name": "C", "source": LOCAL}},
            ],
        }
    )
    parsed, findings = parse_load_order(text)
    assert parsed is not None
    assert _errors(findings) == []
    assert _warnings(findings)
    assert [e.save_identity.name for e in parsed.entries] == ["A", "B", "C"]
    assert [e.enabled for e in parsed.entries] == [True, True, False]


def test_parse_duplicate_identity_skips_the_later_entry_with_error() -> None:
    text = json.dumps(
        {
            "format": FORMAT,
            "format_version": 1,
            "mods": [
                {
                    "enabled": True,
                    "title": "first",
                    "save_identity": {"name": "A", "source": LOCAL},
                },
                {"enabled": False, "title": "dup", "save_identity": {"name": "A", "source": LOCAL}},
                {
                    "enabled": True,
                    "title": "steam",
                    "save_identity": {"name": "A", "source": STEAM},
                },
            ],
        }
    )
    parsed, findings = parse_load_order(text)
    assert parsed is not None
    assert len(_errors(findings)) == 1
    assert [(e.save_identity.name, e.save_identity.source) for e in parsed.entries] == [
        ("A", LOCAL),
        ("A", STEAM),
    ]
    assert parsed.entries[0].title == "first"


@pytest.mark.parametrize(
    "identity",
    [None, {}, {"source": LOCAL}, {"name": "", "source": LOCAL}, {"name": None}, "A", 5, []],
)
def test_parse_missing_or_empty_identity_name_skips_entry_with_error(identity: object) -> None:
    text = json.dumps(
        {
            "format": FORMAT,
            "format_version": 1,
            "mods": [
                {"enabled": True, "save_identity": identity},
                {"enabled": True, "save_identity": {"name": "B", "source": LOCAL}},
            ],
        }
    )
    parsed, findings = parse_load_order(text)
    assert parsed is not None
    assert len(_errors(findings)) == 1
    assert [e.save_identity.name for e in parsed.entries] == ["B"]


def test_parse_tolerates_bad_scalars() -> None:
    text = json.dumps(
        {
            "format": FORMAT,
            "format_version": 1,
            "name": 12,
            "priority_direction": "sideways",
            "verified": "yes",
            "created_at": "not a date",
            "notes": None,
            "mods": [
                {"enabled": "no", "title": None, "save_identity": {"name": "A", "source": LOCAL}},
                7,
                None,
            ],
        }
    )
    parsed, findings = parse_load_order(text)
    assert parsed is not None
    assert parsed.created_at is None
    assert parsed.priority.direction in (PriorityDirection.FIRST_WINS, PriorityDirection.LAST_WINS)
    assert len(parsed.entries) == 1
    assert isinstance(parsed.entries[0].enabled, bool)
    assert isinstance(parsed.entries[0].title, str)
    assert isinstance(parsed.name, str)
    assert isinstance(parsed.notes, str)
    assert findings  # every tolerated oddity is reported


_SCALARS: tuple[Callable[[random.Random], Any], ...] = (
    lambda _rng: None,
    lambda rng: rng.choice([True, False]),
    lambda rng: rng.randint(-3, 3),
    lambda rng: rng.choice([FORMAT, "first_wins", "", "A", "Steam", "mod_local_source", "ñ"]),
    lambda rng: rng.random(),
    lambda rng: rng.choice(["2025-01-01T00:00:00", "x", "1"]) * rng.randint(0, 2),
)
_KEYS = (
    "format",
    "format_version",
    "name",
    "game",
    "priority_direction",
    "verified",
    "created_with",
    "created_at",
    "notes",
    "mods",
    "rank",
    "enabled",
    "title",
    "save_identity",
    "source",
    "workshop_id",
    "folder",
    "tier",
    "junk",
)


def _garbage(rng: random.Random, depth: int = 0) -> Any:
    kind = rng.randint(0, 7 if depth < 3 else 5)
    if kind < len(_SCALARS):
        return _SCALARS[kind](rng)
    if kind == 6:
        return [_garbage(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {rng.choice(_KEYS): _garbage(rng, depth + 1) for _ in range(rng.randint(0, 7))}


def _garbage_document(rng: random.Random) -> Any:
    doc: dict[str, Any] = {"format": FORMAT, "format_version": rng.choice([1, 1, 1, 0, 2, "1"])}
    doc["mods"] = [_garbage(rng) for _ in range(rng.randint(0, 5))]
    for key in ("name", "priority_direction", "verified", "created_at", "notes", "junk"):
        if rng.random() < 0.5:
            doc[key] = _garbage(rng)
    return doc


def test_parse_never_raises_on_garbage() -> None:
    rng = random.Random(1337)
    for i in range(500):
        obj = _garbage_document(rng) if i % 2 else _garbage(rng)
        text = json.dumps(obj) if rng.random() < 0.9 else repr(obj)
        parsed, findings = parse_load_order(text)
        assert parsed is None or isinstance(parsed, LoadOrderDocument)
        assert isinstance(findings, list)
        assert all(isinstance(f, Finding) for f in findings)
        if parsed is not None:
            again, _ = parse_load_order(dump_load_order(parsed))
            assert again == parsed


def test_parse_never_raises_on_random_bytes() -> None:
    rng = random.Random(99)
    for _ in range(200):
        text = "".join(chr(rng.randint(0, 0x2FF)) for _ in range(rng.randint(0, 40)))
        parsed, findings = parse_load_order(text)
        assert parsed is None
        assert _errors(findings)


# ----------------------------------------------------------------- document_from_order


def test_document_from_order_active_only_and_with_disabled() -> None:
    chorus = workshop_mod("2248772895", title="The Chorus")
    wayfarer = local_mod("0001_Superior_Wayfarer", title="Superior Wayfarer")
    patch = local_mod("crusader_hu_swf_compat", title="Crusader HU SWF compat")
    mods = _mods(chorus, wayfarer, patch)
    order = load_order("2248772895", "-0001_Superior_Wayfarer", "crusader_hu_swf_compat")
    tiers = {M("2248772895"): "class", M("crusader_hu_swf_compat"): "class_patch"}
    common: dict[str, Any] = {
        "name": "Weekly",
        "priority": PrioritySetting(direction=PriorityDirection.LAST_WINS),
        "created_with": "DD Manager 1.0.0",
        "created_at": CREATED,
        "tiers": tiers,
    }
    active_doc = document_from_order(order, mods, include_disabled=False, **common)
    assert [e.save_identity.name for e in active_doc.entries] == [
        "2248772895",
        "Crusader HU SWF compat",  # local mods write their title (dd2.py:3521-3527)
    ]
    assert all(e.enabled for e in active_doc.entries)
    assert active_doc.name == "Weekly"
    assert active_doc.priority.direction is PriorityDirection.LAST_WINS
    assert active_doc.created_with == "DD Manager 1.0.0"
    assert active_doc.created_at == CREATED

    full_doc = document_from_order(order, mods, include_disabled=True, **common)
    assert [(e.save_identity.name, e.enabled) for e in full_doc.entries] == [
        ("2248772895", True),
        ("Superior Wayfarer", False),
        ("Crusader HU SWF compat", True),
    ]
    first, second, third = full_doc.entries
    assert first.save_identity == chorus.save_identity
    assert first.title == "The Chorus"
    assert first.workshop_id == "2248772895"
    assert first.folder in (None, "2248772895")
    assert first.tier == "class"
    assert second.save_identity == wayfarer.save_identity
    assert second.folder == "0001_Superior_Wayfarer"
    assert not second.workshop_id
    assert second.tier is None
    assert third.tier == "class_patch"


def test_document_from_order_round_trips_through_text() -> None:
    mods = _mods(workshop_mod("111", title="One"), local_mod("two", title="Two"))
    order = load_order("111", "two")
    doc = document_from_order(
        order,
        mods,
        name="n",
        priority=PrioritySetting(),
        created_with="t",
        created_at=None,
        tiers={},
        include_disabled=True,
    )
    parsed, findings = parse_load_order(dump_load_order(doc))
    assert findings == []
    assert parsed == doc


# ----------------------------------------------------------------- resolve_document


def _resolve(
    doc: LoadOrderDocument, mods: Mapping[ModId, ModInfo], base: LoadOrder
) -> ResolveResult:
    result = resolve_document(doc, mods, base)
    assert isinstance(result, ResolveResult)
    assert isinstance(result.order, LoadOrder)
    return result


def test_resolve_exact_identity_beats_everything() -> None:
    real = workshop_mod("2248772895", title="The Chorus")
    decoy = local_mod("the_chorus", title="The Chorus")
    doc = _doc(_entry("2248772895", STEAM, title="The Chorus", folder="the_chorus"))
    result = _resolve(doc, _mods(real, decoy), load_order("the_chorus", "2248772895"))
    assert result.matched == ((0, M("2248772895")),)
    assert result.unresolved == ()
    assert result.order.entries == (M("2248772895"), M("the_chorus"))
    assert result.order.enabled == frozenset({M("2248772895")})


def test_resolve_workshop_id_match_when_identity_differs() -> None:
    copy_ = local_mod("chorus_local", title="Chorus (local copy)", workshop_id="2248772895")
    doc = _doc(_entry("something else", LOCAL, title="?", workshop_id="2248772895"))
    result = _resolve(doc, _mods(copy_), load_order("chorus_local"))
    assert result.matched == ((0, M("chorus_local")),)


def test_resolve_folder_match_requires_same_kind() -> None:
    local = local_mod("my_mod", title="Renamed Title")
    doc = _doc(_entry("Old Title", LOCAL, title="Old Title", folder="my_mod"))
    result = _resolve(doc, _mods(local), load_order("my_mod"))
    assert result.matched == ((0, M("my_mod")),)

    steam_entry = _doc(_entry("999", STEAM, title="Old Title", folder="my_mod"))
    result = _resolve(steam_entry, _mods(local), load_order("my_mod"))
    assert result.matched == ()
    assert result.unresolved == steam_entry.entries


def test_resolve_unique_normalized_title_match_and_ambiguity() -> None:
    mod = local_mod("some_folder", title="Superior Wayfarer")
    doc = _doc(_entry("gone", LOCAL, title="superior-wayfarer!"))
    result = _resolve(doc, _mods(mod), load_order("some_folder"))
    assert result.matched == ((0, M("some_folder")),)

    twin = local_mod("other_folder", title="Superior  Wayfarer")
    result = _resolve(doc, _mods(mod, twin), load_order("some_folder", "other_folder"))
    assert result.matched == ()
    assert result.unresolved == doc.entries
    assert result.order.active() == ()


def test_resolve_order_is_document_order_then_unmentioned_base_disabled() -> None:
    mods = _mods(local_mod("a"), local_mod("b"), local_mod("c"), local_mod("d"), workshop_mod("5"))
    base = load_order("d", "-c", "b", "a", "5")
    doc = _doc(_entry("c", enabled=True), _entry("ghost"), _entry("a", enabled=False), _entry("b"))
    result = _resolve(doc, mods, base)
    assert result.order.entries == (M("c"), M("a"), M("b"), M("d"), M("5"))
    assert result.order.enabled == frozenset({M("c"), M("b")})
    assert result.matched == ((0, M("c")), (2, M("a")), (3, M("b")))
    assert [e.save_identity.name for e in result.unresolved] == ["ghost"]
    assert set(result.order.entries) == set(base.entries)  # never pruned


def test_resolve_never_matches_one_mod_twice() -> None:
    mod = local_mod("a", title="Alpha")
    doc = _doc(_entry("a", enabled=False), _entry("zzz", title="Alpha"))
    result = _resolve(doc, _mods(mod), load_order("a"))
    assert result.matched == ((0, M("a")),)
    assert [e.save_identity.name for e in result.unresolved] == ["zzz"]
    assert result.order.entries == (M("a"),)
    assert not result.order.is_enabled(M("a"))


def test_resolve_findings_are_findings() -> None:
    doc = _doc(_entry("ghost"))
    result = _resolve(doc, {}, load_order("x"))
    assert all(isinstance(f, Finding) for f in result.findings)
    assert result.order.entries == (M("x"),)


def test_resolve_identity_name_stands_in_for_a_missing_folder_same_kind_only() -> None:
    """A legacy local save name IS the folder: an entry without ``folder`` whose identity name
    equals an installed local folder matches it even though the title changed; a Steam entry
    with that name does not (kind gate)."""
    local = local_mod("my_mod", title="Renamed Title")
    assert local.save_identity == SaveIdentity("Renamed Title", LOCAL)
    doc = _doc(_entry("my_mod", LOCAL, title="Old Title"))
    result = _resolve(doc, _mods(local), load_order("my_mod"))
    assert result.matched == ((0, M("my_mod")),)
    assert result.findings == ()

    steam = _doc(_entry("my_mod", STEAM, title="Old Title"))
    result = _resolve(steam, _mods(local), load_order("my_mod"))
    assert result.matched == ()
    assert result.unresolved == steam.entries


def test_resolve_same_identity_copies_are_told_apart_by_the_folder_hint() -> None:
    """Two local copies titled alike share one SaveIdentity (what core.duplicate_identity
    reports); the user's own saved profile carries the folders, so both resolve to themselves."""
    a = local_mod("a", title="Alpha")
    copy_ = local_mod("a_copy", title="Alpha")
    assert a.save_identity == copy_.save_identity
    mods = _mods(a, copy_)
    order = load_order("a_copy", "-a")
    doc = document_from_order(
        order,
        mods,
        name="mine",
        priority=PrioritySetting(),
        created_with="t",
        created_at=None,
        tiers={},
        include_disabled=True,
    )
    result = _resolve(doc, mods, load_order("a", "a_copy"))
    assert result.matched == ((0, M("a_copy")), (1, M("a")))
    assert result.unresolved == ()
    assert result.findings == ()
    assert result.order.entries == (M("a_copy"), M("a"))
    assert result.order.enabled == frozenset({M("a_copy")})
    # the profile also survives the text round trip: parse keys duplicates on (identity, folder)
    parsed, findings = parse_load_order(dump_load_order(doc))
    assert _errors(findings) == []
    assert parsed == doc


def test_resolve_same_identity_without_a_narrowing_hint_stays_ambiguous() -> None:
    a = local_mod("a", title="Alpha")
    copy_ = local_mod("a_copy", title="Alpha")
    doc = _doc(_entry("Alpha", LOCAL, title="Alpha"))
    result = _resolve(doc, _mods(a, copy_), load_order("a", "a_copy"))
    assert result.matched == ()
    assert result.unresolved == doc.entries
    assert [f.rule_id for f in result.findings] == ["loadorder.ambiguous"]
    assert result.order.active() == ()


def test_resolve_narrowing_ignores_a_hint_that_points_outside_the_identity_pool() -> None:
    """The identity rung is the strongest: a folder hint naming a third mod does not override
    an ambiguous identity match, it is simply unable to narrow it."""
    a = local_mod("a", title="Alpha")
    copy_ = local_mod("a_copy", title="Alpha")
    other = local_mod("other", title="Other")
    doc = _doc(_entry("Alpha", LOCAL, title="Alpha", folder="other"))
    result = _resolve(doc, _mods(a, copy_, other), load_order("a", "a_copy", "other"))
    assert result.matched == ()
    assert [f.rule_id for f in result.findings] == ["loadorder.ambiguous"]


def test_parse_keeps_same_identity_entries_that_differ_by_folder() -> None:
    def entry(folder: str | None) -> dict[str, Any]:
        return {"save_identity": {"name": "Alpha", "source": LOCAL}, "folder": folder}

    text = json.dumps(
        {
            "format": FORMAT,
            "format_version": 1,
            "mods": [entry("a"), entry("a_copy"), entry("a"), entry(None), entry(None)],
        }
    )
    parsed, findings = parse_load_order(text)
    assert parsed is not None
    assert [e.folder for e in parsed.entries] == ["a", "a_copy", None]
    assert [f.rule_id for f in _errors(findings)] == ["loadorder.duplicate_identity"] * 2


# ----------------------------------------------------------------- legacy loadout import


def _legacy_loadout(
    order: list[str], enabled: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    enabled_map = dict.fromkeys(order, True) if enabled is None else enabled
    doc: dict[str, Any] = {
        "mods_path": "C:/mods",
        "order": order,
        "enabled": enabled_map,
        "enabled_mods": [m for m in order if enabled_map.get(m, True)],
        "disabled_mods": [m for m in order if not enabled_map.get(m, True)],
        "category_memory": {},
        "nicknames": {},
        "categories": dict.fromkeys(order, "Unassigned"),
    }
    doc.update(extra)
    return doc


def test_parse_legacy_loadout_shape() -> None:
    obj = _legacy_loadout(
        ["0001_a", "b", "2248772895"],
        {"0001_a": True, "b": False},
        nicknames={"b": "Bee"},
        categories={"0001_a": "Class", "b": "Unassigned"},
        category_memory={"norm:a": "Class"},
    )
    doc, extras, findings = parse_legacy_loadout(obj)
    assert doc is not None
    assert extras is not None
    assert _errors(findings) == []
    assert [e.folder for e in doc.entries] == ["0001_a", "b", "2248772895"]
    assert [e.save_identity for e in doc.entries] == [
        SaveIdentity("0001_a", ""),
        SaveIdentity("b", ""),
        SaveIdentity("2248772895", ""),
    ]
    assert [e.enabled for e in doc.entries] == [True, False, True]  # missing -> True
    assert isinstance(extras, LegacyLoadoutExtras)
    assert dict(extras.nicknames) == {"b": "Bee"}
    assert dict(extras.categories) == {"0001_a": "Class", "b": "Unassigned"}
    assert dict(extras.category_memory) == {"norm:a": "Class"}


def test_parse_legacy_loadout_enabled_values_are_truthiness() -> None:
    obj = _legacy_loadout(["a", "b", "c"], {"a": 0, "b": "yes", "c": None})
    doc, _, _ = parse_legacy_loadout(obj)
    assert doc is not None
    assert [e.enabled for e in doc.entries] == [False, True, False]


@pytest.mark.parametrize(
    "obj",
    [
        None,
        [],
        "x",
        {},
        {"order": {"a": 1}, "enabled": {}},
        {"order": ["a"], "enabled": ["a"]},
        {"order": "a", "enabled": {}},
        {"enabled": {}},
        {"order": []},
    ],
)
def test_parse_legacy_loadout_rejects_invalid_shape_like_legacy(obj: object) -> None:
    doc, extras, findings = parse_legacy_loadout(obj)
    assert doc is None
    assert extras is None
    assert _errors(findings)


def test_parse_legacy_loadout_non_dict_extras_are_ignored() -> None:
    obj = _legacy_loadout(["a"], nicknames=["x"], categories=5, category_memory=None)
    doc, extras, _ = parse_legacy_loadout(obj)
    assert doc is not None
    assert extras is not None
    assert dict(extras.nicknames) == {}
    assert dict(extras.categories) == {}
    assert dict(extras.category_memory) == {}


def test_parse_legacy_loadout_never_raises_on_garbage() -> None:
    rng = random.Random(2024)
    for _ in range(300):
        obj = _garbage(rng)
        if rng.random() < 0.5:
            obj = {"order": _garbage(rng), "enabled": _garbage(rng), "nicknames": _garbage(rng)}
        doc, extras, findings = parse_legacy_loadout(obj)
        assert (doc is None) == (extras is None)
        assert all(isinstance(f, Finding) for f in findings)


def test_legacy_loadout_resolves_by_folder_against_current_mods() -> None:
    mods = _mods(local_mod("0001_a", title="Alpha"), local_mod("b"), local_mod("c"))
    base = load_order("b", "c", "0001_a")
    doc, _, _ = parse_legacy_loadout(_legacy_loadout(["0001_a", "ghost", "c"], {"0001_a": False}))
    assert doc is not None
    result = resolve_document(doc, mods, base)
    assert result.order.entries == (M("0001_a"), M("c"), M("b"))
    assert result.order.enabled == frozenset({M("c")})
    assert [e.folder for e in result.unresolved] == ["ghost"]


class _StubApp:
    """The attributes legacy_loadout.load_loadout reads from the Tk ModManager."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.messages: list[tuple[str, str, str]] = []
        self.status = ""
        self.remembered: list[tuple[str, str]] = []

    def show_warning(self, title: str, body: str) -> None:
        self.messages.append(("warning", title, body))

    def show_error(self, title: str, body: str) -> None:
        self.messages.append(("error", title, body))

    def show_info(self, title: str, body: str) -> None:
        self.messages.append(("info", title, body))

    def remember_mod_category(self, mod: str, category: str) -> None:
        self.remembered.append((mod, category))

    def save_state(self) -> None:
        pass

    def rebuild_category_menus(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    def set_status_text(self, text: str) -> None:
        self.status = text


class _StubFileDialog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def askopenfilename(self, **_: Any) -> str:
        return str(self.path)


def _legacy_import(
    legacy: LegacyOracle, tmp_path: Path, state: dict[str, Any], loadout: dict[str, Any]
) -> _StubApp:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "dd_mod_loadout.json"
    path.write_text(json.dumps(loadout), encoding="utf-8")
    app = _StubApp(state)
    legacy.module("legacy_loadout").load_loadout(app, str(tmp_path), _StubFileDialog(path))
    assert not [m for m in app.messages if m[0] == "error"], app.messages
    return app


def _core_import(
    state: dict[str, Any], loadout: dict[str, Any]
) -> tuple[ResolveResult, LoadOrderDocument]:
    current = state["order"]
    mods = {M(m): local_mod(m) for m in current}
    base = LoadOrder(
        tuple(M(m) for m in current),
        frozenset(M(m) for m in current if state["enabled"].get(m, True)),
    )
    doc, _, findings = parse_legacy_loadout(loadout)
    assert doc is not None, findings
    return resolve_document(doc, mods, base), doc


@pytest.mark.legacy
def test_legacy_loadout_import_parity_on_seeded_loadouts(
    legacy: LegacyOracle, tmp_path: Path
) -> None:
    rng = random.Random(31337)
    pool = [f"mod{i}" for i in range(10)]
    for i in range(60):
        current = rng.sample(pool, rng.randint(1, 8))
        state = {
            "order": list(current),
            "enabled": {m: rng.random() < 0.7 for m in current},
            "categories": {},
            "category_memory": {},
            "nicknames": {},
        }
        loadout_order = rng.sample(pool, rng.randint(0, 8))
        enabled = {m: rng.random() < 0.5 for m in loadout_order if rng.random() < 0.8}
        loadout = _legacy_loadout(loadout_order, enabled)
        app = _legacy_import(legacy, tmp_path / str(i), json.loads(json.dumps(state)), loadout)
        result, doc = _core_import(state, loadout)
        assert result.order.entries == tuple(M(m) for m in app.state["order"]), (state, loadout)
        mentioned = {e.folder for e in doc.entries}
        for m in current:
            if m in mentioned and m in enabled:
                assert result.order.is_enabled(M(m)) == app.state["enabled"][m], (m, loadout)
        missing = [m for m in loadout_order if m not in current]
        assert [e.folder for e in result.unresolved] == missing


@pytest.mark.legacy
def test_regression_lock_unmentioned_mods_keep_their_flag_in_legacy_but_are_disabled_here(
    legacy: LegacyOracle, tmp_path: Path
) -> None:
    """Documented divergence: base entries the document does not mention end up disabled."""
    state = {"order": ["a", "b"], "enabled": {"a": True, "b": True}, "categories": {}}
    loadout = _legacy_loadout(["a"], {"a": True})
    app = _legacy_import(legacy, tmp_path, json.loads(json.dumps(state)), loadout)
    assert app.state["enabled"]["b"] is True  # legacy leaves it alone
    result, _ = _core_import(state, loadout)
    assert result.order.entries == (M("a"), M("b"))
    assert not result.order.is_enabled(M("b"))  # core: unmentioned -> disabled


@pytest.mark.legacy
def test_regression_lock_mentioned_mod_without_enabled_flag(
    legacy: LegacyOracle, tmp_path: Path
) -> None:
    """Documented divergence: legacy keeps the current flag; the port defaults to enabled."""
    state = {"order": ["a"], "enabled": {"a": False}, "categories": {}}
    loadout = _legacy_loadout(["a"], {})
    app = _legacy_import(legacy, tmp_path, json.loads(json.dumps(state)), loadout)
    assert app.state["enabled"]["a"] is False
    result, _ = _core_import(state, loadout)
    assert result.order.is_enabled(M("a"))
