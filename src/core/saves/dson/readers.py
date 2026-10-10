"""Readers: a ``{ "0": {name, source}, ... }`` object as identities, and named scalar fields.

They read through the parsed document, never a byte scan.
"""

from collections.abc import Collection

from src.core.errors import DsonFormatError
from src.core.ids import SaveIdentity
from src.core.saves.dson.document import object_meta1_index, parse
from src.core.saves.dson.fields import decode_scalar
from src.core.saves.dson.layout import DsonDocument
from src.core.saves.format import DsonScalar


def child_identity(doc: DsonDocument, child: int) -> tuple[SaveIdentity, int, int] | None:
    """``(identity, name field, source field)`` of object ``child``, or ``None``.

    The identity comes from the first string field called ``name`` and the first called
    ``source`` among the child's direct fields (objects and other names are ignored).  ``None``
    when ``child`` is not an object or lacks either: the shape the readers refuse.
    """
    if not doc.meta2[child].is_object:
        return None
    found: dict[str, tuple[int, str]] = {}
    for field in doc.children[child]:
        entry = doc.meta2[field]
        field_name = doc.name_of(field)
        if entry.is_object or field_name in found or field_name not in ("name", "source"):
            continue
        value = decode_scalar(doc.data, entry, doc.field_end(field))
        if isinstance(value, str):
            found[field_name] = (field, value)
    if "name" not in found or "source" not in found:
        return None
    (name_field, name), (source_field, source) = found["name"], found["source"]
    return SaveIdentity(name, source), name_field, source_field


def _read_child_identity(doc: DsonDocument, child: int, object_name: str) -> SaveIdentity:
    entry = doc.meta2[child]
    if not entry.is_object:
        raise DsonFormatError(
            f"Child {doc.name_of(child)!r} of {object_name!r} is not an object.",
            code="name_source_shape",
            offset=entry.offset,
        )
    found = child_identity(doc, child)
    if found is None:
        raise DsonFormatError(
            f"Child {doc.name_of(child)!r} of {object_name!r} lacks string fields name/source.",
            code="name_source_shape",
            offset=entry.offset,
        )
    return found[0]


def read_name_source_object(doc: DsonDocument, i: int) -> tuple[SaveIdentity, ...]:
    """Read object ``i`` whose children ``"0".."N-1"`` each hold string fields name and source.

    UTF-8 throughout, no ASCII / 300-byte / 999-entry limits.  Child order is data
    order; child names are not interpreted.  Raises :class:`DsonFormatError` when a child is not
    an object or lacks a string ``name`` or ``source``.
    """
    object_meta1_index(doc, i)
    object_name = doc.name_of(i)
    return tuple(_read_child_identity(doc, child, object_name) for child in doc.children[i])


def read_scalars(raw: bytes, names: Collection[str]) -> dict[str, DsonScalar]:
    """Decode the scalar fields called ``names``.

    Raises :class:`DsonFormatError` on an invalid save instead of returning ``{}``.
    A name that occurs several times yields its last occurrence; object fields are skipped.
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
