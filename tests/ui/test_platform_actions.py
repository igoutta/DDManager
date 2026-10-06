"""P21: Launch Game and Open Local Mods Folder go through ``platform_actions`` and report back."""

from pathlib import Path

import pytest

from src.services import platform_actions
from src.services.errors import LaunchError
from tests.ui.m5_support import action_for


@pytest.fixture
def launches(monkeypatch):
    calls: list[tuple[str, tuple]] = []
    monkeypatch.setattr(
        platform_actions,
        "launch_game",
        lambda install, env: calls.append(("launch", (install, env))),
    )
    monkeypatch.setattr(
        platform_actions, "open_folder", lambda path, env: calls.append(("open", (path, env)))
    )
    return calls


@pytest.fixture
def rig(rig_factory):
    return rig_factory(window=True)


# ---------------------------------------------------------------------------- launch


def test_launch_starts_the_game_with_the_detected_install(rig, launches):
    action_for(rig.window, "launch_game").trigger()
    assert launches == [("launch", (rig.controller.install(), rig.services.env))]
    assert rig.controller.install() is rig.services.detector.snapshot
    assert rig.messages.only("ui.notice.game_launched").level == "info"


def test_a_failed_launch_is_a_notice_not_a_crash(rig, monkeypatch):
    def refuse(install, env):
        raise LaunchError("No Steam launcher or local Darkest Dungeon executable was found.")

    monkeypatch.setattr(platform_actions, "launch_game", refuse)
    action_for(rig.window, "launch_game").trigger()
    note = rig.messages.only("ui.notice.action_failed")
    assert note.level == "error"
    assert note.params == {
        "error": "No Steam launcher or local Darkest Dungeon executable was found."
    }
    assert rig.messages.with_key("ui.notice.game_launched") == []


def test_launching_before_the_first_scan_asks_to_scan_first(rig_factory, launches):
    rig = rig_factory(window=True, start=False)
    action_for(rig.window, "launch_game").trigger()
    assert launches == []
    assert rig.messages.only("ui.notice.not_scanned").level == "warning"


def test_the_toolbar_and_the_file_menu_both_offer_launch(rig):
    launch = action_for(rig.window, "launch_game")
    assert launch in rig.window.chrome.toolbar.actions()
    assert launch in rig.window.chrome.menus["file"].actions()
    assert action_for(rig.window, "open_local_mods") in rig.window.chrome.menus["file"].actions()
    assert launch.toolTip() != launch.text()


# ---------------------------------------------------------------------------- local mods folder


def test_open_local_mods_shows_the_first_local_mods_folder(rig, launches):
    action_for(rig.window, "open_local_mods").trigger()
    folder = rig.services.detector.snapshot.local_mod_dirs[0]
    assert launches == [("open", (folder, rig.services.env))]
    note = rig.messages.only("ui.notice.local_mods_opened")
    assert Path(note.params["path"]) == folder


def test_without_a_local_mods_folder_the_user_is_told(rig, launches):
    rig.services.detector.set_snapshot(local_mod_dirs=())
    rig.controller.rescan()
    rig.messages.clear()
    action_for(rig.window, "open_local_mods").trigger()
    assert launches == []
    assert rig.messages.only("ui.notice.no_local_mods").level == "warning"


def test_a_folder_that_cannot_be_opened_is_a_notice(rig, monkeypatch):
    def refuse(path, env):
        raise LaunchError("That folder is not set or no longer exists.")

    monkeypatch.setattr(platform_actions, "open_folder", refuse)
    action_for(rig.window, "open_local_mods").trigger()
    assert rig.messages.only("ui.notice.action_failed").params == {
        "error": "That folder is not set or no longer exists."
    }
    assert rig.messages.with_key("ui.notice.local_mods_opened") == []


def test_open_local_mods_before_the_first_scan_asks_to_scan_first(rig_factory, launches):
    rig = rig_factory(window=True, start=False)
    action_for(rig.window, "open_local_mods").trigger()
    assert launches == []
    assert rig.messages.only("ui.notice.not_scanned").level == "warning"
