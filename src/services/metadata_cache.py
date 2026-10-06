"""On-disk cache of derived ``ModInfo`` (``<data>/cache/mod_info.v1.json``).

A lookup is pure (it never mutates the cache); the caller commits explicitly and then saves.
Entries are validated by ``MetadataSignature``; anything unreadable is a miss.  Lookups, commits
and saves are serialised by a lock: scans run in worker threads and may overlap for a moment.
"""

import json
import logging
import threading
from collections.abc import Collection, Mapping
from dataclasses import asdict
from pathlib import Path, PurePath
from typing import Any, Final

from src.core.findings import Finding
from src.core.ids import ModId, SaveIdentity, SourceKind
from src.core.model import MetadataSignature, ModInfo
from src.services.fsutil import atomic_write_text

log = logging.getLogger(__name__)

FORMAT: Final = "ddmanager.mod-info-cache"
FORMAT_VERSION: Final = 1


def cache_key(source_id: str, path: PurePath) -> str:
    """``"<source>|<casefolded path>"``."""
    return f"{source_id}|{str(path).casefold()}"


def _opt_path(value: object) -> PurePath | None:
    return None if value is None else PurePath(str(value))


def info_to_json(info: ModInfo) -> dict[str, Any]:
    """A JSON-ready dict of ``info`` (paths as strings, sets as sorted lists)."""
    return {
        "id": str(info.id),
        "source_id": info.source_id,
        "kind": info.kind.value,
        "path": str(info.path),
        "root": str(info.root),
        "title": info.title,
        "project_title": info.project_title,
        "save_identity": {"name": info.save_identity.name, "source": info.save_identity.source},
        "workshop_id": info.workshop_id,
        "version_label": info.version_label,
        "updated_label": info.updated_label,
        "black_reliquary": info.black_reliquary,
        "tags": list(info.tags),
        "top_level_dirs": sorted(info.top_level_dirs),
        "code_subdirs": [[top, list(children)] for top, children in info.code_subdirs],
        "files": sorted(info.files),
        "preview_path": None if info.preview_path is None else str(info.preview_path),
        "preview_mtime_ns": info.preview_mtime_ns,
        "load_after_hints": list(info.load_after_hints),
        "signature": asdict(info.signature),
        "shadowed": [str(path) for path in info.shadowed],
        "project_published_file_id": info.project_published_file_id,
    }


def info_from_json(data: Mapping[str, Any]) -> ModInfo:
    """Inverse of :func:`info_to_json`; raises ``KeyError``/``TypeError``/``ValueError`` if bad."""
    identity = data["save_identity"]
    return ModInfo(
        id=ModId(data["id"]),
        source_id=data["source_id"],
        kind=SourceKind(data["kind"]),
        path=PurePath(data["path"]),
        root=PurePath(data["root"]),
        title=data["title"],
        project_title=data["project_title"],
        save_identity=SaveIdentity(identity["name"], identity["source"]),
        workshop_id=data["workshop_id"],
        version_label=data["version_label"],
        updated_label=data["updated_label"],
        black_reliquary=bool(data["black_reliquary"]),
        tags=tuple(data["tags"]),
        top_level_dirs=frozenset(data["top_level_dirs"]),
        code_subdirs=tuple((top, tuple(children)) for top, children in data["code_subdirs"]),
        files=frozenset(data["files"]),
        preview_path=_opt_path(data["preview_path"]),
        preview_mtime_ns=data["preview_mtime_ns"],
        load_after_hints=tuple(data["load_after_hints"]),
        signature=MetadataSignature(**data["signature"]),
        shadowed=tuple(PurePath(path) for path in data["shadowed"]),
        project_published_file_id=data["project_published_file_id"],
    )


def _entries_of(document: object) -> dict[str, dict[str, Any]]:
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError("not a mod-info cache")
    if document.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"unsupported cache version {document.get('format_version')!r}")
    entries = document.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("cache has no entries object")
    return {key: value for key, value in entries.items() if isinstance(value, dict)}


class MetadataCache:
    """Keyed by :func:`cache_key`; see the module docstring."""

    def __init__(self, path: Path, entries: dict[str, dict[str, Any]] | None = None) -> None:
        self._path = path
        self._entries: dict[str, dict[str, Any]] = entries or {}
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: Path) -> tuple[MetadataCache, list[Finding]]:
        """The cache at ``path``; a missing file is empty, a corrupt one is empty plus a finding."""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(path), []
        except OSError as exc:
            return cls(path), [_discarded(path, str(exc))]
        try:
            return cls(path, _entries_of(json.loads(text))), []
        except ValueError as exc:
            return cls(path), [_discarded(path, str(exc))]

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(self, key: str, signature: MetadataSignature) -> ModInfo | None:
        """The cached info when its stored signature equals ``signature``; never mutates."""
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            return None
        try:
            if MetadataSignature(**entry["signature"]) != signature:
                return None
            return info_from_json(entry["info"])
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("cache entry %s is unusable: %s", key, exc)
            return None

    def commit(
        self, updates: Mapping[str, ModInfo], *, keep: Collection[str] | None = None
    ) -> bool:
        """Store ``updates``; with ``keep`` every other entry is dropped (a stale-entry sweep).

        True when an entry was added, replaced or dropped (so a save is worth its write).
        """
        with self._lock:
            entries = dict(self._entries)
            for key, info in updates.items():
                entries[key] = {"signature": asdict(info.signature), "info": info_to_json(info)}
            if keep is not None:
                wanted = set(keep) | set(updates)
                entries = {k: v for k, v in entries.items() if k in wanted}
            changed = bool(updates) or entries.keys() != self._entries.keys()
            self._entries = entries
        return changed

    def save(self) -> None:
        with self._lock:
            entries = dict(self._entries)
        document = {"format": FORMAT, "format_version": FORMAT_VERSION, "entries": entries}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path, json.dumps(document, ensure_ascii=False, indent=None))


def _discarded(path: Path, reason: str) -> Finding:
    return Finding.info(
        "cache.discarded", f"The mod info cache {path.name} was ignored: {reason}", reason=reason
    )
