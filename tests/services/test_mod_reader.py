"""Per-folder disk reading: snapshot fields, and identity parity (oracle + committed goldens)."""

import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.core.identity import (
    category_memory_keys,
    derive_mod_info,
    display_name,
    display_name_with_suffix,
    display_suffix,
    duplicate_keys,
    sort_key,
)
from src.core.ids import SourceKind
from src.core.model import ModInfo, ModSnapshot
from src.services.detection import is_workshop_content_path, workshop_id_for_folder
from src.services.mod_reader import read_project_bytes, snapshot_mod_folder
from src.services.sources import ReadContext
from tests.services.helpers import TZ
from tests.support import mod_facts as mf

GOLDEN = Path(__file__).absolute().parents[1] / "golden" / "identity" / "cases.json"
MODDING = Path(__file__).absolute().parents[2] / "modding"


def read(folder: Path, root: Path | None = None, acf: dict[str, str] | None = None) -> ModSnapshot:
    under = is_workshop_content_path(folder)
    return snapshot_mod_folder(
        folder,
        root=root if root is not None else folder.parent,
        source_id="steam" if under else "local",
        kind=SourceKind.WORKSHOP if under else SourceKind.LOCAL,
        under_workshop=under,
        workshop_id=workshop_id_for_folder(folder, under_workshop=under),
        ctx=ReadContext(acf_times=acf or {}, tz=TZ),
    )


def record(info: ModInfo, nickname: str | None = None) -> dict[str, object]:
    return {
        "title": info.title,
        "published_file_id": info.workshop_id,
        "save_identity": list(info.save_identity.as_tuple()),
        "version_label": info.version_label,
        "updated_label": info.updated_label,
        "black_reliquary": info.black_reliquary,
        "project_mtime": info.signature.project_mtime,
        "localization_signature": info.signature.localization_signature,
        "workshop_timeupdated": info.signature.workshop_timeupdated,
        "legacy_tags": list(info.tags),
        "display_name": display_name(info, nickname),
        "display_suffix": display_suffix(info),
        "display_name_with_suffix": display_name_with_suffix(info, nickname),
        "sort_name": sort_key(info, nickname),
        "duplicate_keys": list(duplicate_keys(info)),
        "category_memory_keys": list(category_memory_keys(info)),
    }


@pytest.fixture(scope="module")
def case_dirs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return mf.materialize_all(tmp_path_factory.mktemp("reader"))


# ----------------------------------------------------------- parity with the test-side reader


@pytest.mark.parametrize("spec", mf.CASES, ids=[s.id for s in mf.CASES])
def test_snapshot_matches_the_independent_test_side_reader(
    spec: mf.ModDirSpec, case_dirs: dict[str, Path]
) -> None:
    folder = case_dirs[spec.id]
    mine = read(folder, acf=dict(spec.acf))
    expected = mf.snapshot_from_dir(folder, acf=dict(spec.acf))
    ignore = {"source_id", "path", "root", "preview_path", "preview_mtime_ns"}
    for field in dataclasses.fields(ModSnapshot):
        if field.name in ignore:
            continue
        assert getattr(mine, field.name) == getattr(expected, field.name), field.name
    assert str(mine.path) == str(folder)
    assert str(mine.root) == str(folder.parent)


@pytest.mark.parametrize("spec", mf.CASES, ids=[s.id for s in mf.CASES])
def test_identity_matches_the_committed_goldens(
    spec: mf.ModDirSpec, case_dirs: dict[str, Path]
) -> None:
    golden = json.loads(GOLDEN.read_text("utf-8"))
    case = next(c for c in golden["cases"] if c["id"] == spec.id)
    info = derive_mod_info(read(case_dirs[spec.id], acf=dict(spec.acf)), tz=TZ)
    assert record(info) == case["record"]
    for nickname, expected in case["nicknames"].items():
        got = record(info, nickname)
        assert {k: got[k] for k in expected} == expected, nickname


@pytest.mark.legacy
@pytest.mark.parametrize("spec", mf.CASES, ids=[s.id for s in mf.CASES])
def test_synthetic_cases_match_the_pinned_oracle(
    legacy: Any, spec: mf.ModDirSpec, case_dirs: dict[str, Path]
) -> None:
    dd2, categories = legacy.module("dd2"), legacy.module("categories")
    folder = case_dirs[spec.id]
    manager = mf.legacy_manager(dd2, {spec.folder: folder}, acf=dict(spec.acf))
    expected = mf.legacy_record(manager, categories, dd2, spec.folder)
    info = derive_mod_info(read(folder, acf=dict(spec.acf)), tz=TZ)
    assert record(info) == expected


@pytest.mark.legacy
@pytest.mark.parametrize(
    "name", sorted(p.name for p in MODDING.iterdir() if p.is_dir()) if MODDING.is_dir() else []
)
def test_every_sample_mod_matches_read_mod_metadata(
    legacy: Any, name: str, sample_mods_dir: Path
) -> None:
    dd2, categories = legacy.module("dd2"), legacy.module("categories")
    folder = sample_mods_dir / name
    manager = mf.legacy_manager(dd2, {name: folder})
    expected = mf.legacy_record(manager, categories, dd2, name)
    info = derive_mod_info(read(folder), tz=TZ)
    assert record(info) == expected
    identity = expected["save_identity"]
    assert isinstance(identity, list)
    assert info.save_identity.as_tuple() == tuple(identity)


