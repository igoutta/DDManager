"""Differential tests of the verbatim ports against the pinned legacy dd2 functions."""

import random
import string

import pytest

from src.core.saves import dson
from src.core.saves.dson_v1 import DsonV1Format
from tests.core.saves.test_dson import STRICT_ONLY
from tests.support import parity_matrix as pm
from tests.support.dson_builder import (
    THREE_ENTRIES,
    build_save,
    sample_variants,
    standard_root,
    standard_save,
)
from tests.support.identities import identities
from tests.support.mutations import info_bit31_indices, or_object_infos, set_info_bit31
from tools.legacy_oracle import LegacyOracle

pytestmark = pytest.mark.legacy

CJK = "测试模组字"
ALPHABET = string.ascii_letters + string.digits + string.punctuation + " " + CJK
ALPHABET += "éèüß\U0001f525\U0001f409"
FMT = DsonV1Format()

# spare bits of an object's info word: bit 1 sits between is_object and the name length, bit 31
# above the meta1 index; neither is read by the format (dd2.py:669, 734, 741)
SPARE_INFO_BITS = {"clean": 0, "bit_1": 0x2, "bit_31": 0x80000000, "bits_1_and_31": 0x80000002}


def _random_name(rng: random.Random, max_len: int = 40) -> str:
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, max_len)))


def test_string_hash_and_field_info_parity_over_5000_names(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    rng = random.Random(20260929)
    non_ascii = 0
    for _ in range(5000):
        name = _random_name(rng)
        non_ascii += not name.isascii()
        assert dson.string_hash(name) == dd2.dson_string_hash(name)
        assert dson.field_info(name) == dd2.dson_field_info(name)
        index = rng.randrange(0, 0x100000)
        assert dson.field_info(name, index) == dd2.dson_field_info(name, index)
    assert non_ascii > 1000
    assert dson.string_hash("applied_ugcs_1_0") == dd2.dson_string_hash("applied_ugcs_1_0")


def test_set_object_index_in_info_parity_including_bit_31(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    rng = random.Random(1234)
    negatives = 0
    for _ in range(5000):
        info = rng.randrange(-(2**31), 2**31)
        negatives += info < 0
        index = rng.randrange(0, 0x100000)
        got = dson.set_object_index_in_info(info, index)
        assert got == dd2.dson_set_object_index_in_info(info, index)
        assert (got < 0) == (info < 0)  # bit 31 is kept
    assert negatives > 1000


def test_build_string_field_parity(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    rng = random.Random(99)
    for _ in range(1000):
        field_name = rng.choice(["name", "source", "estatename", _random_name(rng, 12)])
        value = _random_name(rng, 60) if rng.random() < 0.9 else ""
        offset = rng.randrange(0, 4096)
        expected, _meta2 = dd2.dson_build_string_field(field_name, value, offset)
        assert dson.build_string_field(field_name, value, offset) == expected


def test_rebuild_field_block_parity(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    raw = build_save(standard_root(THREE_ENTRIES), pad_byte=0x00)
    doc = dson.parse(raw)
    for i, entry in enumerate(doc.meta2):
        legacy_entry = {"hash": entry.hash, "offset": entry.offset, "info": entry.info}
        for new_offset in range(9):
            expected = dd2.dson_rebuild_existing_field_block(
                doc.data, legacy_entry, doc.field_end(i), new_offset
            )
            assert (
                dson.rebuild_field_block(doc.data, entry, doc.field_end(i), new_offset) == expected
            )


@pytest.mark.parametrize("bits", sorted(SPARE_INFO_BITS), ids=sorted(SPARE_INFO_BITS))
@pytest.mark.parametrize("value", ["A", "AB", "ABC", "ABCD", "Ruins of the Hamlet"])
def test_patch_scalar_string_parity(legacy: LegacyOracle, value: str, bits: str) -> None:
    """dd2.py:937 copies every later info word verbatim (no meta1 index rewrite), so spare bits
    on the objects after the patched field must survive exactly as the legacy left them."""
    dd2 = legacy.module("dd2")
    raw = or_object_infos(standard_save(THREE_ENTRIES), SPARE_INFO_BITS[bits])
    assert dd2.dson_validate_editor_compatible(raw) is None
    assert dson.validate(raw).ok_strict
    expected = dd2.dson_patch_scalar_string_field(raw, "estatename", value)
    doc = dson.parse(raw)
    estate = doc.find_child(0, "estatename")
    assert estate is not None
    assert dson.serialize(dson.patch_scalar_string(doc, estate, value)) == expected


# matrix cells only (pm.CARRIED_POSITIONS is keyed by them): every N=3 column, the other rows once
SPARE_BIT_CASES = [(3, 1), (3, 2), (3, 5), (3, 12), (7, 5), (1, 1), (0, 1), (None, 2)]


@pytest.mark.parametrize("bits", sorted(SPARE_INFO_BITS), ids=sorted(SPARE_INFO_BITS))
@pytest.mark.parametrize(("n", "m"), SPARE_BIT_CASES, ids=[pm.case_id(*c) for c in SPARE_BIT_CASES])
def test_write_applied_parity_with_spare_info_bits(
    legacy: LegacyOracle, n: int | None, m: int, bits: str
) -> None:
    """The resize/insert paths DO rewrite later infos (dd2.py:1109, 1425), clearing bit 1 past
    the splice even for a zero meta1 delta; the codec mirrors that path for path.

    Bit 31 is the one listed divergence: the legacy cleared it on every word of the block, the
    codec keeps it on the child word of each entry that already existed (``or_object_infos``
    flags object words only, so name/source words are clear on both sides).  The cells and
    positions come from ``pm.CARRIED_POSITIONS``; every other cell matches byte for byte.
    """
    dd2 = legacy.module("dd2")
    raw = or_object_infos(pm.build_input(n), SPARE_INFO_BITS[bits])
    entries = pm.new_entries(m)
    keys, table = pm.stub_identities(entries)
    expected, count = dd2.dson_patch_mod_list_resize(raw, keys, legacy.stub_manager(table))
    assert count == m
    ours = FMT.write_applied(raw, identities(entries))
    carried: set[int] = set()
    if SPARE_INFO_BITS[bits] & 0x80000000:
        applied = dson.parse(ours).find_child(0, "applied_ugcs_1_0")
        assert applied is not None
        carried = {applied + 1 + 3 * k for k in pm.CARRIED_POSITIONS.get((n, m), ())}
    assert info_bit31_indices(ours) == info_bit31_indices(expected) | carried
    assert set_info_bit31(ours, carried, on=False) == expected
    assert (ours == expected) == (not carried)


@pytest.mark.parametrize("name", sorted(STRICT_ONLY))
def test_strict_only_inputs_pass_the_pinned_validator(legacy: LegacyOracle, name: str) -> None:
    """Every STRICT-only input is accepted by the legacy: the extra checks are ours alone."""
    dd2 = legacy.module("dd2")
    raw, _codes = STRICT_ONLY[name]
    assert dd2.dson_validate_editor_compatible(raw) is None
    assert dson.validate(raw).ok


def test_legacy_verdict_on_variants(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    for name, raw in sample_variants().items():
        assert dd2.dson_validate_editor_compatible(raw) is None, name
        assert dson.validate(raw).ok, name
