"""Identifiers: mod ids, save sources and the SaveIdentity value type."""

import pytest

from src.core.errors import DDManagerError
from src.core.ids import ModId, SaveIdentity, SaveSource, SourceKind, parse_mod_id
from src.core.saves.dson_v1 import DsonV1Format
from tests.support.dson_builder import THREE_ENTRIES, standard_save


@pytest.mark.parametrize("raw", ["", ".", "..", "a/b", "a\\b", "/", "\\"])
def test_parse_mod_id_rejects_path_like_keys(raw: str) -> None:
    with pytest.raises(ValueError, match="invalid mod id"):
        parse_mod_id(raw)


def test_parse_mod_id_keeps_the_exact_basename() -> None:
    assert parse_mod_id("My Mod (v2)") == ModId("My Mod (v2)")
    assert parse_mod_id("...") == "..."
    assert parse_mod_id("2861478271") == "2861478271"


def test_source_constants() -> None:
    assert SourceKind.WORKSHOP == "workshop"
    assert SourceKind.LOCAL == "local"
    assert (SaveSource.STEAM, SaveSource.LOCAL, SaveSource.DLC) == (
        "Steam",
        "mod_local_source",
        "dlc",
    )


def test_save_identity_value_semantics() -> None:
    steam = SaveIdentity("2861478271", SaveSource.STEAM)
    local = SaveIdentity("Local Mod", SaveSource.LOCAL)
    assert steam.is_workshop and not local.is_workshop
    assert steam.as_tuple() == ("2861478271", "Steam")
    assert steam == SaveIdentity("2861478271", "Steam")
    assert steam != SaveIdentity("2861478271", "mod_local_source")
    assert sorted([local, steam]) == [steam, local]  # ordered by (name, source)
    assert len({steam, SaveIdentity("2861478271", "Steam")}) == 1
    with pytest.raises(AttributeError):
        steam.name = "x"  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize("name", ["测试模组", "Épée \U0001f525", "x" * 1000, "", "7"])
def test_save_identity_accepts_any_utf8_text(name: str) -> None:
    identity = SaveIdentity(name, SaveSource.LOCAL)
    assert identity.name == name


@pytest.mark.parametrize(
    ("name", "source"),
    [("a\x00b", "Steam"), ("a", "Ste\x00am"), ("\x00", "")],
    ids=["nul_in_name", "nul_in_source", "nul_only"],
)
def test_save_identity_rejects_nul(name: str, source: str) -> None:
    with pytest.raises(ValueError, match="NUL"):
        SaveIdentity(name, source)


@pytest.mark.parametrize(
    ("name", "source"),
    [("\ud800bad", "Steam"), ("ok", "\udcff"), ("mod\udc80name", "mod_local_source")],
    ids=["lone_high_surrogate", "lone_low_surrogate_in_source", "surrogateescape_byte"],
)
def test_save_identity_rejects_text_that_cannot_be_encoded(name: str, source: str) -> None:
    """A surrogateescape-decoded folder name can never be written into a save: fail at
    construction with a ValueError instead of a UnicodeEncodeError deep inside write_applied."""
    with pytest.raises(ValueError, match="UTF-8") as info:
        SaveIdentity(name, source)
    assert isinstance(info.value.__cause__, UnicodeEncodeError)


def test_identities_that_pass_construction_always_serialize() -> None:
    """The constructor is the only gate: whatever it accepts, write_applied can encode."""
    fmt = DsonV1Format()
    entries = (
        SaveIdentity("测试模组", SaveSource.LOCAL),
        SaveIdentity("Épée \U0001f525", SaveSource.LOCAL),
        SaveIdentity("", SaveSource.STEAM),
    )
    try:
        out = fmt.write_applied(standard_save(THREE_ENTRIES), entries)
    except DDManagerError as exc:  # pragma: no cover - would be a codec bug
        raise AssertionError(f"typed error on encodable identities: {exc}") from exc
    assert fmt.read_applied(out) == entries
