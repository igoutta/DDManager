"""parse/serialize, lookups, readers and the validator levels of src.core.saves.dson."""

import random
import struct

import pytest

from src.core.errors import DsonFormatError, DsonUnsupportedError
from src.core.saves import dson
from src.core.saves.dson import (
    DSON_MAGIC,
    HEADER_SIZE,
    META1_SIZE,
    META2_SIZE,
    Meta1,
    Meta2,
)
from src.core.saves.dson_v1 import DsonV1Format
from tests.support.dson_builder import (
    ANCHOR_BLOCK,
    APPLIED_BLOCK,
    LOCAL,
    PERSISTENT_OBJECT,
    STEAM,
    THREE_ENTRIES,
    TINY_ROOT,
    B,
    I,
    O,
    S,
    build_save,
    find_layout,
    layout,
    sample_variants,
    standard_root,
    standard_save,
)
from tests.support.identities import identities
from tests.support.mutations import (
    bump_root_all_children,
    duplicate_meta2_record,
    swap_meta1_records,
    with_i32,
    with_second_root,
)

VARIANTS = sample_variants()
CJK = "测试模组"


def test_constants_match_the_format() -> None:
    assert HEADER_SIZE == 64
    assert META1_SIZE == 16
    assert META2_SIZE == 12
    assert DSON_MAGIC == b"\x01\xb1\x00\x00"


def test_parse_header_and_tables() -> None:
    raw = build_save(TINY_ROOT)
    doc = dson.parse(raw)
    header = doc.header
    assert header.raw == raw[:64]
    assert header.magic == DSON_MAGIC
    assert header.revision == b"\x00\x00\x00\x00"
    assert (header.header_length, header.meta1_size, header.meta1_count) == (64, 32, 2)
    assert (header.meta1_offset, header.meta2_count, header.meta2_offset) == (64, 4, 96)
    assert (header.data_length, header.data_offset) == (19, 144)
    assert doc.data == raw[144:]
    assert doc.meta1 == (Meta1(-1, 0, 2, 3), Meta1(0, 2, 1, 1))
    assert doc.meta2[2] == Meta2(99, 5, (2 << 2) | 1 | (1 << 11))
    assert doc.meta2[0].is_object and doc.meta2[0].object_index == 0
    assert doc.meta2[0].name_length == 2
    assert not doc.meta2[1].is_object and doc.meta2[1].object_index is None
    assert doc.meta2[2].object_index == 1
    assert doc.meta2[3].name_length == 3


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_serialize_parse_identity(name: str) -> None:
    raw = VARIANTS[name]
    assert dson.serialize(dson.parse(raw)) == raw


@pytest.mark.parametrize(
    "raw",
    [
        standard_save(THREE_ENTRIES, pad_byte=0xFF),
        build_save(standard_root(THREE_ENTRIES), magic=b"\x00\x00\x00\x00", filler=0x00),
        build_save(standard_root(None), revision=b"\x07\x00\x00\x00", filler=0x11),
    ],
    ids=["nonzero_padding", "zero_magic", "revision_7"],
)
def test_serialize_keeps_unknown_bytes_and_payloads(raw: bytes) -> None:
    assert dson.serialize(dson.parse(raw)) == raw


GOOD = standard_save(THREE_ENTRIES)
# parse refuses all of these; header_length != 64 is a parse gate (dd2.py:1319), NOT a verdict of
# the pinned validator (dd2.py:1202 never reads byte 8), so LEGACY-level validate accepts it
PARSE_REJECTS = {
    "empty": b"",
    "short": GOOD[:63],
    "truncated": GOOD[:-1],
    "header_length_65": with_i32(GOOD, 8, 65),
    "meta1_offset_68": with_i32(GOOD, 24, 68),
    "meta2_count_off_by_one": with_i32(GOOD, 44, struct.unpack_from("<i", GOOD, 44)[0] + 1),
    "random": random.Random(7).randbytes(300),
    "decoded_text": b'{\n    "base_root" : {\n        "version" : 5\n    }\n}\n',
}


VALIDATE_REJECTS = {k: v for k, v in PARSE_REJECTS.items() if k != "header_length_65"}


@pytest.mark.parametrize("name", sorted(PARSE_REJECTS))
def test_parse_raises_dson_format_error(name: str) -> None:
    with pytest.raises(DsonFormatError):
        dson.parse(PARSE_REJECTS[name])


