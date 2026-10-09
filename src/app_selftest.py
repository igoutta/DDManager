"""``--self-test``: prove the installation (or the frozen build) can run the GUI.

Every check returns a list of problems; none raises. The frozen build runs this before the
release zip is made, so each check targets something PyInstaller (or its pruning in
``packaging/ddmanager.spec``) can silently drop: Qt image/icon plugins, the platform plugin,
Qt translations, the package data files and the modules reached only through importlib.
"""

import dataclasses
import json
import sys
from collections.abc import Callable
from importlib import import_module, resources
from importlib.resources.abc import Traversable
from pathlib import Path

from PySide6.QtCore import QByteArray, QLibraryInfo, QTranslator
from PySide6.QtGui import QGuiApplication, QIcon, QImageReader
from PySide6.QtSvg import QSvgRenderer

import src
from src.core.findings import Severity
from src.core.saves import DEFAULT_SAVE_FORMATS
from src.plugins import BUILTIN_SOURCES
from src.rules import BUILTIN_RULES
from src.services.app_paths import ENV_OVERRIDE, AppPaths, DataDirMode, resolve_app_paths
from src.services.environment import Environment
from src.services.rules_repo import load_bundled_rules
from src.ui.i18n import DEFAULT_LANGUAGE, available_languages
from src.ui.theme.theme import render_qss
from src.ui.theme.tokens import DARK_TOKENS

type Check = Callable[[], list[str]]

REQUIRED_IMAGE_FORMATS = (b"jpeg", b"gif", b"png", b"svg", b"ico", b"webp")
REQUIRED_LANGUAGES = (DEFAULT_LANGUAGE, "es_ES", "pt_PT", "zh_CN")
# Qt ships no qtbase_pt_PT, so the closest catalog Portuguese can get is pt_BR.
TRANSLATION_PROBES = ("qtbase_es_ES", "qtbase_zh_CN", "qtbase_pt_BR")
REQUIRED_PLUGINS = (("iconengines", "qsvgicon"), ("imageformats", "qsvg"))
REQUIRED_ICONS = ("rescan.svg", "patch.svg", "up.svg", "down.svg")  # sentinels


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resource_root() -> Traversable:
    # src/resources has no __init__.py, so it is reached through the ``src`` package.
    return resources.files("src") / "resources"


def _qt_plugin_present(folder: str, stem: str) -> bool:
    directory = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / folder
    return any(directory.glob(f"*{stem}.*"))  # qsvg.dll on Windows, libqsvg.so elsewhere


def check_image_formats() -> list[str]:
    available = {bytes(fmt.data()).lower() for fmt in QImageReader.supportedImageFormats()}
    return [
        f"image format {fmt.decode()} is not supported"
        for fmt in REQUIRED_IMAGE_FORMATS
        if fmt not in available
    ]


def check_platform() -> list[str]:
    name = QGuiApplication.platformName()
    if not name:
        return ["no Qt platform plugin is loaded"]
    if not _qt_plugin_present("platforms", f"q{name}"):
        return [f"the Qt {name} platform plugin file is missing from the plugins folder"]
    return []


def check_qt_plugins() -> list[str]:
    return [
        f"Qt plugin {folder}/{stem} is missing"
        for folder, stem in REQUIRED_PLUGINS
        if not _qt_plugin_present(folder, stem)
    ]


def check_translations() -> list[str]:
    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    return [
        f"Qt translation {name} cannot be loaded from {directory}"
        for name in TRANSLATION_PROBES
        if not QTranslator().load(name, directory)
    ]


def _catalog_keys(code: str) -> set[str]:
    text = (_resource_root() / "i18n" / f"{code}.json").read_text(encoding="utf-8")
    return set(json.loads(text))


def check_catalogs() -> list[str]:
    found = available_languages()
    missing = [code for code in REQUIRED_LANGUAGES if code not in found]
    if missing:
        return [f"i18n catalogs are missing: {', '.join(missing)}"]
    try:
        keys = {code: _catalog_keys(code) for code in REQUIRED_LANGUAGES}
    except (OSError, ValueError, TypeError) as exc:
        return [f"an i18n catalog is unreadable: {exc}"]
    reference = keys[DEFAULT_LANGUAGE]
    problems = [] if reference else ["the i18n catalogs are empty"]
    problems += [
        f"i18n catalog {code} differs from {DEFAULT_LANGUAGE} by {len(names ^ reference)} keys"
        for code, names in keys.items()
        if names != reference
    ]
    return problems


