"""Mod identity: the one place that decides a mod's title, save identity and identity keys.

Covers the month/year and updated labels, the metadata read (with the localization /
internal-code title fallbacks), the save identity and duplicate keys, and the identity values
and category-memory keys.  The text gates live in :mod:`src.core.identity_text` and the
display names in
:mod:`src.core.display`; both are re-exported here for the contract.  Everything is pure; the
clock enters only as ``tz``.
"""

import html
import re
from collections.abc import Sequence
from datetime import datetime, tzinfo
from typing import Final

from src.core.display import (
    display_name,
    display_name_with_suffix,
    display_suffix,
    sort_key,
)
from src.core.identity_text import (
    is_bad_display_title,
    looks_like_numeric_id,
    normalize_mod_identity,
    split_numeric_prefix,
    strip_numeric_prefix,
    text_has_latin,
)
from src.core.ids import SaveIdentity, SaveSource
from src.core.model import MetadataSignature, ModInfo, ModSnapshot, subdirs_of
from src.core.project_xml import (
    ProjectInfo,
    is_black_reliquary_tagged,
    load_after_hints,
    version_label,
)
from src.core.text import WHITESPACE_RE, collapse_whitespace

__all__ = [
    "category_memory_keys",
    "derive_mod_info",
    "display_name",
    "display_name_with_suffix",
    "display_suffix",
    "duplicate_keys",
    "format_month_year",
    "internal_code_title",
    "is_bad_display_title",
    "localization_title",
    "looks_like_numeric_id",
    "mod_identity_values",
    "normalize_mod_identity",
    "project_identity_name",
    "resolve_save_identity",
    "resolve_workshop_id",
    "sort_key",
    "split_numeric_prefix",
    "strip_numeric_prefix",
    "text_has_latin",
    "updated_label",
]

_CODE_SEPARATORS_RE: Final = re.compile(r"[_\-]+")
_CODE_TITLE_TOPS: Final[tuple[str, ...]] = ("heroes", "monsters", "dungeons", "raid")
_MAX_LOCALIZATION_TITLE_LEN: Final = 80

# ------------------------------------------------------------ title fallbacks


def _localization_priority(entry_id: str) -> int | None:
    """Rank of a localization entry id, ``None`` when it is not a name."""
    if entry_id.startswith("hero_class_name_"):
        return 0
    if "class_name" in entry_id:
        return 1
    if "mod_name" in entry_id or "title" in entry_id:
        return 2
    if entry_id.endswith("_name") or "_name_" in entry_id:
        return 3
    return None


def localization_title(entries: Sequence[tuple[str, str]]) -> str | None:
    """The best-ranked short, clean name among ``(entry id, raw text)``.

    Text is stripped, HTML-unescaped and whitespace-collapsed in that order (no second strip,
    as the title rules require); texts that are empty, longer than 80 characters or bad display
    titles are skipped.  The winner is the minimum of ``(priority, len(text), text)``; ``None``
    when nothing qualifies.
    """
    candidates: list[tuple[int, int, str]] = []
    for raw_id, raw_text in entries:
        entry_id = raw_id.lower()
        text = WHITESPACE_RE.sub(" ", html.unescape(raw_text.strip()))
        if not text or len(text) > _MAX_LOCALIZATION_TITLE_LEN or is_bad_display_title(text):
            continue
        priority = _localization_priority(entry_id)
        if priority is not None:
            candidates.append((priority, len(text), text))
    return min(candidates)[2] if candidates else None


def _title_case_code_name(cleaned: str) -> str:
    """Capitalise words; short all-lowercase words become acronyms."""
    words: list[str] = []
    for part in cleaned.split():
        if part.islower() and len(part) <= 3:
            words.append(part.upper())
        else:
            words.append(part[:1].upper() + part[1:])
    return " ".join(words)


