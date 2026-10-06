"""Every action and button of the window and of each dialog explains itself in a tooltip."""

import json
from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractButton

from tests.ui.helpers import action_specs_of, build, make_diff_vm, make_patch_vm

EN_JSON = Path(__file__).parents[2] / "src" / "resources" / "i18n" / "en.json"


def en_catalog() -> dict[str, str]:
    data = json.loads(EN_JSON.read_text(encoding="utf-8"))
    return data.get("catalog", data) if isinstance(data.get("catalog"), dict) else data


def items(root):
    for obj in (*root.findChildren(QAction), *root.findChildren(QAbstractButton)):
        name = obj.objectName()
        if name.startswith(("qt_", "_q_")) or type(obj).__name__ == "QTableCornerButton":
            continue
        yield obj


def check_tooltips(root) -> int:
    seen = 0
    for obj in items(root):
        seen += 1
        label = f"{type(obj).__name__} {obj.objectName() or obj.text()!r}"
        tip = obj.toolTip()
        assert tip.strip(), f"{label}: empty tooltip"
        assert tip != obj.text(), f"{label}: tooltip repeats the label"
    return seen


def test_main_window_actions_and_buttons(main_window):
    assert check_tooltips(main_window) >= 12


def test_every_ddm_key_has_a_tip_in_en_json(main_window):
    catalog = en_catalog()
    keys = {
        a.property("ddm_key") for a in main_window.findChildren(QAction) if a.property("ddm_key")
    }
    assert len(keys) >= 12
    for key in sorted(keys):
        assert catalog.get(f"ui.action.{key}.tip", "").strip(), f"ui.action.{key}.tip"
        assert catalog.get(f"ui.action.{key}", "").strip(), f"ui.action.{key}"


def test_toolbar_actions_use_the_translated_tip(main_window, translator):
    for action in main_window.findChildren(QAction):
        key = action.property("ddm_key")
        if key:
            assert translator.tr(f"ui.action.{key}.tip") in action.toolTip()


def _dialogs(main_window, translator, fake_services):
    from src.ui.dialogs.crash_dialog import CrashDialog
    from src.ui.dialogs.order_diff_dialog import OrderDiffDialog
    from src.ui.dialogs.patch_preview_dialog import PatchPreviewDialog
    from src.ui.dialogs.profile_manager_dialog import ProfileManagerDialog
    from src.ui.dialogs.shortcuts_dialog import ShortcutsDialog

    controller = main_window.test_controller
    common = {
        "translator": translator,
        "tokens": main_window.tokens,
        "icons": main_window.icons,
        "actions": list(main_window.hub.actions.values()),
        "controller": controller,
        "profiles": controller.profiles,
        "title": "Crash",
        "summary": "Boom",
        "text": "Boom",
        "details": "Traceback",
        "title_key": "ui.diff.title.auto_sort",
        "specs": action_specs_of(main_window),
        "parent": main_window,
    }
    yield "order_diff", build(OrderDiffDialog, vm=make_diff_vm(), **common)
    yield "patch_preview", build(PatchPreviewDialog, vm=make_patch_vm(), **common)
    yield (
        "patch_preview_blocking",
        build(
            PatchPreviewDialog,
            vm=make_patch_vm(blocking=True, acks=(("cloud", "ui.patch.ack.cloud"),)),
            **common,
        ),
    )
    yield "profile_manager", build(ProfileManagerDialog, **common)
    yield "crash", build(CrashDialog, **common)
    yield "shortcuts", build(ShortcutsDialog, **common)


def test_each_dialog_has_tooltips_on_all_buttons(main_window, translator, fake_services, qtbot):
    for name, dialog in _dialogs(main_window, translator, fake_services):
        qtbot.addWidget(dialog)
        try:
            check_tooltips(dialog)
        except AssertionError as exc:
            pytest.fail(f"{name}: {exc}")
