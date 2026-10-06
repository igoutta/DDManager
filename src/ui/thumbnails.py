"""Row thumbnails: decode to ``QImage`` in a worker, convert to ``QPixmap`` on the GUI thread."""

from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QImageReader, QPixmap, QPixmapCache

from src.core.ids import ModId
from src.ui.ports import CancelToken, Executor

POOL = "thumbs"
CACHE_LIMIT_KB = 64 * 1024


class ThumbnailError(Exception):
    """The file could not be decoded as an image."""


def decode_thumbnail(path: Path, max_px: int) -> QImage:
    """Decode and smooth-scale ``path`` to fit ``max_px``; safe to call from any thread."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    reader.setDecideFormatFromContent(True)
    image = reader.read()
    if image.isNull():
        raise ThumbnailError(reader.errorString())
    if max(image.width(), image.height()) <= max_px:
        return image
    return image.scaled(
        max_px,
        max_px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _device_pixel_ratio() -> float:
    screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


class ThumbnailProvider(QObject):
    """``pixmap()`` returns a cached pixmap or ``None`` and queues a decode; ``ready`` follows."""

    ready = Signal(str)

    def __init__(self, executor: Executor, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._executor = executor
        self._waiting: dict[str, set[ModId]] = {}
        self._failed: set[str] = set()
        if QPixmapCache.cacheLimit() < CACHE_LIMIT_KB:
            QPixmapCache.setCacheLimit(CACHE_LIMIT_KB)

    @staticmethod
    def cache_key(path: Path, stamp: int | None, px: int, dpr: float) -> str:
        return f"ddm-thumb|{path}|{stamp}|{px}|{dpr:g}"

    def pixmap(
        self, mod_id: ModId, path: Path | None, stamp: int | None, px: int
    ) -> QPixmap | None:
        if path is None or px <= 0:
            return None
        dpr = _device_pixel_ratio()
        key = self.cache_key(path, stamp, px, dpr)
        if key in self._failed:
            return None
        cached = QPixmap()
        if QPixmapCache.find(key, cached):
            return cached
        waiting = self._waiting.get(key)
        if waiting is not None:
            waiting.add(mod_id)
            return None
        self._waiting[key] = {mod_id}
        self._start_decode(key, path, px, dpr)
        return None

    def _start_decode(self, key: str, path: Path, px: int, dpr: float) -> None:
        target = max(1, round(px * dpr))

        def work(token: CancelToken) -> QImage:
            if token.is_cancelled():
                raise ThumbnailError("cancelled")
            return decode_thumbnail(path, target)

        self._executor.submit(
            work,
            on_ok=lambda image: self._on_decoded(key, image, dpr),
            on_err=lambda _exc: self._on_failed(key),
            pool=POOL,
        )

    def _on_decoded(self, key: str, image: QImage, dpr: float) -> None:
        pixmap = QPixmap.fromImage(image)  # GUI thread only
        pixmap.setDevicePixelRatio(dpr)
        QPixmapCache.insert(key, pixmap)
        for mod_id in self._waiting.pop(key, set()):
            self.ready.emit(mod_id)

    def _on_failed(self, key: str) -> None:
        self._failed.add(key)
        self._waiting.pop(key, None)

    def clear(self) -> None:
        """Forget failures (after a rescan) so changed files are retried."""
        self._failed.clear()
