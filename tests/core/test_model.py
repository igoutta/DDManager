"""Disk-fact value types and the manifest helpers (src/core/model.py).

``ModInfo``/``ModSnapshot``/``MetadataSignature`` are frozen slotted values holding facts only
(no tier, category, nickname or enabled flag); ``normalize_manifest_path`` and
``parse_modfiles_txt`` are total and produce the casefolded posix form the overlap rules compare.
"""

import dataclasses
import random
from pathlib import Path, PurePath

import pytest

from src.core.ids import ModId, SaveIdentity, SaveSource, SourceKind
from src.core.model import (
    MetadataSignature,
    ModInfo,
    ModSnapshot,
    normalize_manifest_path,
    parse_modfiles_txt,
)
from tests.support import factories

# ----------------------------------------------------------------- normalize_manifest_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("heroes/crusader/crusader.info.darkest", "heroes/crusader/crusader.info.darkest"),
        ("Heroes\\Crusader\\Crusader.INFO.darkest", "heroes/crusader/crusader.info.darkest"),
        ("./shared/a.json", "shared/a.json"),
        ("/shared/a.json", "shared/a.json"),
        ("shared/./a.json", "shared/a.json"),
        ("./././x", "x"),
        ("project.xml", "project.xml"),
        ("Localization/Chorus.String_Table.XML", "localization/chorus.string_table.xml"),
        ("\u00c9t\u00e9/\u0130.txt", "\u00e9t\u00e9/i\u0307.txt"),
    ],
)
def test_normalize_manifest_path_accepts(raw: str, expected: str) -> None:
    assert normalize_manifest_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", ".", "./", "/", "a/", "a\\", "../a", "a/../b", "a/..", "..", "./.."],
)
def test_normalize_manifest_path_rejects(raw: str) -> None:
    assert normalize_manifest_path(raw) is None


def test_normalize_manifest_path_is_idempotent_and_total() -> None:
    rng = random.Random(5)
    pool = ["a", "B", "/", "\\", ".", "..", " ", "\u00df", "x.y", "dir", "\t"]
    for _ in range(2000):
        raw = "".join(rng.choice(pool) for _ in range(rng.randint(0, 10)))
        result = normalize_manifest_path(raw)
        if result is None:
            continue
        assert result == normalize_manifest_path(result)
        assert result == result.casefold()
        assert "\\" not in result
        assert not result.startswith("/") and not result.endswith("/")
        assert ".." not in result.split("/")
        assert "." not in result.split("/")


# ----------------------------------------------------------------- parse_modfiles_txt


def test_parse_modfiles_txt_normalizes_and_ignores_blank_lines() -> None:
    text = "audio\\chorus.bank\r\n\r\n  \nHeroes/Chorus/chorus.info.darkest\n./shared/x.json\n"
    assert parse_modfiles_txt(text) == frozenset(
        {"audio/chorus.bank", "heroes/chorus/chorus.info.darkest", "shared/x.json"}
    )


def test_parse_modfiles_txt_drops_invalid_lines_and_dedupes() -> None:
    text = "a/b\nA/B\n../evil\nx/\n\n"
    result = parse_modfiles_txt(text)
    assert result == frozenset({"a/b"})
    assert isinstance(result, frozenset)


def test_parse_modfiles_txt_empty() -> None:
    assert parse_modfiles_txt("") == frozenset()
    assert parse_modfiles_txt("\n\n") == frozenset()


def test_parse_modfiles_txt_on_the_sample_mods(sample_mods_dir: Path) -> None:
    for folder in sorted(p for p in sample_mods_dir.iterdir() if p.is_dir()):
        manifest = (folder / "modfiles.txt").read_text("utf-8", errors="replace")
        files = parse_modfiles_txt(manifest)
        assert all(normalize_manifest_path(f) == f for f in files), folder.name
        assert all("\\" not in f for f in files), folder.name
    crusader = parse_modfiles_txt(
        (sample_mods_dir / "crusader_hu_swf_compat" / "modfiles.txt").read_text("utf-8")
    )
    assert "heroes/crusader/crusader.info.darkest" in crusader
    chorus = parse_modfiles_txt(
        (sample_mods_dir / "chorus_class_mod" / "modfiles.txt").read_text("utf-8")
    )
    assert "audio/chorus.campaign.guid_overrides.json" in chorus


# ----------------------------------------------------------------- value types


