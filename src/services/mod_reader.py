"""All per-mod-folder I/O: one ``project.xml`` parse, one directory walk, one localization pass.

Everything the domain needs to know about a mod folder is gathered into a ``ModSnapshot``;
``src.core.identity.derive_mod_info`` then decides titles and identities from it.  Ports the I/O
halves of ``dd2.py:3358-3381`` (localization signature), ``3432-3446`` (newest file),
``3477-3617`` (project/localization reading) and ``4607-4638`` (preview icon).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.core.identity import resolve_workshop_id
from src.core.ids import ModId, SourceKind
from src.core.model import MetadataSignature, ModSnapshot, normalize_manifest_path
from src.core.project_xml import (
    ProjectInfo,
    localization_entries,
    parse_project,
    parse_xml_forgiving,
)
from src.services.sources import ModLocation, ReadContext
from src.services.steam_locations import is_workshop_content_path, workshop_id_for_folder

log = logging.getLogger(__name__)

CODE_TOPS = ("heroes", "monsters", "dungeons", "raid", "trinkets", "quirks", "diseases", "upgrades")
_DEFAULT_PREVIEWS = ("preview_icon.png", "preview_icon.gif", "preview_icon.jpg")


def read_project_bytes(path: Path) -> bytes | None:
    """Raw ``<path>/project.xml``, ``None`` when it is missing or unreadable."""
    try:
        return (path / "project.xml").read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.debug("cannot read project.xml of %s: %s", path, exc)
        return None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def content_roots_mtime_ns(path: Path) -> int | None:
    """Newest ``st_mtime_ns`` of ``path`` and its direct subdirectories, ``None`` if unreadable.

    A directory's mtime changes when an entry is created, deleted or renamed directly in it, so
    this stamp notices files added to or removed from a content root without walking the tree.
    """
    try:
        stamps = [path.stat().st_mtime_ns]
        stamps.extend(
            child.stat().st_mtime_ns
            for child in path.iterdir()
            if child.is_dir(follow_symlinks=False)
        )
    except OSError as exc:
        log.debug("cannot stat the content roots of %s: %s", path, exc)
        return None
    return max(stamps)


@dataclass(slots=True)
class _Walk:
    """What one pass over a mod folder collected."""

    top_dirs: list[str] = field(default_factory=list)
    code_dirs: dict[str, list[str]] = field(default_factory=dict)
    files: set[str] = field(default_factory=set)
    newest: float | None = None
    root_error: OSError | None = None


def _note_files(walk: _Walk, directory: Path, rel_parts: tuple[str, ...], names: list[str]) -> None:
    for name in names:
        mtime = _mtime(directory / name)
        if mtime is not None and (walk.newest is None or mtime > walk.newest):
            walk.newest = mtime
        if rel_parts:
            normalized = normalize_manifest_path("/".join((*rel_parts, name)))
            if normalized is not None:
                walk.files.add(normalized)


def _walk_folder(path: Path) -> _Walk:
    """``dd2.py:3432-3446`` newest mtime plus the file manifest and directory facts."""
    walk = _Walk()

    def on_error(exc: OSError) -> None:
        if exc.filename is not None and Path(exc.filename) == path:
            walk.root_error = exc
        else:
            log.debug("walk of %s skipped %s: %s", path, exc.filename, exc)

    for directory, dirs, names in path.walk(on_error=on_error, follow_symlinks=False):
        rel_parts = directory.relative_to(path).parts
        if not rel_parts:
            walk.top_dirs = list(dirs)
        elif len(rel_parts) == 1 and rel_parts[0].casefold() in CODE_TOPS:
            walk.code_dirs[rel_parts[0].casefold()] = sorted(dirs)
        _note_files(walk, directory, rel_parts, names)
    if walk.root_error is not None:
        raise walk.root_error
    return walk


def _read_localization(path: Path, *, deep: bool) -> tuple[tuple[tuple[str, str], ...], str]:
    """Entry pairs (``dd2.py:3542-3560``) and the ``"count:int(newest)"`` signature."""
    directory = path / "localization"
    try:
        names = sorted(entry.name for entry in directory.iterdir())
    except OSError:
        return (), ""
    xml_names = [name for name in names if name.lower().endswith(".xml")]
    if not xml_names:
        return (), ""
    newest = max((_mtime(directory / name) or 0.0 for name in xml_names), default=0.0)
    entries: list[tuple[str, str]] = []
    for name in xml_names if deep else ():
        entries.extend(_parse_localization_file(directory / name))
    return tuple(entries), f"{len(xml_names)}:{int(newest)}"


def _parse_localization_file(file: Path) -> tuple[tuple[str, str], ...]:
    try:
        root = parse_xml_forgiving(file.read_bytes())
    except OSError as exc:
        log.debug("cannot read localization file %s: %s", file, exc)
        return ()
    return () if root is None else localization_entries(root)


def _declared_preview(project: ProjectInfo | None) -> list[str]:
    if project is None or not project.preview_icon_file:
        return []
    declared = Path(project.preview_icon_file)
    if declared.is_absolute() or ".." in declared.parts:
        return []
    return [project.preview_icon_file]


def _find_preview(path: Path, project: ProjectInfo | None) -> Path | None:
    """The declared icon, else ``preview_icon.png/.gif/.jpg`` (``dd2.py:4607-4638``).

    The declared icon is checked first (``dd2.py`` only did so after the three defaults failed).
    """
    for name in (*_declared_preview(project), *_DEFAULT_PREVIEWS):
        candidate = path / name
        if candidate.is_file():
            return candidate
    return None


def _preview_mtime_ns(preview: Path | None) -> int | None:
    if preview is None:
        return None
    try:
        return preview.stat().st_mtime_ns
    except OSError:
        return None


def _code_subdirs(walk: _Walk) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((top, tuple(walk.code_dirs[top])) for top in CODE_TOPS if top in walk.code_dirs)


def snapshot_mod_folder(
    path: Path,
    *,
    root: Path,
    source_id: str,
    kind: SourceKind,
    under_workshop: bool,
    workshop_id: str,
    ctx: ReadContext,
) -> ModSnapshot:
    """Gather the disk facts of one mod folder; ``OSError`` when the folder itself is unreadable."""
    walk = _walk_folder(path)
    project_bytes = read_project_bytes(path)
    project = None if project_bytes is None else parse_project(project_bytes)
    entries, signature = _read_localization(path, deep=ctx.deep)
    resolved = resolve_workshop_id(
        under_workshop=under_workshop, path_workshop_id=workshop_id, project=project
    )
    preview = _find_preview(path, project)
    return ModSnapshot(
        key=ModId(path.name),
        source_id=source_id,
        kind=kind,
        path=path,
        root=root,
        under_workshop=under_workshop,
        path_workshop_id=workshop_id,
        project=project,
        localization_entries=entries,
        top_level_dirs=frozenset(name.casefold() for name in walk.top_dirs),
        code_subdirs=_code_subdirs(walk),
        files=frozenset(walk.files),
        newest_mtime=walk.newest,
        project_mtime=_mtime(path / "project.xml") if project_bytes is not None else None,
        localization_signature=signature,
        acf_timeupdated=ctx.acf_times.get(resolved, "") if resolved else "",
        preview_path=preview,
        preview_mtime_ns=_preview_mtime_ns(preview),
        content_roots_mtime_ns=content_roots_mtime_ns(path),
    )


def signature_of(location: ModLocation, ctx: ReadContext) -> MetadataSignature:
    """The metadata-cache key of a folder from stats and ``project.xml`` alone (no walk).

    Equals the ``signature`` of the ``ModInfo`` that :func:`snapshot_mod_folder` leads to for
    the same folder state, so ``MetadataCache.lookup`` can decide freshness before any reading:
    a workshop root (``steamapps/workshop/content/262060``) is read as the Steam source does,
    anything else as the local source does.  ``project.xml`` is parsed only under the workshop,
    where the resolved id selects the ACF ``timeupdated``.
    """
    path = location.path
    under_workshop = is_workshop_content_path(path)
    project_bytes = read_project_bytes(path)
    project = parse_project(project_bytes) if under_workshop and project_bytes else None
    resolved = resolve_workshop_id(
        under_workshop=under_workshop,
        path_workshop_id=workshop_id_for_folder(path, under_workshop=under_workshop),
        project=project,
    )
    return MetadataSignature(
        metadata_path=str(path),
        project_mtime=_mtime(path / "project.xml") if project_bytes is not None else None,
        localization_signature=_read_localization(path, deep=False)[1],
        workshop_timeupdated=ctx.acf_times.get(resolved, "") if resolved else "",
        content_roots_mtime_ns=content_roots_mtime_ns(path),
    )
