"""FindingsModel: severity groups over findings."""

import pytest
from PySide6.QtCore import QModelIndex, Qt

from src.core.findings import Severity
from src.ui.models.findings_model import FindingsModel
from tests.ui.helpers import build, first_attr, make_finding


@pytest.fixture
def model(qtbot, translator):
    return build(FindingsModel, translator=translator)


def mixed(n_error=2, n_warning=3, n_info=1):
    out = [make_finding(f"e{i}", Severity.ERROR) for i in range(n_error)]
    out += [make_finding(f"w{i}", Severity.WARNING) for i in range(n_warning)]
    out += [make_finding(f"i{i}", Severity.INFO) for i in range(n_info)]
    return out


def group_labels(model):
    return [
        str(model.index(r, 0).data(Qt.ItemDataRole.DisplayRole)) for r in range(model.rowCount())
    ]


@pytest.mark.parametrize("count", [0, 1, 50])
def test_model_tester(model, qtmodeltester, count):
    severities = (Severity.ERROR, Severity.WARNING, Severity.INFO)
    model.set_findings([make_finding(f"f{i}", severities[i % 3]) for i in range(count)])
    qtmodeltester.check(model)


def test_two_level_structure_and_group_counts(model):
    model.set_findings(mixed())
    labels = group_labels(model)
    assert any("Errors (2)" in label for label in labels)
    assert any("Warnings (3)" in label for label in labels)
    assert any("Info (1)" in label for label in labels)
    counts = {}
    for row in range(model.rowCount()):
        group = model.index(row, 0)
        assert not group.parent().isValid()
        counts[group.data(Qt.ItemDataRole.DisplayRole)] = model.rowCount(group)
        for child in range(model.rowCount(group)):
            leaf = model.index(child, 0, group)
            assert leaf.parent() == group
            assert model.rowCount(leaf) == 0
    assert sorted(counts.values()) == [1, 2, 3]
    assert model.columnCount() == 4


def test_errors_group_comes_first(model):
    model.set_findings(list(reversed(mixed())))
    assert "Errors" in group_labels(model)[0]


def test_headers_are_the_four_columns(model):
    heads = [model.headerData(c, Qt.Orientation.Horizontal) for c in range(4)]
    assert all(isinstance(h, str) and h for h in heads)
    assert len(set(heads)) == 4


def test_message_and_rule_columns(model):
    model.set_findings(
        [make_finding("only", Severity.ERROR, rule_id="core.sort_cycle", message="Cycle of mods")]
    )
    group = model.index(0, 0)
    texts = [str(model.index(0, c, group).data(Qt.ItemDataRole.DisplayRole)) for c in range(4)]
    assert "core.sort_cycle" in texts
    assert "Cycle of mods" in texts


def test_set_findings_replaces_and_empties(model, qtmodeltester):
    model.set_findings(mixed())
    model.set_findings(mixed(1, 0, 0))
    qtmodeltester.check(model)
    assert sum(model.rowCount(model.index(r, 0)) for r in range(model.rowCount())) == 1
    model.set_findings([])
    assert sum(model.rowCount(model.index(r, 0)) for r in range(model.rowCount())) == 0
    assert model.rowCount(QModelIndex()) in (0, 3)


def test_severity_filter_hides_groups(model):
    set_filter = first_attr(
        model, ("set_severities", "set_severity_filter", "set_visible_severities")
    )
    model.set_findings(mixed())
    set_filter(frozenset({Severity.ERROR}))
    labels = group_labels(model)
    assert any("Errors" in label for label in labels)
    assert not any("Warnings" in label or "Info" in label for label in labels)
