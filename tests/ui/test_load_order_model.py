"""LoadOrderModel: model-tester contract, moves, drag and drop at the mime-data level."""

import json
import os
import random

import pytest
from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)

from src.core.ids import ModId
from src.core.load_order import LoadOrder
from src.ui.models.load_order_model import Col, LoadOrderModel
from src.ui.models.roles import MIME_MOD_IDS, DragOrigin, Role, decode_payload, encode_payload
from tests.ui.helpers import build

ROOT = QModelIndex()
MOVE = Qt.DropAction.MoveAction


def drop(model, ids, row, origin=DragOrigin.LOAD_ORDER, parent=ROOT):
    return model.dropMimeData(encode_payload(origin, ids), MOVE, row, 0, parent)


def selected_ids(model, selection):
    return {model.index(i.row(), 0).data(Role.MOD_ID) for i in selection.selectedRows()}


@pytest.mark.parametrize("count", [0, 1, 50])
def test_model_tester(order_model, rows_factory, qtmodeltester, count):
    order_model.apply_rows(rows_factory(count))
    qtmodeltester.check(order_model)
    assert order_model.rowCount() == count
    assert order_model.columnCount() == len(Col)


def test_apply_rows_sequences_keep_the_model_valid(rows_factory, thumbs, translator, qtmodeltester):
    """Replay every prefix of a seeded apply_rows sequence on a fresh model, then run the tester.

    A tester that stays attached while rows move would flag the rank column (column 0 shows the
    position, so its display text legitimately changes when a row moves); the tester therefore
    only inspects the settled state of each replay.
    """
    rng = random.Random(7)
    pool = rows_factory(40)
    steps = [rng.sample(pool, rng.randint(0, len(pool))) for _ in range(10)]
    for count in range(1, len(steps) + 1):
        model = build(LoadOrderModel, thumbs=thumbs, translator=translator)
        for chosen in steps[:count]:
            model.apply_rows(chosen)
            assert model.order() == tuple(r.mod_id for r in chosen)
            assert [model.row_of(r.mod_id) for r in chosen] == list(range(len(chosen)))
        qtmodeltester.check(model)


def test_apply_rows_rejects_duplicates(order_model, rows_factory):
    rows = rows_factory(3)
    with pytest.raises(ValueError, match="duplicate"):
        order_model.apply_rows([*rows, rows[0]])


def test_payload_only_change_emits_data_changed_not_structure(order_model, rows_factory, qtbot):
    import dataclasses

    rows = rows_factory(5)
    order_model.apply_rows(rows)
    changed = [*rows]
    changed[2] = dataclasses.replace(rows[2], finding_count=3, worst_severity=30)
    with (
        qtbot.waitSignal(order_model.dataChanged) as blocker,
        qtbot.assertNotEmitted(order_model.rowsMoved),
    ):
        order_model.apply_rows(changed)
    assert blocker.args[0].row() == 2
    assert order_model.index(2, Col.FINDINGS).data(Role.FINDING_COUNT) == 3


def test_rank_role_follows_position(order_model, rows_factory):
    rows = rows_factory(6)
    order_model.apply_rows(rows)
    order_model.apply_rows(list(reversed(rows)))
    for i in range(6):
        assert order_model.index(i, Col.RANK).data(Role.RANK) == i + 1
        assert order_model.index(i, Col.TITLE).data(Role.MOD_ID) == rows[5 - i].mod_id


def test_data_roles_for_every_column(order_model, rows_factory):
    order_model.apply_rows(rows_factory(3))
    for col in Col:
        index = order_model.index(1, col)
        assert str(index.data(Qt.ItemDataRole.ToolTipRole)).strip(), col
    right = order_model.index(1, Col.RANK).data(Qt.ItemDataRole.TextAlignmentRole)
    assert int(right) & int(Qt.AlignmentFlag.AlignRight)
    assert order_model.index(1, 0).data(Qt.ItemDataRole.AccessibleTextRole)
    assert order_model.index(1, 0).data(Role.TIER) == "ui"


