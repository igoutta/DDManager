"""Translator: fallback chain, format tolerance, language switching."""

import json
from pathlib import Path

import pytest

from src.ui.i18n import Translator

I18N = Path(__file__).parents[2] / "src" / "resources" / "i18n"
BODY = "auto_detect_complete_body"  # a legacy key whose template has named placeholders
PARAMS = {
    "game_root": "G",
    "local_mods": "L",
    "workshop_mods": "W",
    "mod_text": "M",
    "save_text": "S",
    "profile_count": 3,
}


def test_english_lookup_and_format(translator):
    assert translator.tr("all_files") == "All files"
    text = translator.tr(BODY, **PARAMS)
    assert "G" in text and "{" not in text


def test_unknown_key_returns_the_key(translator):
    assert translator.tr("no.such.key") == "no.such.key"
    assert not translator.has("no.such.key")
    assert translator.has("all_files")


def test_missing_or_bad_params_return_the_raw_template(translator):
    raw = translator.tr(BODY)
    assert "{game_root}" in raw
    assert translator.tr("all_files", unused=1) == "All files"
    assert translator.tr(BODY, game_root="G") == raw


def test_other_language_translates_and_unknown_language_falls_back_to_english(qapp):
    es = Translator.from_resources("es_ES")
    assert es.tr("all_files") == "Todos los archivos"
    assert es.language() == "es_ES"
    odd = Translator.from_resources("xx_XX")
    assert odd.tr("all_files") == "All files"
    assert odd.tr("no.such.key") == "no.such.key"


def test_languages_lists_every_catalog(translator):
    assert {"en", "es_ES", "pt_PT", "zh_CN"} <= set(translator.languages())


def test_set_language_emits_and_switches(translator, qtbot):
    with qtbot.waitSignal(translator.languageChanged) as blocker:
        translator.set_language("es_ES")
    assert blocker.args == ["es_ES"]
    assert translator.language() == "es_ES"
    assert translator.tr("all_files") == "Todos los archivos"
    translator.set_language("en")
    assert translator.tr("all_files") == "All files"


def test_set_language_with_no_qt_catalog_still_works(translator):
    translator.set_language("zh_CN")  # no qtbase_zh_CN.qm needed to succeed
    assert translator.language() == "zh_CN"
    translator.set_language("en")


@pytest.mark.parametrize("lang", ["es_ES", "pt_PT", "zh_CN"])
def test_ui_keys_of_other_languages_never_invent_keys(lang):
    en = json.loads((I18N / "en.json").read_text(encoding="utf-8"))
    other = json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))
    extra = {k for k in other if k.startswith("ui.") and k not in en}
    assert not extra, sorted(extra)[:5]


def test_every_ui_key_in_english_is_non_empty():
    en = json.loads((I18N / "en.json").read_text(encoding="utf-8"))
    empty = [k for k, v in en.items() if k.startswith("ui.") and not str(v).strip()]
    assert not empty
