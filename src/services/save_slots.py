"""Profile slots (``persist.game.json`` per ``profile_N`` folder): number, date, week, label.

Covers ``profile_number_from_path``, ``profile_sort_key``, week and metadata reading, the slot
label, slot detection and the latest save.  Reads go through the save-format registry
(``read_scalars``); an unreadable file yields no values.

Documented divergence: the last-resort "any ``persist.*.json`` field containing ``week``" loop
skips ``persist.game.backup.*.json`` (the backups the app itself writes
next to the save), ``*.decoded.json`` and dot files, so a backup can no longer feed a stale week.
"""

import logging
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from src.core.errors import DDManagerError
from src.core.findings import Finding
from src.core.ids import SaveIdentity
from src.core.saves import SaveFormatRegistry, dson
from src.core.saves.format import DsonScalar
from src.services.detection import is_steam_cloud_path
from src.services.fsutil import safe_mtime_ns
from src.services.ports import Clock

_LOG: Final = logging.getLogger(__name__)
_PROFILE_RE: Final = re.compile(r"profile[_ -]?(\d+)", re.IGNORECASE)
_NO_NUMBER: Final = 9999

type _Candidate = tuple[str, str, int]
"""``(file name, field name, adjustment)`` of the week chain."""

_INRAID: Final[tuple[_Candidate, ...]] = (
    ("persist.campaign_log.json", "current_week", 0),
    ("persist.campaign_log.json", "total_weeks", 0),
    ("persist.estate.json", "week", 0),
)
_EXACT: Final[tuple[_Candidate, ...]] = (
    ("persist.town_event.json", "last_town_event_week", 0),
    ("persist.estate.json", "week", 0),
    ("persist.campaign_log.json", "current_week", 0),
    ("persist.campaign_log.json", "total_weeks", -1),
)


@dataclass(frozen=True, slots=True)
class SaveSlot:
    save_path: Path
    profile_dir: Path
    number: int | None
    date_time: str | None
    week: int | None
    mtime: datetime | None
    steam_cloud: bool
    findings: tuple[Finding, ...] = ()


def profile_number_from_path(path: Path) -> int | None:
    """``profile[_ -]?N`` over the path parts, the LAST match wins."""
    for part in reversed(path.parts):
        match = _PROFILE_RE.fullmatch(part)
        if match:
            return int(match.group(1))
    return None


def profile_sort_key(slot: SaveSlot) -> tuple[int, str]:
    """Slots without a number sort last; ties by casefolded path."""
    number = slot.number if slot.number is not None else _NO_NUMBER
    return (number, str(slot.save_path).casefold())


def slot_label(slot: SaveSlot) -> str:
    """``Profile N (slot N+1) - <date> - Week W [<dir>]``."""
    date = slot.date_time
    if not date:
        date = slot.mtime.strftime("%Y-%m-%d %H:%M") if slot.mtime is not None else "unknown date"
    if slot.number is None:
        base = f"Unknown Profile - {date}"
    else:
        base = f"Profile {slot.number} (slot {slot.number + 1}) - {date}"
    if slot.week is not None:
        base = f"{base} - Week {slot.week}"
    return f"{base} [{slot.save_path.parent.name}]"


def _week_number(values: dict[str, DsonScalar], field: str, adjustment: int) -> int | None:
    if field not in values:
        return None
    try:
        week = int(values[field]) + adjustment
    except TypeError, ValueError:
        return None
    return week if week >= 0 else None


def _is_week_source(name: str) -> bool:
    lower = name.lower()
    if not lower.startswith("persist.") or not lower.endswith(".json"):
        return False
    return not (lower.startswith("persist.game.backup.") or lower.endswith(".decoded.json"))


