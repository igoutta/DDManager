"""The mod-source plugin contract: where mods are discovered and how they are read."""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import tzinfo
from pathlib import Path
from typing import Protocol

from src.core.ids import ModId
from src.core.model import ModInfo, ModSnapshot
from src.services.detection import InstallSnapshot

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModLocation:
    """One discovered mod folder, claimed by one source."""

    source_id: str
    key: ModId
    path: Path
    root: Path
    extra: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ReadContext:
    """What a source needs besides the folder: ACF update times, the zone, and read depth.

    ``deep=False`` skips parsing ``localization/*.xml`` entries (the signature is still taken).
    """

    acf_times: Mapping[str, str]
    tz: tzinfo
    deep: bool = True


class ModSource(Protocol):
    """A way of finding and reading mods; ``claim_priority`` lower claims a folder first."""

    @property
    def source_id(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def claim_priority(self) -> int: ...

    def discover(self, install: InstallSnapshot) -> Iterable[ModLocation]: ...

    def snapshot(self, location: ModLocation, ctx: ReadContext) -> ModSnapshot: ...

    def page_url(self, info: ModInfo) -> str | None: ...


def child_locations(
    source_id: str, root: Path, *, extra: tuple[tuple[str, str], ...] = ()
) -> list[ModLocation]:
    """Every direct subdirectory of ``root`` as a location (name order; unreadable root -> none)."""
    try:
        children = sorted(entry for entry in root.iterdir() if entry.is_dir())
    except OSError as exc:
        log.debug("cannot list mod root %s: %s", root, exc)
        return []
    return [ModLocation(source_id, ModId(child.name), child, root, extra) for child in children]
