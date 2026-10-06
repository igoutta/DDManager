"""``ddmanager save plan|patch|backup|restore``: thin wrappers over the save services."""

import argparse
from datetime import datetime
from pathlib import Path

from src.cli_context import (
    Session,
    active_identities,
    missing_mods,
    open_session,
    print_findings,
    scan_mods,
)
from src.core.ids import SaveIdentity
from src.core.legacy_state import StateChanges
from src.core.load_order import missing_active
from src.services.backup import BackupReason, BackupRecord
from src.services.errors import BackupNotFoundError, StateConflictError, UnacknowledgedRiskError
from src.services.fsutil import atomic_write_bytes
from src.services.save_patch import (
    ACK_DUPLICATE_IDENTITY,
    ACK_GAME_STATE_UNKNOWN,
    ACK_NON_DEFAULT_FILENAME,
    ACK_STEAM_CLOUD,
    PatchPlan,
)

ACK_CHOICES = (
    ACK_STEAM_CLOUD,
    ACK_DUPLICATE_IDENTITY,
    ACK_NON_DEFAULT_FILENAME,
    ACK_GAME_STATE_UNKNOWN,
)


def _show(entry: SaveIdentity) -> str:
    return f"{entry.name} | {entry.source}"


def _print_plan(plan: PatchPlan) -> None:
    print(f"save: {plan.save_path}")
    print(f"format: {plan.format_id}")
    print(f"original: sha256 {plan.original.sha256[:16]}... ({plan.original.size} bytes)")
    print(f"applied mods: {len(plan.before)} -> {len(plan.after)}")
    for entry in plan.diff.added:
        print(f"  + {_show(entry)}")
    for entry in plan.diff.removed:
        print(f"  - {_show(entry)}")
    for entry, old, new in plan.diff.moved:
        print(f"  ~ {_show(entry)}: {old + 1} -> {new + 1}")
    if plan.diff.is_empty:
        print("  (no change to the applied mods)")
    print_findings(plan.findings)
    if plan.required_acks:
        print(
            "acknowledgements needed: " + " ".join(f"--ack {a}" for a in sorted(plan.required_acks))
        )


def _make_plan(session: Session, save_path: Path) -> PatchPlan:
    _, scan = scan_mods(session)
    order = session.state.doc.order
    skipped = missing_active(order, missing_mods(session, scan, order))
    if skipped:
        print(
            f"{len(skipped)} enabled mod(s) are missing from disk and will not be written: "
            + ", ".join(skipped)
        )
    entries = active_identities(session, scan)
    return session.services.patcher.plan(save_path, entries)


def cmd_plan(args: argparse.Namespace) -> int:
    session = open_session(args.data_dir)
    plan = _make_plan(session, args.file)
    _print_plan(plan)
    if args.emit is not None:
        atomic_write_bytes(args.emit, plan.patched)
        print(f"patched bytes written to {args.emit} (the save itself was not touched)")
    return 0


def _remember(session: Session, save_path: Path, backup: BackupRecord) -> None:
    """``dd2.py:1778-1782``: remember the save and its backup in the state."""
    changes = StateChanges(
        settings={
            "last_save_path": str(save_path),
            "last_backup_path": str(backup.path),
            "last_output_path": str(save_path),
        }
    )
    try:
        session.services.state.save(session.state.doc, changes, expected=session.state.fingerprint)
    except StateConflictError:
        print("warning: mod_state.json changed meanwhile; the last-backup path was not saved")


def cmd_patch(args: argparse.Namespace) -> int:
    session = open_session(args.data_dir)
    plan = _make_plan(session, args.file)
    _print_plan(plan)
    try:
        result = session.services.patcher.apply(plan, acknowledged=frozenset(args.ack))
    except UnacknowledgedRiskError as exc:
        print("re-run with: " + " ".join(f"--ack {a}" for a in sorted(exc.missing)))
        raise
    print(f"patched {result.save_path}")
    print(f"backup: {result.backup.path}")
    _remember(session, result.save_path, result.backup)
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    session = open_session(args.data_dir)
    record = session.services.backups.create(args.file, reason=BackupReason.MANUAL)
    print(f"backup: {record.path}")
    return 0


def _choose_backup(session: Session, save_path: Path, source: Path | None) -> BackupRecord:
    backups = session.services.backups
    if source is None:
        latest = backups.latest(save_path)
        if latest is None:
            raise BackupNotFoundError(f"No backup of {save_path} was found.", path=str(save_path))
        return latest
    wanted = source.absolute()
    for record in backups.list(save_path):
        if record.path.absolute() == wanted:
            return record
    if not source.is_file():
        raise BackupNotFoundError(f"Backup file not found: {source}", path=str(source))
    stat = source.stat()
    created = datetime.fromtimestamp(stat.st_mtime).astimezone()
    return BackupRecord(source, save_path, created, None, stat.st_size, None, "legacy")


def cmd_restore(args: argparse.Namespace) -> int:
    session = open_session(args.data_dir)
    record = _choose_backup(session, args.file, args.source)
    result = session.services.backups.restore(record, target=args.file)
    print(f"restored {result.restored_from.path.name} -> {result.target}")
    print(f"previous contents saved as {result.pre_restore_backup.path}")
    return 0
