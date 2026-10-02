"""The stack walk over every field, shared by the validator and the document builder.

Port of the walk inside ``dson_validate_editor_compatible`` (dd2.py:1224-1303).  ONE walker serves
every caller:

* **checked** mode (``checked=True``) reproduces the LEGACY verdict: it raises :class:`RejectError`
  with the first problem the legacy raised on, in the legacy order, and pops an object when
  ``seen == expected`` exactly as dd2.py:1297 did;
* **tolerant** mode (``checked=False``) never raises; it is what the splice primitive uses to
  index a freshly assembled document.  An object whose meta1 index is out of range is a leaf, an
  object left open at the end owns the rest of the file, and an object with a negative
  ``direct_children`` closes at once (``seen >= expected``).

Both modes record the direct-children index and one :class:`ObjectVisit` per object.  In checked
mode an out-of-range index or an overfull parent is a rejection before the tolerant degradations
could apply, so on a legacy-valid document the two modes see exactly the same tree: the walk the
validator accepted is the walk the document indexes.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.core.saves.dson.layout import Meta1, Meta2, meta2_name, string_hash
from src.core.saves.format import DsonProblem


class RejectError(Exception):
    """Internal: carries the first problem the legacy validator would have raised on."""

    def __init__(self, problem: DsonProblem) -> None:
        super().__init__(problem.message)
        self.problem = problem


@dataclass(slots=True)
class _Frame:
    """An open object on the walker's stack (dd2.py:1286-1291).

    ``running`` is the object's running number (its position among object fields).
    """

    index: int
    object_index: int
    expected: int
    running: int
    seen: int = 0


@dataclass(frozen=True, slots=True)
class ObjectVisit:
    """One object as the walk saw it: where it is and how many fields it really holds."""

    field_index: int
    object_index: int
    running_index: int
    descendants: int


@dataclass(frozen=True, slots=True)
class TreeWalk:
    """What one walk found: direct children per field, one visit per object, the object count."""

    children: tuple[tuple[int, ...], ...]
    visits: tuple[ObjectVisit, ...]
    object_count: int


# ------------------------------------------------------------------ per-field legacy checks


def check_field_name(data: bytes, entry: Meta2) -> str:
    """dd2.py:1229-1253: name length, termination, UTF-8 and hash; returns the decoded name.

    An empty name slice made the legacy raise ``IndexError``; that is a rejection here too.
    """
    offset = entry.offset
    name_length = entry.name_length
    if name_length <= 0:
        raise RejectError(
            DsonProblem("name_length", offset, f"{offset}: Field name has invalid length.")
        )
    name_end = offset + name_length
    if name_end > len(data):
        raise RejectError(
            DsonProblem(
                "name_past_data", offset, f"{offset}: Field name extends past the data block."
            )
        )
    name_bytes = data[offset:name_end]
    if not name_bytes or name_bytes[-1] != 0:
        raise RejectError(
            DsonProblem(
                "name_not_terminated", offset, f"{offset}: Field name is not null-terminated."
            )
        )
    if 0 in name_bytes[:-1]:
        raise RejectError(
            DsonProblem(
                "name_embedded_nul",
                offset,
                f"{offset}: Field name contains an unexpected null byte.",
            )
        )
    try:
        field_name = name_bytes[:-1].decode("utf-8")
    except UnicodeDecodeError:
        raise RejectError(
            DsonProblem("name_not_utf8", offset, f"{offset}: Field name is not valid UTF-8.")
        ) from None
    if string_hash(field_name) != entry.hash:
        raise RejectError(
            DsonProblem(
                "hash_mismatch", offset, f"{offset}: Field name hash mismatch for {field_name!r}."
            )
        )
    return field_name


def check_object_record(
    meta1: Sequence[Meta1], entry: Meta2, object_index: int, field_index: int, parent: int
) -> None:
    """dd2.py:1258-1272: the object's meta1 record must point back here and at the open parent."""
    offset = entry.offset
    if object_index >= len(meta1):
        raise RejectError(
            DsonProblem(
                "object_index_range",
                offset,
                f"{offset}: Object index {object_index} is outside meta1.",
            )
        )
    record = meta1[object_index]
    if record.meta2_index != field_index:
        raise RejectError(
            DsonProblem(
                "object_meta2_mismatch",
                offset,
                f"{offset}: Object metadata points to field {record.meta2_index}, "
                f"but this field is {field_index}.",
            )
        )
    if record.parent != parent:
        raise RejectError(
            DsonProblem(
                "object_parent_mismatch",
                offset,
                f"{offset}: Object parent {record.parent} does not match current parent {parent}.",
            )
        )


