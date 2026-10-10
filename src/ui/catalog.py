"""Pure builders: scan result + state -> immutable view models (no Qt, no I/O)."""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from src.core.categories import CATEGORY_COLORS, category_color
from src.core.display import display_name, sort_key
from src.core.findings import DisableMods, EnableMods, Finding, MakeWin, SetTier, Severity
from src.core.ids import ModId
from src.core.load_order import LoadOrder
from src.core.model import ModInfo
from src.ui.session import Session
from src.ui.theme.tokens import tier_token
from src.ui.viewmodels import (
    DetailsVM,
    FindingVM,
    ModRowVM,
    MultiDetailsVM,
    OrderDiffRow,
    OrderDiffVM,
)

type Tr = Callable[..., str]
type Has = Callable[[str], bool]

_UNASSIGNED_COLOR = CATEGORY_COLORS["Unassigned"]
_SUMMARY_LINES = 3


def category_label(name: str | None, tr: Tr, has: Has | None = None) -> str:
    """The translated category name (``category_<snake>`` keys), else the raw name.

    With ``has`` a name the catalog does not know (a custom category) is shown as typed.
    """
    if not name:
        return tr("category_unassigned")
    key = f"category_{name.lower().replace(' ', '_')}"
    return tr(key) if has is None or has(key) else name


def finding_message(finding: Finding, tr: Tr, has: Has) -> str:
    """The translated message when the catalog knows the key, else the English sentence."""
    key = finding.message_key
    if key and has(key):
        return tr(key, **dict(finding.params))
    return finding.message


def fix_label(finding: Finding, tr: Tr) -> str | None:
    match finding.fix:
        case MakeWin():
            return tr("ui.fix.make_win")
        case DisableMods():
            return tr("ui.fix.disable")
        case EnableMods():
            return tr("ui.fix.enable")
        case SetTier():
            return tr("ui.fix.set_tier")
        case None:
            return None
    return None


def finding_vm(finding: Finding, tr: Tr, has: Has) -> FindingVM:
    return FindingVM(
        key=finding.key,
        rule_id=finding.rule_id,
        severity=int(finding.severity),
        message=finding_message(finding, tr, has),
        mod_ids=finding.mod_ids,
        fix_label=fix_label(finding, tr),
        details=finding.details,
    )


def counts(findings: Sequence[Finding]) -> tuple[int, int, int]:
    """``(errors, warnings, infos)``."""
    errors = sum(1 for f in findings if f.severity >= Severity.ERROR)
    warnings = sum(1 for f in findings if Severity.WARNING <= f.severity < Severity.ERROR)
    return (errors, warnings, len(findings) - errors - warnings)


def findings_by_mod(findings: Sequence[Finding]) -> dict[ModId, list[Finding]]:
    grouped: dict[ModId, list[Finding]] = defaultdict(list)
    for item in findings:
        for mod in item.mod_ids:
            grouped[mod].append(item)
    return grouped


