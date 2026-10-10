"""StateRepository: round trip, conflicts, corrupt-file policy, read-only mode, pre-upgrade copy."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.core.findings import Finding, Severity
from src.core.ids import ModId
from src.core.state_file import (
    SCHEMA_VERSION,
    STATE_KEYS,
    StateChanges,
    parse_state,
    render_state,
    render_state_json,
)
from src.services.errors import StateConflictError, StateReadOnlyError
from src.services.fsutil import FileFingerprint
from src.services.state_repo import StateRepository

FIXTURE = Path(__file__).absolute().parents[1] / "fixtures" / "mod_state_v0.json"
M = ModId


@pytest.fixture
def repo(app_paths, fixed_clock) -> StateRepository:
    return StateRepository(app_paths, default_language="en", clock=fixed_clock)


@pytest.fixture
def with_fixture(app_paths) -> Path:
    app_paths.state_file.write_bytes(FIXTURE.read_bytes())
    return app_paths.state_file


def ids(findings) -> list[str]:
    return [f.rule_id for f in findings]


def test_no_file_gives_defaults(repo: StateRepository) -> None:
    snap = repo.load()
    assert (snap.origin, snap.fingerprint, snap.writable) == ("default", None, True)
    assert snap.doc.settings.language == "en"
    assert snap.doc.order.entries == ()
    assert snap.findings == ()


def test_loading_the_fixture(repo: StateRepository, with_fixture: Path) -> None:
    snap = repo.load()
    assert (snap.origin, snap.writable) == ("main", True)
    assert snap.fingerprint == FileFingerprint.of(with_fixture)
    assert snap.findings == ()
    assert snap.doc.settings.language == "es"
    expected, _ = parse_state(json.loads(FIXTURE.read_text("utf-8")))
    assert snap.doc.order == expected.order
    assert dict(snap.doc.raw) == dict(expected.raw)


def test_round_trip_keeps_all_22_keys_unknown_keys_and_key_order(
    repo: StateRepository, with_fixture: Path
) -> None:
    original = json.loads(FIXTURE.read_text("utf-8"))
    snap = repo.load()
    changes = StateChanges(nicknames={M("2248772895"): "Choir"})
    fingerprint = repo.save(snap.doc, changes, expected=snap.fingerprint)
    written = json.loads(with_fixture.read_text("utf-8"))
    assert list(written) == [*original, "schema_version"]
    assert set(STATE_KEYS) <= set(written)
    assert written["window_geometry"] == original["window_geometry"]
    assert written["schema_version"] == SCHEMA_VERSION
    assert written["nicknames"] == {**original["nicknames"], "2248772895": "Choir"}
    for key in STATE_KEYS:
        if key not in ("nicknames", "enabled"):
            assert written[key] == snap.doc.raw[key], key
    assert fingerprint == FileFingerprint.of(with_fixture)


def test_written_bytes_are_exactly_the_rendered_json(
    repo: StateRepository, with_fixture: Path
) -> None:
    snap = repo.load()
    new_order = snap.doc.order.disable({M("2248772895")})
    changes = StateChanges(order=new_order)
    repo.save(snap.doc, changes, expected=snap.fingerprint)
    assert with_fixture.read_bytes() == render_state_json(render_state(snap.doc, changes)).encode()


def test_save_rotates_the_previous_main_into_the_backup(
    repo: StateRepository, app_paths, with_fixture: Path
) -> None:
    snap = repo.load()
    repo.save(snap.doc, StateChanges(), expected=snap.fingerprint)
    assert app_paths.state_backup_file.read_bytes() == FIXTURE.read_bytes()
    first = with_fixture.read_bytes()
    snap = repo.load()
    repo.save(snap.doc, StateChanges(nicknames={M("x"): "y"}), expected=snap.fingerprint)
    assert app_paths.state_backup_file.read_bytes() == first


def test_first_save_creates_the_file_when_expected_is_none(
    repo: StateRepository, app_paths
) -> None:
    snap = repo.load()
    repo.save(snap.doc, StateChanges(), expected=None)
    assert json.loads(app_paths.state_file.read_text("utf-8"))["schema_version"] == SCHEMA_VERSION
    assert not app_paths.state_backup_file.exists()


def test_conflict_when_the_file_changed_underneath(
    repo: StateRepository, with_fixture: Path
) -> None:
    snap = repo.load()
    with_fixture.write_text(with_fixture.read_text("utf-8").replace('"es"', '"en"'), "utf-8")
    other = with_fixture.read_bytes()
    with pytest.raises(StateConflictError) as caught:
        repo.save(snap.doc, StateChanges(), expected=snap.fingerprint)
    assert caught.value.expected == snap.fingerprint
    assert caught.value.actual == FileFingerprint.of(with_fixture)
    assert with_fixture.read_bytes() == other
    repo.save(snap.doc, StateChanges(), expected=snap.fingerprint, force=True)
    assert json.loads(with_fixture.read_text("utf-8"))["language"] == "es"


def test_conflict_when_a_file_appeared_but_none_was_expected(
    repo: StateRepository, with_fixture: Path
) -> None:
    snap = repo.load()
    with pytest.raises(StateConflictError) as caught:
        repo.save(snap.doc, StateChanges(), expected=None)
    assert caught.value.expected is None
    assert caught.value.actual == FileFingerprint.of(with_fixture)
    assert with_fixture.read_bytes() == FIXTURE.read_bytes()


def test_changed_since(repo: StateRepository, app_paths, with_fixture: Path) -> None:
    fp = repo.load().fingerprint
    assert repo.changed_since(fp) is False
    with_fixture.write_text("{}", "utf-8")
    assert repo.changed_since(fp) is True
    with_fixture.unlink()
    assert repo.changed_since(None) is False
    assert repo.changed_since(fp) is True
    with_fixture.write_text("{}", "utf-8")
    assert repo.changed_since(None) is True


def test_corrupt_main_recovers_from_backup_and_is_never_rotated_over_it(
    repo: StateRepository, app_paths
) -> None:
    good = FIXTURE.read_bytes()
    app_paths.state_backup_file.write_bytes(good)
    app_paths.state_file.write_bytes(b'{"language": "es", "order": [')
    snap = repo.load()
    assert snap.origin == "backup"
    assert "state.recovered_from_backup" in ids(snap.findings)
    assert snap.doc.settings.language == "es"
    assert app_paths.state_file.read_bytes() == b'{"language": "es", "order": ['
    repo.save(snap.doc, StateChanges(), expected=snap.fingerprint)
    assert app_paths.state_backup_file.read_bytes() == good
    assert json.loads(app_paths.state_file.read_text("utf-8"))["language"] == "es"


def test_both_files_unreadable_gives_defaults_error_and_preserves_the_corrupt_copy(
    repo: StateRepository, app_paths
) -> None:
    app_paths.state_file.write_bytes(b"\x00not json")
    app_paths.state_backup_file.write_bytes(b"also not json")
    snap = repo.load()
    assert snap.origin == "default"
    assert snap.writable is True
    unreadable = [f for f in snap.findings if f.rule_id == "state.unreadable"]
    assert [f.severity for f in unreadable] == [Severity.ERROR]
    repo.save(snap.doc, StateChanges(), expected=snap.fingerprint)
    kept = list(app_paths.data_dir.glob("mod_state.corrupt.*.json"))
    assert [p.read_bytes() for p in kept] == [b"\x00not json"]
    assert app_paths.state_backup_file.read_bytes() == b"also not json"
    assert json.loads(app_paths.state_file.read_text("utf-8"))["schema_version"] == SCHEMA_VERSION


def test_a_main_that_is_json_but_not_an_object_is_not_rotated(
    repo: StateRepository, app_paths
) -> None:
    app_paths.state_backup_file.write_bytes(FIXTURE.read_bytes())
    app_paths.state_file.write_bytes(b"[1, 2, 3]")
    snap = repo.load()
    repo.save(snap.doc, StateChanges(), expected=snap.fingerprint)
    assert app_paths.state_backup_file.read_bytes() == FIXTURE.read_bytes()


def test_error_findings_make_the_repository_read_only(
    app_paths, fixed_clock, with_fixture: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.services.state_repo as module

    real = module.parse_state

    def failing(obj: object, *, default_language: str = "en"):
        doc, findings = real(obj, default_language=default_language)
        return doc, [*findings, Finding.error("state.test_error", "forced for the test")]

    monkeypatch.setattr(module, "parse_state", failing)
    repo = StateRepository(app_paths, default_language="en", clock=fixed_clock)
    snap = repo.load()
    assert snap.writable is False
    assert "state.test_error" in ids(snap.findings)
    before = with_fixture.read_bytes()
    with pytest.raises(StateReadOnlyError) as caught:
        repo.save(snap.doc, StateChanges(), expected=snap.fingerprint)
    assert "reason" in caught.value.details
    assert with_fixture.read_bytes() == before
    assert not app_paths.state_backup_file.exists()


def test_failed_write_leaves_the_state_file_untouched(
    repo: StateRepository, app_paths, with_fixture: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = repo.load()

    def broken(*_a: Any, **_k: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        repo.save(snap.doc, StateChanges(order=snap.doc.order.disable({M("2248772895")})),
                  expected=snap.fingerprint)  # fmt: skip
    assert with_fixture.read_bytes() == FIXTURE.read_bytes()
    assert not [p for p in app_paths.data_dir.iterdir() if p.name.endswith(".tmp")]


def test_pre_upgrade_copy_is_made_once(
    repo: StateRepository, app_paths, with_fixture: Path
) -> None:
    assert repo.ensure_pre_upgrade_copy() is True
    assert app_paths.pre_upgrade_state_file.read_bytes() == FIXTURE.read_bytes()
    with_fixture.write_text("{}", "utf-8")
    assert repo.ensure_pre_upgrade_copy() is False
    assert app_paths.pre_upgrade_state_file.read_bytes() == FIXTURE.read_bytes()


def test_pre_upgrade_copy_needs_a_main_file(repo: StateRepository, app_paths) -> None:
    assert repo.ensure_pre_upgrade_copy() is False
    assert not app_paths.pre_upgrade_state_file.exists()


def test_read_language_prefers_main_then_backup_then_none(repo: StateRepository, app_paths) -> None:
    assert repo.read_language() is None
    app_paths.state_backup_file.write_text(json.dumps({"language": "fr"}), "utf-8")
    assert repo.read_language() == "fr"
    app_paths.state_file.write_text(json.dumps({"language": "es"}), "utf-8")
    assert repo.read_language() == "es"
    app_paths.state_file.write_text("{broken", "utf-8")
    assert repo.read_language() == "fr"
    app_paths.state_file.write_text(json.dumps({"order": []}), "utf-8")
    assert repo.read_language() == "fr"
    app_paths.state_backup_file.write_text("[]", "utf-8")
    assert repo.read_language() is None
