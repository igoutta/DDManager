"""The host environment as an injectable value: platform, home, env vars and the registry.

``Environment.from_host`` is the ONLY place that touches ``sys.platform``, ``os.environ``,
``winreg`` and ``ctypes``; every other service receives an ``Environment`` so detection can be
tested with fakes on any platform.
"""

import ctypes
import importlib
import os
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from typing import Literal, Protocol

type PlatformName = Literal["windows", "linux", "darwin"]

_FOLDERID_DOCUMENTS = "FDD39AD0-238F-46AF-ADB4-6C85480369C7"


class Hive(StrEnum):
    HKCU = "HKCU"
    HKLM = "HKLM"


class RegistryReader(Protocol):
    def read_value(self, hive: Hive, key: str, name: str) -> str | None: ...

    def subkeys(self, hive: Hive, key: str) -> list[str]: ...


class NullRegistry:
    """The registry of a host without one."""

    __slots__ = ()

    def read_value(self, hive: Hive, key: str, name: str) -> str | None:
        return None

    def subkeys(self, hive: Hive, key: str) -> list[str]:
        return []


def _norm_key(key: str) -> str:
    return key.replace("/", "\\").strip("\\").casefold()


class DictRegistry:
    """A registry backed by dicts (tests); key and value names are case-insensitive."""

    __slots__ = ("_subkeys", "_values")

    def __init__(
        self,
        values: Mapping[tuple[Hive, str, str], str] | None = None,
        subkeys: Mapping[tuple[Hive, str], list[str]] | None = None,
    ) -> None:
        self._values = {
            (hive, _norm_key(key), name.casefold()): value
            for (hive, key, name), value in (values or {}).items()
        }
        self._subkeys = {
            (hive, _norm_key(key)): list(children)
            for (hive, key), children in (subkeys or {}).items()
        }

    def read_value(self, hive: Hive, key: str, name: str) -> str | None:
        return self._values.get((hive, _norm_key(key), name.casefold()))

    def subkeys(self, hive: Hive, key: str) -> list[str]:
        return list(self._subkeys.get((hive, _norm_key(key)), []))


def _load_winreg() -> ModuleType | None:
    try:
        return importlib.import_module("winreg")
    except ImportError:
        return None


class WinRegRegistry:
    """``winreg``-backed registry; every ``OSError`` becomes ``None`` / ``[]``."""

    __slots__ = ("_winreg",)

    def __init__(self) -> None:
        self._winreg = _load_winreg()

    def _hive(self, hive: Hive) -> int | None:
        if self._winreg is None:
            return None
        return (
            self._winreg.HKEY_CURRENT_USER if hive is Hive.HKCU else self._winreg.HKEY_LOCAL_MACHINE
        )

    def read_value(self, hive: Hive, key: str, name: str) -> str | None:
        root = self._hive(hive)
        if root is None or self._winreg is None:
            return None
        try:
            with self._winreg.OpenKey(root, key) as handle:
                value, _kind = self._winreg.QueryValueEx(handle, name)
        except OSError:
            return None
        return value if isinstance(value, str) and value else None

    def subkeys(self, hive: Hive, key: str) -> list[str]:
        root = self._hive(hive)
        if root is None or self._winreg is None:
            return []
        names: list[str] = []
        try:
            with self._winreg.OpenKey(root, key) as handle:
                while True:
                    names.append(self._winreg.EnumKey(handle, len(names)))
        except OSError:
            return names  # EnumKey raises OSError at the end of the list (or on failure)


@dataclass(frozen=True, slots=True)
class Environment:
    platform: PlatformName
    home: Path
    env: Mapping[str, str]
    registry: RegistryReader
    known_documents_dir: Path | None = None

    @property
    def is_windows(self) -> bool:
        return self.platform == "windows"

    @property
    def is_linux(self) -> bool:
        return self.platform == "linux"

    @property
    def is_macos(self) -> bool:
        return self.platform == "darwin"

    def env_path(self, name: str) -> Path | None:
        """The variable as a path (names compare case-insensitively); ``None`` if unset/empty."""
        wanted = name.casefold()
        for key, value in self.env.items():
            if key.casefold() == wanted and value.strip():
                return Path(value.strip())
        return None

    @classmethod
    def from_host(cls) -> Environment:
        platform = _host_platform()
        return cls(
            platform=platform,
            home=Path.home(),
            env=dict(os.environ),
            registry=WinRegRegistry() if platform == "windows" else NullRegistry(),
            known_documents_dir=_windows_documents_dir() if platform == "windows" else None,
        )


def _host_platform() -> PlatformName:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _windows_documents_dir() -> Path | None:
    """The (possibly redirected) Documents folder via ``SHGetKnownFolderPath``."""
    if sys.platform != "win32":
        return None
    try:
        guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(_FOLDERID_DOCUMENTS).bytes_le)
        pointer = ctypes.c_wchar_p()
        status = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(pointer)
        )
        value = pointer.value
        ctypes.windll.ole32.CoTaskMemFree(pointer)
    except OSError, AttributeError, ValueError:
        return None
    return Path(value) if status == 0 and value else None
