"""Built-in mod sources (static imports so PyInstaller bundles them)."""

from src.plugins.local_folder import LocalFolderSource
from src.plugins.steam_workshop import SteamWorkshopSource
from src.services.sources import ModSource

BUILTIN_SOURCES: tuple[ModSource, ...] = (SteamWorkshopSource(), LocalFolderSource())

__all__ = ["BUILTIN_SOURCES", "LocalFolderSource", "SteamWorkshopSource"]
