"""The write_applied matrix against committed goldens: frozen outputs of this program.

The goldens pin the bytes ``write_applied`` produces for every cell of
tests/support/parity_matrix.py; real game-written saves are covered by the corpus check
(tests/core/saves/test_corpus.py).
Regenerate with ``just regen-goldens`` (tools/regen_goldens.py, ``--update`` to accept a change)
only when the matrix or the builder changes on purpose; the input digest recorded per case detects
accidental drift.
"""

import hashlib
import json
from pathlib import Path

import pytest

from src.core.saves import dson
from src.core.saves.dson_v1 import DsonV1Format
from tests.support import parity_matrix as pm
from tests.support.identities import identities

GOLDEN_DIR = Path(__file__).absolute().parents[3] / "tests" / "golden" / "dson"
CASES_FILE = GOLDEN_DIR / "cases.json"
FMT = DsonV1Format()


def _load_cases() -> list[dict[str, object]]:
    """The committed manifest; its absence is a regression, never a reason to skip."""
    if not CASES_FILE.is_file():
        pytest.fail(
            f"{CASES_FILE} is missing: the goldens are the frozen byte-level contract of"
            " write_applied; restore them from git or run tools/regen_goldens.py",
            pytrace=False,
        )
    document = json.loads(CASES_FILE.read_text("utf-8"))
    cases = document["cases"]
    assert isinstance(cases, list)
    assert cases, f"{CASES_FILE} holds no cases"
    return cases


CASES = _load_cases()


def test_manifest_is_committed_and_names_the_writer() -> None:
    document = json.loads(CASES_FILE.read_text("utf-8"))
    assert document["generator"] == "tools/regen_goldens.py"
    assert document["writer"] == "src.core.saves.dson_v1.DsonV1Format.write_applied"
    assert document["builder"] == "tests/support/dson_builder.py standard_save"
    assert len(CASES) == len(pm.CASES)


def _key(case: dict[str, object]) -> tuple[int | None, int]:
    existing = case["existing"]
    new_count = case["new_count"]
    assert existing is None or isinstance(existing, int)
    assert isinstance(new_count, int)
    return existing, new_count


def test_goldens_cover_the_whole_matrix() -> None:
    assert sorted((_key(c) for c in CASES), key=str) == sorted(pm.CASES, key=str)
    assert len({c["id"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[str(c["id"]) for c in CASES])
def test_write_applied_matches_golden(case: dict[str, object]) -> None:
    n, m = _key(case)
    raw = pm.build_input(n)
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == case["input_sha256"], "builder output drifted: regenerate the goldens"
    entries = pm.new_entries(m)
    output = case["output"]
    assert isinstance(output, str)
    expected = (GOLDEN_DIR / output).read_bytes()
    assert hashlib.sha256(expected).hexdigest() == case["output_sha256"]
    got = FMT.write_applied(raw, identities(entries))
    assert got == expected
    assert FMT.read_applied(got) == identities(entries)
    assert dson.validate(got).ok_strict
