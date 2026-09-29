"""Maintainer-local corpus: real persist.game*.json copies under $DDM_SAVE_CORPUS (never in CI)."""

import os
from collections import Counter
from pathlib import Path

import pytest

from src.core.saves import default_registry, dson
from src.core.saves.dson import DSON_MAGIC
from src.core.saves.dson_v1 import DsonV1Format


def corpus_files() -> list[Path]:
    root = os.environ.get("DDM_SAVE_CORPUS")
    if not root:
        return []
    return sorted(p for p in Path(root).rglob("*.json") if p.is_file())


FILES = corpus_files()
pytestmark = [
    pytest.mark.corpus,
    pytest.mark.skipif(not FILES, reason="DDM_SAVE_CORPUS is unset or holds no *.json files"),
]
FMT = DsonV1Format()


@pytest.fixture(scope="module")
def corpus() -> list[tuple[Path, bytes]]:
    return [(path, path.read_bytes()) for path in FILES]


def test_every_file_is_detected_and_carries_the_magic(corpus: list[tuple[Path, bytes]]) -> None:
    registry = default_registry()
    for path, raw in corpus:
        assert registry.detect(raw).format_id == "dson.v1", path
        assert raw[:4] == DSON_MAGIC, (path, raw[:4].hex())


def test_strict_pass_rate(corpus: list[tuple[Path, bytes]]) -> None:
    strict_ok = 0
    failures: list[str] = []
    for path, raw in corpus:
        report = dson.validate(raw)
        assert report.ok, (path, report.legacy_errors[:3])
        strict_ok += report.ok_strict
        failures.extend(
            f"{path.name}: {p.code}@{p.offset} {p.message}" for p in report.strict_errors
        )
    print(f"strict pass rate: {strict_ok}/{len(corpus)}")
    for line in failures[:40]:
        print(line)


def test_rewrite_identity_for_every_file(corpus: list[tuple[Path, bytes]]) -> None:
    with_block = 0
    for path, raw in corpus:
        doc = dson.parse(raw)
        assert dson.serialize(doc) == raw, path
        if doc.find_child(0, FMT.applied_block) is None:
            continue
        with_block += 1
        assert FMT.write_applied(raw, FMT.read_applied(raw)) == raw, path
    print(f"rewrite identity: {with_block} files with an applied block, {len(corpus)} total")


def test_payload_size_histogram_after_persistent_ugcs(corpus: list[tuple[Path, bytes]]) -> None:
    """Aligned payload sizes (what _assert_shift_safe classifies by) and non-zero padding."""
    sizes: Counter[int] = Counter()
    unsafe: list[str] = []
    for path, raw in corpus:
        doc = dson.parse(raw)
        anchor = doc.find_child(0, FMT.anchor_block)
        if anchor is None:
            continue
        for i in range(anchor, len(doc.meta2)):
            entry = doc.meta2[i]
            if entry.is_object:
                continue
            start = entry.offset + entry.name_length
            end = doc.field_end(i)
            payload, payload_start, _ = dson.payload_layout(doc.data, entry, end)
            size = end - start if end - start == 1 else len(payload)
            sizes[size] += 1
            if size in (0, 2, 3) or any(doc.data[start:payload_start]):
                unsafe.append(f"{path.name}: {doc.name_of(i)} region={end - start} payload={size}")
    print("aligned payload sizes after persistent_ugcs:")
    for size, count in sorted(sizes.items()):
        print(f"  {size:>6} bytes: {count}")
    for line in unsafe[:40]:
        print("  unsafe-realign candidate:", line)
