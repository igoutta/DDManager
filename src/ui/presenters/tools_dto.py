"""Plain data the tools dialogs render (apply order, save code, diagnostics): frozen view models."""

from dataclasses import dataclass
from pathlib import Path

from src.core.ids import ModId


@dataclass(frozen=True, slots=True)
class RenameRowVM:
    """One folder of the apply-order preview: ``old_name`` becomes ``new_name``."""

    mod_id: ModId
    title: str
    old_name: str
    new_name: str


@dataclass(frozen=True, slots=True)
class RenamePreviewVM:
    """What "Apply order to local mod folders" is about to do, shown before anything moves."""

    rows: tuple[RenameRowVM, ...]
    root: Path | None = None
    skipped_workshop: int = 0
    warnings: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class SaveCodeVM:
    """The ``applied_ugcs_1_0`` block of the enabled mods, as text to paste into a decoded save."""

    text: str
    count: int


@dataclass(frozen=True, slots=True)
class DiagnosticsVM:
    """The setup report: ``text`` is ``lines`` joined by newlines (English by design)."""

    text: str
    lines: tuple[str, ...]
