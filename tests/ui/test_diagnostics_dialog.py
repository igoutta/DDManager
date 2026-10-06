"""P20: Check Setup shows a copyable English report; Copy Debug Info copies the same text."""

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QPlainTextEdit

from src.__about__ import __version__
from src.core.diagnostics import DiagnosticsInput, diagnostics_lines
from src.services.backup import BackupReason, BackupRecord
from tests.ui.conftest import ENABLED
from tests.ui.m5_support import (
    assert_no_raw_keys,
    construct,
    find_button,
    follow_language,
    load_attr,
    shown_models,
    tool_dialog,
    trigger,
)

LINES = ("DD Manager version: 0.3.0", "Mods loaded: 3", "Last backup: (none)")


def types():
    vm_cls = load_attr("src.ui.presenters.tools_dto", "DiagnosticsVM")
    dialog_cls = load_attr("src.ui.dialogs.diagnostics_dialog", "DiagnosticsDialog")
    return vm_cls, dialog_cls


def dialog_for(lines, translator, icons, qtbot):
    vm_cls, dialog_cls = types()
    vm = vm_cls(text="\n".join(lines), lines=tuple(lines))
    dialog = construct(dialog_cls, vm=vm, translator=translator, icons=icons, parent=None)
    qtbot.addWidget(dialog)
    return dialog


def line_of(lines, label):
    found = [line for line in lines if line.startswith(f"{label}:")]
    assert len(found) == 1, f"{label!r} must be reported exactly once: {lines}"
    return found[0].split(":", 1)[1].strip()


def report(rig):
    """The lines Check Setup reports, through the dialog the action ends up showing."""
    vm_cls, dialog_cls = types()
    dialog = tool_dialog(rig, "check_setup", dialog_cls, vm_cls)
    return dialog, dialog.text.toPlainText().splitlines()


# ---------------------------------------------------------------------------- the dialog


def test_the_report_is_shown_verbatim_read_only_and_selectable(qtbot, translator, icons):
    dialog = dialog_for(LINES, translator, icons, qtbot)
    box = dialog.findChild(QPlainTextEdit)
    assert box.toPlainText() == "\n".join(LINES)
    assert box.isReadOnly()


def test_every_text_of_the_dialog_is_in_the_catalog(qtbot, translator, icons):
    assert_no_raw_keys(dialog_for(LINES, translator, icons, qtbot))


def test_copy_puts_the_exact_report_on_the_clipboard(qtbot, translator, icons):
    dialog = dialog_for(LINES, translator, icons, qtbot)
    QGuiApplication.clipboard().setText("stale")
    dialog.show()
    qtbot.waitExposed(dialog)
    find_button(dialog, translator.tr("ui.diag.copy")).click()
    assert QGuiApplication.clipboard().text() == "\n".join(LINES)


def test_close_closes_the_dialog(qtbot, translator, icons):
    dialog = dialog_for(LINES, translator, icons, qtbot)
    dialog.show()
    qtbot.waitExposed(dialog)
    find_button(dialog, translator.tr("ui.dialog.close")).click()
    assert not dialog.isVisible()


@pytest.mark.parametrize("language", ["es_ES", "pt_PT", "zh_CN"])
def test_the_chrome_follows_the_language_but_the_report_stays_english(
    qtbot, translator, icons, language
):
    dialog = dialog_for(LINES, translator, icons, qtbot)
    result = follow_language(dialog, translator, language)
    assert result.checked >= 2
    assert dialog.text.toPlainText() == "\n".join(
        LINES
    )  # pasted into bug reports: never translated


# ---------------------------------------------------------------------------- the report


def test_check_setup_reports_the_facts_of_the_session(rig_factory):
    rig = rig_factory(window=True)
    services = rig.services
    _dialog, lines = report(rig)
    save = services.save_path
    assert line_of(lines, "DD Manager version") == __version__
    assert line_of(lines, "Mods loaded") == str(len(services.catalog))
    assert line_of(lines, "Enabled mods") == str(len(ENABLED))
    assert line_of(lines, "Disabled mods") == str(len(services.catalog) - len(ENABLED))
    assert line_of(lines, "Mods folder valid") == "Yes"
    assert Path(line_of(lines, "Mods folder")) == services.detector.snapshot.primary_mods_dir
    assert Path(line_of(lines, "Selected save")) == save
    assert line_of(lines, "Save detected") == "Yes"
    assert line_of(lines, "Save has applied_ugcs_1_0") == "Yes"
    assert line_of(lines, "Applied mods in save") == str(len(services.in_save))
    assert line_of(lines, "Last backup") == "(none)"
    assert Path(line_of(lines, "App data folder")) == services.paths.data_dir
    assert line_of(lines, "Python")
    assert line_of(lines, "Platform")


