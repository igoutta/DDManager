"""P24: the four catalogs carry the same keys and placeholders; every tooltip holds in each."""

import json
import string
from pathlib import Path

import pytest
from PySide6.QtGui import QAction

from src.core.ids import ModId
from src.core.saves.applied_text import render_applied_text
from tests.support.identities import identities
from tests.ui.m5_support import LANGUAGES, construct, load_attr
from tests.ui.test_tooltips import check_tooltips

I18N = Path(__file__).parents[2] / "src" / "resources" / "i18n"
GOLDEN = Path(__file__).parents[1] / "golden" / "i18n" / "legacy_keys.json"
OTHERS = tuple(code for code in LANGUAGES if code != "en")


def read(language):
    """The catalog with a hard failure on a duplicate key (``json`` would silently keep one)."""
    seen: list[str] = []

    def pairs(items):
        seen.extend(key for key, _ in items)
        return dict(items)

    data = json.loads(
        (I18N / f"{language}.json").read_text(encoding="utf-8"), object_pairs_hook=pairs
    )
    assert len(seen) == len(set(seen)), (
        f"{language}.json repeats keys: {sorted({k for k in seen if seen.count(k) > 1})}"
    )
    return data


def placeholders(template):
    return {
        name.split(".")[0].split("[")[0]
        for _, name, _, _ in string.Formatter().parse(template)
        if name is not None
    }


@pytest.fixture(scope="module")
def catalogs():
    return {language: read(language) for language in LANGUAGES}


# ---------------------------------------------------------------------------- keys


@pytest.mark.parametrize("language", OTHERS)
def test_the_key_set_equals_the_english_key_set(catalogs, language):
    en, other = set(catalogs["en"]), set(catalogs[language])
    assert sorted(en - other) == [], f"{language}.json lacks keys of en.json"
    assert sorted(other - en) == [], f"{language}.json has keys en.json does not"


def test_there_are_ui_keys_and_the_legacy_ones_are_untouched(catalogs):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["keys"]
    assert len(golden) == 115
    for language in LANGUAGES:
        catalog = catalogs[language]
        assert set(golden) <= set(catalog), language
        assert any(key.startswith("ui.") for key in catalog), f"{language}.json has no ui.* keys"
        assert not [k for k in golden if k.startswith("ui.")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_value_is_a_non_empty_string(catalogs, language):
    bad = [k for k, v in catalogs[language].items() if not isinstance(v, str) or not v.strip()]
    assert bad == []


# ---------------------------------------------------------------------------- placeholders


@pytest.mark.parametrize("language", OTHERS)
def test_every_key_has_exactly_the_english_placeholders(catalogs, language):
    wrong = {
        key: (sorted(placeholders(catalogs["en"][key])), sorted(placeholders(text)))
        for key, text in catalogs[language].items()
        if key in catalogs["en"] and placeholders(text) != placeholders(catalogs["en"][key])
    }
    assert wrong == {}, f"{language}.json changes placeholders: {wrong}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_template_parses_and_formats_with_its_own_placeholders(catalogs, language):
    broken = {}
    for key, text in catalogs[language].items():
        try:
            text.format(**dict.fromkeys(placeholders(text), "x"))
        except (ValueError, IndexError, KeyError) as exc:
            broken[key] = repr(exc)
    assert broken == {}


# ---------------------------------------------------------------------------- the files


@pytest.mark.parametrize("language", LANGUAGES)
def test_keys_are_sorted_and_the_file_is_crlf_utf8_without_bom(language):
    raw = (I18N / f"{language}.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\r\n") == raw.count(b"\n"), "mixed or LF line endings"
    assert raw.endswith(b"}\r\n")
    keys = list(read(language))
    assert keys == sorted(keys)


@pytest.mark.parametrize("language", OTHERS)
def test_ui_texts_are_translated_not_copied_from_english(catalogs, language):
    ui = [k for k in catalogs["en"] if k.startswith("ui.")]
    same = [k for k in ui if catalogs[language].get(k) == catalogs["en"][k]]
    assert len(same) <= len(ui) // 2, f"{language}.json copies {len(same)} of {len(ui)} ui texts"


# ---------------------------------------------------------------------------- tooltips


def tr_in(translator, language):
    translator.set_language(language)
    return translator


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_action_and_button_of_the_window_has_a_tooltip_in_each_language(
    main_window, translator, language
):
    tr_in(translator, language)
    assert check_tooltips(main_window) >= 12


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_window_action_has_its_text_and_tip_in_each_catalog(main_window, catalogs, language):
    keys = {
        a.property("ddm_key") for a in main_window.findChildren(QAction) if a.property("ddm_key")
    }
    assert len(keys) >= 30
    missing = [
        k
        for k in sorted(keys)
        for suffix in ("", ".tip")
        if f"ui.action.{k}{suffix}" not in catalogs[language]
    ]
    assert missing == []


@pytest.fixture
def every_m5_dialog(rig_factory, qtbot, tmp_path):
    """One instance of every M5 dialog, built over the same live rig."""
    rig = rig_factory(window=True)
    window, c = rig.window, rig.controller
    common = {
        "translator": rig.translator,
        "icons": window.icons,
        "parent": window,
    }
    dto = "src.ui.presenters.tools_dto"
    nickname_vm = c.labels.nickname_vm(ModId("chorus_class_mod"))
    entries = identities([("123", "Steam")])

    def build(module, name, **extra):
        dialog = construct(load_attr(f"src.ui.dialogs.{module}", name), **common, **extra)
        qtbot.addWidget(dialog)
        return dialog

    dialogs = {
        "categories": build("categories_dialog", "CategoriesDialog", presenter=c.categories),
        "paths": build("paths_dialog", "PathsDialog", presenter=c.paths),
        "settings": build("settings_dialog", "SettingsDialog", presenter=c.settings),
        "nickname": build("nickname_dialog", "NicknameDialog", vm=nickname_vm),
        "approval": build(
            "plugin_approval_dialog", "PluginApprovalDialog", presenter=c.settings.trust
        ),
        "save_code": build(
            "save_code_dialog",
            "SaveCodeDialog",
            vm=load_attr(dto, "SaveCodeVM")(render_applied_text(entries), 1),
        ),
        "diagnostics": build(
            "diagnostics_dialog",
            "DiagnosticsDialog",
            vm=load_attr(dto, "DiagnosticsVM")("a: 1", ("a: 1",)),
        ),
        "apply_order": build(
            "apply_order_dialog",
            "ApplyOrderDialog",
            vm=load_attr(dto, "RenamePreviewVM")(
                (load_attr(dto, "RenameRowVM")(ModId("a"), "A", "a", "0001_a"),)
            ),
        ),
        "profiles": build("profile_manager_dialog", "ProfileManagerDialog", port=c.profiles),
    }
    return rig, dialogs


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_button_of_every_m5_dialog_has_a_tooltip_in_each_language(every_m5_dialog, language):
    rig, dialogs = every_m5_dialog
    rig.translator.set_language(language)
    for name, dialog in dialogs.items():
        try:
            assert check_tooltips(dialog) >= 1, name
        except AssertionError as exc:
            pytest.fail(f"{name} in {language}: {exc}")
