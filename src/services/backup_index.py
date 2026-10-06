"""``index.json`` of one managed backup slot directory.

The directory listing is the truth; the index only adds metadata (reason, sha256, exact creation
time).  A missing or damaged index is never an error: it is rebuilt from the files on the next
write and reported as an INFO finding.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from src.core.findings import Finding
from src.services.fsutil import atomic_write_text

_LOG: Final = logging.getLogger(__name__)

INDEX_NAME: Final = "index.json"
FORMAT: Final = "ddmanager.backup-index"
FORMAT_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class IndexEntry:
    file: str
    created: str
    reason: str | None
    size: int
    sha256: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "file": self.file,
            "created": self.created,
            "reason": self.reason,
            "size": self.size,
            "sha256": self.sha256,
        }


def _entry(raw: object) -> IndexEntry | None:
    if not isinstance(raw, dict):
        return None
    file, created, size = raw.get("file"), raw.get("created"), raw.get("size")
    if not isinstance(file, str) or not isinstance(created, str) or not isinstance(size, int):
        return None
    reason, sha = raw.get("reason"), raw.get("sha256")
    return IndexEntry(
        file,
        created,
        reason if isinstance(reason, str) else None,
        size,
        sha if isinstance(sha, str) else None,
    )


def read_index(slot_dir: Path) -> tuple[dict[str, IndexEntry], Finding | None]:
    """Entries by file name; ``({}, finding)`` when the index exists but is unusable."""
    path = slot_dir / INDEX_NAME
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError, RecursionError) as exc:
        return {}, _rebuilt(path, str(exc))
    items = obj.get("entries") if isinstance(obj, dict) else None
    if not isinstance(items, list) or obj.get("format") != FORMAT:
        return {}, _rebuilt(path, "unexpected layout")
    entries = [e for e in (_entry(item) for item in items) if e is not None]
    return {e.file: e for e in entries}, None


def _rebuilt(path: Path, why: str) -> Finding:
    message = f"The backup index {path} could not be used ({why}); it will be rebuilt."
    return Finding.info("backup.index_rebuilt", message)


def reconcile_index(
    slot_dir: Path, files: Iterable[Path], created_of: Callable[[str], datetime | None]
) -> dict[str, IndexEntry]:
    """The index reconciled with the directory listing (``files``, the truth): rows whose file
    is gone are dropped and files the index does not know get a row rebuilt from the file."""
    entries, finding = read_index(slot_dir)
    if finding is not None:
        _LOG.info("%s", finding.message)
    live = {name: e for name, e in entries.items() if (slot_dir / name).is_file()}
    for path in files:
        if path.name not in live:
            live[path.name] = entry_from_file(path, created_of(path.name))
    return live


def entry_from_file(path: Path, created: datetime | None) -> IndexEntry:
    """A row for a backup the index never recorded (no reason; size and hash from the file)."""
    stamp = created.isoformat() if created else ""
    try:
        raw = path.read_bytes()
    except OSError:
        return IndexEntry(path.name, stamp, None, 0, None)
    return IndexEntry(path.name, stamp, None, len(raw), hashlib.sha256(raw).hexdigest())


def write_index(slot_dir: Path, save_path: Path, entries: Mapping[str, IndexEntry]) -> None:
    """Atomically rewrite the index (entries sorted by file name for stable output)."""
    obj = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "save_path": str(save_path),
        "entries": [entries[name].to_json() for name in sorted(entries)],
    }
    atomic_write_text(slot_dir / INDEX_NAME, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def write_index_quietly(slot_dir: Path, save_path: Path, entries: Mapping[str, IndexEntry]) -> None:
    """``write_index`` that only logs an ``OSError`` (the backup files are already safe)."""
    try:
        write_index(slot_dir, save_path, entries)
    except OSError as exc:
        _LOG.warning("cannot update the backup index in %s: %s", slot_dir, exc)