def test_move_rows_contract(order_model, rows_factory, qtbot):
    rows = rows_factory(10)
    order_model.apply_rows(rows)
    ids = list(order_model.order())
    for src, count, dst in [(2, 2, 2), (2, 2, 3), (2, 2, 4), (0, 0, 5), (8, 5, 0), (2, 1, 11)]:
        assert not order_model.moveRows(ROOT, src, count, ROOT, dst), (src, count, dst)
        assert order_model.order() == tuple(ids)
    with qtbot.waitSignal(order_model.rowsMoved):
        assert order_model.moveRows(ROOT, 2, 1, ROOT, 6)
    assert order_model.order() == (*ids[:2], *ids[3:6], ids[2], *ids[6:])
    assert order_model.index(5, Col.RANK).data(Role.RANK) == 6


def test_mime_data_dedupes_sorts_and_stamps_pid(order_model, rows_factory):
    order_model.apply_rows(rows_factory(8))
    indexes = [order_model.index(r, c) for r in (5, 2, 5, 3) for c in (2, 0)]
    random.Random(1).shuffle(indexes)
    mime = order_model.mimeData(indexes)
    payload = decode_payload(mime)
    assert payload is not None
    assert payload.origin is DragOrigin.LOAD_ORDER
    assert payload.pid == os.getpid()
    assert payload.ids == tuple(ModId(f"mod_{r:03d}") for r in (2, 3, 5))
    assert mime.text().split("\n") == list(payload.ids)


def test_drop_emits_move_request_and_leaves_the_model_to_the_controller(
    order_model, rows_factory, qtbot
):
    order_model.apply_rows(rows_factory(6))
    before = order_model.order()
    with qtbot.waitSignal(order_model.moveRequested) as blocker:
        assert drop(order_model, ["mod_001", "mod_002"], 5)
    assert blocker.args == [[ModId("mod_001"), ModId("mod_002")], 5]
    assert order_model.order() == before


def test_drop_row_minus_one_appends(order_model, rows_factory, qtbot):
    order_model.apply_rows(rows_factory(6))
    with qtbot.waitSignal(order_model.moveRequested) as blocker:
        assert drop(order_model, ["mod_000"], -1)
    assert blocker.args[1] == 6


def test_available_payload_requests_enable(order_model, rows_factory, qtbot):
    order_model.apply_rows(rows_factory(6))
    with (
        qtbot.waitSignal(order_model.enableRequested) as blocker,
        qtbot.assertNotEmitted(order_model.moveRequested),
    ):
        assert drop(order_model, ["new_a", "new_b"], 2, origin=DragOrigin.AVAILABLE)
    assert blocker.args == [[ModId("new_a"), ModId("new_b")], 2]


def _tampered(pid_delta=0, **patch):
    payload = encode_payload(DragOrigin.LOAD_ORDER, [ModId("mod_000")])
    body = json.loads(bytes(payload.data(MIME_MOD_IDS).data()))
    body["pid"] += pid_delta
    body.update(patch)
    from PySide6.QtCore import QByteArray, QMimeData

    md = QMimeData()
    md.setData(MIME_MOD_IDS, QByteArray(json.dumps(body).encode()))
    return md


def _garbage():
    from PySide6.QtCore import QByteArray, QMimeData

    md = QMimeData()
    md.setData(MIME_MOD_IDS, QByteArray(b"{not json"))
    other = QMimeData()
    other.setText("mod_000")
    return [md, other, QMimeData(), _tampered(pid_delta=1), _tampered(ids=[])]


def test_foreign_and_garbage_payloads_are_rejected(order_model, rows_factory, qtbot):
    order_model.apply_rows(rows_factory(4))
    for md in _garbage():
        assert not order_model.canDropMimeData(md, MOVE, 1, 0, ROOT)
        with (
            qtbot.assertNotEmitted(order_model.moveRequested),
            qtbot.assertNotEmitted(order_model.enableRequested),
        ):
            assert not order_model.dropMimeData(md, MOVE, 1, 0, ROOT)


def test_flags_allow_drops_only_between_rows(order_model, rows_factory):
    order_model.apply_rows(rows_factory(3))
    assert order_model.flags(ROOT) & Qt.ItemFlag.ItemIsDropEnabled
    for col in Col:
        flags = order_model.flags(order_model.index(1, col))
        assert not flags & Qt.ItemFlag.ItemIsDropEnabled
        for needed in (
            Qt.ItemFlag.ItemIsEnabled,
            Qt.ItemFlag.ItemIsSelectable,
            Qt.ItemFlag.ItemIsDragEnabled,
            Qt.ItemFlag.ItemNeverHasChildren,
        ):
            assert flags & needed