def test_the_report_matches_the_pure_builder_line_for_line(rig_factory):
    rig = rig_factory(window=True)
    services = rig.services
    session = rig.controller.session
    uncategorized = sum(1 for mod in session.order.entries if mod not in session.categories)
    _dialog, lines = report(rig)
    expected = diagnostics_lines(
        DiagnosticsInput(
            app_version=__version__,
            python_version=line_of(lines, "Python"),
            platform=line_of(lines, "Platform"),
            data_dir=str(services.paths.data_dir),
            mods_path=str(services.detector.snapshot.primary_mods_dir),
            mods_path_valid=True,
            mod_count=len(services.catalog),
            enabled_count=len(ENABLED),
            uncategorized_count=uncategorized,
            selected_save=str(services.save_path),
            save_detected=True,
            save_has_applied_block=True,
            applied_count=len(services.in_save),
            last_backup="",
            game_root="",
            workshop_dir="",
            local_mods_dir=str(services.detector.snapshot.local_mod_dirs[0]),
            priority_direction=line_of(lines, "Priority direction"),
            priority_verified=True,
        )
    )
    assert tuple(lines) == expected


def test_the_roots_and_the_last_backup_are_reported(rig_factory, tmp_path):
    rig = rig_factory(window=True)
    services = rig.services
    game, workshop = tmp_path / "Darkest Dungeon", tmp_path / "workshop" / "262060"
    services.detector.set_snapshot(game_roots=(game,), workshop_dirs=(workshop,))
    when = datetime(2026, 5, 2, 9, 30).astimezone()
    services.backups.records.append(
        BackupRecord(
            tmp_path / "persist.game.backup.20260502-093000.json",
            services.save_path,
            when,
            BackupReason.MANUAL,
            10,
            None,
            "managed",
        )
    )
    rig.controller.rescan()  # the new install and backup become known
    _dialog, lines = report(rig)
    assert Path(line_of(lines, "Game install")) == game
    assert Path(line_of(lines, "Workshop mods folder")) == workshop
    assert line_of(lines, "Last backup") != "(none)"


def test_without_a_save_the_save_lines_say_not_checked(rig_factory):
    rig = rig_factory(
        window=True,
        extra={"last_save_path": "", "selected_profile_path": ""},
    )
    rig.services.detector.set_snapshot(save_files=())
    rig.controller.rescan()
    _dialog, lines = report(rig)
    assert line_of(lines, "Selected save") == "(not selected)"
    assert line_of(lines, "Save detected") == "No"
    assert line_of(lines, "Save has applied_ugcs_1_0") == "Not checked"
    assert line_of(lines, "Applied mods in save") == "Not checked"


def test_the_report_stays_english_whatever_the_interface_language(rig_factory):
    rig = rig_factory(window=True)
    _dialog, english = report(rig)
    rig.controller.set_language("es_ES")
    _dialog, spanish = report(rig)
    assert spanish == english


# ---------------------------------------------------------------------------- copy debug info


def test_copy_debug_info_copies_the_same_text_without_opening_a_dialog(rig_factory):
    rig = rig_factory(window=True)
    _dialog, lines = report(rig)
    opened = len(rig.driver.opened)
    QGuiApplication.clipboard().setText("stale")
    trigger(rig.window, "copy_debug")
    assert len(rig.driver.opened) == opened
    assert QGuiApplication.clipboard().text().splitlines() == lines
    assert rig.messages.log, "the user is told the debug info was copied"


def test_check_setup_never_changes_anything(rig_factory):
    rig = rig_factory(window=True)
    order = rig.controller.order()
    shown_models(rig, "check_setup", load_attr("src.ui.presenters.tools_dto", "DiagnosticsVM"))
    assert rig.controller.order() == order
    assert rig.controller.undo_stack.count() == 0
    rig.controller.flush()
    assert all(changes.order is None or changes.order == order for changes in rig.state.saves)
