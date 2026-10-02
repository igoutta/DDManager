"""The Check Setup / Copy Debug Info text (src/core/diagnostics.py).

Legacy ``setup_diagnostics_lines`` (dd2.py:2978-3032) gathered live facts and formatted
``"Label: value"`` lines; ``build_debug_info_text`` (3034) joined them.  The port takes the facts
as a ``DiagnosticsInput`` and only formats, so the tests check that every fact is rendered, that
the output is deterministic and pure text, and that it stays English with a legacy-shaped label
vocabulary (users paste it into bug reports).
"""

import dataclasses
import inspect
import re
from typing import Any

import pytest

from src.core.diagnostics import DiagnosticsInput, diagnostics_lines
from tools.legacy_oracle import LegacyOracle

LINE = re.compile(r"^[^:\n]+: \S.*$")


def _input(**overrides: Any) -> DiagnosticsInput:
    fields: dict[str, Any] = {
        "app_version": "1.0.0-rc3",
        "python_version": "3.14.0",
        "platform": "win32",
        "data_dir": r"C:\Users\ga\AppData\Roaming\DD Manager Data",
        "mods_path": r"C:\Games\Darkest Dungeon\mods",
        "mods_path_valid": True,
        "mod_count": 37,
        "enabled_count": 23,
        "uncategorized_count": 5,
        "selected_save": r"C:\Users\ga\Documents\Darkest\profile_3\persist.game.json",
        "save_detected": True,
        "save_has_applied_block": True,
        "applied_count": 19,
        "last_backup": r"C:\Users\ga\Documents\Darkest\profile_3\persist.game.backup.json",
        "game_root": r"C:\Games\Darkest Dungeon",
        "workshop_dir": r"C:\Steam\steamapps\workshop\content\262060",
        "local_mods_dir": r"C:\Games\Darkest Dungeon\mods",
        "priority_direction": "first_wins",
        "priority_verified": True,
        "extra": (),
    }
    fields.update(overrides)
    return DiagnosticsInput(**fields)


def _labels(lines: tuple[str, ...]) -> list[str]:
    return [line.split(": ", 1)[0] for line in lines]


def _values(lines: tuple[str, ...]) -> list[str]:
    return [line.split(": ", 1)[1] for line in lines]


# ----------------------------------------------------------------- shape


def test_lines_are_label_value_pairs() -> None:
    lines = diagnostics_lines(_input())
    assert isinstance(lines, tuple)
    assert len(lines) >= 19
    for line in lines:
        assert isinstance(line, str)
        assert LINE.match(line), line
        assert "\n" not in line
    labels = _labels(lines)
    assert len(set(labels)) == len(labels), "labels are unique"


def test_output_is_deterministic() -> None:
    first = diagnostics_lines(_input())
    second = diagnostics_lines(_input())
    assert first == second


def test_every_fact_is_rendered() -> None:
    info = _input()
    text = "\n".join(diagnostics_lines(info))
    for field in dataclasses.fields(DiagnosticsInput):
        value = getattr(info, field.name)
        if isinstance(value, str):
            assert value in text, field.name
        elif isinstance(value, int) and not isinstance(value, bool):
            assert str(value) in _values(diagnostics_lines(info)), field.name


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("app_version", "9.9.9"),
        ("python_version", "3.99.1"),
        ("platform", "linux"),
        ("data_dir", "D:/elsewhere"),
        ("mods_path", "D:/mods"),
        ("mods_path_valid", False),
        ("mod_count", 1),
        ("enabled_count", 0),
        ("uncategorized_count", 36),
        ("selected_save", "D:/save.json"),
        ("save_detected", False),
        ("save_has_applied_block", False),
        ("save_has_applied_block", None),
        ("applied_count", None),
        ("applied_count", 3),
        ("last_backup", "D:/backup.json"),
        ("game_root", "D:/dd"),
        ("workshop_dir", "D:/ws"),
        ("local_mods_dir", "D:/local"),
        ("priority_direction", "last_wins"),
        ("priority_verified", False),
    ],
)
def test_changing_one_fact_changes_the_text(field: str, value: Any) -> None:
    base = diagnostics_lines(_input())
    changed = diagnostics_lines(_input(**{field: value}))
    assert changed != base, field
    assert _labels(changed) == _labels(base), "labels never depend on values"
    differing = [i for i, (a, b) in enumerate(zip(base, changed, strict=True)) if a != b]
    assert 1 <= len(differing) <= 2, (field, differing)


