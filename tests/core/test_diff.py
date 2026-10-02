"""Sequence diffs (src/core/diff.py): membership and index changes between two orders."""

import random

import pytest

from src.core.diff import SequenceDiff, sequence_diff
from src.core.ids import ModId


def test_identical_sequences_give_an_empty_diff() -> None:
    diff = sequence_diff(["a", "b"], ["a", "b"])
    assert diff == SequenceDiff(added=(), removed=(), moved=())
    assert diff.is_empty
    assert sequence_diff([], []).is_empty
    assert sequence_diff((), ()) == SequenceDiff((), (), ())


def test_added_and_removed_keep_their_own_sequence_order() -> None:
    diff = sequence_diff(["a", "b", "c"], ["c", "x", "a", "y"])
    assert diff.added == ("x", "y")
    assert diff.removed == ("b",)
    assert set(diff.moved) == {("a", 0, 2), ("c", 2, 0)}
    assert not diff.is_empty


def test_pure_reorder_reports_every_displaced_item_with_raw_indices() -> None:
    diff = sequence_diff(["a", "b", "c", "d"], ["a", "c", "b", "d"])
    assert diff.added == ()
    assert diff.removed == ()
    assert set(diff.moved) == {("b", 1, 2), ("c", 2, 1)}


def test_insertion_at_the_front_moves_every_following_item() -> None:
    diff = sequence_diff(["a", "b"], ["x", "a", "b"])
    assert diff.added == ("x",)
    assert diff.removed == ()
    assert set(diff.moved) == {("a", 0, 1), ("b", 1, 2)}


def test_append_moves_nothing() -> None:
    diff = sequence_diff(["a", "b"], ["a", "b", "c"])
    assert diff == SequenceDiff(added=("c",), removed=(), moved=())


def test_removal_at_the_end_moves_nothing() -> None:
    diff = sequence_diff(["a", "b", "c"], ["a", "b"])
    assert diff == SequenceDiff(added=(), removed=("c",), moved=())


def test_disjoint_sequences() -> None:
    diff = sequence_diff(["a", "b"], ["c"])
    assert diff == SequenceDiff(added=("c",), removed=("a", "b"), moved=())
    assert sequence_diff([], ["a"]) == SequenceDiff(added=("a",), removed=(), moved=())
    assert sequence_diff(["a"], []) == SequenceDiff(added=(), removed=("a",), moved=())


def test_is_empty_is_false_for_each_kind_of_change() -> None:
    assert not SequenceDiff((), (), (("a", 0, 1),)).is_empty
    assert not SequenceDiff(("a",), (), ()).is_empty
    assert not SequenceDiff((), ("a",), ()).is_empty


def test_generic_over_hashable_item_types() -> None:
    ints = sequence_diff([1, 2, 3], [3, 2, 1])
    assert set(ints.moved) == {(1, 0, 2), (3, 2, 0)}
    ids = sequence_diff([ModId("x")], [ModId("y"), ModId("x")])
    assert ids.added == (ModId("y"),)
    assert ids.moved == ((ModId("x"), 0, 1),)
    pairs = sequence_diff([("a", 1)], [("a", 1), ("b", 2)])
    assert pairs.added == (("b", 2),)


def test_result_is_a_frozen_value() -> None:
    diff = sequence_diff(["a"], ["b"])
    with pytest.raises((AttributeError, TypeError)):
        diff.added = ()  # ty: ignore[invalid-assignment]
    assert diff == sequence_diff(["a"], ["b"])
    assert hash(diff) == hash(sequence_diff(["a"], ["b"]))


def test_seeded_properties() -> None:
    rng = random.Random(20260929)
    for _ in range(500):
        pool = [f"m{i}" for i in range(rng.randint(0, 12))]
        before = rng.sample(pool, rng.randint(0, len(pool)))
        after = rng.sample(pool, rng.randint(0, len(pool)))
        diff = sequence_diff(before, after)
        assert diff.added == tuple(x for x in after if x not in before)
        assert diff.removed == tuple(x for x in before if x not in after)
        expected_moved = {
            (x, i, after.index(x))
            for i, x in enumerate(before)
            if x in after and after.index(x) != i
        }
        assert set(diff.moved) == expected_moved
        assert len(diff.moved) == len(expected_moved)
        assert diff.is_empty == (before == after)
        assert sequence_diff(after, before).added == diff.removed
        assert sequence_diff(after, before).removed == diff.added
