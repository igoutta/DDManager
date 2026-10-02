"""Regenerate tests/golden/* from the pinned legacy oracle (dev only, never in CI).

Golden sets (``python tools/regen_goldens.py [dson] [identity] [classify]``, all when no argument):

* ``dson``: every cell of the write_applied parity matrix (tests/support/parity_matrix.py) is
  built with the independent test builder and patched with the pinned
  ``dd2.dson_patch_mod_list_resize``. The expected bytes land in ``case_NN.bin`` and
  ``cases.json`` records the inputs, digests and any legacy error, so
  tests/core/saves/test_goldens.py can prove byte parity without dd2.py.
* ``identity``: the synthetic mod folders of tests/support/mod_facts.py run through
  ``dd2.ModManager.read_mod_metadata`` and the display/sort/duplicate helpers (``cases.json``),
  plus tables for the pure helpers over seeded corpora (``helpers.json``).
* ``classify``: ``categories.auto_category_scores`` / ``suggested_category_for_mod`` over every
  ``modding/*`` sample and every synthetic folder (``cases.json``).
"""

import hashlib
import json
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType
from typing import Any

from tests.support import mod_facts as mf
from tests.support import parity_matrix as pm
from tools.legacy_oracle import LEGACY_COMMIT, LegacyOracle, extract

ROOT = Path(__file__).absolute().parent.parent
GOLDEN_DIR = ROOT / "tests" / "golden" / "dson"
IDENTITY_DIR = ROOT / "tests" / "golden" / "identity"
CLASSIFY_DIR = ROOT / "tests" / "golden" / "classify"
MODDING_DIR = ROOT / "modding"


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", "utf-8")


# ----------------------------------------------------------------- dson


def regenerate(oracle: LegacyOracle | None = None) -> list[dict[str, object]]:
    oracle = LegacyOracle(extract()) if oracle is None else oracle
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


def _report_dson(cases: list[dict[str, object]]) -> None:
    written = sum(1 for case in cases if case["output"] is not None)
    print(f"dson: {len(cases)} cases, {written} golden files, {len(cases) - written} legacy errors")
    for case in cases:
        if case["legacy_error"] is not None:
            print(f"  {case['id']} ({case['matrix_id']}): {case['legacy_error']}")


# ----------------------------------------------------------------- identity


def _helper_tables(dd2: ModuleType) -> dict[str, Any]:
    """Pure-helper goldens: the oracle's answers over the seeded/fixed corpora of mod_facts."""
    seed, count = 2024, 2000
    manager = dd2.ModManager
    version_rows = []
    for major, minor in mf.VERSION_CASES:
        root = ET.fromstring(
            f"<p><VersionMajor>{major}</VersionMajor><VersionMinor>{minor}</VersionMinor></p>"
        )
        version_rows.append([major, minor, manager.version_label_from_project(None, root)])
    return {
        "normalize_mod_identity": {
            "seed": seed,
            "count": count,
            "pairs": [
                [text, dd2.normalize_mod_identity(text)] for text in mf.identity_corpus(seed, count)
            ],
        },
        "titles": [
            {
                "text": text,
                "has_latin": bool(dd2.text_has_latin(text)),
                "numeric": bool(dd2.looks_like_numeric_id(text)),
                "bad": bool(dd2.is_bad_display_title(text)),
            }
            for text in mf.TITLE_CORPUS
        ],
        "version_label": version_rows,
        "black_reliquary": [
            {"tags": list(tags), "tagged": bool(manager.is_black_reliquary_tagged(None, tags))}
            for tags in mf.BLACK_RELIQUARY_CASES
        ],
        "save_name": [[folder, manager.save_name(None, folder)] for folder in mf.SAVE_NAME_CASES],
    }


def _identity_case(oracle: LegacyOracle, spec: mf.ModDirSpec, folder: Path) -> dict[str, Any]:
    dd2 = oracle.module("dd2")
    categories = oracle.module("categories")
    manager = mf.legacy_manager(dd2, {spec.folder: folder}, acf=dict(spec.acf))
    return {
        "id": spec.id,
        "folder": spec.folder,
        "spec_digest": spec.digest(),
        "record": mf.legacy_record(manager, categories, dd2, spec.folder),
        "nicknames": {
            nick: mf.legacy_nickname_record(manager, spec.folder, nick) for nick in spec.nicknames
        },
    }


