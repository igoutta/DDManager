"""``ddmanager scan [--json]`` and ``ddmanager diagnostics``."""

import argparse
import json
import platform
import sys
from pathlib import Path

from src.__about__ import __version__
from src.cli_context import Session, detect_install, open_session, print_findings, scan_mods
from src.core.diagnostics import DiagnosticsInput, diagnostics_lines
from src.core.findings import Finding, Severity
from src.core.ids import ModId
from src.core.model import ModInfo
from src.services.scan import ScanResult

SCAN_SCHEMA = "ddmanager.scan"


def _finding_json(finding: Finding) -> dict[str, object]:
    return {
        "rule_id": finding.rule_id,
        "severity": Severity(finding.severity).name.lower(),
        "message": finding.message,
        "mod_ids": list(finding.mod_ids),
    }


def _mod_json(mod: ModId, info: ModInfo, scan: ScanResult, *, enabled: bool) -> dict[str, object]:
    return {
        "id": mod,
        "title": info.title,
        "source": info.source_id,
        "kind": info.kind.value,
        "workshop_id": info.workshop_id,
        "save_identity": {"name": info.save_identity.name, "source": info.save_identity.source},
        "path": str(scan.locations[mod].path) if mod in scan.locations else str(info.path),
        "enabled": enabled,
    }


def cmd_scan(args: argparse.Namespace) -> int:
    session = open_session(args.data_dir)
    install, scan = scan_mods(session)
    active = set(session.state.doc.order.active())
    if args.json:
        document = {
            "schema": SCAN_SCHEMA,
            "version": 1,
            "mod_roots": [str(root) for root in install.mod_roots],
            "mods": [_mod_json(m, i, scan, enabled=m in active) for m, i in scan.mods.items()],
            "findings": [_finding_json(f) for f in (*install.findings, *scan.findings)],
        }
        print(json.dumps(document, indent=2, ensure_ascii=False))
        return 0
    print(f"{len(scan.mods)} mod(s) in {len(install.mod_roots)} folder(s)")
    for mod, info in scan.mods.items():
        print(f"  [{'x' if mod in active else ' '}] {mod}  ({info.source_id}) {info.title}")
    print_findings((*install.findings, *scan.findings))
    return 0


def _first(paths: tuple[Path, ...]) -> str:
    return str(paths[0]) if paths else ""


def _applied_count(session: Session, save: str) -> int | None:
    if not save or not Path(save).is_file():
        return None
    entries = session.services.slots.applied_entries(Path(save))
    return len(entries)


def _platform_label() -> str:
    """``platform.platform()`` spawns ``cmd /c ver`` and WMI queries on Windows (over a second);
    the kernel version from ``sys.getwindowsversion()`` is instant and says the same thing."""
    windows_version = getattr(sys, "getwindowsversion", None)
    if windows_version is None:
        return platform.platform()
    version = windows_version()
    return f"Windows {version.major}.{version.minor}.{version.build}"


def build_diagnostics(session: Session) -> DiagnosticsInput:
    install = detect_install(session)
    scan = session.services.scanner.scan(install)
    settings = session.state.doc.settings
    doc = session.state.doc
    priority = session.services.initial_settings.priority
    mods_path = settings.mods_path or (
        str(install.primary_mods_dir) if install.primary_mods_dir else ""
    )
    extra = (
        ("Data folder mode", session.services.paths.mode.value),
        ("Plugins loaded", str(sum(r.status == "loaded" for r in session.services.plugin_records))),
        ("State origin", session.state.origin),
        ("Scan findings", str(len(scan.findings))),
    )
    return DiagnosticsInput(
        app_version=__version__,
        python_version=sys.version.split()[0],
        platform=_platform_label(),
        data_dir=str(session.services.paths.data_dir),
        mods_path=mods_path,
        mods_path_valid=bool(mods_path) and Path(mods_path).is_dir(),
        mod_count=len(scan.mods),
        enabled_count=sum(1 for mod in doc.order.active() if mod in scan.mods),
        uncategorized_count=sum(1 for mod in scan.mods if mod not in doc.categories),
        selected_save=settings.last_save_path,
        save_detected=bool(settings.last_save_path) and Path(settings.last_save_path).is_file(),
        save_has_applied_block=None,
        applied_count=_applied_count(session, settings.last_save_path),
        last_backup=settings.last_backup_path,
        game_root=_first(install.game_roots),
        workshop_dir=_first(install.workshop_dirs),
        local_mods_dir=_first(install.local_mod_dirs),
        priority_direction=priority.direction.value,
        priority_verified=priority.verified,
        extra=extra,
    )


def cmd_diagnostics(args: argparse.Namespace) -> int:
    session = open_session(args.data_dir)
    for line in diagnostics_lines(build_diagnostics(session)):
        print(line)
    print_findings((*session.state.findings, *session.services.startup_findings))
    return 0
