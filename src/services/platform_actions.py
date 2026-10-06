"""Launching things on the host: file manager, browser, the game; plus UI language detection.

Ports ``dd2.py:5893-5966`` (open folder, launch game) and ``localization.py:522-553``
(``detect_default_language``).  Every side effect is injectable so tests never start anything.
"""

import ctypes
import locale
import os
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from src.services.detection import STEAM_APP_ID, InstallSnapshot
from src.services.environment import Environment
from src.services.errors import LaunchError

STEAM_URI: Final = f"steam://rungameid/{STEAM_APP_ID}"
GAME_EXECUTABLES: Final = ("Darkest.exe", "DarkestDungeon.exe")

type Runner = Callable[..., object]
type StartFile = Callable[[str], object]


def _default_startfile(target: str) -> None:
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        raise LaunchError("os.startfile is not available on this platform.")
    startfile(target)


def _run_first(commands: list[list[str]], run: Runner) -> list[str]:
    """Start the first command whose program exists; ``LaunchError`` when none does."""
    for command in commands:
        try:
            run(command)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LaunchError(f"Could not run {command[0]}: {exc}") from exc
        return command
    raise LaunchError("No supported launcher was found on this platform.")


def open_folder(
    path: Path,
    env: Environment,
    *,
    run: Runner = subprocess.Popen,
    startfile: StartFile = _default_startfile,
) -> None:
    """``dd2.py:5893-5918``: show ``path`` in the platform's file manager."""
    if not path.is_dir():
        raise LaunchError(f"That folder is not set or no longer exists: {path}")
    target = str(path)
    if env.is_windows:
        try:
            startfile(target)
        except OSError as exc:
            raise LaunchError(f"Could not open {target}: {exc}") from exc
        return
    program = "open" if env.is_macos else "xdg-open"
    _run_first([[program, target]], run)


def open_url(url: str, *, opener: Callable[[str], bool] = webbrowser.open) -> None:
    """Open an http(s) link in the default browser."""
    if urlparse(url).scheme not in {"http", "https"}:
        raise LaunchError(f"Refusing to open a non-web link: {url}")
    if not opener(url):
        raise LaunchError(f"No browser could open {url}")


def _game_executable(install: InstallSnapshot) -> Path | None:
    for root in install.game_roots:
        for name in GAME_EXECUTABLES:
            candidate = root / name
            if candidate.is_file():
                return candidate
    return None


def _launch_windows(install: InstallSnapshot, startfile: StartFile) -> str:
    try:
        startfile(STEAM_URI)
    except OSError:
        executable = _game_executable(install)
        if executable is None:
            raise LaunchError(
                "No Steam launcher or local Darkest Dungeon executable was found."
            ) from None
        startfile(str(executable))
        return str(executable)
    return STEAM_URI


def launch_game(
    install: InstallSnapshot,
    env: Environment,
    *,
    run: Runner = subprocess.Popen,
    startfile: StartFile = _default_startfile,
) -> str:
    """``dd2.py:5926-5966``: start the game through Steam; returns what was launched."""
    if env.is_windows:
        return _launch_windows(install, startfile)
    if env.is_macos:
        _run_first([["open", STEAM_URI]], run)
    else:
        _run_first([["xdg-open", STEAM_URI], ["steam", STEAM_URI]], run)
    return STEAM_URI


# --------------------------------------------------------------- language detection


def map_locale_to_language(locale_name: str | None) -> str:
    """``localization.py:473-481``: a locale name to one of ``zh_CN``/``pt_PT``/``es_ES``/``en``."""
    normalized = (locale_name or "").strip().lower().replace("-", "_")
    for prefix, language in (("zh", "zh_CN"), ("pt", "pt_PT"), ("es", "es_ES")):
        if normalized.startswith(prefix):
            return language
    return "en"


def _windows_ui_language_id() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        return int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    except OSError, AttributeError, ValueError:
        return None


def _windows_language(ui_language_id: Callable[[], int | None]) -> str | None:
    language_id = ui_language_id()
    name = locale.windows_locale.get(language_id, "") if language_id is not None else ""
    return map_locale_to_language(name) if name else None


def detect_default_language(
    env: Environment, *, ui_language_id: Callable[[], int | None] = _windows_ui_language_id
) -> str:
    """``localization.py:522-553`` with the POSIX precedence fixed: LC_ALL, LC_MESSAGES, LANG."""
    if env.is_windows:
        detected = _windows_language(ui_language_id)
        if detected is not None:
            return detected
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.env.get(name, "").strip()
        if value:
            return map_locale_to_language(value)
    return map_locale_to_language(locale.getlocale()[0])
