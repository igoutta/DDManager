"""Process probes: they never raise and answer a three-state RunState."""

import sys
from pathlib import Path

import pytest

from src.services.ports import RunState
from src.services.process import (
    MANAGER_IMAGES,
    LinuxProcProbe,
    NullProbe,
    WindowsToolhelpProbe,
    default_probe,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Toolhelp is a Windows API")
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs /proc")
IMAGE = Path(sys.executable).name


def test_run_state_values() -> None:
    assert {s.value for s in RunState} == {"running", "not_running", "unknown"}


def test_null_probe_never_knows() -> None:
    assert NullProbe().find({"darkest.exe"}) is RunState.UNKNOWN
    assert NullProbe().find(set()) is RunState.UNKNOWN


def test_manager_images() -> None:
    assert {"dd manager.exe"} == MANAGER_IMAGES


@windows_only
def test_windows_probe_finds_this_python_case_insensitively() -> None:
    probe = WindowsToolhelpProbe()
    assert probe.find({IMAGE}) is RunState.RUNNING
    assert probe.find({IMAGE.upper(), "no-such-image.exe"}) is RunState.RUNNING


@windows_only
def test_windows_probe_reports_absent_images() -> None:
    assert WindowsToolhelpProbe().find({"definitely-not-running-ddm.exe"}) is RunState.NOT_RUNNING
    assert WindowsToolhelpProbe().find(set()) is RunState.NOT_RUNNING


@linux_only
def test_linux_probe_finds_this_python() -> None:
    probe = LinuxProcProbe()
    assert probe.find({IMAGE}) is RunState.RUNNING
    assert probe.find({"definitely-not-running-ddm"}) is RunState.NOT_RUNNING


def test_default_probe_per_platform(fake_env) -> None:
    assert isinstance(default_probe(fake_env("windows")), WindowsToolhelpProbe)
    assert isinstance(default_probe(fake_env("linux")), LinuxProcProbe)
    assert isinstance(default_probe(fake_env("darwin")), NullProbe)
