"""``parse`` / ``serialize`` and the document-level tree lookups the edits build on.

:func:`serialize` is THE only serializer (every edit and every round trip goes
through it).
"""

import struct
from collections.abc import Sequence

from src.core.errors import DsonFormatError
from src.core.saves.dson.layout import (
    HEADER_SIZE,
    META1_STRUCT,
    META2_STRUCT,
    DsonDocument,
    DsonHeader,
    Meta1,
    Meta2,
    data_block,
    read_tables,
    refresh_header,
)
from src.core.saves.dson.validate import structural_walk
from src.core.saves.dson.walk import RejectError, walk_tree
from src.core.saves.format import DsonProblem


def _format_error(problem: DsonProblem) -> DsonFormatError:
    return DsonFormatError(problem.message, code=problem.code, offset=problem.offset)


def make_document(
    header: DsonHeader,
    meta1: Sequence[Meta1],
    meta2: Sequence[Meta2],
    data: bytes,
    children: tuple[tuple[int, ...], ...] | None = None,
) -> DsonDocument:
    """Assemble a document; without ``children`` the tolerant walk indexes the tables."""
    if children is None:
        children = walk_tree(data, meta1, meta2, checked=False).children
    return DsonDocument(
        header=refresh_header(header, len(meta1), len(meta2), len(data)),
        meta1=tuple(meta1),
        meta2=tuple(meta2),
        data=data,
        children=children,
    )


def parse(raw: bytes) -> DsonDocument:
    """Parse a structurally valid save into a :class:`DsonDocument`.

    Raises :class:`DsonFormatError` on any layout problem: the STRUCTURAL validator's
    checks plus the ``header_length == 64`` / ``meta1_offset == 64`` gate the edits need.
    ``serialize(parse(raw)) == raw`` for every accepted input.
    """
    header, meta1, meta2 = read_tables(raw)
    try:
        walk = structural_walk(raw, header, meta1, meta2)
    except RejectError as exc:
        raise _format_error(exc.problem) from None
    if header.header_length != HEADER_SIZE or header.meta1_offset != HEADER_SIZE:
        raise DsonFormatError(
            "Unsupported DSON header layout.", code="unsupported_header_layout", offset=8
        )
    if header.meta1_count < 0 or header.meta2_count < 0:
        raise DsonFormatError("Negative table count in header.", code="negative_count", offset=20)
    return make_document(header, meta1, meta2, data_block(raw, header), walk.children)


def serialize(doc: DsonDocument) -> bytes:
    """``header.raw`` with the six size/offset fields recomputed, then meta1, meta2 and data."""
    header = refresh_header(doc.header, len(doc.meta1), len(doc.meta2), len(doc.data))
    try:
        meta1 = b"".join(
            META1_STRUCT.pack(e.parent, e.meta2_index, e.direct_children, e.all_children)
            for e in doc.meta1
        )
        meta2 = b"".join(META2_STRUCT.pack(e.hash, e.offset, e.info) for e in doc.meta2)
    except struct.error as exc:
        raise DsonFormatError(
            f"Table value does not fit in 32 bits: {exc}", code="table_overflow", offset=64
        ) from exc
    return header.raw + meta1 + meta2 + doc.data


# ------------------------------------------------------------------ tree lookups


def entry_at(doc: DsonDocument, i: int) -> Meta2:
    """``doc.meta2[i]`` with a :class:`DsonFormatError` instead of ``IndexError``."""
    if not 0 <= i < len(doc.meta2):
        raise DsonFormatError(
            f"Field index {i} is out of range.", code="index_out_of_range", offset=0
        )
    return doc.meta2[i]


def object_meta1_index(doc: DsonDocument, i: int) -> int:
    """The meta1 index of object field ``i``; refuses scalars and dangling indices."""
    entry = entry_at(doc, i)
    object_index = entry.object_index
    if object_index is None:
        raise DsonFormatError(
            f"{doc.name_of(i)!r} is not marked as an object in metadata.",
            code="not_an_object",
            offset=entry.offset,
        )
    if object_index >= len(doc.meta1):
        raise DsonFormatError(
            f"{doc.name_of(i)!r} points outside the meta1 table.",
            code="object_index_range",
            offset=entry.offset,
        )
    return object_index


def subtree_end(doc: DsonDocument, i: int) -> int:
    """One past the last descendant field of ``i`` (fields are in pre-order)."""
    end = i + 1
    stack = [i]
    while stack:
        node = stack.pop()
        for child in doc.children[node]:
            end = max(end, child + 1)
            stack.append(child)
    return end


def parent_map(doc: DsonDocument) -> list[int]:
    """meta2 index -> parent meta2 index (-1 for top-level fields)."""
    parents = [-1] * len(doc.meta2)
    for parent, kids in enumerate(doc.children):
        for child in kids:
            parents[child] = parent
    return parents
