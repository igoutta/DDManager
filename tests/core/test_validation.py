"""src/core/validation.py: Finding values, ModuleRule, ValidationContext, ValidationReport,
run_rules and apply_fix (contract: m2_contract.md, cluster C)."""

import types
from collections.abc import Sequence

import pytest

from src.core.ids import ModId
from src.core.load_order import PriorityDirection
from src.core.tiers import Tier
from src.core.validation import (
    DisableMods,
    EnableMods,
    Finding,
    MakeWin,
    ModuleRule,
    SetTier,
    Severity,
    ValidationContext,
    ValidationReport,
    apply_fix,
    run_rules,
)
from tests.support.factories import context, load_order, local_mod, mentions, only

A, B, C, D, X = (ModId(name) for name in ("a", "b", "c", "d", "x"))
FIRST, LAST = PriorityDirection.FIRST_WINS, PriorityDirection.LAST_WINS


class StubRule:
    """A hand-rolled Rule (structural Protocol) that returns canned findings or raises."""

    def __init__(
        self,
        rule_id: str,
        findings: Sequence[Finding] = (),
        *,
        raises: Exception | None = None,
    ) -> None:
        self.rule_id = rule_id
        self.description = f"stub {rule_id}"
        self._findings = list(findings)
        self._raises = raises
        self.calls = 0

    def validate(self, ctx: ValidationContext) -> list[Finding]:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return list(self._findings)


def finding(rule_id: str, severity: Severity, *mods: str, message: str = "m") -> Finding:
    return Finding(
        rule_id=rule_id, severity=severity, message=message, mod_ids=tuple(ModId(m) for m in mods)
    )


def make_ctx(*spec: str, direction: PriorityDirection = FIRST, verified: bool = True):
    keys = [item.removeprefix("-") for item in spec]
    return context(
        load_order(*spec),
        [local_mod(key) for key in keys],
        direction=direction,
        verified=verified,
    )


# ------------------------------------------------------------------ values


def test_severity_is_an_ordered_int_enum() -> None:
    assert (Severity.INFO, Severity.WARNING, Severity.ERROR) == (10, 20, 30)
    assert Severity.INFO < Severity.WARNING < Severity.ERROR
    assert min(Severity.ERROR, Severity.INFO) is Severity.INFO
    assert max(Severity.WARNING, Severity.INFO) is Severity.WARNING


def test_finding_defaults_and_focus_key() -> None:
    bare = Finding(rule_id="core.x", severity=Severity.INFO, message="hello")
    assert (bare.mod_ids, bare.fix, bare.message_key, bare.params, bare.details) == (
        (),
        None,
        "",
        (),
        (),
    )
    assert bare.key == "core.x:"
    full = Finding(
        rule_id="core.x",
        severity=Severity.WARNING,
        message="hello",
        mod_ids=(A, B),
        fix=MakeWin(winner=A, over=B),
        message_key="finding.x",
        params=(("mod", "a"),),
        details=("heroes/a.darkest",),
    )
    assert full.key == "core.x:a,b"
    assert full.fix == MakeWin(A, B)
    assert hash(full) == hash(
        Finding(
            rule_id="core.x",
            severity=Severity.WARNING,
            message="hello",
            mod_ids=(A, B),
            fix=MakeWin(winner=A, over=B),
            message_key="finding.x",
            params=(("mod", "a"),),
            details=("heroes/a.darkest",),
        )
    )
    with pytest.raises(AttributeError):
        full.message = "changed"  # ty: ignore[invalid-assignment]


def test_fix_values_are_plain_frozen_records() -> None:
    assert MakeWin(winner=A, over=B) == MakeWin(ModId("a"), ModId("b"))
    assert DisableMods(mods=(A, B)) == DisableMods((ModId("a"), ModId("b")))
    assert EnableMods(mods=(C,)) != EnableMods(mods=(D,))
    assert SetTier(mod=A, tier_id="patch").tier_id == "patch"
    assert len({MakeWin(A, B), MakeWin(A, B), DisableMods((A,))}) == 2
    with pytest.raises(AttributeError):
        DisableMods((A,)).mods = ()  # ty: ignore[invalid-assignment]


