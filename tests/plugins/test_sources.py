"""The built-in mod sources and the Nexus example plugin."""

import json
from pathlib import Path

from src.core.ids import ModId, SourceKind
from src.core.model import ModSnapshot
from src.plugins import BUILTIN_SOURCES
from src.plugins.local_folder import LocalFolderSource
from src.plugins.nexus_example import NexusSource, register
from src.plugins.steam_workshop import SteamWorkshopSource
from src.services.plugin_registry import PluginRegistry
from src.services.sources import ReadContext
from tests.services.helpers import TZ, make_install
from tests.support import factories

WORKSHOP_TAIL = ("steamapps", "workshop", "content", "262060")


def ctx(acf: dict[str, str] | None = None) -> ReadContext:
    return ReadContext(acf_times=acf or {}, tz=TZ)


def workshop_root(tmp_path: Path) -> Path:
    return tmp_path.joinpath("Steam", *WORKSHOP_TAIL)


def names(locations) -> list[str]:
    return [str(loc.path.name) for loc in locations]


def test_builtin_registry_order_and_identity() -> None:
    steam, local = BUILTIN_SOURCES
    assert isinstance(steam, SteamWorkshopSource)
    assert isinstance(local, LocalFolderSource)
    assert (steam.source_id, steam.display_name, steam.claim_priority) == (
        "steam",
        "Steam Workshop",
        50,
    )
    assert (local.source_id, local.display_name, local.claim_priority) == (
        "local",
        "Local mods",
        100,
    )


def test_local_discovers_direct_subdirectories_of_non_workshop_roots_in_root_order(
    mod_dir, tmp_path: Path
) -> None:
    first, second, workshop = tmp_path / "b_root", tmp_path / "a_root", workshop_root(tmp_path)
    mod_dir(first, "zeta", title="Z")
    mod_dir(first, "__temp__x", title="T")
    mod_dir(second, "alpha", title="A")
    mod_dir(workshop, "1111111", title="W")
    (first / "file.txt").write_text("x", "utf-8")
    (first / "zeta" / "nested").mkdir()
    locations = list(LocalFolderSource().discover(make_install([first, workshop, second])))
    assert [loc.root for loc in locations] == [first, first, second]
    assert {loc.path for loc in locations[:2]} == {first / "zeta", first / "__temp__x"}
    assert locations[2].path == second / "alpha"
    assert {loc.source_id for loc in locations} == {"local"}
    assert {loc.root for loc in locations} == {first, second}
    assert {loc.key for loc in locations} == {ModId("zeta"), ModId("__temp__x"), ModId("alpha")}


def test_steam_discovers_only_workshop_roots(mod_dir, tmp_path: Path) -> None:
    local, workshop = tmp_path / "mods", workshop_root(tmp_path)
    mod_dir(local, "plain", title="P")
    mod_dir(workshop, "1111111", title="W1")
    mod_dir(workshop, "2222222", title="W2")
    other = tmp_path.joinpath("Steam", "steamapps", "workshop", "content", "2620601")
    mod_dir(other, "3333333", title="Other app")
    locations = list(SteamWorkshopSource().discover(make_install([local, workshop, other])))
    assert sorted(names(locations)) == ["1111111", "2222222"]
    assert {loc.source_id for loc in locations} == {"steam"}
    assert {loc.root for loc in locations} == {workshop}


def test_local_snapshot_is_a_local_read(mod_dir, tmp_path: Path) -> None:
    folder = mod_dir(tmp_path / "mods", "1234567_cool", title="Cool")
    source = LocalFolderSource()
    (location,) = source.discover(make_install([tmp_path / "mods"]))
    snap = source.snapshot(location, ctx({"1234567": "1731672000"}))
    assert isinstance(snap, ModSnapshot)
    assert (snap.source_id, snap.kind, snap.under_workshop) == ("local", SourceKind.LOCAL, False)
    assert snap.path_workshop_id == ""
    assert snap.acf_timeupdated == ""
    assert str(snap.path) == str(folder)


def test_steam_snapshot_resolves_the_workshop_id_and_acf(mod_dir, tmp_path: Path) -> None:
    workshop = workshop_root(tmp_path)
    mod_dir(workshop, "1234567890", title="Cloud", published_id="1234567890")
    mod_dir(workshop, "1234567_named_mod", title="Named")
    source = SteamWorkshopSource()
    by_name = {loc.path.name: loc for loc in source.discover(make_install([workshop]))}
    snap = source.snapshot(by_name["1234567890"], ctx({"1234567890": "1731672000"}))
    assert (snap.source_id, snap.kind, snap.under_workshop) == ("steam", SourceKind.WORKSHOP, True)
    assert (snap.path_workshop_id, snap.acf_timeupdated) == ("1234567890", "1731672000")
    named = source.snapshot(by_name["1234567_named_mod"], ctx({"1234567": "5"}))
    assert (named.path_workshop_id, named.acf_timeupdated) == ("1234567", "5")


def test_page_urls() -> None:
    steam, local = BUILTIN_SOURCES
    workshop_mod = factories.workshop_mod("1234567890")
    assert steam.page_url(workshop_mod) == (
        "https://steamcommunity.com/sharedfiles/filedetails/?id=1234567890"
    )
    assert steam.page_url(factories.local_mod("plain")) is None
    assert local.page_url(factories.local_mod("plain")) is None
    assert local.page_url(workshop_mod) is None


# ------------------------------------------------------------------ nexus example


def test_nexus_is_documentation_not_builtin() -> None:
    assert all(not isinstance(s, NexusSource) for s in BUILTIN_SOURCES)
    source = NexusSource()
    assert (source.source_id, source.claim_priority) == ("nexus", 10)
    assert source.claim_priority < BUILTIN_SOURCES[0].claim_priority


def test_nexus_claims_only_folders_with_a_sidecar(mod_dir, tmp_path: Path) -> None:
    root = tmp_path / "mods"
    claimed = mod_dir(root, "from_nexus", title="Nexus mod")
    mod_dir(root, "plain", title="Plain")
    (claimed / "nexus.json").write_text(json.dumps({"mod_id": 123}), "utf-8")
    source = NexusSource()
    (location,) = source.discover(make_install([root]))
    assert (location.path, location.source_id, location.key) == (claimed, "nexus", "from_nexus")
    assert ("mod_id", "123") in location.extra


def test_nexus_identity_equals_the_local_read(mod_dir, tmp_path: Path) -> None:
    root = tmp_path / "mods"
    folder = mod_dir(root, "from_nexus", title="Nexus mod")
    (folder / "nexus.json").write_text(json.dumps({"mod_id": 123}), "utf-8")
    (nexus_loc,) = NexusSource().discover(make_install([root]))
    local_loc = next(
        loc for loc in LocalFolderSource().discover(make_install([root])) if loc.path == folder
    )
    nexus_snap = NexusSource().snapshot(nexus_loc, ctx())
    local_snap = LocalFolderSource().snapshot(local_loc, ctx())
    assert nexus_snap.source_id == "nexus"
    assert nexus_snap.project == local_snap.project
    assert nexus_snap.files == local_snap.files
    assert nexus_snap.kind is local_snap.kind
    assert nexus_snap.path_workshop_id == local_snap.path_workshop_id


def test_nexus_page_url_points_at_nexusmods() -> None:
    url = NexusSource().page_url(factories.local_mod("from_nexus"))
    assert url is None or url.startswith("https://www.nexusmods.com/")


def test_nexus_register_adds_the_source() -> None:
    registry = PluginRegistry()
    register(registry)
    assert [s.source_id for s in registry.mod_sources] == ["nexus"]
