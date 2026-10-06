"""``<data>/settings.json``: the new app's own settings (``ddmanager.settings`` v1).

Everything that is not part of the legacy ``mod_state.json`` lives here: priority direction,
active profile, backup retention and the plugin/rule-module trust lists.  The reader is tolerant:
a wrong type yields the default plus a finding, unknown keys are kept and written back, and a
missing file is simply the defaults.  Newer ``format_version`` values are read best-effort.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from src.core.findings import Finding
from src.core.json_values import JsonValue
from src.core.load_order import PriorityDirection, PrioritySetting
from src.services.fsutil import atomic_write_text

FORMAT: Final = "ddmanager.settings"
FORMAT_VERSION: Final = 1
_KNOWN_KEYS: Final = frozenset({
    "format", "format_version", "priority", "active_profile", "selected_save", "backups",
    "plugins", "rules", "refuse_when_game_running", "language",
})  # fmt: skip


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Managed-backup retention: delete only what is outside ALL three protections."""

    keep_last: int = 20
    keep_days: int = 30
    min_keep: int = 3


@dataclass(frozen=True, slots=True)
class PluginTrust:
    """Opt-in code loading: nothing runs unless ``enabled`` and the file's hash is approved."""

    enabled: bool = False
    approved: Mapping[str, str] = field(default_factory=dict)
    """File name -> sha256 of the approved content."""
    disabled: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Settings:
    priority: PrioritySetting = field(default_factory=PrioritySetting)
    active_profile: str | None = None
    selected_save: Path | None = None
    backups: RetentionPolicy = field(default_factory=RetentionPolicy)
    plugins: PluginTrust = field(default_factory=PluginTrust)
    rules: PluginTrust = field(default_factory=PluginTrust)
    refuse_when_game_running: bool = True
    language: str | None = None
    extra: tuple[tuple[str, JsonValue], ...] = ()
    """Unknown top-level keys, written back untouched."""


# ---------------------------------------------------------------- typed readers


class _Reader:
    """Typed access to one JSON object; wrong types yield the default and a finding."""

    def __init__(self, obj: object, where: str, findings: list[Finding]) -> None:
        self._obj: Mapping[str, object] = obj if isinstance(obj, dict) else {}
        self._where = where
        self._findings = findings
        if obj is not None and not isinstance(obj, dict):
            self._bad(where, "an object")

    def _bad(self, key: str, expected: str) -> None:
        message = f"settings: '{key}' should be {expected}; the default is used."
        self._findings.append(Finding.warning("settings.bad_value", message))

    def _get(self, key: str) -> object:
        return self._obj.get(key)

    def boolean(self, key: str, *, default: bool) -> bool:
        value = self._get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        self._bad(f"{self._where}.{key}", "true or false")
        return default

    def integer(self, key: str, default: int, minimum: int = 0) -> int:
        value = self._get(key)
        if value is None:
            return default
        if isinstance(value, int) and not isinstance(value, bool) and value >= minimum:
            return value
        self._bad(f"{self._where}.{key}", f"an integer >= {minimum}")
        return default

    def text(self, key: str) -> str | None:
        value = self._get(key)
        if value is None:
            return None
        if isinstance(value, str) and value:
            return value
        if value != "":
            self._bad(f"{self._where}.{key}", "text")
        return None

    def mapping(self, key: str) -> object:
        return self._get(key)

    def str_map(self, key: str) -> dict[str, str]:
        value = self._get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            self._bad(f"{self._where}.{key}", "an object of text")
            return {}
        return {k: v for k, v in value.items() if isinstance(v, str)}

    def str_list(self, key: str) -> frozenset[str]:
        value = self._get(key)
        if value is None:
            return frozenset()
        if not isinstance(value, list):
            self._bad(f"{self._where}.{key}", "a list of text")
            return frozenset()
        return frozenset(item for item in value if isinstance(item, str))


