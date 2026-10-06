"""Writing ``mod_state.json`` from the session (optimistic concurrency, no Qt)."""

from typing import Literal

from src.core.legacy_state import StateChanges
from src.services.errors import StateConflictError, StateReadOnlyError
from src.services.state_repo import StateRepository
from src.ui.session import Session

type WriteOutcome = Literal["ok", "conflict", "read_only"]


def is_dirty(s: Session) -> bool:
    return s.pending.any() or s.order != s.doc.order


def _changes(s: Session) -> StateChanges:
    p = s.pending
    return StateChanges(
        order=s.order,
        categories=dict(p.categories) or None,
        attempted=set(p.attempted) or None,
        category_memory_updates=dict(p.memory) or None,
        settings=dict(p.settings) or None,
    )


def write_state(repo: StateRepository, s: Session, *, rebase: bool = False) -> WriteOutcome:
    """Save order + pending changes; with ``rebase`` apply them over the file as it is now."""
    base, expected = s.doc, s.fingerprint
    if rebase:
        snapshot = repo.load()
        base, expected = snapshot.doc, snapshot.fingerprint
    try:
        repo.save(base, _changes(s), expected=expected)
    except StateConflictError:
        return "conflict"
    except StateReadOnlyError:
        return "read_only"
    adopt(repo, s)
    return "ok"


def adopt(repo: StateRepository, s: Session) -> None:
    """Take the file as the new base and forget the pending changes."""
    snapshot = repo.load()
    s.doc, s.fingerprint = snapshot.doc, snapshot.fingerprint
    s.pending.clear()
    s.conflict = False