def check_default_rules() -> list[str]:
    rules, findings = load_bundled_rules()
    problems = [
        f"default_rules.json: {f.message}" for f in findings if f.severity >= Severity.ERROR
    ]
    if not (rules.mods or rules.overlap_ignore or rules.overlap_merge):
        problems.append("default_rules.json parsed to an empty document")
    return problems


def check_stylesheet() -> list[str]:
    try:
        rendered = render_qss(DARK_TOKENS)
    except (KeyError, ValueError, OSError) as exc:
        return [f"the stylesheet cannot be rendered: {exc}"]
    return [] if rendered.strip() else ["the rendered stylesheet is empty"]


def check_icons() -> list[str]:
    icons = [item for item in (_resource_root() / "icons").iterdir() if item.name.endswith(".svg")]
    present = {item.name for item in icons}
    problems = [f"icon {name} is not bundled" for name in REQUIRED_ICONS if name not in present]
    problems += [
        f"icon {item.name} cannot be rendered"
        for item in icons
        if not QSvgRenderer(QByteArray(item.read_bytes())).isValid()
    ]
    app_icon = _resource_root() / "icons" / "app.ico"
    if not app_icon.is_file():
        problems.append("icon app.ico is not bundled")
    elif QIcon(str(app_icon)).isNull():
        problems.append("icon app.ico cannot be loaded")
    return problems


def check_registrations() -> list[str]:
    checks = (
        ("mod sources", BUILTIN_SOURCES),
        ("rules", BUILTIN_RULES),
        ("save formats", DEFAULT_SAVE_FORMATS),
    )
    return [f"no built-in {name} are registered" for name, items in checks if not items]


def check_registry_module() -> list[str]:
    """``winreg`` is only reached through ``importlib.import_module``; PyInstaller cannot see it."""
    if sys.platform != "win32":
        return []
    try:
        import_module("winreg")
    except ImportError:
        return ["the winreg module is not bundled"]
    return []


def portable_paths() -> AppPaths:
    """Where the data would live with no ``--data-dir`` and no ``DDMANAGER_DATA_DIR``.

    Writability is assumed so the probe never touches the disk; it only exercises the
    resolution rules (beside the executable when frozen, at the repo root otherwise).
    """
    host = Environment.from_host()
    clean = {k: v for k, v in host.env.items() if k.casefold() != ENV_OVERRIDE.casefold()}
    return resolve_app_paths(
        frozen=is_frozen(),
        executable=Path(sys.executable),
        package_init=Path(src.__file__),
        env=dataclasses.replace(host, env=clean),
        is_writable=lambda _directory: True,
    )


def check_portable_paths() -> list[str]:
    if not is_frozen():
        return []
    paths = portable_paths()
    beside = Path(sys.executable).absolute().parent
    if paths.mode is DataDirMode.PORTABLE_FROZEN and paths.anchor == beside:
        return []
    return [f"the frozen data dir is {paths.data_dir} ({paths.mode.value}), not beside {beside}"]


CHECKS: dict[str, Check] = {
    check.__name__: check
    for check in (
        check_image_formats,
        check_platform,
        check_qt_plugins,
        check_translations,
        check_catalogs,
        check_default_rules,
        check_stylesheet,
        check_icons,
        check_registrations,
        check_registry_module,
        check_portable_paths,
    )
}


def _run(name: str, check: Check) -> list[str]:
    try:
        return check()
    except Exception as exc:  # noqa: BLE001 - a self-test reports every failure, it never crashes
        return [f"{name} raised {type(exc).__name__}: {exc}"]


def describe(paths: AppPaths) -> list[str]:
    """The facts printed above the verdict (real data dir, portable probe, platform, Qt paths)."""
    portable = portable_paths()
    return [
        f"data dir: {paths.data_dir} (mode {paths.mode.value}: {paths.reason})",
        f"portable data dir: {portable.data_dir} (mode {portable.mode.value}: {portable.reason})",
        f"frozen: {'yes' if is_frozen() else 'no'} ({sys.executable})",
        f"platform: {QGuiApplication.platformName()}",
        f"qt plugins: {QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)}",
        f"qt translations: {QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)}",
    ]


def run_self_test(paths: AppPaths) -> int:
    """Print the facts, then ``0`` when every check passes and ``1`` otherwise."""
    problems = [problem for name, check in CHECKS.items() for problem in _run(name, check)]
    lines = [
        *describe(paths),
        *(f"FAIL: {problem}" for problem in problems),
        "self-test: " + ("FAILED" if problems else "ok"),
    ]
    if sys.stdout is not None:  # a frozen windowed exe started without a console has none
        sys.stdout.write("\n".join(lines) + "\n")
    return 1 if problems else 0
