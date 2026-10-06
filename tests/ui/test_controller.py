"""MainController against fake services and an immediate executor (no window)."""

import pytest

from src.core.ids import ModId
from src.core.load_order import MoveOp
from src.services.errors import StateConflictError
from src.ui.ports import PatchDecision
from tests.ui.conftest import CATEGORIES, ENABLED
from tests.ui.fakes import fingerprint


def active(controller):
    return list(controller.load_order_model.order())


def test_start_populates_both_models(started, fake_services):
    controller, _ = started
    assert active(controller) == list(ENABLED)
    assert controller.available_model.rowCount() == len(fake_services.catalog)
    assert fake_services.scanner.calls == 1
    assert controller.undo_stack.count() == 0


def test_start_emits_status_and_findings(make_controller, qtbot):
    controller, _ = make_controller()
    with qtbot.waitSignal(controller.statusChanged), qtbot.waitSignal(controller.findingsChanged):
        controller.start()


def test_one_undo_command_per_change_and_undo_restores(started):
    controller, _ = started
    first = active(controller)
    controller.move([ModId(first[3])], MoveOp.UP)
    assert controller.undo_stack.count() == 1
    moved = active(controller)
    assert moved[2] == first[3]
    controller.enable([ModId("chorus_class_mod_testdrop")])
    assert controller.undo_stack.count() == 2
    controller.undo()
    assert active(controller) == moved
    controller.undo()
    assert active(controller) == first
    controller.redo()
    assert active(controller) == moved


def test_noop_changes_push_nothing(started):
    controller, _ = started
    order = active(controller)
    controller.move([ModId(order[0])], MoveOp.TOP)
    controller.move([ModId(order[-1])], MoveOp.BOTTOM)
    controller.enable([ModId(order[1])])
    controller.disable([ModId("chorus_class_mod_testdrop")])  # already disabled
    controller.move_to([ModId(order[2])], 2)
    assert controller.undo_stack.count() == 0
    assert active(controller) == order


def test_move_to_matches_core(started):
    controller, _ = started
    order = active(controller)
    controller.move_to([ModId(order[4])], 1)
    assert active(controller) == [order[0], order[4], *order[1:4], order[5]]
    assert controller.undo_stack.count() == 1


def test_guarded_disable_prompts_once_and_respects_no(make_controller):
    controller, prompter = make_controller({"confirm_disable_active": False})
    controller.start()
    in_save = ModId(ENABLED[1])
    controller.disable([in_save])
    assert prompter.count("confirm_disable_active") == 1
    titles, _slot = prompter.calls[0][1]
    assert any("Chorus" in t for t in titles)
    assert in_save in active(controller)
    assert controller.undo_stack.count() == 0


def test_guarded_disable_proceeds_on_yes_and_skips_the_prompt_for_other_mods(make_controller):
    controller, prompter = make_controller({"confirm_disable_active": True})
    controller.start()
    controller.disable([ModId(ENABLED[5])])  # not listed in the active save
    assert prompter.count("confirm_disable_active") == 0
    controller.disable([ModId(ENABLED[0]), ModId(ENABLED[1])])
    assert prompter.count("confirm_disable_active") == 1
    assert ENABLED[0] not in active(controller)
    assert controller.undo_stack.count() == 2


def test_guarded_undo(make_controller, fake_services):
    answers = {"confirm_disable_active": [False, True]}
    controller, prompter = make_controller(answers)
    controller.start()
    newcomer = ModId("chorus_class_mod_testdrop")
    fake_services.slots.applied = (
        *fake_services.slots.applied,
        fake_services.catalog[newcomer].save_identity,
    )
    controller.enable([newcomer])
    assert newcomer in active(controller)
    controller.undo()  # would disable a mod the active save lists -> asks, answer no
    assert prompter.count("confirm_disable_active") == 1
    assert newcomer in active(controller)
    controller.undo()  # answer yes
    assert prompter.count("confirm_disable_active") == 2
    assert newcomer not in active(controller)


