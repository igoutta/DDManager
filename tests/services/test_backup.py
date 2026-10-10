"""BackupService: managed copies, listing, retention policy, verify, restore."""

import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.services.backup import (
    BESIDE_SAVE_BACKUP_RE,
    BackupReason,
    BackupService,
)
from src.services.errors import BackupInvalidError, BackupNotFoundError, GameRunningError
from src.services.fsutil import backup_timestamp
from src.services.ports import FixedClock, RunState
from src.services.settings_repo import RetentionPolicy
from tests.services.helpers import NOW, fake_save_bytes, set_mtime

A = fake_save_bytes([("1111111", "Steam")])
B = fake_save_bytes([("Other", "mod_local_source")])


@pytest.fixture
def save_path(tmp_path: Path) -> Path:
    path = tmp_path / "Darkest" / "profile_0" / "persist.game.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(A)
    return path


@pytest.fixture
def make(app_paths, fake_registry, fake_probe):
    def build(at: datetime = NOW, policy: RetentionPolicy | None = None, probe=None):
        return BackupService(
            app_paths,
            fake_registry,
            clock=FixedClock(at),
            probe=probe or fake_probe(RunState.NOT_RUNNING),
            policy=policy or RetentionPolicy(),
        )

    return build


def managed_files(service: BackupService, save_path: Path) -> list[str]:
    return sorted(p.name for p in service.slot_dir(save_path).glob("persist.game.backup.*.json"))


def make_aged(make, save_path: Path, ages_days: list[float]) -> list:
    """Create one backup per age (oldest first) under a huge policy so nothing is pruned."""
    records = []
    for age in sorted(ages_days, reverse=True):
        service = make(
            NOW - timedelta(days=age), RetentionPolicy(keep_last=10_000, keep_days=10_000)
        )
        records.append(service.create(save_path, reason=BackupReason.MANUAL))
    return records


def test_slot_dir_is_named_after_the_save_dir_and_a_hash_of_its_full_path(
    make, app_paths, save_path: Path
) -> None:
    digest = hashlib.sha1(str(save_path.parent.absolute()).casefold().encode("utf-8")).hexdigest()
    assert make().slot_dir(save_path) == app_paths.backups_dir / f"profile_0-{digest[:8]}"
    other = save_path.parent.parent / "elsewhere" / "profile_0" / "persist.game.json"
    assert make().slot_dir(other) != make().slot_dir(save_path)


def test_create_copies_the_save_into_the_managed_slot(make, app_paths, save_path: Path) -> None:
    service = make()
    record = service.create(save_path, reason=BackupReason.PRE_PATCH)
    assert record.path.parent == service.slot_dir(save_path)
    assert record.path.name == f"persist.game.backup.{backup_timestamp(NOW)}.json"
    assert record.path.read_bytes() == A
    assert save_path.read_bytes() == A
    assert (record.save_path, record.reason, record.location) == (
        save_path,
        BackupReason.PRE_PATCH,
        "managed",
    )
    assert record.created == NOW
    assert record.size == len(A)
    assert record.sha256 == hashlib.sha256(A).hexdigest()
    assert app_paths.backups_dir in record.path.parents
    assert not [p for p in record.path.parent.iterdir() if p.name.endswith(".tmp")]


def test_create_with_raw_backs_up_those_bytes(make, save_path: Path) -> None:
    record = make().create(save_path, reason=BackupReason.PRE_PATCH, raw=B)
    assert record.path.read_bytes() == B
    assert record.sha256 == hashlib.sha256(B).hexdigest()
    assert save_path.read_bytes() == A


def test_two_backups_in_one_second_get_a_numeric_suffix(make, save_path: Path) -> None:
    service = make()
    first = service.create(save_path, reason=BackupReason.MANUAL)
    second = service.create(save_path, reason=BackupReason.MANUAL)
    stamp = backup_timestamp(NOW)
    assert first.path.name == f"persist.game.backup.{stamp}.json"
    assert second.path.name == f"persist.game.backup.{stamp}-2.json"
    assert BESIDE_SAVE_BACKUP_RE.match(second.path.name)


def test_index_records_the_metadata(make, save_path: Path) -> None:
    service = make()
    record = service.create(save_path, reason=BackupReason.PRE_RESTORE)
    index = json.loads((service.slot_dir(save_path) / "index.json").read_text("utf-8"))
    assert index["format"] == "ddmanager.backup-index"
    assert index["format_version"] == 1
    assert index["save_path"] == str(save_path)
    (entry,) = index["entries"]
    assert entry["file"] == record.path.name
    assert entry["reason"] == "pre-restore"
    assert entry["size"] == len(A)
    assert entry["sha256"] == record.sha256
    assert "created" in entry


def test_list_is_newest_first_and_latest_agrees(make, save_path: Path) -> None:
    records = [
        make(NOW + timedelta(minutes=m)).create(save_path, reason=BackupReason.MANUAL)
        for m in (0, 5, 10)
    ]
    service = make(NOW + timedelta(hours=1))
    listed = service.list(save_path)
    assert [r.path for r in listed] == [r.path for r in reversed(records)]
    assert [r.reason for r in listed] == [BackupReason.MANUAL] * 3
    assert service.latest(save_path) == listed[0]


