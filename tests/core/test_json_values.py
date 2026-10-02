"""The shared JSON value alias and tolerant field reader (src/core/json_values.py)."""

from src.core.json_values import TypedFields, as_json


def _fields(obj: dict[str, object]) -> tuple[TypedFields, list[tuple[str, str]]]:
    reports: list[tuple[str, str]] = []
    return TypedFields(obj, lambda key, expected: reports.append((key, expected))), reports


def test_present_values_of_the_right_type_are_returned_without_a_report() -> None:
    fields, reports = _fields({"s": "x", "b": False, "l": [1], "d": {"k": 1}, "o": "y"})
    assert fields.str_("s") == "x"
    assert fields.bool_("b", default=True) is False
    assert fields.list_("l") == [1]
    assert fields.dict_("d") == {"k": 1}
    assert fields.optional_str("o") == "y"
    assert reports == []


def test_absent_or_null_values_yield_defaults_silently() -> None:
    fields, reports = _fields({"n": None})
    assert fields.str_("n", "dflt") == "dflt"
    assert fields.str_("missing") == ""
    assert fields.optional_str("n") is None
    assert fields.bool_("missing", default=True) is True
    assert fields.list_("n") == []
    assert fields.dict_("missing") == {}
    assert reports == []


def test_wrong_types_yield_defaults_and_one_report_each() -> None:
    fields, reports = _fields({"s": 1, "b": "yes", "l": "x", "d": [], "o": 2.5})
    assert fields.str_("s", "dflt") == "dflt"
    assert fields.bool_("b", default=False) is False
    assert fields.list_("l") == []
    assert fields.dict_("d") == {}
    assert fields.optional_str("o") is None
    assert [key for key, _ in reports] == ["s", "b", "l", "d", "o"]
    assert all(expected for _, expected in reports)


def test_bool_is_not_accepted_as_text_and_text_is_not_a_bool() -> None:
    fields, reports = _fields({"s": True, "b": "true"})
    assert fields.str_("s") == ""
    assert fields.bool_("b", default=False) is False
    assert len(reports) == 2


def test_extra_keeps_unknown_keys_in_document_order() -> None:
    fields, _ = _fields({"a": 1, "known": 2, "z": [1, {"x": None}], "m": 0})
    assert fields.extra(frozenset({"known"})) == (("a", 1), ("z", [1, {"x": None}]), ("m", 0))


def test_as_json_narrows_json_shapes_and_stringifies_anything_else() -> None:
    value = {"a": [1, 2.5, "s", None, True], "b": {"c": {}}}
    assert as_json(value) == value
    assert as_json((1, 2)) == "(1, 2)"
    assert as_json({1: "x"}) == {"1": "x"}
