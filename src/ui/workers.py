"""Background execution: a QThreadPool-backed executor with results marshalled to the GUI thread.

Workers may create ``QImage`` but never ``QPixmap``. Results travel through a relay ``QObject``
living in the GUI thread over a queued connection, so no callback ever runs on a worker thread.
"""

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from src.ui.ports import CancelToken, TaskHandle

THUMB_THREADS = 2


class _Token:
    """A cancellation flag shared between the GUI thread and one worker run."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


class _Handle:
    def __init__(self, token: _Token) -> None:
        self._token = token
        self.finished = False

    def cancel(self) -> None:
        self._token.cancel()

    @property
    def done(self) -> bool:
        return self.finished


class _Relay(QObject):
    """Lives in the GUI thread; runs the callables emitted by worker threads."""

    deliver = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.deliver.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _run(self, fn: object) -> None:
        if callable(fn):
            fn()


class _Task(QRunnable):
    def __init__(self, work: Callable[[], None]) -> None:
        super().__init__()
        self.setAutoDelete(False)  # Python owns it; the executor keeps it alive until delivered
        self._work = work

    def run(self) -> None:
        self._work()


class QtExecutor:
    """``Executor`` over named ``QThreadPool`` instances ("io" global, "thumbs" two threads)."""

    def __init__(self, pools: dict[str, QThreadPool] | None = None) -> None:
        self._relay = _Relay()
        if pools is None:
            thumbs = QThreadPool()
            thumbs.setMaxThreadCount(THUMB_THREADS)
            pools = {"io": QThreadPool.globalInstance(), "thumbs": thumbs}
        self._pools = pools
        self._alive: set[_Task] = set()
        self._generation: dict[str, int] = {}
        self._tokens: dict[str, _Token] = {}

    def submit[T](
        self,
        fn: Callable[[CancelToken], T],
        *,
        on_ok: Callable[[T], None],
        on_err: Callable[[BaseException], None],
        key: str | None = None,
        pool: str = "io",
    ) -> TaskHandle:
        token = _Token()
        handle = _Handle(token)
        generation = self._claim(key, token)
        tasks: list[_Task] = []

        def finish(outcome: tuple[T, None] | tuple[None, BaseException] | None) -> None:
            self._alive.difference_update(tasks)
            handle.finished = True
            if outcome is None or token.is_cancelled() or self._stale(key, generation):
                return
            result, error = outcome
            if error is not None:
                on_err(error)
            else:
                on_ok(result)  # ty: ignore[invalid-argument-type]

        def work() -> None:
            outcome: tuple[T, None] | tuple[None, BaseException] | None = None
            if not token.is_cancelled():
                try:
                    outcome = (fn(token), None)
                except BaseException as exc:  # noqa: BLE001 - forwarded to on_err on the GUI thread
                    outcome = (None, exc)
            self._relay.deliver.emit(lambda: finish(outcome))

        task = _Task(work)
        tasks.append(task)
        self._alive.add(task)
        self._pools[pool].start(task)
        return handle

    def _claim(self, key: str | None, token: _Token) -> int:
        """Cancel the previous run for ``key`` and return this run's generation."""
        if key is None:
            return 0
        previous = self._tokens.get(key)
        if previous is not None:
            previous.cancel()
        self._tokens[key] = token
        generation = self._generation.get(key, 0) + 1
        self._generation[key] = generation
        return generation

    def _stale(self, key: str | None, generation: int) -> bool:
        return key is not None and self._generation.get(key) != generation

    def wait_idle(self, timeout_ms: int = 5000) -> bool:
        """Block until every pool is idle; queued deliveries still need an event loop."""
        return all(pool.waitForDone(timeout_ms) for pool in self._pools.values())


class ImmediateExecutor:
    """Runs the task inline on the calling thread: deterministic tests."""

    def submit[T](
        self,
        fn: Callable[[CancelToken], T],
        *,
        on_ok: Callable[[T], None],
        on_err: Callable[[BaseException], None],
        key: str | None = None,
        pool: str = "io",
    ) -> TaskHandle:
        del key, pool
        token = _Token()
        handle = _Handle(token)
        try:
            result = fn(token)
        except Exception as exc:  # noqa: BLE001 - mirrors QtExecutor: errors go to on_err
            handle.finished = True
            on_err(exc)
            return handle
        handle.finished = True
        on_ok(result)
        return handle
