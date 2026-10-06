"""The load order value type (src/core/load_order.py).

``entries`` mirrors the mod_state.json "order" list (interleaved; disabled and missing mods
included) and ``active()`` is what the save patcher writes as ``applied_ugcs_1_0``. Moves act on
``active()`` and are spliced back, so inactive slots never move.

Parity: cross-side moves vs the pinned ``dd2.ModManager.move_selection_between_sides``
(dd2.py:6742-6766, which calls ``reorder_visible_group`` 6684-6712 over the target side) and the
``load_mods`` merge rule (dd2.py:6021, 6044-6050). Documented divergences (enable appends after
the last active entry, disable keeps the slot, reconcile never prunes, casefold instead of lower)
are locked by name.
"""

import random
from collections.abc import Iterable, Sequence
from types import ModuleType, SimpleNamespace
from typing import Any

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
from tools.legacy_oracle import LegacyOracle

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
    """Documented divergence: the legacy click-toggle (dd2.py:5669-5676) only flipped the flag,
    re-enabling a mod in its remembered slot; the drag path (6742-6766) appended."""
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
    """Documented divergence: the legacy re-slotted a disabled mod inside the disabled list."""
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
    """Regression lock vs dd2.py:6044-6050: the legacy dropped saved mods that were not on disk
    (a briefly unmounted drive wiped their order slot); core keeps every entry and reports it."""
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
    """Documented divergence: the legacy sorted discovered folders with ``str.lower``
    (dd2.py:6021); ``"ß".casefold()`` is ``"ss"`` so it now sorts before ``"st"``."""
    rec = LoadOrder((), frozenset()).reconcile([M(x) for x in ("st", "ß", "Sz", "sa")])
    assert rec.added == _ids("sa ß st Sz")
    assert rec.order.enabled == frozenset()


def test_reconcile_seeded_against_the_legacy_merge_rule() -> None:
    """Inline port of dd2.py:6021 (``sorted(mods, key=str.lower)``) and 6044-6050 with ASCII
    names (where ``lower`` and ``casefold`` agree): added == legacy new_mods; entries minus the
    missing ones == legacy merged_order; nothing else changes."""
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


# ----------------------------------------------------------------- legacy parity


def _legacy_manager(dd2: ModuleType, order: LoadOrder) -> Any:
    """A ``ModManager`` without Tk: only what ``move_selection_between_sides`` (dd2.py:6742-6766)
    and ``visible_mods_for_side_from_state`` (4496-4546) read."""
    mgr = object.__new__(dd2.ModManager)
    mgr.state = {
        "order": list(order.entries),
        "enabled": {m: order.is_enabled(m) for m in order.entries},
        "categories": {},
        "metadata": {},
    }
    mgr.recent_new_mods = set()  # 4537: no NEW-window promotion
    mgr.current_filter_category = lambda: "All"  # 4501
    mgr.search_text = SimpleNamespace(get=lambda: "")  # 4502
    mgr.confirm_disable_active_mods = lambda mods: True  # 6747: no active-save prompt
    mgr.refresh = lambda: None
    mgr.schedule_save_state = lambda: None
    mgr.restore_drag_selection = lambda side, mods: None
    return mgr


def _legacy_order(mgr: Any) -> LoadOrder:
    state = mgr.state
    entries = tuple(ModId(m) for m in state["order"])
    return LoadOrder(entries, frozenset(ModId(m) for m, on in state["enabled"].items() if on))


def _random_cross_side_case(
    rng: random.Random, source: Sequence[ModId]
) -> tuple[list[ModId], int | None]:
    ids = [m for m in source if rng.random() < 0.5] or [rng.choice(source)]
    gap: int | None = rng.choice([None, rng.randint(0, 20)])
    return ids, gap


@pytest.mark.legacy
def test_enable_parity_with_legacy_disabled_to_enabled_moves(legacy: LegacyOracle) -> None:
    """``enable(ids, at=gap)`` == ``move_selection_between_sides("disabled", "enabled", ids, gap)``
    on the full order, for explicit gaps (clamped like the legacy) and for ``None``."""
    dd2 = legacy.module("dd2")
    rng = random.Random(6742)
    compared = 0
    for _ in range(500):
        order = _random_order(rng)
        if not order.inactive():
            continue
        ids, gap = _random_cross_side_case(rng, order.inactive())
        if gap is not None:
            gap = min(gap, len(order.active()))
        mgr = _legacy_manager(dd2, order)
        mgr.move_selection_between_sides("disabled", "enabled", list(ids), gap)
        assert order.enable(ids, at=gap) == _legacy_order(mgr)
        compared += 1
    assert compared > 300


@pytest.mark.legacy
def test_disable_divergence_lock_legacy_re_slots_the_mod(legacy: LegacyOracle) -> None:
    """Documented divergence: the legacy moved a disabled mod to the end of the disabled list
    (dd2.py:6752-6762); core keeps its slot. The active sequence agrees."""
    dd2 = legacy.module("dd2")
    order = _order("a b c* d")
    mgr = _legacy_manager(dd2, order)
    mgr.move_selection_between_sides("enabled", "disabled", ["a"], None)
    legacy_result = _legacy_order(mgr)
    assert legacy_result.entries == _ids("c b a d")
    core = order.disable({M("a")})
    assert core.entries == order.entries
    assert core.active() == legacy_result.active() == _ids("b d")
    assert set(core.inactive()) == set(legacy_result.inactive())


@pytest.mark.legacy
def test_toggle_parity_disable_keeps_the_slot_like_the_legacy_click_toggle(
    legacy: LegacyOracle,
) -> None:
    """``toggle_mod_enabled`` (dd2.py:5669-5676) only flips the flag, so ``disable`` is a verbatim
    port of that path (whole-value equality) while ``enable`` diverges by appending."""
    dd2 = legacy.module("dd2")
    rng = random.Random(5669)
    for _ in range(200):
        order = _random_order(rng)
        mod = rng.choice(order.entries)
        mgr = _legacy_manager(dd2, order)
        mgr.toggle_mod_enabled(mod)
        toggled = _legacy_order(mgr)
        assert toggled.entries == order.entries
        if order.is_enabled(mod):
            assert order.disable({mod}) == toggled
        else:
            core = order.enable([mod])
            assert core.enabled == toggled.enabled
            assert core.active()[-1] == mod
            assert [m for m in core.active() if m != mod] == [
                m for m in toggled.active() if m != mod
            ]


@pytest.mark.legacy
def test_disable_parity_on_the_active_sequence(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    rng = random.Random(6752)
    for _ in range(300):
        order = _random_order(rng)
        if not order.active():
            continue
        ids, gap = _random_cross_side_case(rng, order.active())
        mgr = _legacy_manager(dd2, order)
        mgr.move_selection_between_sides("enabled", "disabled", list(ids), gap)
        legacy_result = _legacy_order(mgr)
        core = order.disable(set(ids))
        assert core.active() == legacy_result.active()
        assert core.enabled == legacy_result.enabled
        assert sorted(core.entries) == sorted(legacy_result.entries)
