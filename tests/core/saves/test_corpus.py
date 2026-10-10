"""The real-game corpus: ``persist.game.json`` copies under ``$DDM_SAVE_CORPUS`` (never in CI).

``just corpus-refresh`` (tools/make_corpus.py) fills ``<repo>/.corpus`` from the game's own save
folders; ``just corpus`` runs these tests against it.  This is where the codec meets the game.
"""

import os
from collections import Counter
from pathlib import Path

import pytest

from src.core.errors import DsonUnsupportedError
from src.core.ids import SaveIdentity
from src.core.saves import default_registry, dson
from src.core.saves.dson import DSON_MAGIC
from src.core.saves.dson.layout import META2_SIZE, read_tables
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
        assert report.ok, (path, report.structural_errors[:3])
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


def _variants(before: tuple[SaveIdentity, ...]) -> list[tuple[SaveIdentity, ...]]:
    """Reorder, add (one local, one Workshop entry), remove the first, and empty."""
    local, steam = SaveIdentity("Corpus Local Mod", "mod_local_source"), SaveIdentity("1", "Steam")
    added = (*before, local, steam)
    return [tuple(reversed(before)), added, before[1:], ()]


def _without_bit31(raw: bytes) -> bytes:
    """``raw`` with bit 31 cleared in every meta2 info word (the game's undocumented flag)."""
    header, _, meta2 = read_tables(raw)
    out = bytearray(raw)
    for index in range(len(meta2)):
        out[header.meta2_offset + META2_SIZE * index + 11] &= 0x7F
    return bytes(out)


def _check_round_trip(raw: bytes, out: bytes, entries: tuple[SaveIdentity, ...]) -> None:
    """Writing the original list back restores the file: byte for byte when every original entry
    survived the intermediate write (it keeps its bit-31 flags), else up to those flags, which a
    removed entry loses and comes back with clear."""
    before = FMT.read_applied(raw)
    back = FMT.write_applied(out, before)
    assert FMT.read_applied(back) == before
    survivors = list(entries)
    kept_all = all(entry in survivors and survivors.remove(entry) is None for entry in before)
    if kept_all:
        assert back == raw
    else:
        assert _without_bit31(back) == _without_bit31(raw)


def test_write_applied_round_trip_on_every_file(corpus: list[tuple[Path, bytes]]) -> None:
    """Reorder, add and remove entries on each real save: every result re-validates STRICT (never
    worse than the input), reads back the exact entries, and writing the original list back
    restores the file."""
    rewritten = 0
    for path, raw in corpus:
        has_block = dson.parse(raw).find_child(0, FMT.applied_block) is not None
        strict_before = dson.validate(raw).ok_strict
        for entries in _variants(FMT.read_applied(raw)):
            try:
                out = FMT.write_applied(raw, entries)
            except DsonUnsupportedError as exc:
                assert not has_block and exc.code == "no_anchor", (path, exc)
                break
            report = dson.validate(out)
            assert report.ok, (path, entries, report.structural_errors[:3])
            assert report.ok_strict or not strict_before, (path, entries, report.strict_errors[:3])
            assert FMT.read_applied(out) == entries, (path, entries)
            if has_block:
                _check_round_trip(raw, out, entries)
            rewritten += 1
    print(f"write_applied round trips: {rewritten} rewrites over {len(corpus)} files")
    assert rewritten > 0


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
