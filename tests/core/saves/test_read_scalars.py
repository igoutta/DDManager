"""read_scalars: typed scalar reads that raise instead of returning {}."""

import pytest

from src.core.errors import DsonFormatError
from src.core.saves import dson
from src.core.saves.dson_v1 import DsonV1Format
from tests.support.dson_builder import (
    THREE_ENTRIES,
    B,
    I,
    O,
    R,
    S,
    build_save,
    standard_save,
)

FMT = DsonV1Format()
STANDARD = standard_save(THREE_ENTRIES)
ALL_ROOT_SCALARS = {
    "version": 5,
    "estatename": "Hamlet",
    "inraid": True,
    "raiddungeon": "crypts",
    "never_again": False,
    "tail_int": 0x7FFFFFFF,
}


def test_reads_every_root_scalar_with_its_type() -> None:
    got = dson.read_scalars(STANDARD, list(ALL_ROOT_SCALARS))
    assert got == ALL_ROOT_SCALARS
    for name, value in got.items():
        assert type(value) is type(ALL_ROOT_SCALARS[name]), name


def test_subset_and_unknown_names() -> None:
    assert dson.read_scalars(STANDARD, {"estatename"}) == {"estatename": "Hamlet"}
    assert dson.read_scalars(STANDARD, ("estatename", "no_such_field")) == {"estatename": "Hamlet"}
    assert dson.read_scalars(STANDARD, []) == {}


def test_objects_are_not_scalars() -> None:
    got = dson.read_scalars(STANDARD, ["dlc", "applied_ugcs_1_0", "nested", "version"])
    assert got == {"version": 5}


def test_format_delegates() -> None:
    assert FMT.read_scalars(STANDARD, ["version", "inraid"]) == {"version": 5, "inraid": True}


SPECIAL_ROOT = O(
    "base_root",
    [
        I("neg", -7),
        I("zero", 0),
        I("one", 1),
        S("cjk", "测试"),
        S("empty", ""),
        S("long", "L" * 350),
        B("no", False),
        B("yes", True),
        S("last", "end"),
    ],
)


def test_negative_zero_and_small_ints_are_not_misread_as_strings_or_bools() -> None:
    got = dson.read_scalars(build_save(SPECIAL_ROOT), ["neg", "zero", "one"])
    assert got == {"neg": -7, "zero": 0, "one": 1}


def test_utf8_and_long_strings() -> None:
    got = dson.read_scalars(build_save(SPECIAL_ROOT), ["cjk", "long", "last"])
    assert got == {"cjk": "测试", "long": "L" * 350, "last": "end"}


def test_bools_next_to_strings() -> None:
    got = dson.read_scalars(build_save(SPECIAL_ROOT), ["no", "yes", "last"])
    assert got == {"no": False, "yes": True, "last": "end"}


@pytest.mark.parametrize(
    "raw", [b"", b"not a save at all", STANDARD[:-3]], ids=["empty", "text", "truncated"]
)
def test_invalid_input_raises_instead_of_returning_empty(raw: bytes) -> None:
    with pytest.raises(DsonFormatError) as info:
        dson.read_scalars(raw, ["version"])
    assert type(info.value).family == "dson_format"
    with pytest.raises(DsonFormatError):
        FMT.read_scalars(raw, ["version"])


RAW_ROOT = O(
    "base_root",
    [
        R("r0", b""),
        R("r2", b"\x01\x02"),
        R("r3", b"\x01\x02\x03"),
        R("r8", bytes(range(8))),
        R("float_like", b"\x00\x00\x80\x3f"),
        S("last", "end"),
    ],
)
RAW_EXPECTED: dict[str, bool | int | str | bytes] = {
    "r0": b"",
    "r2": b"\x01\x02",
    "r3": b"\x01\x02\x03",
    "r8": bytes(range(8)),
    "float_like": 0x3F800000,  # exactly 4 bytes decode as an int; the caller knows its fields
    "last": "end",
}


def test_payloads_that_are_not_bool_int_or_string_come_back_as_bytes() -> None:
    """Decided: only EXACTLY 4 bytes decode as an int; longer non-string payloads (vectors,
    doubles) and the 0/2/3-byte oddities are returned raw instead of guessed at."""
    got = dson.read_scalars(build_save(RAW_ROOT), list(RAW_EXPECTED))
    assert got == RAW_EXPECTED
    for name, value in got.items():
        assert type(value) is type(RAW_EXPECTED[name]), name
