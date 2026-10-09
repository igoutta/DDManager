"""Generate ``packaging/ddmanager.ico``: a torch in orange and purple with a gear badge.

Run it once (``uv run python tools/make_icon.py``) and commit the result; the build only reads
the file. The tile and the wood use the app's palette tokens; the flame and the badge use an
icon-only orange/purple pair so the app is recognisable next to the game's own red/gold look.
The ``.ico`` holds PNG-compressed images at every size Windows asks for (16 px taskbar/title
bar up to the 256 px Explorer view).
"""

import math
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
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
BUNDLED = ROOT / "src" / "resources" / "icons" / "app.ico"  # window/taskbar icon at run time
SIZES = (16, 24, 32, 48, 64, 128, 256)

# Icon-only accents (the palette has no purple): the flame runs purple -> orange -> bright,
# the badge is purple with an orange gear.
PURPLE_DEEP = "#4A2466"
PURPLE = "#7B3FA6"
PURPLE_LIGHT = "#A86BD6"
ORANGE_DEEP = "#C8552A"
ORANGE = "#E8923A"
ORANGE_LIGHT = "#F5C25C"
FLAME_CORE = "#FBEFD2"

# Flame tongues: (color, bottom, height, half width, lean) in unit coordinates.
FLAME_LAYERS = (
    (PURPLE_DEEP, 0.51, 0.50, 0.225, 0.045),
    (ORANGE_DEEP, 0.51, 0.40, 0.160, 0.034),
    (ORANGE, 0.51, 0.29, 0.100, 0.020),
    (FLAME_CORE, 0.50, 0.17, 0.050, 0.009),
)
GEAR_TEETH = 8
TORCH_X = 0.44  # the torch sits left of centre to leave room for the badge


def _flame(cx: float, bottom: float, height: float, half_width: float, lean: float) -> QPainterPath:
    """A teardrop tongue: wide at ``bottom``, tip ``height`` above it, leaning ``lean`` right."""
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


def _gear(center: QPointF, outer: float, inner: float, hole: float) -> QPainterPath:
    """A cog with ``GEAR_TEETH`` teeth and a round hole (odd-even fill)."""
    path = QPainterPath()
    steps = GEAR_TEETH * 4
    for i in range(steps):
        angle = 2 * math.pi * i / steps
        radius = outer if (i % 4) in (0, 1) else inner
        point = QPointF(
            center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle)
        )
        if i == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    path.addEllipse(center, hole, hole)
    path.setFillRule(Qt.FillRule.OddEvenFill)
    return path


def _draw_background(painter: QPainter, size: int) -> None:
    """Dark rounded square with a gold hairline and a purple glow behind the flame."""
    palette = DARK_TOKENS.palette
    border = max(1.0, size / 24)
    body = QRectF(border / 2, border / 2, size - border, size - border)
    painter.setPen(QPen(QColor(palette.gold), border))
    painter.setBrush(QColor(palette.ink))
    painter.drawRoundedRect(body, size * 0.16, size * 0.16)
    glow = QRadialGradient(size * TORCH_X, size * 0.36, size * 0.46)
    halo = QColor(PURPLE)
    halo.setAlpha(120)
    glow.setColorAt(0.0, halo)
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawRoundedRect(body, size * 0.16, size * 0.16)


def _draw_handle(painter: QPainter, size: int) -> None:
    """A tapered wooden shaft with a cloth wrap under the flame."""
    palette = DARK_TOKENS.palette
    cx = size * TORCH_X
    shaft = QPainterPath()
    shaft.moveTo(cx - size * 0.06, size * 0.56)
    shaft.lineTo(cx + size * 0.06, size * 0.56)
    shaft.lineTo(cx + size * 0.035, size * 0.92)
    shaft.lineTo(cx - size * 0.035, size * 0.92)
    shaft.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(palette.border))
    painter.drawPath(shaft)
    painter.setBrush(QColor(palette.amber))
    painter.drawRect(QRectF(cx - size * 0.025, size * 0.58, size * 0.02, size * 0.32))
    wrap = QRectF(cx - size * 0.13, size * 0.50, size * 0.26, size * 0.10)
    painter.setBrush(QColor(ORANGE_DEEP))
    painter.drawRoundedRect(wrap, size * 0.03, size * 0.03)
    painter.setBrush(QColor(ORANGE_LIGHT))
    painter.drawRect(QRectF(cx - size * 0.13, size * 0.535, size * 0.26, size * 0.018))


def _draw_flame(painter: QPainter, size: int) -> None:
    """Four nested tongues from deep purple to the bright core."""
    cx = size * TORCH_X
    outline = QPen(QColor(DARK_TOKENS.palette.ink), max(0.0, size / 64))
    for index, (color, bottom, height, half_width, lean) in enumerate(FLAME_LAYERS):
        painter.setPen(outline if index == 0 and size >= 48 else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawPath(_flame(cx, size * bottom, size * height, size * half_width, size * lean))


def _draw_badge(painter: QPainter, size: int) -> None:
    """Bottom-right 'mod' badge: a purple disc with an orange gear and a dark rim."""
    center = QPointF(size * 0.735, size * 0.735)
    radius = size * 0.20
    rim = max(1.0, size / 40)
    painter.setPen(QPen(QColor(DARK_TOKENS.palette.ink), rim))
    painter.setBrush(QColor(PURPLE_DEEP))
    painter.drawEllipse(center, radius, radius)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(PURPLE_LIGHT))
    painter.drawEllipse(center, radius * 0.86, radius * 0.86)
    painter.setBrush(QColor(ORANGE))
    painter.drawPath(_gear(center, radius * 0.70, radius * 0.50, radius * 0.22))
    if size >= 32:
        painter.setBrush(QColor(ORANGE_LIGHT))
        painter.drawEllipse(center, radius * 0.30, radius * 0.30)
        painter.setBrush(QColor(PURPLE_LIGHT))
        painter.drawEllipse(center, radius * 0.19, radius * 0.19)


def render(size: int) -> QImage:
    """One icon image: the game's torch, recoloured, with a gear badge for 'mods'."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_background(painter, size)
    _draw_handle(painter, size)
    _draw_flame(painter, size)
    _draw_badge(painter, size)
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
    # Draws into QImages only (no window); a real platform plugin keeps font/metric behaviour
    # identical to the running app, so do not force the "offscreen" platform here.
    app = QGuiApplication(sys.argv[:1])
    data = build_ico([render(size) for size in SIZES])
    for target in (TARGET, BUNDLED):
        target.write_bytes(data)
        print(f"wrote {target} ({len(data)} bytes, sizes {SIZES})")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
