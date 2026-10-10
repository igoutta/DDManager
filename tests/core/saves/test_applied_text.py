"""render_applied_text renders the applied block in the decoded-save layout, with JSON escaping."""

import json

from src.core.ids import SaveIdentity
from src.core.saves.applied_text import render_applied_text
from tests.support.dson_builder import LOCAL, STEAM
from tests.support.identities import identities

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
