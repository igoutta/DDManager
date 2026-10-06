"""Logging, uncaught-exception hooks (sys + threads), Qt message handler and faulthandler."""

import faulthandler
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

import pytest
from PySide6.QtCore import qInstallMessageHandler, qWarning

from src.ui.errors import (
    configure_logging,
    enable_faulthandler,
    install_exception_hooks,
    install_qt_message_handler,
)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def log():
    logger = logging.getLogger("ddm-test-hooks")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = Capture()
    logger.addHandler(handler)
    logger.records = handler.records  # ty: ignore[unresolved-attribute]
    yield logger
    logger.removeHandler(handler)


@pytest.fixture
def hooks(qapp, monkeypatch):
    """Restores ``sys.excepthook`` / ``threading.excepthook`` whatever the test does."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    return []


def boom():
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        return sys.exc_info()


def test_uncaught_exception_is_logged_and_shown_once_on_the_gui_thread(qtbot, log, hooks):
    shown = []
    install_exception_hooks(
        log, lambda title, details: shown.append((threading.current_thread(), title, details))
    )
    sys.excepthook(*boom())
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)
    thread, title, details = shown[0]
    assert thread is threading.main_thread()
    assert title and "kaboom" in details and "RuntimeError" in details
    assert any("kaboom" in r.getMessage() or "kaboom" in str(r.exc_info) for r in log.records)
    assert any(r.levelno >= logging.ERROR for r in log.records)


def test_keyboard_interrupt_passes_through(qtbot, log, hooks, monkeypatch):
    passed = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *args: passed.append(args[0]))
    shown = []
    install_exception_hooks(log, lambda *a: shown.append(a))
    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    qtbot.wait(100)
    assert passed == [KeyboardInterrupt]
    assert shown == []


def test_thread_exceptions_reach_the_dialog_on_the_gui_thread(qtbot, log, hooks):
    shown = []
    install_exception_hooks(
        log, lambda title, details: shown.append((threading.current_thread(), details))
    )

    def worker():
        raise ValueError("from worker")

    thread = threading.Thread(target=worker, name="ddm-worker")
    thread.start()
    thread.join()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)
    assert shown[0][0] is threading.main_thread()
    assert "from worker" in shown[0][1]


def test_errors_raised_while_the_dialog_is_open_are_only_logged(qtbot, log, hooks):
    shown = []

    def dialog(title, details):
        shown.append(details)
        sys.excepthook(*boom())  # an error inside the crash dialog itself
        qtbot.wait(50)

    install_exception_hooks(log, dialog)
    sys.excepthook(*boom())
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)
    qtbot.wait(150)
    assert len(shown) == 1
    assert len([r for r in log.records if r.levelno >= logging.ERROR]) >= 2


def test_configure_logging_writes_a_rotating_file(tmp_path):
    logger = configure_logging(tmp_path / "logs", logging.INFO)
    try:
        logger.info("hello file")
        for handler in logger.handlers:
            handler.flush()
        files = list((tmp_path / "logs").glob("*.log*"))
        assert files
        assert any("hello file" in f.read_text(encoding="utf-8") for f in files)
        rotating = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
        assert rotating and rotating[0].maxBytes == 1_000_000 and rotating[0].backupCount == 3
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


def test_no_stderr_handler_when_there_is_no_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    logger = configure_logging(tmp_path / "logs")
    try:
        kinds = {type(h) for h in logger.handlers}
        assert logging.StreamHandler not in kinds
        logger.warning("no stderr, no crash")
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


def test_qt_messages_are_routed_to_the_log(qapp, log):
    install_qt_message_handler(log)
    try:
        qWarning("qt says hi")
    finally:
        qInstallMessageHandler(None)
    assert any("qt says hi" in r.getMessage() for r in log.records)
    assert any(r.levelno == logging.WARNING for r in log.records)


def test_faulthandler_writes_to_the_logs_dir(tmp_path):
    was_enabled = faulthandler.is_enabled()
    try:
        handle = enable_faulthandler(tmp_path / "logs")
        assert faulthandler.is_enabled()
        assert list((tmp_path / "logs").glob("faulthandler*"))
        assert not handle.closed
    finally:
        faulthandler.disable()
        if was_enabled:
            faulthandler.enable()
