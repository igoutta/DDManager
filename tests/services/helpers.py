"""Plain helpers shared by the services tests (fixtures live in ``conftest.py``)."""

import json
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.errors import DsonFormatError
from src.core.ids import SaveIdentity
from src.core.saves.format import DsonScalar, SaveValidationReport

TZ = timezone(timedelta(hours=2))
NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=TZ)
FAKE_MAGIC = b"FAKE"


def fake_save_bytes(
    applied: Sequence[tuple[str, str]] = (), scalars: Mapping[str, DsonScalar] | None = None
) -> bytes:
    body = {"applied": [list(pair) for pair in applied], "scalars": dict(scalars or {})}
    return FAKE_MAGIC + json.dumps(body).encode("utf-8")


class FakeFormat:
    """A tiny in-memory SaveFormat: ``FAKE`` + JSON ``{"applied": [...], "scalars": {...}}``.

    ``corrupt_on_write`` makes ``write_applied`` emit bytes that its own ``check`` rejects, to
    exercise the post-write gates of the services.
    """

    format_id = "fake"
    writable = True

    def __init__(self, *, corrupt_on_write: bool = False) -> None:
        self.corrupt_on_write = corrupt_on_write
        self.check_calls = 0
        self.scalar_calls = 0

    def sniff(self, raw: bytes) -> bool:
        return raw.startswith(FAKE_MAGIC)

    def _body(self, raw: bytes) -> dict[str, object]:
        try:
            body = json.loads(raw[len(FAKE_MAGIC) :].decode("utf-8"))
        except ValueError as exc:
            raise DsonFormatError("fake save is unreadable", code="input_invalid") from exc
        if not isinstance(body, dict):
            raise DsonFormatError("fake save is not an object", code="not_an_object")
        return body

    def validate(self, raw: bytes) -> SaveValidationReport:
        return SaveValidationReport()

    def check(self, raw: bytes) -> None:
        self.check_calls += 1
        if b"CORRUPT" in raw:
            raise DsonFormatError("fake save is corrupt", code="hash_mismatch")
        self._body(raw)

    def read_applied(self, raw: bytes) -> tuple[SaveIdentity, ...]:
        applied = self._body(raw)["applied"]
        assert isinstance(applied, list)
        return tuple(SaveIdentity(name, source) for name, source in applied)

    def write_applied(self, raw: bytes, entries: Sequence[SaveIdentity]) -> bytes:
        body = self._body(raw)
        body["applied"] = [[e.name, e.source] for e in entries]
        out = FAKE_MAGIC + json.dumps(body).encode("utf-8")
        return out + b"CORRUPT" if self.corrupt_on_write else out

    def read_scalars(self, raw: bytes, names: Collection[str]) -> dict[str, DsonScalar]:
        self.scalar_calls += 1
        scalars = self._body(raw)["scalars"]
        assert isinstance(scalars, dict)
        return {name: value for name, value in scalars.items() if name in names}


@dataclass
class FakeProbe:
    """A ProcessProbe returning ``state`` and remembering what it was asked."""

    state: object
    calls: list[frozenset[str]] = field(default_factory=list)

    def find(self, image_names: Collection[str]) -> object:
        self.calls.append(frozenset(name.casefold() for name in image_names))
        return self.state


@dataclass(frozen=True)
class SteamTree:
    """What ``make_steam_root`` built."""

    root: Path
    libraries: tuple[Path, ...]
    """Extra libraries (not the root itself)."""
    workshop_dir: Path
    """``<root>/steamapps/workshop/content/262060``."""
    acf_file: Path
    game_dir: Path
    saves: tuple[Path, ...]
    """Every ``persist.game.json`` created under userdata."""
    decoys: tuple[Path, ...]
    """Files next to the saves that must NOT be discovered (backups, decoded copies)."""


def vdf_text(libraries: Sequence[Path]) -> str:
    rows = [
        f'\t"{index}"\n\t{{\n\t\t"path"\t\t"{str(lib).replace(chr(92), chr(92) * 2)}"\n\t}}\n'
        for index, lib in enumerate(libraries, start=1)
    ]
    return '"libraryfolders"\n{\n' + "".join(rows) + "}\n"


def acf_text(times: Mapping[str, str]) -> str:
    items = "".join(
        f'\t\t"{wid}"\n\t\t{{\n\t\t\t"size"\t\t"1"\n\t\t\t"timeupdated"\t\t"{stamp}"\n\t\t}}\n'
        for wid, stamp in times.items()
    )
    head = '"AppWorkshop"\n{\n\t"appid"\t\t"262060"\n\t"WorkshopItemDetails"\n\t{\n'
    return f"{head}{items}\t}}\n}}\n"


def set_mtime(path: Path, when: datetime) -> None:
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))


def tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` (posix relative path -> bytes): a before/after probe."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def make_install(mod_roots: Sequence[Path], *, primary: Path | None = None, saves=()):
    """An ``InstallSnapshot`` holding just ``mod_roots`` (everything else empty)."""
    from src.services.detection import InstallSnapshot

    roots = tuple(mod_roots)
    return InstallSnapshot(
        steam_roots=(),
        libraries=(),
        game_roots=(),
        local_mod_dirs=(),
        workshop_dirs=(),
        primary_mods_dir=primary if primary is not None else (roots[0] if roots else None),
        mod_roots=roots,
        acf_files=(),
        save_files=tuple(saves),
        findings=(),
    )
