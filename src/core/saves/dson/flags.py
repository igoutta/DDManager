"""Bit 31 of a meta2 ``info`` word: an unknown game flag the codec preserves per applied entry.

The game sets bit 31 on some fields it writes - sporadically, inside ``applied_ugcs_1_0`` on child
objects, ``name`` and ``source`` words alike - and loads a save either way.  It is outside every
field the format defines (bit 0, bits 2-10, bits 11-30), so nothing here
interprets it: "never alter what we don't understand".

Outside the applied block the splice keeps every info word's bit 31 (``rebuild_field_block`` and
``set_object_index_in_info`` both preserve it).  Inside the block DD Manager 0.2.x rebuilt every
word from scratch, always clearing the bit; this module lets
:func:`.edits.replace_name_source_object` carry each entry's three bits over instead:

* an entry whose ``(name, source)`` identity already existed in the old block keeps the original
  bit-31 state of its child object word, its ``name`` word and its ``source`` word;
* matching is positional among duplicates (first old occurrence -> first new occurrence);
* a new entry gets all three bits clear (as 0.2.x always did).
"""

from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from src.core.ids import SaveIdentity
from src.core.saves.dson.layout import DsonDocument
from src.core.saves.dson.readers import child_identity

INFO_FLAG_BIT: Final = 0x80000000
_INFO_MASK: Final = 0x7FFFFFFF


@dataclass(frozen=True, slots=True)
class EntryFlags:
    """Bit 31 of the three meta2 words of one applied entry: child object, ``name``, ``source``."""

    child: bool = False
    name: bool = False
    source: bool = False


NO_FLAGS: Final = EntryFlags()
"""What a new entry gets: every bit clear."""


def has_flag(info: int) -> bool:
    """Whether bit 31 is set in a signed i32 ``info`` word."""
    return bool(info & INFO_FLAG_BIT)


def with_flag(info: int, flag: bool) -> int:
    """``info`` with bit 31 set to ``flag`` (every other bit untouched), as a signed i32."""
    bits = (info & _INFO_MASK) | (INFO_FLAG_BIT if flag else 0)
    return bits - 0x100000000 if bits & INFO_FLAG_BIT else bits


def old_entry_flags(doc: DsonDocument, i: int) -> list[tuple[SaveIdentity, EntryFlags]]:
    """Identity and bit-31 state of every readable child of object ``i``, in data order.

    A child that is not ``{name: str, source: str}`` has no identity to match on and is skipped;
    it is dropped with the rest of the old subtree anyway.
    """
    out: list[tuple[SaveIdentity, EntryFlags]] = []
    for child in doc.children[i]:
        found = child_identity(doc, child)
        if found is None:
            continue
        identity, name_field, source_field = found
        flags = EntryFlags(
            child=has_flag(doc.meta2[child].info),
            name=has_flag(doc.meta2[name_field].info),
            source=has_flag(doc.meta2[source_field].info),
        )
        out.append((identity, flags))
    return out


def carry_flags(
    old: Sequence[tuple[SaveIdentity, EntryFlags]], wanted: Sequence[SaveIdentity]
) -> list[EntryFlags]:
    """The flags each ``wanted`` entry keeps: its matching old entry's, or :data:`NO_FLAGS`.

    Matching is by identity and positional among duplicates: the k-th old occurrence of an
    identity feeds the k-th new occurrence; surplus new occurrences are new entries.
    """
    pending: defaultdict[SaveIdentity, deque[EntryFlags]] = defaultdict(deque)
    for identity, flags in old:
        pending[identity].append(flags)
    out: list[EntryFlags] = []
    for identity in wanted:
        queue = pending.get(identity)
        out.append(queue.popleft() if queue else NO_FLAGS)
    return out
