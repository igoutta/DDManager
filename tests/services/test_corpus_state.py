"""Real-world check against a user's own mod_state.json (opt-in, never in CI).

DDM_STATE_CORPUS=<path to a real mod_state.json>   required
DDM_MODS_ROOT=<the mods folder it was written for>  enables the scan checks
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.core.legacy_state import (
    StateChanges,
    parse_state,
    render_state,
    render_state_json,
)
from src.plugins import BUILTIN_SOURCES
from src.services.ports import FixedClock
from src.services.scan import ScanService
from tests.services.helpers import make_install

STATE = os.environ.get("DDM_STATE_CORPUS", "")
MODS_ROOT = os.environ.get("DDM_MODS_ROOT", "")

pytestmark = [
    pytest.mark.corpus,
    pytest.mark.skipif(not STATE, reason="set DDM_STATE_CORPUS to a real mod_state.json"),
]


@pytest.fixture(scope="module")
def original() -> dict[str, object]:
    return json.loads(Path(STATE).read_text("utf-8"))


def test_parse_then_render_is_stable_and_keeps_every_original_key(original) -> None:
    doc, _ = parse_state(original)
    rendered = render_state(doc, StateChanges())
    assert set(original) <= set(rendered)
    kept = [key for key in rendered if key in original]
    assert kept == list(original)
    again, _ = parse_state(json.loads(render_state_json(rendered)))
    assert render_state(again, StateChanges()) == rendered
    assert render_state_json(render_state(again, StateChanges())) == render_state_json(rendered)


def test_the_load_order_survives_the_round_trip(original) -> None:
    doc, _ = parse_state(original)
    rendered = render_state(doc, StateChanges())
    reparsed, findings = parse_state(json.loads(render_state_json(rendered)))
    assert findings == []
    assert reparsed.order == doc.order


@pytest.mark.skipif(not MODS_ROOT, reason="set DDM_MODS_ROOT to scan the real mods folder")
def test_scan_discovers_every_mod_the_state_knows_paths_for(original) -> None:
    clock = FixedClock(datetime.now(UTC).astimezone())
    result = ScanService(BUILTIN_SOURCES, clock=clock).scan(make_install([Path(MODS_ROOT)]))
    known = set(original.get("mod_paths", {}))  # type: ignore[call-overload]
    assert known - set(result.mods) == set()


@pytest.mark.skipif(not MODS_ROOT, reason="set DDM_MODS_ROOT to scan the real mods folder")
def test_scanned_identity_equals_the_saved_metadata_identity(original) -> None:
    doc, _ = parse_state(original)
    clock = FixedClock(datetime.now(UTC).astimezone())
    result = ScanService(BUILTIN_SOURCES, clock=clock).scan(make_install([Path(MODS_ROOT)]))
    compared = 0
    for mod, expected in doc.metadata_identities.items():
        if mod in result.mods:
            assert result.mods[mod].save_identity == expected, mod
            compared += 1
    assert compared > 0
