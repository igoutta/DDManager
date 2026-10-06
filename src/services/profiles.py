"""Named load-order profiles: ``<data>/profiles/<slug>.loadorder.json`` (``ddmanager.loadorder``).

A profile is a plain :class:`~src.core.loadorder_file.LoadOrderDocument`, so a profile file is
also the share/export format.  The legacy ``dd_mod_loadout.json`` (``legacy_loadout.py:30-46``)
is accepted on import and converted by :func:`parse_legacy_loadout`.
"""

import builtins
import dataclasses
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from src.core.findings import Finding, Severity
from src.core.loadorder_file import (
    FORMAT,
    LegacyLoadoutExtras,
    LoadOrderDocument,
    dump_load_order,
    parse_legacy_loadout,
    parse_load_order,
)
from src.services.errors import ProfileExistsError, ProfileFormatError
from src.services.fsutil import atomic_write_text

SUFFIX: Final = ".loadorder.json"
_UNSAFE_RE: Final = re.compile(r"[^\w.-]+")
_RESERVED: Final = frozenset({"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
                              *(f"lpt{n}" for n in range(1, 10))})  # fmt: skip


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    name: str
    path: Path
    created_at: datetime | None
    entry_count: int
    findings: tuple[Finding, ...]


def slugify(name: str) -> str:
    """A file-name-safe, casefolded slug; never empty and never a Windows reserved name."""
    slug = _UNSAFE_RE.sub("-", name.strip().casefold()).strip("-.")
    if not slug:
        return "profile"
    return f"_{slug}" if slug in _RESERVED else slug


def _first_error(findings: list[Finding], fallback: str) -> str:
    for finding in findings:
        if finding.severity >= Severity.ERROR:
            return finding.message
    return fallback


class ProfileRepository:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def path_for(self, name: str) -> Path:
        return self._dir / f"{slugify(name)}{SUFFIX}"

    # ------------------------------------------------------------------ read

    def list(self) -> builtins.list[ProfileSummary]:
        """Every ``*.loadorder.json``; an unreadable one is listed with findings, never raised."""
        try:
            files = sorted(p for p in self._dir.iterdir() if p.name.endswith(SUFFIX))
        except OSError:
            return []
        return [self._summary(path) for path in files]

    def _summary(self, path: Path) -> ProfileSummary:
        stem = path.name.removesuffix(SUFFIX)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            finding = Finding.error("profile.unreadable", f"Cannot read {path.name}: {exc}")
            return ProfileSummary(stem, path, None, 0, (finding,))
        doc, findings = parse_load_order(text)
        if doc is None:
            return ProfileSummary(stem, path, None, 0, tuple(findings))
        return ProfileSummary(
            doc.name or stem, path, doc.created_at, len(doc.entries), tuple(findings)
        )

    def load(self, name: str) -> LoadOrderDocument:
        path = self.path_for(name)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ProfileFormatError(f"No profile named {name!r}.", path=str(path)) from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise ProfileFormatError(
                f"Cannot read profile {name!r}: {exc}", path=str(path)
            ) from exc
        doc, findings = parse_load_order(text)
        if doc is None:
            reason = _first_error(findings, "unreadable")
            raise ProfileFormatError(f"Profile {name!r} is not usable: {reason}", path=str(path))
        return doc

    # ------------------------------------------------------------------ write

    def save(self, doc: LoadOrderDocument, *, overwrite: bool = False) -> Path:
        if not doc.name.strip():
            raise ProfileFormatError("A profile needs a name.")
        path = self.path_for(doc.name)
        if path.exists() and not overwrite:
            raise ProfileExistsError(
                f"A profile named {doc.name!r} already exists.", path=str(path)
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, dump_load_order(doc))
        return path

    def delete(self, name: str) -> None:
        path = self.path_for(name)
        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise ProfileFormatError(f"No profile named {name!r}.", path=str(path)) from exc

    def rename(self, old: str, new: str) -> Path:
        doc = self.load(old)
        target = self.path_for(new)
        source = self.path_for(old)
        if target.exists() and target != source:
            raise ProfileExistsError(f"A profile named {new!r} already exists.", path=str(target))
        path = self.save(dataclasses.replace(doc, name=new), overwrite=True)
        if source != path:
            source.unlink(missing_ok=True)
        return path

    # ------------------------------------------------------------------ interchange

    def import_file(self, path: Path) -> tuple[LoadOrderDocument, LegacyLoadoutExtras | None]:
        """A ``ddmanager.loadorder`` file or a legacy ``dd_mod_loadout.json`` (extras returned)."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ProfileFormatError(f"Cannot read {path}: {exc}", path=str(path)) from exc
        try:
            obj = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise ProfileFormatError(
                f"{path.name} is not valid JSON: {exc}", path=str(path)
            ) from exc
        if isinstance(obj, dict) and obj.get("format") == FORMAT:
            return self._import_native(path, text), None
        return self._import_legacy(path, obj)

    def _import_native(self, path: Path, text: str) -> LoadOrderDocument:
        doc, findings = parse_load_order(text)
        if doc is None:
            raise ProfileFormatError(_first_error(findings, "unreadable"), path=str(path))
        return doc

    def _import_legacy(
        self, path: Path, obj: object
    ) -> tuple[LoadOrderDocument, LegacyLoadoutExtras | None]:
        doc, extras, findings = parse_legacy_loadout(obj)
        if doc is None:
            reason = _first_error(findings, "not a loadout")
            raise ProfileFormatError(f"{path.name} is not a load order: {reason}", path=str(path))
        return dataclasses.replace(doc, name=doc.name or path.stem), extras

    def export(self, doc: LoadOrderDocument, dest: Path) -> None:
        atomic_write_text(dest, dump_load_order(doc))
