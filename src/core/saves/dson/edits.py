"""The public edits: rewrite or insert a ``{ "0": {name, source}, ... }`` object, patch a string.

Each one builds a block and hands it to :func:`.splice.splice`, which repairs every offset,
count and index after it.
"""

from collections.abc import Sequence

from src.core.errors import DsonFormatError, DsonUnsupportedError
from src.core.ids import SaveIdentity
from src.core.saves.dson.document import entry_at, object_meta1_index, parent_map, subtree_end
from src.core.saves.dson.fields import build_string_field
from src.core.saves.dson.flags import NO_FLAGS, EntryFlags, carry_flags, old_entry_flags, with_flag
from src.core.saves.dson.layout import DsonDocument, Meta1, Meta2, field_info, string_hash
from src.core.saves.dson.splice import Span, splice


def _build_name_source_block(
    name_bytes: bytes,
    entries: Sequence[SaveIdentity],
    flags: Sequence[EntryFlags],
    *,
    data_start: int,
    object_meta1: int,
    object_meta2: int,
    parent_meta1: int,
    object_entry: Meta2,
) -> tuple[bytes, list[Meta1], list[Meta2]]:
    """Build an object ``{ "0": {name, source}, ... }`` block.

    ``name_bytes`` is the object's NUL-terminated name.  Child ``k`` gets meta1 index
    ``object_meta1 + 1 + k`` and meta2 index ``object_meta2 + 1 + 3k``; each child is
    ``Meta1(object_meta1, ..., 2, 2)`` and the object itself ``(parent, object_meta2, N, 3N)``.
    ``flags[k]`` is the bit-31 state of child ``k``'s three info words (see :mod:`.flags`); new
    entries are written with all three bits clear.
    """
    data = bytearray(name_bytes)
    count = len(entries)
    meta1 = [Meta1(parent_meta1, object_meta2, count, count * 3)]
    meta2 = [object_entry]
    for k, (identity, kept) in enumerate(zip(entries, flags, strict=True)):
        child_name = str(k)
        child_offset = data_start + len(data)
        data.extend(child_name.encode("utf-8"))
        data.append(0)
        child_info = with_flag(field_info(child_name, object_meta1 + 1 + k), kept.child)
        meta2.append(Meta2(string_hash(child_name), child_offset, child_info))
        meta1.append(Meta1(object_meta1, object_meta2 + 1 + 3 * k, 2, 2))

        name_offset = data_start + len(data)
        data.extend(build_string_field("name", identity.name, name_offset))
        name_info = with_flag(field_info("name"), kept.name)
        meta2.append(Meta2(string_hash("name"), name_offset, name_info))

        source_offset = data_start + len(data)
        data.extend(build_string_field("source", identity.source, source_offset))
        source_info = with_flag(field_info("source"), kept.source)
        meta2.append(Meta2(string_hash("source"), source_offset, source_info))
    return bytes(data), meta1, meta2


def _descendant_objects(doc: DsonDocument, i: int, end: int) -> list[int]:
    """Sorted meta1 indices of the object fields strictly inside subtree ``[i, end)``."""
    return sorted(
        index for j in range(i + 1, end) if (index := doc.meta2[j].object_index) is not None
    )


def replace_name_source_object(
    doc: DsonDocument, i: int, entries: Sequence[SaveIdentity]
) -> DsonDocument:
    """Rewrite object ``i`` as ``{ "0": {name, source}, ... }`` for ``entries``.

    The object's own
    meta2 record and name bytes are kept verbatim, its meta1 becomes ``(parent, i, N, 3N)``, the
    old subtree is dropped, ancestors get ``all_children += delta`` and later fields are rebuilt.
    Bit-31 preservation: an entry that already existed keeps bit 31 of its three info
    words (DD Manager 0.2.x cleared it; see :mod:`.flags`), new entries get it clear.
    Raises :class:`DsonUnsupportedError` (``nested_object_span``) when the subtree's meta1
    records are not the contiguous range right after the object's own record.
    """
    wanted = tuple(entries)
    object_meta1 = object_meta1_index(doc, i)
    entry = doc.meta2[i]
    end = subtree_end(doc, i)
    descendants = _descendant_objects(doc, i, end)
    expected = list(range(object_meta1 + 1, object_meta1 + 1 + len(descendants)))
    if descendants != expected:
        raise DsonUnsupportedError(
            f"object {doc.name_of(i)!r} has descendant objects at meta1 {descendants} instead of"
            f" the contiguous range {expected}",
            code="nested_object_span",
            field=doc.name_of(i),
            offset=entry.offset,
        )
    parent_meta1 = doc.meta1[object_meta1].parent
    name_bytes = doc.data[entry.offset : entry.offset + entry.name_length]
    block, meta1, meta2 = _build_name_source_block(
        name_bytes,
        wanted,
        carry_flags(old_entry_flags(doc, i), wanted),
        data_start=entry.offset,
        object_meta1=object_meta1,
        object_meta2=i,
        parent_meta1=parent_meta1,
        object_entry=entry,
    )
    span = Span(object_meta1, object_meta1 + 1 + len(descendants), i, end)
    return splice(doc, span, block, meta1, meta2, parent_meta1=parent_meta1, parent_direct_delta=0)