class SaveSlotService:
    def __init__(self, formats: SaveFormatRegistry, *, clock: Clock) -> None:
        self._formats = formats
        self._clock = clock  # kept for the service contract; slot times come from the files
        self._slot_cache: dict[Path, tuple[int | None, SaveSlot]] = {}
        self._applied_cache: dict[Path, tuple[int | None, tuple[SaveIdentity, ...]]] = {}
        self._applied_findings: dict[Path, Finding] = {}

    # ------------------------------------------------------------------ slots

    def slots(self, save_files: Sequence[Path]) -> list[SaveSlot]:
        """Unique files (case-insensitive) sorted by ``profile_sort_key``."""
        seen: set[str] = set()
        slots: list[SaveSlot] = []
        for path in save_files:
            key = str(path.absolute()).casefold()
            if key in seen:
                continue
            seen.add(key)
            slots.append(self._slot(path))
        return sorted(slots, key=profile_sort_key)

    def _slot(self, path: Path) -> SaveSlot:
        mtime_ns = safe_mtime_ns(path)
        cached = self._slot_cache.get(path)
        if cached is not None and cached[0] == mtime_ns:
            return self._with_applied_finding(cached[1])
        slot = self._build_slot(path, mtime_ns)
        self._slot_cache[path] = (mtime_ns, slot)
        return self._with_applied_finding(slot)

    def _with_applied_finding(self, slot: SaveSlot) -> SaveSlot:
        extra = self._applied_findings.get(slot.save_path)
        if extra is None or extra in slot.findings:
            return slot
        return SaveSlot(
            slot.save_path, slot.profile_dir, slot.number, slot.date_time, slot.week,
            slot.mtime, slot.steam_cloud, (*slot.findings, extra),
        )  # fmt: skip

    def _build_slot(self, path: Path, mtime_ns: int | None) -> SaveSlot:
        findings: list[Finding] = []
        values = self._scalars(path, {"date_time"}, findings)
        raw_date = values.get("date_time")
        date_time = str(raw_date).strip() if raw_date else ""
        mtime = None
        if mtime_ns is not None:
            # the LOCAL zone, like ``datetime.fromtimestamp(getmtime)``
            mtime = datetime.fromtimestamp(mtime_ns / 1e9, tz=UTC).astimezone()
        return SaveSlot(
            save_path=path,
            profile_dir=path.parent,
            number=profile_number_from_path(path),
            date_time=date_time or None,
            week=self.read_week(path),
            mtime=mtime,
            steam_cloud=is_steam_cloud_path(path),
            findings=tuple(findings),
        )

    # ------------------------------------------------------------------ week

    def read_week(self, save_path: Path) -> int | None:
        """In-raid chain, exact chain, then the filtered scan."""
        profile_dir = save_path.parent
        game = self._scalars(profile_dir / "persist.game.json", {"inraid"})
        if game.get("inraid") is True:
            week = self._chain(profile_dir, _INRAID)
            if week is not None:
                return week
        week = self._chain(profile_dir, _EXACT)
        return week if week is not None else self._scan_week(profile_dir)

    def _chain(self, profile_dir: Path, candidates: Sequence[_Candidate]) -> int | None:
        for filename, field, adjustment in candidates:
            path = profile_dir / filename
            if not path.is_file():
                continue
            week = _week_number(self._scalars(path, {field}), field, adjustment)
            if week is not None:
                return week
        return None

    def _scan_week(self, profile_dir: Path) -> int | None:
        try:
            names = sorted(entry.name for entry in profile_dir.iterdir())
        except OSError:
            return None
        for name in names:
            if _is_week_source(name):
                week = self._first_week(profile_dir / name)
                if week is not None:
                    return week
        return None

    def _first_week(self, path: Path) -> int | None:
        for name, value in self._week_fields(path).items():
            if name.lower().startswith("number_of_weeks_"):
                continue
            week = _week_number({name: value}, name, 0)
            if week is not None:
                return week
        return None

    def _week_fields(self, path: Path) -> dict[str, DsonScalar]:
        """Scalars whose name contains ``week``."""
        try:
            raw = path.read_bytes()
            doc = dson.parse(raw)
            names = {
                doc.name_of(i)
                for i, entry in enumerate(doc.meta2)
                if not entry.is_object and "week" in doc.name_of(i).lower()
            }
            return self._formats.detect(raw).read_scalars(raw, names)
        except (OSError, DDManagerError) as exc:
            _LOG.debug("no week fields in %s: %s", path, exc)
            return {}

    def _scalars(
        self, path: Path, names: Collection[str], findings: list[Finding] | None = None
    ) -> dict[str, DsonScalar]:
        try:
            raw = path.read_bytes()
            return self._formats.detect(raw).read_scalars(raw, names)
        except FileNotFoundError:
            return {}
        except (OSError, DDManagerError) as exc:
            _LOG.debug("cannot read scalars of %s: %s", path, exc)
            if findings is not None:
                message = f"Cannot read {path.name}: {exc}"
                findings.append(Finding.warning("save_slots.unreadable", message))
            return {}

    # ------------------------------------------------------------------ applied / latest

    def applied_entries(self, save_path: Path) -> tuple[SaveIdentity, ...]:
        """The applied block, cached by ``(path, mtime_ns)``; ``()`` plus a finding on error."""
        mtime_ns = safe_mtime_ns(save_path)
        cached = self._applied_cache.get(save_path)
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]
        try:
            raw = save_path.read_bytes()
            entries = self._formats.detect(raw).read_applied(raw)
        except (OSError, DDManagerError) as exc:
            message = f"Cannot read the applied mods of {save_path.name}: {exc}"
            self._applied_findings[save_path] = Finding.warning(
                "save_slots.applied_unreadable", message
            )
            entries = ()
        else:
            self._applied_findings.pop(save_path, None)
        self._applied_cache[save_path] = (mtime_ns, entries)
        return entries

    def latest(self, save_files: Sequence[Path]) -> Path | None:
        """With a guarded stat: the file with the greatest mtime."""
        best: tuple[int, Path] | None = None
        for path in save_files:
            mtime = safe_mtime_ns(path)
            if mtime is not None and (best is None or mtime > best[0]):
                best = (mtime, path)
        return best[1] if best else None
