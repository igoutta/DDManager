"""ThumbnailProvider: decoding, content sniffing, failures and in-flight de-duplication."""

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage, QImageWriter

from src.ui.thumbnails import ThumbnailProvider
from src.ui.workers import QtExecutor


class CountingExecutor:
    def __init__(self, inner):
        self.inner = inner
        self.submits = 0

    def submit(self, fn, **kwargs):
        self.submits += 1
        return self.inner.submit(fn, **kwargs)


@pytest.fixture
def executor(qapp):
    return CountingExecutor(QtExecutor())


@pytest.fixture
def provider(executor):
    return ThumbnailProvider(executor)


def make_image(path: Path, fmt: str, size: int = 300) -> Path:
    image = QImage(size, size // 2, QImage.Format.Format_RGB32)
    image.fill(QColor("#B99A45"))
    assert QImageWriter(str(path), fmt.encode()).write(image), fmt
    return path


def wait_ready(qtbot, provider, mod_id, path, stamp, px):
    with qtbot.waitSignal(provider.ready, timeout=5000) as blocker:
        assert provider.pixmap(mod_id, path, stamp, px) is None
    assert blocker.args == [mod_id]


@pytest.mark.parametrize(("fmt", "name"), [("JPG", "a.jpg"), ("PNG", "a.png")])
def test_decodes_and_caches_scaled(qtbot, provider, tmp_path, fmt, name):
    path = make_image(tmp_path / name, fmt)
    wait_ready(qtbot, provider, "m1", path, 7, 64)
    pixmap = provider.pixmap("m1", path, 7, 64)
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.deviceIndependentSize().width() <= 64 + 1


def test_content_is_sniffed_not_the_extension(qtbot, provider, tmp_path):
    path = make_image(tmp_path / "really_png.jpg", "PNG")
    wait_ready(qtbot, provider, "sniffed", path, 1, 48)
    assert provider.pixmap("sniffed", path, 1, 48) is not None


def test_a_new_stamp_decodes_again(qtbot, provider, tmp_path):
    path = make_image(tmp_path / "s.png", "PNG")
    wait_ready(qtbot, provider, "s", path, 1, 48)
    assert provider.pixmap("s", path, 2, 48) is None
    qtbot.waitUntil(lambda: provider.pixmap("s", path, 2, 48) is not None, timeout=5000)


def test_missing_and_corrupt_files_yield_none_and_are_remembered(
    qtbot, provider, executor, tmp_path
):
    missing = tmp_path / "nope.png"
    corrupt = tmp_path / "bad.png"
    corrupt.write_bytes(b"not an image at all")
    for path in (missing, corrupt):
        assert provider.pixmap("x", path, 1, 32) is None
        qtbot.wait(300)
        assert provider.pixmap("x", path, 1, 32) is None
    submitted = executor.submits
    for _ in range(3):
        assert provider.pixmap("x", missing, 1, 32) is None
    qtbot.wait(100)
    assert executor.submits == submitted  # failures are cached, never retried


def test_no_path_or_size_means_no_work(provider, executor):
    assert provider.pixmap("x", None, None, 32) is None
    assert provider.pixmap("x", Path("whatever.png"), None, 0) is None
    assert executor.submits == 0


def test_in_flight_requests_are_deduplicated(qtbot, provider, executor, tmp_path):
    path = make_image(tmp_path / "d.png", "PNG")
    seen = []
    provider.ready.connect(seen.append)
    for mod in ("a", "b", "c", "a"):
        assert provider.pixmap(mod, path, 1, 40) is None
    assert executor.submits == 1
    qtbot.waitUntil(lambda: {"a", "b", "c"} <= set(seen), timeout=5000)


def test_threaded_decode_returns_to_the_gui_thread(qtbot, provider, tmp_path):
    import threading

    path = make_image(tmp_path / "t.png", "PNG")
    threads = []
    provider.ready.connect(lambda _id: threads.append(threading.current_thread()))
    provider.pixmap("t", path, 1, 40)
    qtbot.waitUntil(lambda: bool(threads), timeout=5000)
    assert threads[0] is threading.main_thread()
