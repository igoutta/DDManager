"""P13 (file paths editor) and P14 (Auto Detect, first-run summary): the five legacy path keys."""

from pathlib import Path

import pytest

from src.services.detection import ManualPaths
from tests.ui.m5_support import (
    action_for,
    assert_no_raw_keys,
    construct,
    follow_language,
    load_attr,
)

KEYS = (
    "manual_game_root",
    "mods_path",
    "manual_local_mods_path",
    "manual_workshop_mods_path",
    "selected_profile_path",
)


@pytest.fixture
def folders(tmp_path):
    """Real folders and saves (names without digits, so a profile count stays unambiguous)."""
    names = {
        "game": tmp_path / "Darkest Dungeon",
        "mods": tmp_path / "Darkest Dungeon" / "mods",
        "local": tmp_path / "Darkest Dungeon" / "localmods",
        "workshop": tmp_path / "steam" / "workshop" / "content",
    }
    for path in names.values():
        path.mkdir(parents=True)
    saves = [tmp_path / name / "persist.game.json" for name in ("alpha", "beta", "gamma", "delta")]
    for save in saves:
        save.parent.mkdir()
        save.write_bytes(b"x")
    return {**names, "saves": saves}


@pytest.fixture
def rig(rig_factory, folders):
    rig = rig_factory(
        window=True,
        extra={
            "manual_game_root": str(folders["game"]),
            "mods_path": str(folders["mods"]),
            "manual_local_mods_path": str(folders["local"]),
            "manual_workshop_mods_path": str(folders["workshop"]),
            "selected_profile_path": str(folders["saves"][0]),
            "last_save_path": str(folders["saves"][0]),
        },
    )
    rig.services.detector.set_snapshot(
        game_roots=(folders["game"],),
        local_mod_dirs=(folders["local"],),
        workshop_dirs=(folders["workshop"],),
        primary_mods_dir=folders["mods"],
        save_files=tuple(folders["saves"]),
    )
    return rig


@pytest.fixture
def open_dialog(rig, qtbot):
    def make():
        dialog = construct(
            load_attr("src.ui.dialogs.paths_dialog", "PathsDialog"),
            presenter=rig.controller.paths,
            translator=rig.translator,
            icons=rig.window.icons,
            parent=rig.window,
        )
        qtbot.addWidget(dialog)
        dialog.show()
        return dialog

    return make


def same(a: str, b: object) -> bool:
    return (not a and not b) or Path(a) == Path(str(b))


# ---------------------------------------------------------------------------- the editor (P13)


def test_the_editor_has_the_five_legacy_keys_in_legacy_order(rig, open_dialog):
    dialog = open_dialog()
    assert tuple(dialog.rows) == KEYS
    for row in dialog.rows.values():
        assert set(row.buttons) == {"browse", "auto", "clear"}


def test_the_fields_start_from_the_saved_values(rig, open_dialog, folders):
    dialog = open_dialog()
    wanted = {
        "manual_game_root": folders["game"],
        "mods_path": folders["mods"],
        "manual_local_mods_path": folders["local"],
        "manual_workshop_mods_path": folders["workshop"],
        "selected_profile_path": folders["saves"][0],
    }
    assert {k: Path(v) for k, v in dialog.values().items()} == wanted


def test_a_blank_override_shows_the_path_in_use(rig_factory, folders, qtbot):
    rig = rig_factory(
        window=True,
        extra={
            "manual_game_root": "",
            "manual_local_mods_path": "",
            "manual_workshop_mods_path": "",
            "selected_profile_path": "",
            "mods_path": str(folders["mods"]),
        },
    )
    rig.services.detector.set_snapshot(
        game_roots=(folders["game"],),
        local_mod_dirs=(folders["local"],),
        workshop_dirs=(folders["workshop"],),
        primary_mods_dir=folders["mods"],
        save_files=tuple(folders["saves"]),
    )
    rig.controller.rescan()
    dialog = construct(
        load_attr("src.ui.dialogs.paths_dialog", "PathsDialog"),
        presenter=rig.controller.paths,
        translator=rig.translator,
        icons=rig.window.icons,
        parent=rig.window,
    )
    qtbot.addWidget(dialog)
    values = dialog.values()
    assert Path(values["manual_game_root"]) == folders["game"]
    assert Path(values["manual_local_mods_path"]) == folders["local"]
    assert Path(values["manual_workshop_mods_path"]) == folders["workshop"]


