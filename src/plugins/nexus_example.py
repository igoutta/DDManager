"""Example third-party source: local folders carrying a ``nexus.json`` sidecar.

This module documents the plugin contract and is NOT part of ``BUILTIN_SOURCES``.  A user plugin
exports ``register(registry)`` and adds sources, rules or save formats to it; a source claims
folders at ``claim_priority`` (lower first) and reads them with ``snapshot_mod_folder``.
Identity stays that of a local mod, only the page link differs.
"""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.core.ids import SourceKind
from src.core.model import ModInfo, ModSnapshot
from src.services.detection import InstallSnapshot
from src.services.mod_reader import snapshot_mod_folder
from src.services.plugin_registry import PluginRegistry
from src.services.sources import ModLocation, ReadContext, child_locations
from src.services.steam_locations import is_workshop_content_path

log = logging.getLogger(__name__)

SIDECAR = "nexus.json"
GAME_DOMAIN = "darkestdungeon"


def read_nexus_mod_id(folder: Path) -> int | None:
    """``mod_id`` from ``<folder>/nexus.json``; ``None`` when absent or malformed."""
    try:
        data = json.loads((folder / SIDECAR).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.debug("unreadable %s in %s: %s", SIDECAR, folder, exc)
        return None
    mod_id = data.get("mod_id") if isinstance(data, dict) else None
    return mod_id if isinstance(mod_id, int) and not isinstance(mod_id, bool) else None


@dataclass(frozen=True, slots=True)
class NexusSource:
    source_id: str = "nexus"
    display_name: str = "Nexus Mods (sidecar)"
    claim_priority: int = 10

    def discover(self, install: InstallSnapshot) -> Iterable[ModLocation]:
        for root in install.mod_roots:
            if is_workshop_content_path(root):
                continue
            for location in child_locations(self.source_id, root):
                mod_id = read_nexus_mod_id(location.path)
                if mod_id is not None:
                    yield ModLocation(
                        location.source_id,
                        location.key,
                        location.path,
                        location.root,
                        (("mod_id", str(mod_id)),),
                    )

    def snapshot(self, location: ModLocation, ctx: ReadContext) -> ModSnapshot:
        return snapshot_mod_folder(
            location.path,
            root=location.root,
            source_id=self.source_id,
            kind=SourceKind.LOCAL,
            under_workshop=False,
            workshop_id="",
            ctx=ctx,
        )

    def page_url(self, info: ModInfo) -> str | None:
        mod_id = read_nexus_mod_id(Path(info.path))
        if mod_id is None:
            return None
        return f"https://www.nexusmods.com/{GAME_DOMAIN}/mods/{mod_id}"


def register(registry: PluginRegistry) -> None:
    """Plugin entry point."""
    registry.add_mod_source(NexusSource())
