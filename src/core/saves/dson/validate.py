"""The two validation levels: LEGACY (the verdict of dd2.py:1202-1309) and STRICT (extra checks).

:func:`legacy_walk` is also the gate :func:`.document.parse` runs; it hands back the checked walk
so the document's children index comes from the very walk that accepted it.
"""

from collections.abc import Sequence

from src.core.errors import DsonFormatError
from src.core.saves.dson.layout import (
    DSON_MAGIC,
    HEADER_SIZE,
    META1_SIZE,
    META2_SIZE,
    DsonHeader,
    Meta1,
    Meta2,
    data_block,
    meta2_name,
    read_tables,
)
from src.core.saves.dson.walk import ObjectVisit, RejectError, TreeWalk, walk_tree
from src.core.saves.format import DsonProblem, SaveValidationReport

# ------------------------------------------------------------------ LEGACY level


def _check_layout(raw: bytes, header: DsonHeader) -> None:
    """dd2.py:1208-1218: the four header/table layout checks, in order."""
    if header.data_offset + header.data_length != len(raw):
        raise RejectError(
            DsonProblem(
                "file_size_mismatch", 60, "Header data offset/length does not match the file size."
            )
        )
    if header.meta1_size != header.meta1_count * META1_SIZE:
        raise RejectError(
            DsonProblem("meta1_size_mismatch", 16, "Meta1 size does not match the object count.")
        )
    if header.meta2_offset != header.meta1_offset + header.meta1_size:
        raise RejectError(
            DsonProblem(
                "meta2_offset_mismatch", 48, "Meta2 offset does not follow the meta1 block."
            )
        )
    if header.data_offset != header.meta2_offset + header.meta2_count * META2_SIZE:
        raise RejectError(
            DsonProblem("data_offset_mismatch", 60, "Data offset does not follow the meta2 block.")
        )


def _check_offsets_sorted(meta2: Sequence[Meta2]) -> None:
    """dd2.py:1220-1222 (non-strict: equal offsets are accepted)."""
    offsets = [entry.offset for entry in meta2]
    if offsets != sorted(offsets):
        bad = next(k for k in range(1, len(offsets)) if offsets[k] < offsets[k - 1])
        raise RejectError(
            DsonProblem("offsets_unsorted", offsets[bad], "Meta2 field offsets are not sorted.")
        )


def legacy_walk(
    raw: bytes, header: DsonHeader, meta1: Sequence[Meta1], meta2: Sequence[Meta2]
) -> TreeWalk:
    """Every check of ``dson_validate_editor_compatible`` (dd2.py:1202-1309), in its order.

    Raises :class:`RejectError` with the first problem the legacy would have raised on; the
    accept/reject verdict is identical, arithmetic included.  Returns the checked walk.
    """
    _check_layout(raw, header)
    _check_offsets_sorted(meta2)
    walk = walk_tree(data_block(raw, header), meta1, meta2, checked=True)
    if walk.object_count != header.meta1_count:
        raise RejectError(
            DsonProblem(
                "object_count_mismatch",
                20,
                f"Object count mismatch: parsed {walk.object_count}, header says"
                f" {header.meta1_count}.",
            )
        )
    return walk


# ------------------------------------------------------------------ STRICT level


def _strict_magic_problems(raw: bytes) -> list[DsonProblem]:
    if raw[:4] == DSON_MAGIC:
        return []
    return [
        DsonProblem(
            "bad_magic",
            0,
            f"Unexpected magic {bytes(raw[:4]).hex()!r}; expected {DSON_MAGIC.hex()!r}"
            " (the expected value is unverified against real saves).",
        )
    ]


def _strict_header_problems(header: DsonHeader) -> list[DsonProblem]:
    out: list[DsonProblem] = []
    if header.header_length != HEADER_SIZE:
        out.append(
            DsonProblem(
                "header_length", 8, f"Header length is {header.header_length}, expected 64."
            )
        )
    if header.meta1_offset != HEADER_SIZE:
        out.append(
            DsonProblem("meta1_offset", 24, f"Meta1 offset is {header.meta1_offset}, expected 64.")
        )
    return out


def _strict_offset_problems(meta2: Sequence[Meta2]) -> list[DsonProblem]:
    return [
        DsonProblem(
            "offsets_not_increasing",
            meta2[k].offset,
            f"{meta2[k].offset}: Field offset does not increase past the previous field"
            f" at {meta2[k - 1].offset}.",
        )
        for k in range(1, len(meta2))
        if meta2[k].offset <= meta2[k - 1].offset
    ]


def _strict_root_problems(meta1: Sequence[Meta1]) -> list[DsonProblem]:
    roots = sum(1 for entry in meta1 if entry.parent == -1)
    if roots == 1:
        return []
    return [DsonProblem("root_count", 0, f"Expected exactly one root object, found {roots}.")]


def _strict_visit_problems(
    data: bytes, meta1: Sequence[Meta1], meta2: Sequence[Meta2], visits: Sequence[ObjectVisit]
) -> list[DsonProblem]:
    """meta1 index == running object index, and exact ``all_children`` per object."""
    out: list[DsonProblem] = []
    for visit in visits:
        entry = meta2[visit.field_index]
        if visit.object_index != visit.running_index:
            out.append(
                DsonProblem(
                    "meta1_order",
                    entry.offset,
                    f"{entry.offset}: Object {meta2_name(data, entry)!r} uses meta1 index"
                    f" {visit.object_index} but is object number {visit.running_index}.",
                )
            )
        declared = meta1[visit.object_index].all_children
        if declared != visit.descendants:
            out.append(
                DsonProblem(
                    "all_children_mismatch",
                    entry.offset,
                    f"{entry.offset}: Object {meta2_name(data, entry)!r} declares"
                    f" all_children={declared} but has {visit.descendants} descendant fields.",
                )
            )
    return out


def _problem_of(exc: DsonFormatError) -> DsonProblem:
    offset = exc.details.get("offset")
    return DsonProblem(exc.code, offset if isinstance(offset, int) else 0, exc.message)


def validate(raw: bytes) -> SaveValidationReport:
    """Validate without raising.

    LEGACY level reproduces the verdict of ``dson_validate_editor_compatible`` (dd2.py:1202-1309):
    it accepts exactly what the legacy accepted.  STRICT level adds ``bad_magic``, the 64-byte
    header layout, strictly increasing meta2 offsets, meta1 index == running object index, exact
    ``all_children`` per object and exactly one root.
    """
    strict = _strict_magic_problems(raw)
    try:
        header, meta1, meta2 = read_tables(raw)
    except DsonFormatError as exc:
        return SaveValidationReport((_problem_of(exc),), tuple(strict))
    strict.extend(_strict_header_problems(header))
    try:
        walk = legacy_walk(raw, header, meta1, meta2)
    except RejectError as exc:
        return SaveValidationReport((exc.problem,), tuple(strict))
    strict.extend(_strict_offset_problems(meta2))
    strict.extend(_strict_root_problems(meta1))
    strict.extend(_strict_visit_problems(data_block(raw, header), meta1, meta2, walk.visits))
    return SaveValidationReport((), tuple(strict))
