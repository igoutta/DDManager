"""The ``QT_QPA_PLATFORM`` value of the UI tests (no Qt import: it runs before PySide6 loads)."""

from pathlib import Path


def platform_argument() -> str:
    """``offscreen`` with a desktop-sized virtual screen so restored window geometry fits.

    Qt splits the platform argument on ``:``, so the config path must not carry a drive letter;
    a path relative to the working directory works because the suite runs from the repo root.
    """
    config = Path(__file__).with_name("offscreen.json")
    try:
        relative = config.relative_to(Path.cwd())
    except ValueError:
        return "offscreen"
    return f"offscreen:configfile={relative.as_posix()}"
