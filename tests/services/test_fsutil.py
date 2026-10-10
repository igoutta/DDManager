"""Atomic writes, retrying replace, fingerprints and the small path helpers."""

import hashlib
import os
from datetime import datetime
from pathlib import Path

import pytest

from src.services.errors import SaveLockedError
from src.services.fsutil import (
    FileFingerprint,
    atomic_copy,
    atomic_write_bytes,
    atomic_write_text,
    backup_timestamp,
    replace_with_retry,
    safe_mtime_ns,
    unique_path,
)
from tests.services.helpers import TZ


def listing(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


class FlakyReplace:
    """``os.replace`` that raises ``error`` for the first ``failures`` calls."""

    def __init__(self, failures: int, error: OSError) -> None:
        self.failures = failures
        self.error = error
        self.calls = 0
        self._real = os.replace

    def __call__(self, src, dst, *args, **kwargs) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        self._real(src, dst, *args, **kwargs)


def test_fingerprint_of_file_and_bytes(tmp_path: Path) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"hello")
    fp = FileFingerprint.of(target)
    assert fp is not None
    assert fp.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert fp.size == 5
    assert fp.mtime_ns == target.stat().st_mtime_ns
    assert FileFingerprint.of_bytes(b"hello", target.stat()) == fp
    assert FileFingerprint.of(tmp_path / "missing") is None


def test_fingerprint_changes_with_content_and_is_hashable(tmp_path: Path) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"one")
    first = FileFingerprint.of(target)
    target.write_bytes(b"two")
    second = FileFingerprint.of(target)
    assert first != second
    assert len({first, second}) == 2


def test_atomic_write_bytes_creates_and_replaces(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    atomic_write_bytes(target, b"first")
    assert target.read_bytes() == b"first"
    atomic_write_bytes(target, b"second", fsync=False)
    assert target.read_bytes() == b"second"
    assert listing(tmp_path) == ["out.bin"]


def test_replace_failure_keeps_original_bytes_and_leaves_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.bin"
    target.write_bytes(b"original")
    monkeypatch.setattr(os, "replace", FlakyReplace(99, OSError("disk on fire")))
    with pytest.raises(OSError, match="disk on fire"):
        atomic_write_bytes(target, b"new content")
    assert target.read_bytes() == b"original"
    assert listing(tmp_path) == ["out.bin"]


def test_permission_error_twice_then_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = FlakyReplace(2, PermissionError("locked"))
    monkeypatch.setattr(os, "replace", flaky)
    target = tmp_path / "out.bin"
    target.write_bytes(b"old")
    delays: list[float] = []
    src = tmp_path / "staged.tmp"
    src.write_bytes(b"new")
    replace_with_retry(src, target, sleep=delays.append)
    assert flaky.calls == 3
    assert len(delays) == 2
    assert delays[0] == pytest.approx(0.05)
    assert delays[1] >= delays[0]
    assert target.read_bytes() == b"new"
    assert not src.exists()


def test_permission_error_forever_is_save_locked_after_all_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = FlakyReplace(99, PermissionError("locked"))
    monkeypatch.setattr(os, "replace", flaky)
    src, dst = tmp_path / "a.tmp", tmp_path / "dst"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    delays: list[float] = []
    with pytest.raises(SaveLockedError):
        replace_with_retry(src, dst, attempts=4, sleep=delays.append)
    assert flaky.calls == 4
    assert len(delays) == 3
    assert dst.read_bytes() == b"old"


def test_atomic_write_survives_a_locked_destination_that_frees_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "replace", FlakyReplace(2, PermissionError("locked")))
    monkeypatch.setattr("time.sleep", lambda _s: None)
    target = tmp_path / "out.bin"
    atomic_write_bytes(target, b"data")
    assert target.read_bytes() == b"data"
    assert listing(tmp_path) == ["out.bin"]


