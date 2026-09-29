"""Seeded byte flips: the LEGACY level must give the pinned validator's verdict everywhere."""

import random
import struct

import pytest

from src.core.saves import dson
from src.core.saves.format import SaveValidationReport
from tests.support.dson_builder import THREE_ENTRIES, standard_save
from tools.legacy_oracle import LegacyOracle

BASE = standard_save(THREE_ENTRIES)
DATA_OFFSET = struct.unpack_from("<i", BASE, 60)[0]
FLIPS = 2000


def _flips(seed: int, lower: int, upper: int, count: int = FLIPS) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    return [(rng.randrange(lower, upper), rng.randrange(1, 256)) for _ in range(count)]


def _mutate(*flips: tuple[int, int]) -> bytes:
    out = bytearray(BASE)
    for position, mask in flips:
        out[position] ^= mask
    return bytes(out)


# header + tables, then the data block (names, hashes and UTF-8 live there), then pairs anywhere
MUTANTS: list[tuple[str, bytes]] = [
    *((f"tables_{p}_{m:02x}", _mutate((p, m))) for p, m in _flips(20260929, 0, DATA_OFFSET)),
    *((f"data_{p}_{m:02x}", _mutate((p, m))) for p, m in _flips(20260930, DATA_OFFSET, len(BASE))),
    *(
        (f"pair_{a}_{b}", _mutate(a, b))
        for a, b in zip(
            _flips(20260931, 0, len(BASE), 300), _flips(20260932, 0, len(BASE), 300), strict=True
        )
    ),
]


@pytest.mark.legacy
def test_legacy_level_matches_the_pinned_verdict(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    mismatches: list[tuple[str, bool, tuple[str, ...]]] = []
    accepted = 0
    codes_seen: set[str] = set()
    for name, mutated in MUTANTS:
        try:
            dd2.dson_validate_editor_compatible(mutated)
        except Exception:  # noqa: BLE001 - ValueError, struct.error, IndexError... all mean reject
            legacy_ok = False
        else:
            legacy_ok = True
        accepted += legacy_ok
        report = dson.validate(mutated)
        codes_seen.update(p.code for p in report.legacy_errors)
        if report.ok != legacy_ok:
            mismatches.append((name, legacy_ok, tuple(p.code for p in report.legacy_errors)))
        if report.ok_strict:
            assert report.ok, name  # strict rejects are a superset
    assert mismatches == []
    assert 0 < accepted < len(MUTANTS)  # the sample exercises both verdicts
    # the data-side branches must stay covered: a flipped name byte hits each of these
    assert {"name_not_utf8", "hash_mismatch", "name_not_terminated"} <= codes_seen


@pytest.mark.legacy
def test_header_regions_the_legacy_ignores(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    for position in (*range(8), *range(8, 16), *range(28, 44), *range(52, 56)):
        mutated = _mutate((position, 0xFF))
        assert dd2.dson_validate_editor_compatible(mutated) is None, position
        assert dson.validate(mutated).ok, position


def test_validate_never_raises_anywhere_in_the_file() -> None:
    for position, mask in _flips(4242, 0, len(BASE)):
        report = dson.validate(_mutate((position, mask)))
        assert isinstance(report, SaveValidationReport)
        assert report.ok_strict <= report.ok


def test_strict_is_stricter_than_legacy_on_the_header() -> None:
    header_length_flip = _mutate((8, 0x01))  # header_length 64 -> 65: legacy never reads it
    report = dson.validate(header_length_flip)
    assert report.ok
    assert not report.ok_strict
    meta2_offset = struct.unpack_from("<i", BASE, 48)[0]
    bit_31 = _mutate((meta2_offset + 8 + 3, 0x80))  # meta2[0].info bit 31: masked by the legacy
    assert dson.validate(bit_31).ok
