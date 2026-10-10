"""Real-world check against the user's own mod_state.json (opt-in, never in CI).

DDM_STATE_CORPUS=<path to a real mod_state.json>   required
DDM_MODS_ROOT=<the mods folder it was written for>  enables the scan checks

``just corpus-refresh`` (tools/make_corpus.py) fills ``<repo>/.corpus`` and ``just corpus`` sets
both variables from it (tools/corpus_env.py).
"""

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.core.ids import SourceKind
from src.core.state_file import (
    StateChanges,
    parse_state,
    render_state,
    render_state_json,
)
from src.plugins import BUILTIN_SOURCES
from src.services.detection import InstallDetector, ManualPaths
from src.services.environment import Environment
from src.services.ports import FixedClock
from src.services.scan import ScanService
from src.services.steam_locations import path_key
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
    paths = original.get("mod_paths", {})  # type: ignore[call-overload]
    # mod_paths may still name mods that were uninstalled since the state was written (the app
    # never prunes); only folders that exist today must be discovered.
    known = {key for key, path in paths.items() if Path(str(path)).is_dir()}
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


@pytest.mark.skipif(not MODS_ROOT, reason="set DDM_MODS_ROOT to scan the real mods folder")
def test_full_scan_identities_match_the_saved_metadata_per_kind(original) -> None:
    """The app's own detection around DDM_MODS_ROOT (Workshop and local roots alike) is scanned in
    full; every scanned mod the state holds a metadata identity for must resolve to exactly that
    identity, and both kinds must have been compared when the state knows mods of that kind."""
    doc, _ = parse_state(original)
    install = InstallDetector(Environment.from_host()).detect(ManualPaths(), Path(MODS_ROOT))
    assert path_key(Path(MODS_ROOT)) in {path_key(root) for root in install.mod_roots}
    clock = FixedClock(datetime.now(UTC).astimezone())
    result = ScanService(BUILTIN_SOURCES, clock=clock).scan(install)
    assert result.mods
    compared: Counter[SourceKind] = Counter()
    mismatches: list[str] = []
    for mod, info in result.mods.items():
        expected = doc.metadata_identities.get(mod)
        if expected is None:
            continue
        compared[info.kind] += 1
        if info.save_identity != expected:
            mismatches.append(f"{mod}: scanned {info.save_identity}, state {expected}")
    assert mismatches == []
    known_kinds = {result.mods[mod].kind for mod in doc.metadata_identities if mod in result.mods}
    assert known_kinds <= set(compared)
    assert sum(compared.values()) > 0
    print(f"identities compared: {dict(compared)} over {len(result.mods)} scanned mods")
