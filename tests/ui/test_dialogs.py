"""The five dialogs, driven through their public widgets (no exec loops)."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QPushButton,
    QTableView,
    QTableWidget,
    QTabWidget,
    QTreeWidget,
)

from src.ui.dialogs.crash_dialog import CrashDialog
from src.ui.dialogs.order_diff_dialog import OrderDiffDialog
from src.ui.dialogs.patch_preview_dialog import PatchPreviewDialog
from src.ui.dialogs.profile_manager_dialog import ProfileManagerDialog
from src.ui.dialogs.shortcuts_dialog import ShortcutsDialog
from tests.ui.helpers import action_specs_of, build, first_attr, make_diff_vm, make_patch_vm


@pytest.fixture
def common(main_window, translator, tokens, icons):
    controller = main_window.test_controller
    return {
        "translator": translator,
        "tokens": tokens,
        "icons": icons,
        "actions": list(main_window.hub.actions.values()),
        "controller": controller,
        "profiles": controller.profiles,
        "title": "Unexpected error",
        "summary": "Boom happened",
        "text": "Boom happened",
        "details": "Traceback (most recent call last): boom",
        "title_key": "ui.diff.title.auto_sort",
        "specs": action_specs_of(main_window),
        "parent": main_window,
    }


def all_text(dialog) -> list[str]:
    out = [w.text() for w in dialog.findChildren(QLabel)]
    out += [w.text() for w in dialog.findChildren(QAbstractButton)]
    for table in dialog.findChildren(QTableWidget):
        out += [
            table.item(r, c).text()
            for r in range(table.rowCount())
            for c in range(table.columnCount())
            if table.item(r, c)
        ]
    for tree in dialog.findChildren(QTreeWidget):
        out += [
            tree.topLevelItem(r).text(c)
            for r in range(tree.topLevelItemCount())
            for c in range(tree.columnCount())
        ]
    for lst in dialog.findChildren(QListWidget):
        out += [lst.item(r).text() for r in range(lst.count())]
    for view in dialog.findChildren(QTableView):
        model = view.model()
        if model is not None:
            out += [
                str(model.index(r, c).data())
                for r in range(model.rowCount())
                for c in range(model.columnCount())
            ]
    return out


def role_button(dialog, *roles):
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None, "dialog has no QDialogButtonBox"
    for button in box.buttons():
        if box.buttonRole(button) in roles:
            return button
    raise AssertionError(f"no button with role {roles}")


ACCEPT = (QDialogButtonBox.ButtonRole.AcceptRole, QDialogButtonBox.ButtonRole.ApplyRole)
REJECT = (QDialogButtonBox.ButtonRole.RejectRole,)


def test_order_diff_lists_every_row_and_the_move_count(qtbot, common):
    dialog = build(OrderDiffDialog, vm=make_diff_vm(moved=2, total=5), **common)
    qtbot.addWidget(dialog)
    assert any("2 of 5" in t for t in all_text(dialog))
    texts = all_text(dialog)
    for i in range(5):
        assert any(f"Mod {i}" in t for t in texts)


def test_order_diff_apply_accepts_and_cancel_rejects(qtbot, common):
    dialog = build(OrderDiffDialog, vm=make_diff_vm(), **common)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.mouseClick(role_button(dialog, *ACCEPT), Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Accepted
    again = build(OrderDiffDialog, vm=make_diff_vm(), **common)
    qtbot.addWidget(again)
    again.show()
    qtbot.mouseClick(role_button(again, *REJECT), Qt.MouseButton.LeftButton)
    assert again.result() == QDialog.DialogCode.Rejected


def test_patch_preview_shows_slot_path_backup_and_lists(qtbot, common):
    dialog = build(PatchPreviewDialog, vm=make_patch_vm(), **common)
    qtbot.addWidget(dialog)
    joined = "\n".join(all_text(dialog))
    for needle in ("Slot 1", "persist.game.json", "backups"):
        assert needle in joined, needle


def test_patch_preview_requires_every_ack_before_the_primary_button(qtbot, common):
    vm = make_patch_vm(acks=(("cloud", "ui.patch.ack.cloud"), ("running", "ui.patch.ack.running")))
    dialog = build(PatchPreviewDialog, vm=vm, **common)
    qtbot.addWidget(dialog)
    dialog.show()
    primary = role_button(dialog, *ACCEPT)
    boxes = dialog.findChildren(QCheckBox)
    assert len(boxes) == 2
    assert not primary.isEnabled()
    boxes[0].setChecked(True)
    assert not primary.isEnabled()
    boxes[1].setChecked(True)
    assert primary.isEnabled()
    decision = first_attr(dialog, ("decision", "patch_decision"))()
    assert decision.proceed is True
    assert decision.acknowledged == frozenset({"cloud", "running"})
    assert decision.override_errors is False


def test_patch_preview_blocking_needs_the_override_checkbox(qtbot, common):
    dialog = build(PatchPreviewDialog, vm=make_patch_vm(blocking=True), **common)
    qtbot.addWidget(dialog)
    dialog.show()
    primary = role_button(dialog, *ACCEPT)
    assert not primary.isEnabled()
    override = [b for b in dialog.findChildren(QCheckBox) if "despite" in b.text().lower()]
    assert len(override) == 1
    override[0].setChecked(True)
    assert primary.isEnabled()
    assert first_attr(dialog, ("decision", "patch_decision"))().override_errors is True


def test_patch_preview_non_blocking_has_no_override_checkbox(qtbot, common):
    dialog = build(PatchPreviewDialog, vm=make_patch_vm(), **common)
    qtbot.addWidget(dialog)
    assert not [b for b in dialog.findChildren(QCheckBox) if "despite" in b.text().lower()]
    assert role_button(dialog, *ACCEPT).isEnabled()


def test_profile_manager_has_three_tabs(qtbot, common):
    dialog = build(ProfileManagerDialog, **common)
    qtbot.addWidget(dialog)
    tabs = dialog.findChild(QTabWidget)
    assert tabs is not None
    assert tabs.count() == 3
    assert all(tabs.tabText(i).strip() for i in range(3))
    assert len({tabs.tabText(i) for i in range(3)}) == 3


def test_profile_manager_lists_the_detected_slot(qtbot, common):
    dialog = build(ProfileManagerDialog, **common)
    qtbot.addWidget(dialog)
    dialog.show()
    assert any("persist.game.json" in t or "profile_0" in t for t in all_text(dialog))


def test_crash_dialog_has_four_actions_and_copies_details(qtbot, common):
    dialog = build(CrashDialog, **common)
    qtbot.addWidget(dialog)
    dialog.show()
    buttons = {b.text().lower(): b for b in dialog.findChildren(QPushButton)}
    for needle in ("copy", "log", "continue", "quit"):
        assert any(needle in t for t in buttons), (needle, list(buttons))
    copy = next(b for t, b in buttons.items() if "copy" in t)
    qtbot.mouseClick(copy, Qt.MouseButton.LeftButton)
    assert "boom" in QGuiApplication.clipboard().text().lower()


def test_shortcuts_dialog_lists_every_shortcut(qtbot, common):
    dialog = build(ShortcutsDialog, **common)
    qtbot.addWidget(dialog)
    joined = "\n".join(all_text(dialog))
    for seq in ("F5", "F7", "Ctrl+Shift+P", "Ctrl+Shift+A", "Ctrl+B", "F1"):
        assert seq in joined, seq
