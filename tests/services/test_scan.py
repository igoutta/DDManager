"""ScanService: discovery, path claims, first-root-wins shadowing, findings, determinism, and
the metadata cache (a second scan reads nothing; every kind of change on disk invalidates)."""

import dataclasses
from collections.abc import Callable, Iterable
from datetime import timedelta
from pathlib import Path

import pytest

from src.core.findings import Severity
from src.core.ids import ModId, SourceKind
from src.core.model import ModInfo, ModSnapshot
from src.plugins import BUILTIN_SOURCES
from src.services.detection import InstallSnapshot
from src.services.errors import SaveLockedError
from src.services.metadata_cache import MetadataCache, cache_key
from src.services.mod_reader import signature_of, snapshot_mod_folder
from src.services.scan import ScanService, scan_with_cache
from src.services.sources import ModLocation, ReadContext
from tests.services.helpers import NOW, TZ, acf_text, make_install, set_mtime


class StubSource:
    """A configurable ModSource over explicit folders."""

    def __init__(
        self,
        source_id: str,
        priority: int,
        folders: Iterable[Path],
        *,
        fail_discover: bool = False,
        fail_on: str | None = None,
    ) -> None:
        self.source_id = source_id
        self.display_name = source_id
        self.claim_priority = priority
        self.folders = list(folders)
        self.fail_discover = fail_discover
        self.fail_on = fail_on
        self.snapshots = 0

    def discover(self, install: InstallSnapshot) -> Iterable[ModLocation]:
        if self.fail_discover:
            raise RuntimeError("discover exploded")
        for folder in self.folders:
            yield ModLocation(self.source_id, ModId(folder.name), folder, folder.parent)

    def snapshot(self, location: ModLocation, ctx: ReadContext) -> ModSnapshot:
        self.snapshots += 1
        if location.path.name == self.fail_on:
            raise PermissionError("cannot read folder")
        return snapshot_mod_folder(
            location.path,
            root=location.root,
            source_id=self.source_id,
            kind=SourceKind.LOCAL,
            under_workshop=False,
            workshop_id="",
            ctx=ctx,
        )

    def page_url(self, info: ModInfo) -> str | None:
        return None


def service(sources, clock) -> ScanService:
    return ScanService(sources, clock=clock, tz=TZ)


def rule_ids(result) -> list[str]:
    return [f.rule_id for f in result.findings]


def test_builtin_sources_find_local_and_workshop_mods(mod_dir, tmp_path: Path, fixed_clock) -> None:
    local = tmp_path / "game" / "mods"
    workshop = tmp_path / "Steam" / "steamapps" / "workshop" / "content" / "262060"
    mod_dir(local, "Bravo_mod", title="Bravo")
    mod_dir(local, "alpha_mod", title="Alpha")
    mod_dir(workshop, "1234567890", title="Cloud", published_id="1234567890")
    (local / "stray.txt").write_text("not a mod", "utf-8")
    result = service(BUILTIN_SOURCES, fixed_clock).scan(make_install([local, workshop]))
    assert list(result.mods) == ["1234567890", "alpha_mod", "Bravo_mod"]
    cloud = result.mods[ModId("1234567890")]
    assert (cloud.kind, cloud.source_id, cloud.workshop_id) == (
        SourceKind.WORKSHOP,
        "steam",
        "1234567890",
    )
    assert cloud.save_identity.as_tuple() == ("1234567890", "Steam")
    alpha = result.mods[ModId("alpha_mod")]
    assert (alpha.kind, alpha.source_id) == (SourceKind.LOCAL, "local")
    assert alpha.save_identity.as_tuple() == ("Alpha", "mod_local_source")
    assert result.findings == ()
    assert result.shadowed == {}
    assert result.locations[ModId("alpha_mod")].path == local / "alpha_mod"
    assert result.locations[ModId("1234567890")].source_id == "steam"


