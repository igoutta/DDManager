"""The ddmanager CLI over a hermetic world: fake linux host, tmp data dir, tmp mods."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.cli import main
from src.core.ids import SaveIdentity
from src.core.saves import DsonV1Format
from src.services.environment import Environment
from src.services.profiles import ProfileRepository
from tests.support.dson_builder import THREE_ENTRIES, standard_save

LOCAL = "mod_local_source"
ERROR_LINE = re.compile(r"^\[[a-z0-9_.]+\] \S", re.MULTILINE)
ACK_UNKNOWN = ["--ack", "game_state_unknown"]


@dataclass
class World:
    data: Path
    mods: Path
    save: Path
    raw: bytes

    def run(self, *args: str) -> int:
        return main(["--data-dir", str(self.data), *args])

    @property
    def wanted(self) -> tuple[SaveIdentity, ...]:
        return (SaveIdentity("Bravo Mod", LOCAL), SaveIdentity("Alpha Mod", LOCAL))


@pytest.fixture
def world(tmp_path: Path, mod_dir, fake_env, monkeypatch: pytest.MonkeyPatch) -> World:
    host: Environment = fake_env("linux", home=tmp_path / "home")
    monkeypatch.setattr(Environment, "from_host", classmethod(lambda cls: host))
    data = tmp_path / "data"
    data.mkdir()
    mods = tmp_path / "mods"
    for folder, title in (("alpha", "Alpha Mod"), ("bravo", "Bravo Mod"), ("charlie", "Charlie")):
        mod_dir(mods, folder, title=title)
    state = {
        "mods_path": str(mods),
        "order": ["bravo", "alpha", "charlie"],
        "enabled": {"bravo": True, "alpha": True, "charlie": False},
    }
    (data / "mod_state.json").write_text(json.dumps(state), "utf-8")
    raw = standard_save(THREE_ENTRIES)
    save = tmp_path / "Darkest" / "profile_0" / "persist.game.json"
    save.parent.mkdir(parents=True)
    save.write_bytes(raw)
    return World(data, mods, save, raw)


def mod_ids(doc: dict[str, Any]) -> list[str]:
    mods = doc["mods"]
    if isinstance(mods, dict):
        return list(mods)
    return [str(m.get("id") or m.get("key")) for m in mods]


# ------------------------------------------------------------------ scan


def test_scan_json_lists_mods_and_findings(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert world.run("scan", "--json") == 0
    doc = json.loads(capsys.readouterr().out)
    assert isinstance(doc, dict)
    assert {"mods", "findings"} <= set(doc)
    assert sorted(mod_ids(doc)) == ["alpha", "bravo", "charlie"]
    assert isinstance(doc["findings"], list)
    assert (world.data / "mod_state.json").exists()


def test_scan_text_mentions_every_mod(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    assert world.run("scan") == 0
    out = capsys.readouterr().out
    for title in ("Alpha Mod", "Bravo Mod", "Charlie"):
        assert title in out


# ------------------------------------------------------- save plan / patch / backup / restore


def test_plan_emit_is_byte_identical_to_write_applied(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "plan.bin"
    assert world.run("save", "plan", str(world.save), "--emit", str(out)) == 0
    assert out.read_bytes() == DsonV1Format().write_applied(world.raw, world.wanted)
    assert world.save.read_bytes() == world.raw
    printed = capsys.readouterr().out
    assert "Bravo Mod" in printed
    assert not list((world.data / "backups").rglob("*.json"))


def test_plan_without_emit_prints_and_writes_nothing(world: World, tmp_path: Path) -> None:
    assert world.run("save", "plan", str(world.save)) == 0
    assert world.save.read_bytes() == world.raw
    assert sorted(p.name for p in world.save.parent.iterdir()) == ["persist.game.json"]


def test_patch_applies_the_state_order_with_a_backup(world: World) -> None:
    assert world.run("save", "patch", str(world.save), *ACK_UNKNOWN) == 0
    assert world.save.read_bytes() == DsonV1Format().write_applied(world.raw, world.wanted)
    backups = list((world.data / "backups").rglob("persist.game.backup.*.json"))
    assert [p.read_bytes() for p in backups] == [world.raw]


def test_patch_of_a_steam_cloud_save_needs_the_acknowledgement(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cloud = tmp_path / "Steam" / "userdata" / "1" / "262060" / "remote" / "persist.game.json"
    cloud.parent.mkdir(parents=True)
    cloud.write_bytes(world.raw)
    assert world.run("save", "patch", str(cloud), *ACK_UNKNOWN) == 1
    assert ERROR_LINE.search(capsys.readouterr().err)
    assert cloud.read_bytes() == world.raw
    assert world.run("save", "patch", str(cloud), *ACK_UNKNOWN, "--ack", "steam_cloud") == 0
    assert cloud.read_bytes() == DsonV1Format().write_applied(world.raw, world.wanted)


def test_backup_then_restore_default_is_the_latest(world: World) -> None:
    assert world.run("save", "backup", str(world.save)) == 0
    (backup,) = (world.data / "backups").rglob("persist.game.backup.*.json")
    assert backup.read_bytes() == world.raw
    assert world.run("save", "patch", str(world.save), *ACK_UNKNOWN) == 0
    assert world.save.read_bytes() != world.raw
    assert world.run("save", "restore", str(world.save)) == 0
    assert world.save.read_bytes() == world.raw


def test_restore_from_a_chosen_backup(world: World) -> None:
    assert world.run("save", "backup", str(world.save)) == 0
    (backup,) = (world.data / "backups").rglob("persist.game.backup.*.json")
    world.save.write_bytes(standard_save([]))
    assert world.run("save", "restore", str(world.save), "--from", str(backup)) == 0
    assert world.save.read_bytes() == world.raw


# ------------------------------------------------------------------ profiles


def test_profile_export_import_list_and_apply(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from src.core.load_order import PrioritySetting
    from src.core.loadorder_file import GAME, LoadOrderDocument, LoadOrderEntry

    entries = tuple(
        LoadOrderEntry(SaveIdentity(title, LOCAL), enabled, title, folder, None, None)
        for folder, title, enabled in (
            ("alpha", "Alpha Mod", True),
            ("charlie", "Charlie", True),
            ("bravo", "Bravo Mod", False),
        )
    )
    doc = LoadOrderDocument("Night Run", GAME, PrioritySetting(), "tests", None, "", entries)
    ProfileRepository(world.data / "profiles").save(doc)
    assert world.run("profile", "list") == 0
    assert "Night Run" in capsys.readouterr().out
    dest = tmp_path / "exported.json"
    assert world.run("profile", "export", "Night Run", str(dest)) == 0
    assert json.loads(dest.read_text("utf-8"))["format"] == "ddmanager.loadorder"
    assert world.run("profile", "apply", "Night Run") == 0
    state = json.loads((world.data / "mod_state.json").read_text("utf-8"))
    assert state["order"][:3] == ["alpha", "charlie", "bravo"]
    assert state["enabled"] == {"alpha": True, "charlie": True, "bravo": False}


def test_profile_import_of_a_legacy_loadout(world: World, tmp_path: Path) -> None:
    legacy = {"order": ["alpha", "bravo"], "enabled": {"alpha": True, "bravo": False}}
    source = tmp_path / "dd_mod_loadout.json"
    source.write_text(json.dumps(legacy), "utf-8")
    assert world.run("profile", "import", str(source)) == 0
    assert ProfileRepository(world.data / "profiles").list()


def test_profile_apply_of_an_unknown_profile_is_a_user_error(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    before = (world.data / "mod_state.json").read_bytes()
    assert world.run("profile", "apply", "Nope") == 1
    assert capsys.readouterr().err.strip()
    assert (world.data / "mod_state.json").read_bytes() == before


# ------------------------------------------------------------------ diagnostics and exit codes


def test_diagnostics_prints_a_report(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    assert world.run("diagnostics") == 0
    assert capsys.readouterr().out.strip()


def test_typed_errors_print_code_and_message_and_exit_1(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nowhere" / "persist.game.json"
    assert world.run("save", "plan", str(missing)) == 1
    assert ERROR_LINE.search(capsys.readouterr().err)
    assert world.run("save", "restore", str(world.save)) == 1
    assert ERROR_LINE.search(capsys.readouterr().err)
    assert world.save.read_bytes() == world.raw


def test_usage_errors_exit_2(world: World) -> None:
    for argv in (["frobnicate"], ["save"], ["save", "plan"], ["profile", "export", "only-one"]):
        with pytest.raises(SystemExit) as caught:
            world.run(*argv)
        assert caught.value.code == 2, argv