def _anchor_parent(doc: DsonDocument, before: int) -> tuple[int, int]:
    """``(anchor meta1 index, its parent's meta1 index)``; refuses scalars and the root."""
    entry = entry_at(doc, before)
    anchor_meta1 = entry.object_index
    if anchor_meta1 is None or anchor_meta1 >= len(doc.meta1):
        raise DsonUnsupportedError(
            f"{doc.name_of(before)!r} is not marked as an object in metadata.",
            code="no_anchor",
            field=doc.name_of(before),
            offset=entry.offset,
        )
    parent_meta1 = doc.meta1[anchor_meta1].parent
    if parent_meta1 < 0:
        raise DsonUnsupportedError(
            f"{doc.name_of(before)!r} is a root object; the new object needs a parent object.",
            code="no_anchor",
            field=doc.name_of(before),
            offset=entry.offset,
        )
    return anchor_meta1, parent_meta1


def insert_name_source_object(
    doc: DsonDocument, *, before: int, name: str, entries: Sequence[SaveIdentity]
) -> DsonDocument:
    """Insert a new ``{ "0": {name, source}, ... }`` object right before object ``before``.

    The new object takes the
    anchor's meta1 index, meta2 index and data offset (the anchor and everything after it shift),
    the anchor's parent gets ``direct_children += 1`` and ``all_children += 1 + 3N``.  Raises
    :class:`DsonUnsupportedError` (``no_anchor``) when ``before`` is not an object or has no
    parent object (inserting before the root would create a second root).
    """
    if "\x00" in name:
        raise ValueError("DSON field name must not contain NUL")
    wanted = tuple(entries)
    anchor_meta1, parent_meta1 = _anchor_parent(doc, before)
    offset = doc.meta2[before].offset
    object_entry = Meta2(string_hash(name), offset, field_info(name, anchor_meta1))
    block, meta1, meta2 = _build_name_source_block(
        name.encode("utf-8") + b"\x00",
        wanted,
        [NO_FLAGS] * len(wanted),
        data_start=offset,
        object_meta1=anchor_meta1,
        object_meta2=before,
        parent_meta1=parent_meta1,
        object_entry=object_entry,
    )
    span = Span(anchor_meta1, anchor_meta1, before, before)
    return splice(doc, span, block, meta1, meta2, parent_meta1=parent_meta1, parent_direct_delta=1)


def patch_scalar_string(doc: DsonDocument, i: int, value: str) -> DsonDocument:
    """Replace scalar field ``i`` with a string payload.

    The meta2 record is rebuilt from ``field_info(name)`` (a set bit 31
    is dropped), no meta1 record changes, and later fields are rebuilt for their new offsets.
    """
    entry = entry_at(doc, i)
    if entry.is_object:
        raise DsonFormatError(
            f"{doc.name_of(i)!r} is an object field, not a scalar string field.",
            code="not_a_scalar",
            offset=entry.offset,
        )
    name = doc.name_of(i)
    block = build_string_field(name, value, entry.offset)
    meta2 = [Meta2(string_hash(name), entry.offset, field_info(name))]
    parent = parent_map(doc)[i]
    parent_meta1 = doc.meta2[parent].object_index if parent >= 0 else None
    span = Span(0, 0, i, i + 1)
    return splice(
        doc,
        span,
        block,
        (),
        meta2,
        parent_meta1=-1 if parent_meta1 is None else parent_meta1,
        parent_direct_delta=0,
    )
