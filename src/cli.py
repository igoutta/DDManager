"""Command-line entry point. Subcommands are added milestone by milestone."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from src.__about__ import __version__
from src.core.errors import DDManagerError, UnknownSaveFormatError
from src.core.saves import DsonProblem, SaveFormat, SaveValidationReport, default_registry
from src.core.saves import dson as dson_codec
from src.core.saves.dson_v1 import DsonV1Format


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ddmanager", description="DD Manager (Darkest Dungeon 1)")
    parser.add_argument("--version", action="version", version=f"ddmanager {__version__}")
    parser.add_argument("--data-dir", help="override the DD Manager Data directory")
    commands = parser.add_subparsers(dest="command")

    save = commands.add_parser("save", help="inspect or verify a binary save (persist.game.json)")
    save_commands = save.add_subparsers(dest="save_command", required=True)
    inspect = save_commands.add_parser(
        "inspect", help="print format, header numbers, applied mods and validation problems"
    )
    inspect.add_argument("file", type=Path, help="path to a persist.game.json")
    verify = save_commands.add_parser(
        "verify", help="exit 0 when the save is legacy-valid, 1 otherwise"
    )
    verify.add_argument("file", type=Path, help="path to a persist.game.json")
    return parser


def _read_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return None


def _print_problems(label: str, problems: Sequence[DsonProblem], *, skipped: bool = False) -> None:
    if not problems:
        print(f"{label}: skipped (fix the legacy problems first)" if skipped else f"{label}: OK")
        return
    print(f"{label}: {len(problems)} problem(s)")
    for problem in problems:
        print(f"  [{problem.code}] @{problem.offset}: {problem.message}")


def _print_report(report: SaveValidationReport) -> None:
    _print_problems("legacy", report.legacy_errors)
    _print_problems("strict", report.strict_errors, skipped=not report.ok)


def _print_format(raw: bytes) -> SaveFormat | None:
    try:
        fmt = default_registry().detect(raw)
    except UnknownSaveFormatError as exc:
        print(f"format: unknown ({exc})")
        return None
    except DDManagerError as exc:
        print(f"format: {exc}")
        return None
    print(f"format: {fmt.format_id} ({'writable' if fmt.writable else 'read-only'})")
    return fmt


def _validate(fmt: SaveFormat | None, raw: bytes) -> SaveValidationReport:
    """Ask the detected format; an unrecognised file still gets the codec's diagnostics."""
    return fmt.validate(raw) if fmt is not None else dson_codec.validate(raw)


def _print_header(raw: bytes) -> None:
    if len(raw) < dson_codec.HEADER_SIZE:
        print("header: file is shorter than 64 bytes")
        return
    header = dson_codec.read_header(raw)
    print(f"magic: {header.magic.hex()}  revision: {header.revision.hex()}")
    print(
        f"header_length={header.header_length} meta1_count={header.meta1_count}"
        f" meta1_offset={header.meta1_offset} meta1_size={header.meta1_size}"
        f" meta2_count={header.meta2_count} meta2_offset={header.meta2_offset}"
        f" data_length={header.data_length} data_offset={header.data_offset}"
    )


def _applied_block_status(fmt: DsonV1Format, raw: bytes) -> str | None:
    """A line describing an ABSENT applied block (what a write would do), or None when present."""
    doc = dson_codec.parse(raw)
    if doc.find_child(0, fmt.applied_block) is not None:
        return None
    anchor = doc.find_child(0, fmt.anchor_block)
    if anchor is None or not doc.meta2[anchor].is_object:
        return (
            f"{fmt.applied_block}: absent, and no {fmt.anchor_block} object under the root:"
            " a write would be refused (no_anchor)"
        )
    return f"{fmt.applied_block}: absent (a write would insert it before {fmt.anchor_block})"


def _print_applied(fmt: SaveFormat, raw: bytes) -> None:
    try:
        if isinstance(fmt, DsonV1Format):
            status = _applied_block_status(fmt, raw)
            if status is not None:
                print(status)
                return
        entries = fmt.read_applied(raw)
    except DDManagerError as exc:
        print(f"applied_ugcs_1_0: unreadable ({exc})")
        return
    print(f"applied_ugcs_1_0: {len(entries)} entries")
    for rank, entry in enumerate(entries, start=1):
        print(f"  {rank}. {entry.name} | {entry.source}")


def save_inspect(path: Path) -> int:
    raw = _read_file(path)
    if raw is None:
        return 2
    print(f"file: {path}")
    print(f"size: {len(raw)} bytes")
    fmt = _print_format(raw)
    _print_header(raw)
    report = _validate(fmt, raw)
    if fmt is not None and report.ok:
        _print_applied(fmt, raw)
    _print_report(report)
    return 0 if fmt is not None and report.ok else 1


def save_verify(path: Path) -> int:
    raw = _read_file(path)
    if raw is None:
        return 2
    fmt = _print_format(raw)
    report = _validate(fmt, raw)
    _print_report(report)
    return 0 if fmt is not None and report.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.command is None:
        from src.app import main as gui_main  # noqa: PLC0415  (Qt is imported lazily)

        gui_args = ["--data-dir", args.data_dir] if args.data_dir else []
        return gui_main(gui_args)
    if args.command == "save" and args.save_command == "inspect":
        return save_inspect(args.file)
    if args.command == "save" and args.save_command == "verify":
        return save_verify(args.file)
    return 0
