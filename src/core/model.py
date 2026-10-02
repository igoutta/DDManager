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
    """The NEW app's metadata cache key, shaped like ``dd2.py:3383-3404``.

    Same four fields as the legacy ``metadata_signature_for_mod``, but ``workshop_timeupdated``
    is looked up by the RESOLVED workshop id (``identity.resolve_workshop_id``: the project's
    ``PublishedFileId`` first) while the legacy keyed it by the path-derived id
    (``workshop_id_for_mod``, called at ``dd2.py:3482``).  It therefore must not be compared with
    a legacy ``metadata[*].workshop_timeupdated`` value; a stale legacy cache simply misses once.
    """

    metadata_path: str
    project_mtime: float | None
    localization_signature: str
    """``"<xml count>:<newest mtime>"`` of ``localization/*.xml`` or ``""`` (``dd2.py:3358``)."""
    workshop_timeupdated: str
    """``ModSnapshot.acf_timeupdated``: the ACF ``timeupdated`` for the resolved workshop id."""


@dataclass(frozen=True, slots=True)
class ModSnapshot:
    """Everything the filesystem says about a mod folder; built by services, read by core."""

    key: ModId
    source_id: str
    kind: SourceKind
    path: PurePath
    root: PurePath
    under_workshop: bool
    """True when ``path`` lies under ``steamapps/workshop/content/262060`` (``paths.py:14``)."""
    path_workshop_id: str
    """Workshop id derived from the folder name/path (``dd2.py:3968-3985``), ``""`` if none."""
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

    Feeds both the updated label (``dd2.py:3448-3473``) and :class:`MetadataSignature`.
    """
    preview_path: PurePath | None
    preview_mtime_ns: int | None


@dataclass(frozen=True, slots=True)
class ModInfo:
    """Disk facts only: no tier, category, nickname or enabled flag lives here."""

    id: ModId
    source_id: str
    kind: SourceKind
    path: PurePath
    root: PurePath
    title: str
    """Display title after the legacy chain (``identity.derive_mod_info``)."""
    project_title: str | None
    """Raw project ``<Title>`` (possibly ``""``), ``None`` when there is no parsable project.xml."""
    save_identity: SaveIdentity
    workshop_id: str
    """The legacy ``published_file_id``: set only for folders under the workshop path."""
    version_label: str
    """``"M.m"`` or ``""``."""
    updated_label: str
    """``"MM/YY"`` or ``""``."""
    black_reliquary: bool
    tags: tuple[str, ...]
    """``ProjectInfo.legacy_tags`` (classifier parity)."""
    top_level_dirs: frozenset[str]
    code_subdirs: tuple[tuple[str, tuple[str, ...]], ...]
    files: frozenset[str]
    preview_path: PurePath | None
    preview_mtime_ns: int | None
    load_after_hints: tuple[str, ...]
    signature: MetadataSignature
    shadowed: tuple[PurePath, ...] = ()
    project_published_file_id: str = ""
    """Raw project ``<PublishedFileId>`` regardless of location (``dd2.py:4063-4081`` needs it)."""

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