def internal_code_title(code_subdirs: Sequence[tuple[str, Sequence[str]]]) -> str | None:
    """Title from the first Latin subfolder of heroes/monsters/dungeons/raid.

    ``None`` when no content directory has a Latin-named child.
    """
    for top in _CODE_TITLE_TOPS:
        for name in sorted(subdirs_of(code_subdirs, top)):
            cleaned = collapse_whitespace(_CODE_SEPARATORS_RE.sub(" ", name))
            if cleaned and text_has_latin(cleaned):
                return _title_case_code_name(cleaned)
    return None


# ---------------------------------------------------------- identity decision


def resolve_workshop_id(
    *, under_workshop: bool, path_workshop_id: str, project: ProjectInfo | None
) -> str:
    """The ``published_file_id`` of a mod.

    Empty unless the folder lies under the workshop path; there, the project's
    ``PublishedFileId`` wins over the id read from the path.  Services look the ACF
    ``timeupdated`` up by this value.
    """
    if not under_workshop:
        return ""
    if project is not None and project.published_file_id:
        return project.published_file_id
    return path_workshop_id


def _project_title_passes(title: str, fallback: str) -> bool:
    """The Latin gate for a project ``<Title>``."""
    return bool(
        title
        and not is_bad_display_title(title)
        and (
            text_has_latin(title) or not text_has_latin(fallback) or looks_like_numeric_id(fallback)
        )
    )


def resolve_save_identity(
    *, folder_key: str, under_workshop: bool, path_workshop_id: str, project: ProjectInfo | None
) -> SaveIdentity:
    """The ``save_name`` / ``save_source`` pair a mod writes into the save.

    Workshop folders write their published id with source ``Steam``; local folders write the
    project title when it passes the gate, else the folder name without numeric prefixes,
    with source ``mod_local_source``.
    """
    fallback = strip_numeric_prefix(folder_key)
    workshop_id = resolve_workshop_id(
        under_workshop=under_workshop, path_workshop_id=path_workshop_id, project=project
    )
    if under_workshop and workshop_id:
        return SaveIdentity(workshop_id, SaveSource.STEAM)
    name = fallback
    if project is not None and _project_title_passes(project.title, fallback):
        name = project.title
    return SaveIdentity(name or fallback, SaveSource.LOCAL)


def _resolve_title(snapshot: ModSnapshot, fallback: str) -> str:
    """The title chain: project title, localization name, code name."""
    project = snapshot.project
    title = fallback
    if project is not None and _project_title_passes(project.title, fallback):
        title = project.title
    if title != fallback and text_has_latin(title):
        return title
    localized = localization_title(snapshot.localization_entries)
    if localized and text_has_latin(localized) and not is_bad_display_title(localized):
        return localized
    code_title = internal_code_title(snapshot.code_subdirs)
    if looks_like_numeric_id(fallback) and code_title and not text_has_latin(title):
        return code_title
    return title


def format_month_year(timestamp: str | float, tz: tzinfo) -> str:
    """``MM/YY`` in ``tz``; ``""`` when the value is not a timestamp."""
    try:
        moment = datetime.fromtimestamp(float(timestamp), tz)
    except ValueError, OverflowError, OSError:
        return ""
    return moment.strftime("%m/%y")


def updated_label(
    *, acf_timeupdated: str, newest_mtime: float | None, project_mtime: float | None, tz: tzinfo
) -> str:
    """Workshop update time, else newest file, else project.xml mtime."""
    candidates: list[str | float] = []
    if acf_timeupdated:
        candidates.append(acf_timeupdated)
    if newest_mtime is not None:
        candidates.append(newest_mtime)
    if project_mtime is not None:
        candidates.append(project_mtime)
    for candidate in candidates:
        label = format_month_year(candidate, tz)
        if label:
            return label
    return ""


def _signature(snapshot: ModSnapshot) -> MetadataSignature:
    """The cache key of the NEW app (see :class:`MetadataSignature`)."""
    return MetadataSignature(
        metadata_path=str(snapshot.path),
        project_mtime=snapshot.project_mtime,
        localization_signature=snapshot.localization_signature,
        workshop_timeupdated=snapshot.acf_timeupdated,
        content_roots_mtime_ns=snapshot.content_roots_mtime_ns,
    )


