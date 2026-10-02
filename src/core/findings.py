"""Findings and fixes: the one diagnostic value that rules, parsers and planners produce.

This module sits at the bottom of the dependency graph (it needs only ``ids``) so the file
formats (rules file, load-order file, state file) and the planners can report problems without
pulling in the validation machinery.  :mod:`src.core.validation` re-exports every name here.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import IntEnum

from src.core.ids import ModId


class Severity(IntEnum):
    """How bad a finding is; ``ERROR`` findings block patching a save."""

    INFO = 10
    WARNING = 20
    ERROR = 30


# ---------------------------------------------------------------- fixes


@dataclass(frozen=True, slots=True)
class MakeWin:
    """Move ``winner`` so that it wins conflicts against ``over``."""

    winner: ModId
    over: ModId


@dataclass(frozen=True, slots=True)
class DisableMods:
    """Disable the listed mods (their slots in the load order are kept)."""

    mods: tuple[ModId, ...]


@dataclass(frozen=True, slots=True)
class EnableMods:
    """Enable the listed mods (appended after the last active entry)."""

    mods: tuple[ModId, ...]


@dataclass(frozen=True, slots=True)
class SetTier:
    """Assign ``tier_id`` to ``mod`` (a state change, not a load-order change)."""

    mod: ModId
    tier_id: str


type Fix = MakeWin | DisableMods | EnableMods | SetTier


# ---------------------------------------------------------------- findings


@dataclass(frozen=True, slots=True)
class Finding:
    """One diagnostic: which rule fired, how bad, which mods, and an optional one-click fix.

    ``message`` is always a complete English sentence; ``message_key``/``params`` let the UI
    render a translated equivalent when a translation exists.  ``details`` carries sample
    paths or other free-form lines shown below the message.
    """

    rule_id: str
    severity: Severity
    message: str
    mod_ids: tuple[ModId, ...] = ()
    fix: Fix | None = None
    message_key: str = ""
    params: tuple[tuple[str, str], ...] = ()
    details: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        """Stable identity for UI focus/selection: ``"<rule_id>:<mod,mod,...>"``."""
        return f"{self.rule_id}:{','.join(self.mod_ids)}"

    @classmethod
    def at(
        cls,
        severity: Severity,
        rule_id: str,
        message: str,
        *,
        mod_ids: Iterable[ModId] = (),
        details: Iterable[str] = (),
        **params: str,
    ) -> Finding:
        """A finding whose ``message_key`` is ``finding.<rule_id>`` and whose params are sorted.

        This is the shape every format module and planner uses; rules that need a fix or a
        sub-key construct the dataclass directly.
        """
        return cls._make(severity, rule_id, message, mod_ids, details, params)

    @classmethod
    def info(cls, rule_id: str, message: str, **params: str) -> Finding:
        return cls._make(Severity.INFO, rule_id, message, (), (), params)

    @classmethod
    def warning(cls, rule_id: str, message: str, **params: str) -> Finding:
        return cls._make(Severity.WARNING, rule_id, message, (), (), params)

    @classmethod
    def error(cls, rule_id: str, message: str, **params: str) -> Finding:
        return cls._make(Severity.ERROR, rule_id, message, (), (), params)

    @classmethod
    def _make(
        cls,
        severity: Severity,
        rule_id: str,
        message: str,
        mod_ids: Iterable[ModId],
        details: Iterable[str],
        params: Mapping[str, str],
    ) -> Finding:
        return cls(
            rule_id=rule_id,
            severity=severity,
            message=message,
            mod_ids=tuple(mod_ids),
            message_key=f"finding.{rule_id}",
            params=tuple(sorted(params.items())),
            details=tuple(details),
        )
