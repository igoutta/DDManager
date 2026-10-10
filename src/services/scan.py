"""Scanning: ask every source for mod folders, resolve conflicts, read and derive ``ModInfo``.

The first root wins per folder name, and a shadowed duplicate is reported as a finding instead
of being dropped silently.  A failing source or an unreadable folder never aborts the scan.

With a :class:`MetadataCache` the scan takes a cheap stat-based signature of each folder first
(``mod_reader.signature_of``) and reuses the cached ``ModInfo`` when it matches; only folders
that changed are read and derived again.  The scan never writes the cache: the derived entries
come back in ``ScanResult.cache_updates`` and :func:`scan_with_cache` commits and saves them.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, tzinfo
from pathlib import Path

from src.core.findings import Finding, Severity
from src.core.identity import derive_mod_info
from src.core.ids import ModId
from src.core.model import ModInfo
from src.services.detection import InstallSnapshot
from src.services.errors import ServiceError
from src.services.metadata_cache import MetadataCache, cache_key
from src.services.mod_reader import signature_of
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
    cache_updates: Mapping[str, ModInfo] = field(default_factory=dict)
    """Entries derived by this scan, keyed by ``metadata_cache.cache_key`` (misses only)."""
    cache_hits: int = 0


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


@dataclass(slots=True)
class _Pass:
    """One scan's reading state: the sources, the cache and what has been found so far."""

    by_id: Mapping[str, ModSource]
    ctx: ReadContext
    cache: MetadataCache | None
    findings: list[Finding]
    updates: dict[str, ModInfo] = field(default_factory=dict)
    hits: int = 0

    def read(self, location: ModLocation) -> ModInfo | None:
        """The folder's ``ModInfo`` from the cache or from disk; ``None`` (plus a finding) if
        it cannot be read."""
        key = cache_key(location.source_id, location.path)
        try:
            cached = self._cached(key, location)
            if cached is not None:
                return cached
            snapshot = self.by_id[location.source_id].snapshot(location, self.ctx)
            info = derive_mod_info(snapshot, tz=self.ctx.tz)
        except Exception as exc:  # plugin boundary: skip this folder, keep scanning
            log.exception("cannot read mod folder %s", location.path)
            self.findings.append(
                Finding.at(
                    Severity.WARNING,
                    "scan.mod_unreadable",
                    f"Mod folder {location.key!r} could not be read: {exc}",
                    mod_ids=[location.key],
                    details=[str(location.path)],
                )
            )
            return None
        if self.cache is not None:
            self.updates[key] = info
        return info

    def _cached(self, key: str, location: ModLocation) -> ModInfo | None:
        if self.cache is None:
            return None
        info = self.cache.lookup(key, signature_of(location, self.ctx))
        if info is not None:
            self.hits += 1
        return info


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
        cache: MetadataCache | None = None,
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
        reading = _Pass(by_id, ctx, cache, findings)
        mods: dict[ModId, ModInfo] = {}
        ordered = sorted(winners, key=lambda key: (key.casefold(), key))
        cancelled = False
        for done, key in enumerate(ordered):
            if token.is_cancelled():
                cancelled = True
                break
            reporter.report(done, len(ordered), key)
            info = reading.read(winners[key])
            if info is not None:
                mods[key] = replace(info, shadowed=tuple(shadowed.get(key, ())))
        reporter.report(len(mods), len(ordered))
        log.info("scan: %d mods, %d from the cache", len(mods), reading.hits)
        return ScanResult(
            mods=mods,
            findings=tuple(findings),
            shadowed={key: tuple(paths) for key, paths in shadowed.items()},
            locations={key: winners[key] for key in mods},
            cancelled=cancelled,
            cache_updates=reading.updates,
            cache_hits=reading.hits,
        )


def remember_scan(cache: MetadataCache, result: ScanResult) -> Finding | None:
    """Commit what the scan derived and save the cache; a complete scan sweeps stale entries.

    A cache that cannot be written costs nothing but the speed-up: the scan result stands and
    the failure comes back as a ``cache.not_saved`` finding.
    """
    keep = (
        None
        if result.cancelled
        else [cache_key(loc.source_id, loc.path) for loc in result.locations.values()]
    )
    if not cache.commit(result.cache_updates, keep=keep):
        return None
    try:
        cache.save()
    except (OSError, ServiceError) as exc:  # a full disk, or a locked replacement target
        log.warning("the mod info cache could not be saved: %s", exc)
        return Finding.warning(
            "cache.not_saved", f"The mod info cache could not be saved: {exc}", reason=str(exc)
        )
    return None


def scan_with_cache(
    scanner: ScanService,
    cache: MetadataCache,
    install: InstallSnapshot,
    *,
    cancel: CancelToken | None = None,
    progress: ProgressReporter | None = None,
) -> ScanResult:
    """``scanner.scan`` over ``cache`` followed by :func:`remember_scan` (the usual pairing)."""
    result = scanner.scan(install, cache=cache, cancel=cancel, progress=progress)
    note = remember_scan(cache, result)
    return result if note is None else replace(result, findings=(*result.findings, note))
