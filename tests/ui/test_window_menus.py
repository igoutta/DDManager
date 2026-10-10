"""View menu: checkable entries show the real indicator; each exclusive group has one choice."""

from PySide6.QtGui import QActionGroup

from src.core.load_order import PriorityDirection
from src.ui.widgets.window_actions import DENSITY_SLUGS, LANGUAGES

GROUPS = {
    "group_density": [f"density_{slug}" for slug in DENSITY_SLUGS.values()],
    "group_language": [f"lang_{code}" for code in LANGUAGES],
    "group_priority": ["prio_first", "prio_last"],
}


def checked_density(window) -> list[str]:
    hub = window.hub.actions
    return [k for k in hub if k.startswith("density_") and hub[k].isChecked()]


def test_checkable_actions_carry_no_icon_and_toolbar_actions_keep_theirs(main_window):
    checkable = [a for a in main_window.hub.actions.values() if a.isCheckable()]
    assert len(checkable) >= 10
    for action in checkable:
        assert action.icon().isNull(), action.objectName()
    for key in ("rescan", "sort", "validate", "backup", "patch", "undo", "redo"):
        assert not main_window.hub[key].icon().isNull(), key


def test_density_language_and_priority_are_exclusive_groups_with_one_choice(main_window):
    groups = {g.objectName(): g for g in main_window.findChildren(QActionGroup)}
    for name, keys in GROUPS.items():
        group = groups[name]
        assert group.isExclusive(), name
        assert [a.objectName() for a in group.actions()] == [f"act_{k}" for k in keys]
        assert sum(a.isChecked() for a in group.actions()) == 1, name


def test_every_entry_of_the_choice_submenus_is_checkable_and_iconless(main_window):
    for name in ("density", "language", "priority"):
        menu = main_window.chrome.menus[name]
        entries = [a for a in menu.actions() if not a.isSeparator()]
        assert entries, name
        for action in entries:
            assert action.isCheckable(), action.objectName()
            assert action.icon().isNull(), action.objectName()


def test_the_checked_density_follows_the_controller(rig_factory):
    rig = rig_factory(window=True)
    for mode in ("Compact", "Visual", "No Icons", "Comfortable"):
        rig.controller.set_density(mode)
        assert checked_density(rig.window) == [f"density_{DENSITY_SLUGS[mode]}"]


def test_the_checked_language_follows_the_translator(rig_factory, translator):
    rig = rig_factory(window=True)
    for code in ("es_ES", "zh_CN", "en"):
        translator.set_language(code)
        assert [c for c in LANGUAGES if rig.window.hub[f"lang_{c}"].isChecked()] == [code]


def test_the_checked_direction_follows_the_priority_setting(rig_factory):
    rig = rig_factory(window=True)
    hub = rig.window.hub
    presenter = rig.controller.settings
    presenter.set_priority(PriorityDirection.LAST_WINS, verified=True)
    assert hub["prio_last"].isChecked()
    assert not hub["prio_first"].isChecked()
    assert hub["prio_verified"].isChecked()
    presenter.set_priority(PriorityDirection.FIRST_WINS, verified=False)
    assert hub["prio_first"].isChecked()
    assert not hub["prio_last"].isChecked()
    assert not hub["prio_verified"].isChecked()
