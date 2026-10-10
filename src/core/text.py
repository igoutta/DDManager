"""Text primitives shared by several modules: the identity punctuation class and whitespace
collapsing."""

import re
from typing import Final

PUNCTUATION_RE: Final = re.compile(r"[_\\/\-:;,.()[\]{}'\"!+]+")
"""The characters ``normalize_mod_identity`` turns into spaces."""

WHITESPACE_RE: Final = re.compile(r"\s+")
"""A run of whitespace (collapsed to one space by :func:`collapse_whitespace`)."""


def collapse_whitespace(text: str) -> str:
    """Runs of whitespace become one space and the result is stripped."""
    return WHITESPACE_RE.sub(" ", text).strip()
