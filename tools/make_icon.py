"""Generate ``packaging/ddmanager.ico``: a dark square with a gold "DD" monogram.

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
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QImageWriter,
    QPainter,
    QPen,
)

from src.ui.theme.tokens import DARK_TOKENS

ROOT = Path(__file__).absolute().parent.parent
TARGET = ROOT / "packaging" / "ddmanager.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)
MONOGRAM = "DD"
TEXT_SHARE = 0.72  # the monogram spans this share of the inner width


def _fit_font(size: int, inner: float) -> QFont:
    """The heading font at the largest pixel size whose monogram fits ``inner`` px wide."""
    font = QFont()
    font.setFamilies(list(DARK_TOKENS.typography.heading_families))
    font.setBold(True)
    pixel = max(6, int(size * 0.6))
    while pixel > 6:
        font.setPixelSize(pixel)
        if QFontMetricsF(font).horizontalAdvance(MONOGRAM) <= inner * TEXT_SHARE:
            break
        pixel -= 1
    return font


def render(size: int) -> QImage:
    """One icon image: panel-colored rounded square, gold hairline border, gold monogram."""
    palette = DARK_TOKENS.palette
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    border = max(1.0, size / 24)
    body = QRectF(border / 2, border / 2, size - border, size - border)
    painter.setPen(QPen(QColor(palette.gold), border))
    painter.setBrush(QColor(palette.bg))
    painter.drawRoundedRect(body, size * 0.16, size * 0.16)
    painter.setFont(_fit_font(size, body.width()))
    painter.setPen(QColor(palette.gold))
    painter.drawText(body, Qt.AlignmentFlag.AlignCenter, MONOGRAM)
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
