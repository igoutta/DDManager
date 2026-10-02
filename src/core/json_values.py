"""The JSON value alias and the one tolerant field reader shared by every JSON file format.

``json.loads`` already yields :data:`JsonValue` shapes; :func:`as_json` only narrows the static
type.  :class:`TypedFields` reads one object with "wrong type -> default plus a report" semantics
so the rules file, the load-order file and the state file all repair the same way.
"""

from collections.abc import Callable, Mapping

type JsonValue = bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None
type JsonObject = dict[str, JsonValue]
type Extra = tuple[tuple[str, JsonValue], ...]
"""Unknown keys of an object, kept in document order so a round trip loses nothing."""

type Report = Callable[[str, str], None]
"""``report(key, expected)``: called once per field whose value has the wrong type."""


def as_json(value: object) -> JsonValue:
    """Narrow a ``json.loads`` result to :data:`JsonValue` (it already is one by construction)."""
    if isinstance(value, dict):
        return {str(key): as_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [as_json(item) for item in value]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


class TypedFields:
    """Typed, tolerant access to one JSON object; a wrong type yields the default and a report.

    ``None`` always means "absent" and yields the default silently.
    """

    __slots__ = ("obj", "report")

    def __init__(self, obj: Mapping[str, object], report: Report) -> None:
        self.obj = obj
        self.report = report

    def str_(self, key: str, default: str = "") -> str:
        value = self.obj.get(key)
        if value is None:
            return default
        if isinstance(value, str):
            return value
        self.report(key, "text")
        return default

    def optional_str(self, key: str) -> str | None:
        value = self.obj.get(key)
        if value is None:
            return None
        if isinstance(value, str):
            return value
        self.report(key, "text or null")
        return None

    def bool_(self, key: str, *, default: bool) -> bool:
        value = self.obj.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        self.report(key, "true or false")
        return default

    def list_(self, key: str) -> list[object]:
        value = self.obj.get(key)
        if value is None:
            return []
        if isinstance(value, list):
            return value
        self.report(key, "a list")
        return []

    def dict_(self, key: str) -> dict[str, object]:
        value = self.obj.get(key)
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        self.report(key, "an object")
        return {}

    def extra(self, known: frozenset[str]) -> Extra:
        """Every key not in ``known``, narrowed to JSON values, in document order."""
        return tuple((key, as_json(value)) for key, value in self.obj.items() if key not in known)
