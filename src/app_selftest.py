"""``--self-test``: prove the installation (or the frozen build) can run the GUI."""

import json
import os
import sys
from importlib import resources
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImageReader

from src.core.saves import DEFAULT_SAVE_FORMATS
from src.plugins import BUILTIN_SOURCES
from src.rules import BUILTIN_RULES
from src.services.app_paths import AppPaths
from src.ui.theme.theme import render_qss
from src.ui.theme.tokens import DARK_TOKENS

REQUIRED_IMAGE_FORMATS = (b"jpeg", b"gif", b"png", b"svg")
REQUIRED_RESOURCES = (
    ("i18n", "en.json"),
    ("i18n", "es_ES.json"),
    ("i18n", "pt_PT.json"),
    ("i18n", "zh_CN.json"),
    ("default_rules.json", ""),
    ("icons", "rescan.svg"),
)


def _resource_path(*parts: str) -> Path | None:
    node = resources.files("src") / "resources"
    for part in parts:
        if part:
            node = node / part
    return Path(str(node)) if node.is_file() else None


def check_image_formats() -> list[str]:
    available = {bytes(fmt.data()).lower() for fmt in QImageReader.supportedImageFormats()}
    return [
        f"image format {fmt.decode()} is not supported"
        for fmt in REQUIRED_IMAGE_FORMATS
        if fmt not in available
    ]


def check_platform() -> list[str]:
    name = QGuiApplication.platformName()
    return [] if name else ["no Qt platform plugin is loaded"]


def check_resources() -> list[str]:
    problems = [
        f"resource {'/'.join(p for p in parts if p)} is missing"
        for parts in REQUIRED_RESOURCES
        if _resource_path(*parts) is None
    ]
    catalog = _resource_path("i18n", "en.json")
    if catalog is not None:
        try:
            json.loads(catalog.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"en.json is unreadable: {exc}")
    try:
        render_qss(DARK_TOKENS)
    except (KeyError, ValueError, OSError) as exc:
        problems.append(f"the stylesheet cannot be rendered: {exc}")
    return problems


def check_registrations() -> list[str]:
    checks = (
        ("mod sources", BUILTIN_SOURCES),
        ("rules", BUILTIN_RULES),
        ("save formats", DEFAULT_SAVE_FORMATS),
    )
    return [f"no built-in {name} are registered" for name, items in checks if not items]


def run_self_test(paths: AppPaths) -> int:
    """Print the facts, then ``0`` when every check passes and ``1`` otherwise."""
    problems = [
        *check_image_formats(),
        *check_platform(),
        *check_resources(),
        *check_registrations(),
    ]
    lines = [
        f"data dir: {paths.data_dir} (mode {paths.mode.value}: {paths.reason})",
        f"platform: {QGuiApplication.platformName()}",
        *(f"FAIL: {problem}" for problem in problems),
        "self-test: " + ("FAILED" if problems else "ok"),
    ]
    sys.stdout.write(os.linesep.join(lines) + os.linesep)
    return 1 if problems else 0
