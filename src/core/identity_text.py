"""The pure text gates of mod identity (``dd2.py:546-620``, ``3960-3964``).

These need nothing but :mod:`src.core.text`, so the display names, the folder planner and the
rules file can use them without importing the identity decision chain.
"""

import html
import re
from typing import Final

from src.core.text import PUNCTUATION_RE, collapse_whitespace

_LATIN_RE: Final = re.compile(r"[A-Za-z]")
_COMBATS_RE: Final = re.compile(r"\b\d+\s+combats?\b")
_BAD_TITLE_WORDS: Final = frozenset({"tooltip", "tooltips", "tray_icon"})
_PREFIX_WINDOW: Final = 5
"""``dd2.py:4017`` / ``7290``: a numeric prefix counts only when ``_`` sits in the first five
characters."""


def normalize_mod_identity(value: str | None) -> str:
    """Verbatim ``dd2.py:546-554``: unescape, lower, ``&`` -> ``and``, punctuation to spaces.

    ``None`` is accepted (and yields ``""``) exactly as the legacy did.
    """
    if value is None:
        return ""
    text = html.unescape(str(value)).lower()
    text = text.replace("&", " and ")
    return collapse_whitespace(PUNCTUATION_RE.sub(" ", text))


def strip_numeric_prefix(folder: str) -> str:
    """Verbatim ``dd2.py:3960-3964`` (``ModManager.save_name``): drop leading ``<digits>_`` parts.

    Keeps the legacy quirk that ``"1234_"`` becomes ``""`` while ``"1234"`` stays ``"1234"``.
    """
    parts = folder.split("_")
    while parts and parts[0].isdigit():
        parts.pop(0)
    return "_".join(parts) if parts else folder


def split_numeric_prefix(name: str) -> tuple[str, str] | None:
    """``(prefix, remainder)`` when ``name`` starts with ``<digits>_`` inside the first five
    characters (``dd2.py:4017-4020`` and ``7290-7293`` share this test); else ``None``."""
    if "_" not in name[:_PREFIX_WINDOW]:
        return None
    prefix, remainder = name.split("_", 1)
    return (prefix, remainder) if prefix.isdigit() else None


def text_has_latin(text: str) -> bool:
    """``dd2.py:592``: any ASCII letter."""
    return _LATIN_RE.search(text or "") is not None


def looks_like_numeric_id(text: str) -> bool:
    """``dd2.py:596``: non-empty and all digits."""
    return bool(text) and str(text).isdigit()


def is_bad_display_title(text: str) -> bool:
    """``dd2.py:600-620``: colour markup, ``%``, angle brackets, ``N combats`` or tooltip words."""
    if not text:
        return True
    value = html.unescape(str(text)).strip()
    lowered = value.lower()
    if not value:
        return True
    if "{colour" in lowered or "{color" in lowered:
        return True
    if "%" in value or "<" in value or ">" in value:
        return True
    if _COMBATS_RE.search(lowered):
        return True
    return lowered in _BAD_TITLE_WORDS
