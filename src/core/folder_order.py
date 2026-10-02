"""Planning for "Apply order to local mod folders" (legacy ``dd2.py:7226-7311``, made sane).

The legacy renamed every local mod folder to ``<category base + index>_<name>`` so the game
loads them in list order; the base came from the category priority table (``7239-7250``).
Here the prefix is simply the 4-digit 1-based position in ``LoadOrder.entries`` (monotonic,
disabled mods included as in the legacy loop over ``order``), one existing numeric prefix is
stripped exactly like ``7290-7293``, a previous ``_<n>_`` dedupe segment is dropped too, and
collisions are deduplicated with ``_<n>_`` (``7296-7303``).  Only the plan is computed here;
the services layer performs the renames in two phases (see :class:`RenamePlan`).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from src.core.findings import Finding, Severity
from src.core.identity_text import split_numeric_prefix
from src.core.ids import ModId, SourceKind
from src.core.load_order import LoadOrder
from src.core.model import ModInfo

MAX_ENTRIES: Final = 9999
"""The largest position a 4-digit prefix can express."""

_DEDUPE_SUFFIX_RE: Final = re.compile(r"\d{1,2}_(.+)")
"""A dedupe counter is tiny (``7301``: it starts at 1 and grows per collision); a longer digit
run after the prefix, such as a 7+ digit Workshop id in ``0005_1234567_mymod``, is content."""


@dataclass(frozen=True, slots=True)
class RenameStep:
    """Rename the folder of ``mod`` from ``old_name`` to ``new_name`` (same parent)."""

    mod: ModId
    old_name: str
    new_name: str


@dataclass(frozen=True, slots=True)
class RenamePlan:
    """The steps to perform and the id mapping to apply to the state afterwards.

    Targets routinely equal other steps' sources (``foo`` -> ``0001_foo`` while ``0001_foo`` ->
    ``0002_foo``; cycles are possible), so the steps MUST be executed in two phases exactly as
    the legacy did (``dd2.py:7329-7360``): every ``old_name`` to a temporary name first, then
    every temporary name to its ``new_name``, rolling back on failure (``7405-7415``).
    :attr:`requires_two_phase` says whether a plain sequential rename would collide.
    """

    steps: tuple[RenameStep, ...]
    rekey: Mapping[ModId, ModId]
    findings: tuple[Finding, ...]

    @property
    def requires_two_phase(self) -> bool:
        """True when some step's target is another step's source (case-insensitively)."""
        sources = {step.old_name.casefold() for step in self.steps}
        return any(step.new_name.casefold() in sources for step in self.steps)


def strip_order_prefix(name: str) -> str:
    """Drop ONE numeric prefix (``dd2.py:7290-7293``) and a following ``_<n>_`` dedupe segment.

    The legacy test is kept as is: a prefix counts only when the underscore sits within the
    first five characters.  The dedupe segment is recognised only as a one- or two-digit run,
    so ``0005_1234567_mymod`` gives back ``1234567_mymod`` (a copied Workshop folder keeps its
    id).  Residual ambiguity: a content name that itself starts with a short number, such as
    ``2_player_mod``, cannot be told from a dedupe segment once prefixed and is shortened to
    ``player_mod`` on the next apply.  A name that would become empty is returned unchanged.
    """
    split = split_numeric_prefix(name)
    if split is None:
        return name
    stripped = split[1]
    match = _DEDUPE_SUFFIX_RE.fullmatch(stripped)
    if match:
        stripped = match.group(1)
    return stripped or name


def _dedupe(prefix: str, stripped: str, used: set[str]) -> str:
    """``dd2.py:7296-7303``: insert ``_<n>_`` until the lower-cased name is unused."""
    candidate = f"{prefix}_{stripped}"
    suffix = 1
    while candidate.lower() in used:
        candidate = f"{prefix}_{suffix}_{stripped}"
        suffix += 1
    used.add(candidate.lower())
    return candidate


def _local_mods(
    order: LoadOrder, mods: Mapping[ModId, ModInfo]
) -> tuple[list[tuple[int, ModId]], list[ModId]]:
    """``(position, mod)`` for every local entry, plus the entries without a ``ModInfo``."""
    local: list[tuple[int, ModId]] = []
    unknown: list[ModId] = []
    for position, mod in enumerate(order.entries, start=1):
        info = mods.get(mod)
        if info is None:
            unknown.append(mod)
        elif info.kind is SourceKind.LOCAL:
            local.append((position, mod))
    return local, unknown


def plan_folder_renames(order: LoadOrder, mods: Mapping[ModId, ModInfo]) -> RenamePlan:
    """Plan the renames that make local folder names sort like ``order.entries``.

    Workshop mods are skipped (``dd2.py:7281-7283``); entries without a ``ModInfo`` are skipped
    with a WARNING finding (the legacy aborted, ``7270-7279``).  More than :data:`MAX_ENTRIES`
    entries yield an ERROR finding and an empty plan.  Mods whose name would not change get
    no step but still reserve their name.  Applying the plan and planning again yields no
    steps (idempotent), Workshop-style ``<id>_<name>`` content names included.
    """
    if len(order.entries) > MAX_ENTRIES:
        finding = Finding.error(
            "folder_order.too_many_mods",
            f"Cannot apply the order to folders: more than {MAX_ENTRIES} mods are listed.",
        )
        return RenamePlan((), {}, (finding,))
    local, unknown = _local_mods(order, mods)
    findings: list[Finding] = []
    if unknown:
        findings.append(
            Finding.at(
                Severity.WARNING,
                "folder_order.missing_mods",
                f"{len(unknown)} listed mod(s) are not on disk and were skipped.",
                mod_ids=unknown,
            )
        )
    used: set[str] = set()
    steps: list[RenameStep] = []
    for position, mod in local:
        new_name = _dedupe(f"{position:04d}", strip_order_prefix(mod), used)
        if new_name != mod:
            steps.append(RenameStep(mod, mod, new_name))
    rekey = {step.mod: ModId(step.new_name) for step in steps}
    return RenamePlan(tuple(steps), rekey, tuple(findings))
