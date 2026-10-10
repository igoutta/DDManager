"""The load order value type (src/core/load_order.py).

``entries`` mirrors the mod_state.json "order" list (interleaved; disabled and missing mods
included) and ``active()`` is what the save patcher writes as ``applied_ugcs_1_0``. Moves act on
``active()`` and are spliced back, so inactive slots never move.

Documented behaviours (enable appends after the last active entry, disable keeps the slot,
reconcile never prunes, casefold ordering) are locked by name.
"""

import random
from collections.abc import Iterable

import pytest

from src.core.ids import ModId, SaveIdentity, SaveSource
from src.core.load_order import (
    LoadOrder,
    MoveOp,
    PriorityDirection,
    PrioritySetting,
    Reconciliation,
    applied_entries,
    missing_active,
)
from src.core.reorder import move_block, move_down, move_to_bottom, move_to_top, move_up

FIRST = PriorityDirection.FIRST_WINS
LAST = PriorityDirection.LAST_WINS
M = ModId


def _ids(spec: str) -> tuple[ModId, ...]:
    return tuple(ModId(tok.rstrip("*")) for tok in spec.split())


def _order(spec: str) -> LoadOrder:
    """``"a b* c"`` -> entries (a, b, c) with ``b`` disabled."""
    tokens = spec.split()
    entries = tuple(ModId(t.rstrip("*")) for t in tokens)
    enabled = frozenset(ModId(t) for t in tokens if not t.endswith("*"))
    return LoadOrder(entries, enabled)


def _random_order(rng: random.Random, max_len: int = 12) -> LoadOrder:
    names = [f"m{i}" for i in range(rng.randint(1, max_len))]
    rng.shuffle(names)
    entries = tuple(ModId(x) for x in names)
    enabled = frozenset(m for m in entries if rng.random() < 0.6)
    return LoadOrder(entries, enabled)


def _assert_same_membership(before: LoadOrder, after: LoadOrder) -> None:
    assert sorted(after.entries) == sorted(before.entries)
    assert after.enabled == before.enabled


def _assert_inactive_slots_fixed(before: LoadOrder, after: LoadOrder) -> None:
    for i, m in enumerate(before.entries):
        if not before.is_enabled(m):
            assert after.entries[i] == m


# ----------------------------------------------------------------- construction and views


def test_construction_and_views() -> None:
    order = _order("a b* c d*")
    assert order.entries == _ids("a b c d")
    assert order.enabled == frozenset(_ids("a c"))
    assert order.active() == _ids("a c")
    assert order.inactive() == _ids("b d")
    assert order.is_enabled(M("a"))
    assert not order.is_enabled(M("b"))
    assert not order.is_enabled(M("zzz"))
    assert order.rank(M("a")) == 1
    assert order.rank(M("c")) == 2
    assert order.rank(M("b")) is None
    assert order.rank(M("zzz")) is None
    assert order.ranks() == {M("a"): 1, M("c"): 2}


def test_empty_order() -> None:
    order = LoadOrder((), frozenset())
    assert order.active() == ()
    assert order.inactive() == ()
    assert order.ranks() == {}
    assert order.precedence(FIRST) == {}
    assert order.reconcile(()).order == order


def test_value_semantics_and_immutability() -> None:
    a = _order("a b*")
    b = LoadOrder((M("a"), M("b")), frozenset({M("a")}))
    assert a == b
    assert hash(a) == hash(b)
    assert a != _order("a b")
    with pytest.raises((AttributeError, TypeError)):
        a.entries = ()  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize("entries", [("a", "a"), ("a", "b", "a")])
