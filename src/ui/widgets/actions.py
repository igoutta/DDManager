"""Action specs, the action factory and the recolouring SVG icon set."""

from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from typing import Final

from PySide6.QtCore import QByteArray, QObject, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QStyle

from src.ui.theme.tokens import ThemeTokens

type Tr = Callable[..., str]
type KeyLike = QKeySequence | QKeySequence.StandardKey | str

_ICON_PX: Final = 64
_FALLBACKS: Final = {
    "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "error": QStyle.StandardPixmap.SP_MessageBoxCritical,
    "info": QStyle.StandardPixmap.SP_MessageBoxInformation,
    "folder": QStyle.StandardPixmap.SP_DirIcon,
}


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """Everything needed to build one QAction; texts come from ``ui.action.<key>[.tip]``."""

    key: str
    icon: str
    slot: Callable[[], None]
    shortcuts: tuple[KeyLike, ...] = ()
    context: Qt.ShortcutContext = Qt.ShortcutContext.WindowShortcut
    danger: bool = False
    checkable: bool = False


class IconSet:
    """Loads ``src/resources/icons/*.svg``, recolours ``currentColor`` and caches the QIcons."""

    def __init__(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self._cache: dict[tuple[str, str], QIcon] = {}

    def color(self, tone: str) -> str:
        return str(getattr(self._tokens.palette, tone, self._tokens.palette.text))

    @staticmethod
    def _source(name: str) -> str | None:
        path = resources.files("src") / "resources" / "icons" / f"{name}.svg"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    @staticmethod
    def _pixmap(svg: str, color: str) -> QPixmap:
        renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode("utf-8")))
        pixmap = QPixmap(_ICON_PX, _ICON_PX)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap

    def get(self, name: str, tone: str = "text") -> QIcon:
        """The icon ``name`` in palette color ``tone``; a style icon when the SVG is missing."""
        key = (name, tone)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        svg = self._source(name)
        icon = QIcon()
        if svg is None:
            style = QApplication.style()
            fallback = _FALLBACKS.get(name, QStyle.StandardPixmap.SP_FileIcon)
            icon = style.standardIcon(fallback) if style is not None else QIcon()
        else:
            icon.addPixmap(self._pixmap(svg, self.color(tone)), QIcon.Mode.Normal)
            icon.addPixmap(self._pixmap(svg, self.color("disabled")), QIcon.Mode.Disabled)
        self._cache[key] = icon
        return icon


def shortcut_text(action: QAction) -> str:
    """The native text of the action's shortcuts, e.g. ``F5`` or ``Ctrl+Shift+A, Ctrl+Z``."""
    return ", ".join(
        seq.toString(QKeySequence.SequenceFormat.NativeText) for seq in action.shortcuts()
    )


def retranslate_action(action: QAction, tr: Tr) -> None:
    """Text, tooltip (with the shortcut) and status tip from the catalog."""
    key = str(action.property("ddm_key"))
    tip = tr(f"ui.action.{key}.tip")
    keys = shortcut_text(action)
    action.setText(tr(f"ui.action.{key}"))
    action.setToolTip(f"{tip} ({keys})" if keys else tip)
    action.setStatusTip(tip)


def make_action(spec: ActionSpec, parent: QObject, tr: Tr, icons: IconSet) -> QAction:
    action = QAction(icons.get(spec.icon, "amber" if spec.danger else "text"), "", parent)
    action.setObjectName(f"act_{spec.key}")
    action.setProperty("ddm_key", spec.key)
    action.setCheckable(spec.checkable)
    action.setShortcuts(
        [k if isinstance(k, QKeySequence) else QKeySequence(k) for k in spec.shortcuts]
    )
    action.setShortcutContext(spec.context)
    action.setProperty("danger", spec.danger)
    action.triggered.connect(lambda _checked=False: spec.slot())
    retranslate_action(action, tr)
    return action
