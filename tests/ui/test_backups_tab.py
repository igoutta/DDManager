"""P19: the Backups tab lists managed and legacy backups, restores them validated and confirmed."""

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QTabWidget

from src.services import platform_actions
from src.services.backup import BackupReason, BackupRecord
from src.services.errors import BackupInvalidError, GameRunningError, LaunchError
from tests.ui.m5_support import assert_no_raw_keys, construct, follow_language, load_attr

STAMP = "%Y-%m-%d %H:%M"


def when(day, hour, minute=0):
    return datetime(2026, 5, day, hour, minute).astimezone()


@pytest.fixture
def records(fake_services, tmp_path):
    save = fake_services.save_path
    folder = tmp_path / "backups"
    legacy = save.parent
    return [
        BackupRecord(
            folder / "persist.game.backup.20260503-101500.json",
            save,
            when(3, 10, 15),
            BackupReason.PRE_PATCH,
            2048,
            "a" * 64,
            "managed",
        ),
        BackupRecord(
            folder / "persist.game.backup.20260502-091000.json",
            save,
            when(2, 9, 10),
            BackupReason.MANUAL,
            10,
            None,
            "managed",
        ),
        BackupRecord(
            legacy / "persist.game.backup.20260420-180000.json",
            save,
            when(20, 18),
            None,
            5 * 1024 * 1024,
            None,
            "legacy",
        ),
    ]


@pytest.fixture
def rig(rig_factory, records):
    rig = rig_factory(window=True)
    rig.services.backups.records[:] = records
    return rig


@pytest.fixture
def open_manager(rig, qtbot):
    def make():
        dialog = construct(
            load_attr("src.ui.dialogs.profile_manager_dialog", "ProfileManagerDialog"),
            port=rig.controller.profiles,
            translator=rig.translator,
            icons=rig.window.icons,
            parent=rig.window,
        )
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.backups_tab.refresh()
        return dialog

    return make


def cells(table):
    return [
        [table.item(r, c).text() for c in range(table.columnCount())]
        for r in range(table.rowCount())
    ]


def select(dialog, row):
    dialog.backups_tab.table.selectRow(row)


# ---------------------------------------------------------------------------- listing


def test_managed_and_legacy_backups_are_listed_newest_first_with_their_details(
    rig, records, open_manager
):
    dialog = open_manager()
    assert cells(dialog.backups_tab.table) == [
        [records[0].created.strftime(STAMP), "pre-patch", "2 KiB", "managed"],
        [records[1].created.strftime(STAMP), "manual", "10 B", "managed"],
        [records[2].created.strftime(STAMP), "", "5120 KiB", "legacy"],
    ]
    assert rig.services.backups.list_calls >= 1


def test_the_listing_is_the_active_slots_only(rig, records, open_manager):
    open_manager()
    asked = rig.services.backups.list_calls
    assert asked
    assert rig.controller.profiles.backups_for_active()[0].path == records[0].path
    rig.controller.session.save_path = None
    assert rig.controller.profiles.backups_for_active() == []


def test_the_tab_refreshes_when_it_is_shown(rig, open_manager):
    dialog = open_manager()
    tabs = dialog.findChild(QTabWidget)
    calls = rig.services.backups.list_calls
    tabs.setCurrentIndex(0)
    tabs.setCurrentIndex(2)
    assert rig.services.backups.list_calls > calls
    assert tabs.tabText(2) == rig.translator.tr("ui.manager.backups")


def test_every_text_of_the_tab_is_in_the_catalog(rig, open_manager):
    assert_no_raw_keys(open_manager())


# ---------------------------------------------------------------------------- restore


def test_restore_asks_first_and_names_the_file(rig, records, open_manager):
    dialog = open_manager()
    select(dialog, 1)
    dialog.backups_tab.restore_button.click()
    (args, kwargs) = rig.prompter.calls_named("confirm")[0]
    assert args == ("ui.backups.restore_confirm",)
    assert kwargs == {"name": records[1].path.name}


