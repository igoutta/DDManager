"""Logging, crash hooks, the Qt message handler and faulthandler."""

import faulthandler
import logging
import sys
import threading
import traceback
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import IO, Final

from PySide6.QtCore import QObject, Qt, QtMsgType, Signal, Slot, qInstallMessageHandler

LOGGER_NAME: Final = "ddmanager"
LOG_FILE: Final = "ddmanager.log"
FAULT_FILE: Final = "faulthandler.log"
# faulthandler's Windows handler also reports *first-chance* exceptions that the OS or Qt
# catch right away. 0x8001010D (RPC_E_CANTCALLOUT_ININPUTSYNCCALL, raised by COM during
# input-sync calls such as drag-and-drop or UI Automation) is the usual one; the process
# keeps running.
FAULT_HEADER: Final = (
    "# DD Manager faulthandler log. Entries with 'code 0x8001010d' are first-chance COM "
    "exceptions handled by Windows/Qt (not crashes); a real crash ends the session here."
    "\n"
)
LOG_BYTES: Final = 1_000_000
LOG_BACKUPS: Final = 3
CRASH_TITLE: Final = "Unexpected error"
_MARK: Final = "_ddm_handler"

_QT_LEVELS: Final = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}

type DialogFactory = Callable[[str, str], None]

_fault_file: IO[str] | None = None


def configure_logging(logs_dir: Path, level: int | str = logging.INFO) -> logging.Logger:
    """Rotating file log (1 MB x 3); a stderr handler only when a stderr exists."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(LOGGER_NAME)
    log.setLevel(level)
    for handler in list(log.handlers):
        if getattr(handler, _MARK, False):
            log.removeHandler(handler)
            handler.close()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            logs_dir / LOG_FILE, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _MARK, True)
        log.addHandler(handler)
    return log


class _CrashRelay(QObject):
    """GUI-thread relay: always queued, so a dialog never opens inside a paint/drag handler."""

    crashed = Signal(str)

    def __init__(self, dialog_factory: DialogFactory) -> None:
        super().__init__()
        self._dialog_factory = dialog_factory
        self._showing = False
        self.crashed.connect(self._show, Qt.ConnectionType.QueuedConnection)

    @Slot(str)
    def _show(self, details: str) -> None:
        if self._showing:
            return
        self._showing = True
        try:
            self._dialog_factory(CRASH_TITLE, details)
        finally:
            self._showing = False


class ExceptionHooks:
    """Installed ``sys.excepthook``/``threading.excepthook``; ``uninstall()`` restores them."""

    def __init__(self, log: logging.Logger, dialog_factory: DialogFactory) -> None:
        self._log = log
        self._relay = _CrashRelay(dialog_factory)
        self._prev_sys = sys.excepthook
        self._prev_thread = threading.excepthook
        sys.excepthook = self._on_sys
        threading.excepthook = self._on_thread

    def uninstall(self) -> None:
        sys.excepthook = self._prev_sys
        threading.excepthook = self._prev_thread

    def _report(
        self,
        exc_type: type[BaseException],
        exc: BaseException | None,
        tb: TracebackType | None,
        origin: str,
    ) -> None:
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        self._log.critical("Unhandled exception in %s\n%s", origin, details)
        self._relay.crashed.emit(details)

    def _on_sys(
        self, exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        self._report(exc_type, exc, tb, "main thread")

    def _on_thread(self, args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit or args.exc_type is None:
            return
        name = args.thread.name if args.thread is not None else "unknown thread"
        self._report(args.exc_type, args.exc_value, args.exc_traceback, name)


def install_exception_hooks(log: logging.Logger, dialog_factory: DialogFactory) -> ExceptionHooks:
    """Route uncaught exceptions to ``log`` and, queued on the GUI thread, ``dialog_factory``."""
    return ExceptionHooks(log, dialog_factory)


def install_qt_message_handler(log: logging.Logger) -> None:
    """Send Qt's own warnings and errors to ``log``."""

    def handler(kind: QtMsgType, context: object, message: str) -> None:
        del context
        log.log(_QT_LEVELS.get(kind, logging.WARNING), "Qt: %s", message)

    qInstallMessageHandler(handler)


def enable_faulthandler(logs_dir: Path) -> IO[str]:
    """Dump native crash tracebacks into ``faulthandler.log`` (the file stays open on purpose)."""
    global _fault_file  # noqa: PLW0603 - faulthandler needs the file object to outlive this call
    logs_dir.mkdir(parents=True, exist_ok=True)
    if _fault_file is not None:
        faulthandler.disable()
        _fault_file.close()
    _fault_file = (logs_dir / FAULT_FILE).open("a", encoding="utf-8")
    _fault_file.write(FAULT_HEADER)
    _fault_file.flush()
    faulthandler.enable(file=_fault_file, all_threads=True)
    return _fault_file
