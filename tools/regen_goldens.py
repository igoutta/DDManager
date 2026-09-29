"""Regenerate tests/golden/dson from the pinned legacy oracle (dev only, never in CI).

Every cell of the write_applied parity matrix (tests/support/parity_matrix.py) is built with the
independent test builder and patched with the pinned ``dd2.dson_patch_mod_list_resize``. The
expected bytes land in ``case_NN.bin`` and ``cases.json`` records the inputs, digests and any
legacy error, so tests/core/saves/test_goldens.py can prove byte parity without dd2.py.
"""

import hashlib
import json
from pathlib import Path

from tests.support import parity_matrix as pm
from tools.legacy_oracle import LEGACY_COMMIT, LegacyOracle, extract

ROOT = Path(__file__).absolute().parent.parent
GOLDEN_DIR = ROOT / "tests" / "golden" / "dson"


def regenerate() -> list[dict[str, object]]:
    oracle = LegacyOracle(extract())
    dd2 = oracle.module("dd2")
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for stale in GOLDEN_DIR.glob("case_*.bin"):
        stale.unlink()
    cases: list[dict[str, object]] = []
    for index, (n, m) in enumerate(pm.CASES):
        raw = pm.build_input(n)
        entries = pm.new_entries(m)
        keys, table = pm.stub_identities(entries)
        case_name = f"case_{index:02d}"
        record: dict[str, object] = {
            "id": case_name,
            "matrix_id": pm.case_id(n, m),
            "existing": n,
            "new_count": m,
            "existing_entries": pm.existing_entries(n),
            "new_entries": entries,
            "input_size": len(raw),
            "input_sha256": hashlib.sha256(raw).hexdigest(),
            "output": None,
            "output_sha256": None,
            "legacy_error": None,
        }
        try:
            patched, count = dd2.dson_patch_mod_list_resize(raw, keys, oracle.stub_manager(table))
        except Exception as exc:  # noqa: BLE001 - the legacy raises plain ValueError/IndexError
            record["legacy_error"] = f"{type(exc).__name__}: {exc}"
        else:
            if count != m:
                raise RuntimeError(f"{case_name}: legacy wrote {count} entries, expected {m}")
            (GOLDEN_DIR / f"{case_name}.bin").write_bytes(patched)
            record["output"] = f"{case_name}.bin"
            record["output_sha256"] = hashlib.sha256(patched).hexdigest()
        cases.append(record)
    document = {
        "legacy_commit": LEGACY_COMMIT,
        "legacy_function": "dd2.dson_patch_mod_list_resize",
        "generator": "tools/regen_goldens.py",
        "builder": "tests/support/dson_builder.py standard_save",
        "cases": cases,
    }
    (GOLDEN_DIR / "cases.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    return cases


def main() -> int:
    cases = regenerate()
    written = sum(1 for case in cases if case["output"] is not None)
    print(f"{len(cases)} cases, {written} golden files, {len(cases) - written} legacy errors")
    for case in cases:
        if case["legacy_error"] is not None:
            print(f"  {case['id']} ({case['matrix_id']}): {case['legacy_error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
