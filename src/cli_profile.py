"""``ddmanager profile list|save|export|import|apply``."""

import argparse

from src.__about__ import __version__
from src.cli_context import open_session, print_findings, scan_mods
from src.core.legacy_state import StateChanges
from src.core.loadorder_file import document_from_order, resolve_document


def cmd_list(args: argparse.Namespace) -> int:
    session = open_session(args.data_dir)
    summaries = session.services.profiles.list()
    if not summaries:
        print("no profiles")
    for summary in summaries:
        print(f"{summary.name}  ({summary.entry_count} mods)  {summary.path}")
        print_findings(summary.findings, prefix="  ")
    return 0


def cmd_save(args: argparse.Namespace) -> int:
    """Store the current state order as a named profile (every slot, disabled ones too)."""
    session = open_session(args.data_dir)
    services = session.services
    _, scan = scan_mods(session)
    doc = document_from_order(
        session.state.doc.order,
        scan.mods,
        name=args.name,
        priority=services.initial_settings.priority,
        created_with=f"ddmanager {__version__}",
        created_at=services.clock.now(),
        tiers={},
        include_disabled=True,
    )
    path = services.profiles.save(doc, overwrite=args.overwrite)
    print(f"saved {len(doc.entries)} mods to {path}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    session = open_session(args.data_dir)
    session.services.profiles.export(session.services.profiles.load(args.name), args.dest)
    print(f"exported {args.name!r} to {args.dest}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    session = open_session(args.data_dir)
    doc, extras = session.services.profiles.import_file(args.file)
    path = session.services.profiles.save(doc, overwrite=args.overwrite)
    print(f"imported {doc.name!r} ({len(doc.entries)} mods) to {path}")
    if extras is not None:
        print("note: the legacy nicknames and categories of the loadout were not imported")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Adopt a profile's order and enabled flags in ``mod_state.json`` (never touches a save)."""
    session = open_session(args.data_dir)
    doc = session.services.profiles.load(args.name)
    _, scan = scan_mods(session)
    result = resolve_document(doc, scan.mods, session.state.doc.order)
    print(f"matched {len(result.matched)} of {len(doc.entries)} mods")
    print_findings(result.findings)
    if args.dry_run:
        print("dry run: mod_state.json was not changed")
        return 0
    session.services.state.save(
        session.state.doc,
        StateChanges(order=result.order),
        expected=session.state.fingerprint,
    )
    print(f"profile {args.name!r} applied; {len(result.order.active())} mods enabled")
    return 0