def test_keys_are_casefold_sorted_whatever_the_discovery_order(
    mod_dir, tmp_path: Path, fixed_clock
) -> None:
    folders = [
        mod_dir(tmp_path, name, title=name) for name in ("charlie", "Bravo", "alpha", "Delta")
    ]
    forward = service([StubSource("s", 100, folders)], fixed_clock).scan(make_install([tmp_path]))
    backward = service([StubSource("s", 100, folders[::-1])], fixed_clock).scan(
        make_install([tmp_path])
    )
    assert list(forward.mods) == ["alpha", "Bravo", "charlie", "Delta"]
    assert list(backward.mods) == list(forward.mods)
    assert backward.mods == forward.mods


def test_first_root_wins_and_the_loser_is_reported_shadowed(
    mod_dir, tmp_path: Path, fixed_clock
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    mod_dir(first, "dup", title="First Dup")
    mod_dir(first, "only_first", title="One")
    mod_dir(second, "dup", title="Second Dup")
    mod_dir(second, "only_second", title="Two")
    result = service(BUILTIN_SOURCES, fixed_clock).scan(make_install([first, second]))
    assert list(result.mods) == ["dup", "only_first", "only_second"]
    assert result.mods[ModId("dup")].path == first / "dup"
    assert result.mods[ModId("dup")].title == "First Dup"
    assert result.shadowed == {"dup": (second / "dup",)}
    (finding,) = result.findings
    assert (finding.rule_id, finding.severity) == ("scan.shadowed", Severity.WARNING)
    assert finding.mod_ids == ("dup",)


def test_sample_mods_in_two_roots_are_all_shadowed_by_the_first(
    sample_mods_dir: Path, modding_copy: Path, fixed_clock
) -> None:
    install = make_install([sample_mods_dir, modding_copy])
    result = service(BUILTIN_SOURCES, fixed_clock).scan(install)
    names = sorted((p.name for p in sample_mods_dir.iterdir() if p.is_dir()), key=str.casefold)
    assert list(result.mods) == names
    assert all(result.mods[ModId(n)].path == sample_mods_dir / n for n in names)
    assert dict(result.shadowed) == {n: (modding_copy / n,) for n in names}
    assert rule_ids(result) == ["scan.shadowed"] * len(names)


def test_same_path_is_claimed_by_the_lowest_priority_number(
    mod_dir, tmp_path: Path, fixed_clock
) -> None:
    folder = mod_dir(tmp_path, "shared", title="Shared")
    late = StubSource("late", 100, [folder])
    early = StubSource("early", 50, [folder])
    result = service([late, early], fixed_clock).scan(make_install([tmp_path]))
    assert result.mods[ModId("shared")].source_id == "early"
    assert result.locations[ModId("shared")].source_id == "early"
    assert result.shadowed == {}
    assert result.findings == ()


def test_path_claim_ignores_case_and_trailing_separators(
    mod_dir, tmp_path: Path, fixed_clock
) -> None:
    folder = mod_dir(tmp_path, "shared", title="Shared")
    spelled = Path(str(folder).upper() + "/")
    early = StubSource("early", 10, [folder])
    late = StubSource("late", 90, [spelled])
    result = service([late, early], fixed_clock).scan(make_install([tmp_path]))
    assert result.mods[ModId("shared")].source_id == "early"


def test_temp_folders_are_listed_with_an_info_finding(mod_dir, tmp_path: Path, fixed_clock) -> None:
    mod_dir(tmp_path, "__temp__20250101-000000__0001_mod", title="Half renamed")
    mod_dir(tmp_path, "fine", title="Fine")
    result = service(BUILTIN_SOURCES, fixed_clock).scan(make_install([tmp_path]))
    assert "__temp__20250101-000000__0001_mod" in result.mods
    (finding,) = result.findings
    assert (finding.rule_id, finding.severity) == ("scan.temp_folder", Severity.INFO)
    assert finding.mod_ids == ("__temp__20250101-000000__0001_mod",)


def test_a_failing_source_is_a_finding_and_the_scan_continues(
    mod_dir, tmp_path: Path, fixed_clock
) -> None:
    folder = mod_dir(tmp_path, "ok", title="Ok")
    broken = StubSource("broken", 10, [], fail_discover=True)
    good = StubSource("good", 100, [folder])
    result = service([broken, good], fixed_clock).scan(make_install([tmp_path]))
    assert list(result.mods) == ["ok"]
    assert rule_ids(result) == ["scan.source_failed"]
    assert "broken" in result.findings[0].message


def test_an_unreadable_folder_is_skipped_with_a_finding(
    mod_dir, tmp_path: Path, fixed_clock
) -> None:
    good = mod_dir(tmp_path, "good", title="Good")
    bad = mod_dir(tmp_path, "bad", title="Bad")
    source = StubSource("s", 100, [bad, good], fail_on="bad")
    result = service([source], fixed_clock).scan(make_install([tmp_path]))
    assert list(result.mods) == ["good"]
    assert "bad" not in result.locations
    (finding,) = result.findings
    assert finding.rule_id == "scan.mod_unreadable"
    assert finding.mod_ids == ("bad",)


def test_local_source_skips_workshop_roots_and_steam_skips_local_roots(
    mod_dir, tmp_path: Path, fixed_clock
) -> None:
    local = tmp_path / "mods"
    workshop = tmp_path / "steamapps" / "workshop" / "content" / "262060"
    mod_dir(local, "l1", title="L")
    mod_dir(workshop, "1111111", title="W", published_id="1111111")
    install = make_install([local, workshop])
    local_only = service([BUILTIN_SOURCES[1]], fixed_clock).scan(install)
    steam_only = service([BUILTIN_SOURCES[0]], fixed_clock).scan(install)
    assert list(local_only.mods) == ["l1"]
    assert list(steam_only.mods) == ["1111111"]


@pytest.mark.parametrize("n", [0, 1])
def test_empty_roots_scan_cleanly(tmp_path: Path, fixed_clock, n: int) -> None:
    roots = [tmp_path] if n else []
    result = service(BUILTIN_SOURCES, fixed_clock).scan(make_install(roots))
    assert (dict(result.mods), result.findings, dict(result.shadowed)) == ({}, (), {})


# ------------------------------------------------------------------ the metadata cache

FILES = ("heroes/abomination/abomination.art.darkest", "localization/x.string_table.xml")


class CachedWorld:
    """Two local mods, a scanner over one stub source and a cache file to scan through."""

    def __init__(self, mod_dir, tmp_path: Path, clock) -> None:
        self.root = tmp_path / "mods"
        self.folders = {
            name: mod_dir(self.root, name, title=name.title(), files=FILES)
            for name in ("alpha", "bravo")
        }
        for folder in self.folders.values():
            set_mtime(folder / "heroes", NOW - timedelta(days=1))
            set_mtime(folder, NOW - timedelta(days=1))
        self.source = StubSource("s", 100, list(self.folders.values()))
        self.scanner = service([self.source], clock)
        self.install = make_install([self.root])
        self.cache_file = tmp_path / "cache" / "mod_info.v1.json"

    def scan(self):
        cache, findings = MetadataCache.load(self.cache_file)
        assert findings == []
        return scan_with_cache(self.scanner, cache, self.install)

    def key(self, name: str) -> str:
        return cache_key("s", self.folders[name])


@pytest.fixture
def cached(mod_dir, tmp_path: Path, fixed_clock) -> CachedWorld:
    return CachedWorld(mod_dir, tmp_path, fixed_clock)


def test_a_second_scan_reuses_the_cache_and_reads_no_folder(cached: CachedWorld) -> None:
    first = cached.scan()
    assert (cached.source.snapshots, first.cache_hits) == (2, 0)
    assert sorted(first.cache_updates) == sorted(cached.key(n) for n in ("alpha", "bravo"))
    assert cached.cache_file.is_file(), "the cache is saved after the scan"
    second = cached.scan()
    assert (cached.source.snapshots, second.cache_hits) == (2, 2)
    assert dict(second.cache_updates) == {}
    assert second.mods == first.mods
    assert second.mods[ModId("alpha")].files == frozenset(FILES), "the manifest comes along"
    assert second.locations == first.locations


def touch_project(folder: Path) -> None:
    set_mtime(folder / "project.xml", NOW + timedelta(hours=1))


def add_content_file(folder: Path) -> None:
    (folder / "heroes" / "new_hero.art.darkest").write_bytes(b"x")


def add_localization(folder: Path) -> None:
    (folder / "localization" / "y.string_table.xml").write_bytes(b"<root/>")


def remove_top_level_dir(folder: Path) -> None:
    for file in (folder / "localization").iterdir():
        file.unlink()
    (folder / "localization").rmdir()


@pytest.mark.parametrize(
    "change", [touch_project, add_content_file, add_localization, remove_top_level_dir]
)
def test_a_change_on_disk_invalidates_only_that_mod(
    cached: CachedWorld, change: Callable[[Path], None]
) -> None:
    first = cached.scan()
    change(cached.folders["bravo"])
    second = cached.scan()
    assert (cached.source.snapshots, second.cache_hits) == (3, 1)
    assert list(second.cache_updates) == [cached.key("bravo")]
    assert second.mods[ModId("alpha")] == first.mods[ModId("alpha")]
    bravo = second.mods[ModId("bravo")]
    assert bravo.signature != first.mods[ModId("bravo")].signature
    if change is add_content_file:
        assert "heroes/new_hero.art.darkest" in bravo.files, "overlap detection sees new files"
    third = cached.scan()
    assert (cached.source.snapshots, third.cache_hits) == (3, 2)


def test_a_mod_that_vanished_is_swept_from_the_cache(cached: CachedWorld) -> None:
    cached.scan()
    cached.source.folders.remove(cached.folders["bravo"])
    result = cached.scan()
    assert list(result.mods) == ["alpha"]
    cache, _ = MetadataCache.load(cached.cache_file)
    assert len(cache) == 1
    assert cache.lookup(cached.key("bravo"), result.mods[ModId("alpha")].signature) is None


def test_signature_of_equals_the_derived_signature_for_workshop_and_local_mods(
    mod_dir, tmp_path: Path, fixed_clock
) -> None:
    """The invariant the cache rests on: the cheap key is the key the full read produces."""
    local = tmp_path / "game" / "mods"
    workshop = tmp_path / "Steam" / "steamapps" / "workshop" / "content" / "262060"
    mod_dir(local, "alpha_mod", title="Alpha", files=FILES)
    mod_dir(workshop, "1234567890", title="Cloud", published_id="1234567890", files=FILES)
    mod_dir(workshop, "renamed_777", title="Moved", published_id="1234567891", files=FILES)
    acf = tmp_path / "appworkshop_262060.acf"
    acf.write_text(acf_text({"1234567890": "17316", "1234567891": "17999"}), "utf-8")
    install = dataclasses.replace(make_install([local, workshop]), acf_files=(acf,))
    result = service(BUILTIN_SOURCES, fixed_clock).scan(install)
    ctx = ReadContext(acf_times={"1234567890": "17316", "1234567891": "17999"}, tz=TZ)
    for key, info in result.mods.items():
        assert signature_of(result.locations[key], ctx) == info.signature, key
    assert result.mods[ModId("renamed_777")].signature.workshop_timeupdated == "17999", (
        "the project's PublishedFileId selects the ACF time, as the full read does"
    )
    assert all(i.signature.content_roots_mtime_ns is not None for i in result.mods.values())


@pytest.mark.parametrize(
    "failure",
    [OSError("disk full"), SaveLockedError("locked", path="x", attempts=1)],
    ids=["os_error", "locked"],
)
def test_a_cache_that_cannot_be_saved_is_a_finding_and_the_scan_stands(
    cached: CachedWorld, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(MetadataCache, "save", broken)
    cache, _ = MetadataCache.load(cached.cache_file)
    result = scan_with_cache(cached.scanner, cache, cached.install)
    assert sorted(result.mods) == ["alpha", "bravo"]
    assert rule_ids(result) == ["cache.not_saved"]
    assert result.findings[0].severity is Severity.WARNING
    assert not cached.cache_file.exists()


def test_a_cancelled_scan_sweeps_nothing(cached: CachedWorld) -> None:
    cached.scan()

    class AfterOne:
        count = 0

        def is_cancelled(self) -> bool:
            self.count += 1
            return self.count > 1

    cache, _ = MetadataCache.load(cached.cache_file)
    result = cached.scanner.scan(cached.install, cache=cache, cancel=AfterOne())
    assert result.cancelled and list(result.mods) == ["alpha"]
    from src.services.scan import remember_scan

    assert remember_scan(cache, result) is None
    assert len(cache) == 2