def test_clear_empties_only_its_own_field(rig, open_dialog):
    dialog = open_dialog()
    before = dialog.values()
    dialog.rows["manual_local_mods_path"].buttons["clear"].click()
    after = dialog.values()
    assert after["manual_local_mods_path"] == ""
    assert {k: v for k, v in after.items() if k != "manual_local_mods_path"} == {
        k: v for k, v in before.items() if k != "manual_local_mods_path"
    }


def test_auto_fills_each_field_from_a_fresh_detection_without_manual_overrides(
    rig, open_dialog, folders
):
    dialog = open_dialog()
    for row in dialog.rows.values():
        row.edit.setText("C:/typed/by/hand")
    wanted = {
        "manual_game_root": folders["game"],
        "mods_path": folders["mods"],
        "manual_local_mods_path": folders["local"],
        "manual_workshop_mods_path": folders["workshop"],
        "selected_profile_path": folders["saves"][0],  # the newest detected save
    }
    for key, row in dialog.rows.items():
        row.buttons["auto"].click()
        assert Path(row.edit.text()) == wanted[key], key
    assert rig.services.detector.last_manual == ManualPaths(), "Auto ignores the manual overrides"


def test_auto_with_nothing_detected_blanks_the_field(rig, open_dialog):
    rig.services.detector.set_snapshot(game_roots=(), save_files=())
    dialog = open_dialog()
    dialog.rows["manual_game_root"].buttons["auto"].click()
    dialog.rows["selected_profile_path"].buttons["auto"].click()
    assert dialog.rows["manual_game_root"].edit.text() == ""
    assert dialog.rows["selected_profile_path"].edit.text() == ""


def test_browse_picks_a_folder_starting_near_the_current_value(rig, open_dialog, tmp_path):
    picked = tmp_path / "elsewhere"
    rig.prompter.answers["pick_folder"] = picked
    dialog = open_dialog()
    dialog.rows["manual_game_root"].buttons["browse"].click()
    (args, _kwargs) = rig.prompter.calls_named("pick_folder")[-1]
    assert Path(args[0]) == Path(dialog.rows["manual_game_root"].entry.value)
    assert Path(dialog.rows["manual_game_root"].edit.text()) == picked
    assert Path(dialog.rows["mods_path"].edit.text()) != picked


def test_browse_for_the_profile_asks_for_a_save_file(rig, open_dialog, folders, tmp_path):
    chosen = tmp_path / "omega" / "persist.game.json"
    rig.prompter.answers["pick_save_file"] = chosen
    dialog = open_dialog()
    dialog.rows["selected_profile_path"].buttons["browse"].click()
    assert rig.prompter.calls_named("pick_folder") == []
    (args, _kwargs) = rig.prompter.calls_named("pick_save_file")[-1]
    assert Path(args[0]) == folders["saves"][0].parent
    assert Path(dialog.rows["selected_profile_path"].edit.text()) == chosen


def test_cancelling_browse_keeps_the_field(rig, open_dialog):
    rig.prompter.answers["pick_folder"] = None
    dialog = open_dialog()
    before = dialog.values()
    dialog.rows["mods_path"].buttons["browse"].click()
    assert dialog.values() == before


def test_every_text_of_the_editor_is_in_the_catalog(rig, open_dialog):
    assert_no_raw_keys(open_dialog())


@pytest.mark.parametrize("language", ["es_ES", "pt_PT", "zh_CN"])
def test_the_editor_follows_the_language_live(rig, open_dialog, language):
    dialog = open_dialog()
    dialog.rows["mods_path"].edit.setText("C:/typed/by/hand")
    result = follow_language(dialog, rig.translator, language)
    assert result.changed >= 14, "title, 2 captions, 15 row buttons and 2 footer buttons"
    assert dialog.rows["mods_path"].edit.text() == "C:/typed/by/hand"


# ---------------------------------------------------------------------------- Save / Cancel


