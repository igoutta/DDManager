"""Generate ``packaging/ddmanager.ico``: a heraldic torch in gold engraving with a gear mark.

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
# the palette's gold line-work on the dark tile, in the spirit of illuminated emblems.
EMBER = "#C8552A"
EMBER_LIGHT = "#E8A54A"
GEAR_TEETH = 8
TORCH_X = 0.43  # the torch sits left of centre to leave room for the gear
GEAR_AT = (0.775, 0.775)
GEAR_RADIUS = 0.16

# Heraldic flame: (dx, bottom, height, half width, lean) in unit coordinates, back to front.
TONGUES = (
    (-0.150, 0.49, 0.18, 0.050, -0.050),
    (0.155, 0.49, 0.21, 0.050, 0.050),
    (-0.075, 0.49, 0.31, 0.080, -0.055),
    (0.085, 0.49, 0.34, 0.080, 0.060),
    (0.000, 0.49, 0.45, 0.110, 0.015),
)


def _flame(cx: float, bottom: float, height: float, half_width: float, lean: float) -> QPainterPath:
    """A pointed tongue: wide at ``bottom``, tip ``height`` above it, leaning ``lean`` sideways."""
    top = bottom - height
    path = QPainterPath()
    path.moveTo(cx, bottom)
    path.cubicTo(
        cx - half_width * 1.45,
        bottom - height * 0.22,
        cx - half_width * 0.95 + lean * 0.4,
        bottom - height * 0.78,
        cx + lean,
        top,
    )
    path.cubicTo(
        cx + half_width * 1.05 + lean * 0.4,
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
    glow = QRadialGradient(size * TORCH_X, size * 0.34, size * 0.42)
    halo = QColor(EMBER)
    halo.setAlpha(70)
    glow.setColorAt(0.0, halo)
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawRoundedRect(body, size * 0.16, size * 0.16)


def _draw_shaft(painter: QPainter, size: int) -> None:
    """A turned shaft: tapered stem, a knop half-way down and a flared foot."""
    palette = DARK_TOKENS.palette
    cx = size * TORCH_X
    painter.setPen(_line_pen(size))
    painter.setBrush(QColor(palette.panel))
    stem = QPainterPath()
    stem.moveTo(cx - size * 0.040, size * 0.62)
    stem.lineTo(cx + size * 0.040, size * 0.62)
    stem.lineTo(cx + size * 0.028, size * 0.90)
    stem.lineTo(cx - size * 0.028, size * 0.90)
    stem.closeSubpath()
    painter.drawPath(stem)
    foot = QPainterPath()
    foot.moveTo(cx - size * 0.028, size * 0.88)
    foot.lineTo(cx + size * 0.028, size * 0.88)
    foot.lineTo(cx + size * 0.075, size * 0.94)
    foot.lineTo(cx - size * 0.075, size * 0.94)
    foot.closeSubpath()
    painter.drawPath(foot)
    knop = QRectF(cx - size * 0.065, size * 0.715, size * 0.13, size * 0.075)
    painter.drawEllipse(knop)
    if size >= 32:
        painter.drawLine(
            QPointF(cx - size * 0.038, size * 0.655), QPointF(cx + size * 0.038, size * 0.655)
        )
        painter.drawLine(
            QPointF(cx - size * 0.031, size * 0.835), QPointF(cx + size * 0.031, size * 0.835)
        )


def _draw_cup(painter: QPainter, size: int) -> None:
    """A fluted chalice-shaped socket with a scalloped rim."""
    palette = DARK_TOKENS.palette
    cx = size * TORCH_X
    painter.setPen(_line_pen(size))
    painter.setBrush(QColor(palette.panel))
    cup = QPainterPath()
    cup.moveTo(cx - size * 0.150, size * 0.49)
    cup.lineTo(cx + size * 0.150, size * 0.49)
    cup.cubicTo(
        cx + size * 0.150,
        size * 0.57,
        cx + size * 0.070,
        size * 0.58,
        cx + size * 0.045,
        size * 0.63,
    )
    cup.lineTo(cx - size * 0.045, size * 0.63)
    cup.cubicTo(
        cx - size * 0.070,
        size * 0.58,
        cx - size * 0.150,
        size * 0.57,
        cx - size * 0.150,
        size * 0.49,
    )
    cup.closeSubpath()
    painter.drawPath(cup)
    rim = QRectF(cx - size * 0.150, size * 0.465, size * 0.30, size * 0.05)
    painter.drawRoundedRect(rim, size * 0.02, size * 0.02)
    if size >= 32:
        painter.setPen(_line_pen(size, 0.6))
        for dx in (-0.075, 0.0, 0.075):
            painter.drawLine(
                QPointF(cx + size * dx, size * 0.52), QPointF(cx + size * dx * 0.55, size * 0.605)
            )


def _draw_flame(painter: QPainter, size: int) -> None:
    """Heraldic flame: five gold-outlined tongues, dark bodies warming to ember, a bright heart."""
    palette = DARK_TOKENS.palette
    cx = size * TORCH_X
    body = QLinearGradient(0.0, size * 0.06, 0.0, size * 0.50)
    body.setColorAt(0.0, QColor(palette.ink))
    body.setColorAt(0.55, QColor(palette.crimson))
    body.setColorAt(1.0, QColor(EMBER))
    painter.setPen(_line_pen(size))
    painter.setBrush(body)
    for dx, bottom, height, half_width, lean in TONGUES:
        painter.drawPath(
            _flame(cx + size * dx, size * bottom, size * height, size * half_width, size * lean)
        )
    heart = QLinearGradient(0.0, size * 0.27, 0.0, size * 0.48)
    heart.setColorAt(0.0, QColor(palette.text_bright))
    heart.setColorAt(1.0, QColor(EMBER_LIGHT))
    painter.setPen(_line_pen(size, 0.6))
    painter.setBrush(heart)
    painter.drawPath(_flame(cx + size * 0.01, size * 0.48, size * 0.22, size * 0.055, size * 0.01))


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
    """One icon image: a heraldic torch with a gold gear mark for 'mods'."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_background(painter, size)
    _draw_shaft(painter, size)
    _draw_cup(painter, size)
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
