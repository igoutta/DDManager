"""Fixtures of the UI tests.  ``QT_QPA_PLATFORM`` must be set before PySide6 is imported."""

import os

from tests.ui.offscreen import platform_argument

os.environ.setdefault("QT_QPA_PLATFORM", platform_argument())

from pathlib import Path

import pytest

from src.core.ids import ModId
from src.services.app_paths import AppPaths, DataDirMode
from src.services.bootstrap import build_services
from src.services.settings_repo import Settings
from src.ui.controller import MainController
from src.ui.widgets.main_window import MainWindow
from tests.ui import fakes
from tests.ui.helpers import FakePrompter, FakeThumbs, build, make_rows

# Enabled order of the canned state; every other catalog mod starts disabled.
ENABLED = (
    "chorus_class_mod",
    "2248772895",
    "swf_trinkets24_compat",
    "crusader_hu_swf_compat",
    "1739565783",
    "better_stage_coach_swf_compat",
)
CATEGORIES = {
    "better_stage_coach_swf_compat": "Patch",
    "chorus_class_mod": "Class",
    "1739565783": "UI",
}


@pytest.fixture
def rows_factory():
    """``rows_factory(n, tiers=TIER_CYCLE, **overrides) -> list[ModRowVM]``."""
    return make_rows


@pytest.fixture
def thumbs(qapp):
    return FakeThumbs()


@pytest.fixture
def tokens(qapp):
    from src.ui.theme.tokens import DARK_TOKENS

    return DARK_TOKENS


@pytest.fixture
def icons(qapp, tokens):
    from src.ui.widgets.actions import IconSet

    return IconSet(tokens)


@pytest.fixture
def translator(qapp):
    """English translator; whatever language a test switched to is undone afterwards, because
    the ``qtbase_<lang>`` translator it installs on the application is global (it would change
    how later tests see key sequences and standard button texts)."""
    from src.ui.i18n import Translator

    tr = Translator.from_resources("en")
    yield tr
    if tr.language() != "en":
        tr.set_language("en")


@pytest.fixture
def order_model(qtbot, thumbs, translator):
    from src.ui.models.load_order_model import LoadOrderModel

    return build(LoadOrderModel, thumbs=thumbs, translator=translator)


@pytest.fixture
def immediate_executor(qapp):
    from src.ui.workers import ImmediateExecutor

    return build(ImmediateExecutor)


@pytest.fixture
def fake_prompter():
    """``fake_prompter(answers=None) -> FakePrompter`` (answers: method -> value/callable/list)."""

    def make(answers=None) -> FakePrompter:
        return FakePrompter(answers)

    return make


@pytest.fixture
def fake_services(tmp_path: Path, tmp_path_factory: pytest.TempPathFactory, sample_mods_dir: Path):
    """Real wiring for settings/rules/registry, in-memory doubles for everything with I/O.

    The save lives outside ``tmp_path`` so its path never carries the test's own name (the
    status bar shows it, and tests look for words such as "wins" in the window's labels).
    """
    paths = AppPaths(tmp_path / "data", DataDirMode.OVERRIDE, None, "test")
    real = build_services(paths, settings=Settings())
    save_path = tmp_path_factory.mktemp("saves") / "profile_0" / "persist.game.json"
    save_path.parent.mkdir(parents=True)
    save_path.write_bytes(b"fake save")
    catalog = fakes.build_catalog(sample_mods_dir)
    state = fakes.FakeState(
        fakes.build_state(
            catalog,
            enabled=ENABLED,
            mods_path=sample_mods_dir,
            save_path=save_path,
            categories=CATEGORIES,
        )
    )
    in_save = [catalog[ModId(key)].save_identity for key in ENABLED[:3]]
    backups = fakes.FakeBackups(tmp_path / "backups")
    return fakes.FakeServices(
        real,
        scanner=fakes.FakeScanner(catalog),
        detector=fakes.FakeDetector(sample_mods_dir, save_path),
        state=state,
        slots=fakes.FakeSlots(save_path, in_save),
        backups=backups,
        patcher=fakes.FakePatcher(backups, in_save),
        catalog=catalog,
        save_path=save_path,
        in_save=in_save,
    )


