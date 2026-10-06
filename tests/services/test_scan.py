"""ScanService: discovery, path claims, first-root-wins shadowing, findings, determinism."""

from collections.abc import Iterable
from pathlib import Path

import pytest

from src.core.findings import Severity
from src.core.ids import ModId, SourceKind
from src.core.model import ModInfo, ModSnapshot
from src.plugins import BUILTIN_SOURCES
from src.services.detection import InstallSnapshot
from src.services.mod_reader import snapshot_mod_folder
from src.services.scan import ScanService
from src.services.sources import ModLocation, ReadContext
from tests.services.helpers import TZ, make_install


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

    def discover(self, install: InstallSnapshot) -> Iterable[ModLocation]:
        if self.fail_discover:
            raise RuntimeError("discover exploded")
        for folder in self.folders:
            yield ModLocation(self.source_id, ModId(folder.name), folder, folder.parent)

    def snapshot(self, location: ModLocation, ctx: ReadContext) -> ModSnapshot:
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