def test_verify_failure_removes_temp_and_keeps_original(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    target.write_bytes(b"original")

    def verify(data: bytes) -> None:
        raise ValueError("bad bytes")

    with pytest.raises(ValueError, match="bad bytes"):
        atomic_write_bytes(target, b"new", verify=verify)
    assert target.read_bytes() == b"original"
    assert listing(tmp_path) == ["out.bin"]


def test_verify_receives_the_bytes_read_back(tmp_path: Path) -> None:
    seen: list[bytes] = []
    atomic_write_bytes(tmp_path / "out.bin", b"payload", verify=seen.append)
    assert seen == [b"payload"]


def test_verify_failure_on_a_new_file_leaves_nothing(tmp_path: Path) -> None:
    def verify(data: bytes) -> None:
        raise ValueError("no")

    with pytest.raises(ValueError, match="no"):
        atomic_write_bytes(tmp_path / "fresh.bin", b"new", verify=verify)
    assert listing(tmp_path) == []


def test_temp_name_is_a_dot_file_beside_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources: list[Path] = []

    def spy(src, dst, *args, **kwargs) -> None:
        sources.append(Path(src))
        raise OSError("stop")

    monkeypatch.setattr(os, "replace", spy)
    with pytest.raises(OSError, match="stop"):
        atomic_write_bytes(tmp_path / "out.bin", b"x")
    assert len(sources) == 1
    assert sources[0].parent == tmp_path
    assert sources[0].name.startswith(".out.bin.")
    assert sources[0].name.endswith(".tmp")


def test_atomic_write_text_encodes(tmp_path: Path) -> None:
    target = tmp_path / "t.txt"
    atomic_write_text(target, "café")
    assert target.read_bytes() == "café".encode()
    atomic_write_text(target, "café", encoding="latin-1")
    assert target.read_bytes() == b"caf\xe9"


def test_atomic_copy_copies_bytes_and_keeps_the_source(tmp_path: Path) -> None:
    src, dst = tmp_path / "a.bin", tmp_path / "b.bin"
    src.write_bytes(b"\x00\x01payload")
    atomic_copy(src, dst)
    assert dst.read_bytes() == b"\x00\x01payload"
    assert src.read_bytes() == b"\x00\x01payload"
    assert listing(tmp_path) == ["a.bin", "b.bin"]


def test_atomic_copy_never_leaves_a_half_written_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, dst = tmp_path / "a.bin", tmp_path / "b.bin"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    monkeypatch.setattr(os, "replace", FlakyReplace(99, OSError("nope")))
    with pytest.raises(OSError, match="nope"):
        atomic_copy(src, dst)
    assert dst.read_bytes() == b"old"
    assert listing(tmp_path) == ["a.bin", "b.bin"]


def test_unique_path_suffixes_before_the_extension(tmp_path: Path) -> None:
    free = tmp_path / "save.json"
    assert unique_path(free) == free
    free.write_bytes(b"")
    assert unique_path(free) == tmp_path / "save-2.json"
    (tmp_path / "save-2.json").write_bytes(b"")
    assert unique_path(free) == tmp_path / "save-3.json"


def test_unique_path_handles_dotted_and_extensionless_names(tmp_path: Path) -> None:
    dotted = tmp_path / "persist.game.backup.20250101-000000.json"
    dotted.write_bytes(b"")
    assert unique_path(dotted) == tmp_path / "persist.game.backup.20250101-000000-2.json"
    bare = tmp_path / "notes"
    bare.write_bytes(b"")
    assert unique_path(bare) == tmp_path / "notes-2"


def test_backup_timestamp_format() -> None:
    assert backup_timestamp(datetime(2025, 1, 2, 3, 4, 5, tzinfo=TZ)) == "20250102-030405"


def test_safe_mtime_ns(tmp_path: Path) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"")
    assert safe_mtime_ns(target) == target.stat().st_mtime_ns
    assert safe_mtime_ns(tmp_path / "gone") is None
