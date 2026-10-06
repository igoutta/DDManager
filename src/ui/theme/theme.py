"""Applying the theme: Fusion + a complete QPalette + the rendered stylesheet."""

from importlib import resources
from string import Template

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from src.ui.theme.tokens import ThemeTokens


def render_qss(tokens: ThemeTokens) -> str:
    """Fill ``dark.qss`` from ``tokens``; an unknown placeholder raises ``KeyError``."""
    source = (resources.files("src.ui.theme") / "dark.qss").read_text(encoding="utf-8")
    return Template(source).substitute(tokens.mapping())


def _palette_roles(tokens: ThemeTokens) -> dict[QPalette.ColorRole, str]:
    p = tokens.palette
    cr = QPalette.ColorRole
    return {
        cr.Window: p.bg,
        cr.WindowText: p.text,
        cr.Base: p.field,
        cr.AlternateBase: p.field_alt,
        cr.Text: p.text,
        cr.Button: p.panel,
        cr.ButtonText: p.text,
        cr.BrightText: p.text_bright,
        cr.Highlight: p.select,
        cr.HighlightedText: p.select_text,
        cr.ToolTipBase: p.panel_deep,
        cr.ToolTipText: p.text_bright,
        cr.PlaceholderText: p.muted,
        cr.Link: p.gold,
        cr.LinkVisited: p.muted,
        cr.Light: p.border,
        cr.Midlight: p.panel,
        cr.Mid: p.border,
        cr.Dark: p.panel_deep,
        cr.Shadow: p.ink,
    }


def build_palette(tokens: ThemeTokens) -> QPalette:
    """A palette that sets every role, including the Disabled group."""
    palette = QPalette()
    for role, color in _palette_roles(tokens).items():
        palette.setColor(role, QColor(color))
    disabled = QPalette.ColorGroup.Disabled
    muted = QColor(tokens.palette.disabled)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(disabled, role, muted)
    palette.setColor(disabled, QPalette.ColorRole.Highlight, QColor(tokens.palette.panel))
    palette.setColor(disabled, QPalette.ColorRole.HighlightedText, muted)
    return palette


def make_font(families: tuple[str, ...], points: float, *, bold: bool = False) -> QFont:
    font = QFont()
    font.setFamilies(list(families))
    font.setPointSizeF(points)
    font.setBold(bold)
    return font


def apply_theme(app: QApplication, tokens: ThemeTokens) -> None:
    app.setStyle("Fusion")
    app.setPalette(build_palette(tokens))
    app.setFont(make_font(tokens.typography.body_families, tokens.typography.body_pt))
    app.setStyleSheet(render_qss(tokens))


def set_property(widget: QWidget, name: str, value: object) -> None:
    """Set a dynamic property that the stylesheet selects on, then re-polish the widget."""
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_role(widget: QWidget, role: str) -> None:
    """Set ``role="<role>"`` (primary, heading, muted, ...) and re-polish."""
    set_property(widget, "role", role)
