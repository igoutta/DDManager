"""SavePatchService: plan is read-only, apply is gated, backed up, verified and atomic."""

import os
from pathlib import Path

import pytest

from src.core.diff import sequence_diff
from src.core.errors import SaveFormatError, UnknownSaveFormatError
from src.core.ids import SaveIdentity
from src.core.saves import DsonV1Format, SaveFormatRegistry, default_registry
from src.services.backup import BackupReason, BackupService
from src.services.errors import (
    GameRunningError,
    SaveNotFoundError,
    StaleSaveError,
    UnacknowledgedRiskError,
)
from src.services.fsutil import FileFingerprint
from src.services.ports import FixedClock, RunState
from src.services.save_patch import (
    ACK_DUPLICATE_IDENTITY,
    ACK_GAME_STATE_UNKNOWN,
    ACK_NON_DEFAULT_FILENAME,
    ACK_STEAM_CLOUD,
    SavePatchService,
)
from tests.services.helpers import NOW, FakeFormat, fake_save_bytes
from tests.support.dson_builder import THREE_ENTRIES, standard_save
from tests.support.identities import identities

ORIGINAL = fake_save_bytes([("1111111", "Steam"), ("Old Local", "mod_local_source")])
ENTRIES = (SaveIdentity("2222222", "Steam"), SaveIdentity("New Local", "mod_local_source"))


@pytest.fixture
def save_path(tmp_path: Path) -> Path:
    path = tmp_path / "Darkest" / "profile_0" / "persist.game.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(ORIGINAL)
    return path


@pytest.fixture
def build(app_paths, fake_probe):
    def make(fmt=None, state=RunState.NOT_RUNNING, registry=None):
        fmt = fmt or FakeFormat()
        registry = registry or SaveFormatRegistry([fmt])
        probe = fake_probe(state)
        backups = BackupService(app_paths, registry, clock=FixedClock(NOW), probe=probe)
        return SavePatchService(registry, backups, probe=probe), backups, probe, fmt

    return make


def temp_files(folder: Path) -> list[str]:
    return [p.name for p in folder.iterdir() if p.name.endswith(".tmp")]


def test_game_images_constant() -> None:
    assert {"darkest.exe", "darkestdungeon.exe", "darkest"} == SavePatchService.GAME_IMAGES


def test_plan_describes_the_patch_and_writes_nothing(build, app_paths, save_path: Path) -> None:
    service, _, _, fmt = build()
    before_tree = sorted(p for p in app_paths.data_dir.rglob("*"))
    plan = service.plan(save_path, ENTRIES)
    assert save_path.read_bytes() == ORIGINAL
    assert sorted(app_paths.data_dir.rglob("*")) == before_tree
    assert sorted(p.name for p in save_path.parent.iterdir()) == ["persist.game.json"]
    assert plan.save_path == save_path
    assert plan.format_id == "fake"
    assert plan.original == FileFingerprint.of(save_path)
    assert plan.before == fmt.read_applied(ORIGINAL)
    assert plan.after == ENTRIES
    assert plan.diff == sequence_diff(plan.before, plan.after)
    assert plan.patched == fmt.write_applied(ORIGINAL, ENTRIES)
    assert plan.required_acks == frozenset()
    assert service.dry_run_diff(plan) == plan.diff
    assert save_path.read_bytes() == ORIGINAL


def test_plan_allows_an_empty_list(build, save_path: Path) -> None:
    plan = build()[0].plan(save_path, [])
    assert plan.after == ()
    assert plan.diff.removed == plan.before


def test_plan_of_a_missing_file(build, tmp_path: Path) -> None:
    with pytest.raises(SaveNotFoundError):
        build()[0].plan(tmp_path / "nope" / "persist.game.json", ENTRIES)


def test_plan_of_unrecognised_bytes(build, save_path: Path) -> None:
    save_path.write_bytes(b"definitely not a save")
    with pytest.raises(UnknownSaveFormatError):
        build()[0].plan(save_path, ENTRIES)
    assert save_path.read_bytes() == b"definitely not a save"


@pytest.mark.parametrize(
    ("folder", "name", "entries", "state", "expected"),
    [
        (("Steam", "userdata", "123", "262060", "remote"), "persist.game.json", ENTRIES,
         RunState.NOT_RUNNING, {ACK_STEAM_CLOUD}),
        (("Darkest", "p"), "persist.game.json", (*ENTRIES, ENTRIES[0]),
         RunState.NOT_RUNNING, {ACK_DUPLICATE_IDENTITY}),
        (("Darkest", "p"), "renamed.json", ENTRIES, RunState.NOT_RUNNING,
         {ACK_NON_DEFAULT_FILENAME}),
        (("Darkest", "p"), "persist.game.json", ENTRIES, RunState.UNKNOWN,
         {ACK_GAME_STATE_UNKNOWN}),
        (("Steam", "userdata", "123", "262060", "remote"), "renamed.json", (*ENTRIES, ENTRIES[1]),
         RunState.UNKNOWN, {ACK_STEAM_CLOUD, ACK_NON_DEFAULT_FILENAME, ACK_DUPLICATE_IDENTITY,
                            ACK_GAME_STATE_UNKNOWN}),
    ],
)  # fmt: skip
def test_risks_become_required_acknowledgements(
    build, tmp_path: Path, folder, name, entries, state, expected
) -> None:
    target = tmp_path.joinpath(*folder) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(ORIGINAL)
    plan = build(state=state)[0].plan(target, entries)
    assert plan.required_acks == frozenset(expected)
    assert len(plan.findings) >= len(expected)


