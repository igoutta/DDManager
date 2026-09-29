"""Text rendering of the applied-mods block for hand-edited (decoded) saves."""

import json
from collections.abc import Sequence

from src.core.ids import SaveIdentity

_INDENT1 = " " * 8
_INDENT2 = " " * 12
_INDENT3 = " " * 16


def _escape(text: str) -> str:
    """JSON-escape quotes, backslashes and control characters (the legacy did not escape)."""
    return json.dumps(text, ensure_ascii=False)[1:-1]


def render_applied_text(entries: Sequence[SaveIdentity]) -> str:
    """Reproduce the ``generate_save_code`` layout (dd2.py:7164-7182) exactly.

    8/12/16-space indents, the last child without a trailing comma, the block closed with ``},``
    so it can be pasted after ``never_again`` in a decoded save.  Names and sources are
    JSON-escaped, which the legacy text was not.
    """
    lines = [f'{_INDENT1}"applied_ugcs_1_0" : {{']
    last = len(entries) - 1
    for i, entry in enumerate(entries):
        lines.append(f'{_INDENT2}"{i}" : {{')
        lines.append(f'{_INDENT3}"name" : "{_escape(entry.name)}",')
        lines.append(f'{_INDENT3}"source" : "{_escape(entry.source)}"')
        lines.append(f"{_INDENT2}}}" if i == last else f"{_INDENT2}}},")
    lines.append(f"{_INDENT1}}},")
    return "\n".join(lines)
