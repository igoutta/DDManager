"""Settings dialog (priority, language, density, retention, trust) and plugin approval."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTableWidget

from src.core.load_order import PriorityDirection
from src.services.plugin_loader import PluginRecord
from src.services.settings_repo import RetentionPolicy
from tests.ui.m5_support import (
    action_for,
    assert_no_raw_keys,
    construct,
    follow_language,
    load_attr,
)

REPO_ROOT = Path(__file__).parents[2]
PLUGIN_SOURCE = b"def register(registry):\n    return None\n"


@pytest.fixture
def rig(rig_factory):
    return rig_factory(window=True)


@pytest.fixture
def open_settings(rig, qtbot):
    def make():
        dialog = construct(
            load_attr("src.ui.dialogs.settings_dialog", "SettingsDialog"),
            presenter=rig.controller.settings,
            translator=rig.translator,
            icons=rig.window.icons,
            parent=rig.window,
        )
        qtbot.addWidget(dialog)
        dialog.show()
        return dialog

    return make


def persisted(rig):
    """The settings file as the real repository reads it back."""
    settings, findings = rig.services.settings.load()
    assert not findings
    return settings


RULE_V1 = b"# rule v1" + bytes([10])


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def table_rows(table: QTableWidget) -> list[list[str]]:
    rows = []
    for r in range(table.rowCount()):
        items = [table.item(r, c) for c in range(table.columnCount())]
        rows.append([item.text() for item in items if item is not None])
    return rows


# ---------------------------------------------------------------------------- initial values


def test_the_dialog_shows_the_current_settings(rig, open_settings):
    dialog = open_settings()
    assert dialog.first_radio.isChecked()
    assert not dialog.last_radio.isChecked()
    assert dialog.verified_box.isChecked()
    assert (dialog.keep_last.value(), dialog.keep_days.value(), dialog.min_keep.value()) == (
        RetentionPolicy().keep_last,
        RetentionPolicy().keep_days,
        RetentionPolicy().min_keep,
    )
    assert dialog.language_combo.currentData() == "en"
    assert dialog.density_combo.currentData() == "Comfortable"
    assert not dialog.plugins_section.enable_box.isChecked()
    assert not dialog.rules_section.enable_box.isChecked()


def test_every_text_of_the_dialog_is_in_the_catalog(rig, open_settings):
    dialog = open_settings()
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        assert_no_raw_keys(dialog)


def test_the_languages_offered_are_the_four_catalogs_in_menu_order(rig, open_settings):
    dialog = open_settings()
    codes = [dialog.language_combo.itemData(i) for i in range(dialog.language_combo.count())]
    assert codes == ["en", "zh_CN", "pt_PT", "es_ES"]
    modes = [dialog.density_combo.itemData(i) for i in range(dialog.density_combo.count())]
    assert modes == ["No Icons", "Compact", "Comfortable", "Visual"]


# ---------------------------------------------------------------------------- priority


def test_choosing_last_wins_applies_at_once_and_is_persisted(rig, open_settings):
    dialog = open_settings()
    dialog.last_radio.click()
    assert rig.controller.priority().direction is PriorityDirection.LAST_WINS
    assert persisted(rig).priority.direction is PriorityDirection.LAST_WINS
    assert persisted(rig).priority.verified is True
    labels = rig.controller.status()
    assert "wins" in labels.direction_bottom_label.lower()
    assert "wins" not in labels.direction_top_label.lower()


def test_the_verified_toggle_is_a_flag_not_a_third_direction(rig, open_settings):
    dialog = open_settings()
    dialog.verified_box.click()
    setting = persisted(rig).priority
    assert setting.verified is False
    assert setting.direction is PriorityDirection.FIRST_WINS
    assert rig.controller.status().direction_verified is False
    dialog.verified_box.click()
    assert persisted(rig).priority.verified is True


def test_the_priority_section_links_to_the_load_order_semantics_doc(
    rig, open_settings, monkeypatch
):
    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(opened.append))
    dialog = open_settings()
    dialog.docs_button.click()
    assert len(opened) == 1
    assert opened[0].toString().endswith("docs/load-order-semantics.md")
    assert (REPO_ROOT / "docs" / "load-order-semantics.md").is_file()


# ---------------------------------------------------------------------------- language and density


def test_choosing_a_language_switches_the_interface_and_persists_the_language_key(
    rig, open_settings
):
    dialog = open_settings()
    index = dialog.language_combo.findData("es_ES")
    dialog.language_combo.setCurrentIndex(index)
    dialog.language_combo.activated.emit(index)
    assert rig.translator.language() == "es_ES"
    assert rig.settings_written()["language"] == "es_ES"
    assert rig.window.windowTitle() == rig.translator.tr("app_title")
    assert dialog.language_combo.currentData() == "es_ES", "the dialog re-fills in the new language"


def test_choosing_a_density_changes_the_rows_and_persists_the_view_mode(rig, open_settings):
    dialog = open_settings()
    index = dialog.density_combo.findData("Visual")
    dialog.density_combo.setCurrentIndex(index)
    dialog.density_combo.activated.emit(index)
    assert rig.controller.density() == "Visual"
    assert rig.settings_written()["view_mode"] == "Visual"
    assert rig.window.hub.actions["density_visual"].isChecked()


# ---------------------------------------------------------------------------- retention


def test_retention_is_persisted_as_one_policy(rig, open_settings):
    dialog = open_settings()
    dialog.keep_last.setValue(5)
    dialog.keep_days.setValue(10)
    dialog.min_keep.setValue(2)
    assert persisted(rig).backups == RetentionPolicy(keep_last=5, keep_days=10, min_keep=2)


def test_retention_never_goes_below_one_kept_backup(rig, open_settings):
    dialog = open_settings()
    dialog.keep_last.setValue(0)
    assert dialog.keep_last.value() == 1
    assert persisted(rig).backups.keep_last == 1
    assert dialog.keep_last.minimum() == 1
    assert dialog.min_keep.minimum() == 0
    assert dialog.keep_days.minimum() == 0


def test_the_note_says_retention_applies_at_the_next_start(rig, open_settings):
    dialog = open_settings()
    assert dialog.backups_note.text() == rig.translator.tr("ui.settings.restart_note")
    assert dialog.backups_note.text() != "ui.settings.restart_note"


# ---------------------------------------------------------------------------- trust


@pytest.fixture
def plugin_file(rig):
    path = rig.services.paths.plugins_dir / "extra_source.py"
    path.write_bytes(PLUGIN_SOURCE)
    return path


@pytest.fixture
def rule_file(rig):
    path = rig.services.paths.rules_dir / "extra_rule.py"
    path.write_bytes(PLUGIN_SOURCE + b"# rule\n")
    return path


def test_the_switches_are_off_by_default_and_persist_when_turned_on(rig, open_settings):
    dialog = open_settings()
    dialog.plugins_section.enable_box.click()
    assert persisted(rig).plugins.enabled is True
    assert persisted(rig).rules.enabled is False
    dialog.rules_section.enable_box.click()
    assert persisted(rig).rules.enabled is True
    dialog.plugins_section.enable_box.click()
    assert persisted(rig).plugins.enabled is False


def test_files_are_listed_with_status_and_full_sha256(rig, open_settings, plugin_file, rule_file):
    dialog = open_settings()
    (plugin_row,) = table_rows(dialog.plugins_section.table)
    (rule_row,) = table_rows(dialog.rules_section.table)
    assert plugin_row[0] == "extra_source.py"
    assert plugin_row[2] == sha256(PLUGIN_SOURCE)
    assert rule_row[0] == "extra_rule.py"
    assert rule_row[2] == sha256(PLUGIN_SOURCE + b"# rule\n")
    assert plugin_row[1] == rig.translator.tr("ui.trust.status.not_approved")


def test_approve_pins_the_hash_of_the_file_and_revoke_removes_it(
    rig, open_settings, plugin_file, rule_file
):
    dialog = open_settings()
    section = dialog.plugins_section
    assert not section.approve_button.isEnabled(), "nothing selected"
    section.table.selectRow(0)
    assert section.approve_button.isEnabled()
    assert not section.revoke_button.isEnabled()
    section.approve_button.click()
    assert dict(persisted(rig).plugins.approved) == {"extra_source.py": sha256(PLUGIN_SOURCE)}
    assert dict(persisted(rig).rules.approved) == {}, "approving a plugin never approves rules"
    assert table_rows(section.table)[0][1] == rig.translator.tr("ui.trust.status.approved")
    section.table.selectRow(0)
    assert not section.approve_button.isEnabled()
    section.revoke_button.click()
    assert dict(persisted(rig).plugins.approved) == {}


def test_rule_modules_are_approved_separately(rig, open_settings, rule_file):
    dialog = open_settings()
    dialog.rules_section.table.selectRow(0)
    dialog.rules_section.approve_button.click()
    assert dict(persisted(rig).rules.approved) == {"extra_rule.py": sha256(rule_file.read_bytes())}
    assert dict(persisted(rig).plugins.approved) == {}


def test_a_file_edited_after_approval_is_shown_as_changed_and_must_be_approved_again(
    rig, open_settings, plugin_file
):
    dialog = open_settings()
    dialog.plugins_section.table.selectRow(0)
    dialog.plugins_section.approve_button.click()
    plugin_file.write_bytes(PLUGIN_SOURCE + b"# edited\n")
    dialog.plugins_section.refresh()
    row = table_rows(dialog.plugins_section.table)[0]
    assert row[1] == rig.translator.tr("ui.trust.status.changed")
    assert row[2] == sha256(PLUGIN_SOURCE + b"# edited\n")
    dialog.plugins_section.table.selectRow(0)
    assert dialog.plugins_section.approve_button.isEnabled()
    assert dialog.plugins_section.revoke_button.isEnabled()


def test_approving_a_file_that_changed_since_it_was_listed_is_refused(rig, plugin_file):
    trust = rig.controller.settings.trust
    listed = sha256(PLUGIN_SOURCE)
    plugin_file.write_bytes(PLUGIN_SOURCE + b"# swapped after the user looked\n")
    assert trust.approve("plugins", "extra_source.py", expected=listed) is False
    assert dict(persisted(rig).plugins.approved) == {}
    assert rig.messages.only("ui.notice.trust_stale").level == "warning"


def test_only_plain_file_names_can_be_approved(rig):
    trust = rig.controller.settings.trust
    assert trust.approve("plugins", "../evil.py") is False
    assert trust.approve("plugins", "missing.py") is False
    assert dict(persisted(rig).plugins.approved) == {}


def test_the_security_note_is_part_of_the_plugins_page(rig, open_settings):
    dialog = open_settings()
    assert dialog.security_note.text() == rig.translator.tr("ui.trust.security_note")
    assert dialog.security_note.text() != "ui.trust.security_note"
    assert dialog.plugins_tab.isAncestorOf(dialog.security_note)


# ---------------------------------------------------------------------------- general


def test_the_window_action_opens_the_dialog(rig):
    rig.driver.on("SettingsDialog", lambda dialog: dialog.last_radio.click())
    action_for(rig.window, "settings").trigger()
    assert rig.driver.names() == ["SettingsDialog"]
    assert persisted(rig).priority.direction is PriorityDirection.LAST_WINS


@pytest.mark.parametrize("language", ["es_ES", "pt_PT", "zh_CN"])
def test_the_dialog_follows_the_language_live(rig, open_settings, language):
    dialog = open_settings()
    result = follow_language(dialog, rig.translator, language)
    assert result.checked >= 6
    assert dialog.language_combo.currentData() == language


# ---------------------------------------------------------------------------- plugin approval


def record(rig, name, status, data=PLUGIN_SOURCE, kind="plugins"):
    directory = (
        rig.services.paths.plugins_dir if kind == "plugins" else rig.services.paths.rules_dir
    )
    path = directory / name
    path.write_bytes(data)
    return PluginRecord(path.stem, "user", path, sha256(data), status, (), None)


@pytest.fixture
def pending(rig):
    """A start-up with one new plugin, one changed rule module and one already running."""
    trust = rig.controller.settings.current().rules
    old = {"edited_rule.py": sha256(RULE_V1)}
    rig.controller.settings.save(
        replace(rig.controller.settings.current(), rules=replace(trust, approved=old))
    )
    rig.services.plugin_records = (
        record(rig, "new_source.py", "not_approved"),
        record(rig, "edited_rule.py", "changed", b"# rule v2\n", "rules"),
        record(rig, "fine.py", "loaded", b"# ok\n"),
    )
    return rig


@pytest.fixture
def open_approval(pending, qtbot):
    def make():
        dialog = construct(
            load_attr("src.ui.dialogs.plugin_approval_dialog", "PluginApprovalDialog"),
            presenter=pending.controller.settings.trust,
            translator=pending.translator,
            icons=pending.window.icons,
            parent=pending.window,
        )
        qtbot.addWidget(dialog)
        dialog.show()
        return dialog

    return make


def test_the_approval_dialog_lists_user_files_with_kind_status_and_hash(pending, open_approval):
    dialog = open_approval()
    tr = pending.translator.tr
    rows = {row[0]: row for row in table_rows(dialog.table)}
    assert set(rows) == {"new_source.py", "edited_rule.py", "fine.py"}
    assert rows["new_source.py"][1:] == [
        tr("ui.trust.kind.plugins"),
        tr("ui.trust.status.not_approved"),
        sha256(PLUGIN_SOURCE),
    ]
    assert rows["edited_rule.py"][1] == tr("ui.trust.kind.rules")
    assert rows["edited_rule.py"][2] == tr("ui.trust.status.changed")
    assert rows["fine.py"][2] == tr("ui.trust.status.loaded")
    assert_no_raw_keys(dialog)


def test_approve_pins_only_the_selected_file_and_only_pending_files_can_be_approved(
    pending, open_approval
):
    dialog = open_approval()
    names = [dialog.table.item(r, 0).text() for r in range(dialog.table.rowCount())]
    dialog.table.selectRow(names.index("fine.py"))
    assert not dialog.approve_button.isEnabled(), "a running file needs no approval"
    dialog.table.selectRow(names.index("new_source.py"))
    assert dialog.approve_button.isEnabled()
    dialog.approve_button.click()
    approved = persisted(pending)
    assert dict(approved.plugins.approved) == {"new_source.py": sha256(PLUGIN_SOURCE)}
    assert dict(approved.rules.approved) == {"edited_rule.py": sha256(RULE_V1)}
    status = {
        dialog.table.item(r, 0).text(): dialog.table.item(r, 2).text()
        for r in range(dialog.table.rowCount())
    }
    assert status["new_source.py"] == pending.translator.tr("ui.trust.status.approved")
    assert status["edited_rule.py"] == pending.translator.tr("ui.trust.status.changed")


def test_approve_all_asks_first_and_then_pins_every_pending_file(pending, open_approval):
    dialog = open_approval()
    pending.messages.confirm_answer = False
    dialog.approve_all_button.click()
    assert dict(persisted(pending).plugins.approved) == {}
    assert dict(persisted(pending).rules.approved) == {"edited_rule.py": sha256(RULE_V1)}
    pending.messages.confirm_answer = True
    dialog.approve_all_button.click()
    assert dict(persisted(pending).plugins.approved) == {"new_source.py": sha256(PLUGIN_SOURCE)}
    assert dict(persisted(pending).rules.approved) == {"edited_rule.py": sha256(b"# rule v2\n")}
    assert not dialog.approve_all_button.isEnabled(), "nothing is left to approve"


def test_later_closes_without_approving_anything(pending, open_approval):
    dialog = open_approval()
    dialog.close_button.click()
    assert not dialog.isVisible()
    assert dict(persisted(pending).plugins.approved) == {}


def test_the_dialog_is_offered_at_start_up_only_when_a_file_needs_a_decision(rig, pending):
    offer = load_attr("src.ui.widgets.manage_actions", "offer_plugin_approval")
    offer(rig.window)
    assert rig.driver.names() == ["PluginApprovalDialog"]


def test_nothing_is_offered_when_there_are_no_user_files_or_none_is_pending(rig):
    offer = load_attr("src.ui.widgets.manage_actions", "offer_plugin_approval")
    offer(rig.window)
    rig.services.plugin_records = (record(rig, "fine.py", "loaded"),)
    offer(rig.window)
    rig.services.plugin_records = (
        PluginRecord("builtin.sources", "builtin", None, None, "loaded", (), None),
    )
    offer(rig.window)
    assert rig.driver.opened == []


def test_the_approval_dialog_has_a_menu_action_too(rig, pending):
    rig.driver.on("PluginApprovalDialog", lambda dialog: dialog.close_button.click())
    action_for(rig.window, "plugin_approval").trigger()
    assert rig.driver.names() == ["PluginApprovalDialog"]


@pytest.mark.parametrize("language", ["es_ES", "pt_PT", "zh_CN"])
def test_the_approval_dialog_follows_the_language_live(pending, open_approval, language):
    dialog = open_approval()
    result = follow_language(dialog, pending.translator, language)
    assert result.checked >= 5
    assert dialog.table.item(0, 0).text() in {"new_source.py", "edited_rule.py", "fine.py"}
