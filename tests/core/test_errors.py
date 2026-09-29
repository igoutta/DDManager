"""DDManagerError: the class-level family, the per-instance code, details and str()."""

import pytest

from src.core.errors import (
    AmbiguousSaveFormatError,
    DDManagerError,
    DsonFormatError,
    DsonUnsupportedError,
    RoundTripError,
    SaveFormatError,
    UnknownSaveFormatError,
)

FAMILIES: dict[type[DDManagerError], str] = {
    DDManagerError: "error",
    SaveFormatError: "save_format",
    UnknownSaveFormatError: "unknown_save_format",
    AmbiguousSaveFormatError: "ambiguous_save_format",
    DsonFormatError: "dson_format",
    DsonUnsupportedError: "dson_unsupported",
    RoundTripError: "round_trip",
}


@pytest.mark.parametrize("cls", list(FAMILIES), ids=lambda cls: cls.__name__)
def test_family_and_message_key(cls: type[DDManagerError]) -> None:
    family = FAMILIES[cls]
    assert cls.family == family
    expected_key = "error.generic" if cls is DDManagerError else f"error.{family}"
    assert cls.message_key == expected_key
    exc = cls("plain")
    assert exc.code == family  # no reason given: the code IS the family
    assert exc.message == "plain"
    assert exc.details == {}
    assert exc.args == ("plain",)
    assert str(exc) == f"[{family}] plain"
    assert isinstance(exc, DDManagerError)


def test_code_keyword_narrows_the_instance_only() -> None:
    exc = DsonUnsupportedError("m", code="no_anchor", offset=12)
    assert exc.code == "no_anchor"
    assert type(exc).family == "dson_unsupported"
    assert DsonUnsupportedError.family == "dson_unsupported"
    assert exc.details == {"code": "no_anchor", "offset": 12}
    assert str(exc) == "[no_anchor] m"
    assert repr(exc) == "DsonUnsupportedError('m')"
    # another instance of the same class is untouched
    assert DsonUnsupportedError("other").code == "dson_unsupported"


@pytest.mark.parametrize("code", ["", None, 7], ids=["empty", "none", "int"])
def test_empty_or_non_string_code_keeps_the_family(code: object) -> None:
    exc = RoundTripError("x", code=code)
    assert exc.code == "round_trip"
    assert exc.details["code"] == code
    assert str(exc) == "[round_trip] x"


def test_hierarchy_supports_narrowing_by_family() -> None:
    for cls in (UnknownSaveFormatError, AmbiguousSaveFormatError, DsonFormatError):
        assert issubclass(cls, SaveFormatError)
    for cls in (DsonUnsupportedError, RoundTripError):
        assert issubclass(cls, SaveFormatError)
    with pytest.raises(SaveFormatError) as info:
        raise DsonUnsupportedError("m", code="unsafe_realign")
    assert info.value.code == "unsafe_realign"
    with pytest.raises(DDManagerError):
        raise UnknownSaveFormatError("m")
