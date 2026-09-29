"""render_applied_text reproduces the legacy 'Generate Save Code' layout, with JSON escaping."""

import inspect
import json
import textwrap
from types import ModuleType

import pytest

from src.core.ids import SaveIdentity
from src.core.saves.applied_text import render_applied_text
from tests.support.dson_builder import LOCAL, STEAM
from tests.support.identities import identities
from tools.legacy_oracle import LegacyOracle

PLAIN = identities([("1234567890", STEAM), ("Local Mod", LOCAL), ("42", STEAM)])

EXPECTED_PLAIN = "\n".join(
    [
        '        "applied_ugcs_1_0" : {',
        '            "0" : {',
        '                "name" : "1234567890",',
        '                "source" : "Steam"',
        "            },",
        '            "1" : {',
        '                "name" : "Local Mod",',
        '                "source" : "mod_local_source"',
        "            },",
        '            "2" : {',
        '                "name" : "42",',
        '                "source" : "Steam"',
        "            }",
        "        },",
    ]
)


def test_layout_for_plain_names() -> None:
    assert render_applied_text(PLAIN) == EXPECTED_PLAIN


def test_single_entry_has_no_trailing_comma_on_the_child() -> None:
    text = render_applied_text(PLAIN[:1])
    assert text.splitlines()[-2:] == ["            }", "        },"]
    assert text.count("},") == 1


def test_quotes_and_backslashes_are_escaped() -> None:
    name = 'He said "hi" \\ done'
    text = render_applied_text([SaveIdentity(name, LOCAL)])
    expected_line = f'                "name" : {json.dumps(name)},'
    assert expected_line in text.splitlines()
    assert '\\"hi\\"' in text
    assert "\\\\" in text
    # every line except the outer braces stays valid JSON once wrapped
    body = "{" + text.rstrip(",") + "}"
    assert json.loads(body)["applied_ugcs_1_0"]["0"]["name"] == name


def test_utf8_names_survive() -> None:
    name = "测试模组"
    text = render_applied_text([SaveIdentity(name, LOCAL)])
    body = json.loads("{" + text.rstrip(",") + "}")
    assert body["applied_ugcs_1_0"]["0"] == {"name": name, "source": LOCAL}


def _legacy_render(dd2: ModuleType, entries: tuple[SaveIdentity, ...]) -> str:
    """Run the text-building lines of the pinned generate_save_code (dd2.py:7164-7182)."""
    source = inspect.getsource(dd2.ModManager.generate_save_code)
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines) if 'indent1 = "' in line)
    end = next(i for i, line in enumerate(lines) if 'output = "\\n".join(lines)' in line)
    snippet = textwrap.dedent("\n".join(lines[start : end + 1]))
    table = {f"mod_{k}": (e.name, e.source) for k, e in enumerate(entries)}

    class Stub:
        def save_identity_for_mod(self, mod: str) -> tuple[str, str]:
            return table[mod]

    namespace: dict[str, object] = {"self": Stub(), "enabled_mods": list(table)}
    exec(snippet, namespace)
    output = namespace["output"]
    assert isinstance(output, str)
    return output


@pytest.mark.legacy
@pytest.mark.parametrize(
    "entries",
    [PLAIN, PLAIN[:1], identities([("x", LOCAL), ("22", STEAM)])],
    ids=["three", "one", "two"],
)
def test_layout_matches_the_pinned_legacy_text(
    legacy: LegacyOracle, entries: tuple[SaveIdentity, ...]
) -> None:
    dd2 = legacy.module("dd2")
    assert render_applied_text(entries) == _legacy_render(dd2, entries)
