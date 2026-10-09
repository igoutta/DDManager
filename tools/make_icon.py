"""Generate ``packaging/ddmanager.ico``: a lit torch on a dark, gold-rimmed tile.

Run it once (``uv run python tools/make_icon.py``) and commit the result; the build only reads
the file. Colors come from the app's palette tokens. The ``.ico`` holds PNG-compressed images at
every size Windows asks for (16 px taskbar/title bar up to the 256 px Explorer view).
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QImageWriter,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from src.ui.theme.tokens import DARK_TOKENS

ROOT = Path(__file__).absolute().parent.parent
TARGET = ROOT / "packaging" / "ddmanager.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _flame(
    cx: float, bottom: float, height: float, half_width: float, lean: float
) -> QPainterPath:
    """A teardrop flame in unit coordinates: wide at ``bottom``, tip ``height`` above, leaning right."""
    top = bottom - height
    path = QPainterPath()
    path.moveTo(cx, bottom)
    path.cubicTo(
        cx - half_width * 1.45,
        bottom - height * 0.22,
        cx - half_width * 0.95,
        bottom - height * 0.78,
        cx + lean,
        top,
    )
    path.cubicTo(
        cx + half_width * 1.05,
        bottom - height * 0.72,
        cx + half_width * 1.35,
        bottom - height * 0.18,
        cx,
        bottom,
    )
    path.closeSubpath()
    return path


def _draw_background(painter: QPainter, size: int) -> None:
    """Dark rounded square with a gold hairline and a warm glow where the flame will sit."""
    palette = DARK_TOKENS.palette
    border = max(1.0, size / 24)
    body = QRectF(border / 2, border / 2, size - border, size - border)
    painter.setPen(QPen(QColor(palette.gold), border))
    painter.setBrush(QColor(palette.ink))
    painter.drawRoundedRect(body, size * 0.16, size * 0.16)
    glow = QRadialGradient(size * 0.5, size * 0.36, size * 0.42)
    warm = QColor(palette.amber)
    warm.setAlpha(110)
    glow.setColorAt(0.0, warm)
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawRoundedRect(body, size * 0.16, size * 0.16)


def _draw_handle(painter: QPainter, size: int) -> None:
    """A tapered wooden shaft with a cloth wrap under the flame."""
    palette = DARK_TOKENS.palette
    shaft = QPainterPath()
    shaft.moveTo(size * 0.44, size * 0.56)
    shaft.lineTo(size * 0.56, size * 0.56)
    shaft.lineTo(size * 0.535, size * 0.92)
    shaft.lineTo(size * 0.465, size * 0.92)
    shaft.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(palette.border))
    painter.drawPath(shaft)
    painter.setBrush(QColor(palette.amber))
    painter.drawRect(QRectF(size * 0.475, size * 0.58, size * 0.02, size * 0.32))
    wrap = QRectF(size * 0.37, size * 0.50, size * 0.26, size * 0.10)
    painter.setBrush(QColor(palette.amber_hover))
    painter.drawRoundedRect(wrap, size * 0.03, size * 0.03)
    painter.setBrush(QColor(palette.gold))
    painter.drawRect(QRectF(size * 0.37, size * 0.535, size * 0.26, size * 0.018))


def _draw_flame(painter: QPainter, size: int) -> None:
    """Four nested tongues: crimson, amber, gold, then the bright core."""
    palette = DARK_TOKENS.palette
    layers = (
        (palette.crimson, 0.51, 0.50, 0.225, 0.045),
        (palette.amber, 0.51, 0.40, 0.160, 0.034),
        (palette.gold, 0.51, 0.29, 0.100, 0.020),
        (palette.text_bright, 0.50, 0.17, 0.050, 0.009),
    )
    outline = QPen(QColor(palette.ink), max(0.0, size / 64))
    for index, (color, bottom, height, half_width, lean) in enumerate(layers):
        painter.setPen(outline if index == 0 and size >= 48 else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawPath(
            _flame(size * 0.50, size * bottom, size * height, size * half_width, size * lean)
        )


def render(size: int) -> QImage:
    """One icon image: a lit torch (the game's iconic light meter) on a dark gold-rimmed tile."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_background(painter, size)
    _draw_handle(painter, size)
    _draw_flame(painter, size)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QImageWriter(buffer, QByteArray(b"PNG"))
    if not writer.write(image):
        raise RuntimeError(f"Qt could not encode the icon as PNG: {writer.errorString()}")
    data: QByteArray = buffer.data()
    return bytes(data.data())


def build_ico(images: list[QImage]) -> bytes:
    """An ICO container: ICONDIR, one ICONDIRENTRY per image, then the PNG payloads."""
    payloads = [png_bytes(image) for image in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for image, payload in zip(images, payloads, strict=True):
        side = image.width() % 256  # 256 is stored as 0
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(payload), offset)
        offset += len(payload)
    return header + entries + b"".join(payloads)


def main() -> int:
    # Draws into QImages only (no window), but needs the platform's real font database: the
    # "offscreen" plugin has no usable fonts on Windows and would render the monogram as boxes.
    app = QGuiApplication(sys.argv[:1])
    TARGET.write_bytes(build_ico([render(size) for size in SIZES]))
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes, sizes {SIZES})")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
