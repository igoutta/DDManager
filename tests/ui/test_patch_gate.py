"""Health Check errors gate Patch Save, and enabled mods missing from disk are never written.

Plan M4 / contract §4: the preview lists the current report's ERROR findings, its primary button
stays disabled until "Patch despite N errors" is ticked, and a cancelled dialog never applies.
An enabled mod whose folder is gone keeps its ERROR finding (with the Disable fix) but is left
out of the entries written to the save: never written from the stale ``metadata`` identity.
"""

import pytest
from PySide6.QtWidgets import QCheckBox, QLabel

from src.core.findings import DisableMods, Severity
from src.rules.duplicate_identity import RULE_ID as DUPLICATE
from src.rules.missing_from_disk import RULE_ID as MISSING
from src.ui.dialogs.patch_preview_dialog import PatchPreviewDialog
from src.ui.ports import PatchDecision
from src.ui.viewmodels import PatchPreviewVM
from tests.support.factories import local_mod
from tests.ui.conftest import ENABLED

GONE = ENABLED[3]  # enabled, not among the entries the fake save already lists
STALE_NAME = "Crusader Compat (stale)"
STALE_METADATA = {
    "title": STALE_NAME,
    "published_file_id": "",
    "save_name": STALE_NAME,
    "save_source": "mod_local_source",
    "version_label": "",
    "updated_label": "",
    "black_reliquary": False,
    "metadata_path": "",
    "project_mtime": None,
    "localization_signature": "",
    "workshop_timeupdated": "",
}
OVERRIDE = PatchDecision(True, frozenset(), True)


def previews(rig) -> list[PatchPreviewVM]:
    return rig.prompter.objects_of(PatchPreviewVM)


def errors(vm: PatchPreviewVM) -> list[str]:
    return [f.rule_id for f in vm.findings if f.severity >= Severity.ERROR]


@pytest.fixture
def make_rig(rig_factory):
    """A rig whose state still carries ``GONE``'s v0.2.1 metadata while its folder is gone."""

    def make(answers=None):
        rig = rig_factory(answers=answers, extra={"metadata": {GONE: STALE_METADATA}})
        catalog = {k: v for k, v in rig.services.catalog.items() if k != GONE}
        rig.services.scanner.set_catalog(catalog)
        rig.controller.rescan()
        rig.messages.clear()
        return rig

    return make


@pytest.fixture
def rig(make_rig):
    return make_rig()


# ---------------------------------------------------------------------------- the gate


def test_an_error_finding_makes_the_preview_blocking_and_lists_it(rig):
    rig.controller.patch_save()
    (vm,) = previews(rig)
    assert vm.blocking
    assert errors(vm) == [MISSING]
    (finding,) = [f for f in vm.findings if f.rule_id == MISSING]
    assert finding.mod_ids == (GONE,)
    assert vm.missing_count == 1


def test_a_decision_without_the_override_never_applies(rig):
    rig.controller.patch_save()  # the default answer proceeds without overriding the errors
    assert rig.prompter.count("review_patch") == 1
    assert rig.services.patcher.applies == []
    assert rig.services.backups.created == []


def test_cancelling_never_applies_whatever_the_boxes_say(make_rig):
    rig = make_rig({"review_patch": PatchDecision(False, frozenset(), True)})
    rig.controller.patch_save()
    assert rig.services.patcher.applies == []


def test_the_override_applies_without_the_missing_mod(make_rig):
    rig = make_rig({"review_patch": OVERRIDE})
    rig.controller.patch_save()
    ((plan, _acks),) = rig.services.patcher.applies
    assert plan.after == tuple(rig.mods[m].save_identity for m in ENABLED if m != GONE)
    stale = rig.controller.session.doc.metadata_identities[GONE]
    assert stale.name == STALE_NAME and stale not in plan.after


def test_a_duplicate_identity_error_gates_too(rig_factory, fake_services):
    twin = local_mod("twin_of_chorus", title="chorus_class_mod")  # same (title, local) identity
    rig = rig_factory(
        catalog={**fake_services.catalog, twin.id: twin}, enabled=(*ENABLED, "twin_of_chorus")
    )
    rig.controller.patch_save()
    (vm,) = previews(rig)
    assert vm.blocking
    assert DUPLICATE in errors(vm)
    assert vm.missing_count == 0
    assert rig.services.patcher.applies == []


def test_disabling_the_missing_mod_through_its_fix_unblocks_the_preview(rig):
    finding = next(
        f for f in rig.controller.session.findings if f.rule_id == MISSING and GONE in f.mod_ids
    )
    assert finding.severity is Severity.ERROR
    assert isinstance(finding.fix, DisableMods)
    rig.controller.apply_fix(finding.key)
    rig.controller.patch_save()
    (vm,) = previews(rig)
    assert not vm.blocking
    assert vm.missing_count == 0
    assert errors(vm) == []


# ---------------------------------------------------------------------------- the dialog


def test_the_dialog_disables_the_primary_button_until_the_override_is_ticked(
    rig, qtbot, translator
):
    rig.controller.patch_save()
    (vm,) = previews(rig)
    dialog = PatchPreviewDialog(vm, translator)
    qtbot.addWidget(dialog)
    assert not dialog.patch_button.isEnabled()
    (override,) = [b for b in dialog.findChildren(QCheckBox) if "despite" in b.text()]
    assert "1" in override.text()
    assert dialog.errors is not None
    listed = [dialog.errors.item(i).text() for i in range(dialog.errors.count())]
    assert any(GONE in text for text in listed), listed
    notes = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("1 enabled mod" in text and "will not be written" in text for text in notes), notes
    override.setChecked(True)
    assert dialog.patch_button.isEnabled()
    assert dialog.decision() == PatchDecision(True, frozenset(), True)
    override.setChecked(False)
    assert not dialog.patch_button.isEnabled()
    assert dialog.decision().proceed is False


# ---------------------------------------------------------------------------- save code


def test_save_code_leaves_the_missing_mod_out(rig):
    vm = rig.controller.tools.save_code()
    assert vm is not None
    assert vm.count == len(ENABLED) - 1
    assert STALE_NAME not in vm.text
    assert rig.mods[ENABLED[0]].save_identity.name in vm.text