def test_save_writes_the_five_keys_and_the_last_save_then_rescans_with_them(
    rig, open_dialog, tmp_path
):
    dialog = open_dialog()
    new = {
        "manual_game_root": tmp_path / "g2",
        "mods_path": tmp_path / "m2",
        "manual_local_mods_path": tmp_path / "l2",
        "manual_workshop_mods_path": tmp_path / "w2",
        "selected_profile_path": tmp_path / "s2" / "persist.game.json",
    }
    for key, path in new.items():
        dialog.rows[key].edit.setText(f"  {path}  ")
    scans = rig.services.scanner.calls
    dialog.save_button.click()
    written = rig.state.settings_written()
    assert {k: Path(written[k]) for k in KEYS} == new
    assert Path(written["last_save_path"]) == new["selected_profile_path"]
    assert rig.services.scanner.calls == scans + 1
    assert rig.services.detector.last_manual.game_root == new["manual_game_root"]
    assert rig.services.detector.last_manual.local_mods == new["manual_local_mods_path"]
    assert rig.services.detector.last_manual.workshop_mods == new["manual_workshop_mods_path"]


def test_save_with_blank_fields_clears_the_overrides(rig, open_dialog):
    dialog = open_dialog()
    for row in dialog.rows.values():
        row.edit.setText("")
    dialog.save_button.click()
    written = rig.state.settings_written()
    assert {k: written[k] for k in KEYS} == dict.fromkeys(KEYS, "")
    assert "last_save_path" not in written, "no profile: the last save stays as it was"


def test_save_says_what_it_stored(rig, open_dialog, folders):
    dialog = open_dialog()
    dialog.save_button.click()
    assert rig.messages.only("status_manual_paths_profile").params == {
        "path": str(folders["saves"][0])
    }
    rig.messages.clear()
    dialog = open_dialog()
    dialog.rows["selected_profile_path"].edit.setText("")
    dialog.save_button.click()
    assert rig.messages.only("status_manual_paths_mods").params == {"path": str(folders["mods"])}
    rig.messages.clear()
    dialog = open_dialog()
    for row in dialog.rows.values():
        row.edit.setText("")
    dialog.save_button.click()
    assert rig.messages.only("status_manual_paths").params == {}


def test_cancel_writes_nothing_and_does_not_rescan(rig, open_dialog):
    dialog = open_dialog()
    for row in dialog.rows.values():
        row.edit.setText("C:/typed/by/hand")
    scans = rig.services.scanner.calls
    dialog.cancel_button.click()
    assert rig.state.settings_written() == {}
    assert rig.services.scanner.calls == scans
    assert rig.messages.log == []


def test_the_window_action_opens_the_editor(rig, folders):
    def script(dialog):
        dialog.rows["mods_path"].edit.setText(str(folders["local"]))
        dialog.save_button.click()

    rig.driver.on("PathsDialog", script)
    action_for(rig.window, "paths").trigger()
    assert rig.driver.names() == ["PathsDialog"]
    assert Path(rig.state.settings_written()["mods_path"]) == folders["local"]


# ---------------------------------------------------------------------------- Auto Detect (P14)


def summary_params(rig, folders, *, game=True, local=True, workshop=True, save=True):
    tr = rig.translator.tr
    return {
        "game_root": str(folders["game"]) if game else tr("not_found"),
        "local_mods": str(folders["local"]) if local else tr("not_found"),
        "workshop_mods": str(folders["workshop"]) if workshop else tr("not_found"),
        "mod_text": str(folders["mods"]),
        "save_text": str(folders["saves"][0]) if save else tr("no_save_file_found"),
        "profile_count": len(folders["saves"]) if save else 0,
    }


def test_auto_detect_adopts_the_best_mods_folder_and_newest_save_and_shows_the_summary(
    rig, folders, tmp_path
):
    rig.controller.apply_settings({"mods_path": str(tmp_path / "stale")})
    scans = rig.services.scanner.calls
    action_for(rig.window, "auto_detect").trigger()
    written = rig.state.settings_written()
    assert Path(written["mods_path"]) == folders["mods"]
    assert Path(written["last_save_path"]) == folders["saves"][0]
    assert rig.services.scanner.calls == scans + 1
    summary = rig.messages.only("auto_detect_complete_body")
    assert summary.params == summary_params(rig, folders)
    for fragment in ("game_root", "local_mods", "workshop_mods", "mod_text", "save_text"):
        assert summary.params[fragment] in summary.text
    assert str(len(folders["saves"])) in summary.text