# ------------------------------------------------------------------ the walker


@dataclass(slots=True)
class _Walker:
    """State of one pre-order walk; see the module docstring for the two modes."""

    data: bytes
    meta1: Sequence[Meta1]
    meta2: Sequence[Meta2]
    checked: bool
    children: list[list[int]] = field(init=False)
    visits: list[ObjectVisit] = field(default_factory=list)
    stack: list[_Frame] = field(default_factory=list)
    running: int = -1

    def __post_init__(self) -> None:
        self.children = [[] for _ in self.meta2]

    def run(self) -> TreeWalk:
        for index, entry in enumerate(self.meta2):
            self._visit(index, entry)
        self._finish()
        self.visits.sort(key=lambda visit: visit.field_index)
        children = tuple(tuple(kids) for kids in self.children)
        return TreeWalk(children, tuple(self.visits), self.running + 1)

    def _visit(self, index: int, entry: Meta2) -> None:
        """One field, in the legacy order: name, object record, parent's count, push, pops."""
        object_index = entry.object_index
        if self.checked:
            check_field_name(self.data, entry)
            if object_index is not None:
                parent = self.stack[-1].running if self.stack else -1
                check_object_record(self.meta1, entry, object_index, index, parent)
        self._note_child(index, entry, is_object=object_index is not None)
        if object_index is not None:
            self._open(index, object_index)
        while self.stack and self._complete(self.stack[-1]):
            self._close(self.stack.pop(), index)

    def _note_child(self, index: int, entry: Meta2, *, is_object: bool) -> None:
        """dd2.py:1276-1283: count this field against the open object, or require a root object."""
        if self.stack:
            top = self.stack[-1]
            self.children[top.index].append(index)
            top.seen += 1
            if self.checked and top.seen > top.expected:
                raise RejectError(
                    DsonProblem(
                        "too_many_children",
                        entry.offset,
                        f"{entry.offset}: Object {self._name(top.index)!r} has too many children.",
                    )
                )
        elif self.checked and not is_object:
            raise RejectError(
                DsonProblem(
                    "first_field_not_object",
                    entry.offset,
                    f"{entry.offset}: First field is not a root object.",
                )
            )

    def _open(self, index: int, object_index: int) -> None:
        """dd2.py:1286-1291; in checked mode the index was already proven in range."""
        self.running += 1
        if 0 <= object_index < len(self.meta1):
            expected = self.meta1[object_index].direct_children
            self.stack.append(_Frame(index, object_index, expected, self.running))

    def _complete(self, frame: _Frame) -> bool:
        """dd2.py:1297 pops on equality; tolerant mode also closes a negative ``expected``."""
        if self.checked:
            return frame.seen == frame.expected
        return frame.seen >= frame.expected

    def _close(self, frame: _Frame, last_index: int) -> None:
        self.visits.append(
            ObjectVisit(frame.index, frame.object_index, frame.running, last_index - frame.index)
        )

    def _finish(self) -> None:
        """dd2.py:1299-1303: an object still open at the end is a rejection in checked mode."""
        if self.checked and self.stack:
            top = self.stack[-1]
            raise RejectError(
                DsonProblem(
                    "children_incomplete",
                    self.meta2[top.index].offset,
                    f"Object {self._name(top.index)!r} has {top.seen} of "
                    f"{top.expected} expected children.",
                )
            )
        while self.stack:
            self._close(self.stack.pop(), len(self.meta2) - 1)

    def _name(self, index: int) -> str:
        return meta2_name(self.data, self.meta2[index])


def walk_tree(
    data: bytes, meta1: Sequence[Meta1], meta2: Sequence[Meta2], *, checked: bool
) -> TreeWalk:
    """Walk every field once; see the module docstring for ``checked``."""
    return _Walker(data, meta1, meta2, checked).run()
