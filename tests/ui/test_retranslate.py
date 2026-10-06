"""P24: switching the language relabels every part of the live window, and back again."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMenu

from src.ui.models.load_order_model import Col
from tests.ui.m5_support import (
    LANGUAGES,
    action_for,
    assert_no_raw_keys,
    catalog_of,
    construct,
    en_catalog,
    follow_language,
    load_attr,
    settle,
    texts_of,
)

OTHERS = tuple(code for code in LANGUAGES if code != "en")


@pytest.fixture
def rig(rig_factory):
    rig = rig_factory(window=True)
    rig.window.show()
    return rig


def has_real(language: str, key: str) -> bool:
    """The catalog of ``language`` translates ``key`` (not just a copy of the English text)."""
    return catalog_of(language).get(key, en_catalog().get(key)) != en_catalog().get(key)


@pytest.mark.parametrize("language", OTHERS)
def test_every_label_of_the_window_follows_the_language(rig, language):
    result = follow_language(rig.window, rig.translator, language)
    assert result.checked >= 40, "actions, menus, tips, pane labels and buttons are checked"
    assert result.unchanged == [], "a translated key left a label in English"


@pytest.mark.parametrize("language", OTHERS)
def test_the_window_title_uses_the_legacy_translation(rig, language):
    english = rig.window.windowTitle()
    rig.translator.set_language(language)
    assert rig.window.windowTitle() == catalog_of(language)["app_title"]
    assert rig.window.windowTitle() != english


@pytest.mark.parametrize("language", OTHERS)
def test_actions_and_their_tips_are_retranslated_with_the_shortcut_kept(rig, language):
    rig.translator.set_language(language)
    tr = rig.translator.tr
    actions = [a for a in rig.window.findChildren(QAction) if a.property("ddm_key")]
    assert len(actions) >= 30
    for action in actions:
        key = action.property("ddm_key")
        assert action.text() == tr(f"ui.action.{key}"), key
        assert tr(f"ui.action.{key}.tip") in action.toolTip(), key
        assert action.toolTip() != action.text(), key


@pytest.mark.parametrize("language", OTHERS)
def test_menu_titles_and_their_tips_follow(rig, language):
    rig.translator.set_language(language)
    tr = rig.translator.tr
    menus = rig.window.chrome.menus
    assert set(menus) >= {
        "file",
        "edit",
        "tools",
        "view",
        "density",
        "language",
        "priority",
        "help",
    }
    for menu in menus.values():
        key = str(menu.property("title_key"))
        assert menu.title() == tr(key)
        assert menu.menuAction().toolTip() == tr(f"{key}.tip")
    assert all(isinstance(m, QMenu) for m in menus.values())


@pytest.mark.parametrize("language", OTHERS)
def test_pane_titles_and_list_headers_follow(rig, language):
    rig.translator.set_language(language)
    tr = rig.translator.tr
    labels = {label.text() for label in rig.window.findChildren(QLabel)}
    assert tr("ui.available.title") in labels
    model = rig.controller.load_order_model
    for column, key in ((Col.RANK, "rank"), (Col.TITLE, "title"), (Col.SOURCE, "source")):
        header = model.headerData(
            int(column), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
        )
        assert header == tr(f"ui.lo.col.{key}")
    assert rig.window.dock.windowTitle() == tr("ui.health.title")


@pytest.mark.parametrize("language", OTHERS)
def test_rows_are_rebuilt_with_the_new_category_names_and_badges(rig, language):
    rig.translator.set_language(language)
    tr = rig.translator.tr
    row = rig.controller.rows()["chorus_class_mod"]
    assert row.category_label == tr("category_class")
    assert row.tier_badge == tr("ui.tier.cls")
    assert has_real(language, "category_class") == (row.category_label != "Class")


@pytest.mark.parametrize("language", OTHERS)
def test_the_status_bar_summary_follows(rig, language):
    rig.translator.set_language(language)
    tr = rig.translator.tr
    order = rig.controller.order()
    summary = tr("ui.status.summary", enabled=len(order.active()), total=len(order.entries))
    assert rig.window.status_bar.profile.toolTip() == tr("ui.status.profile.tip", summary=summary)


def test_switching_back_to_english_restores_every_text(rig, qtbot):
    qtbot.wait(300)  # the Available count label is debounced
    english = texts_of(rig.window)
    assert english
    for language in OTHERS:
        rig.translator.set_language(language)
        settle()
    rig.translator.set_language("en")
    settle()
    qtbot.wait(300)
    assert texts_of(rig.window) == english


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_label_ever_shows_a_raw_catalog_key(rig, language):
    rig.translator.set_language(language)
    assert_no_raw_keys(rig.window)
    for action in rig.window.findChildren(QAction):
        assert not action.text().startswith("ui."), action.property("ddm_key")


def test_a_language_without_a_catalog_falls_back_to_english(rig, qtbot):
    qtbot.wait(300)
    english = texts_of(rig.window)
    rig.translator.set_language("xx_XX")
    settle()
    qtbot.wait(300)
    assert texts_of(rig.window) == english
    assert_no_raw_keys(rig.window)


@pytest.mark.parametrize("language", OTHERS)
def test_choosing_the_language_action_switches_checks_and_persists_it(rig, language):
    action_for(rig.window, f"lang_{language}").trigger()
    assert rig.translator.language() == language
    checked = [code for code in LANGUAGES if action_for(rig.window, f"lang_{code}").isChecked()]
    assert checked == [language]
    assert rig.settings_written()["language"] == language


def test_untranslated_ui_keys_fall_back_to_english_never_to_the_key(rig):
    """While a catalog lacks a ``ui.*`` key the English text shows: no raw key, no crash."""
    en = en_catalog()
    for language in OTHERS:
        rig.translator.set_language(language)
        missing = [
            key
            for key in en
            if key.startswith("ui.") and key not in catalog_of(language) and "{" not in en[key]
        ]
        for key in missing[:50]:
            assert rig.translator.tr(key) == en[key]


@pytest.mark.parametrize("language", OTHERS)
@pytest.mark.parametrize("surface", ["window", "settings", "profile_manager"])
def test_the_generic_tooltips_of_qt_chrome_buttons_follow_the_language_too(
    rig, qtbot, surface, language
):
    """Table corners, dock buttons, tab arrows: tipped once by the window and by each dialog."""
    if surface == "window":
        root = rig.window
    else:
        module, name, extra = {
            "settings": (
                "settings_dialog",
                "SettingsDialog",
                {"presenter": rig.controller.settings},
            ),
            "profile_manager": (
                "profile_manager_dialog",
                "ProfileManagerDialog",
                {"port": rig.controller.profiles},
            ),
        }[surface]
        root = construct(
            load_attr(f"src.ui.dialogs.{module}", name),
            translator=rig.translator,
            icons=rig.window.icons,
            parent=rig.window,
            **extra,
        )
        qtbot.addWidget(root)
    result = follow_language(root, rig.translator, language, chrome=True)
    assert result.checked >= 1, f"{surface} has no generic chrome tooltip left to check"
