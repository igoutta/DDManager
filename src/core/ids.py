"""Identifiers shared across the domain: mod keys, source kinds and save identities."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, NewType

ModId = NewType("ModId", str)
"""The EXACT mod folder basename, which is also the ``mod_state.json`` key."""


def parse_mod_id(raw: str) -> ModId:
    """Validate a folder basename as a mod id (no empty, dot or path-separator keys)."""
    if not raw or raw in {".", ".."} or "/" in raw or "\\" in raw:
        raise ValueError(f"invalid mod id {raw!r}")
    return ModId(raw)


class SourceKind(StrEnum):
    """Where a mod lives on disk; NOT what is written into the save."""

    WORKSHOP = "workshop"
    LOCAL = "local"


class SaveSource:
    """``source`` values seen in ``applied_ugcs_1_0`` / ``dlc`` entries (an open set on purpose)."""

    STEAM: Final = "Steam"
    LOCAL: Final = "mod_local_source"
    DLC: Final = "dlc"


@dataclass(frozen=True, slots=True, order=True)
class SaveIdentity:
    """One ``{name, source}`` pair as the game stores it in ``applied_ugcs_1_0``."""

    name: str
    source: str

    def __post_init__(self) -> None:
        for value in (self.name, self.source):
            if "\x00" in value:
                raise ValueError("save identity must not contain NUL bytes")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                # e.g. a surrogateescape-decoded folder name: it can never be written into a save
                raise ValueError("save identity must be UTF-8 encodable") from exc

    @property
    def is_workshop(self) -> bool:
        return self.source == SaveSource.STEAM

    def as_tuple(self) -> tuple[str, str]:
        return (self.name, self.source)
