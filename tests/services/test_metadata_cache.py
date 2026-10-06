"""MetadataCache: pure lookup, explicit commit/save, per-field invalidation, corrupt files."""

import dataclasses
import json
import os
from pathlib import Path, PurePath

import pytest

from src.core.findings import Severity
from src.core.ids import SourceKind
from src.core.model import MetadataSignature, ModInfo
from src.services.metadata_cache import MetadataCache
from tests.support import factories


def rich_info(name: str = "alpha", folder: str = "C:/mods/alpha") -> ModInfo:
    sig = MetadataSignature(f"C:/mods/{name}/project.xml", 1710504000.5, "2:1710504000", "17316")
    return factories.mod_info(
        name,
        kind=SourceKind.WORKSHOP,
        title="Alpha \u00e9",
        workshop_id="1234567",
        files=("heroes/a/b.png", "localization/x.string_table.xml"),
        tags=("Class", "Hero"),
        hints=("Beta",),
        path=PurePath(folder),
        root=PurePath("C:/mods"),
        preview_path=PurePath(folder, "preview_icon.png"),
        preview_mtime_ns=1710504000123456789,
        black_reliquary=True,
        signature=sig,
        shadowed=(PurePath("C:/other/alpha"),),
        project_published_file_id="1234567",
    )


def key_of(info: ModInfo) -> str:
    return f"{info.source_id}|{str(info.path).casefold()}"


@pytest.fixture
def cache_file(tmp_path: Path) -> Path:
    (tmp_path / "cache").mkdir()
    return tmp_path / "cache" / "mod_info.v1.json"


def fresh(cache_file: Path) -> MetadataCache:
    cache, findings = MetadataCache.load(cache_file)
    assert findings == []
    return cache


def test_missing_file_is_an_empty_cache_without_findings(cache_file: Path) -> None:
    cache = fresh(cache_file)
    assert cache.lookup("local|x", rich_info().signature) is None


def test_commit_save_load_roundtrips_every_field(cache_file: Path) -> None:
    info = rich_info()
    cache = fresh(cache_file)
    cache.commit({key_of(info): info})
    cache.save()
    loaded = fresh(cache_file)
    assert loaded.lookup(key_of(info), info.signature) == info


def test_file_format(cache_file: Path) -> None:
    info = rich_info()
    cache = fresh(cache_file)
    cache.commit({key_of(info): info})
    cache.save()
    doc = json.loads(cache_file.read_text("utf-8"))
    assert doc["format"] == "ddmanager.mod-info-cache"
    assert doc["format_version"] == 1
    assert list(doc["entries"]) == [key_of(info)]
    entry = doc["entries"][key_of(info)]
    assert set(entry) == {"signature", "info"}
    assert entry["signature"]["localization_signature"] == "2:1710504000"
    assert entry["info"]["title"] == "Alpha \u00e9"
    assert isinstance(entry["info"]["path"], str)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("metadata_path", "C:/elsewhere/project.xml"),
        ("project_mtime", 1710504001.5),
        ("project_mtime", None),
        ("localization_signature", "3:1710504000"),
        ("workshop_timeupdated", "17317"),
        ("content_roots_mtime_ns", 1710504000123456789),
    ],
)
def test_each_signature_field_invalidates(field: str, value: object, cache_file: Path) -> None:
    info = rich_info()
    cache = fresh(cache_file)
    cache.commit({key_of(info): info})
    changed = dataclasses.replace(info.signature, **{field: value})
    assert cache.lookup(key_of(info), changed) is None
    assert cache.lookup(key_of(info), info.signature) == info


def test_lookup_is_pure(cache_file: Path) -> None:
    info = rich_info()
    cache = fresh(cache_file)
    cache.commit({key_of(info): info})
    cache.save()
    before = cache_file.read_bytes()
    stale = dataclasses.replace(info.signature, project_mtime=1.0)
    assert cache.lookup(key_of(info), stale) is None
    assert cache.lookup("local|unknown", info.signature) is None
    assert cache.lookup(key_of(info), info.signature) == info
    cache.save()
    assert cache_file.read_bytes() == before


