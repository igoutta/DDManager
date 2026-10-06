"""Filesystem primitives: fingerprints, atomic writes with read-back verification, unique names."""

import logging
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from src.services.errors import SaveLockedError

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    """Content hash plus size and mtime: "has this file changed since I read it?"."""

    sha256: str
    size: int
    mtime_ns: int

    @classmethod
    def of(cls, path: Path) -> FileFingerprint | None:
        """Fingerprint of ``path``; ``None`` when it does not exist."""
        try:
            with path.open("rb") as handle:
                data = handle.read()
                stat = os.fstat(handle.fileno())
        except FileNotFoundError:
            return None
        return cls.of_bytes(data, stat)

    @classmethod
    def of_bytes(cls, data: bytes, st: os.stat_result) -> FileFingerprint:
        return cls(sha256=sha256(data).hexdigest(), size=len(data), mtime_ns=st.st_mtime_ns)


def replace_with_retry(
    src: Path,
    dst: Path,
    *,
    attempts: int = 6,
    first_delay: float = 0.05,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """``src.replace(dst)``, retrying with backoff while another process holds ``dst``."""
    delay = first_delay
    for attempt in range(1, attempts + 1):
        try:
            src.replace(dst)
        except PermissionError as exc:
            if attempt == attempts:
                raise SaveLockedError(
                    f"{dst} is locked by another program.", path=str(dst), attempts=attempts
                ) from exc
            log.debug("replace %s -> %s denied (attempt %d), retrying", src, dst, attempt)
            sleep(delay)
            delay *= 2
        else:
            return


def _write_temp(fd: int, data: bytes, *, fsync: bool) -> None:
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        if fsync:
            os.fsync(handle.fileno())


def atomic_write_bytes(
    target: Path,
    data: bytes,
    *,
    verify: Callable[[bytes], None] | None = None,
    fsync: bool = True,
) -> None:
    """Write ``data`` next to ``target``, verify it from disk, then replace ``target``.

    ``verify`` receives the bytes read back from the temp file and raises to veto; the temp
    file is removed on any failure and ``target`` is left byte-identical.
    """
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp = Path(name)
    try:
        _write_temp(fd, data, fsync=fsync)
        if verify is not None:
            verify(temp.read_bytes())
        replace_with_retry(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def atomic_write_text(target: Path, text: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(target, text.encode(encoding))


def atomic_copy(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` so ``dst`` is never half written."""
    atomic_write_bytes(dst, src.read_bytes())


def unique_path(path: Path) -> Path:
    """``dd2.py:524-534``: ``path`` itself, else ``-2``, ``-3`` ... before the extension."""
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def legacy_timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def safe_mtime_ns(path: Path) -> int | None:
    """``st_mtime_ns`` or ``None`` when the file is missing or vanished."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None
