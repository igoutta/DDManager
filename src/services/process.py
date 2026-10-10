"""Is the game (or another DD Manager) running?  Probes never raise; failure is ``UNKNOWN``."""

import ctypes
import logging
import sys
from collections.abc import Collection, Iterator
from ctypes import wintypes
from pathlib import Path
from typing import Final

from src.services.environment import Environment
from src.services.ports import ProcessProbe, RunState

log = logging.getLogger(__name__)

MANAGER_IMAGES: Final = frozenset({"dd manager.exe"})
"""The image name of the DD Manager executable itself (every packaged version)."""
_TH32CS_SNAPPROCESS: Final = 0x00000002
_MAX_PATH: Final = 260


class _ProcessEntry(ctypes.Structure):
    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * _MAX_PATH),
    )


def _wanted(image_names: Collection[str]) -> frozenset[str]:
    return frozenset(name.casefold() for name in image_names)


def _toolhelp_names() -> Iterator[str]:
    """Image names of every running process (``CreateToolhelp32Snapshot``); raises ``OSError``."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        more = kernel32.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            yield entry.szExeFile
            more = kernel32.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(handle)


class WindowsToolhelpProbe:
    """Process lookup through the Toolhelp snapshot API."""

    def find(self, image_names: Collection[str]) -> RunState:
        wanted = _wanted(image_names)
        try:
            running = any(name.casefold() in wanted for name in _toolhelp_names())
        except (OSError, AttributeError, ValueError) as exc:
            log.debug("toolhelp probe failed: %s", exc)
            return RunState.UNKNOWN
        return RunState.RUNNING if running else RunState.NOT_RUNNING


def _read_proc_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""  # the process exited between listing and reading


def _proc_images(proc_dir: Path) -> set[str]:
    """``comm`` plus the base names of the first ``cmdline`` arguments (Proton shows the exe)."""
    images = {_read_proc_text(proc_dir / "comm").strip().casefold()}
    for argument in _read_proc_text(proc_dir / "cmdline").split("\x00")[:3]:
        images.add(argument.replace("\\", "/").rsplit("/", 1)[-1].casefold())
    images.discard("")
    return images


class LinuxProcProbe:
    """Process lookup by reading ``/proc``."""

    def __init__(self, proc_root: Path = Path("/proc")) -> None:
        self._root = proc_root

    def find(self, image_names: Collection[str]) -> RunState:
        wanted = _wanted(image_names)
        try:
            entries = [entry for entry in self._root.iterdir() if entry.name.isdigit()]
        except OSError as exc:
            log.debug("cannot list %s: %s", self._root, exc)
            return RunState.UNKNOWN
        if any(_proc_images(entry) & wanted for entry in entries):
            return RunState.RUNNING
        return RunState.NOT_RUNNING


class NullProbe:
    """For hosts where process lookup is not supported."""

    def find(self, image_names: Collection[str]) -> RunState:
        return RunState.UNKNOWN


def default_probe(env: Environment) -> ProcessProbe:
    """The probe that fits ``env``'s platform."""
    if env.is_windows and sys.platform == "win32":
        return WindowsToolhelpProbe()
    if env.is_linux:
        return LinuxProcProbe()
    return NullProbe()
