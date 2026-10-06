"""Composition root of the desktop application: the only module that wires every layer."""

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

import src
from src.__about__ import __version__
from src.app_selftest import run_self_test
from src.services.app_paths import AppPaths, resolve_app_paths
from src.services.bootstrap import Services, build_services
from src.services.environment import Environment
from src.services.platform_actions import detect_default_language
from src.services.settings_repo import PluginTrust, SettingsRepository
from src.ui.controller import MainController
from src.ui.dialogs.crash_dialog import CrashDialog
from src.ui.errors import (
    configure_logging,
    enable_faulthandler,
    install_exception_hooks,
    install_qt_message_handler,
)
from src.ui.i18n import Translator
from src.ui.theme.theme import apply_theme
from src.ui.theme.tokens import DARK_TOKENS
from src.ui.thumbnails import ThumbnailProvider
from src.ui.widgets.actions import IconSet
from src.ui.widgets.main_window import MainWindow
from src.ui.widgets.prompter import QtPrompter
from src.ui.workers import QtExecutor

APP_NAME = "DD Manager"
LOCK_WAIT_MS = 200


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ddmanager", description="DD Manager")
    parser.add_argument("--data-dir", type=Path, default=None, help="use this data folder")
    parser.add_argument("--lang", default=None, help="UI language code (en, es_ES, pt_PT, zh_CN)")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING or ERROR")
    parser.add_argument("--self-test", action="store_true", help="check the installation, exit")
    parser.add_argument("--safe-mode", action="store_true", help="do not load user plugins/rules")
    return parser.parse_args(list(sys.argv[1:] if argv is None else argv))


def resolve_paths(args: argparse.Namespace, env: Environment) -> AppPaths:
    return resolve_app_paths(
        frozen=bool(getattr(sys, "frozen", False)),
        executable=Path(sys.executable),
        package_init=Path(src.__file__),
        env=env,
        override=args.data_dir,
    )


def create_application() -> QApplication:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    return app


def build_app_services(paths: AppPaths, env: Environment, *, safe_mode: bool) -> Services:
    """Wire the services; safe mode keeps the user's settings but trusts no user code."""
    if not safe_mode:
        return build_services(paths, env=env)
    paths.ensure()
    settings, _findings = SettingsRepository(paths.settings_file).load()
    return build_services(
        paths, env=env, settings=replace(settings, plugins=PluginTrust(), rules=PluginTrust())
    )


def pick_language(args: argparse.Namespace, services: Services, env: Environment) -> str:
    return args.lang or services.state.read_language() or detect_default_language(env)


def acquire_lock(paths: AppPaths, translator: Translator) -> QLockFile | None:
    """The single-instance lock; a second instance explains itself and gets ``None``."""
    lock = QLockFile(str(paths.lock_file))
    if lock.tryLock(LOCK_WAIT_MS):
        return lock
    QMessageBox.information(None, APP_NAME, translator.tr("ui.app.already_running"))
    return None


def run_gui(args: argparse.Namespace, paths: AppPaths, env: Environment) -> int:
    services = build_app_services(paths, env, safe_mode=args.safe_mode)
    services.state.ensure_pre_upgrade_copy()
    log = configure_logging(paths.logs_dir, str(args.log_level).upper())
    enable_faulthandler(paths.logs_dir)
    install_qt_message_handler(log)
    app = create_application()
    translator = Translator.from_resources(pick_language(args, services, env))
    lock = acquire_lock(paths, translator)
    if lock is None:
        return 0
    apply_theme(app, DARK_TOKENS)
    executor = QtExecutor()
    thumbnails = ThumbnailProvider(executor)
    controller = MainController(services, executor, translator, thumbnails)
    window = MainWindow(controller, translator, DARK_TOKENS, IconSet(DARK_TOKENS))
    controller.attach_prompter(QtPrompter(window, translator))
    install_crash_dialog(app, log, window, translator, paths)
    app.aboutToQuit.connect(lock.unlock)
    window.show()
    QTimer.singleShot(0, controller.start)
    return app.exec()


def install_crash_dialog(
    app: QApplication,
    log: logging.Logger,
    window: MainWindow,
    translator: Translator,
    paths: AppPaths,
) -> None:
    def show(title: str, details: str) -> None:
        dialog = CrashDialog(title, details, translator, paths.logs_dir, window)
        if dialog.exec() == CrashDialog.DialogCode.Rejected:
            app.quit()

    install_exception_hooks(log, show)


def main(argv: Sequence[str] | None = None) -> int:
    """Start the GUI (``--self-test`` checks the installation instead and never shows it)."""
    args = parse_args(argv)
    env = Environment.from_host()
    paths = resolve_paths(args, env)
    if args.self_test:
        create_application()
        return run_self_test(paths)
    return run_gui(args, paths, env)
