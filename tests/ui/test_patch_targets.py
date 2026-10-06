"""P16: Tools > Patch Other File... and Patch Latest Detected Save, both through the patch preview.

"Patch Save" (File menu) writes the selected slot.  The two Tools items pick another target:
any file the user chooses, or the most recently changed detected save (confirmed by name first).
Neither changes which slot is selected, and a file that is not called ``persist.game.json`` adds
the ``non_default_filename`` acknowledgement to the preview.
"""

import pytest

from src.services.save_patch import ACK_NON_DEFAULT_FILENAME
from src.ui.ports import PatchDecision
from src.ui.viewmodels import PatchPreviewVM
from tests.ui.conftest import ENABLED
from tests.ui.m5_support import LANGUAGES, action_for, catalog_of, trigger

ACK_KEY = "ui.ack.non_default_filename"


def save_file(tmp_path_factory, folder: str, name: str):
    path = tmp_path_factory.mktemp("saves") / folder / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"another save")
    return path


@pytest.fixture
def other_save(tmp_path_factory):
    """A save of another profile, with the name the game reads."""
    return save_file(tmp_path_factory, "profile_3", "persist.game.json")


@pytest.fixture
def odd_save(tmp_path_factory):
    """A save file whose name the game would not read."""
    return save_file(tmp_path_factory, "profile_4", "persist.game.json.bak")


def previews(rig) -> list[PatchPreviewVM]:
    return rig.prompter.objects_of(PatchPreviewVM)


def planned_paths(rig):
    return [path for path, _entries in rig.services.patcher.plans]


# ---------------------------------------------------------------------------- Patch other file


def test_patch_other_file_asks_for_a_file_and_previews_a_patch_of_it(rig_factory, other_save):
    rig = rig_factory(window=True, answers={"pick_save_file": other_save})
    trigger(rig.window, "patch_other")
    ((start_dir,), _kwargs) = rig.prompter.calls_named("pick_save_file")[0]
    assert start_dir == rig.services.save_path.parent, "the picker starts beside the selected save"
    (vm,) = previews(rig)
    assert vm.save_path == other_save
    assert planned_paths(rig) == [other_save]
    expected = tuple(rig.mods[m].save_identity for m in ENABLED)
    assert rig.services.patcher.plans[0][1] == expected, "the enabled mods in load order"
    ((plan, _acks),) = rig.services.patcher.applies
    assert plan.save_path == other_save
    assert rig.controller.save_path() == rig.services.save_path, "the selected slot stays"


def test_cancelling_the_file_picker_patches_nothing(rig_factory):
    rig = rig_factory(window=True, answers={"pick_save_file": None})
    trigger(rig.window, "patch_other")
    assert rig.prompter.count("pick_save_file") == 1
    assert previews(rig) == []
    assert planned_paths(rig) == []


def test_a_non_default_filename_requires_its_acknowledgement_in_the_preview(rig_factory, odd_save):
    def acknowledge_everything(vm: PatchPreviewVM) -> PatchDecision:
        return PatchDecision(True, frozenset(ack for ack, _key in vm.required_acks), False)

    rig = rig_factory(
        window=True,
        answers={"pick_save_file": odd_save, "review_patch": acknowledge_everything},
    )
    trigger(rig.window, "patch_other")
    (vm,) = previews(rig)
    assert (ACK_NON_DEFAULT_FILENAME, ACK_KEY) in vm.required_acks
    assert all(rig.translator.has(key) for _ack, key in vm.required_acks)
    ((plan, acknowledged),) = rig.services.patcher.applies
    assert plan.save_path == odd_save
    assert ACK_NON_DEFAULT_FILENAME in acknowledged


def test_the_default_filename_needs_no_such_acknowledgement(rig_factory, other_save):
    rig = rig_factory(window=True, answers={"pick_save_file": other_save})
    trigger(rig.window, "patch_other")
    (vm,) = previews(rig)
    assert ACK_NON_DEFAULT_FILENAME not in {ack for ack, _key in vm.required_acks}


# ---------------------------------------------------------------------------- Patch latest detected


def test_patch_latest_detected_confirms_the_newest_detected_save_then_previews_it(
    rig_factory, other_save
):
    rig = rig_factory(window=True)
    services = rig.services
    files = (services.save_path, other_save)
    services.detector.set_snapshot(save_files=files)
    asked = []

    def latest(save_files):
        asked.append(tuple(save_files))
        return other_save  # the slot service decides by mtime; the flow must take its answer

    services.slots.latest = latest
    rig.controller.rescan()
    trigger(rig.window, "patch_latest")
    assert asked[-1] == files, "every detected save file is a candidate"
    (((key,), params),) = rig.prompter.calls_named("confirm")
    assert key == "ui.prompt.patch_latest"
    assert params["file"] == str(other_save)
    assert params["slot"] == rig.controller.slot_label(other_save) != ""
    (vm,) = previews(rig)
    assert vm.save_path == other_save
    assert planned_paths(rig) == [other_save]
    assert rig.controller.save_path() == services.save_path, "the selected slot stays"


def test_declining_the_confirmation_patches_nothing(rig_factory):
    rig = rig_factory(window=True, answers={"confirm": False})
    trigger(rig.window, "patch_latest")
    assert rig.prompter.confirm_keys() == ["ui.prompt.patch_latest"]
    assert previews(rig) == []
    assert planned_paths(rig) == []


def test_with_no_detected_save_file_it_explains_and_patches_nothing(rig_factory):
    rig = rig_factory(window=True)
    rig.services.detector.set_snapshot(save_files=())
    rig.controller.rescan()
    rig.messages.clear()
    trigger(rig.window, "patch_latest")
    note = rig.messages.only("ui.notice.no_save_detected")
    assert note.level == "warning"
    assert rig.prompter.confirm_keys() == []
    assert planned_paths(rig) == []


# ---------------------------------------------------------------------------- the menu items


def test_both_are_tools_menu_items_with_their_own_tooltips_in_every_language(rig_factory):
    rig = rig_factory(window=True)
    tools = rig.window.chrome.menus["tools"].actions()
    for name in ("patch_other", "patch_latest"):
        action = action_for(rig.window, name)
        assert action in tools
        assert action.toolTip().strip() and action.toolTip() != action.text()
        for language in LANGUAGES:
            catalog = catalog_of(language)
            text, tip = catalog[f"ui.action.{name}"], catalog[f"ui.action.{name}.tip"]
            assert text.strip() and tip.strip() and text != tip, (language, name)
