"""The probe kit writes two local mods laid out as docs/load-order-semantics.md expects."""

import json
from pathlib import Path

import pytest

from tools import probe_kit


def test_write_kit_lays_out_two_local_mods(tmp_path: Path) -> None:
    written = probe_kit.write_kit(tmp_path)
    assert [path.name for path in written] == ["ddm_probe_a", "ddm_probe_b"]
    for mod_dir, amount in zip(written, (4, 8), strict=True):
        assert f"({amount} recruits)" in (mod_dir / "project.xml").read_text("utf-8")
        building = json.loads((mod_dir / probe_kit.REL_TARGET).read_text("utf-8"))
        store = building["data"]["stores"][0]["data"]
        assert store["number_of_recruits_upgrades"][0] == {"amount": amount}
        assert probe_kit.REL_TARGET in (mod_dir / "modfiles.txt").read_text("utf-8")
    unlisted = written[1] / "localization" / "ddm_probe_unlisted.string_table.xml"
    assert unlisted.is_file()
    assert "localization" not in (written[1] / "modfiles.txt").read_text("utf-8")


def test_main_writes_into_the_given_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe_kit.main([str(tmp_path)]) == 0
    assert (tmp_path / "ddm_probe_a" / "project.xml").is_file()
    assert "load-order-semantics" in capsys.readouterr().out


def test_main_defaults_to_the_detected_mods_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe_kit, "default_dest", lambda: tmp_path / "mods")
    assert probe_kit.main([""]) == 0  # the just recipe passes an empty string when no dest is given
    assert (tmp_path / "mods" / "ddm_probe_b" / "modfiles.txt").is_file()


def test_main_fails_cleanly_without_an_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(probe_kit, "default_dest", lambda: None)
    assert probe_kit.main([]) == 2
    assert "No Darkest Dungeon install" in capsys.readouterr().err
