"""Tiny bridge from builder (name, source) tuples to the canonical SaveIdentity type."""

from collections.abc import Sequence

from src.core.ids import SaveIdentity
from tests.support.dson_builder import Entry


def identities(entries: Sequence[Entry]) -> tuple[SaveIdentity, ...]:
    return tuple(SaveIdentity(name, source) for name, source in entries)


def entries_of(ids: Sequence[SaveIdentity]) -> tuple[Entry, ...]:
    return tuple((identity.name, identity.source) for identity in ids)
