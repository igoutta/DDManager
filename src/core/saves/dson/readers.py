"""Readers: a ``{ "0": {name, source}, ... }`` object as identities, and named scalar fields.

They replace the heuristic byte scanner of dd2.py:395-484, ``dson_parse_named_name_source_object``
(821) and ``read_scalar_dson_fields`` (2740).
"""

from collections.abc import Collection

from src.core.errors import DsonFormatError
from src.core.ids import SaveIdentity
from src.core.saves.dson.document import object_meta1_index, parse
from src.core.saves.dson.fields import decode_scalar
from src.core.saves.dson.layout import DsonDocument
from src.core.saves.format import DsonScalar


def _read_child_identity(doc: DsonDocument, child: int, object_name: str) -> SaveIdentity:
    entry = doc.meta2[child]
    if not entry.is_object:
        raise DsonFormatError(
            f"Child {doc.name_of(child)!r} of {object_name!r} is not an object.",
            code="name_source_shape",
            offset=entry.offset,
        )
    values: dict[str, str] = {}
    for field in doc.children[child]:
        field_entry = doc.meta2[field]
        field_name = doc.name_of(field)
        if field_entry.is_object or field_name not in ("name", "source"):
            continue
        value = decode_scalar(doc.data, field_entry, doc.field_end(field))
        if isinstance(value, str):
            values.setdefault(field_name, value)
    if "name" not in values or "source" not in values:
        raise DsonFormatError(
            f"Child {doc.name_of(child)!r} of {object_name!r} lacks string fields name/source.",
            code="name_source_shape",
            offset=entry.offset,
        )
    return SaveIdentity(values["name"], values["source"])


def read_name_source_object(doc: DsonDocument, i: int) -> tuple[SaveIdentity, ...]:
    """Read object ``i`` whose children ``"0".."N-1"`` each hold string fields name and source.

    Replaces the heuristic byte scanner (dd2.py:395-484) and ``dson_parse_named_name_source_object``
    (dd2.py:821): UTF-8 throughout, no ASCII / 300-byte / 999-entry limits.  Child order is data
    order; child names are not interpreted.  Raises :class:`DsonFormatError` when a child is not
    an object or lacks a string ``name`` or ``source``.
    """
    object_meta1_index(doc, i)
    object_name = doc.name_of(i)
    return tuple(_read_child_identity(doc, child, object_name) for child in doc.children[i])


def read_scalars(raw: bytes, names: Collection[str]) -> dict[str, DsonScalar]:
    """Decode the scalar fields called ``names`` (replaces dd2.py:2740 ``read_scalar_dson_fields``).

    Raises :class:`DsonFormatError` on an invalid save instead of returning ``{}``.  Like the
    legacy, a name that occurs several times yields its last occurrence; object fields are skipped.
    """
    doc = parse(raw)
    wanted = set(names)
    out: dict[str, DsonScalar] = {}
    if not wanted:
        return out
    for i, entry in enumerate(doc.meta2):
        if entry.is_object:
            continue
        name = doc.name_of(i)
        if name in wanted:
            out[name] = decode_scalar(doc.data, entry, doc.field_end(i))
    return out
