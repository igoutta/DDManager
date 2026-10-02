"""project.xml facts (src/core/project_xml.py).

Contract: ``parse_project`` is total (bytes -> ProjectInfo | None) and follows the legacy decode
ladder of ``dd2.parse_xml_file_forgiving`` (dd2.py:634-666); ``legacy_tags`` is the exact
``categories.project_tag_values`` list (categories.py:105-131); the small helpers are verbatim
ports (xml_text_from_child 576-582, strip_invalid_xml_chars 585-589, version_label 3406-3421,
is_black_reliquary_tagged 3423-3430). Parity is proved against the pinned oracle on temp files.
"""

import dataclasses
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from src.core.project_xml import (
    ProjectInfo,
    is_black_reliquary_tagged,
    load_after_hints,
    parse_project,
    strip_invalid_xml_chars,
    version_label,
    xml_text_from_child,
)
from tests.support import mod_facts as mf
from tools.legacy_oracle import LegacyOracle

CRUSADER = "crusader_hu_swf_compat"
STAGE_COACH = "better_stage_coach_swf_compat"
TRINKETS24 = "swf_trinkets24_compat"


def _project(**kwargs: Any) -> bytes:
    return mf.project_xml(**kwargs).encode("utf-8")


def _parsed(**kwargs: Any) -> ProjectInfo:
    info = parse_project(_project(**kwargs))
    assert info is not None
    return info


# ----------------------------------------------------------------- ProjectInfo value type


def test_project_info_is_a_frozen_slotted_value() -> None:
    info = _parsed(title="X")
    assert isinstance(info, ProjectInfo)
    assert dataclasses.is_dataclass(info)
    assert hasattr(info, "__slots__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.title = "Y"  # ty: ignore[invalid-assignment]
    assert [f.name for f in dataclasses.fields(info)] == [
        "title",
        "published_file_id",
        "version_major",
        "version_minor",
        "legacy_tags",
        "clean_tags",
        "preview_icon_file",
        "description",
    ]


def test_fields_are_raw_child_texts() -> None:
    info = _parsed(
        title="  Spaced Title ",
        published_id="2248772895",
        major="01",
        minor="2",
        tags=("New Class", "support"),
        description="Line one.\n\nLine two.",
        preview="preview_icon.png",
    )
    assert info.title == "Spaced Title"
    assert info.published_file_id == "2248772895"
    assert info.version_major == "01"  # raw text; version_label does the int folding
    assert info.version_minor == "2"
    assert info.clean_tags == ("New Class", "support")
    assert info.preview_icon_file == "preview_icon.png"
    assert info.description.strip() == "Line one.\n\nLine two."


def test_absent_children_are_empty_strings() -> None:
    info = _parsed(title=None, major=None, minor=None)
    assert info == ProjectInfo(
        title="",
        published_file_id="",
        version_major="",
        version_minor="",
        legacy_tags=(),
        clean_tags=(),
        preview_icon_file="",
        description="",
    )


def test_entities_in_title_are_decoded_by_the_xml_layer() -> None:
    info = _parsed(title='Rogue & Knight\'s "Fate" <v2>')
    assert info.title == 'Rogue & Knight\'s "Fate" <v2>'


# ----------------------------------------------------------------- tags


def test_legacy_tags_include_the_outer_pseudo_tag_and_split_on_separators() -> None:
    info = _parsed(tags=("Character Mod", "Class Mod", "A, B/C|D", "class mod", "", "  "))
    assert info.clean_tags == ("Character Mod", "Class Mod", "A, B/C|D", "class mod")
    # categories.py:117-129: every <Tags> element (outer first), whitespace collapsed,
    # split on [,/|], html-unescaped, deduped case-insensitively keeping the first spelling.
    assert info.legacy_tags == (
        "Character Mod Class Mod A",
        "B",
        "C",
        "D class mod",
        "Character Mod",
        "Class Mod",
        "A",
        "D",
    )


def test_flat_single_tags_element_is_both_leaf_and_legacy_tag() -> None:
    raw = b"<project><Title>T</Title><Tags>Class</Tags></project>"
    info = parse_project(raw)
    assert info is not None
    assert info.clean_tags == ("Class",)
    assert info.legacy_tags == ("Class",)


def test_leaf_tags_keep_case_and_order_and_are_not_split() -> None:
    info = _parsed(tags=("Patch", "Compatibility", "ui", "A, B"))
    assert info.clean_tags == ("Patch", "Compatibility", "ui", "A, B")


def test_tag_entities_are_unescaped_for_legacy_tags() -> None:
    raw = b"<project><Tags><Tags>Rock &amp;amp; Roll</Tags></Tags></project>"
    info = parse_project(raw)
    assert info is not None
    assert info.clean_tags == ("Rock &amp; Roll",)
    assert "Rock & Roll" in info.legacy_tags


# ----------------------------------------------------------------- decode ladder


def test_bom_and_junk_before_declaration_are_tolerated() -> None:
    raw = b"\xef\xbb\xbfjunk\n" + _project(title="BOM Mod")
    info = parse_project(raw)
    assert info is not None
    assert info.title == "BOM Mod"


def test_junk_before_root_without_declaration() -> None:
    raw = b"garbage<project><Title>Rooted</Title></project>"
    info = parse_project(raw)
    assert info is not None
    assert info.title == "Rooted"


def test_control_characters_are_stripped_before_the_retry() -> None:
    raw = b"<project><Title>Bad\x01Char</Title></project>"
    info = parse_project(raw)
    assert info is not None
    assert info.title == "BadChar"


def test_gb18030_declared_document_parses_through_the_decode_ladder() -> None:
    text = mf.project_xml("模组标题").replace('encoding="utf-8"', 'encoding="gb18030"')
    info = parse_project(text.encode("gb18030"))
    assert info is not None
    assert info.title == "模组标题"


def test_utf16_document_parses() -> None:
    text = mf.project_xml("Wide Title").replace('encoding="utf-8"', 'encoding="utf-16"')
    info = parse_project(text.encode("utf-16"))
    assert info is not None
    assert info.title == "Wide Title"


@pytest.mark.parametrize(
    "raw",
    [b"", b"   ", b"<project><Title>", b"\xff\xfe\x00", b"not xml at all", b"<a><b></a>"],
)
def test_unparseable_input_gives_none(raw: bytes) -> None:
    assert parse_project(raw) is None


def test_parse_project_is_total_on_mutated_bytes() -> None:
    rng = random.Random(7)
    base = _project(title="Fuzz Base", published_id="42", tags=("UI",))
    for _ in range(300):
        raw = _mutate(rng, base)
        result = parse_project(raw)
        assert result is None or isinstance(result, ProjectInfo)


def _mutate(rng: random.Random, base: bytes) -> bytes:
    data = bytearray(base)
    for _ in range(rng.randint(1, 6)):
        kind = rng.randrange(4)
        at = rng.randrange(len(data) + 1)
        if kind == 0 and data:
            data[min(at, len(data) - 1)] = rng.randrange(256)
        elif kind == 1:
            data[at:at] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 8)))
        elif kind == 2:
            del data[at : at + rng.randint(1, 16)]
        else:
            data = bytearray(data[:at])
    return bytes(data)


