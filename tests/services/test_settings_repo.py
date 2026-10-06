"""SettingsRepository: defaults, round trip, tolerant parsing, unknown keys, atomic save."""

import json
import os
from pathlib import Path

import pytest

from src.core.findings import Severity
from src.core.load_order import PriorityDirection, PrioritySetting
from src.services.settings_repo import (
    PluginTrust,
    RetentionPolicy,
    Settings,
    SettingsRepository,
)

HEADER_KEYS = {"format", "format_version"}


def non_default(tmp_path: Path) -> Settings:
    return Settings(
        priority=PrioritySetting(PriorityDirection.LAST_WINS, verified=False),
        active_profile="my profile",
        selected_save=tmp_path / "Darkest" / "profile_2" / "persist.game.json",
        backups=RetentionPolicy(keep_last=5, keep_days=7, min_keep=2),
        plugins=PluginTrust(
            enabled=True, approved={"a.py": "ab" * 32}, disabled=frozenset({"b.py"})
        ),
        rules=PluginTrust(enabled=True, approved={"r.py": "cd" * 32}),
        refuse_when_game_running=False,
        language="es",
    )


def test_defaults() -> None:
    settings = Settings()
    assert settings.priority == PrioritySetting()
    assert settings.priority.direction is PriorityDirection.FIRST_WINS
    assert (settings.active_profile, settings.selected_save, settings.language) == (
        None,
        None,
        None,
    )
    assert settings.backups == RetentionPolicy(keep_last=20, keep_days=30, min_keep=3)
    assert settings.plugins == PluginTrust(enabled=False, approved={}, disabled=frozenset())
    assert settings.rules == PluginTrust()
    assert settings.refuse_when_game_running is True


def test_missing_file_gives_defaults_without_findings(tmp_path: Path) -> None:
    assert SettingsRepository(tmp_path / "settings.json").load() == (Settings(), [])


def test_round_trip(tmp_path: Path) -> None:
    repo = SettingsRepository(tmp_path / "settings.json")
    wanted = non_default(tmp_path)
    repo.save(wanted)
    loaded, findings = repo.load()
    assert findings == []
    assert loaded == wanted


def test_file_declares_its_format(tmp_path: Path) -> None:
    repo = SettingsRepository(tmp_path / "settings.json")
    repo.save(non_default(tmp_path))
    doc = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert doc["format"] == "ddmanager.settings"
    assert doc["format_version"] == 1


@pytest.mark.parametrize("content", [b"{broken", b"", b"[]", b"42", b"\xff\xfe\x00"])
def test_unreadable_file_gives_defaults_and_a_finding(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(content)
    settings, findings = SettingsRepository(path).load()
    assert settings == Settings()
    assert findings
    assert all(f.severity < Severity.ERROR for f in findings)
    assert path.read_bytes() == content


def test_bad_values_fall_back_to_defaults_with_findings(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    repo = SettingsRepository(path)
    repo.save(non_default(tmp_path))
    saved = json.loads(path.read_text("utf-8"))
    value_keys = [key for key in saved if key not in HEADER_KEYS]
    assert value_keys
    for key in value_keys:
        damaged = {**saved, key: ["not", {"valid": "x"}]}
        path.write_text(json.dumps(damaged), "utf-8")
        settings, findings = repo.load()
        assert findings, key
        assert settings != non_default(tmp_path), key


def test_all_bad_values_at_once_equal_the_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    repo = SettingsRepository(path)
    repo.save(non_default(tmp_path))
    saved = json.loads(path.read_text("utf-8"))
    damaged = {k: (v if k in HEADER_KEYS else ["bad"]) for k, v in saved.items()}
    path.write_text(json.dumps(damaged), "utf-8")
    settings, findings = repo.load()
    assert settings == Settings()
    assert len(findings) >= len(damaged) - len(HEADER_KEYS)


def test_one_bad_value_does_not_discard_the_good_ones(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    repo = SettingsRepository(path)
    wanted = non_default(tmp_path)
    repo.save(wanted)
    saved = json.loads(path.read_text("utf-8"))
    language_key = next(k for k, v in saved.items() if v == "es")
    path.write_text(json.dumps({**saved, language_key: ["bad"]}), "utf-8")
    settings, findings = repo.load()
    assert findings
    assert settings.language is None
    assert settings.priority == wanted.priority
    assert settings.backups == wanted.backups
    assert settings.plugins == wanted.plugins
    assert settings.selected_save == wanted.selected_save


def test_unknown_keys_survive_a_load_save_cycle(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    repo = SettingsRepository(path)
    repo.save(non_default(tmp_path))
    doc = json.loads(path.read_text("utf-8"))
    doc["future_feature"] = {"nested": [1, 2, 3]}
    path.write_text(json.dumps(doc), "utf-8")
    settings, findings = repo.load()
    assert findings == []
    repo.save(settings)
    assert json.loads(path.read_text("utf-8"))["future_feature"] == {"nested": [1, 2, 3]}


def test_save_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "settings.json"
    repo = SettingsRepository(path)
    repo.save(Settings(language="en"))
    before = path.read_bytes()

    def broken(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        repo.save(non_default(tmp_path))
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]
