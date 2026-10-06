"""Shared plumbing of the CLI subcommands: services, installation scan and error formatting."""

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import src
from src.core.findings import Finding, Severity
from src.core.ids import ModId, SaveIdentity
from src.core.load_order import LoadOrder, applied_entries
from src.services.app_paths import AppPaths, resolve_app_paths
from src.services.bootstrap import Services, build_services
from src.services.detection import InstallSnapshot, ManualPaths
from src.services.environment import Environment
from src.services.errors import ServiceError
from src.services.scan import ScanResult
from src.services.state_repo import StateSnapshot


@dataclass(frozen=True, slots=True)
class Session:
    """What most subcommands need: wired services and the state as loaded."""

    services: Services
    state: StateSnapshot


def open_session(data_dir: str | None) -> Session:
    """Resolve the data directory, wire the services and load ``mod_state.json``."""
    env = Environment.from_host()
    paths: AppPaths = resolve_app_paths(
        frozen=bool(getattr(sys, "frozen", False)),
        executable=Path(sys.executable),
        package_init=Path(src.__file__),
        env=env,
        override=Path(data_dir) if data_dir else None,
    )
    services = build_services(paths, env=env)
    return Session(services, services.state.load())


def _optional_path(text: str) -> Path | None:
    return Path(text) if text.strip() else None


def detect_install(session: Session) -> InstallSnapshot:
    """Run installation detection with the manual paths and mods folder saved in the state."""
    settings = session.state.doc.settings
    manual = ManualPaths(
        game_root=_optional_path(settings.manual_game_root),
        local_mods=_optional_path(settings.manual_local_mods_path),
        workshop_mods=_optional_path(settings.manual_workshop_mods_path),
    )
    return session.services.detector.detect(manual, _optional_path(settings.mods_path))


def scan_mods(session: Session) -> tuple[InstallSnapshot, ScanResult]:
    install = detect_install(session)
    return install, session.services.scanner.scan(install)


def identity_map(session: Session, scan: ScanResult) -> dict[ModId, SaveIdentity]:
    """Scanned identities win over the ones cached in the state metadata."""
    known = dict(session.state.doc.metadata_identities)
    known.update({mod: info.save_identity for mod, info in scan.mods.items()})
    return known


def active_identities(
    session: Session, scan: ScanResult, order: LoadOrder | None = None
) -> tuple[SaveIdentity, ...]:
    """The applied-mods list for ``order`` (default: the state order), or a service error."""
    chosen = order if order is not None else session.state.doc.order
    try:
        return applied_entries(chosen, identity_map(session, scan))
    except ValueError as exc:
        raise ServiceError(str(exc), code="identity_missing") from exc


def print_findings(findings: Iterable[Finding], *, prefix: str = "") -> None:
    for finding in findings:
        label = Severity(finding.severity).name.lower()
        print(f"{prefix}[{label}] {finding.rule_id}: {finding.message}")
        for line in finding.details:
            print(f"{prefix}    {line}")