def test_duplicate_entries_are_rejected(entries: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        LoadOrder(tuple(ModId(e) for e in entries), frozenset())


def test_enabled_must_be_a_subset_of_entries() -> None:
    with pytest.raises(ValueError):
        LoadOrder(_ids("a b"), frozenset(_ids("a zzz")))


def test_enums_and_priority_setting_defaults() -> None:
    assert PriorityDirection.FIRST_WINS == "first_wins"
    assert PriorityDirection.LAST_WINS == "last_wins"
    assert [op.value for op in MoveOp] == ["top", "up", "down", "bottom"]
    assert PrioritySetting() == PrioritySetting(direction=FIRST, verified=True)
    assert PrioritySetting(verified=False).direction is FIRST


# ----------------------------------------------------------------- precedence


def test_precedence_first_wins_gives_rank_one_the_highest_value() -> None:
    order = _order("a b* c d")
    assert order.precedence(FIRST) == {M("a"): 2, M("c"): 1, M("d"): 0}
    assert order.precedence(LAST) == {M("a"): 0, M("c"): 1, M("d"): 2}


def test_wins_follows_precedence() -> None:
    order = _order("a b* c")
    assert order.wins(M("a"), M("c"), FIRST)
    assert not order.wins(M("c"), M("a"), FIRST)
    assert order.wins(M("c"), M("a"), LAST)
    assert not order.wins(M("a"), M("c"), LAST)
    assert not order.wins(M("a"), M("a"), FIRST)


def test_precedence_seeded_consistency_with_ranks() -> None:
    rng = random.Random(11)
    for _ in range(200):
        order = _random_order(rng)
        n = len(order.active())
        for direction in (FIRST, LAST):
            prec = order.precedence(direction)
            assert set(prec) == set(order.active())
            assert sorted(prec.values()) == list(range(n))
            for m, r in order.ranks().items():
                assert prec[m] == (n - r if direction is FIRST else r - 1)
            for a in order.active():
                for b in order.active():
                    assert order.wins(a, b, direction) == (prec[a] > prec[b])


# ----------------------------------------------------------------- move / move_to

BASE = "a b* c d e* f"  # active: a c d f


def test_move_examples_are_spliced_around_inactive_slots() -> None:
    order = _order(BASE)
    assert order.move({M("d")}, MoveOp.UP) == _order("a b* d c e* f")
    assert order.move({M("a")}, MoveOp.DOWN) == _order("c b* a d e* f")
    assert order.move({M("c"), M("f")}, MoveOp.TOP) == _order("c b* f a e* d")
    assert order.move({M("a")}, MoveOp.BOTTOM) == _order("c b* d f e* a")


def test_move_with_empty_or_pinned_selection_is_identity() -> None:
    order = _order(BASE)
    for op in MoveOp:
        assert order.move(frozenset(), op) == order
    assert order.move({M("a")}, MoveOp.UP) == order
    assert order.move({M("a")}, MoveOp.TOP) == order
    assert order.move({M("f")}, MoveOp.DOWN) == order
    assert order.move({M("f")}, MoveOp.BOTTOM) == order
    assert order.move(set(order.active()), MoveOp.UP) == order


def test_move_ignores_inactive_and_unknown_ids_in_the_selection() -> None:
    """Resolved ambiguity: ``move`` acts over ``active()`` via ``reorder.*``, which ignores ids
    absent from the view, so inactive or unknown ids in the selection have no effect."""
    order = _order("a b* c d")
    assert order.move({M("b"), M("d")}, MoveOp.TOP) == _order("d b* a c")
    assert order.move({M("b")}, MoveOp.TOP) == order
    assert order.move({M("zzz")}, MoveOp.BOTTOM) == order
    assert order.move_to({M("b"), M("a")}, 3) == _order("c b* d a")
    assert order.move_to({M("zzz")}, 0) == order


def test_move_to_examples() -> None:
    order = _order(BASE)
    assert order.move_to({M("a")}, 0) == order
    assert order.move_to({M("a")}, 1) == order
    assert order.move_to({M("a")}, 2) == _order("c b* a d e* f")
    assert order.move_to({M("a")}, 3) == _order("c b* d a e* f")
    assert order.move_to({M("a")}, 4) == _order("c b* d f e* a")
    assert order.move_to({M("c"), M("f")}, 0) == _order("c b* f a e* d")
    assert order.move_to(frozenset(), 2) == order


def test_move_seeded_invariants_match_reorder_functions() -> None:
    reference = {
        MoveOp.TOP: move_to_top,
        MoveOp.UP: move_up,
        MoveOp.DOWN: move_down,
        MoveOp.BOTTOM: move_to_bottom,
    }
    rng = random.Random(6684)
    for _ in range(300):
        order = _random_order(rng)
        active = order.active()
        if not active:
            continue
        ids = frozenset(rng.sample(active, rng.randint(0, len(active))))
        for op, func in reference.items():
            moved = order.move(ids, op)
            _assert_same_membership(order, moved)
            _assert_inactive_slots_fixed(order, moved)
            assert moved.active() == func(active, ids)
        gap = rng.randint(0, len(active))
        landed = order.move_to(ids, gap)
        _assert_same_membership(order, landed)
        _assert_inactive_slots_fixed(order, landed)
        assert landed.active() == move_block(active, ids, gap)
        if ids:
            first = min(i for i, m in enumerate(landed.active()) if m in ids)
            assert first == gap - sum(1 for m in active[:gap] if m in ids), "lands at the indicator"


# ----------------------------------------------------------------- enable / disable


def test_enable_appends_after_the_last_active_entry_by_default() -> None:
    """Enabling without a gap appends; it does not restore a remembered slot."""
    order = _order("a b* c d*")
    result = order.enable([M("b")])
    assert result.active() == _ids("a c b")
    assert result.inactive() == _ids("d")
    assert result.enabled == frozenset(_ids("a b c"))
    assert sorted(result.entries) == sorted(order.entries)
    assert order.enable([M("b")], at=len(order.active())) == result


def test_enable_at_gap_inserts_in_active_coordinates() -> None:
    order = _order("a b* c d*")
    assert order.enable([M("d")], at=1).active() == _ids("a d c")
    assert order.enable([M("d")], at=1) == _order("a b* d c")  # spliced over active + ids slots
    assert order.enable([M("b")], at=0) == _order("b a c d*")
    assert order.enable([M("b"), M("d")], at=2).active() == _ids("a c b d")
    assert order.enable([M("b"), M("d")], at=0).active() == _ids("b d a c")


def test_enable_uses_the_given_sequence_order() -> None:
    """Resolved ambiguity: ``ids`` is a Sequence on purpose (the drag selection order), so the
    insertion order is the argument order, not the entries order."""
    order = _order("a b* c* d")
    assert order.enable([M("c"), M("b")]).active() == _ids("a d c b")
    assert order.enable([M("b"), M("c")]).active() == _ids("a d b c")


def test_enable_rejects_unknown_ids_and_ignores_enabled_ones() -> None:
    order = _order("a b* c")
    with pytest.raises(ValueError):
        order.enable([M("zzz")])
    with pytest.raises(ValueError):
        order.enable([M("b"), M("zzz")], at=0)
    assert order.enable([]) == order
    assert order.enable([M("a")]) == order
    assert order.enable([M("a"), M("b")]) == order.enable([M("b")])
    assert order.enable([M("c"), M("b")], at=0) == _order("b a c")


def test_disable_keeps_the_slot_in_entries() -> None:
    """A disabled mod is not re-slotted inside the disabled list."""
    order = _order("a b c* d")
    result = order.disable({M("b")})
    assert result.entries == order.entries
    assert result.active() == _ids("a d")
    assert result.inactive() == _ids("b c")
    assert result.enabled == frozenset(_ids("a d"))


def test_disable_ignores_inactive_and_unknown_ids() -> None:
    """Resolved ambiguity: disabling what is not active is a no-op (nothing to change)."""
    order = _order("a b c* d")
    assert order.disable({M("c")}) == order
    assert order.disable({M("zzz")}) == order
    assert order.disable(frozenset()) == order
    assert order.disable({M("a"), M("c"), M("zzz")}) == _order("a* b c* d")


def test_enable_then_disable_round_trip_keeps_membership() -> None:
    rng = random.Random(3)
    for _ in range(200):
        order = _random_order(rng)
        inactive = order.inactive()
        if not inactive:
            continue
        ids = [m for m in inactive if rng.random() < 0.5] or [inactive[0]]
        gap = rng.choice([None, rng.randint(0, len(order.active()))])
        enabled = order.enable(ids, at=gap)
        assert enabled.enabled == order.enabled | set(ids)
        assert sorted(enabled.entries) == sorted(order.entries)
        assert [m for m in enabled.active() if m not in ids] == list(order.active())
        if gap is not None:
            assert enabled.active()[gap : gap + len(ids)] == tuple(ids)
        else:
            assert enabled.active()[-len(ids) :] == tuple(ids)
        back = enabled.disable(set(ids))
        assert back.enabled == order.enabled
        assert back.active() == order.active()


# ----------------------------------------------------------------- with_active_sequence / forget


def test_with_active_sequence_splices_into_the_active_slots() -> None:
    order = _order(BASE)
    assert order.with_active_sequence(_ids("f d c a")) == _order("f b* d c e* a")
    assert order.with_active_sequence(order.active()) == order


@pytest.mark.parametrize("seq", ["a c d", "a c d f f", "a c d b", "a c d zzz", "a c f d x"])
def test_with_active_sequence_rejects_non_permutations(seq: str) -> None:
    with pytest.raises(ValueError):
        _order(BASE).with_active_sequence(_ids(seq))


def test_forget_is_the_only_way_entries_shrink() -> None:
    order = _order("a b* c")
    assert order.forget({M("b"), M("c")}) == _order("a")
    assert order.forget({M("a")}) == _order("b* c")
    assert order.forget(set(order.entries)) == LoadOrder((), frozenset())
    assert order.forget({M("zzz")}) == order  # resolved ambiguity: unknown ids are ignored
    assert order.forget(frozenset()) == order


# ----------------------------------------------------------------- reconcile


def test_reconcile_appends_unknown_present_ids_sorted_casefold_and_disabled() -> None:
    order = _order("a b* c")
    rec = order.reconcile(_ids("c x Y b2 a"))
    assert isinstance(rec, Reconciliation)
    assert rec.order == _order("a b* c b2* x* Y*")
    assert rec.added == _ids("b2 x Y")
    assert rec.missing == _ids("b")


def test_reconcile_never_prunes_or_re_sorts() -> None:
    """Saved mods that are not on disk are kept and reported (a briefly unmounted drive must not
    wipe their order slot)."""
    order = _order("c a b*")
    rec = order.reconcile(_ids("a"))
    assert rec.order == order
    assert rec.added == ()
    assert rec.missing == _ids("c b")  # entries order, enabled flags untouched
    assert rec.order.is_enabled(M("c"))


def test_reconcile_accepts_any_iterable_and_is_idempotent() -> None:
    order = _order("a")
    present: Iterable[ModId] = (M(x) for x in ("b", "a"))
    rec = order.reconcile(present)
    assert rec.order == _order("a b*")
    assert order.reconcile({M("a"), M("b")}).order == rec.order
    again = rec.order.reconcile(_ids("a b"))
    assert again.order == rec.order
    assert again.added == ()
    assert again.missing == ()


def test_reconcile_sorts_added_ids_by_casefold_not_lower() -> None:
    """Discovered folders sort by ``casefold``, not ``str.lower``; ``"ß".casefold()`` is ``"ss"``
    so it sorts before ``"st"``."""
    rec = LoadOrder((), frozenset()).reconcile([M(x) for x in ("st", "ß", "Sz", "sa")])
    assert rec.added == _ids("sa ß st Sz")
    assert rec.order.enabled == frozenset()


def test_reconcile_seeded_against_a_reference_merge() -> None:
    """Inline reference merge (``sorted(mods, key=str.lower)``) with ASCII
    names (where ``lower`` and ``casefold`` agree): added == the new mods; entries minus the
    missing ones == the merged order; nothing else changes."""
    rng = random.Random(6044)
    pool = [f"Mod{i}" if i % 3 else f"mod{i}" for i in range(20)]
    for _ in range(300):
        saved = rng.sample(pool, rng.randint(0, 10))
        present = rng.sample(pool, rng.randint(0, 12))
        current = sorted(present, key=str.lower)
        new_mods = [m for m in current if m not in saved]
        merged = [m for m in saved if m in current] + new_mods
        order = LoadOrder(tuple(M(x) for x in saved), frozenset(M(x) for x in saved[::2]))
        rec = order.reconcile(M(x) for x in present)
        assert list(rec.added) == new_mods
        assert list(rec.missing) == [m for m in saved if m not in current]
        assert [m for m in rec.order.entries if m not in rec.missing] == merged
        assert rec.order.entries == (*order.entries, *rec.added)
        assert rec.order.enabled == order.enabled


# ----------------------------------------------------------------- applied_entries


def test_applied_entries_maps_active_only() -> None:
    order = _order("a b* c")
    identities = {
        M("a"): SaveIdentity("111", SaveSource.STEAM),
        M("b"): SaveIdentity("B", SaveSource.LOCAL),
        M("c"): SaveIdentity("C mod", SaveSource.LOCAL),
    }
    assert applied_entries(order, identities) == (identities[M("a")], identities[M("c")])
    assert applied_entries(LoadOrder((), frozenset()), {}) == ()


def test_applied_entries_lists_every_missing_identity() -> None:
    order = _order("alpha bravo charlie delta*")
    with pytest.raises(ValueError) as info:
        applied_entries(order, {M("alpha"): SaveIdentity("111", SaveSource.STEAM)})
    message = str(info.value)
    assert "bravo" in message
    assert "charlie" in message
    assert "alpha" not in message, "only the missing ids are listed"
    assert "delta" not in message, "inactive entries need no identity"


def test_applied_entries_leaves_mods_missing_from_disk_out_even_with_a_cached_identity() -> None:
    """Contract §4: an enabled mod whose folder is gone is excluded, never written from a stale
    identity; the others still need one."""
    order = _order("alpha gone bravo lost* charlie")
    identities = {
        M("alpha"): SaveIdentity("111", SaveSource.STEAM),
        M("gone"): SaveIdentity("Gone", SaveSource.LOCAL),
        M("charlie"): SaveIdentity("C mod", SaveSource.LOCAL),
    }
    missing = frozenset({M("gone"), M("lost")})
    with pytest.raises(ValueError, match="bravo"):
        applied_entries(order, identities, missing=missing)
    identities[M("bravo")] = SaveIdentity("B", SaveSource.LOCAL)
    assert applied_entries(order, identities, missing=missing) == (
        identities[M("alpha")],
        identities[M("bravo")],
        identities[M("charlie")],
    )
    assert missing_active(order, missing) == (M("gone"),), "disabled missing mods do not count"
    assert missing_active(order, missing, present=True) == _ids("alpha bravo charlie")
