"""Builders for the pure value objects that the validation and rules tests feed to ``src.core``.

Everything here constructs ``ModInfo`` / ``LoadOrder`` / ``ValidationContext`` values directly
(never through ``derive_mod_info``), so a rule test depends only on the rule under test plus the
contract's value types.  ``sample_patch_mod`` reads one of the real patch mods under ``modding/``
with a tiny test-side reader (title, leaf ``<Tags>``, "Load this after:" bullets, file manifest)
so the rule fixtures stay independent of the production ``project_xml`` parser.
"""

import dataclasses
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath

from src.core.ids import ModId, SaveIdentity, SaveSource, SourceKind
from src.core.load_order import LoadOrder, PriorityDirection, PrioritySetting
from src.core.model import MetadataSignature, ModInfo
from src.core.rules_data import RulesData, parse_rules_data, resolve_rules
from src.core.tiers import Tier
from src.core.validation import Finding, Severity, ValidationContext

WORKSHOP_ROOT = PurePosixPath("C:/Steam/steamapps/workshop/content/262060")
LOCAL_ROOT = PurePosixPath("C:/Games/Darkest Dungeon/mods")
CODE_DIRS = ("heroes", "monsters", "dungeons", "raid", "trinkets", "quirks", "diseases", "upgrades")

# Precedence-space weights (higher wins) shaped like ``TierTable.from_categories`` over the default
# category order: overhaul is the base, unassigned sits above every category, patch above all.
TIER_WEIGHTS: Mapping[str, int] = {
    "overhaul": 0,
    "ui": 100,
    "district": 200,
    "dungeon": 300,
    "quirk": 400,
    "item": 500,
    "enemy": 600,
    "class_patch": 700,
    "class": 800,
    "skin": 900,
    "unassigned": 1000,
    "patch": 1100,
}

# The overlap lists shipped in src/resources/default_rules.json (contract example document).
DEFAULT_IGNORE = ("project.xml", "modfiles.txt", "preview_icon.*", "*.bak")
DEFAULT_MERGE = ("localization/*.string_table.xml",)
DEFAULT_OVERLAP_RULES = RulesData(
    mods=(), overlap_ignore=DEFAULT_IGNORE, overlap_merge=DEFAULT_MERGE
)

_LOAD_AFTER = re.compile(r"load (this|it) after:?", re.IGNORECASE)


def strip_numeric_prefix(folder: str) -> str:
    """Test-side copy of the folder rule: drop leading ``<digits>_`` parts."""
    parts = folder.split("_")
    while parts and parts[0].isdigit():
        parts.pop(0)
    return "_".join(parts) if parts else folder


def normalize_path(raw: str) -> str:
    """Manifest form: forward slashes, no leading ``./`` or ``/``, casefolded."""
    text = raw.replace("\\", "/").casefold()
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def tier(tier_id: str, weight: int | None = None) -> Tier:
    """A ``Tier`` value; builtin ids get their ``TIER_WEIGHTS`` weight, others 1000 unless given."""
    builtin = tier_id in TIER_WEIGHTS
    resolved = TIER_WEIGHTS.get(tier_id, 1000) if weight is None else weight
    return Tier(id=tier_id, weight=resolved, category=None, builtin=builtin)


def _derived_dirs(
    files: frozenset[str],
) -> tuple[frozenset[str], tuple[tuple[str, tuple[str, ...]], ...]]:
    top = frozenset(f.split("/", 1)[0] for f in files if "/" in f)
    code: list[tuple[str, tuple[str, ...]]] = []
    for top_dir in CODE_DIRS:
        prefix = top_dir + "/"
        children = sorted(
            {f.split("/")[1] for f in files if f.startswith(prefix) and f.count("/") >= 2}
        )
        if children:
            code.append((top_dir, tuple(children)))
    return top, tuple(code)


def mod_info(
    key: str,
    *,
    kind: SourceKind = SourceKind.LOCAL,
    title: str | None = None,
    workshop_id: str | None = None,
    files: Iterable[str] = (),
    tags: Iterable[str] = (),
    hints: Iterable[str] = (),
    **overrides: object,
) -> ModInfo:
    """A ``ModInfo`` with sensible defaults; ``overrides`` are applied with ``dataclasses.replace``.

    Workshop mods default to ``workshop_id = key`` (when numeric) and a Steam save identity; local
    mods default to the save identity ``(title, mod_local_source)`` with the title falling
    back to the numeric-prefix-stripped folder name.
    """
    file_set = frozenset(normalize_path(f) for f in files)
    top, code = _derived_dirs(file_set)
    if kind is SourceKind.WORKSHOP:
        resolved_title = key if title is None else title
        wid = (key if key.isdigit() else "") if workshop_id is None else workshop_id
        identity = SaveIdentity(wid or key, SaveSource.STEAM)
        root = WORKSHOP_ROOT
    else:
        resolved_title = strip_numeric_prefix(key) if title is None else title
        wid = "" if workshop_id is None else workshop_id
        identity = SaveIdentity(resolved_title, SaveSource.LOCAL)
        root = LOCAL_ROOT
    path = root / key
    info = ModInfo(
        id=ModId(key),
        source_id="steam_workshop" if kind is SourceKind.WORKSHOP else "local_folder",
        kind=kind,
        path=path,
        root=root,
        title=resolved_title,
        project_title=resolved_title,
        save_identity=identity,
        workshop_id=wid,
        version_label="",
        updated_label="",
        black_reliquary=False,
        tags=tuple(tags),
        top_level_dirs=top,
        code_subdirs=code,
        files=file_set,
        preview_path=None,
        preview_mtime_ns=None,
        load_after_hints=tuple(hints),
        signature=MetadataSignature(
            metadata_path=str(path),
            project_mtime=None,
            localization_signature="",
            workshop_timeupdated="",
        ),
        shadowed=(),
    )
    return dataclasses.replace(info, **overrides) if overrides else info


