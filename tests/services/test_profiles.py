"""ProfileRepository: named load-order documents on disk."""

import json
import re
from pathlib import Path

import pytest

from src.core.ids import SaveIdentity
from src.core.load_order import PriorityDirection, PrioritySetting
from src.core.loadorder_file import (
    GAME,
    LoadOrderDocument,
    LoadOrderEntry,
    dump_load_order,
    parse_load_order,
)
from src.services.errors import ProfileExistsError, ProfileFormatError
from src.services.profiles import ProfileRepository, slugify


def entry(name: str, source: str = "mod_local_source", *, enabled: bool = True) -> LoadOrderEntry:
    return LoadOrderEntry(
        save_identity=SaveIdentity(name, source),
        enabled=enabled,
        title=name.title(),
        folder=name,
        workshop_id=name if source == "Steam" else None,
        tier="class",
    )


def doc(name: str, *entries: LoadOrderEntry) -> LoadOrderDocument:
    return LoadOrderDocument(
        name=name,
        game=GAME,
        priority=PrioritySetting(PriorityDirection.LAST_WINS, verified=False),
        created_with="tests",
        created_at=None,
        notes="a note",
        entries=entries or (entry("alpha"), entry("1234567", "Steam", enabled=False)),
    )


@pytest.fixture
def repo(tmp_path: Path) -> ProfileRepository:
    folder = tmp_path / "profiles"
    folder.mkdir()
    return ProfileRepository(folder)


def test_slugify_is_safe_stable_and_never_empty() -> None:
    assert slugify("Hello World") == slugify("hello world")
    for raw in ("A/B:C\\D", "  spaced  ", "caf\u00e9 \u00fcber", "???", "", "x" * 300):
        slug = slugify(raw)
        assert slug
        assert re.fullmatch(r"[^/\\:*?\"<>|\s]+", slug), slug
        assert slugify(slug) == slug
    assert slugify("one") != slugify("two")


def test_save_writes_a_loadorder_file_that_parses_back(
    repo: ProfileRepository, tmp_path: Path
) -> None:
    original = doc("Main Run")
    path = repo.save(original)
    assert path.parent == tmp_path / "profiles"
    assert path.name == f"{slugify('Main Run')}.loadorder.json"
    parsed, findings = parse_load_order(path.read_text("utf-8"))
    assert findings == []
    assert parsed == original
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_load_returns_the_saved_document(repo: ProfileRepository) -> None:
    original = doc("Main Run")
    repo.save(original)
    assert repo.load("Main Run") == original


def test_saving_over_an_existing_profile_needs_overwrite(repo: ProfileRepository) -> None:
    path = repo.save(doc("Run"))
    before = path.read_bytes()
    with pytest.raises(ProfileExistsError):
        repo.save(doc("Run", entry("other")))
    assert path.read_bytes() == before
    repo.save(doc("Run", entry("other")), overwrite=True)
    assert [e.save_identity.name for e in repo.load("Run").entries] == ["other"]
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_load_of_a_garbage_file_is_a_profile_format_error(repo: ProfileRepository) -> None:
    path = repo.save(doc("Run"))
    path.write_text("{this is not json", "utf-8")
    with pytest.raises(ProfileFormatError):
        repo.load("Run")


def test_list_describes_every_profile_and_flags_bad_ones_without_raising(
    repo: ProfileRepository, tmp_path: Path
) -> None:
    repo.save(doc("Alpha Run"))
    repo.save(doc("Beta Run", entry("only")))
    broken = tmp_path / "profiles" / "broken.loadorder.json"
    broken.write_text("{nope", "utf-8")
    (tmp_path / "profiles" / "notes.txt").write_text("ignore me", "utf-8")
    summaries = {s.path.name: s for s in repo.list()}
    assert set(summaries) == {
        f"{slugify('Alpha Run')}.loadorder.json",
        f"{slugify('Beta Run')}.loadorder.json",
        "broken.loadorder.json",
    }
    alpha = summaries[f"{slugify('Alpha Run')}.loadorder.json"]
    assert (alpha.name, alpha.entry_count, alpha.findings) == ("Alpha Run", 2, ())
    assert summaries[f"{slugify('Beta Run')}.loadorder.json"].entry_count == 1
    assert summaries["broken.loadorder.json"].findings
    assert broken.read_text("utf-8") == "{nope"


