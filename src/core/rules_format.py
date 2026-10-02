"""The community rules file (``"ddmanager.rules"`` v1, JSON): parse, dump and merge.

A rules document declares, per mod reference, a tier and relations to other mods
(``requires``, ``load_after``, ``patch_for``, ``incompatible``, ``compatible_with``) plus two
lists of file patterns that change how :mod:`src.rules.file_overlap` treats a path.  Applying a
document to the installed mods is :mod:`src.core.rules_resolve`'s job.

Mod references (``ModRef`` strings) are one of::

    steam:<PublishedFileId>                 a Workshop mod, by the id written into the save
    local:<normalize_mod_identity(save name)>   a local mod, by its normalized save name
    title:<normalized title>                any mod whose normalized display title matches
    key:<folder>                            the exact folder basename (user files only)

Parsing is total: it never raises, and every problem becomes a ``Finding`` whose rule id starts
with ``rules.``.  A document with ``format_version`` above the supported one yields
:data:`EMPTY_RULES` and one ERROR finding; a malformed entry yields WARNING findings and is
skipped, so a typo never silently changes precedence.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from src.core.findings import Finding
from src.core.identity_text import normalize_mod_identity
from src.core.ids import parse_mod_id
from src.core.json_values import TypedFields

FORMAT: Final = "ddmanager.rules"
FORMAT_VERSION: Final = 1

REF_KINDS: Final = ("steam", "local", "title", "key")
TOP_LEVEL_KEYS: Final = frozenset({"format", "format_version", "overlap", "mods"})
OVERLAP_KEYS: Final = frozenset({"ignore", "merge"})
ENTRY_KEYS: Final = frozenset(
    {"tier", "requires", "load_after", "patch_for", "incompatible", "compatible_with", "title_hint"}
)
INCOMPATIBLE_KEYS: Final = frozenset({"ref", "reason"})
_REF_LIST_KEYS: Final = ("requires", "load_after", "patch_for", "compatible_with")


@dataclass(frozen=True, slots=True)
class ModRule:
    """One ``mods`` entry of a rules document (all refs canonical, see :func:`canonical_ref`)."""

    ref: str
    tier: str | None = None
    requires: tuple[str, ...] = ()
    load_after: tuple[str, ...] = ()
    patch_for: tuple[str, ...] = ()
    incompatible: tuple[tuple[str, str], ...] = ()
    compatible_with: tuple[str, ...] = ()
    title_hint: str = ""


@dataclass(frozen=True, slots=True)
class RulesData:
    """A parsed rules document."""

    mods: tuple[ModRule, ...] = ()
    overlap_ignore: tuple[str, ...] = ()
    overlap_merge: tuple[str, ...] = ()


EMPTY_RULES: Final = RulesData()


# ---------------------------------------------------------------- refs


def canonical_ref(raw: object, *, allow_key_refs: bool = True) -> str | None:
    """The canonical form of a ModRef, or ``None`` when ``raw`` is not a valid reference.

    ``local:``/``title:`` values are normalized with ``normalize_mod_identity`` so two spellings
    of the same title merge to one ref; ``steam:`` values must be digits; ``key:`` values must
    be valid mod ids and are only accepted when ``allow_key_refs`` is set.
    """
    if not isinstance(raw, str):
        return None
    kind, sep, value = raw.partition(":")
    kind = kind.strip().lower()
    if not sep or kind not in REF_KINDS or (kind == "key" and not allow_key_refs):
        return None
    canonical = _canonical_value(kind, value.strip())
    return f"{kind}:{canonical}" if canonical else None


def _canonical_value(kind: str, value: str) -> str:
    if kind in {"local", "title"}:
        return normalize_mod_identity(value)
    if kind == "steam":
        return value if value.isdigit() else ""
    try:
        return parse_mod_id(value)
    except ValueError:
        return ""


# ---------------------------------------------------------------- parsing


def _warning(code: str, message: str, **params: str) -> Finding:
    return Finding.warning(f"rules.{code}", message, **params)


def _error(code: str, message: str, **params: str) -> Finding:
    return Finding.error(f"rules.{code}", message, **params)


def parse_rules_data(text: str, *, allow_key_refs: bool = True) -> tuple[RulesData, list[Finding]]:
    """Parse a rules document; never raises (problems come back as ``rules.*`` findings)."""
    findings: list[Finding] = []
    root = _load_root(text, findings)
    if root is None or not _check_header(root, findings):
        return EMPTY_RULES, findings
    _warn_unknown_keys(root, TOP_LEVEL_KEYS, "document", findings)
    ignore, merge = _parse_overlap(root.get("overlap"), findings)
    mods = _parse_mods(root.get("mods"), allow_key_refs, findings)
    return RulesData(mods=mods, overlap_ignore=ignore, overlap_merge=merge), findings


def _load_root(text: str, findings: list[Finding]) -> dict[str, object] | None:
    try:
        root = json.loads(text)
    except (ValueError, RecursionError) as exc:
        findings.append(_error("invalid_json", f"Rules file is not valid JSON: {exc}"))
        return None
    if not isinstance(root, dict):
        findings.append(_error("not_an_object", "Rules file must be a JSON object."))
        return None
    return root


def _check_header(root: Mapping[str, object], findings: list[Finding]) -> bool:
    if root.get("format") != FORMAT:
        message = f"Rules file format must be {FORMAT!r}, got {root.get('format')!r}."
        findings.append(_error("wrong_format", message))
        return False
    version = root.get("format_version", FORMAT_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        findings.append(_error("bad_version", f"Rules file format_version {version!r} is invalid."))
        return False
    if version > FORMAT_VERSION:
        findings.append(
            _error(
                "newer_version",
                f"Rules file format_version {version} was made by a newer DD Manager "
                f"(this one reads version {FORMAT_VERSION}).",
                version=str(version),
            )
        )
        return False
    return True


def _warn_unknown_keys(
    obj: Mapping[str, object], known: frozenset[str], where: str, findings: list[Finding]
) -> None:
    findings.extend(
        _warning("unknown_field", f"Unknown field {key!r} in {where}.", field=key, where=where)
        for key in obj
        if key not in known
    )


def _parse_overlap(
    value: object, findings: list[Finding]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if value is None:
        return (), ()
    if not isinstance(value, dict):
        findings.append(_warning("bad_overlap", "'overlap' must be an object; ignored."))
        return (), ()
    _warn_unknown_keys(value, OVERLAP_KEYS, "overlap", findings)
    return (
        _pattern_list(value.get("ignore"), "overlap.ignore", findings),
        _pattern_list(value.get("merge"), "overlap.merge", findings),
    )


def _pattern_list(value: object, where: str, findings: list[Finding]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        findings.append(_warning("bad_list", f"'{where}' must be a list of patterns; ignored."))
        return ()
    patterns: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            patterns.append(item.strip())
        else:
            findings.append(_warning("bad_pattern", f"'{where}' item {item!r} is not a pattern."))
    return tuple(dict.fromkeys(patterns))


def _parse_mods(
    value: object, allow_key_refs: bool, findings: list[Finding]
) -> tuple[ModRule, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        findings.append(_warning("bad_mods", "'mods' must be an object; ignored."))
        return ()
    rules: dict[str, ModRule] = {}
    for raw_ref, raw_entry in value.items():
        ref = canonical_ref(raw_ref, allow_key_refs=allow_key_refs)
        if ref is None:
            message = f"Invalid mod reference {raw_ref!r}; entry skipped."
            findings.append(_warning("bad_ref", message))
            continue
        if ref in rules:
            message = f"Duplicate mod reference {ref!r}; last wins."
            findings.append(_warning("duplicate_ref", message))
        rule = _parse_entry(ref, raw_entry, allow_key_refs, findings)
        if rule is not None:
            rules[ref] = rule
    return tuple(rules.values())


@dataclass(slots=True)
class _EntryReader:
    """Reads one ``mods`` entry, collecting every problem so the caller can skip the entry.

    The typed field access is :class:`TypedFields`; this class adds the reference-specific
    readers on top and turns every type report into a problem line.
    """

    ref: str
    raw: Mapping[str, object]
    allow_key_refs: bool
    problems: list[str] = field(default_factory=list)
    fields: TypedFields = field(init=False)

    def __post_init__(self) -> None:
        self.fields = TypedFields(self.raw, self._report)

    def _report(self, key: str, expected: str) -> None:
        self.problems.append(f"{key!r} must be {expected}")

    def check_keys(self) -> None:
        self.problems.extend(f"unknown field {key!r}" for key in self.raw if key not in ENTRY_KEYS)

    def string(self, key: str) -> str:
        return self.fields.str_(key).strip()

    def refs(self, key: str) -> tuple[str, ...]:
        refs = (self.ref_of(key, item) for item in self.fields.list_(key))
        return tuple(dict.fromkeys(ref for ref in refs if ref))

    def ref_of(self, key: str, item: object) -> str:
        ref = canonical_ref(item, allow_key_refs=self.allow_key_refs)
        if ref is None:
            self.problems.append(f"{key!r} has an invalid mod reference {item!r}")
            return ""
        return ref

    def incompatible(self) -> tuple[tuple[str, str], ...]:
        pairs = (self._incompatible_item(item) for item in self.fields.list_("incompatible"))
        return tuple(pair for pair in pairs if pair is not None)

    def _incompatible_item(self, item: object) -> tuple[str, str] | None:
        if isinstance(item, str):
            ref = self.ref_of("incompatible", item)
            return (ref, "") if ref else None
        if not isinstance(item, dict):
            self.problems.append(f"'incompatible' item {item!r} must be a reference or an object")
            return None
        self.problems.extend(
            f"unknown field {key!r} in 'incompatible' item"
            for key in item
            if key not in INCOMPATIBLE_KEYS
        )
        reason = item.get("reason", "")
        if not isinstance(reason, str):
            self.problems.append("'incompatible' reason must be a string")
            reason = ""
        ref = self.ref_of("incompatible", item.get("ref"))
        return (ref, reason.strip()) if ref else None


def _parse_entry(
    ref: str, raw: object, allow_key_refs: bool, findings: list[Finding]
) -> ModRule | None:
    if not isinstance(raw, dict):
        findings.append(_warning("bad_entry", f"{ref}: entry must be an object; skipped.", ref=ref))
        return None
    reader = _EntryReader(ref, raw, allow_key_refs)
    reader.check_keys()
    rule = ModRule(
        ref=ref,
        tier=reader.string("tier") or None,
        requires=reader.refs("requires"),
        load_after=reader.refs("load_after"),
        patch_for=reader.refs("patch_for"),
        incompatible=reader.incompatible(),
        compatible_with=reader.refs("compatible_with"),
        title_hint=reader.string("title_hint"),
    )
    if reader.problems:
        findings.extend(
            _warning("bad_entry", f"{ref}: {problem}; entry skipped.", ref=ref)
            for problem in reader.problems
        )
        return None
    return rule


# ---------------------------------------------------------------- dump / merge


def dump_rules_data(rules: RulesData) -> str:
    """Serialize as the canonical JSON document (``parse_rules_data`` round-trips it)."""
    document = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "overlap": {"ignore": list(rules.overlap_ignore), "merge": list(rules.overlap_merge)},
        "mods": {rule.ref: _entry_json(rule) for rule in rules.mods},
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _entry_json(rule: ModRule) -> dict[str, object]:
    entry: dict[str, object] = {}
    if rule.title_hint:
        entry["title_hint"] = rule.title_hint
    if rule.tier:
        entry["tier"] = rule.tier
    for key in _REF_LIST_KEYS:
        refs: tuple[str, ...] = getattr(rule, key)
        if refs:
            entry[key] = list(refs)
    if rule.incompatible:
        entry["incompatible"] = [
            {"ref": ref, "reason": reason} for ref, reason in rule.incompatible
        ]
    return entry


def merge_rules(default: RulesData, user: RulesData) -> RulesData:
    """Per ref the user entry replaces the default one wholesale; overlap lists are unioned."""
    by_ref = {rule.ref: rule for rule in default.mods}
    by_ref.update({rule.ref: rule for rule in user.mods})
    return RulesData(
        mods=tuple(by_ref.values()),
        overlap_ignore=tuple(dict.fromkeys((*default.overlap_ignore, *user.overlap_ignore))),
        overlap_merge=tuple(dict.fromkeys((*default.overlap_merge, *user.overlap_merge))),
    )
