"""Steam Workshop mods: subfolders of ``steamapps/workshop/content/262060`` roots."""

from collections.abc import Iterable
from dataclasses import dataclass

from src.core.ids import SourceKind
from src.core.model import ModInfo, ModSnapshot
from src.services.detection import InstallSnapshot
from src.services.mod_reader import snapshot_mod_folder
from src.services.sources import ModLocation, ReadContext, child_locations
from src.services.steam_locations import is_workshop_content_path, workshop_id_for_folder

PAGE_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={}"


@dataclass(frozen=True, slots=True)
class SteamWorkshopSource:
    source_id: str = "steam"
    display_name: str = "Steam Workshop"
    claim_priority: int = 50

    def discover(self, install: InstallSnapshot) -> Iterable[ModLocation]:
        for root in install.mod_roots:
            if is_workshop_content_path(root):
                yield from child_locations(self.source_id, root)

    def snapshot(self, location: ModLocation, ctx: ReadContext) -> ModSnapshot:
        return snapshot_mod_folder(
            location.path,
            root=location.root,
            source_id=self.source_id,
            kind=SourceKind.WORKSHOP,
            under_workshop=True,
            workshop_id=workshop_id_for_folder(location.path, under_workshop=True),
            ctx=ctx,
        )

    def page_url(self, info: ModInfo) -> str | None:
        return PAGE_URL.format(info.workshop_id) if info.workshop_id else None
