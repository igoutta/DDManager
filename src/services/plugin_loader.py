"""Built-in registration and the opt-in, hash-pinned loader for user plugins.

User plugins are arbitrary Python, so nothing runs unless the user turned plugins on AND approved
the exact sha256 of the file (``Settings.plugins``).  Every plugin registers into a STAGING
registry that is merged only when ``register`` returned cleanly, so a plugin that raises,
exits or clashes on an id leaves the live registry untouched.  A problem is reported as a
``plugin.*`` finding and a :class:`PluginRecord`; it never aborts start-up.
"""

import hashlib
import importlib.util
import logging
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Final, Literal

from src.core.findings import Finding
from src.core.saves import DEFAULT_SAVE_FORMATS
from src.plugins import BUILTIN_SOURCES
from src.rules import BUILTIN_RULES
from src.services.plugin_registry import PluginRegistry
from src.services.settings_repo import PluginTrust

API_VERSION: Final = 1

_LOG: Final = logging.getLogger(__name__)

type Status = Literal["loaded", "not_approved", "changed", "disabled", "failed", "incompatible"]
type Origin = Literal["builtin", "user"]


@dataclass(frozen=True, slots=True)
class PluginRecord:
    plugin_id: str
    origin: Origin
    path: Path | None
    sha256: str | None
    status: Status
    contributed: tuple[str, ...]
    error: str | None


@dataclass(frozen=True, slots=True)
class GatedImport:
    """Result of :func:`import_gated`: the module when it ran, the record and any findings."""

    record: PluginRecord
    module: ModuleType | None
    findings: tuple[Finding, ...]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_builtin(registry: PluginRegistry) -> list[PluginRecord]:
    """Register the shipped sources, rules and save formats (static imports, PyInstaller-safe)."""
    for source in BUILTIN_SOURCES:
        registry.add_mod_source(source)
    for rule in BUILTIN_RULES:
        registry.add_rule(rule)
    for fmt in DEFAULT_SAVE_FORMATS:
        registry.add_save_format(fmt)
    groups = (
        ("builtin.mod_sources", tuple(s.source_id for s in BUILTIN_SOURCES)),
        ("builtin.rules", tuple(r.rule_id for r in BUILTIN_RULES)),
        ("builtin.save_formats", tuple(f.format_id for f in DEFAULT_SAVE_FORMATS)),
    )
    return [PluginRecord(name, "builtin", None, None, "loaded", ids, None) for name, ids in groups]


# ---------------------------------------------------------------- trust gate + import


def _trust_status(name: str, digest: str, trust: PluginTrust) -> Status | None:
    """``None`` when the file may run; otherwise why it may not."""
    if name in trust.disabled:
        return "disabled"
    approved = trust.approved.get(name)
    if approved is None:
        return "not_approved"
    return None if approved == digest else "changed"


def _record(
    path: Path, digest: str | None, status: Status, error: str | None = None
) -> PluginRecord:
    return PluginRecord(path.stem, "user", path, digest, status, (), error)


def _gate_finding(record: PluginRecord) -> Finding:
    name = record.path.name if record.path else record.plugin_id
    messages = {
        "disabled": f"{name} is switched off.",
        "not_approved": f"{name} is not approved yet; it was not run.",
        "changed": f"{name} changed since it was approved; it was not run.",
    }
    return Finding.info(f"plugin.{record.status}", messages[record.status])


def import_gated(path: Path, trust: PluginTrust, *, namespace: str) -> GatedImport:
    """Hash-check ``path`` against ``trust`` and, only if approved, import it privately."""
    try:
        digest = sha256_of(path)
    except OSError as exc:
        record = _record(path, None, "failed", str(exc))
        return GatedImport(record, None, (_failure(path, str(exc)),))
    status = _trust_status(path.name, digest, trust)
    if status is not None:
        record = _record(path, digest, status)
        return GatedImport(record, None, (_gate_finding(record),))
    return _import(path, digest, namespace)


def _failure(path: Path, why: str) -> Finding:
    return Finding.warning("plugin.load_failed", f"{path.name} could not be loaded: {why}")


def _import(path: Path, digest: str, namespace: str) -> GatedImport:
    name = f"_ddmanager_{namespace}_{re.sub(r'\W', '_', path.stem)}"
    try:
        module = _exec_module(path, name)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - plugin code is untrusted; reported
        _LOG.exception("plugin %s failed to import", path)
        sys.modules.pop(name, None)
        why = f"{type(exc).__name__}: {exc}"
        return GatedImport(_record(path, digest, "failed", why), None, (_failure(path, why),))
    version = getattr(module, "API_VERSION", API_VERSION)
    if not isinstance(version, int) or version > API_VERSION:
        sys.modules.pop(name, None)
        why = f"needs plugin API {version!r}, this app provides {API_VERSION}"
        finding = Finding.warning("plugin.incompatible", f"{path.name} {why}.")
        return GatedImport(_record(path, digest, "incompatible", why), None, (finding,))
    return GatedImport(_record(path, digest, "loaded"), module, ())


def _exec_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- user plugins


def load_user_plugins(
    directory: Path, registry: PluginRegistry, trust: PluginTrust
) -> tuple[list[PluginRecord], list[Finding]]:
    """Load approved ``*.py`` plugins of ``directory`` (nothing unless ``trust.enabled``)."""
    records: list[PluginRecord] = []
    findings: list[Finding] = []
    if not trust.enabled:
        return records, findings
    for path in plugin_files(directory):
        gated = import_gated(path, trust, namespace="plugin")
        findings.extend(gated.findings)
        if gated.module is None:
            records.append(gated.record)
            continue
        record, extra = _register(gated, registry)
        records.append(record)
        findings.extend(extra)
    return records, findings


def plugin_files(directory: Path) -> list[Path]:
    try:
        return sorted(
            p for p in directory.glob("*.py") if p.is_file() and not p.name.startswith("_")
        )
    except OSError:
        return []


def _register(gated: GatedImport, registry: PluginRegistry) -> tuple[PluginRecord, list[Finding]]:
    """Run ``register`` against a staging registry and merge it only on success."""
    register = getattr(gated.module, "register", None)
    if not callable(register):
        return _failed(gated.record, "the module does not export register(registry)")
    staging = registry.staging()
    try:
        register(staging)
        contributed = staging.commit_into(registry)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - plugin code is untrusted; reported
        _LOG.exception("plugin %s failed to register", gated.record.plugin_id)
        return _failed(gated.record, f"{type(exc).__name__}: {exc}")
    return replace(gated.record, contributed=tuple(contributed)), []


def _failed(record: PluginRecord, why: str) -> tuple[PluginRecord, list[Finding]]:
    path = record.path
    name = path.name if path else record.plugin_id
    finding = Finding.warning("plugin.load_failed", f"{name} could not be loaded: {why}")
    return replace(record, status="failed", error=why), [finding]