def test_list_of_an_empty_directory(repo: ProfileRepository) -> None:
    assert repo.list() == []


def test_rename_moves_the_file_and_the_name(repo: ProfileRepository) -> None:
    old_path = repo.save(doc("Old Name"))
    new_path = repo.rename("Old Name", "New Name")
    assert not old_path.exists()
    assert new_path.name == f"{slugify('New Name')}.loadorder.json"
    assert repo.load("New Name").name == "New Name"
    assert [s.name for s in repo.list()] == ["New Name"]


def test_rename_onto_an_existing_profile_is_refused(repo: ProfileRepository) -> None:
    a = repo.save(doc("A"))
    b = repo.save(doc("B", entry("only")))
    before = (a.read_bytes(), b.read_bytes())
    with pytest.raises(ProfileExistsError):
        repo.rename("A", "B")
    assert (a.read_bytes(), b.read_bytes()) == before


def test_delete(repo: ProfileRepository) -> None:
    path = repo.save(doc("Gone"))
    repo.save(doc("Kept"))
    repo.delete("Gone")
    assert not path.exists()
    assert [s.name for s in repo.list()] == ["Kept"]


def test_export_writes_a_standalone_document(repo: ProfileRepository, tmp_path: Path) -> None:
    original = doc("Shared")
    dest = tmp_path / "out" / "shared.json"
    dest.parent.mkdir()
    repo.export(original, dest)
    assert parse_load_order(dest.read_text("utf-8"))[0] == original
    assert dest.read_text("utf-8").strip() == dump_load_order(original).strip()
    assert [p.name for p in dest.parent.iterdir()] == ["shared.json"]


def test_import_of_an_exported_document(repo: ProfileRepository, tmp_path: Path) -> None:
    original = doc("Shared")
    dest = tmp_path / "shared.json"
    repo.export(original, dest)
    imported, extras = repo.import_file(dest)
    assert imported == original
    assert extras is None
    assert repo.list() == []


def test_import_of_a_v02_loadout(repo: ProfileRepository, tmp_path: Path) -> None:
    loadout = {
        "mods_path": "C:/mods",
        "order": ["2248772895", "0001_Local_Mod", "off_mod"],
        "enabled": {"2248772895": True, "0001_Local_Mod": True, "off_mod": False},
        "nicknames": {"0001_Local_Mod": "Nick"},
        "categories": {"2248772895": "Class"},
        "category_memory": {"The Chorus": "Class"},
    }
    source = tmp_path / "dd_mod_loadout.json"
    source.write_text(json.dumps(loadout), "utf-8")
    imported, extras = repo.import_file(source)
    assert [e.folder for e in imported.entries] == ["2248772895", "0001_Local_Mod", "off_mod"]
    assert [e.enabled for e in imported.entries] == [True, True, False]
    assert extras is not None
    assert dict(extras.nicknames) == {"0001_Local_Mod": "Nick"}
    assert dict(extras.categories) == {"2248772895": "Class"}
    assert dict(extras.category_memory) == {"The Chorus": "Class"}
    assert source.read_text("utf-8") == json.dumps(loadout)


@pytest.mark.parametrize(
    "content",
    ['{"something": "else"}', "[1, 2]", "not json at all", "", '{"order": [], "enabled": []}'],
)
def test_import_of_anything_else_is_a_profile_format_error(
    repo: ProfileRepository, tmp_path: Path, content: str
) -> None:
    source = tmp_path / "x.json"
    source.write_text(content, "utf-8")
    with pytest.raises(ProfileFormatError):
        repo.import_file(source)