def test_metadata_signature_is_the_four_field_key_plus_the_content_root_stamp() -> None:
    sig = MetadataSignature(
        metadata_path="c:\\mods\\x",
        project_mtime=1.5,
        localization_signature="2:17",
        workshop_timeupdated="",
    )
    assert [f.name for f in dataclasses.fields(sig)] == [
        "metadata_path",
        "project_mtime",
        "localization_signature",
        "workshop_timeupdated",
        "content_roots_mtime_ns",
    ]
    assert sig.content_roots_mtime_ns is None, "a value without the stamp still constructs"
    assert sig != dataclasses.replace(sig, content_roots_mtime_ns=1)
    assert hasattr(sig, "__slots__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        sig.project_mtime = 2.0  # ty: ignore[invalid-assignment]
    assert sig == MetadataSignature("c:\\mods\\x", 1.5, "2:17", "")
    assert hash(sig) == hash(MetadataSignature("c:\\mods\\x", 1.5, "2:17", ""))


def _snapshot() -> ModSnapshot:
    return ModSnapshot(
        key=ModId("0001_mod"),
        source_id="local_folder",
        kind=SourceKind.LOCAL,
        path=PurePath("C:/mods/0001_mod"),
        root=PurePath("C:/mods"),
        under_workshop=False,
        path_workshop_id="",
        project=None,
        localization_entries=(("hero_class_name_x", "X"),),
        top_level_dirs=frozenset({"heroes"}),
        code_subdirs=(("heroes", ("x",)),),
        files=frozenset({"heroes/x/x.info.darkest"}),
        newest_mtime=None,
        project_mtime=None,
        localization_signature="",
        acf_timeupdated="",
        preview_path=None,
        preview_mtime_ns=None,
    )


def test_mod_snapshot_is_frozen_slotted_and_holds_no_derivations() -> None:
    snap = _snapshot()
    names = {f.name for f in dataclasses.fields(snap)}
    assert hasattr(snap, "__slots__")
    assert names == {
        "key",
        "source_id",
        "kind",
        "path",
        "root",
        "under_workshop",
        "path_workshop_id",
        "project",
        "localization_entries",
        "top_level_dirs",
        "code_subdirs",
        "files",
        "newest_mtime",
        "project_mtime",
        "localization_signature",
        "acf_timeupdated",
        "preview_path",
        "preview_mtime_ns",
        "content_roots_mtime_ns",
    }
    assert not names & {"title", "tier", "category", "nickname", "enabled", "save_identity"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.key = ModId("other")  # ty: ignore[invalid-assignment]


def test_mod_info_is_frozen_slotted_facts_only() -> None:
    info = factories.local_mod("0001_mod", files=["heroes/x/x.info.darkest", "raid/camping/a.json"])
    names = {f.name for f in dataclasses.fields(info)}
    assert hasattr(info, "__slots__")
    # the contract fields must all be there; extra fact fields (never derivations) are allowed
    assert {
        "id",
        "source_id",
        "kind",
        "path",
        "root",
        "title",
        "project_title",
        "save_identity",
        "workshop_id",
        "version_label",
        "updated_label",
        "black_reliquary",
        "tags",
        "top_level_dirs",
        "code_subdirs",
        "files",
        "preview_path",
        "preview_mtime_ns",
        "load_after_hints",
        "signature",
        "shadowed",
    } <= names
    assert not names & {"tier", "category", "nickname", "enabled"}
    assert info.shadowed == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.title = "x"  # ty: ignore[invalid-assignment]


def test_shadowed_defaults_to_empty_and_is_the_only_default() -> None:
    required = [
        f.name
        for f in dataclasses.fields(ModInfo)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    ]
    assert "shadowed" not in required
    assert "signature" in required


def test_subdirs_of_returns_the_children_or_empty() -> None:
    info = factories.local_mod(
        "mod",
        files=[
            "heroes/Zeta/a",
            "heroes/alpha/b",
            "monsters/beast/c",
            "shared/x",
            "trinkets/t.json",
        ],
    )
    assert info.subdirs_of("heroes") == ("alpha", "zeta")  # the factory casefolds manifest paths
    assert info.subdirs_of("monsters") == ("beast",)
    assert info.subdirs_of("trinkets") == ()  # files only, no child dirs
    assert info.subdirs_of("dungeons") == ()
    assert info.subdirs_of("shared") == ()
    assert info.top_level_dirs == frozenset({"heroes", "monsters", "shared", "trinkets"})


def test_mod_info_identity_fields_are_plain_values() -> None:
    info = factories.workshop_mod("2248772895", title="The Chorus")
    assert info.id == "2248772895"
    assert info.kind is SourceKind.WORKSHOP
    assert info.workshop_id == "2248772895"
    assert info.save_identity == SaveIdentity("2248772895", SaveSource.STEAM)
    assert info.save_identity.is_workshop
    assert info.title == "The Chorus"
    assert isinstance(info.signature, MetadataSignature)
    assert isinstance(info.files, frozenset)
    assert isinstance(info.tags, tuple)
    assert isinstance(info.load_after_hints, tuple)