@pytest.mark.parametrize("name", sorted(VALIDATE_REJECTS))
def test_validate_never_raises(name: str) -> None:
    report = dson.validate(VALIDATE_REJECTS[name])
    assert not report.ok
    assert not report.ok_strict
    assert report.legacy_errors


def test_header_length_is_legacy_valid_but_strict_invalid_and_unparseable() -> None:
    raw = PARSE_REJECTS["header_length_65"]
    report = dson.validate(raw)
    assert report.ok
    assert not report.ok_strict
    assert [p.code for p in report.strict_errors] == ["header_length"]
    with pytest.raises(DsonFormatError) as info:
        dson.parse(raw)
    assert info.value.code == "unsupported_header_layout"


def test_children_index_and_names() -> None:
    root = standard_root(THREE_ENTRIES)
    doc = dson.parse(build_save(root))
    layouts = layout(root)
    assert len(doc.children) == len(doc.meta2)
    assert [doc.name_of(i) for i in range(len(doc.meta2))] == [e.path[-1] for e in layouts]
    root_names = [doc.name_of(i) for i in doc.children[0]]
    assert root_names == [child.name for child in root.children]
    applied = doc.find_child(0, APPLIED_BLOCK)
    assert applied is not None
    assert [doc.name_of(i) for i in doc.children[applied]] == ["0", "1", "2"]
    first = doc.children[applied][0]
    assert [doc.name_of(i) for i in doc.children[first]] == ["name", "source"]
    version = doc.find_child(0, "version")
    assert version is not None
    assert doc.children[version] == ()


def test_field_offset_and_end() -> None:
    doc = dson.parse(standard_save(THREE_ENTRIES))
    count = len(doc.meta2)
    for i in range(count):
        assert doc.field_offset(i) == doc.meta2[i].offset
        expected_end = doc.meta2[i + 1].offset if i + 1 < count else len(doc.data)
        assert doc.field_end(i) == expected_end
    assert doc.field_offset(0) == 0


LOOKUP_ROOT = O(
    "base_root",
    [
        S("x", "root x"),
        O("nested", [S("x", "nested x"), O("deep", [S("only_deep", "d")]), S("shadow", "n")]),
        S("shadow", "r"),
    ],
)


def test_find_child_is_a_path_lookup_and_find_anywhere_is_not() -> None:
    doc = dson.parse(build_save(LOOKUP_ROOT))
    layouts = layout(LOOKUP_ROOT)

    def index(*path: str) -> int:
        return next(e.meta2_index for e in layouts if e.path == path)

    nested = index("base_root", "nested")
    deep = index("base_root", "nested", "deep")
    assert doc.find_child(0, "x") == index("base_root", "x")
    assert doc.find_child(nested, "x") == index("base_root", "nested", "x")
    assert doc.find_anywhere("x") == index("base_root", "x")
    assert doc.find_child(0, "only_deep") is None
    assert doc.find_child(nested, "only_deep") is None  # grandchild, not a direct child
    assert doc.find_child(deep, "only_deep") == index("base_root", "nested", "deep", "only_deep")
    assert doc.find_anywhere("only_deep") == index("base_root", "nested", "deep", "only_deep")
    # a nested field comes first in data order; the path lookup still returns the root one
    assert doc.find_child(0, "shadow") == index("base_root", "shadow")
    assert doc.find_anywhere("shadow") == index("base_root", "nested", "shadow")
    assert doc.find_child(0, "missing") is None
    assert doc.find_anywhere("missing") is None
    assert doc.find_child(index("base_root", "x"), "anything") is None


SPECIAL_ENTRIES = (
    (CJK, LOCAL),
    ("x" * 400, LOCAL),
    ("Épée \U0001f525 Mod", LOCAL),
    ("42", STEAM),
    ("a", LOCAL),
)


def test_read_name_source_object_handles_utf8_and_long_values() -> None:
    doc = dson.parse(standard_save(SPECIAL_ENTRIES))
    applied = doc.find_child(0, APPLIED_BLOCK)
    assert applied is not None
    assert dson.read_name_source_object(doc, applied) == identities(SPECIAL_ENTRIES)
    anchor = doc.find_child(0, ANCHOR_BLOCK)
    assert anchor is not None
    assert dson.read_name_source_object(doc, anchor) == identities([("1234567890", STEAM)])
    dlc = doc.find_child(0, "dlc")
    assert dlc is not None
    assert dson.read_name_source_object(doc, dlc) == identities([("crimson_court", "dlc")])


