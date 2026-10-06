"""Theme tokens, stylesheet rendering and application."""

import dataclasses

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QPushButton

from src.ui.theme.theme import apply_theme, render_qss, set_role
from src.ui.theme.tokens import DARK_TOKENS, DENSITY, TIER_TOKENS

LEGACY_THEME = {
    "bg": "#14100F",
    "panel": "#211A18",
    "panel_deep": "#100D0C",
    "field": "#181210",
    "field_alt": "#1D1714",
    "border": "#3A2A24",
    "text": "#D8C7A3",
    "text_bright": "#E7D8B0",
    "muted": "#9D8E77",
    "gold": "#B99A45",
    "crimson": "#8F1D1D",
    "crimson_hover": "#A72A24",
    "amber": "#B56A24",
    "amber_hover": "#C47A30",
    "disabled": "#746A60",
    "select": "#5A2623",
    "select_text": "#F3E7C6",
    "ink": "#050505",
}
TIERS = (
    "overhaul",
    "ui",
    "district",
    "dungeon",
    "quirk",
    "item",
    "enemy",
    "class_patch",
    "class",
    "skin",
    "patch",
    "unassigned",
)


def luminance(color: str) -> float:
    c = QColor(color)
    channels = [
        v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        for v in (c.redF(), c.greenF(), c.blueF())
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_palette_keeps_the_verbatim_legacy_colors():
    palette = DARK_TOKENS.palette
    for name, value in LEGACY_THEME.items():
        assert getattr(palette, name).upper() == value, name
    for extra in ("error", "warning", "info", "ok"):
        assert QColor(getattr(palette, extra)).isValid()


def test_render_qss_is_complete():
    qss = render_qss(DARK_TOKENS)
    assert qss.strip()
    assert "${" not in qss
    assert "$" not in qss.replace("$$", "")
    assert DARK_TOKENS.palette.bg in qss


def test_render_qss_raises_on_a_missing_token():
    with pytest.raises((KeyError, ValueError, AttributeError, TypeError)):
        render_qss(None)  # ty: ignore[invalid-argument-type]


def test_every_known_tier_has_a_token_and_contrasts_with_panel_and_field():
    palette = DARK_TOKENS.palette
    for tier in TIERS:
        assert tier in TIER_TOKENS, tier
        token = TIER_TOKENS[tier]
        assert token.badge_key
        assert contrast(token.color, palette.panel) >= 3.0, tier
        assert contrast(token.color, palette.field) >= 3.0, tier


def test_density_modes():
    assert DENSITY["No Icons"] == (0, 24)
    assert DENSITY["Compact"] == (28, 32)
    assert DENSITY["Comfortable"] == (40, 46)
    assert DENSITY["Visual"] == (52, 60)


@pytest.fixture
def restore_app(qapp):
    style, palette, font, sheet = (
        qapp.style().name(),
        qapp.palette(),
        qapp.font(),
        qapp.styleSheet(),
    )
    yield qapp
    QApplication.setStyle(style)
    qapp.setPalette(palette)
    qapp.setFont(font)
    qapp.setStyleSheet(sheet)


def test_apply_theme_sets_fusion_palette_and_stylesheet(restore_app):
    apply_theme(restore_app, DARK_TOKENS)
    palette = restore_app.palette()
    assert palette.color(QPalette.ColorRole.Window).name().upper() == LEGACY_THEME["bg"]
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        assert (
            palette.color(QPalette.ColorGroup.Disabled, role).name().upper()
            == LEGACY_THEME["disabled"]
        )
    assert restore_app.styleSheet().strip()
    restore_app.setStyleSheet("")  # an active stylesheet wraps the style; look at the real one
    assert restore_app.style().name().lower() == "fusion"


def test_stylesheet_parses_without_qt_warnings(restore_app, qtbot, qtlog):
    apply_theme(restore_app, DARK_TOKENS)
    button = QPushButton("probe")
    qtbot.addWidget(button)
    set_role(button, "danger")
    button.show()
    qtbot.waitExposed(button)
    bad = [
        r
        for r in qtlog.records
        if "stylesheet" in r.message.lower() or "parse" in r.message.lower()
    ]
    assert not bad, [r.message for r in bad]


def test_set_role_sets_a_dynamic_property_and_repolishes(qtbot):
    button = QPushButton("x")
    qtbot.addWidget(button)
    set_role(button, "danger")
    assert "danger" in {
        str(button.property(bytes(n.data()).decode())) for n in button.dynamicPropertyNames()
    }


def test_tokens_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        DARK_TOKENS.palette.bg = "#000000"  # ty: ignore[invalid-assignment]
