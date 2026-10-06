"""Local mods: every subfolder of every non-workshop mod root (legacy parity: nothing skipped)."""

from collections.abc import Iterable
from dataclasses import dataclass

from src.core.ids import SourceKind
from src.core.model import ModInfo, ModSnapshot
from src.services.detection import InstallSnapshot
from src.services.mod_reader import snapshot_mod_folder
from src.services.sources import ModLocation, ReadContext, child_locations
from src.services.steam_locations import is_workshop_content_path


@dataclass(frozen=True, slots=True)
class LocalFolderSource:
    source_id: str = "local"
    display_name: str = "Local mods"
    claim_priority: int = 100

    def discover(self, install: InstallSnapshot) -> Iterable[ModLocation]:
        for root in install.mod_roots:
            if not is_workshop_content_path(root):
                yield from child_locations(self.source_id, root)

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
        return None
