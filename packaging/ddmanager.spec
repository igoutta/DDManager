# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DD Manager (Darkest Dungeon 1 mod manager).

Build with ``packaging/build.ps1`` (or ``just build``). Produces ``dist/DD Manager/`` with
``DD Manager.exe`` + ``_internal/`` - the same layout as the v0.2.x releases, so users can
extract a new zip over their existing portable folder and keep ``DD Manager Data``.

Qt is trimmed to what a widgets app needs; ``DD Manager.exe --self-test`` verifies the
result (image formats, platform plugin, resources, built-in plugins) before zipping.
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - injected by PyInstaller
RESOURCES = ROOT / "src" / "resources"
ICON = ROOT / "packaging" / "ddmanager.ico"
VERSION_FILE = ROOT / "build" / "version_info.txt"

# Qt plugin folders we keep (everything else under PySide6/plugins is dropped).
KEEP_PLUGIN_DIRS = {"platforms", "imageformats", "iconengines", "styles"}
KEEP_PLATFORMS = {"qwindows"}
KEEP_IMAGEFORMATS = {"qjpeg", "qgif", "qico", "qsvg", "qwebp"}
KEEP_TRANSLATIONS = {"qtbase_zh_CN", "qtbase_zh_TW", "qtbase_pt_BR", "qtbase_pt_PT", "qtbase_es", "qtbase_en"}
DROP_DLL_PREFIXES = (
    "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6Network", "Qt6OpenGL",
    "Qt6Multimedia", "Qt6WebEngine", "Qt6Designer", "Qt6Charts", "Qt63D", "Qt6Positioning",
    "Qt6Sql", "Qt6Test", "Qt6Xml", "Qt6Concurrent", "Qt6Help", "Qt6Bluetooth", "Qt6Nfc",
    "Qt6RemoteObjects", "Qt6Scxml", "Qt6Sensors", "Qt6SerialPort", "Qt6WebSockets",
    "Qt6WebChannel", "Qt6UiTools", "Qt6PrintSupport", "Qt6DBus",
)
DROP_FILES = {"opengl32sw.dll", "d3dcompiler_47.dll"}


def _keep(entry):
    dest = entry[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1]
    stem = name.split(".", 1)[0]
    if name in DROP_FILES or stem.startswith(DROP_DLL_PREFIXES):
        return False
    if "/plugins/" in dest:
        parts = dest.split("/plugins/", 1)[1].split("/")
        folder = parts[0]
        if folder not in KEEP_PLUGIN_DIRS:
            return False
        if folder == "platforms" and stem not in KEEP_PLATFORMS:
            return False
        if folder == "imageformats" and stem not in KEEP_IMAGEFORMATS:
            return False
    if "/translations/" in dest:
        return stem in KEEP_TRANSLATIONS
    return True


a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(RESOURCES), "src/resources")],
    hiddenimports=[],  # built-in plugins/rules/formats are imported statically by the package
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "_tkinter",
        "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtMultimedia",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtCharts", "PySide6.QtDesigner", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtPrintSupport", "PySide6.QtDBus",
    ],
    noarchive=False,
    optimize=1,
)
a.binaries = TOC([e for e in a.binaries if _keep(e)])  # noqa: F821
a.datas = TOC([e for e in a.datas if _keep(e)])  # noqa: F821

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DD Manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX is disabled on purpose: it triggers antivirus false positives
    console=False,
    icon=str(ICON) if ICON.is_file() else None,
    version=str(VERSION_FILE) if VERSION_FILE.is_file() else None,
    contents_directory="_internal",
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DD Manager",
)