def test_commit_replaces_an_entry_and_is_not_persisted_until_save(cache_file: Path) -> None:
    old = rich_info()
    cache = fresh(cache_file)
    cache.commit({key_of(old): old})
    cache.save()
    newer = dataclasses.replace(
        old, title="Changed", signature=dataclasses.replace(old.signature, project_mtime=2.0)
    )
    cache.commit({key_of(old): newer})
    assert fresh(cache_file).lookup(key_of(old), old.signature) == old
    assert cache.lookup(key_of(old), newer.signature) == newer
    assert cache.lookup(key_of(old), old.signature) is None
    cache.save()
    assert fresh(cache_file).lookup(key_of(old), newer.signature) == newer


def test_commit_keep_prunes_everything_else(cache_file: Path) -> None:
    infos = [rich_info(n, f"C:/mods/{n}") for n in ("a", "b", "c")]
    cache = fresh(cache_file)
    cache.commit({key_of(i): i for i in infos[:2]})
    cache.commit({key_of(infos[2]): infos[2]}, keep={key_of(infos[0]), key_of(infos[2])})
    cache.save()
    loaded = fresh(cache_file)
    assert loaded.lookup(key_of(infos[0]), infos[0].signature) == infos[0]
    assert loaded.lookup(key_of(infos[1]), infos[1].signature) is None
    assert loaded.lookup(key_of(infos[2]), infos[2].signature) == infos[2]


def test_commit_without_keep_keeps_everything(cache_file: Path) -> None:
    first, second = rich_info("a", "C:/mods/a"), rich_info("b", "C:/mods/b")
    cache = fresh(cache_file)
    cache.commit({key_of(first): first})
    cache.commit({key_of(second): second})
    assert cache.lookup(key_of(first), first.signature) == first
    assert cache.lookup(key_of(second), second.signature) == second


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"",
        b"[]",
        json.dumps({"format": "something-else", "format_version": 1, "entries": {}}).encode(),
        json.dumps({"format": "ddmanager.mod-info-cache", "format_version": 99}).encode(),
    ],
)
def test_corrupt_or_foreign_file_is_an_empty_cache_with_an_info_finding(
    cache_file: Path, content: bytes
) -> None:
    cache_file.write_bytes(content)
    cache, findings = MetadataCache.load(cache_file)
    assert len(findings) == 1
    assert findings[0].severity is Severity.INFO
    assert cache.lookup("local|x", rich_info().signature) is None
    assert cache_file.read_bytes() == content


def test_save_is_atomic(cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    info = rich_info()
    cache = fresh(cache_file)
    cache.commit({key_of(info): info})
    cache.save()
    original = cache_file.read_bytes()
    cache.commit({key_of(info): dataclasses.replace(info, title="Other")})

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        cache.save()
    assert cache_file.read_bytes() == original
    assert sorted(p.name for p in cache_file.parent.iterdir()) == ["mod_info.v1.json"]


def test_a_legacy_shaped_entry_without_the_content_root_stamp_still_loads(cache_file: Path) -> None:
    """Entries written before ``content_roots_mtime_ns`` existed hit for the same four fields and
    miss as soon as a stamp is known (the next commit upgrades them)."""
    info = rich_info()
    cache = fresh(cache_file)
    cache.commit({key_of(info): info})
    cache.save()
    doc = json.loads(cache_file.read_text("utf-8"))
    entry = doc["entries"][key_of(info)]
    del entry["signature"]["content_roots_mtime_ns"]
    del entry["info"]["signature"]["content_roots_mtime_ns"]
    cache_file.write_text(json.dumps(doc), "utf-8")
    loaded = fresh(cache_file)
    assert loaded.lookup(key_of(info), info.signature) == info
    stamped = dataclasses.replace(info.signature, content_roots_mtime_ns=5)
    assert loaded.lookup(key_of(info), stamped) is None


def test_commit_reports_whether_anything_changed(cache_file: Path) -> None:
    first, second = rich_info("a", "C:/mods/a"), rich_info("b", "C:/mods/b")
    cache = fresh(cache_file)
    assert cache.commit({key_of(first): first, key_of(second): second}) is True
    assert cache.commit({}, keep=[key_of(first), key_of(second)]) is False, "nothing to sweep"
    assert cache.commit({}) is False
    assert cache.commit({}, keep=[key_of(first)]) is True, "an entry was dropped"
    assert len(cache) == 1