def test_declining_restores_nothing(rig, open_manager):
    rig.prompter.answers["confirm"] = False
    dialog = open_manager()
    select(dialog, 0)
    dialog.backups_tab.restore_button.click()
    assert rig.services.backups.restores == []
    assert rig.messages.log == []


def test_restore_without_a_selected_row_does_nothing(rig, open_manager):
    dialog = open_manager()
    dialog.backups_tab.table.clearSelection()
    dialog.backups_tab.table.setCurrentCell(-1, -1)
    dialog.backups_tab.restore_button.click()
    assert rig.prompter.calls_named("confirm") == []
    assert rig.services.backups.restores == []


@pytest.mark.parametrize("row", [0, 2])
def test_restore_replaces_the_active_save_with_the_selected_backup(
    rig, records, open_manager, row, qtbot
):
    dialog = open_manager()
    select(dialog, row)
    with qtbot.waitSignal(rig.controller.slotsChanged, timeout=2000):
        dialog.backups_tab.restore_button.click()
    assert rig.services.backups.restores == [(records[row], rig.services.save_path)]
    note = rig.messages.only("ui.notice.restored")
    assert note.params == {"name": records[row].path.name}


def test_a_restore_is_remembered_for_the_rollback_and_the_slot_list_refreshes(
    rig, records, open_manager
):
    dialog = open_manager()
    select(dialog, 0)
    calls = rig.services.backups.list_calls
    dialog.backups_tab.restore_button.click()
    written = rig.settings_written()
    pre_restore = rig.services.backups.record(rig.services.save_path)
    assert Path(written["last_save_path"]) == rig.services.save_path
    assert Path(written["last_backup_path"]) == pre_restore.path, "v0.2.1 can restore it again"
    assert rig.controller.status().last_backup == pre_restore.created
    assert rig.services.backups.list_calls > calls, "the table is read again after the restore"


@pytest.mark.parametrize(
    "error",
    [
        BackupInvalidError("Backup x is not a valid save: bad magic", path="x"),
        GameRunningError("Darkest Dungeon is running; close it before restoring a save."),
    ],
)
def test_a_refused_restore_is_reported_and_remembers_nothing(rig, open_manager, error):
    rig.services.backups.raise_on_restore = error
    dialog = open_manager()
    select(dialog, 0)
    dialog.backups_tab.restore_button.click()
    expected_key = (
        error.message_key if rig.translator.has(error.message_key) else "ui.error.operation"
    )
    failed = [m for m in rig.messages.log if m.level == "error"]
    assert [m.key for m in failed] == [expected_key]
    assert failed[0].params["details"] == error.message
    assert rig.messages.with_key("ui.notice.restored") == []
    assert "last_backup_path" not in rig.settings_written()


# ---------------------------------------------------------------------------- the folder


def test_open_folder_shows_the_backup_folder_of_the_slot(rig, open_manager, monkeypatch):
    opened = []
    monkeypatch.setattr(platform_actions, "open_folder", lambda path, env: opened.append(path))
    dialog = open_manager()
    dialog.backups_tab.folder_button.click()
    assert opened == [rig.services.backups.slot_dir(rig.services.save_path)]


def test_a_folder_that_cannot_be_opened_is_a_notice_not_a_crash(rig, open_manager, monkeypatch):
    def refuse(path, env):
        raise LaunchError("That folder is not set or no longer exists.")

    monkeypatch.setattr(platform_actions, "open_folder", refuse)
    dialog = open_manager()
    dialog.backups_tab.folder_button.click()
    note = rig.messages.only("ui.notice.action_failed")
    assert note.level == "error"
    assert note.params == {"error": "That folder is not set or no longer exists."}


# ---------------------------------------------------------------------------- language


@pytest.mark.parametrize("language", ["es_ES", "pt_PT", "zh_CN"])
def test_the_tab_follows_the_language_live(rig, open_manager, language):
    dialog = open_manager()
    follow_language(dialog, rig.translator, language)
    assert cells(dialog.backups_tab.table)[0][3] == "managed", "data cells are not translated"