class RowBuilder:
    """Builds :class:`ModRowVM` / :class:`DetailsVM` from a session."""

    def __init__(
        self,
        tr: Tr,
        has: Has,
        source_names: Mapping[str, str],
        page_url: Callable[[ModInfo], str | None],
    ) -> None:
        self._tr = tr
        self._has = has
        self._source_names = source_names
        self._page_url = page_url

    # ------------------------------------------------------------------ rows

    def build_all(self, s: Session) -> dict[ModId, ModRowVM]:
        grouped = findings_by_mod(s.findings)
        return {mod: self._row(mod, s, grouped.get(mod, [])) for mod in s.order.entries}

    def build_some(self, ids: Iterable[ModId], s: Session) -> dict[ModId, ModRowVM]:
        """The rows of those ``ids`` that are order entries (the shape of ``build_all``)."""
        grouped = findings_by_mod(s.findings)
        entries = set(s.order.entries)
        return {mod: self._row(mod, s, grouped.get(mod, [])) for mod in ids if mod in entries}

    def _common(self, mod: ModId, s: Session, found: Sequence[Finding]) -> dict[str, object]:
        tier = s.tiers.get(mod) or s.table.unassigned()
        category = s.categories.get(mod) or tier.category
        label = category_label(category, self._tr, self._has)
        return {
            "tier_id": tier.id,
            "tier_badge": self._tr(tier_token(tier.id).badge_key),
            "tier_label": label,
            "category_label": label,
            "color": category_color(
                category or "Unassigned", s.doc.category_colors, _UNASSIGNED_COLOR
            ),
            "enabled": s.order.is_enabled(mod),
            "worst_severity": max((int(f.severity) for f in found), default=0),
            "finding_count": len(found),
            "finding_summary": "\n".join(
                finding_message(f, self._tr, self._has) for f in found[:_SUMMARY_LINES]
            ),
        }

    def _row(self, mod: ModId, s: Session, found: Sequence[Finding]) -> ModRowVM:
        info = s.mods.get(mod)
        common = self._common(mod, s, found)
        if info is None:
            return self._missing_row(mod, s, common)
        return self._present_row(mod, info, s, common)

    def _missing_row(self, mod: ModId, s: Session, common: dict[str, object]) -> ModRowVM:
        identity = s.doc.metadata_identities.get(mod)
        ident_text = f"{identity.name} · {identity.source}" if identity else ""
        return ModRowVM(
            mod_id=mod,
            title=str(mod),
            subtitle=self._tr("ui.row.missing"),
            folder=str(mod),
            source_id="",
            source_label="",
            save_identity_text=ident_text,
            missing=True,
            search_blob=f"{mod} {ident_text}".casefold(),
            sort_key=str(mod).casefold(),
            **common,  # ty: ignore[invalid-argument-type]
        )

    def _present_row(
        self, mod: ModId, info: ModInfo, s: Session, common: dict[str, object]
    ) -> ModRowVM:
        nickname = s.doc.nicknames.get(mod)
        title = display_name(info, nickname)
        source_label = self._source_names.get(info.source_id, info.source_id)
        version = info.version_label or info.updated_label
        subtitle = " · ".join(
            p for p in (source_label, version, str(common["category_label"])) if p
        )
        ident = info.save_identity
        blob = " ".join((title, str(mod), ident.name, info.workshop_id, nickname or "", *info.tags))
        return ModRowVM(
            mod_id=mod,
            title=title,
            subtitle=subtitle,
            folder=str(mod),
            source_id=info.source_id,
            source_label=source_label,
            save_identity_text=f"{ident.name} · {ident.source}",
            is_new=mod in s.new_ids,
            search_blob=blob.casefold(),
            sort_key=sort_key(info, nickname),
            icon_path=Path(info.preview_path) if info.preview_path is not None else None,
            icon_stamp=info.preview_mtime_ns,
            black_reliquary=info.black_reliquary,
            version_label=info.version_label,
            updated_label=info.updated_label,
            **common,  # ty: ignore[invalid-argument-type]
        )

    # ------------------------------------------------------------------ details

    def details(
        self, ids: Sequence[ModId], s: Session, rows: Mapping[ModId, ModRowVM]
    ) -> DetailsVM | MultiDetailsVM | None:
        known = [mod for mod in ids if mod in rows]
        if not known:
            return None
        if len(known) > 1:
            return self._multi(known, rows)
        return self._single(known[0], s, rows[known[0]])

    @staticmethod
    def _multi(ids: Sequence[ModId], rows: Mapping[ModId, ModRowVM]) -> MultiDetailsVM:
        tally: dict[str, int] = defaultdict(int)
        for mod in ids:
            tally[rows[mod].tier_label] += 1
        ordered = sorted(tally.items(), key=lambda item: (-item[1], item[0]))
        return MultiDetailsVM(len(ids), tuple(ordered))

    def _rank_text(self, mod: ModId, order: LoadOrder) -> str:
        rank = order.rank(mod)
        if rank is None:
            return self._tr("ui.details.not_enabled")
        total = len(order.active())
        return self._tr("ui.details.rank", rank=rank, total=total, entry=rank - 1)

    def _single(self, mod: ModId, s: Session, row: ModRowVM) -> DetailsVM:
        info = s.mods.get(mod)
        found = [f for f in s.findings if mod in f.mod_ids]
        return DetailsVM(
            mod_id=mod,
            title=row.title,
            rank_text=self._rank_text(mod, s.order),
            identity_text=row.save_identity_text,
            folder=row.folder,
            source_label=row.source_label,
            workshop_url=self._page_url(info) if info is not None else None,
            path=Path(info.path) if info is not None else Path(str(mod)),
            version_text=" · ".join(p for p in (row.version_label, row.updated_label) if p),
            category_label=row.category_label,
            tier_label=row.tier_label,
            tags=info.tags if info is not None else (),
            findings=tuple(finding_vm(f, self._tr, self._has) for f in found),
            icon_path=row.icon_path,
            icon_stamp=row.icon_stamp,
        )


# ---------------------------------------------------------------------- diffs


def order_diff_vm(before: LoadOrder, after: LoadOrder, titles: Mapping[ModId, str]) -> OrderDiffVM:
    """Every active mod of ``after`` (then the removed ones) with its old/new rank."""
    old, new = before.ranks(), after.ranks()
    shown = [*new, *(mod for mod in old if mod not in new)]
    rows = tuple(
        OrderDiffRow(mod, titles.get(mod, str(mod)), old.get(mod), new.get(mod)) for mod in shown
    )
    moved = sum(1 for mod in new if mod in old and old[mod] != new[mod])
    return OrderDiffVM(
        rows=rows,
        moved_count=moved,
        total=len(new),
        added=sum(1 for mod in new if mod not in old),
        removed=sum(1 for mod in old if mod not in new),
    )
