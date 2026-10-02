"""Documentation stub for the ``core.sort_cycle`` finding.

This finding is not produced by a validation pass: ``src.core.sorting.auto_sort`` emits one
ERROR finding with this rule id when the declared precedence edges form a cycle (it lists the
members, drops the cycle's edges and continues).  The module exists so the rule catalogue can
show an id and a description for it; it deliberately has no ``validate`` and is therefore not
part of ``BUILTIN_RULES``.
"""

from typing import Final

from src.core.sorting import SORT_CYCLE_RULE_ID

RULE_ID: Final = SORT_CYCLE_RULE_ID
DESCRIPTION: Final = "Declared precedence rules that contradict each other (emitted by Auto-Sort)."
