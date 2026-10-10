"""Persisting the window layout (geometry, dock state, splitter) in ``ui.ini``."""

from pathlib import Path
from typing import Final

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMainWindow, QSplitter

GEOMETRY_KEY: Final = "window/geometry"
STATE_KEY: Final = "window/state"
SPLITTER_KEY: Final = "window/splitter"
# Default pane widths (px) when no ui.ini has been saved yet: Available, Load Order, Details.
DEFAULT_SIZES: Final = (380, 660, 320)


def save_ui_state(window: QMainWindow, splitter: QSplitter, ini: Path) -> None:
    settings = QSettings(str(ini), QSettings.Format.IniFormat)
    settings.setValue(GEOMETRY_KEY, window.saveGeometry())
    settings.setValue(STATE_KEY, window.saveState())
    settings.setValue(SPLITTER_KEY, splitter.saveState())
    settings.sync()


def restore_ui_state(window: QMainWindow, splitter: QSplitter, ini: Path) -> bool:
    """Restore what ``ini`` holds; True when it had a splitter layout (no default is needed)."""
    settings = QSettings(str(ini), QSettings.Format.IniFormat)
    restored = False
    for key, restore in (
        (GEOMETRY_KEY, window.restoreGeometry),
        (STATE_KEY, window.restoreState),
        (SPLITTER_KEY, splitter.restoreState),
    ):
        value = settings.value(key)
        if value is not None:
            restore(value)
            restored = restored or key == SPLITTER_KEY
    return restored


def apply_default_split(splitter: QSplitter) -> None:
    """Share the splitter's real width in the default proportions (first show only).

    Done before the window has a size, the panes' minimum widths would swallow the proportions,
    so the window calls this on its first show, when the splitter is as wide as it will be.
    """
    total = max(splitter.width(), sum(DEFAULT_SIZES))
    scale = total / sum(DEFAULT_SIZES)
    splitter.setSizes([round(size * scale) for size in DEFAULT_SIZES])