def test_latest_is_none_without_backups(make, save_path: Path) -> None:
    assert make().latest(save_path) is None
    assert make().list(save_path) == []


def test_beside_save_backups_are_listed_but_flagged(make, save_path: Path) -> None:
    beside = save_path.parent / "persist.game.backup.20200102-030405.json"
    beside.write_bytes(A)
    (save_path.parent / "persist.game.backup.20200102-030405-2.json").write_bytes(A)
    (save_path.parent / "persist.game.backup.notatimestamp.json").write_bytes(A)
    (save_path.parent / "persist.estate.json").write_bytes(A)
    service = make()
    managed = service.create(save_path, reason=BackupReason.MANUAL)
    listed = service.list(save_path)
    assert listed[0] == managed
    old = listed[1:]
    assert {r.path.name for r in old} == {beside.name, "persist.game.backup.20200102-030405-2.json"}
    assert all((r.location, r.reason, r.sha256) == ("beside_save", None, None) for r in old)
    assert all(r.created.year == 2020 and r.size == len(A) for r in old)
    assert [r.path for r in service.list(save_path, include_beside_save=False)] == [managed.path]


def test_verify(make, save_path: Path) -> None:
    service = make()
    record = service.create(save_path, reason=BackupReason.MANUAL)
    assert service.verify(record) == []
    record.path.write_bytes(B)
    assert service.verify(record)
    record.path.unlink()
    assert service.verify(record)


def test_verify_flags_a_beside_save_backup_that_fails_its_format_check(
    make, save_path: Path
) -> None:
    beside = save_path.parent / "persist.game.backup.20200102-030405.json"
    beside.write_bytes(A)
    service = make()
    (record,) = service.list(save_path)
    assert service.verify(record) == []
    beside.write_bytes(A + b"CORRUPT")
    assert service.verify(record)


def test_prune_policy_over_25_backups_in_40_days(make, save_path: Path) -> None:
    ages = [i * 1.6 for i in range(25)]
    records = make_aged(make, save_path, ages)
    by_age = dict(zip(sorted(ages, reverse=True), records, strict=True))
    newest_20 = {by_age[a].path for a in sorted(ages)[:20]}
    oldest_5 = {by_age[a].path for a in sorted(ages)[20:]}
    service = make(NOW, RetentionPolicy(keep_last=20, keep_days=30, min_keep=3))
    dry = service.prune(save_path, dry_run=True)
    assert set(dry.deleted) == oldest_5
    assert set(dry.kept) == newest_20
    assert all(p.exists() for p in oldest_5)
    report = service.prune(save_path)
    assert set(report.deleted) == oldest_5
    assert set(report.kept) == newest_20
    assert not any(p.exists() for p in oldest_5)
    assert all(p.exists() for p in newest_20)
    assert len(managed_files(service, save_path)) == 20


def test_prune_keeps_everything_that_is_young_even_beyond_keep_last(make, save_path: Path) -> None:
    make_aged(make, save_path, [i * 0.5 for i in range(25)])
    service = make(NOW, RetentionPolicy(keep_last=20, keep_days=30, min_keep=3))
    report = service.prune(save_path)
    assert report.deleted == ()
    assert len(managed_files(service, save_path)) == 25


def test_prune_keeps_old_backups_inside_keep_last(make, save_path: Path) -> None:
    make_aged(make, save_path, [60, 61, 62, 63, 64])
    service = make(NOW, RetentionPolicy(keep_last=20, keep_days=30, min_keep=3))
    assert service.prune(save_path).deleted == ()
    assert len(managed_files(service, save_path)) == 5


def test_min_keep_protects_the_newest_even_when_old_and_outside_keep_last(
    make, save_path: Path
) -> None:
    records = make_aged(make, save_path, [60, 50, 40, 30, 20, 10])
    service = make(NOW, RetentionPolicy(keep_last=1, keep_days=1, min_keep=3))
    report = service.prune(save_path)
    assert set(report.deleted) == {r.path for r in records[:3]}
    assert {p.name for p in service.slot_dir(save_path).glob("persist.game.backup.*.json")} == {
        r.path.name for r in records[3:]
    }


def test_protected_paths_survive_pruning(make, save_path: Path) -> None:
    records = make_aged(make, save_path, [90, 80, 70, 5, 4, 3, 2, 1])
    service = make(NOW, RetentionPolicy(keep_last=2, keep_days=10, min_keep=1))
    report = service.prune(save_path, protect=[records[0].path])
    assert records[0].path.exists()
    assert records[0].path not in report.deleted
    assert {records[1].path, records[2].path} <= set(report.deleted)


def test_beside_save_backups_are_never_pruned(make, save_path: Path) -> None:
    beside = save_path.parent / "persist.game.backup.20190101-000000.json"
    beside.write_bytes(A)
    make_aged(make, save_path, [60, 50, 40, 30, 20, 10])
    service = make(NOW, RetentionPolicy(keep_last=1, keep_days=1, min_keep=1))
    report = service.prune(save_path)
    assert beside.exists()
    assert beside not in report.deleted
    assert beside.read_bytes() == A