def test_read_name_source_object_with_1200_entries() -> None:
    entries = [(f"{k}", STEAM) if k % 2 else (f"Local {k}", LOCAL) for k in range(1200)]
    raw = standard_save(entries)
    doc = dson.parse(raw)
    applied = doc.find_child(0, APPLIED_BLOCK)
    assert applied is not None
    assert dson.read_name_source_object(doc, applied) == identities(entries)
    assert DsonV1Format().read_applied(raw) == identities(entries)


def test_read_name_source_object_empty() -> None:
    doc = dson.parse(standard_save([]))
    applied = doc.find_child(0, APPLIED_BLOCK)
    assert applied is not None
    assert dson.read_name_source_object(doc, applied) == ()


MALFORMED_LISTS = {
    "scalar_child": O(APPLIED_BLOCK, [S("0", "x")]),
    "missing_source": O(APPLIED_BLOCK, [O("0", [S("name", "n")])]),
    "non_string_source": O(APPLIED_BLOCK, [O("0", [S("name", "n"), I("source", 1)])]),
    "second_child_broken": O(
        APPLIED_BLOCK, [O("0", [S("name", "n"), S("source", "s")]), O("1", [B("name", True)])]
    ),
}


@pytest.mark.parametrize("name", sorted(MALFORMED_LISTS))
def test_read_name_source_object_rejects_malformed_children(name: str) -> None:
    """A child that is not ``{name: str, source: str}`` raises ``name_source_shape`` (decided:
    raise, never silently skip or return an empty list) and read_applied propagates it."""
    raw = build_save(O("base_root", [I("version", 5), MALFORMED_LISTS[name], PERSISTENT_OBJECT]))
    assert dson.validate(raw).ok_strict
    doc = dson.parse(raw)
    applied = doc.find_child(0, APPLIED_BLOCK)
    assert applied is not None
    with pytest.raises(DsonFormatError) as info:
        dson.read_name_source_object(doc, applied)
    assert info.value.code == "name_source_shape"
    with pytest.raises(DsonFormatError) as info:
        DsonV1Format().read_applied(raw)
    assert info.value.code == "name_source_shape"


def test_read_name_source_object_ignores_extra_fields_and_object_children() -> None:
    applied = O(
        APPLIED_BLOCK,
        [O("0", [I("rank", 3), S("source", "s"), O("meta", [S("name", "decoy")]), S("name", "n")])],
    )
    raw = build_save(O("base_root", [applied, PERSISTENT_OBJECT]))
    doc = dson.parse(raw)
    index = doc.find_child(0, APPLIED_BLOCK)
    assert index is not None
    assert dson.read_name_source_object(doc, index) == identities([("n", "s")])


def test_read_name_source_object_needs_an_object() -> None:
    doc = dson.parse(standard_save(THREE_ENTRIES))
    version = doc.find_child(0, "version")
    assert version is not None
    with pytest.raises(DsonFormatError) as info:
        dson.read_name_source_object(doc, version)
    assert info.value.code == "not_an_object"


def test_insert_needs_an_anchor_with_a_parent_object() -> None:
    """``before=0`` (the root itself) would create a second root; a scalar is no anchor either."""
    doc = dson.parse(standard_save(None))
    ids = identities(THREE_ENTRIES)
    with pytest.raises(DsonUnsupportedError) as info:
        dson.insert_name_source_object(doc, before=0, name=APPLIED_BLOCK, entries=ids)
    assert info.value.code == "no_anchor"
    version = doc.find_child(0, "version")
    assert version is not None
    with pytest.raises(DsonUnsupportedError) as info:
        dson.insert_name_source_object(doc, before=version, name=APPLIED_BLOCK, entries=ids)
    assert info.value.code == "no_anchor"
    with pytest.raises(ValueError, match="NUL"):
        dson.insert_name_source_object(doc, before=1, name="a\x00b", entries=ids)


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_validate_accepts_variants_at_both_levels(name: str) -> None:
    report = dson.validate(VARIANTS[name])
    assert (report.legacy_errors, report.strict_errors) == ((), ())


