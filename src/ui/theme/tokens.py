"""Design tokens: the verbatim legacy palette plus the semantic additions."""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class Palette:
    """The 18 legacy theme colors (``dd2.py:115-134``) and the new semantic ones."""

    bg: str = "#14100F"
    panel: str = "#211A18"
    panel_deep: str = "#100D0C"
    field: str = "#181210"
    field_alt: str = "#1D1714"
    border: str = "#3A2A24"
    text: str = "#D8C7A3"
    text_bright: str = "#E7D8B0"
    muted: str = "#9D8E77"
    gold: str = "#B99A45"
    crimson: str = "#8F1D1D"
    crimson_hover: str = "#A72A24"
    amber: str = "#B56A24"
    amber_hover: str = "#C47A30"
    disabled: str = "#746A60"
    select: str = "#5A2623"
    select_text: str = "#F3E7C6"
    ink: str = "#050505"
    # new semantic tokens
    error: str = "#D9534F"
    warning: str = "#D8A13A"
    info: str = "#7FA7C9"
    ok: str = "#8FB36B"


@dataclass(frozen=True, slots=True)
class TierToken:
    """A tier's color and the i18n key of its 3-letter badge (color is never the only signal)."""

    color: str
    badge_key: str


TIER_TOKENS: Final[Mapping[str, TierToken]] = MappingProxyType(
    {
        "overhaul": TierToken("#C8553D", "ui.tier.ovh"),
        "ui": TierToken("#8FA6B8", "ui.tier.ui"),
        "district": TierToken("#6D9C9A", "ui.tier.dst"),
        "dungeon": TierToken("#B88B4A", "ui.tier.dgn"),
        "quirk": TierToken("#B26B7B", "ui.tier.qrk"),
        "item": TierToken("#C1A85D", "ui.tier.itm"),
        "enemy": TierToken("#B65A4D", "ui.tier.eny"),
        "class_patch": TierToken("#879B5B", "ui.tier.cpt"),
        "class": TierToken("#A4B56C", "ui.tier.cls"),
        "skin": TierToken("#9D7A9A", "ui.tier.skn"),
        "patch": TierToken("#8C7BB0", "ui.tier.pat"),
        "unassigned": TierToken("#82786B", "ui.tier.una"),
        # user-defined categories without an override resolve to text_bright (legacy fallback)
        "custom": TierToken("#E7D8B0", "ui.tier.cus"),
    }
)
CUSTOM_PREFIX: Final = "custom:"


def tier_token(tier_id: str) -> TierToken:
    """The token for ``tier_id``; ``custom:<name>`` and unknown ids use the ``custom`` token."""
    token = TIER_TOKENS.get(tier_id)
    return token if token is not None else TIER_TOKENS["custom"]


@dataclass(frozen=True, slots=True)
class Spacing:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    radius: int = 4


@dataclass(frozen=True, slots=True)
class Typography:
    """Font families (first installed one wins) and sizes in points (``dd2.py:136-149``)."""

    heading_families: tuple[str, ...] = ("Georgia", "DejaVu Serif")
    body_families: tuple[str, ...] = ("Segoe UI", "DejaVu Sans")
    mono_families: tuple[str, ...] = ("Consolas", "DejaVu Sans Mono")
    title_pt: float = 20
    subtitle_pt: float = 10
    heading_pt: float = 12
    body_pt: float = 10
    button_pt: float = 9
    mono_pt: float = 10


DENSITY: Final[Mapping[str, tuple[int, int]]] = MappingProxyType(
    {
        "No Icons": (0, 24),
        "Compact": (28, 32),
        "Comfortable": (40, 46),
        "Visual": (52, 60),
    }
)
"""``(icon px, row px)`` keyed by the legacy ``view_mode`` names."""
DEFAULT_DENSITY: Final = "Comfortable"


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    palette: Palette = field(default_factory=Palette)
    spacing: Spacing = field(default_factory=Spacing)
    typography: Typography = field(default_factory=Typography)

    def mapping(self) -> dict[str, str]:
        """Every ``${name}`` available to the stylesheet template."""
        values: dict[str, str] = {}
        for group in (self.palette, self.spacing):
            values.update({f.name: str(getattr(group, f.name)) for f in fields(group)})
        typo = self.typography
        values["font_heading"] = ", ".join(f'"{name}"' for name in typo.heading_families)
        values["font_body"] = ", ".join(f'"{name}"' for name in typo.body_families)
        values["font_mono"] = ", ".join(f'"{name}"' for name in typo.mono_families)
        values["pt_body"] = f"{typo.body_pt:g}"
        values["pt_button"] = f"{typo.button_pt:g}"
        values["pt_heading"] = f"{typo.heading_pt:g}"
        values["pt_title"] = f"{typo.title_pt:g}"
        values["pt_mono"] = f"{typo.mono_pt:g}"
        return values


DARK_TOKENS: Final = ThemeTokens()
