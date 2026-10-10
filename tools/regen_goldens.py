"""Regenerate tests/golden/* from THIS program (dev only, never in CI).

The goldens are frozen outputs of DD Manager itself; the corpus check (``just corpus``) is what
validates the codec against real game-written saves.  Regenerating is therefore a diff of our
own behaviour against what was frozen: a golden whose content changes is reported and REFUSED
unless ``--update`` is passed.  New golden files are always written.

    python tools/regen_goldens.py [--update] [dson] [identity] [classify]

* ``dson``: every cell of tests/support/parity_matrix.py is built with the independent test
  builder and rewritten with ``DsonV1Format.write_applied``; the bytes land in ``case_NN.bin``
  and ``cases.json`` records the inputs and digests (tests/core/saves/test_goldens.py).
* ``identity``: the synthetic mod folders of tests/support/mod_facts.py through
  ``derive_mod_info`` and the display/sort/duplicate helpers (``cases.json``), plus tables for
  the pure text helpers over seeded corpora (``helpers.json``).
* ``classify``: ``category_scores`` / ``suggest_category`` over every ``modding/*`` sample and
  every synthetic folder (``cases.json``).
"""

import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.core.classify import category_scores, suggest_category
from src.core.identity import (
    derive_mod_info,
    is_bad_display_title,
    looks_like_numeric_id,
    normalize_mod_identity,
    strip_numeric_prefix,
    text_has_latin,
)
from src.core.model import ModInfo
from src.core.project_xml import is_black_reliquary_tagged, version_label
from src.core.saves.dson_v1 import DsonV1Format
from tests.support import mod_facts as mf
from tests.support import parity_matrix as pm
from tests.support.identities import identities

ROOT = Path(__file__).absolute().parent.parent
GOLDEN_DIR = ROOT / "tests" / "golden" / "dson"
IDENTITY_DIR = ROOT / "tests" / "golden" / "identity"
CLASSIFY_DIR = ROOT / "tests" / "golden" / "classify"
MODDING_DIR = ROOT / "modding"
GENERATOR = "tools/regen_goldens.py"
CASES_JSON = "cases.json"
SETS = ("dson", "identity", "classify")


class Writer:
    """Collects the regenerated files and applies the refuse-unless-updated policy."""

    def __init__(self, *, update: bool) -> None:
        self.update = update
        self.written: list[Path] = []
        self.refused: list[Path] = []
        self.unchanged: list[Path] = []

    def put(self, path: Path, data: bytes) -> None:
        if path.is_file():
            old = path.read_bytes()
            if old == data:
                self.unchanged.append(path)
                return
            print(f"CHANGED {path.relative_to(ROOT).as_posix()}: {_summary(path, old, data)}")
            if not self.update:
                self.refused.append(path)
                return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.written.append(path)

    def put_json(self, path: Path, document: dict[str, Any]) -> None:
        """JSON with CRLF line endings, the convention of the committed golden manifests."""
        text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        self.put(path, text.replace("\n", "\r\n").encode("utf-8"))


def _summary(path: Path, old: bytes, new: bytes) -> str:
    if path.suffix != ".json":
        return f"{len(old)} -> {len(new)} bytes, sha256 {_sha(old)[:12]} -> {_sha(new)[:12]}"
    try:
        before, after = json.loads(old), json.loads(new)
    except ValueError:
        return "unparseable JSON on one side"
    if not isinstance(before, dict) or not isinstance(after, dict):
        return "document shape changed"
    keys = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    return "differing keys: " + ", ".join(keys)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------- dson


def regenerate_dson(writer: Writer) -> int:
    fmt = DsonV1Format()
    cases: list[dict[str, object]] = []
    for index, (n, m) in enumerate(pm.CASES):
        raw = pm.build_input(n)
        entries = pm.new_entries(m)
        case_name = f"case_{index:02d}"
        patched = fmt.write_applied(raw, identities(entries))
        if fmt.read_applied(patched) != identities(entries):
            raise RuntimeError(f"{case_name}: the written entries do not read back")
        writer.put(GOLDEN_DIR / f"{case_name}.bin", patched)
        cases.append(
            {
                "id": case_name,
                "matrix_id": pm.case_id(n, m),
                "existing": n,
                "new_count": m,
                "existing_entries": pm.existing_entries(n),
                "new_entries": entries,
                "input_size": len(raw),
                "input_sha256": _sha(raw),
                "output": f"{case_name}.bin",
                "output_sha256": _sha(patched),
            }
        )
    document = {
        "generator": GENERATOR,
        "writer": "src.core.saves.dson_v1.DsonV1Format.write_applied",
        "builder": "tests/support/dson_builder.py standard_save",
        "cases": cases,
    }
    writer.put_json(GOLDEN_DIR / CASES_JSON, document)
    return len(cases)