def test_auto_sort_cancel_leaves_the_order_unchanged(make_controller):
    controller, prompter = make_controller({"review_order_change": False})
    controller.start()
    order = active(controller)
    controller.auto_sort()
    assert prompter.count("review_order_change") == 1
    assert active(controller) == order
    assert controller.undo_stack.count() == 0


def test_auto_sort_apply_is_one_undo_command(make_controller):
    controller, prompter = make_controller({"review_order_change": True})
    controller.start()
    order = active(controller)
    controller.auto_sort()
    assert prompter.count("review_order_change") == 1
    assert sorted(active(controller)) == sorted(order)
    assert controller.undo_stack.count() == (0 if active(controller) == order else 1)
    assert CATEGORIES  # the canned state classifies a patch, a UI and a class mod
    controller.undo()
    assert active(controller) == order


def test_patch_save_cancel_never_applies(make_controller, fake_services):
    decline = PatchDecision(False, frozenset(), False)
    controller, prompter = make_controller({"review_patch": decline})
    controller.start()
    controller.patch_save()
    assert prompter.count("review_patch") == 1
    assert len(fake_services.patcher.plans) == 1
    assert fake_services.patcher.applies == []
    assert fake_services.backups.created == []


def test_patch_save_applies_after_confirmation_and_records_paths(make_controller, fake_services):
    controller, _ = make_controller(
        {"review_patch": PatchDecision(True, frozenset({"ack"}), False)}
    )
    controller.start()
    controller.patch_save()
    assert len(fake_services.patcher.applies) == 1
    _plan, acknowledged = fake_services.patcher.applies[0]
    assert acknowledged == frozenset({"ack"})
    expected = tuple(fake_services.catalog[ModId(m)].save_identity for m in ENABLED)
    assert fake_services.patcher.plans[0][1] == expected
    assert controller.can_close()  # flushes the pending state write
    written = {k for ch in fake_services.state.saves for k in (ch.settings or {})}
    assert {"last_backup_path", "last_save_path"} <= written


def test_backup_save_creates_one_backup(started, fake_services):
    controller, _ = started
    controller.backup_save()
    assert len(fake_services.backups.created) == 1


def test_can_close_flushes_the_pending_state_write(started, fake_services):
    controller, _ = started
    order = active(controller)
    controller.move([ModId(order[2])], MoveOp.TOP)
    assert controller.can_close()
    saved = fake_services.state.last_order()
    assert saved is not None
    assert list(saved.active()) == active(controller)


def test_state_conflict_emits_signal(started, fake_services, qtbot):
    controller, _ = started
    fake_services.state.raise_on_save = StateConflictError(
        "changed", expected=fingerprint("a"), actual=fingerprint("b")
    )
    order = active(controller)
    controller.move([ModId(order[2])], MoveOp.TOP)
    with qtbot.waitSignal(controller.stateConflict, timeout=3000):
        controller.can_close()


def test_silent_classify_never_reorders(make_controller, fake_services):
    controller, _ = make_controller()
    before = fake_services.state.doc.order
    controller.start()
    assert active(controller) == list(before.active())
    assert controller.undo_stack.count() == 0
    for changes in fake_services.state.saves:
        if changes.order is not None:
            assert changes.order.entries[: len(before.entries)] == before.entries
    assert controller.available_model.rowCount() == len(fake_services.catalog)


def test_rescan_keeps_the_order(started, fake_services):
    controller, _ = started
    order = active(controller)
    controller.rescan()
    assert fake_services.scanner.calls == 2
    assert active(controller) == order
    assert controller.undo_stack.count() == 0


@pytest.mark.parametrize("op", list(MoveOp))
def test_every_move_op_matches_core(started, op):
    controller, _ = started
    order = active(controller)
    from src.core.load_order import LoadOrder

    expected = LoadOrder(tuple(order), frozenset(order)).move({ModId(order[2])}, op).active()
    controller.move([ModId(order[2])], op)
    assert tuple(active(controller)) == expected