def test_create_prunes_by_policy_and_never_raises(make, save_path: Path) -> None:
    policy = RetentionPolicy(keep_last=2, keep_days=1, min_keep=1)
    make_aged(make, save_path, [10, 9, 8, 7])
    record = make(NOW, policy).create(save_path, reason=BackupReason.MANUAL)
    names = managed_files(make(), save_path)
    assert record.path.name in names
    assert len(names) == 2


def test_index_is_rebuilt_from_the_directory_when_deleted(make, save_path: Path) -> None:
    service = make()
    first = service.create(save_path, reason=BackupReason.PRE_PATCH)
    index = service.slot_dir(save_path) / "index.json"
    index.unlink()
    assert [r.path for r in service.list(save_path)] == [first.path]
    second = make(NOW + timedelta(minutes=1)).create(save_path, reason=BackupReason.MANUAL)
    doc = json.loads(index.read_text("utf-8"))
    assert {e["file"] for e in doc["entries"]} == {first.path.name, second.path.name}


def test_index_garbage_does_not_break_listing(make, save_path: Path) -> None:
    service = make()
    first = service.create(save_path, reason=BackupReason.PRE_PATCH)
    (service.slot_dir(save_path) / "index.json").write_bytes(b"{garbage")
    assert [r.path for r in service.list(save_path)] == [first.path]


# ------------------------------------------------------------------ restore


def test_restore_writes_the_backup_and_takes_a_pre_restore_copy(make, save_path: Path) -> None:
    service = make()
    record = service.create(save_path, reason=BackupReason.MANUAL, raw=B)
    set_mtime(record.path, datetime(2020, 1, 1, tzinfo=NOW.tzinfo))
    result = service.restore(record)
    assert save_path.read_bytes() == B
    assert result.target == save_path
    assert result.restored_from == record
    assert result.pre_restore_backup.reason is BackupReason.PRE_RESTORE
    assert result.pre_restore_backup.path.read_bytes() == A
    assert abs(save_path.stat().st_mtime - time.time()) < 300
    assert record.path.read_bytes() == B
    assert not [p for p in save_path.parent.iterdir() if p.name.endswith(".tmp")]


def test_restore_to_another_target(make, save_path: Path, tmp_path: Path) -> None:
    service = make()
    record = service.create(save_path, reason=BackupReason.MANUAL, raw=B)
    target = tmp_path / "Darkest" / "profile_1" / "persist.game.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(A)
    result = service.restore(record, target=target)
    assert target.read_bytes() == B
    assert save_path.read_bytes() == A
    assert result.target == target
    assert result.pre_restore_backup.save_path == target


def test_restore_of_invalid_bytes_leaves_the_target_untouched(make, save_path: Path) -> None:
    service = make()
    record = service.create(save_path, reason=BackupReason.MANUAL)
    record.path.write_bytes(b"this is not a save")
    before = managed_files(service, save_path)
    with pytest.raises(BackupInvalidError):
        service.restore(record)
    assert save_path.read_bytes() == A
    assert managed_files(service, save_path) == before


def test_restore_of_a_backup_that_fails_the_format_check_is_invalid(make, save_path: Path) -> None:
    service = make()
    record = service.create(save_path, reason=BackupReason.MANUAL)
    record.path.write_bytes(A + b"CORRUPT")
    with pytest.raises(BackupInvalidError):
        service.restore(record)
    assert save_path.read_bytes() == A


def test_restore_of_a_missing_backup(make, save_path: Path) -> None:
    service = make()
    record = service.create(save_path, reason=BackupReason.MANUAL)
    record.path.unlink()
    with pytest.raises(BackupNotFoundError):
        service.restore(record)
    assert save_path.read_bytes() == A


def test_restore_refuses_while_the_game_runs(make, fake_probe, save_path: Path) -> None:
    probe = fake_probe(RunState.RUNNING)
    service = make(probe=probe)
    record = service.create(save_path, reason=BackupReason.MANUAL, raw=B)
    with pytest.raises(GameRunningError):
        service.restore(record)
    assert save_path.read_bytes() == A
    assert "darkest.exe" in probe.calls[0]
    assert len(managed_files(service, save_path)) == 1


def test_restore_proceeds_when_the_game_state_is_unknown(make, fake_probe, save_path: Path) -> None:
    service = make(probe=fake_probe(RunState.UNKNOWN))
    record = service.create(save_path, reason=BackupReason.MANUAL, raw=B)
    service.restore(record)
    assert save_path.read_bytes() == B


def test_restore_from_a_beside_save_backup(make, save_path: Path) -> None:
    beside = save_path.parent / "persist.game.backup.20200102-030405.json"
    beside.write_bytes(B)
    service = make()
    (record,) = service.list(save_path)
    service.restore(record)
    assert save_path.read_bytes() == B
    assert beside.read_bytes() == B