# ----------------------------------------------------------------- identity


def _local_tz():
    zone = datetime.now(UTC).astimezone().tzinfo
    if zone is None:
        raise RuntimeError("no local time zone")
    return zone


def _info(folder: Path, acf: dict[str, str] | None = None) -> ModInfo:
    return derive_mod_info(mf.snapshot_from_dir(folder, acf=acf), tz=_local_tz())


def _helper_tables() -> dict[str, Any]:
    """Tables for the pure text helpers over the seeded and fixed corpora of mod_facts."""
    seed, count = 2024, 2000
    return {
        "normalize_mod_identity": {
            "seed": seed,
            "count": count,
            "pairs": [
                [text, normalize_mod_identity(text)] for text in mf.identity_corpus(seed, count)
            ],
        },
        "titles": [
            {
                "text": text,
                "has_latin": text_has_latin(text),
                "numeric": looks_like_numeric_id(text),
                "bad": is_bad_display_title(text),
            }
            for text in mf.TITLE_CORPUS
        ],
        "version_label": [
            [major, minor, version_label(major, minor)] for major, minor in mf.VERSION_CASES
        ],
        "black_reliquary": [
            {"tags": list(tags), "tagged": is_black_reliquary_tagged(tags)}
            for tags in mf.BLACK_RELIQUARY_CASES
        ],
        "save_name": [[folder, strip_numeric_prefix(folder)] for folder in mf.SAVE_NAME_CASES],
    }


def _identity_case(spec: mf.ModDirSpec, folder: Path) -> dict[str, Any]:
    info = _info(folder, dict(spec.acf))
    return {
        "id": spec.id,
        "folder": spec.folder,
        "spec_digest": spec.digest(),
        "record": mf.identity_record(info),
        "nicknames": {nick: mf.nickname_record(info, nick) for nick in spec.nicknames},
    }


def regenerate_identity(writer: Writer) -> int:
    base = Path(tempfile.mkdtemp(prefix="ddm-identity-"))
    dirs = mf.materialize_all(base)
    cases = [_identity_case(spec, dirs[spec.id]) for spec in mf.CASES]
    header = {
        "generator": f"{GENERATOR} regenerate_identity",
        "builder": "tests/support/mod_facts.py CASES",
    }
    writer.put_json(IDENTITY_DIR / CASES_JSON, {**header, "cases": cases})
    writer.put_json(IDENTITY_DIR / "helpers.json", {**header, **_helper_tables()})
    return len(cases)


# ----------------------------------------------------------------- classify


def _classify(info: ModInfo, nickname: str | None = None) -> dict[str, Any]:
    return {
        "scores": category_scores(info, nickname=nickname),
        "suggestion": suggest_category(info, nickname=nickname),
    }


def _classify_samples() -> dict[str, Any]:
    folders = {p.name: p for p in MODDING_DIR.iterdir() if p.is_dir()}
    return {
        name: {"digest": mf.sample_digest(folder), **_classify(_info(folder))}
        for name, folder in sorted(folders.items())
    }


def _classify_synthetic(spec: mf.ModDirSpec, folder: Path) -> dict[str, Any]:
    info = _info(folder, dict(spec.acf))
    return {
        "spec_digest": spec.digest(),
        **_classify(info),
        "nicknames": {nickname: _classify(info, nickname) for nickname in spec.nicknames},
    }


def regenerate_classify(writer: Writer) -> int:
    base = Path(tempfile.mkdtemp(prefix="ddm-classify-"))
    dirs = mf.materialize_all(base)
    samples = _classify_samples()
    synthetic = {spec.id: _classify_synthetic(spec, dirs[spec.id]) for spec in mf.CASES}
    document = {
        "generator": f"{GENERATOR} regenerate_classify",
        "samples": samples,
        "synthetic": synthetic,
    }
    writer.put_json(CLASSIFY_DIR / CASES_JSON, document)
    return len(samples) + len(synthetic)


# ----------------------------------------------------------------- entry point


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    update = "--update" in args
    chosen = tuple(a for a in args if a != "--update") or SETS
    unknown = [name for name in chosen if name not in SETS]
    if unknown:
        print(f"unknown golden set(s): {', '.join(unknown)}; choose from {', '.join(SETS)}")
        return 2
    writer = Writer(update=update)
    if "dson" in chosen:
        print(f"dson: {regenerate_dson(writer)} cases")
    if "identity" in chosen:
        print(f"identity: {regenerate_identity(writer)} cases + helper tables")
    if "classify" in chosen:
        print(f"classify: {regenerate_classify(writer)} mods")
    print(
        f"{len(writer.unchanged)} unchanged, {len(writer.written)} written,"
        f" {len(writer.refused)} refused"
    )
    if writer.refused:
        print("goldens are frozen outputs of this program: pass --update to accept the changes")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
