"""SaveSlotService: slot numbers, week chain, caching, label."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.core.findings import Severity
from src.core.ids import SaveIdentity
from src.core.saves import SaveFormatRegistry, default_registry
from src.core.saves.format import DsonScalar
from src.services.save_slots import (
    SaveSlot,
    SaveSlotService,
    profile_number_from_path,
    profile_sort_key,
    slot_label,
)
from tests.services.helpers import FakeFormat, fake_save_bytes
from tests.support.dson_builder import B, I, O, S, build_save


def write_fake(folder: Path, name: str, **scalars: DsonScalar) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(fake_save_bytes(scalars=scalars))
    return path


def write_dson(folder: Path, name: str, *nodes: Any) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(build_save(O("base_root", list(nodes))))
    return path


def stamp(path: Path, when: float = 1_700_000_000) -> None:
    os.utime(path, (when, when))


@pytest.fixture
def slots_fake(fake_clock_registry):
    registry, fmt, clock = fake_clock_registry
    return SaveSlotService(registry, clock=clock), fmt


@pytest.fixture
def fake_clock_registry(fixed_clock):
    fmt = FakeFormat()
    return SaveFormatRegistry([fmt]), fmt, fixed_clock


# ------------------------------------------------------------------ pure helpers


@pytest.mark.parametrize(
    ("path", "number"),
    [
        ("Darkest/profile_3/persist.game.json", 3),
        ("Darkest/profile 4/persist.game.json", 4),
        ("Darkest/Profile-5/persist.game.json", 5),
        ("Darkest/profile7/persist.game.json", 7),
        ("Darkest/PROFILE_10/persist.game.json", 10),
        ("Darkest/profile_1/profile_2/persist.game.json", 2),
        ("Darkest/profile_0/persist.game.json", 0),
        ("Darkest/slot_3/persist.game.json", None),
        ("Darkest/profile_a/persist.game.json", None),
        ("Darkest/myprofile_3/persist.game.json", None),
        ("Darkest/profile_3_old/persist.game.json", None),
    ],
)
def test_profile_number_from_path(path: str, number: int | None) -> None:
    assert profile_number_from_path(Path(path)) == number


def make_slot(path: Path, number: int | None) -> SaveSlot:
    return SaveSlot(path, path.parent, number, None, None, None, False)


def test_profile_sort_key_puts_unnumbered_last_then_by_path() -> None:
    a = make_slot(Path("B/profile_2/persist.game.json"), 2)
    b = make_slot(Path("a/profile_2/persist.game.json"), 2)
    c = make_slot(Path("a/x/persist.game.json"), None)
    d = make_slot(Path("a/profile_0/persist.game.json"), 0)
    assert profile_sort_key(c)[0] == 9999
    assert profile_sort_key(d)[0] == 0
    assert sorted([a, b, c, d], key=profile_sort_key) == [d, b, a, c]


# ------------------------------------------------------------------ slots()


def test_slots_are_sorted_deduplicated_and_described(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    p2 = write_fake(tmp_path / "Darkest" / "profile_2", "persist.game.json", date_time="2024-05-06")
    p10 = write_fake(tmp_path / "Darkest" / "profile_10", "persist.game.json")
    other = write_fake(tmp_path / "Darkest" / "misc", "persist.game.json")
    stamp(p2)
    slots = service.slots([p10, other, p2, p2])
    assert [s.save_path for s in slots] == [p2, p10, other]
    first = slots[0]
    assert (first.number, first.profile_dir, first.date_time) == (2, p2.parent, "2024-05-06")
    assert first.steam_cloud is False
    assert first.mtime is not None
    assert first.mtime.timestamp() == pytest.approx(1_700_000_000)
    assert first.mtime.tzinfo is not None
    assert slots[2].number is None


def test_steam_cloud_slots_are_flagged(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    cloud = write_fake(
        tmp_path / "Steam" / "userdata" / "1" / "262060" / "remote", "persist.game.json"
    )
    (slot,) = service.slots([cloud])
    assert slot.steam_cloud is True


def test_metadata_is_cached_by_mtime(slots_fake, tmp_path: Path) -> None:
    service, fmt = slots_fake
    path = write_fake(tmp_path / "profile_1", "persist.game.json", date_time="one")
    stamp(path)
    assert service.slots([path])[0].date_time == "one"
    calls = fmt.scalar_calls
    assert service.slots([path])[0].date_time == "one"
    assert fmt.scalar_calls == calls
    path.write_bytes(fake_save_bytes(scalars={"date_time": "two"}))
    stamp(path, 1_700_000_000)
    assert service.slots([path])[0].date_time == "one"
    stamp(path, 1_700_000_100)
    assert service.slots([path])[0].date_time == "two"


# ------------------------------------------------------------------ week chain


def week(service: SaveSlotService, folder: Path) -> int | None:
    return service.read_week(folder / "persist.game.json")


def test_inraid_chain_prefers_the_campaign_log(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    write_fake(tmp_path, "persist.game.json", inraid=True)
    write_fake(tmp_path, "persist.campaign_log.json", current_week=5, total_weeks=11)
    write_fake(tmp_path, "persist.estate.json", week=9)
    write_fake(tmp_path, "persist.town_event.json", last_town_event_week=3)
    assert week(service, tmp_path) == 5


def test_inraid_chain_falls_through_to_total_weeks_then_estate(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    write_fake(tmp_path, "persist.game.json", inraid=True)
    write_fake(tmp_path, "persist.campaign_log.json", total_weeks=11)
    write_fake(tmp_path, "persist.estate.json", week=9)
    assert week(service, tmp_path) == 11
    (tmp_path / "persist.campaign_log.json").unlink()
    assert week(service, tmp_path) == 9


def test_not_in_raid_chain_order_and_total_weeks_adjustment(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    write_fake(tmp_path, "persist.game.json", inraid=False)
    write_fake(tmp_path, "persist.campaign_log.json", current_week=6, total_weeks=8)
    assert week(service, tmp_path) == 6
    write_fake(tmp_path, "persist.estate.json", week=9)
    assert week(service, tmp_path) == 9
    write_fake(tmp_path, "persist.town_event.json", last_town_event_week=3)
    assert week(service, tmp_path) == 3
    for name in ("persist.town_event.json", "persist.estate.json"):
        (tmp_path / name).unlink()
    write_fake(tmp_path, "persist.campaign_log.json", total_weeks=8)
    assert week(service, tmp_path) == 7


def test_negative_and_non_numeric_values_are_skipped(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    write_fake(tmp_path, "persist.game.json", inraid=False)
    write_fake(tmp_path, "persist.town_event.json", last_town_event_week="soon")
    write_fake(tmp_path, "persist.estate.json", week=-4)
    write_fake(tmp_path, "persist.campaign_log.json", total_weeks=0)
    assert week(service, tmp_path) is None
    write_fake(tmp_path, "persist.campaign_log.json", total_weeks=3)
    assert week(service, tmp_path) == 2


def test_no_profile_files_means_no_week(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    assert week(service, tmp_path) is None


def test_missing_inraid_is_treated_as_not_in_raid(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    write_fake(tmp_path, "persist.game.json")
    write_fake(tmp_path, "persist.estate.json", week=4)
    write_fake(tmp_path, "persist.campaign_log.json", current_week=8)
    assert week(service, tmp_path) == 4


def test_fallback_scan_skips_backups_decoded_copies_and_number_of_weeks(
    tmp_path: Path, fixed_clock
) -> None:
    service = SaveSlotService(default_registry(), clock=fixed_clock)
    write_dson(tmp_path, "persist.game.json", B("inraid", False))
    write_dson(tmp_path, "persist.game.backup.20240101-000000.json", I("week", 99))
    write_dson(tmp_path, "persist.aaa.decoded.json", I("week", 77))
    write_dson(tmp_path, "persist.bbb.json", I("number_of_weeks_total", 55))
    write_dson(tmp_path, "persist.zz_extra.json", I("some_week_counter", 12))
    assert week(service, tmp_path) == 12
    (tmp_path / "persist.zz_extra.json").unlink()
    assert week(service, tmp_path) is None


# ------------------------------------------------------------------ applied entries, latest


def test_applied_entries_and_their_cache(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    path = tmp_path / "profile_0" / "persist.game.json"
    path.parent.mkdir()
    path.write_bytes(fake_save_bytes([("1", "Steam"), ("Loc", "mod_local_source")]))
    stamp(path)
    expected = (SaveIdentity("1", "Steam"), SaveIdentity("Loc", "mod_local_source"))
    assert service.applied_entries(path) == expected
    path.write_bytes(fake_save_bytes([("2", "Steam")]))
    stamp(path)
    assert service.applied_entries(path) == expected
    stamp(path, 1_700_000_500)
    assert service.applied_entries(path) == (SaveIdentity("2", "Steam"),)


def test_unreadable_applied_entries_are_empty_and_reported_on_the_slot(
    slots_fake, tmp_path: Path
) -> None:
    service, _ = slots_fake
    path = tmp_path / "profile_0" / "persist.game.json"
    path.parent.mkdir()
    path.write_bytes(b"FAKE{broken")
    assert service.applied_entries(path) == ()
    (slot,) = service.slots([path])
    assert slot.findings
    assert all(f.severity >= Severity.WARNING for f in slot.findings)


def test_real_dson_applied_entries(tmp_path: Path, fixed_clock) -> None:
    from tests.support.dson_builder import THREE_ENTRIES, standard_save
    from tests.support.identities import identities

    path = tmp_path / "profile_0" / "persist.game.json"
    path.parent.mkdir()
    path.write_bytes(standard_save(THREE_ENTRIES))
    service = SaveSlotService(default_registry(), clock=fixed_clock)
    assert service.applied_entries(path) == identities(THREE_ENTRIES)


def test_latest_is_the_newest_existing_file(slots_fake, tmp_path: Path) -> None:
    service, _ = slots_fake
    old = write_fake(tmp_path / "a", "persist.game.json")
    new = write_fake(tmp_path / "b", "persist.game.json")
    gone = tmp_path / "gone" / "persist.game.json"
    stamp(old, 1_600_000_000)
    stamp(new, 1_700_000_000)
    assert service.latest([old, gone, new]) == new
    assert service.latest([gone]) is None
    assert service.latest([]) is None


# ------------------------------------------------------------------ label


def build_profile(root: Path, folder: str, *, date_time: str | None, week: int | None) -> Path:
    base = root / "Darkest" / folder
    nodes: list[Any] = [B("inraid", False), S("estatename", "Hamlet")]
    if date_time is not None:
        nodes.append(S("date_time", date_time))
    path = write_dson(base, "persist.game.json", *nodes)
    if week is not None:
        write_dson(base, "persist.estate.json", I("week", week))
    stamp(path)
    return path


def test_label_falls_back_to_the_file_mtime_in_local_time(tmp_path: Path, fixed_clock) -> None:
    path = build_profile(tmp_path, "profile_1", date_time=None, week=None)
    (slot,) = SaveSlotService(default_registry(), clock=fixed_clock).slots([path])
    expected = datetime.fromtimestamp(path.stat().st_mtime).strftime(  # noqa: DTZ006 - local time on purpose
        "%Y-%m-%d %H:%M"
    )
    assert expected in slot_label(slot)


def test_label_shapes() -> None:
    path = Path("C:/Darkest/profile_3/persist.game.json")
    slot = SaveSlot(path, path.parent, 3, "2024-05-06", 9, None, False)
    assert slot_label(slot) == "Profile 3 (slot 4) - 2024-05-06 - Week 9 [profile_3]"
    anonymous = SaveSlot(
        Path("C:/x/slotz/persist.game.json"), Path("C:/x/slotz"), None, "d", None, None, False
    )
    assert slot_label(anonymous) == "Unknown Profile - d [slotz]"
