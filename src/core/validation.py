"""Validation: the rule protocol, the context rules inspect, the run loop and fix application.

A *rule* inspects a :class:`ValidationContext` (the load order, the installed mods, their tiers,
the resolved community rules and the priority setting) and returns :class:`Finding` values.
Every diagnostic in the app is a ``Finding`` (defined in :mod:`src.core.findings` and
re-exported here); there is no separate "warning" type.

Direction-dependent findings (anything that depends on which of two mods wins a conflict) are
downgraded to ``INFO`` while the priority direction is unverified, via
:meth:`ValidationContext.capped`.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from types import ModuleType
from typing import Protocol

from src.core.findings import (
    DisableMods,
    EnableMods,
    Finding,
    Fix,
    MakeWin,
    SetTier,
    Severity,
)
from src.core.ids import ModId
from src.core.load_order import LoadOrder, PriorityDirection, PrioritySetting
from src.core.model import ModInfo
from src.core.rules_resolve import ResolvedRules
from src.core.tiers import Tier

__all__ = [
    "DisableMods",
    "EnableMods",
    "Finding",
    "Fix",
    "MakeWin",
    "ModuleRule",
    "Rule",
    "SetTier",
    "Severity",
    "ValidationContext",
    "ValidationReport",
    "apply_fix",
    "run_rules",
    "sort_findings",
]


# ---------------------------------------------------------------- rules


class Rule(Protocol):
    """Anything with an id, a description and ``validate(ctx)``."""

    @property
    def rule_id(self) -> str: ...

    @property
    def description(self) -> str: ...

    def validate(self, ctx: ValidationContext) -> list[Finding]: ...


@dataclass(frozen=True, slots=True)
class ModuleRule:
    """Adapter turning a module that exports ``validate(ctx)`` into a :class:`Rule`.

    Built-in rules (``src/rules/*.py``) and user rules (``<data>/rules/*.py``) share this
    adapter.  ``RULE_ID`` and ``DESCRIPTION`` are optional module attributes; the id defaults
    to ``"<default_prefix>.<module basename>"``.
    """

    rule_id: str
    description: str
    func: Callable[[ValidationContext], list[Finding]]

    def validate(self, ctx: ValidationContext) -> list[Finding]:
        return self.func(ctx)

    @classmethod
    def from_module(cls, module: ModuleType, *, default_prefix: str = "user") -> ModuleRule:
        func = getattr(module, "validate", None)
        if not callable(func):
            raise TypeError(f"rule module {module.__name__!r} has no callable validate(ctx)")
        rule_id = getattr(module, "RULE_ID", None)
        if not isinstance(rule_id, str) or not rule_id:
            rule_id = f"{default_prefix}.{module.__name__.rpartition('.')[2]}"
        description = getattr(module, "DESCRIPTION", "")
        if not isinstance(description, str):
            description = ""
        return cls(rule_id=rule_id, description=description, func=func)


# ---------------------------------------------------------------- context


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Everything a rule may look at.  Build it with :meth:`build` so ``precedence`` is right.

    ``default_tier`` is what :meth:`tier` reports for a mod missing from ``tiers``; callers pass
    their table's ``unassigned()`` so the fallback carries that table's weight.
    """

    order: LoadOrder
    mods: Mapping[ModId, ModInfo]
    tiers: Mapping[ModId, Tier]
    rules: ResolvedRules
    priority: PrioritySetting
    precedence: Mapping[ModId, int]
    default_tier: Tier
    max_detail_paths: int = 5

    @classmethod
    def build(
        cls,
        *,
        order: LoadOrder,
        mods: Mapping[ModId, ModInfo],
        tiers: Mapping[ModId, Tier],
        rules: ResolvedRules,
        priority: PrioritySetting,
        default_tier: Tier,
        max_detail_paths: int = 5,
    ) -> ValidationContext:
        return cls(
            order=order,
            mods=mods,
            tiers=tiers,
            rules=rules,
            priority=priority,
            precedence=order.precedence(priority.direction),
            default_tier=default_tier,
            max_detail_paths=max_detail_paths,
        )

    def info(self, mod: ModId) -> ModInfo | None:
        return self.mods.get(mod)

    def tier(self, mod: ModId) -> Tier:
        return self.tiers.get(mod, self.default_tier)

    def label(self, mod: ModId) -> str:
        """The mod's title, or its folder key when it is unknown or untitled."""
        info = self.mods.get(mod)
        return info.title if info is not None and info.title else str(mod)

    def wins(self, a: ModId, b: ModId) -> bool:
        """Whether ``a`` beats ``b`` in a file conflict (inactive mods lose to everything)."""
        return self.precedence.get(a, 0) > self.precedence.get(b, 0)

    def capped(self, severity: Severity) -> Severity:
        """Severity for direction-dependent findings: ``INFO`` until the direction is verified."""
        return severity if self.priority.verified else min(severity, Severity.INFO)

    def by_precedence(self, mods: Iterable[ModId]) -> tuple[ModId, ...]:
        """The given mods, highest precedence first (ties keep the given order)."""
        return tuple(sorted(mods, key=lambda m: -self.precedence.get(m, 0)))

    def active_infos(self) -> tuple[tuple[ModId, ModInfo], ...]:
        """``(mod, info)`` for every active mod that is installed, in load-order order."""
        return tuple((m, self.mods[m]) for m in self.order.active() if m in self.mods)


# ---------------------------------------------------------------- report


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Findings sorted by severity (worst first), rule id, first rank, message."""

    findings: tuple[Finding, ...]

    @property
    def blocking(self) -> bool:
        return any(f.severity == Severity.ERROR for f in self.findings)

    def for_mod(self, mod: ModId) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if mod in f.mod_ids)

    def count(self, severity: Severity) -> int:
        return sum(1 for f in self.findings if f.severity == severity)


def sort_findings(findings: Iterable[Finding], order: LoadOrder) -> tuple[Finding, ...]:
    """Report order: severity descending, rule id, rank of the first ranked mod, message."""
    ranks = order.ranks()
    unranked = len(ranks) + 1

    def first_rank(finding: Finding) -> int:
        return next((ranks[m] for m in finding.mod_ids if m in ranks), unranked)

    return tuple(
        sorted(
            findings,
            key=lambda f: (-int(f.severity), f.rule_id, first_rank(f), f.message),
        )
    )


def run_rules(
    rules: Sequence[Rule],
    ctx: ValidationContext,
    *,
    disabled: AbstractSet[str] = frozenset(),
) -> ValidationReport:
    """Run every rule not in ``disabled``.

    A crashing rule becomes one ``internal.rule_failed`` ERROR finding instead of sinking the
    report; duplicate rule ids are a programming error and raise ``ValueError`` up front.
    """
    duplicates = sorted(k for k, n in Counter(r.rule_id for r in rules).items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate rule ids: {', '.join(duplicates)}")
    findings: list[Finding] = []
    for rule in rules:
        if rule.rule_id not in disabled:
            findings.extend(_run_one(rule, ctx))
    return ValidationReport(sort_findings(findings, ctx.order))


def _run_one(rule: Rule, ctx: ValidationContext) -> list[Finding]:
    try:
        return list(rule.validate(ctx))
    except Exception as exc:  # noqa: BLE001 - rule isolation: one broken rule must not sink the report
        return [
            Finding(
                rule_id="internal.rule_failed",
                severity=Severity.ERROR,
                message=f"Rule {rule.rule_id} failed: {exc!r}",
                message_key="finding.internal.rule_failed",
                params=(("rule_id", rule.rule_id), ("error", repr(exc))),
            )
        ]


# ---------------------------------------------------------------- fixes


def apply_fix(order: LoadOrder, fix: Fix, direction: PriorityDirection) -> LoadOrder:
    """Return the load order with ``fix`` applied (``SetTier`` leaves the order unchanged)."""
    if isinstance(fix, MakeWin):
        return _apply_make_win(order, fix, direction)
    if isinstance(fix, DisableMods):
        return order.disable(frozenset(fix.mods))
    if isinstance(fix, EnableMods):
        return order.enable(list(fix.mods))
    return order


def _apply_make_win(order: LoadOrder, fix: MakeWin, direction: PriorityDirection) -> LoadOrder:
    """Move the winner right above ``over`` in precedence space; no-op when it already wins."""
    active = order.active()
    if fix.winner not in active or fix.over not in active or fix.winner == fix.over:
        return order
    if order.wins(fix.winner, fix.over, direction):
        return order
    over_index = active.index(fix.over)
    gap = over_index if direction is PriorityDirection.FIRST_WINS else over_index + 1
    return order.move_to({fix.winner}, gap)
