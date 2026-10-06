"""platform_actions with injected runners: nothing real is ever launched."""

import dataclasses
import os
from pathlib import Path

import pytest

from src.services.errors import LaunchError
from src.services.platform_actions import (
    detect_default_language,
    launch_game,
    open_folder,
    open_url,
)
from tests.services.helpers import make_install

STEAM_URL = "steam://rungameid/262060"


class Runner:
    """A ``subprocess.Popen`` stand-in recording the argv of each call."""

    def __init__(self, fail_on: tuple[str, ...] = ()) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, args, *_a: object, **_k: object) -> object:
        argv = [str(a) for a in args]
        self.calls.append(argv)
        if argv[0] in self.fail_on:
            raise FileNotFoundError(argv[0])
        return object()


@pytest.fixture
def startfile(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    started: list[str] = []
    monkeypatch.setattr(
        os, "startfile", lambda target, *a, **k: started.append(str(target)), raising=False
    )
    return started


# ------------------------------------------------------------------ open_folder


def test_open_folder_per_platform(fake_env, tmp_path: Path, startfile: list[str]) -> None:
    runner = Runner()
    open_folder(tmp_path, fake_env("windows"), run=runner)
    assert startfile == [str(tmp_path)]
    assert runner.calls == []
    open_folder(tmp_path, fake_env("linux"), run=runner)
    open_folder(tmp_path, fake_env("darwin"), run=runner)
    assert runner.calls == [["xdg-open", str(tmp_path)], ["open", str(tmp_path)]]


def test_open_folder_needs_an_existing_folder(fake_env, tmp_path: Path) -> None:
    runner = Runner()
    with pytest.raises(LaunchError):
        open_folder(tmp_path / "gone", fake_env("linux"), run=runner)
    assert runner.calls == []


def test_open_folder_failures_are_typed(fake_env, tmp_path: Path) -> None:
    with pytest.raises(LaunchError):
        open_folder(tmp_path, fake_env("linux"), run=Runner(fail_on=("xdg-open",)))


# ------------------------------------------------------------------ open_url


def test_open_url_uses_the_injected_opener() -> None:
    seen: list[str] = []
    open_url("https://example.org/x", opener=lambda url: seen.append(url) or True)
    assert seen == ["https://example.org/x"]


def test_open_url_reports_a_refusing_browser() -> None:
    with pytest.raises(LaunchError):
        open_url("https://example.org/x", opener=lambda url: False)


# ------------------------------------------------------------------ launch_game


def test_windows_launches_through_the_steam_protocol(fake_env, startfile: list[str]) -> None:
    runner = Runner()
    launched = launch_game(make_install([]), fake_env("windows"), run=runner)
    assert launched == STEAM_URL
    assert startfile == [STEAM_URL]
    assert runner.calls == []


def test_windows_falls_back_to_the_game_executable(
    fake_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[str] = []

    def startfile(target: str, *_a: object, **_k: object) -> None:
        if str(target).startswith("steam://"):
            raise OSError("no steam handler")
        started.append(str(target))

    monkeypatch.setattr(os, "startfile", startfile, raising=False)
    root = tmp_path / "DarkestDungeon"
    root.mkdir()
    install = dataclasses.replace(make_install([]), game_roots=(root,))
    runner = Runner()

    def launched_programs() -> list[str]:
        return [*started, *(call[0] for call in runner.calls)]

    with pytest.raises(LaunchError):
        launch_game(install, fake_env("windows"), run=runner)
    assert launched_programs() == []
    (root / "DarkestDungeon.exe").write_bytes(b"MZ")
    assert launch_game(install, fake_env("windows"), run=runner) == str(root / "DarkestDungeon.exe")
    (root / "Darkest.exe").write_bytes(b"MZ")
    assert launch_game(install, fake_env("windows"), run=runner) == str(root / "Darkest.exe")
    assert launched_programs() == [str(root / "DarkestDungeon.exe"), str(root / "Darkest.exe")]


def test_linux_uses_xdg_open_then_the_steam_binary(fake_env) -> None:
    runner = Runner()
    assert launch_game(make_install([]), fake_env("linux"), run=runner) == STEAM_URL
    assert runner.calls == [["xdg-open", STEAM_URL]]
    fallback = Runner(fail_on=("xdg-open",))
    assert launch_game(make_install([]), fake_env("linux"), run=fallback) == STEAM_URL
    assert fallback.calls == [["xdg-open", STEAM_URL], ["steam", STEAM_URL]]


def test_linux_without_any_launcher_is_a_launch_error(fake_env) -> None:
    with pytest.raises(LaunchError):
        launch_game(make_install([]), fake_env("linux"), run=Runner(fail_on=("xdg-open", "steam")))


def test_darwin_uses_open(fake_env) -> None:
    runner = Runner()
    assert launch_game(make_install([]), fake_env("darwin"), run=runner) == STEAM_URL
    assert runner.calls == [["open", STEAM_URL]]


# ------------------------------------------------------------------ language


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"LANG": "es_ES.UTF-8"}, "es_ES"),
        ({"LANG": "es-MX"}, "es_ES"),
        ({"LANG": "pt_BR.UTF-8"}, "pt_PT"),
        ({"LANG": "zh_TW"}, "zh_CN"),
        ({"LANG": "zh-Hans"}, "zh_CN"),
        ({"LANG": "fr_FR.UTF-8"}, "en"),
        ({"LANG": "C"}, "en"),
        ({"LC_MESSAGES": "es_ES", "LANG": "en_US"}, "es_ES"),
        ({"LC_ALL": "pt_PT", "LC_MESSAGES": "es_ES", "LANG": "zh_CN"}, "pt_PT"),
        ({"LC_ALL": "en_US", "LANG": "es_ES"}, "en"),
    ],
)
def test_default_language_follows_the_posix_precedence(fake_env, env: dict, expected: str) -> None:
    assert detect_default_language(fake_env("linux", env)) == expected
