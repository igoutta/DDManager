"""src/rules/sort_cycle.py only documents the finding that sorting.auto_sort emits."""

from src.core.ids import ModId
from src.core.load_order import PriorityDirection
from src.core.sorting import PrecedenceEdge, auto_sort
from src.core.validation import Severity
from src.rules import sort_cycle as rule
from tests.support.factories import load_order


def test_module_documents_the_sorter_finding_and_has_no_validate() -> None:
    assert rule.RULE_ID == "core.sort_cycle"
    assert rule.DESCRIPTION.strip()
    assert not hasattr(rule, "validate")


def test_auto_sort_emits_the_documented_rule_id_on_a_cycle() -> None:
    a, b = ModId("a"), ModId("b")
    edges = [PrecedenceEdge(low=a, high=b, reason="x"), PrecedenceEdge(low=b, high=a, reason="y")]
    result = auto_sort(
        load_order("a", "b"),
        tier_weight=lambda _m: 0,
        edges=edges,
        direction=PriorityDirection.FIRST_WINS,
    )
    cycle = [f for f in result.findings if f.rule_id == rule.RULE_ID]
    assert len(cycle) == 1
    assert cycle[0].severity is Severity.ERROR
    assert set(cycle[0].mod_ids) == {a, b}