def test_internal_move_keeps_relative_order_and_persistent_indexes(order_model, rows_factory):
    rows = rows_factory(10)
    by_id = {r.mod_id: r for r in rows}
    order_model.apply_rows(rows)
    persistent = {
        r.mod_id: QPersistentModelIndex(order_model.index(i, 0)) for i, r in enumerate(rows)
    }
    order = LoadOrder(tuple(by_id), frozenset(by_id))

    def on_move(ids, row):
        nonlocal order
        order = order.move_to(set(ids), row)
        order_model.apply_rows([by_id[m] for m in order.active()])

    order_model.moveRequested.connect(on_move)
    assert drop(order_model, ["mod_007", "mod_003", "mod_005"], 1)
    assert order_model.order()[:4] == ("mod_000", "mod_003", "mod_005", "mod_007")
    for mod_id, index in persistent.items():
        assert index.isValid()
        assert index.data(Role.MOD_ID) == mod_id
        assert index.row() == order_model.row_of(mod_id)


def test_large_permutation_keeps_selection_by_id(order_model, rows_factory):
    rows = rows_factory(120)
    order_model.apply_rows(rows)
    selection = QItemSelectionModel(order_model)
    for row in (5, 6, 50, 99):
        selection.select(
            QItemSelection(order_model.index(row, 0), order_model.index(row, len(Col) - 1)),
            QItemSelectionModel.SelectionFlag.Select,
        )
    wanted = selected_ids(order_model, selection)
    order_model.apply_rows(list(reversed(rows)))
    assert order_model.order()[0] == "mod_119"
    assert (
        selected_ids(order_model, selection)
        == wanted
        == {
            ModId("mod_005"),
            ModId("mod_006"),
            ModId("mod_050"),
            ModId("mod_099"),
        }
    )


def test_model_matches_core_move_to_over_300_seeded_drops(order_model, rows_factory):
    rng = random.Random(20260506)
    rows = rows_factory(30)
    by_id = {r.mod_id: r for r in rows}
    entries = [r.mod_id for r in rows] + [ModId(f"off_{i}") for i in range(8)]
    rng.shuffle(entries)
    enabled = frozenset(by_id)
    order = LoadOrder(tuple(entries), enabled)
    order_model.apply_rows([by_id[m] for m in order.active()])

    def on_move(ids, row):
        nonlocal order
        order = order.move_to(set(ids), row)
        order_model.apply_rows([by_id[m] for m in order.active()])

    order_model.moveRequested.connect(on_move)
    for step in range(300):
        active = order.active()
        picked = rng.sample(active, rng.randint(1, 6))
        gap = rng.randint(0, len(active))
        expected = order.move_to(set(picked), gap).active()
        rng.shuffle(picked)
        assert drop(order_model, picked, gap)
        assert order_model.order() == expected == order.active(), f"drop {step}"
        assert [order_model.row_of(m) for m in expected] == list(range(len(expected)))


def test_thumbnail_ready_changes_only_that_rows_decoration(
    order_model, rows_factory, thumbs, qtbot
):
    order_model.apply_rows(rows_factory(5))
    with qtbot.waitSignal(order_model.dataChanged) as blocker:
        thumbs.ready.emit("mod_003")
    top, bottom, roles = blocker.args[0], blocker.args[1], blocker.args[2]
    assert top.row() == bottom.row() == 3
    assert Qt.ItemDataRole.DecorationRole in roles


def test_live_model_tester_survives_apply_rows_moves(order_model, rows_factory, qtmodeltester):
    pool = rows_factory(30)
    order_model.apply_rows(pool)
    qtmodeltester.check(order_model)  # stays attached while the rows below move
    rng = random.Random(11)
    for _ in range(8):
        chosen = rng.sample(pool, rng.randint(2, len(pool)))
        order_model.apply_rows(chosen)
        assert order_model.order() == tuple(r.mod_id for r in chosen)