# ----------------------------------------------------------------- helpers


def test_xml_text_from_child_is_case_and_namespace_insensitive() -> None:
    root = ET.fromstring(
        '<p xmlns:x="urn:x"><x:TITLE>  A  </x:TITLE><Empty/><Nest><Title>deep</Title></Nest></p>'
    )
    assert xml_text_from_child(root, "title") == "A"
    assert xml_text_from_child(root, "Empty") == ""
    assert xml_text_from_child(root, "Nest") == ""  # text None -> ""; grandchildren not searched
    assert xml_text_from_child(root, "missing") == ""


def test_strip_invalid_xml_chars_keeps_tab_newline_cr_and_printables() -> None:
    assert strip_invalid_xml_chars("a\x00b\x01\tc\nd\re\x1f\x7fé") == "ab\tc\nd\re\x7fé"
    assert strip_invalid_xml_chars("") == ""


@pytest.mark.parametrize(
    ("major", "minor", "expected"),
    [
        ("1", "2", "1.2"),
        ("0", "0", ""),
        ("", "", ""),
        ("01", "02", "1.2"),
        ("1", "", "1"),
        ("", "3", "3"),
        ("1a", "b", "1a.b"),
        ("2", "0", "2.0"),
        ("0", "1", "0.1"),
        ("x", "", "x"),
        ("", "0", "0"),
        ("00", "0", ""),
    ],
)
def test_version_label_contract(major: str, minor: str, expected: str) -> None:
    assert version_label(major, minor) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ((), False),
        (("Black Reliquary",), True),
        (("black_reliquary",), True),
        (("BLACK-RELIQUARY",), True),
        (("blackreliquary",), True),
        (("Black Reliquary Patch",), False),
        (("Class", "Black  Reliquary"), True),
        (("Reliquary Black",), False),
        (("Black&amp;Reliquary",), False),
    ],
)
def test_is_black_reliquary_tagged_contract(tags: tuple[str, ...], expected: bool) -> None:
    assert is_black_reliquary_tagged(tags) is expected
    assert is_black_reliquary_tagged(iter(tags)) is expected


# ----------------------------------------------------------------- load-after hints