def _strict_only_inputs() -> dict[str, tuple[bytes, list[str]]]:
    """Legacy-valid files that only STRICT rejects, with the exact codes expected.

    See tests/support/mutations.py for the surgery; test_dson_parity.py proves the pinned
    validator accepts every one of them.
    """
    root = standard_root(THREE_ENTRIES)
    raw = build_save(root)
    layouts = layout(root)
    dlc = find_layout(layouts, "base_root", "dlc")
    dlc_child = find_layout(layouts, "base_root", "dlc", "0")
    inraid = find_layout(layouts, "base_root", "inraid")
    return {
        "all_children_bump": (bump_root_all_children(raw), ["all_children_mismatch"]),
        "meta1_swapped": (swap_meta1_records(raw, dlc, dlc_child), ["meta1_order", "meta1_order"]),
        "meta2_duplicated": (duplicate_meta2_record(raw, inraid), ["offsets_not_increasing"]),
        "second_root": (with_second_root(raw, "second"), ["root_count"]),
        "header_length_65": (with_i32(raw, 8, 65), ["header_length"]),
        "zero_magic": (build_save(root, magic=bytes(4)), ["bad_magic"]),
    }


STRICT_ONLY = _strict_only_inputs()


@pytest.mark.parametrize("name", sorted(STRICT_ONLY))
def test_strict_only_inputs_report_their_codes(name: str) -> None:
    raw, codes = STRICT_ONLY[name]
    report = dson.validate(raw)
    assert report.legacy_errors == ()
    assert report.ok
    assert not report.ok_strict
    assert [p.code for p in report.strict_errors] == codes
    if name != "header_length_65":
        assert dson.serialize(dson.parse(raw)) == raw  # legacy-valid, so still parseable


def test_second_top_level_object_is_not_a_root_child() -> None:
    """root_count IS reachable behind the legacy gate (the walk lets a new object open once the
    root has closed); the codec keeps the extra object out of the root's children."""
    raw = STRICT_ONLY["second_root"][0]
    doc = dson.parse(raw)
    assert doc.find_child(0, "second") is None
    assert doc.find_anywhere("second") == len(doc.meta2) - 1
    assert doc.meta1[-1].parent == -1
    assert DsonV1Format().read_applied(raw) == identities(THREE_ENTRIES)


def test_bad_magic_is_a_strict_problem_only() -> None:
    raw = build_save(standard_root(THREE_ENTRIES), magic=b"\x00\x00\x00\x00")
    report = dson.validate(raw)
    assert report.legacy_errors == ()
    assert report.ok
    assert not report.ok_strict
    assert [p.code for p in report.strict_errors] == ["bad_magic"]
    assert DsonV1Format().sniff(raw)


def test_problem_records_carry_offsets_and_messages() -> None:
    report = dson.validate(PARSE_REJECTS["truncated"])
    problem = report.legacy_errors[0]
    assert isinstance(problem.code, str) and problem.code
    assert isinstance(problem.offset, int)
    assert isinstance(problem.message, str) and problem.message


@pytest.mark.parametrize("value", ["A", "AB", "ABC", "ABCD", "Much longer estate " + CJK, ""])
def test_patch_scalar_string_keeps_everything_else(value: str) -> None:
    raw = standard_save(THREE_ENTRIES)
    doc = dson.parse(raw)
    estate = doc.find_child(0, "estatename")
    assert estate is not None
    out = dson.serialize(dson.patch_scalar_string(doc, estate, value))
    assert dson.validate(out).ok_strict
    scalars = dson.read_scalars(out, ["estatename", "version", "inraid", "raiddungeon", "tail_int"])
    assert scalars == {
        "estatename": value,
        "version": 5,
        "inraid": True,
        "raiddungeon": "crypts",
        "tail_int": 0x7FFFFFFF,
    }
    assert DsonV1Format().read_applied(out) == identities(THREE_ENTRIES)
    assert out[:8] == raw[:8] and out[12:16] == raw[12:16] and out[28:44] == raw[28:44]


def test_patch_scalar_string_on_a_bool_field_keeps_later_bools_intact() -> None:
    root = O("base_root", [S("s", "v"), B("flag", True), S("t", "w"), B("last", False)])
    doc = dson.parse(build_save(root))
    target = doc.find_child(0, "s")
    assert target is not None
    out = dson.serialize(dson.patch_scalar_string(doc, target, "value that is longer"))
    assert dson.validate(out).ok_strict
    assert dson.read_scalars(out, ["s", "flag", "t", "last"]) == {
        "s": "value that is longer",
        "flag": True,
        "t": "w",
        "last": False,
    }