# ------------------------------------------------------------------ ModuleRule


def _module(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def test_module_rule_defaults_from_module_name() -> None:
    module = _module("my_rule", validate=lambda ctx: [])
    rule = ModuleRule.from_module(module)
    assert rule.rule_id == "user.my_rule"
    assert isinstance(rule.description, str)
    assert ModuleRule.from_module(module, default_prefix="core").rule_id == "core.my_rule"


def test_module_rule_honours_explicit_id_and_description() -> None:
    module = _module(
        "whatever", RULE_ID="core.custom_id", DESCRIPTION="checks things", validate=lambda ctx: []
    )
    rule = ModuleRule.from_module(module)
    assert (rule.rule_id, rule.description) == ("core.custom_id", "checks things")


def test_module_rule_delegates_validate_to_the_module_function() -> None:
    canned = [finding("user.delegating", Severity.INFO, "a")]
    seen: list[ValidationContext] = []

    def validate(ctx: ValidationContext) -> list[Finding]:
        seen.append(ctx)
        return canned

    rule = ModuleRule.from_module(_module("delegating", validate=validate))
    ctx = make_ctx("a")
    assert rule.validate(ctx) == canned
    assert seen == [ctx]


def test_module_rule_without_validate_is_rejected() -> None:
    with pytest.raises((AttributeError, TypeError, ValueError)):
        ModuleRule.from_module(_module("broken", RULE_ID="user.broken"))


# ------------------------------------------------------------------ ValidationContext


def test_build_precomputes_precedence_for_the_configured_direction() -> None:
    for direction in (FIRST, LAST):
        ctx = make_ctx("a", "b", "-x", "c", direction=direction)
        assert dict(ctx.precedence) == ctx.order.precedence(direction)
        assert ctx.priority.direction is direction
        assert ctx.priority.verified is True
        assert ctx.max_detail_paths == 5


def test_wins_follows_the_direction() -> None:
    first = make_ctx("a", "b", direction=FIRST)
    assert first.wins(A, B) and not first.wins(B, A)
    last = make_ctx("a", "b", direction=LAST)
    assert last.wins(B, A) and not last.wins(A, B)


def test_info_tier_and_label_lookups() -> None:
    titled = local_mod("titled_mod", title="A Proper Title")
    untitled = local_mod("untitled", title="")
    ctx = context(
        load_order("titled_mod", "untitled", "ghost"),
        [titled, untitled],
        tiers={"titled_mod": "patch"},
    )
    assert ctx.info(ModId("titled_mod")) is titled
    assert ctx.info(ModId("ghost")) is None
    assert ctx.tier(ModId("titled_mod")).id == "patch"
    unassigned = ctx.tier(ModId("untitled"))
    assert isinstance(unassigned, Tier) and unassigned.id == "unassigned"
    assert isinstance(ctx.tier(ModId("ghost")), Tier)
    assert ctx.label(ModId("titled_mod")) == "A Proper Title"
    assert ctx.label(ModId("untitled")) == "untitled"
    assert ctx.label(ModId("ghost")) == "ghost"


def test_tier_falls_back_to_the_default_tier_the_caller_built_the_context_with() -> None:
    """The fallback carries the caller's table weight (``table.unassigned()``), not a fixed 0."""
    ctx = context(load_order("a", "ghost"), [local_mod("a")])
    assert ctx.tier(ModId("ghost")) is ctx.default_tier
    assert ctx.tier(ModId("a")) is not None
    assert ctx.default_tier.id == "unassigned"
    assert ctx.default_tier.weight == 1000  # factories.TIER_WEIGHTS: above every category


def test_finding_factories_set_message_key_and_sorted_params() -> None:
    warning = Finding.warning("rules.bad_ref", "Bad ref.", where="mods", field="x")
    assert warning.severity is Severity.WARNING
    assert warning.rule_id == "rules.bad_ref"
    assert warning.message_key == "finding.rules.bad_ref"
    assert warning.params == (("field", "x"), ("where", "mods"))
    assert warning.mod_ids == () and warning.fix is None and warning.details == ()
    assert Finding.error("x", "m").severity is Severity.ERROR
    assert Finding.info("x", "m").severity is Severity.INFO
    full = Finding.at(Severity.ERROR, "r", "m", mod_ids=[ModId("a")], details=["d1", "d2"], k="v")
    assert full.mod_ids == (ModId("a"),)
    assert full.details == ("d1", "d2")
    assert full.params == (("k", "v"),)


def test_capped_lowers_everything_to_info_while_unverified() -> None:
    verified = make_ctx("a", verified=True)
    unverified = make_ctx("a", verified=False)
    for severity in Severity:
        assert verified.capped(severity) is severity
        assert unverified.capped(severity) is Severity.INFO


def test_build_accepts_a_custom_detail_cap() -> None:
    ctx = context(load_order("a"), [local_mod("a")], max_detail_paths=2)
    assert ctx.max_detail_paths == 2


# ------------------------------------------------------------------ ValidationReport


def test_report_blocking_for_mod_and_count() -> None:
    warn_ab = finding("core.one", Severity.WARNING, "a", "b")
    info_c = finding("core.two", Severity.INFO, "c")
    report = ValidationReport(findings=(warn_ab, info_c))
    assert report.blocking is False
    assert report.for_mod(A) == (warn_ab,)
    assert report.for_mod(B) == (warn_ab,)
    assert report.for_mod(C) == (info_c,)
    assert report.for_mod(D) == ()
    assert (report.count(Severity.WARNING), report.count(Severity.INFO)) == (1, 1)
    assert report.count(Severity.ERROR) == 0
    blocking = ValidationReport(findings=(finding("core.three", Severity.ERROR, "a"), info_c))
    assert blocking.blocking is True


def test_empty_report() -> None:
    report = ValidationReport(findings=())
    assert not report.blocking
    assert report.for_mod(A) == ()
    assert all(report.count(s) == 0 for s in Severity)


# ------------------------------------------------------------------ run_rules


def test_run_rules_sorts_by_severity_rule_id_first_rank_then_message() -> None:
    ctx = make_ctx("a", "b", "c")
    beta = StubRule(
        "core.beta",
        [
            finding("core.beta", Severity.WARNING, "c"),
            finding("core.beta", Severity.ERROR, "b"),
            finding("core.beta", Severity.WARNING, "a"),
        ],
    )
    alpha = StubRule(
        "core.alpha",
        [
            finding("core.alpha", Severity.WARNING, "b", message="zzz"),
            finding("core.alpha", Severity.WARNING, "b", message="aaa"),
        ],
    )
    report = run_rules([beta, alpha], ctx)
    assert isinstance(report, ValidationReport)
    assert isinstance(report.findings, tuple)
    assert [(f.severity, f.rule_id, f.mod_ids, f.message) for f in report.findings] == [
        (Severity.ERROR, "core.beta", (B,), "m"),
        (Severity.WARNING, "core.alpha", (B,), "aaa"),
        (Severity.WARNING, "core.alpha", (B,), "zzz"),
        (Severity.WARNING, "core.beta", (A,), "m"),
        (Severity.WARNING, "core.beta", (C,), "m"),
    ]
    assert report.blocking


def test_run_rules_isolates_a_crashing_rule_into_an_error_finding() -> None:
    ctx = make_ctx("a", "b")
    crashing = StubRule("core.crashy", raises=RuntimeError("boom goes the rule"))
    fine = StubRule("core.fine", [finding("core.fine", Severity.INFO, "a")])
    report = run_rules([crashing, fine], ctx)
    failure = only(report.findings, "internal.rule_failed")
    assert failure.severity is Severity.ERROR
    assert mentions(failure, "core.crashy")
    assert mentions(failure, "boom goes the rule")
    assert only(report.findings, "core.fine").mod_ids == (A,)
    assert fine.calls == 1


def test_run_rules_rejects_duplicate_rule_ids_before_running_anything() -> None:
    ctx = make_ctx("a")
    first = StubRule("core.same")
    second = StubRule("core.same")
    with pytest.raises(ValueError, match=r"core\.same"):
        run_rules([first, second], ctx)
    assert (first.calls, second.calls) == (0, 0)


def test_run_rules_skips_disabled_rule_ids() -> None:
    ctx = make_ctx("a")
    skipped = StubRule("core.skipped", [finding("core.skipped", Severity.ERROR, "a")])
    kept = StubRule("core.kept", [finding("core.kept", Severity.INFO, "a")])
    report = run_rules([skipped, kept], ctx, disabled={"core.skipped"})
    assert [f.rule_id for f in report.findings] == ["core.kept"]
    assert skipped.calls == 0


def test_run_rules_with_no_rules_is_an_empty_report() -> None:
    report = run_rules([], make_ctx("a"))
    assert report.findings == ()
    assert not report.blocking


# ------------------------------------------------------------------ apply_fix


def test_make_win_moves_the_winner_just_above_over_in_precedence_first_wins() -> None:
    order = load_order("a", "b", "c", "d")
    moved = apply_fix(order, MakeWin(winner=D, over=B), FIRST)
    assert moved.active() == (A, D, B, C)
    assert moved.enabled == order.enabled
    assert moved.wins(D, B, FIRST)


def test_make_win_moves_the_winner_just_after_over_in_index_space_last_wins() -> None:
    order = load_order("a", "b", "c", "d")
    moved = apply_fix(order, MakeWin(winner=A, over=C), LAST)
    assert moved.active() == (B, C, A, D)
    assert moved.wins(A, C, LAST)


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_make_win_is_a_no_op_when_the_winner_already_wins(direction: PriorityDirection) -> None:
    order = load_order("a", "b", "c")
    winner, loser = (A, C) if direction is FIRST else (C, A)
    assert apply_fix(order, MakeWin(winner=winner, over=loser), direction) == order


def test_make_win_keeps_disabled_slots_in_place() -> None:
    order = load_order("a", "-x", "b", "c", "d")
    moved = apply_fix(order, MakeWin(winner=D, over=B), FIRST)
    assert moved.entries == (A, X, D, B, C)
    assert moved.active() == (A, D, B, C)
    assert not moved.is_enabled(X)


def test_disable_mods_keeps_the_slots() -> None:
    order = load_order("a", "b", "c")
    disabled = apply_fix(order, DisableMods(mods=(B, C)), FIRST)
    assert disabled.entries == (A, B, C)
    assert disabled.active() == (A,)
    assert disabled.inactive() == (B, C)


def test_enable_mods_appends_after_the_last_active_entry() -> None:
    """Documented divergence: enabling appends after the last active entry, not in the old slot."""
    order = load_order("a", "-b", "c")
    enabled = apply_fix(order, EnableMods(mods=(B,)), FIRST)
    assert enabled.active() == (A, C, B)
    assert enabled.is_enabled(B)
    assert set(enabled.entries) == {A, B, C}


def test_enable_mods_ignores_already_enabled_ids() -> None:
    order = load_order("a", "b")
    assert apply_fix(order, EnableMods(mods=(A,)), LAST) == order


def test_set_tier_leaves_the_order_untouched() -> None:
    order = load_order("a", "-b", "c")
    assert apply_fix(order, SetTier(mod=A, tier_id="patch"), FIRST) == order
    assert apply_fix(order, SetTier(mod=A, tier_id="patch"), LAST) == order