def test_same_name_with_a_different_source_is_not_a_duplicate(build, save_path: Path) -> None:
    entries = (SaveIdentity("same", "Steam"), SaveIdentity("same", "mod_local_source"))
    assert build()[0].plan(save_path, entries).required_acks == frozenset()


def test_apply_patches_backs_up_and_verifies(build, save_path: Path) -> None:
    service, backups, probe, fmt = build()
    plan = service.plan(save_path, ENTRIES)
    result = service.apply(plan)
    assert save_path.read_bytes() == plan.patched
    assert fmt.read_applied(save_path.read_bytes()) == ENTRIES
    assert result.save_path == save_path
    assert (result.before, result.after) == (plan.before, plan.after)
    assert result.backup.reason is BackupReason.PRE_PATCH
    assert result.backup.path.read_bytes() == ORIGINAL
    assert backups.list(save_path, include_beside_save=False) == [result.backup]
    assert SavePatchService.GAME_IMAGES in probe.calls
    assert temp_files(save_path.parent) == []


def test_missing_acknowledgements_block_apply(build, tmp_path: Path) -> None:
    target = tmp_path / "Steam" / "userdata" / "1" / "262060" / "remote" / "renamed.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(ORIGINAL)
    service, backups, _, _ = build()
    plan = service.plan(target, ENTRIES)
    assert plan.required_acks == {ACK_STEAM_CLOUD, ACK_NON_DEFAULT_FILENAME}
    with pytest.raises(UnacknowledgedRiskError) as none_given:
        service.apply(plan)
    assert none_given.value.missing == {ACK_STEAM_CLOUD, ACK_NON_DEFAULT_FILENAME}
    with pytest.raises(UnacknowledgedRiskError) as partial:
        service.apply(plan, acknowledged=frozenset({ACK_STEAM_CLOUD}))
    assert partial.value.missing == {ACK_NON_DEFAULT_FILENAME}
    assert target.read_bytes() == ORIGINAL
    assert backups.list(target, include_beside_save=False) == []
    service.apply(plan, acknowledged=frozenset({ACK_STEAM_CLOUD, ACK_NON_DEFAULT_FILENAME, "x"}))
    assert target.read_bytes() == plan.patched


def test_apply_refuses_while_the_game_runs(build, save_path: Path) -> None:
    service, backups, _, _ = build(state=RunState.RUNNING)
    plan = service.plan(save_path, ENTRIES)
    with pytest.raises(GameRunningError):
        service.apply(plan)
    assert save_path.read_bytes() == ORIGINAL
    assert backups.list(save_path, include_beside_save=False) == []


def test_a_save_changed_after_planning_is_stale_and_not_backed_up(build, save_path: Path) -> None:
    service, backups, _, _ = build()
    plan = service.plan(save_path, ENTRIES)
    changed = fake_save_bytes([("9999999", "Steam")])
    save_path.write_bytes(changed)
    with pytest.raises(StaleSaveError):
        service.apply(plan)
    assert save_path.read_bytes() == changed
    assert backups.list(save_path, include_beside_save=False) == []
    assert not app_backup_files(backups, save_path)


def app_backup_files(backups: BackupService, save_path: Path) -> list[Path]:
    slot = backups.slot_dir(save_path)
    return list(slot.iterdir()) if slot.exists() else []


def test_a_format_that_rejects_its_own_output_leaves_the_original_intact(
    build, save_path: Path
) -> None:
    service, _, _, _ = build(fmt=FakeFormat(corrupt_on_write=True))
    with pytest.raises(SaveFormatError):
        service.apply(service.plan(save_path, ENTRIES))
    assert save_path.read_bytes() == ORIGINAL
    assert temp_files(save_path.parent) == []


def test_a_failing_replace_leaves_the_original_intact(
    build, save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, _, _ = build()
    plan = service.plan(save_path, ENTRIES)

    def broken(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        service.apply(plan)
    assert save_path.read_bytes() == ORIGINAL
    assert temp_files(save_path.parent) == []


def test_real_dson_end_to_end(build, app_paths, tmp_path: Path) -> None:
    raw = standard_save(THREE_ENTRIES)
    path = tmp_path / "Darkest" / "profile_2" / "persist.game.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    wanted = (*reversed(identities(THREE_ENTRIES)), SaveIdentity("Brand New", "mod_local_source"))
    service, backups, _, _ = build(registry=default_registry())
    plan = service.plan(path, wanted)
    assert plan.format_id == DsonV1Format().format_id
    assert plan.before == identities(THREE_ENTRIES)
    result = service.apply(plan)
    written = path.read_bytes()
    assert written == DsonV1Format().write_applied(raw, wanted)
    assert DsonV1Format().read_applied(written) == wanted
    assert result.backup.path.read_bytes() == raw
    assert backups.latest(path) == result.backup
