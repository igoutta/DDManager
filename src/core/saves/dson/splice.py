"""The ONE splice primitive every edit goes through (resize, insert and scalar patch share it).

:func:`splice` is the common core of the object rewrite, the object insert and the scalar
patch.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from src.core.errors import DsonFormatError
from src.core.saves.dson.document import make_document
from src.core.saves.dson.fields import assert_shift_safe, rebuild_field_block
from src.core.saves.dson.layout import DsonDocument, Meta1, Meta2, set_object_index_in_info


@dataclass(frozen=True, slots=True)
class Span:
    """The region a splice replaces: meta1 ``[m1_start, m1_end)`` and meta2 ``[m2_start, m2_end)``.

    The data region is implied: from ``field_offset(m2_start)`` to ``field_offset(m2_end)``.
    """

    m1_start: int
    m1_end: int
    m2_start: int
    m2_end: int


def _bump_ancestors(meta1: list[Meta1], node: int, *, direct_delta: int, all_delta: int) -> None:
    """Parent ``direct_children``, ancestors' ``all_children``."""
    remaining = len(meta1) + 1
    while node >= 0:
        remaining -= 1
        if remaining < 0:
            raise DsonFormatError("Parent pointers form a cycle.", code="parent_cycle", offset=0)
        if node >= len(meta1):
            raise DsonFormatError(
                f"Parent pointer {node} is outside the meta1 table.",
                code="parent_out_of_range",
                offset=0,
            )
        entry = meta1[node]
        meta1[node] = replace(
            entry,
            direct_children=entry.direct_children + direct_delta,
            all_children=entry.all_children + all_delta,
        )
        direct_delta = 0
        node = entry.parent


def _rebuild_tail(
    doc: DsonDocument, span: Span, cursor: int, meta1_delta: int, *, renumber_objects: bool
) -> tuple[list[bytes], list[Meta2]]:
    """Rebuild every field after the span at its new offset.

    With ``renumber_objects`` every object at or past ``span.m1_end`` gets its meta1 index shifted
    by ``meta1_delta`` through :func:`set_object_index_in_info`, which also normalises the info
    word (only bit 31, bit 0, the name length and the index survive).  Resizes and inserts
    do that even for a zero delta; the scalar patch copies every info verbatim, so it passes
    ``False``.
    """
    parts: list[bytes] = []
    tail: list[Meta2] = []
    for j in range(span.m2_end, len(doc.meta2)):
        entry = doc.meta2[j]
        assert_shift_safe(doc, j, cursor)
        rebuilt = rebuild_field_block(doc.data, entry, doc.field_end(j), cursor)
        object_index = entry.object_index
        info = entry.info
        if renumber_objects and object_index is not None and object_index >= span.m1_end:
            info = set_object_index_in_info(info, object_index + meta1_delta)
        tail.append(Meta2(entry.hash, cursor, info))
        parts.append(rebuilt)
        cursor += len(rebuilt)
    return parts, tail


def _shifted_meta1(
    doc: DsonDocument, span: Span, block: Sequence[Meta1], d1: int, d2: int
) -> list[Meta1]:
    """Preserved records shift past the span by the count deltas."""

    def shifted(entry: Meta1) -> Meta1:
        parent = entry.parent + d1 if entry.parent >= span.m1_end else entry.parent
        meta2_index = (
            entry.meta2_index + d2 if entry.meta2_index >= span.m2_end else entry.meta2_index
        )
        return Meta1(parent, meta2_index, entry.direct_children, entry.all_children)

    return [
        *(shifted(e) for e in doc.meta1[: span.m1_start]),
        *block,
        *(shifted(e) for e in doc.meta1[span.m1_end :]),
    ]


def splice(
    doc: DsonDocument,
    span: Span,
    block_data: bytes,
    block_meta1: Sequence[Meta1],
    block_meta2: Sequence[Meta2],
    *,
    parent_meta1: int,
    parent_direct_delta: int,
) -> DsonDocument:
    """Replace ``span`` with a prebuilt block and repair everything after it.

    This is the common core of the object rewrite, the object insert and the scalar patch:

    * preserved meta1 records with ``parent >= m1_end`` / ``meta2_index >= m2_end`` shift by the
      meta1 / meta2 count deltas;
    * ``parent_meta1`` gets ``direct_children += parent_direct_delta`` and every ancestor from it
      upwards gets ``all_children += meta2 delta``;
    * every field after the span is rebuilt for its new offset with :func:`rebuild_field_block`
      (guarded by :func:`assert_shift_safe`) and, when the splice touches meta1 at all, object
      fields pointing at or past ``m1_end`` get their meta1 index rewritten.
    """
    block_meta1 = tuple(block_meta1)
    block_meta2 = tuple(block_meta2)
    d1 = len(block_meta1) - (span.m1_end - span.m1_start)
    d2 = len(block_meta2) - (span.m2_end - span.m2_start)
    # Later objects' info is rewritten in every path that edits meta1 (resize, insert), even
    # when the count did not change, but never in the scalar patch.
    renumber_objects = bool(block_meta1) or span.m1_start != span.m1_end

    meta1 = _shifted_meta1(doc, span, block_meta1, d1, d2)
    parent = parent_meta1 + d1 if parent_meta1 >= span.m1_end else parent_meta1
    _bump_ancestors(meta1, parent, direct_delta=parent_direct_delta, all_delta=d2)

    start = doc.field_offset(span.m2_start)
    parts, tail = _rebuild_tail(
        doc, span, start + len(block_data), d1, renumber_objects=renumber_objects
    )
    data = b"".join([doc.data[:start], block_data, *parts])
    meta2 = [*doc.meta2[: span.m2_start], *block_meta2, *tail]
    return make_document(doc.header, meta1, meta2, data)