def regenerate_identity(oracle: LegacyOracle) -> int:
    base = Path(tempfile.mkdtemp(prefix="ddm-identity-"))
    dirs = mf.materialize_all(base)
    cases = [_identity_case(oracle, spec, dirs[spec.id]) for spec in mf.CASES]
    header = {
        "legacy_commit": LEGACY_COMMIT,
        "generator": "tools/regen_goldens.py regenerate_identity",
        "builder": "tests/support/mod_facts.py CASES",
    }
    _write_json(IDENTITY_DIR / "cases.json", {**header, "cases": cases})
    helpers = _helper_tables(oracle.module("dd2"))
    _write_json(IDENTITY_DIR / "helpers.json", {**header, **helpers})
    return len(cases)


# ----------------------------------------------------------------- classify


def _classify(oracle: LegacyOracle, manager: Any, mod: str) -> dict[str, Any]:
    categories = oracle.module("categories")
    dd2 = oracle.module("dd2")
    manager.current_metadata_for_mod(mod)
    args = (
        manager.state,
        mod,
        manager.mod_folder_path,
        manager.save_name,
        manager.display_name,
        dd2.parse_xml_file_forgiving,
    )
    return {
        "scores": categories.auto_category_scores(*args),
        "suggestion": categories.suggested_category_for_mod(*args),
    }


def _classify_samples(oracle: LegacyOracle) -> dict[str, Any]:
    dd2 = oracle.module("dd2")
    folders = {p.name: p for p in MODDING_DIR.iterdir() if p.is_dir()}
    manager = mf.legacy_manager(dd2, folders)
    return {
        name: {"digest": mf.sample_digest(folder), **_classify(oracle, manager, name)}
        for name, folder in sorted(folders.items())
    }


def _classify_synthetic(oracle: LegacyOracle, spec: mf.ModDirSpec, folder: Path) -> dict[str, Any]:
    dd2 = oracle.module("dd2")
    manager = mf.legacy_manager(dd2, {spec.folder: folder}, acf=dict(spec.acf))
    result = {
        "spec_digest": spec.digest(),
        **_classify(oracle, manager, spec.folder),
        "nicknames": {},
    }
    for nickname in spec.nicknames:
        manager.state["nicknames"][spec.folder] = nickname
        result["nicknames"][nickname] = _classify(oracle, manager, spec.folder)
    manager.state["nicknames"].pop(spec.folder, None)
    return result


def regenerate_classify(oracle: LegacyOracle) -> int:
    base = Path(tempfile.mkdtemp(prefix="ddm-classify-"))
    dirs = mf.materialize_all(base)
    samples = _classify_samples(oracle)
    synthetic = {spec.id: _classify_synthetic(oracle, spec, dirs[spec.id]) for spec in mf.CASES}
    _write_json(
        CLASSIFY_DIR / "cases.json",
        {
            "legacy_commit": LEGACY_COMMIT,
            "generator": "tools/regen_goldens.py regenerate_classify",
            "samples": samples,
            "synthetic": synthetic,
        },
    )
    return len(samples) + len(synthetic)


# ----------------------------------------------------------------- entry point

SETS = ("dson", "identity", "classify")


def main(argv: list[str] | None = None) -> int:
    chosen = SETS if not argv else tuple(argv)
    unknown = [name for name in chosen if name not in SETS]
    if unknown:
        print(f"unknown golden set(s): {', '.join(unknown)}; choose from {', '.join(SETS)}")
        return 2
    oracle = LegacyOracle(extract())
    if "dson" in chosen:
        _report_dson(regenerate(oracle))
    if "identity" in chosen:
        print(f"identity: {regenerate_identity(oracle)} cases + helper tables")
    if "classify" in chosen:
        print(f"classify: {regenerate_classify(oracle)} mods")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