def test_auto_detect_uses_the_manual_overrides_for_detection(rig, folders):
    action_for(rig.window, "auto_detect").trigger()
    manual = rig.services.detector.last_manual
    assert manual.game_root == folders["game"]
    assert manual.local_mods == folders["local"]
    assert manual.workshop_mods == folders["workshop"]


def test_auto_detect_with_nothing_found_explains_and_changes_nothing(rig):
    rig.services.detector.set_snapshot(
        game_roots=(), local_mod_dirs=(), workshop_dirs=(), primary_mods_dir=None, save_files=()
    )
    scans = rig.services.scanner.calls
    rig.messages.clear()
    action_for(rig.window, "auto_detect").trigger()
    assert rig.messages.keys() == ["auto_detect_nothing_found_body"]
    assert rig.state.settings_written() == {}
    assert rig.services.scanner.calls == scans


def test_auto_detect_with_only_a_save_adopts_the_save_and_does_not_rescan(rig, folders):
    rig.services.detector.set_snapshot(
        game_roots=(), local_mod_dirs=(), workshop_dirs=(), primary_mods_dir=None
    )
    scans = rig.services.scanner.calls
    action_for(rig.window, "auto_detect").trigger()
    written = rig.state.settings_written()
    assert "mods_path" not in written
    assert Path(written["last_save_path"]) == folders["saves"][0]
    assert rig.services.scanner.calls == scans
    params = rig.messages.only("auto_detect_complete_body").params
    assert params["game_root"] == rig.translator.tr("not_found")
    assert params["mod_text"] == rig.translator.tr("no_mod_folder_found")


def test_auto_detect_with_only_mods_says_no_save_was_found(rig, folders):
    rig.services.detector.set_snapshot(save_files=())
    action_for(rig.window, "auto_detect").trigger()
    written = rig.state.settings_written()
    assert Path(written["mods_path"]) == folders["mods"]
    assert "last_save_path" not in written
    params = rig.messages.only("auto_detect_complete_body").params
    assert params["save_text"] == rig.translator.tr("no_save_file_found")
    assert params["profile_count"] == 0


# ---------------------------------------------------------------------------- first run (P14)


def test_a_valid_mods_folder_starts_silently(rig_factory, folders):
    rig = rig_factory(extra={"mods_path": str(folders["mods"]), "first_run_summary_shown": True})
    assert rig.messages.log == []
    assert rig.settings_written() == {}


def test_without_a_mods_folder_the_first_run_detects_one_and_shows_the_summary_once(
    rig_factory, folders
):
    rig = rig_factory(
        start=False,
        extra={"mods_path": "", "first_run_summary_shown": False, "selected_profile_path": ""},
    )
    rig.services.detector.set_snapshot(
        primary_mods_dir=folders["mods"], save_files=tuple(folders["saves"])
    )
    rig.controller.start()
    first = rig.messages.only("ui.notice.first_run")
    assert first.params == {
        "mods": len(rig.services.catalog),
        "saves": len(folders["saves"]),
        "folder": str(folders["mods"]),
    }
    written = rig.settings_written()
    assert Path(written["mods_path"]) == folders["mods"]
    assert written["first_run_summary_shown"] is True
    rig.messages.clear()
    rig.controller.rescan()
    assert rig.messages.with_key("ui.notice.first_run") == [], "the summary is shown only once"


def test_no_install_found_on_first_run_points_to_the_paths_editor(rig_factory):
    rig = rig_factory(start=False, extra={"mods_path": "", "first_run_summary_shown": False})
    rig.services.detector.set_snapshot(primary_mods_dir=None, local_mod_dirs=(), save_files=())
    rig.controller.start()
    assert rig.messages.with_key("ui.notice.no_mods_folder")[0].level == "warning"
