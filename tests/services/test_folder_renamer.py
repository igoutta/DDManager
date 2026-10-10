"""FolderRenamer: two-phase rename with rollback."""

import os
from pathlib import Path

import pytest

from src.core.folder_order import RenamePlan, RenameStep
from src.core.ids import ModId
from src.services.errors import RenameFailedError
from src.services.folder_renamer import FolderRenamer
from src.services.fsutil import backup_timestamp
from tests.services.helpers import NOW, tree_bytes


class RenameSpy:
    """Counts os.rename/os.replace calls (shared counter) and fails from call ``fail_from``."""

    def __init__(self, fail_from: int | None = None, fail_only: bool = False) -> None:
        self.fail_from = fail_from
        self.fail_only = fail_only
        self.calls: list[tuple[str, str]] = []
        self._real_rename = os.rename
        self._real_replace = os.replace

    def _call(self, real, src, dst, *args, **kwargs):
        self.calls.append((Path(src).name, Path(dst).name))
        n = len(self.calls)
        failing = self.fail_from is not None and n >= self.fail_from
        if failing and (not self.fail_only or n == self.fail_from):
            raise PermissionError("locked by another program")
        return real(src, dst, *args, **kwargs)

    def rename(self, src, dst, *args, **kwargs):
        return self._call(self._real_rename, src, dst, *args, **kwargs)

    def replace(self, src, dst, *args, **kwargs):
        return self._call(self._real_replace, src, dst, *args, **kwargs)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "rename", self.rename)
        monkeypatch.setattr(os, "replace", self.replace)


@pytest.fixture
def mods(tmp_path: Path) -> Path:
    root = tmp_path / "mods"
    for name in ("foo", "bar", "baz"):
        (root / name / "sub").mkdir(parents=True)
        (root / name / "id.txt").write_text(name, "utf-8")
        (root / name / "sub" / "deep.bin").write_bytes(name.encode() * 3)
    return root


def make_plan(*pairs: tuple[str, str]) -> RenamePlan:
    steps = tuple(RenameStep(ModId(old), old, new) for old, new in pairs)
    return RenamePlan(steps, {ModId(old): ModId(new) for old, new in pairs}, ())


def locations(root: Path, plan: RenamePlan) -> dict[ModId, Path]:
    return {step.mod: root / step.old_name for step in plan.steps}


def run(mods: Path, plan: RenamePlan):
    return FolderRenamer(clock=_Clock()).execute(plan, mods, locations=locations(mods, plan))


class _Clock:
    def now(self):
        return NOW


def test_plain_renames_keep_contents(mods: Path) -> None:
    plan = make_plan(("foo", "0001_foo"), ("bar", "0002_bar"))
    result = run(mods, plan)
    assert result.renamed == plan.steps
    assert dict(result.rekey) == dict(plan.rekey)
    assert sorted(p.name for p in mods.iterdir()) == ["0001_foo", "0002_bar", "baz"]
    assert (mods / "0001_foo" / "id.txt").read_text("utf-8") == "foo"
    assert (mods / "0002_bar" / "sub" / "deep.bin").read_bytes() == b"barbarbar"


def test_swaps_and_chains_work_because_of_the_two_phases(mods: Path) -> None:
    plan = make_plan(("foo", "bar"), ("bar", "baz"), ("baz", "foo"))
    run(mods, plan)
    assert sorted(p.name for p in mods.iterdir()) == ["bar", "baz", "foo"]
    assert (mods / "bar" / "id.txt").read_text("utf-8") == "foo"
    assert (mods / "baz" / "id.txt").read_text("utf-8") == "bar"
    assert (mods / "foo" / "id.txt").read_text("utf-8") == "baz"


def test_the_temporary_names_follow_the_documented_pattern(
    mods: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = RenameSpy()
    spy.install(monkeypatch)
    run(mods, make_plan(("foo", "0001_foo"), ("bar", "0002_bar")))
    stamp = f"__temp__{backup_timestamp(NOW)}__"
    phase_one, phase_two = spy.calls[:2], spy.calls[2:4]
    assert phase_one == [("foo", f"{stamp}foo"), ("bar", f"{stamp}bar")]
    assert phase_two == [(f"{stamp}foo", "0001_foo"), (f"{stamp}bar", "0002_bar")]


def test_a_phase_two_failure_rolls_everything_back(
    mods: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = tree_bytes(mods)
    plan = make_plan(("foo", "0001_foo"), ("bar", "0002_bar"), ("baz", "0003_baz"))
    RenameSpy(fail_from=5, fail_only=True).install(monkeypatch)
    with pytest.raises(RenameFailedError) as caught:
        run(mods, plan)
    assert caught.value.details["rolled_back"] is True
    assert caught.value.details["stuck"] == []
    assert tree_bytes(mods) == before
    assert sorted(p.name for p in mods.iterdir()) == ["bar", "baz", "foo"]


def test_a_phase_one_failure_rolls_back_too(mods: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = tree_bytes(mods)
    plan = make_plan(("foo", "0001_foo"), ("bar", "0002_bar"))
    RenameSpy(fail_from=2, fail_only=True).install(monkeypatch)
    with pytest.raises(RenameFailedError) as caught:
        run(mods, plan)
    assert caught.value.details["rolled_back"] is True
    assert tree_bytes(mods) == before
    assert sorted(p.name for p in mods.iterdir()) == ["bar", "baz", "foo"]


def test_a_failed_rollback_reports_the_stuck_folders(
    mods: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan(("foo", "0001_foo"), ("bar", "0002_bar"))
    RenameSpy(fail_from=4).install(monkeypatch)
    with pytest.raises(RenameFailedError) as caught:
        run(mods, plan)
    assert caught.value.details["rolled_back"] is False
    stuck = caught.value.details["stuck"]
    assert isinstance(stuck, list)
    assert stuck
    assert all(isinstance(item, str) for item in stuck)


def test_an_existing_destination_is_refused_before_anything_moves(mods: Path) -> None:
    (mods / "0001_foo").mkdir()
    (mods / "0001_foo" / "id.txt").write_text("squatter", "utf-8")
    before = tree_bytes(mods)
    with pytest.raises(RenameFailedError):
        run(mods, make_plan(("foo", "0001_foo"), ("bar", "0002_bar")))
    assert tree_bytes(mods) == before
    assert sorted(p.name for p in mods.iterdir()) == ["0001_foo", "bar", "baz", "foo"]


def test_a_missing_source_is_refused_before_anything_moves(mods: Path) -> None:
    before = tree_bytes(mods)
    with pytest.raises(RenameFailedError):
        run(mods, make_plan(("foo", "0001_foo"), ("ghost", "0002_ghost")))
    assert tree_bytes(mods) == before
    assert not [p for p in mods.iterdir() if p.name.startswith("__temp__")]


def test_an_empty_plan_is_a_no_op(mods: Path) -> None:
    before = tree_bytes(mods)
    result = run(mods, make_plan())
    assert result.renamed == ()
    assert dict(result.rekey) == {}
    assert tree_bytes(mods) == before