def _priority(root: _Reader, findings: list[Finding]) -> PrioritySetting:
    reader = _Reader(root.mapping("priority"), "priority", findings)
    raw = reader.text("direction") or PriorityDirection.FIRST_WINS.value
    try:
        direction = PriorityDirection(raw)
    except ValueError:
        message = f"settings: unknown priority direction {raw!r}; first_wins is used."
        findings.append(Finding.warning("settings.bad_value", message))
        direction = PriorityDirection.FIRST_WINS
    return PrioritySetting(direction, reader.boolean("verified", default=True))


def _retention(root: _Reader, findings: list[Finding]) -> RetentionPolicy:
    reader = _Reader(root.mapping("backups"), "backups", findings)
    default = RetentionPolicy()
    return RetentionPolicy(
        keep_last=reader.integer("keep_last", default.keep_last, 1),
        keep_days=reader.integer("keep_days", default.keep_days, 0),
        min_keep=reader.integer("min_keep", default.min_keep, 0),
    )


def _trust(root: _Reader, key: str, findings: list[Finding]) -> PluginTrust:
    reader = _Reader(root.mapping(key), key, findings)
    return PluginTrust(
        enabled=reader.boolean("enabled", default=False),
        approved=reader.str_map("approved"),
        disabled=reader.str_list("disabled"),
    )


def parse_settings(obj: object) -> tuple[Settings, list[Finding]]:
    """Total parser: never raises; repairs become ``settings.*`` findings."""
    findings: list[Finding] = []
    if not isinstance(obj, dict):
        findings.append(
            Finding.warning("settings.bad_value", "settings: the root is not an object.")
        )
        return Settings(), findings
    root = _Reader(obj, "settings", findings)
    saved = root.text("selected_save")
    settings = Settings(
        priority=_priority(root, findings),
        active_profile=root.text("active_profile"),
        selected_save=Path(saved) if saved else None,
        backups=_retention(root, findings),
        plugins=_trust(root, "plugins", findings),
        rules=_trust(root, "rules", findings),
        refuse_when_game_running=root.boolean("refuse_when_game_running", default=True),
        language=root.text("language"),
        extra=tuple((key, value) for key, value in obj.items() if key not in _KNOWN_KEYS),
    )
    return settings, findings


# ---------------------------------------------------------------- render


def _trust_json(trust: PluginTrust) -> dict[str, JsonValue]:
    approved: dict[str, JsonValue] = {name: trust.approved[name] for name in sorted(trust.approved)}
    disabled: list[JsonValue] = [*sorted(trust.disabled)]
    return {"enabled": trust.enabled, "approved": approved, "disabled": disabled}


def render_settings(settings: Settings) -> str:
    obj: dict[str, JsonValue] = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "priority": {
            "direction": settings.priority.direction.value,
            "verified": settings.priority.verified,
        },
        "active_profile": settings.active_profile,
        "selected_save": str(settings.selected_save) if settings.selected_save else None,
        "backups": {
            "keep_last": settings.backups.keep_last,
            "keep_days": settings.backups.keep_days,
            "min_keep": settings.backups.min_keep,
        },
        "plugins": _trust_json(settings.plugins),
        "rules": _trust_json(settings.rules),
        "refuse_when_game_running": settings.refuse_when_game_running,
        "language": settings.language,
    }
    obj.update(dict(settings.extra))
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


class SettingsRepository:
    """Loads/saves ``settings.json``; a damaged file is replaced only by an explicit ``save``."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> tuple[Settings, list[Finding]]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Settings(), []
        except (OSError, UnicodeDecodeError) as exc:
            return Settings(), [self._unreadable(str(exc))]
        try:
            obj = json.loads(text)
        except (ValueError, RecursionError) as exc:
            return Settings(), [self._unreadable(str(exc))]
        settings, findings = parse_settings(obj)
        version = obj.get("format_version") if isinstance(obj, dict) else None
        if isinstance(version, int) and version > FORMAT_VERSION:
            note = "settings.json was written by a newer DD Manager; unknown values are kept."
            findings.append(Finding.info("settings.newer_version", note))
        return settings, findings

    def _unreadable(self, why: str) -> Finding:
        message = f"settings.json could not be read ({why}); defaults are used."
        return Finding.warning("settings.unreadable", message)

    def save(self, settings: Settings) -> None:
        atomic_write_text(self._path, render_settings(settings))