def test_sample_mods_snapshot_without_errors(sample_mods_dir: Path) -> None:
    for folder in sorted(p for p in sample_mods_dir.iterdir() if p.is_dir()):
        snap = read(folder)
        assert snap.key == folder.name
        assert snap.project is not None, folder.name


# ------------------------------------------------------------------ individual facts


def test_root_level_files_are_excluded_and_the_manifest_is_casefolded_posix(
    mod_dir, tmp_path: Path
) -> None:
    folder = mod_dir(
        tmp_path, "m", title="M", files=("readme.txt", "Heroes/Foo/Bar.PNG", "trinkets/x.txt")
    )
    snap = read(folder)
    assert snap.files == frozenset({"heroes/foo/bar.png", "trinkets/x.txt"})
    assert snap.top_level_dirs == frozenset({"heroes", "trinkets"})


def test_code_subdirs_lists_child_dirs_of_the_content_tops(mod_dir, tmp_path: Path) -> None:
    folder = mod_dir(tmp_path, "m", title="M")
    for rel in ("heroes/alpha", "heroes/beta", "monsters/gamma", "other/delta"):
        (folder / rel).mkdir(parents=True)
    (folder / "heroes" / "file.txt").write_bytes(b"x")
    snap = read(folder)
    assert dict(snap.code_subdirs) == {"heroes": ("alpha", "beta"), "monsters": ("gamma",)}


def test_mtimes_and_localization_signature(mod_dir, tmp_path: Path) -> None:
    folder = mod_dir(tmp_path, "m", title="M", files=("heroes/a.txt",))
    loc = folder / "localization"
    loc.mkdir()
    (loc / "a.string_table.xml").write_text(mf.string_table([("k", "v")]), "utf-8")
    (loc / "b.string_table.xml").write_text(mf.string_table([("k2", "v2")]), "utf-8")
    (loc / "c.txt").write_text("ignored", "utf-8")
    stamps = {
        folder / "project.xml": 1710000000,
        folder / "heroes" / "a.txt": 1720000000,
        loc / "a.string_table.xml": 1700000000,
        loc / "b.string_table.xml": 1705000000,
        loc / "c.txt": 1730000000,
    }
    for path, stamp in stamps.items():
        os.utime(path, (stamp, stamp))
    snap = read(folder)
    assert snap.project_mtime == 1710000000
    assert snap.newest_mtime == 1730000000
    assert snap.localization_signature == "2:1705000000"
    assert dict(snap.localization_entries) == {"k": "v", "k2": "v2"}


def test_no_project_and_no_localization(tmp_path: Path) -> None:
    folder = tmp_path / "bare"
    folder.mkdir()
    snap = read(folder)
    assert snap.project is None
    assert snap.project_mtime is None
    assert snap.localization_signature == ""
    assert snap.localization_entries == ()
    assert snap.files == frozenset()
    assert read_project_bytes(folder) is None


def test_read_project_bytes_returns_the_raw_file(mod_dir, tmp_path: Path) -> None:
    folder = mod_dir(tmp_path, "m", title="M")
    assert read_project_bytes(folder) == (folder / "project.xml").read_bytes()


def test_utf16_project_is_decoded(mod_dir, tmp_path: Path) -> None:
    folder = mod_dir(tmp_path, "m", title="Тест Mod", encoding="utf-16")
    snap = read(folder)
    assert snap.project is not None
    assert snap.project.title == "Тест Mod"


def test_workshop_ids_and_acf_lookup(mod_dir, tmp_path: Path) -> None:
    workshop = tmp_path / "Steam" / "steamapps" / "workshop" / "content" / "262060"
    folder = mod_dir(workshop, "1234567890", title="W", published_id="1234567890")
    acf = {"1234567890": "1731672000"}
    snap = read(folder, acf=acf)
    assert snap.under_workshop is True
    assert snap.path_workshop_id == "1234567890"
    assert snap.acf_timeupdated == "1731672000"
    local = mod_dir(tmp_path / "mods", "1234567890", title="L")
    assert read(local, acf=acf).acf_timeupdated == ""
    assert read(local, acf=acf).path_workshop_id == ""


def test_preview_declared_icon_wins_then_fixed_fallback_order(tmp_path: Path) -> None:
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "project.xml").write_text(mf.project_xml("M", preview="custom.png"), "utf-8")
    assert read(folder).preview_path is None
    for name in ("preview_icon.jpg", "preview_icon.gif", "preview_icon.png"):
        (folder / name).write_bytes(b"x")
        preview = read(folder).preview_path
        assert preview is not None
        assert preview.name == name
    (folder / "custom.png").write_bytes(b"declared")
    snap = read(folder)
    assert snap.preview_path is not None
    assert snap.preview_path.name == "custom.png"
    assert snap.preview_mtime_ns == (folder / "custom.png").stat().st_mtime_ns


def test_preview_fallback_without_a_declared_icon(tmp_path: Path) -> None:
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "project.xml").write_text(mf.project_xml("M"), "utf-8")
    (folder / "preview_icon.jpg").write_bytes(b"x")
    (folder / "preview_icon.gif").write_bytes(b"x")
    snap = read(folder)
    assert snap.preview_path is not None
    assert snap.preview_path.name == "preview_icon.gif"
    assert snap.preview_mtime_ns == (folder / "preview_icon.gif").stat().st_mtime_ns
