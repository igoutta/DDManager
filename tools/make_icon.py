"""Generate ``packaging/ddmanager.ico``: an engraved-style torch with a gold gear mark.

Run it once (``uv run python tools/make_icon.py``) and commit the result; the build only reads
the file. The tile, the line-work and the gear use the app's palette tokens; the flame's heart
uses a restrained ember pair. The ``.ico`` holds PNG-compressed images at every size Windows
asks for (16 px taskbar/title bar up to the 256 px Explorer view).
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
    QLinearGradient,
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

# Icon-only accents: a restrained ember pair for the heart of the flame. Everything else is
# the palette's gold line-work on the dark tile, in the spirit of the game's engraved UI.
EMBER = "#C8552A"
EMBER_LIGHT = "#E8A54A"
GEAR_TEETH = 8
TORCH_X = 0.44  # the torch sits left of centre to leave room for the gear
GEAR_AT = (0.765, 0.765)
GEAR_RADIUS = 0.17


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


def _line_pen(size: int, weight: float = 1.0) -> QPen:
    """The engraving stroke: gold, rounded, scaled with the icon."""
    pen = QPen(QColor(DARK_TOKENS.palette.gold), max(1.0, size / 48 * weight))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw_background(painter: QPainter, size: int) -> None:
    """Dark rounded square with a gold hairline and a faint warm glow behind the flame."""
    palette = DARK_TOKENS.palette
    border = max(1.0, size / 24)
    body = QRectF(border / 2, border / 2, size - border, size - border)
    painter.setPen(QPen(QColor(palette.gold), border))
    painter.setBrush(QColor(palette.ink))
    painter.drawRoundedRect(body, size * 0.16, size * 0.16)
    glow = QRadialGradient(size * TORCH_X, size * 0.36, size * 0.42)
    halo = QColor(EMBER)
    halo.setAlpha(70)
    glow.setColorAt(0.0, halo)
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawRoundedRect(body, size * 0.16, size * 0.16)


def _shaft_width(size: int, y: float) -> float:
    """Half-width of the tapered shaft at unit height ``y`` (0.60 top .. 0.93 bottom)."""
    t = (y - 0.60) / 0.33
    return size * (0.050 - 0.020 * t)


def _draw_handle(painter: QPainter, size: int) -> None:
    """Engraved shaft: slim tapered outline, three wrap lines and a flared cup under the flame."""
    palette = DARK_TOKENS.palette
    cx = size * TORCH_X
    shaft = QPainterPath()
    shaft.moveTo(cx - _shaft_width(size, 0.60), size * 0.60)
    shaft.lineTo(cx + _shaft_width(size, 0.60), size * 0.60)
    shaft.lineTo(cx + _shaft_width(size, 0.93), size * 0.93)
    shaft.lineTo(cx - _shaft_width(size, 0.93), size * 0.93)
    shaft.closeSubpath()
    painter.setPen(_line_pen(size))
    painter.setBrush(QColor(palette.panel))
    painter.drawPath(shaft)
    if size >= 32:
        for y in (0.66, 0.70, 0.74):
            half = _shaft_width(size, y)
            painter.drawLine(QPointF(cx - half, size * y), QPointF(cx + half, size * y))
    cup = QPainterPath()
    cup.moveTo(cx - size * 0.115, size * 0.525)
    cup.lineTo(cx + size * 0.115, size * 0.525)
    cup.lineTo(cx + size * 0.070, size * 0.605)
    cup.lineTo(cx - size * 0.070, size * 0.605)
    cup.closeSubpath()
    painter.setBrush(QColor(palette.panel))
    painter.drawPath(cup)


def _draw_flame(painter: QPainter, size: int) -> None:
    """A gold-outlined flame: dark body warming to ember at the base, a bright inner tongue."""
    palette = DARK_TOKENS.palette
    cx = size * TORCH_X
    body = QLinearGradient(0.0, size * 0.10, 0.0, size * 0.54)
    body.setColorAt(0.0, QColor(palette.ink))
    body.setColorAt(0.55, QColor(palette.crimson))
    body.setColorAt(1.0, QColor(EMBER))
    painter.setPen(_line_pen(size))
    painter.setBrush(body)
    painter.drawPath(_flame(cx, size * 0.54, size * 0.46, size * 0.21, size * 0.04))
    painter.setPen(_line_pen(size, 0.7))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_flame(cx + size * 0.01, size * 0.53, size * 0.34, size * 0.135, size * 0.03))
    core = QLinearGradient(0.0, size * 0.30, 0.0, size * 0.53)
    core.setColorAt(0.0, QColor(palette.text_bright))
    core.setColorAt(1.0, QColor(EMBER_LIGHT))
    painter.setPen(_line_pen(size, 0.6))
    painter.setBrush(core)
    painter.drawPath(_flame(cx + size * 0.015, size * 0.52, size * 0.22, size * 0.07, size * 0.015))


def _draw_gear(painter: QPainter, size: int) -> None:
    """Bottom-right 'mods' mark: a plain gold cog, no disc, a dark rim to lift it off the flame."""
    palette = DARK_TOKENS.palette
    center = QPointF(size * GEAR_AT[0], size * GEAR_AT[1])
    radius = size * GEAR_RADIUS
    painter.setPen(QPen(QColor(palette.ink), max(1.0, size / 40)))
    painter.setBrush(QColor(palette.gold))
    painter.drawPath(_gear(center, radius, radius * 0.72, radius * 0.32))
    if size >= 32:
        painter.setPen(QPen(QColor(palette.ink), max(1.0, size / 96)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius * 0.52, radius * 0.52)


def render(size: int) -> QImage:
    """One icon image: an engraved torch with a gold gear mark for 'mods'."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_background(painter, size)
    _draw_handle(painter, size)
    _draw_flame(painter, size)
    _draw_gear(painter, size)
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