def test_load_after_hints_from_bullets_until_blank_line() -> None:
    text = (
        "Intro paragraph.\n\n"
        "Load this after:\n"
        "- SWF (V0.25) - 2goals, QOL, mermaids, sandwiches...\n"
        "  * Heroes Unchained: Crusader  \n"
        "• Fire Attacks: Crusader Patch (if used)\n"
        "\n"
        "- not a hint anymore\n"
    )
    assert load_after_hints(text) == (
        "SWF (V0.25) - 2goals, QOL, mermaids, sandwiches...",
        "Heroes Unchained: Crusader",
        "Fire Attacks: Crusader Patch (if used)",
    )


@pytest.mark.parametrize("header", ["load it after", "LOAD THIS AFTER:", "Please load it after:"])
def test_load_after_header_is_case_insensitive_and_colon_optional(header: str) -> None:
    assert load_after_hints(f"{header}\n- A\n- B\n") == ("A", "B")


@pytest.mark.parametrize(
    "text", ["", "no header\n- A\n", "Load this after:\n", "Load this after:\n\n- A"]
)
def test_load_after_hints_empty_cases(text: str) -> None:
    assert load_after_hints(text) == ()


def test_load_after_hints_of_the_sample_patch_mods(sample_mods_dir: Path) -> None:
    expected = {
        CRUSADER: (
            "SWF (V0.25) - 2goals, QOL, mermaids, sandwiches...",
            "Heroes Unchained: Crusader",
            "Fire Attacks: Crusader Patch (if used)",
        ),
        STAGE_COACH: ("Better Stage Coach", "SWF (V0.25) - 2goals, QOL, mermaids, sandwiches..."),
        TRINKETS24: (
            "SWF (V0.25) - 2goals, QOL, mermaids, sandwiches...",
            "Trinkets 8, 24 Inventory, 10 Quirks",
        ),
    }
    for folder, hints in expected.items():
        info = parse_project((sample_mods_dir / folder / "project.xml").read_bytes())
        assert info is not None, folder
        assert load_after_hints(info.description) == hints, folder
        assert "Patch" in info.clean_tags and "Compatibility" in info.clean_tags


def test_sample_mods_parse_with_expected_facts(sample_mods_dir: Path) -> None:
    info = parse_project((sample_mods_dir / "chorus_class_mod" / "project.xml").read_bytes())
    assert info is not None
    assert info.title == "The Chorus"
    assert info.clean_tags == ("New Class", "support", "hive mind")
    assert info.legacy_tags == ("New Class support hive mind", "New Class", "support", "hive mind")
    assert (info.version_major, info.version_minor) == ("0", "0")
    assert version_label(info.version_major, info.version_minor) == ""
    assert info.preview_icon_file == "preview_icon.png"


# ----------------------------------------------------------------- parity vs the pinned oracle


def _legacy_root(dd2: ModuleType, tmp_path: Path, raw: bytes, name: str) -> object:
    path = tmp_path / f"{name}.xml"
    path.write_bytes(raw)
    return dd2.parse_xml_file_forgiving(str(path))


LADDER_INPUTS: dict[str, bytes] = {
    "plain": _project(title="Plain", published_id="1"),
    "bom": b"\xef\xbb\xbf" + _project(title="Bom"),
    "bom_junk": b"\xef\xbb\xbfjunk\n" + _project(title="BomJunk"),
    "junk_no_decl": b"abc<project><Title>Junk</Title></project>",
    "control": b"<project><Title>Ctl\x01x</Title></project>",
    "utf16": mf.project_xml("Wide").replace("utf-8", "utf-16").encode("utf-16"),
    "gb18030": mf.project_xml("模组").replace("utf-8", "gb18030").encode("gb18030"),
    "big5": mf.project_xml("模組").replace("utf-8", "big5").encode("big5"),
    "latin1_undeclared": mf.project_xml("Café").encode("latin-1"),
    "empty": b"",
    "spaces": b"   \n",
    "truncated": b"<project><Title>",
    "mismatched": b"<a><b></a>",
    "only_text": b"hello",
}


@pytest.mark.legacy
@pytest.mark.parametrize("name", list(LADDER_INPUTS))
def test_parse_project_matches_legacy_ladder(
    legacy: LegacyOracle, tmp_path: Path, name: str
) -> None:
    dd2 = legacy.module("dd2")
    raw = LADDER_INPUTS[name]
    root = _legacy_root(dd2, tmp_path, raw, name)
    info = parse_project(raw)
    assert (info is None) == (root is None)
    if root is not None and info is not None:
        assert info.title == dd2.xml_text_from_child(root, "Title")
        assert info.published_file_id == dd2.xml_text_from_child(root, "PublishedFileId")


