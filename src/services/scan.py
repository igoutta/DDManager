"""Scanning: ask every source for mod folders, resolve conflicts, read and derive ``ModInfo``.

Replaces the legacy ``get_current_mod_folders`` (``dd2.py:5994-6021``): the same first-root-wins
rule per folder name, but a shadowed duplicate is now reported as a finding instead of being
dropped silently.  A failing source or an unreadable folder never aborts the scan.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, tzinfo
from pathlib import Path

from src.core.findings import Finding, Severity
from src.core.identity import derive_mod_info
from src.core.ids import ModId
from src.core.model import ModInfo
from src.services.detection import InstallSnapshot
from src.services.ports import CancelToken, Clock, NeverCancelled, NullProgress, ProgressReporter
from src.services.sources import ModLocation, ModSource, ReadContext
from src.services.steam_locations import path_key, read_workshop_update_times

log = logging.getLogger(__name__)

TEMP_PREFIX = "__temp__"


@dataclass(frozen=True, slots=True)
class ScanResult:
    mods: Mapping[ModId, ModInfo]
    findings: tuple[Finding, ...]
    shadowed: Mapping[ModId, tuple[Path, ...]]
    locations: Mapping[ModId, ModLocation]
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class _Candidate:
    location: ModLocation
    sort_key: tuple[int, int, int]
    """(index of the root in ``install.mod_roots``, claim rank, discovery order)."""


def _discover(
    sources: Sequence[ModSource], install: InstallSnapshot, findings: list[Finding]
) -> list[tuple[int, ModSource, list[ModLocation]]]:
    """Each source's locations; a source that raises becomes a ``scan.source_failed`` finding."""
    ranked = sorted(enumerate(sources), key=lambda pair: (pair[1].claim_priority, pair[0]))
    discovered: list[tuple[int, ModSource, list[ModLocation]]] = []
    for rank, source in enumerate(item[1] for item in ranked):
        try:
            locations = list(source.discover(install))
        except Exception as exc:  # plugin boundary: a broken source must not abort the scan
            log.exception("mod source %s failed to discover", source.source_id)
            findings.append(
                Finding.warning(
                    "scan.source_failed",
                    f"Mod source {source.source_id!r} failed: {exc}",
                    source=source.source_id,
                )
            )
            continue
        discovered.append((rank, source, locations))
    return discovered


def _claim_paths(
    discovered: Sequence[tuple[int, ModSource, list[ModLocation]]], install: InstallSnapshot
) -> list[_Candidate]:
    """Path-level claim: the lowest ``claim_priority`` source keeps a folder."""
    root_index = {path_key(root): index for index, root in enumerate(install.mod_roots)}
    claimed: set[str] = set()
    candidates: list[_Candidate] = []
    for rank, _source, locations in discovered:
        for order, location in enumerate(locations):
            key = path_key(location.path)
            if key in claimed:
                continue
            claimed.add(key)
            index = root_index.get(path_key(location.root), len(root_index))
            candidates.append(_Candidate(location, (index, rank, order)))
    return candidates


def _dedupe_keys(
    candidates: Sequence[_Candidate],
) -> tuple[dict[ModId, ModLocation], dict[ModId, list[Path]]]:
    """Key-level claim: the first root in ``install.mod_roots`` wins, others are shadowed."""
    winners: dict[ModId, ModLocation] = {}
    shadowed: dict[ModId, list[Path]] = {}
    for candidate in sorted(candidates, key=lambda item: item.sort_key):
        location = candidate.location
        if location.key in winners:
            shadowed.setdefault(location.key, []).append(location.path)
        else:
            winners[location.key] = location
    return winners, shadowed


def _location_findings(
    winners: Mapping[ModId, ModLocation], shadowed: Mapping[ModId, Sequence[Path]]
) -> list[Finding]:
    findings = [
        Finding.at(
            Severity.WARNING,
            "scan.shadowed",
            f"Mod folder {key!r} exists in several roots; only {winners[key].path} is used.",
            mod_ids=[key],
            details=[str(path) for path in paths],
        )
        for key, paths in shadowed.items()
    ]
    findings.extend(
        Finding.at(
            Severity.INFO,
            "scan.temp_folder",
            f"{key!r} looks like a leftover temporary folder from an interrupted rename.",
            mod_ids=[key],
        )
        for key in winners
        if key.startswith(TEMP_PREFIX)
    )
    return findings


class ScanService:
    """Runs a full scan over every registered ``ModSource``."""

    def __init__(
        self, sources: Sequence[ModSource], *, clock: Clock, tz: tzinfo | None = None
    ) -> None:
        self._sources = tuple(sources)
        self._clock = clock
        self._tz = tz

    def _zone(self) -> tzinfo:
        return self._tz or self._clock.now().tzinfo or UTC

    def scan(
        self,
        install: InstallSnapshot,
        *,
        cancel: CancelToken | None = None,
        progress: ProgressReporter | None = None,
    ) -> ScanResult:
        token = cancel or NeverCancelled()
        reporter = progress or NullProgress()
        findings: list[Finding] = []
        discovered = _discover(self._sources, install, findings)
        winners, shadowed = _dedupe_keys(_claim_paths(discovered, install))
        findings.extend(_location_findings(winners, shadowed))
        by_id = {source.source_id: source for _rank, source, _locs in discovered}
        ctx = ReadContext(read_workshop_update_times(install.acf_files), self._zone())
        mods: dict[ModId, ModInfo] = {}
        ordered = sorted(winners, key=lambda key: (key.casefold(), key))
        cancelled = False
        for done, key in enumerate(ordered):
            if token.is_cancelled():
                cancelled = True
                break
            reporter.report(done, len(ordered), key)
            info = self._read_one(by_id, winners[key], ctx, findings)
            if info is not None:
                mods[key] = replace(info, shadowed=tuple(shadowed.get(key, ())))
        reporter.report(len(mods), len(ordered))
        return ScanResult(
            mods=mods,
            findings=tuple(findings),
            shadowed={key: tuple(paths) for key, paths in shadowed.items()},
            locations={key: winners[key] for key in mods},
            cancelled=cancelled,
        )

    def _read_one(
        self,
        by_id: Mapping[str, ModSource],
        location: ModLocation,
        ctx: ReadContext,
        findings: list[Finding],
    ) -> ModInfo | None:
        source = by_id[location.source_id]
        try:
            snapshot = source.snapshot(location, ctx)
            return derive_mod_info(snapshot, tz=ctx.tz)
        except Exception as exc:  # plugin boundary: skip this folder, keep scanning
            log.exception("cannot read mod folder %s", location.path)
            findings.append(
                Finding.at(
                    Severity.WARNING,
                    "scan.mod_unreadable",
                    f"Mod folder {location.key!r} could not be read: {exc}",
                    mod_ids=[location.key],
                    details=[str(location.path)],
                )
            )
            return None
