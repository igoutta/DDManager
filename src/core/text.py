"""Text primitives the legacy spelled out in several places (``dd2.py:546-554``, ``3423-3430``,
``categories.py:105-131``): the identity punctuation class and whitespace collapsing."""

import re
from typing import Final

PUNCTUATION_RE: Final = re.compile(r"[_\\/\-:;,.()[\]{}'\"!+]+")
"""The characters ``normalize_mod_identity`` (``dd2.py:552``) turns into spaces."""

WHITESPACE_RE: Final = re.compile(r"\s+")
"""A run of whitespace (the legacy ``re.sub(r"\\s+", " ", ...)`` pattern)."""


def collapse_whitespace(text: str) -> str:
    """Runs of whitespace become one space and the result is stripped."""
    return WHITESPACE_RE.sub(" ", text).strip()