@pytest.fixture
def make_controller(qtbot, fake_services, immediate_executor, fake_prompter, thumbs, translator):
    """``make_controller(answers=None) -> (controller, prompter)``; not started."""
    from src.ui.controller import MainController

    def make(answers=None):
        prompter = fake_prompter(answers)
        controller = build(
            MainController,
            services=fake_services,
            executor=immediate_executor,
            prompter=prompter,
            translator=translator,
            thumbs=thumbs,
        )
        return controller, prompter

    return make


@pytest.fixture
def started(make_controller):
    """``(controller, prompter)`` after ``start()`` ran on the immediate executor."""
    controller, prompter = make_controller()
    controller.start()
    return controller, prompter


class HarnessWindow(MainWindow):
    """The real window plus the doubles the tests drive it with."""

    test_controller: MainController
    test_prompter: FakePrompter


@pytest.fixture
def window_factory(qtbot, fake_services, make_controller, translator, thumbs, tokens, icons):
    """``window_factory() -> HarnessWindow`` over a fresh, unstarted controller."""

    def make() -> HarnessWindow:
        controller, prompter = make_controller()
        window = build(
            HarnessWindow,
            controller=controller,
            translator=translator,
            thumbs=thumbs,
            tokens=tokens,
            icons=icons,
            services=fake_services,
            prompter=prompter,
            settings_path=fake_services.paths.ui_settings_file,
        )
        qtbot.addWidget(window)
        window.test_controller = controller
        window.test_prompter = prompter
        return window

    return make


@pytest.fixture
def main_window(window_factory):
    return window_factory()


@pytest.fixture
def rig_factory(
    qtbot, fake_services, immediate_executor, thumbs, translator, tokens, icons, monkeypatch
):
    """``rig_factory(...) -> Rig``: a started controller (and window) over customised fakes.

    ``catalog`` replaces what the scanner finds, ``enabled``/``categories`` and every other
    ``fakes.build_state`` keyword shape the state file, ``applied_keys`` is what the active save
    lists, ``answers`` configures the prompter.  Everything is in place BEFORE the controller
    is created, because it reads the state at construction.
    """
    from tests.ui import m5_support as m5

    def make(
        *,
        catalog=None,
        enabled=ENABLED,
        categories=CATEGORIES,
        applied_keys=None,
        answers=None,
        window=False,
        start=True,
        **state,
    ) -> m5.Rig:
        services = fake_services
        if catalog is not None:
            services.catalog = dict(catalog)
            services.scanner.set_catalog(services.catalog)
        services.state.doc = fakes.build_state(
            services.catalog,
            enabled=enabled,
            mods_path=services.detector.snapshot.primary_mods_dir,
            save_path=services.save_path,
            categories=categories,
            **state,
        )
        services.renamer = services.folder_renamer = fakes.FakeRenamer(services.scanner)
        if applied_keys is not None:
            applied = tuple(services.catalog[ModId(k)].save_identity for k in applied_keys)
            services.slots.applied = services.patcher.applied = applied
        prompter = m5.RecordingPrompter(answers)
        controller = build(
            MainController,
            services=services,
            executor=immediate_executor,
            prompter=prompter,
            translator=translator,
            thumbs=thumbs,
        )
        messages = m5.Messages(translator)
        messages.attach(controller, prompter, monkeypatch)
        driver, prompts = m5.DialogDriver(), m5.StaticPrompts()
        driver.install(monkeypatch)
        prompts.install(monkeypatch)
        rig = m5.Rig(services, controller, prompter, translator, messages, driver, prompts)
        if window:
            rig.window = build(
                HarnessWindow,
                controller=controller,
                translator=translator,
                thumbs=thumbs,
                tokens=tokens,
                icons=icons,
                services=services,
                prompter=prompter,
                settings_path=services.paths.ui_settings_file,
            )
            qtbot.addWidget(rig.window)
            rig.window.test_controller, rig.window.test_prompter = controller, prompter
        if start:
            controller.start()
            messages.clear()
        return rig

    return make