def workshop_mod(key: str, **kwargs: object) -> ModInfo:
    return mod_info(key, kind=SourceKind.WORKSHOP, **kwargs)  # ty: ignore[invalid-argument-type]


def local_mod(key: str, **kwargs: object) -> ModInfo:
    return mod_info(key, kind=SourceKind.LOCAL, **kwargs)  # ty: ignore[invalid-argument-type]


def _child_text(root: ET.Element, tag: str) -> str:
    for child in root:
        if child.tag.lower() == tag.lower():
            return (child.text or "").strip()
    return ""


def _leaf_tags(root: ET.Element) -> tuple[str, ...]:
    outer = root.find("Tags")
    if outer is None:
        return ()
    return tuple(
        leaf.text.strip() for leaf in outer.findall("Tags") if leaf.text and leaf.text.strip()
    )


def load_after_hints_of(description: str) -> tuple[str, ...]:
    """Bullet lines after a "Load this after:" line, up to the next blank line."""
    hints: list[str] = []
    collecting = False
    for raw in description.splitlines():
        line = raw.strip()
        if not collecting:
            collecting = bool(_LOAD_AFTER.search(line))
            continue
        if not line:
            break
        if line[:1] in {"-", "*", "\u2022"}:
            hints.append(line[1:].strip())
    return tuple(hints)


@dataclasses.dataclass(frozen=True, slots=True)
class SampleFacts:
    title: str
    tags: tuple[str, ...]
    hints: tuple[str, ...]
    files: tuple[str, ...]


def read_sample_mod(folder: Path) -> SampleFacts:
    """Title, leaf tags, load-after hints and manifest of a real sample mod folder."""
    root = ET.fromstring(folder.joinpath("project.xml").read_bytes())
    files = tuple(
        p.relative_to(folder).as_posix()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.parent != folder
    )
    return SampleFacts(
        title=_child_text(root, "Title"),
        tags=_leaf_tags(root),
        hints=load_after_hints_of(_child_text(root, "ItemDescription")),
        files=files,
    )


def sample_patch_mod(
    sample_mods_dir: Path,
    name: str,
    *,
    kind: SourceKind = SourceKind.LOCAL,
    **overrides: object,
) -> ModInfo:
    """A ``ModInfo`` for ``modding/<name>`` (one of the real ``*_swf_compat`` patch mods)."""
    facts = read_sample_mod(sample_mods_dir / name)
    info = mod_info(
        name,
        kind=kind,
        title=facts.title,
        files=facts.files,
        tags=facts.tags,
        hints=facts.hints,
    )
    return dataclasses.replace(info, **overrides) if overrides else info


def load_order(*spec: str) -> LoadOrder:
    """``load_order("a", "-x", "b")``: entries in that order; a leading ``-`` means disabled."""
    entries = tuple(ModId(item.removeprefix("-")) for item in spec)
    enabled = frozenset(ModId(item) for item in spec if not item.startswith("-"))
    return LoadOrder(entries=entries, enabled=enabled)


def rules_json(
    mods: Mapping[str, object] | None = None,
    *,
    overlap: Mapping[str, Sequence[str]] | None = None,
    version: int = 1,
    extra: Mapping[str, object] | None = None,
) -> str:
    """A ``ddmanager.rules`` document as text."""
    doc: dict[str, object] = {"format": "ddmanager.rules", "format_version": version}
    if overlap is not None:
        doc["overlap"] = {k: list(v) for k, v in overlap.items()}
    doc["mods"] = dict(mods or {})
    if extra:
        doc.update(extra)
    return json.dumps(doc, indent=2)


def context(
    order: LoadOrder,
    mods: Iterable[ModInfo],
    *,
    tiers: Mapping[str, str] | None = None,
    rules: RulesData | str | None = None,
    direction: PriorityDirection = PriorityDirection.FIRST_WINS,
    verified: bool = True,
    max_detail_paths: int = 5,
) -> ValidationContext:
    """Build a ``ValidationContext``; ``tiers`` maps mod key -> tier id (default unassigned).

    ``rules`` is a ``RulesData``, a rules-document text (parsed, must produce no ERROR finding) or
    ``None`` for the shipped overlap lists with no mod entries.
    """
    mod_map = {info.id: info for info in mods}
    tier_ids = tiers or {}
    tier_map = {key: tier(tier_ids.get(key, "unassigned")) for key in mod_map}
    data = DEFAULT_OVERLAP_RULES if rules is None else rules
    if isinstance(data, str):
        data, findings = parse_rules_data(data)
        errors = [f for f in findings if f.severity is Severity.ERROR]
        assert not errors, errors
    return ValidationContext.build(
        order=order,
        mods=mod_map,
        tiers=tier_map,
        rules=resolve_rules(data, mod_map),
        priority=PrioritySetting(direction=direction, verified=verified),
        default_tier=tier("unassigned"),
        max_detail_paths=max_detail_paths,
    )


def mentions(finding: Finding, text: str) -> bool:
    """True when ``text`` occurs in the finding's message, params or details (wording-agnostic)."""
    haystacks = [finding.message, *finding.details, *(value for _, value in finding.params)]
    return any(text in hay for hay in haystacks)


def only(findings: Sequence[Finding], rule_id: str | None = None) -> Finding:
    """The single finding (optionally filtered by rule id); fails loudly otherwise."""
    matches = [f for f in findings if rule_id is None or f.rule_id == rule_id]
    assert len(matches) == 1, matches
    return matches[0]


def with_severity(findings: Sequence[Finding], severity: Severity) -> list[Finding]:
    return [f for f in findings if f.severity is severity]
