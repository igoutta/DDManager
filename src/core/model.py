"""Disk facts about one mod: what the services gather (``ModSnapshot``) and what the domain
derives from it (``ModInfo``), plus the ``modfiles.txt`` manifest normalisation.

No identity decisions live here; ``src.core.identity.derive_mod_info`` is the single place
that turns a snapshot into a ``ModInfo``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath

from src.core.ids import ModId, SaveIdentity, SourceKind
from src.core.project_xml import ProjectInfo


@dataclass(frozen=True, slots=True)
class MetadataSignature:
    """The metadata cache key.

    Four identifying fields plus the content-root stamp; ``workshop_timeupdated``
    is looked up by the RESOLVED workshop id (``identity.resolve_workshop_id``: the project's
    ``PublishedFileId`` first), not by the path-derived id.  A ``workshop_timeupdated`` value
    cached by DD Manager 0.2.x (path-derived id) therefore must not be compared with it; such a
    stale cache entry simply misses once.
    """

    metadata_path: str
    project_mtime: float | None
    localization_signature: str
    """``"<xml count>:<newest mtime>"`` of ``localization/*.xml`` or ``""``."""
    workshop_timeupdated: str
    """``ModSnapshot.acf_timeupdated``: the ACF ``timeupdated`` for the resolved workshop id."""
    content_roots_mtime_ns: int | None = None
    """Newest ``st_mtime_ns`` of the folder and its direct subdirectories: a file added to or
    removed from a content root changes it.  ``None`` in cache entries that predate it and when
    unknown."""


@dataclass(frozen=True, slots=True)
class ModSnapshot:
    """Everything the filesystem says about a mod folder; built by services, read by core."""

    key: ModId
    source_id: str
    kind: SourceKind
    path: PurePath
    root: PurePath
    under_workshop: bool
    """True when ``path`` lies under ``steamapps/workshop/content/262060``."""
    path_workshop_id: str
    """Workshop id derived from the folder name/path, ``""`` if none."""
    project: ProjectInfo | None
    localization_entries: tuple[tuple[str, str], ...]
    """``(entry id, raw text)`` pairs from ``localization/*.xml`` ``<entry id=...>`` elements."""
    top_level_dirs: frozenset[str]
    """Casefolded names of the direct subdirectories."""
    code_subdirs: tuple[tuple[str, tuple[str, ...]], ...]
    """``(top dir, sorted child dir names)`` for the game-content tops, original case."""
    files: frozenset[str]
    """Casefolded posix relative paths of the manifest; root-level files excluded."""
    newest_mtime: float | None
    project_mtime: float | None
    localization_signature: str
    acf_timeupdated: str
    """ACF ``timeupdated`` looked up by ``identity.resolve_workshop_id(...)``; ``""`` unknown.

    Feeds both the updated label and :class:`MetadataSignature`.
    """
    preview_path: PurePath | None
    preview_mtime_ns: int | None
    content_roots_mtime_ns: int | None = None
    """See :attr:`MetadataSignature.content_roots_mtime_ns`."""


@dataclass(frozen=True, slots=True)
class ModInfo:
    """Disk facts only: no tier, category, nickname or enabled flag lives here."""

    id: ModId
    source_id: str
    kind: SourceKind
    path: PurePath
    root: PurePath
    title: str
    """Display title after the title chain (``identity.derive_mod_info``)."""
    project_title: str | None
    """Raw project ``<Title>`` (possibly ``""``), ``None`` when there is no parsable project.xml."""
    save_identity: SaveIdentity
    workshop_id: str
    """The ``published_file_id``: set only for folders under the workshop path."""
    version_label: str
    """``"M.m"`` or ``""``."""
    updated_label: str
    """``"MM/YY"`` or ``""``."""
    black_reliquary: bool
    tags: tuple[str, ...]
    """``ProjectInfo.tags`` (the classifier tags)."""
    top_level_dirs: frozenset[str]
    code_subdirs: tuple[tuple[str, tuple[str, ...]], ...]
    files: frozenset[str]
    preview_path: PurePath | None
    preview_mtime_ns: int | None
    load_after_hints: tuple[str, ...]
    signature: MetadataSignature
    shadowed: tuple[PurePath, ...] = ()
    project_published_file_id: str = ""
    """Raw project ``<PublishedFileId>`` regardless of location (the duplicate keys need it)."""

    def subdirs_of(self, top: str) -> tuple[str, ...]:
        """Child directory names recorded under ``top`` (case-insensitive), ``()`` if none."""
        return subdirs_of(self.code_subdirs, top)


def subdirs_of(code_subdirs: Sequence[tuple[str, Sequence[str]]], top: str) -> tuple[str, ...]:
    """The children recorded under ``top`` in a ``code_subdirs`` table (case-insensitive)."""
    wanted = top.casefold()
    for name, children in code_subdirs:
        if name.casefold() == wanted:
            return tuple(children)
    return ()


def normalize_manifest_path(raw: str) -> str | None:
    """Canonical casefolded posix form of a manifest line, or ``None`` when it is not a file path.

    Backslashes become ``/``; ``./`` prefixes, leading ``/`` and ``.`` segments are dropped;
    ``..`` segments, empty results and trailing ``/`` (directories) are rejected.  Each segment
    is stripped of surrounding whitespace so the result is a fixed point of this function.
    """
    text = raw.strip().replace("\\", "/")
    if not text or text.endswith("/"):
        return None
    segments = [
        stripped for segment in text.split("/") if (stripped := segment.strip()) not in ("", ".")
    ]
    if not segments or ".." in segments:
        return None
    return "/".join(segments).casefold()


def parse_modfiles_txt(text: str) -> frozenset[str]:
    """Normalised entries of a ``modfiles.txt``; blank and invalid lines are ignored."""
    paths: set[str] = set()
    for line in text.splitlines():
        normalized = normalize_manifest_path(line)
        if normalized is not None:
            paths.add(normalized)
    return frozenset(paths)