def test_empty_facts_still_render_a_value() -> None:
    info = _input(
        mods_path="",
        selected_save="",
        last_backup="",
        game_root="",
        workshop_dir="",
        local_mods_dir="",
        data_dir="",
        mods_path_valid=False,
        save_detected=False,
        save_has_applied_block=None,
        applied_count=None,
    )
    lines = diagnostics_lines(info)
    for line in lines:
        assert LINE.match(line), line
    assert _labels(lines) == _labels(diagnostics_lines(_input()))


def test_tristate_save_block_renders_three_distinct_values() -> None:
    variants = {
        state: diagnostics_lines(_input(save_has_applied_block=state))
        for state in (True, False, None)
    }
    rows = {state: set(lines) for state, lines in variants.items()}
    assert rows[True] != rows[False]
    assert rows[True] != rows[None]
    assert rows[False] != rows[None]


def test_extra_pairs_are_appended_in_order() -> None:
    extra = (("Qt", "6.11.2"), ("Theme", "dark"), ("Locale", "es-MX"))
    lines = diagnostics_lines(_input(extra=extra))
    base = diagnostics_lines(_input())
    assert lines[: len(base)] == base
    assert lines[len(base) :] == tuple(f"{k}: {v}" for k, v in extra)


def test_extra_values_may_contain_colons_and_spaces() -> None:
    lines = diagnostics_lines(_input(extra=(("Path", r"C:\x: y"),)))
    assert lines[-1] == r"Path: C:\x: y"


def test_counts_render_as_plain_integers() -> None:
    values = _values(diagnostics_lines(_input(mod_count=1234, enabled_count=0)))
    assert "1234" in values
    assert "0" in values
    assert not any("1,234" in v or "1 234" in v for v in values)


def test_text_is_ascii_english_when_facts_are_ascii() -> None:
    lines = diagnostics_lines(_input())
    text = "\n".join(lines)
    assert text.isascii()


def test_input_is_frozen() -> None:
    info = _input()
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.mod_count = 1  # ty: ignore[invalid-assignment]


# ----------------------------------------------------------------- legacy vocabulary


def _legacy_labels(legacy: LegacyOracle) -> set[str]:
    source = inspect.getsource(legacy.module("dd2").ModManager.setup_diagnostics_lines)
    return set(re.findall(r'f"([^":{]+): ', source))


# Legacy facts (dd2.py:3006-3032) the port deliberately does not render, with the reason.
LEGACY_LABELS_NOT_RENDERED: dict[str, str] = {
    "Captured": "core has no clock; services pass the timestamp through `extra`",
    "Language": "UI state, not a setup fact",
    "View mode": "UI state, not a setup fact",
    "Filter": "UI state, not a setup fact",
    "App data folder writable": "the folder itself is rendered; writability is a services check",
    "Workshop-backed mods": "per-kind counts are not part of DiagnosticsInput (contract)",
    "Local/manual mods": "per-kind counts are not part of DiagnosticsInput (contract)",
    "Metadata entries": "the metadata cache is gone; the uncategorized count replaces it",
    "Visible reserve rows": "widget state",
    "Visible load-order rows": "widget state",
    "Selected profile": "collapsed into 'Selected save'",
    "Selected profile path": "collapsed into 'Selected save'",
    "Latest detected save": "collapsed into 'Selected save' / 'Save detected'",
    "Detected profiles": "profile discovery is not part of DiagnosticsInput (contract)",
}


@pytest.mark.legacy
def test_every_legacy_check_setup_fact_is_rendered_or_explicitly_excluded(
    legacy: LegacyOracle,
) -> None:
    legacy_labels = _legacy_labels(legacy)
    assert len(legacy_labels) == 26  # dd2.py:3006-3032
    excluded = set(LEGACY_LABELS_NOT_RENDERED)
    assert excluded <= legacy_labels, sorted(excluded - legacy_labels)  # no stale exclusions
    expected = legacy_labels - excluded
    assert len(expected) == 12
    ours = set(_labels(diagnostics_lines(_input())))
    assert expected <= ours, sorted(expected - ours)