def derive_mod_info(snapshot: ModSnapshot, *, tz: tzinfo) -> ModInfo:
    """Turn disk facts into a ``ModInfo`` from the project, localization and workshop facts."""
    project = snapshot.project
    fallback = strip_numeric_prefix(snapshot.key)
    workshop_id = resolve_workshop_id(
        under_workshop=snapshot.under_workshop,
        path_workshop_id=snapshot.path_workshop_id,
        project=project,
    )
    return ModInfo(
        id=snapshot.key,
        source_id=snapshot.source_id,
        kind=snapshot.kind,
        path=snapshot.path,
        root=snapshot.root,
        title=_resolve_title(snapshot, fallback),
        project_title=None if project is None else project.title,
        save_identity=resolve_save_identity(
            folder_key=snapshot.key,
            under_workshop=snapshot.under_workshop,
            path_workshop_id=snapshot.path_workshop_id,
            project=project,
        ),
        workshop_id=workshop_id,
        version_label=""
        if project is None
        else version_label(project.version_major, project.version_minor),
        updated_label=updated_label(
            acf_timeupdated=snapshot.acf_timeupdated,
            newest_mtime=snapshot.newest_mtime,
            project_mtime=snapshot.project_mtime,
            tz=tz,
        ),
        black_reliquary=project is not None and is_black_reliquary_tagged(project.tags),
        tags=() if project is None else project.tags,
        top_level_dirs=snapshot.top_level_dirs,
        code_subdirs=snapshot.code_subdirs,
        files=snapshot.files,
        preview_path=snapshot.preview_path,
        preview_mtime_ns=snapshot.preview_mtime_ns,
        load_after_hints=() if project is None else load_after_hints(project.description),
        signature=_signature(snapshot),
        project_published_file_id="" if project is None else project.published_file_id,
    )


# ------------------------------------------------------------- identity keys


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    """Order-preserving de-duplication that also drops empty strings."""
    return tuple(dict.fromkeys(value for value in values if value))


def duplicate_keys(info: ModInfo) -> tuple[str, ...]:
    """over ``ModInfo`` fields.

    Sources in order: workshop id, title, save name, folder without numeric prefixes, folder.
    Each normalised value becomes ``id:<digits>`` or, when at least five characters,
    ``name:<text>``.
    """
    keys: list[str] = []
    for value in (
        info.workshop_id,
        info.title,
        info.save_identity.name,
        strip_numeric_prefix(info.id),
        info.id,
    ):
        normalized = normalize_mod_identity(value)
        if not normalized:
            continue
        if normalized.isdigit():
            keys.append(f"id:{normalized}")
        elif len(normalized) >= 5:
            keys.append(f"name:{normalized}")
    return _unique(keys)


def project_identity_name(info: ModInfo) -> str:
    """Published id, else project title, else workshop id, else save name."""
    fallback = strip_numeric_prefix(info.id)
    if info.project_title is None:
        return info.workshop_id or fallback
    return info.project_published_file_id or info.project_title or info.workshop_id or fallback


def mod_identity_values(info: ModInfo) -> tuple[str, ...]:
    """Every string that has identified this mod, de-duplicated."""
    return _unique(
        (
            info.workshop_id,
            info.save_identity.name,
            info.title,
            project_identity_name(info),
            strip_numeric_prefix(info.id),
            info.id,
        )
    )


def category_memory_keys(info: ModInfo) -> tuple[str, ...]:
    """Each identity value raw and as ``norm:<normalised>``, de-duplicated."""
    keys: list[str] = []
    for identity in mod_identity_values(info):
        keys.append(identity)
        normalized = normalize_mod_identity(identity)
        if normalized:
            keys.append(f"norm:{normalized}")
    return _unique(keys)