@pytest.mark.legacy
def test_parse_project_matches_legacy_on_mutated_bytes(
    legacy: LegacyOracle, tmp_path: Path
) -> None:
    dd2 = legacy.module("dd2")
    rng = random.Random(11)
    base = _project(title="Fuzz Base", published_id="42", tags=("UI", "Class"))
    for index in range(200):
        raw = _mutate(rng, base)
        root = _legacy_root(dd2, tmp_path, raw, f"fuzz_{index}")
        info = parse_project(raw)
        assert (info is None) == (root is None), (index, raw)
        if root is not None and info is not None:
            assert info.title == dd2.xml_text_from_child(root, "Title")
            assert info.published_file_id == dd2.xml_text_from_child(root, "PublishedFileId")
            assert info.version_major == dd2.xml_text_from_child(root, "VersionMajor")


TAG_DOCUMENTS: dict[str, bytes] = {
    "nested": _project(tags=("Character Mod", "Class Mod", "A, B/C|D", "class mod", "", " ")),
    "flat": b"<project><Tags>Class</Tags></project>",
    "entities": (
        b"<project><Tags><Tags>Rock &amp;amp; Roll</Tags><Tags>a&amp;b</Tags></Tags></project>"
    ),
    "namespaced": b'<p xmlns:x="urn:x"><x:tags><x:TAGS>Ui</x:TAGS></x:tags></p>',
    "double_space": b"<project><Tags>two  words / three</Tags></project>",
    "none": _project(),
}


@pytest.mark.legacy
@pytest.mark.parametrize("name", list(TAG_DOCUMENTS))
def test_legacy_tags_match_project_tag_values(
    legacy: LegacyOracle, tmp_path: Path, name: str
) -> None:
    dd2 = legacy.module("dd2")
    categories = legacy.module("categories")
    folder = tmp_path / name
    folder.mkdir()
    (folder / "project.xml").write_bytes(TAG_DOCUMENTS[name])
    expected = categories.project_tag_values(
        lambda _mod: str(folder), name, dd2.parse_xml_file_forgiving
    )
    info = parse_project(TAG_DOCUMENTS[name])
    assert info is not None
    assert list(info.legacy_tags) == expected


@pytest.mark.legacy
def test_legacy_tags_match_on_every_sample_mod(legacy: LegacyOracle, sample_mods_dir: Path) -> None:
    dd2 = legacy.module("dd2")
    categories = legacy.module("categories")
    for folder in sorted(p for p in sample_mods_dir.iterdir() if p.is_dir()):
        expected = categories.project_tag_values(
            lambda _mod, f=folder: str(f), folder.name, dd2.parse_xml_file_forgiving
        )
        info = parse_project((folder / "project.xml").read_bytes())
        assert info is not None, folder.name
        assert list(info.legacy_tags) == expected, folder.name


@pytest.mark.legacy
def test_helpers_match_legacy(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    root = ET.fromstring(
        '<p xmlns:x="urn:x"><x:TITLE>  A  </x:TITLE><Empty/><Nest><Title>deep</Title></Nest></p>'
    )
    for tag in ("title", "Title", "Empty", "Nest", "missing", "p"):
        assert xml_text_from_child(root, tag) == dd2.xml_text_from_child(root, tag)
    rng = random.Random(3)
    alphabet = [chr(i) for i in range(0x30)] + ["a", "é", "桜", "\x7f", chr(0xFFFE)]
    for _ in range(500):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 20)))
        assert strip_invalid_xml_chars(text) == dd2.strip_invalid_xml_chars(text)


@pytest.mark.legacy
@pytest.mark.parametrize(("major", "minor"), mf.VERSION_CASES)
def test_version_label_matches_legacy(legacy: LegacyOracle, major: str, minor: str) -> None:
    dd2 = legacy.module("dd2")
    root = ET.fromstring(
        f"<project><VersionMajor>{major}</VersionMajor><VersionMinor>{minor}</VersionMinor></project>"
    )
    expected = dd2.ModManager.version_label_from_project(None, root)
    assert version_label(major, minor) == expected
    # the contract takes the stripped child texts: feed them exactly as the legacy reads them
    assert (
        version_label(
            dd2.xml_text_from_child(root, "VersionMajor"),
            dd2.xml_text_from_child(root, "VersionMinor"),
        )
        == expected
    )


@pytest.mark.legacy
@pytest.mark.parametrize("tags", mf.BLACK_RELIQUARY_CASES, ids=lambda t: "|".join(t) or "empty")
def test_black_reliquary_matches_legacy(legacy: LegacyOracle, tags: tuple[str, ...]) -> None:
    dd2 = legacy.module("dd2")
    assert is_black_reliquary_tagged(tags) is dd2.ModManager.is_black_reliquary_tagged(None, tags)
