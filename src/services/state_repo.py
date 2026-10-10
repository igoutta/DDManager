"""Repository for ``mod_state.json`` (the 22-key document plus ``schema_version``).

Load with backup recovery, save with one-file rotation, with these data-safety rules:

* rotation ``main -> mod_state.backup.json`` happens ONLY when the main file still parses as a
  JSON object, so a corrupt main never overwrites a good backup;
* a corrupt main is preserved as ``mod_state.corrupt.<ts>.json`` before it is replaced;
* every write is atomic and a stale ``expected`` fingerprint raises :class:`StateConflictError`
  instead of clobbering a concurrent change.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from src.core.findings import Finding, Severity
from src.core.state_file import (
    StateChanges,
    StateDoc,
    parse_state,
    render_state,
    render_state_json,
)
from src.services.app_paths import AppPaths
from src.services.errors import StateConflictError, StateReadOnlyError
from src.services.fsutil import (
    FileFingerprint,
    atomic_copy,
    atomic_write_bytes,
    atomic_write_text,
    backup_timestamp,
    unique_path,
)
from src.services.ports import Clock

_LOG: Final = logging.getLogger(__name__)

type Origin = Literal["main", "backup", "default"]


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """What :meth:`StateRepository.load` found; ``fingerprint`` is the main file's at read time."""

    doc: StateDoc
    fingerprint: FileFingerprint | None
    origin: Origin
    writable: bool
    findings: tuple[Finding, ...]


def same_content(a: FileFingerprint | None, b: FileFingerprint | None) -> bool:
    """Equality on existence, size and sha256 (a pure ``touch`` is not a conflict)."""
    if a is None or b is None:
        return a is b
    return a.sha256 == b.sha256 and a.size == b.size


def _read_object(path: Path) -> tuple[dict[str, object] | None, str]:
    """The JSON object in ``path`` (``None`` when missing/unparseable/not an object) and why not."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        return None, str(exc)
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        return None, str(exc)
    if not isinstance(obj, dict):
        return None, "the root is not a JSON object"
    return obj, ""


class StateRepository:
    """Loads and saves ``<data>/mod_state.json``; never asks, never partially writes."""

    def __init__(self, paths: AppPaths, *, default_language: str, clock: Clock) -> None:
        self._paths = paths
        self._default_language = default_language
        self._clock = clock
        self._read_only_reason: str | None = None

    # ------------------------------------------------------------------ load

    def load(self) -> StateSnapshot:
        """Main file, else backup (WARNING finding), else defaults (ERROR finding).

        A missing main yields defaults with no finding (first run).  ``writable`` is False when
        the parsed document reported ERROR findings; :meth:`save` then refuses.
        """
        main = self._paths.state_file
        fingerprint = FileFingerprint.of(main)
        obj, why = _read_object(main)
        if obj is not None:
            return self._snapshot(obj, fingerprint, "main", ())
        if why == "missing":
            return self._snapshot({}, fingerprint, "default", ())
        return self._recover(fingerprint, why)

    def _recover(self, fingerprint: FileFingerprint | None, why: str) -> StateSnapshot:
        backup, _ = _read_object(self._paths.state_backup_file)
        if backup is not None:
            note = Finding.warning(
                "state.recovered_from_backup",
                f"The state file could not be read ({why}); the backup state was loaded.",
                reason=why,
            )
            return self._snapshot(backup, fingerprint, "backup", (note,))
        note = Finding.error(
            "state.unreadable",
            f"The state file could not be read ({why}) and no usable backup exists;"
            " defaults are used. The unreadable file is preserved when state is next saved.",
            reason=why,
        )
        return self._snapshot({}, fingerprint, "default", (note,), recovered_defaults=True)

    def _snapshot(
        self,
        obj: dict[str, object],
        fingerprint: FileFingerprint | None,
        origin: Origin,
        extra: tuple[Finding, ...],
        *,
        recovered_defaults: bool = False,
    ) -> StateSnapshot:
        doc, parsed = parse_state(obj, default_language=self._default_language)
        findings = (*extra, *parsed)
        # "state.unreadable" does not lock the repository: saving defaults over a corrupt main
        # is how the user recovers, and the corrupt file is preserved first (see _rotate_previous).
        blocking = [
            finding
            for finding in parsed
            if finding.severity >= Severity.ERROR and not recovered_defaults
        ]
        self._read_only_reason = blocking[0].message if blocking else None
        return StateSnapshot(doc, fingerprint, origin, not blocking, findings)

    # ------------------------------------------------------------------ save

    def save(
        self,
        base: StateDoc,
        changes: StateChanges,
        *,
        expected: FileFingerprint | None,
        force: bool = False,
    ) -> FileFingerprint:
        """Apply ``changes`` onto ``base`` and write the result atomically.

        Order: read-only gate, conflict gate (``expected`` ``None`` means "the file must not
        exist"), render, rotate/preserve the previous main, atomic write.
        """
        if self._read_only_reason is not None:
            raise StateReadOnlyError(
                "The state file was opened read-only and will not be overwritten.",
                reason=self._read_only_reason,
            )
        actual = FileFingerprint.of(self._paths.state_file)
        if not force and not same_content(expected, actual):
            raise StateConflictError(
                "mod_state.json changed on disk since it was loaded.",
                expected=expected,
                actual=actual,
            )
        text = render_state_json(render_state(base, changes))
        self._rotate_previous()
        atomic_write_text(self._paths.state_file, text)
        written = FileFingerprint.of(self._paths.state_file)
        if written is None:  # the file we just moved into place vanished
            raise StateConflictError(
                "mod_state.json vanished after it was written.", expected=expected, actual=None
            )
        return written

    def _rotate_previous(self) -> None:
        """Copy main to the backup, but only when main is a good object."""
        main = self._paths.state_file
        try:
            raw = main.read_bytes()
        except FileNotFoundError:
            return
        except OSError as exc:
            _LOG.warning("cannot read %s to rotate it: %s", main, exc)
            return
        obj, _ = _read_object(main)
        target = self._paths.state_backup_file if obj is not None else self._corrupt_copy_path()
        try:
            atomic_write_bytes(target, raw)
        except OSError as exc:
            _LOG.warning("cannot copy %s to %s: %s", main, target, exc)

    def _corrupt_copy_path(self) -> Path:
        stamp = backup_timestamp(self._clock.now())
        return unique_path(self._paths.corrupt_state_file(stamp))

    # ------------------------------------------------------------------ misc

    def ensure_pre_upgrade_copy(self) -> bool:
        """Copy ``mod_state.json`` to ``mod_state.pre-0.3.0.json`` once; never overwrite."""
        target = self._paths.pre_upgrade_state_file
        if target.exists() or not self._paths.state_file.is_file():
            return False
        atomic_copy(self._paths.state_file, target)
        return True

    def changed_since(self, fp: FileFingerprint | None) -> bool:
        return not same_content(fp, FileFingerprint.of(self._paths.state_file))

    def read_language(self) -> str | None:
        """The saved language of main, else of the backup."""
        for path in (self._paths.state_file, self._paths.state_backup_file):
            obj, _ = _read_object(path)
            language = obj.get("language") if obj is not None else None
            if isinstance(language, str) and language:
                return language
        return None
