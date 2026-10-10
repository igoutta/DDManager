"""Synthetic mod folders shared by the identity/classify goldens, their generator and the tests.

``CASES`` describes small mod folders (project.xml, localization, code directories, mtimes) that
exercise the title chain of ``derive_mod_info``: project title, localization fallback, internal
code title, numeric folder names, Workshop ids, encodings and version labels.  ``materialize``
writes one under a temp root, ``snapshot_from_dir`` reads it back into the contract's
``ModSnapshot`` with a small test-side reader (the services layer does this in the app), and
``identity_record`` / ``nickname_record`` are the shapes the identity goldens freeze.

Timestamps are mid-month noon UTC so ``%m/%y`` labels are the same in any zone within UTC+-12.
"""

import dataclasses
import hashlib
import html
import json
import os
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.model import ModInfo, ModSnapshot

STEAM_APP_ID = "262060"
WORKSHOP_PARTS = ("steamapps", "workshop", "content", STEAM_APP_ID)
CODE_DIRS = ("heroes", "monsters", "dungeons", "raid", "trinkets", "quirks", "diseases", "upgrades")

MID_MARCH = 1710504000  # 2024-03-15 12:00 UTC -> "03/24"
MID_MAY = 1715774400  # 2024-05-15 12:00 UTC -> "05/24"
MID_JULY = 1721044800  # 2024-07-15 12:00 UTC -> "07/24"
ACF_MID_NOV = "1731672000"  # 2024-11-15 12:00 UTC -> "11/24"


def project_xml(
    title: str | None = "Sample Mod",
    *,
    published_id: str | None = None,
    major: str | None = "1",
    minor: str | None = "0",
    tags: Iterable[str] = (),
    description: str = "",
    preview: str = "",
) -> str:
    """A project.xml text in the Workshop uploader's shape (leaf <Tags> inside outer <Tags>)."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<project>"]
    if preview:
        lines.append(f"\t<PreviewIconFile>{preview}</PreviewIconFile>")
    if title is not None:
        lines.append(f"\t<Title>{html.escape(title, quote=False)}</Title>")
    if published_id is not None:
        lines.append(f"\t<PublishedFileId>{published_id}</PublishedFileId>")
    lines.append("\t<Language>english</Language>")
    if major is not None:
        lines.append(f"\t<VersionMajor>{major}</VersionMajor>")
    if minor is not None:
        lines.append(f"\t<VersionMinor>{minor}</VersionMinor>")
    tag_list = list(tags)
    if tag_list:
        lines.append("\t<Tags>")
        lines.extend(f"\t\t<Tags>{html.escape(t, quote=False)}</Tags>" for t in tag_list)
        lines.append("\t</Tags>")
    if description:
        lines.append(f"\t<ItemDescription>\n{description}\n\t</ItemDescription>")
    lines.append("</project>")
    return "\n".join(lines) + "\n"


def string_table(entries: Iterable[tuple[str, str]]) -> str:
    """A localization/*.string_table.xml text with CDATA entries like the game's."""
    body = "\n".join(
        f'\t\t<entry id="{entry_id}"><![CDATA[{text}]]></entry>' for entry_id, text in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<root>\n\t<language id="english">\n'
        f"{body}\n\t</language>\n</root>\n"
    )


@dataclasses.dataclass(frozen=True, slots=True)
class ModDirSpec:
    """One synthetic mod folder; ``project_bytes`` overrides ``project`` for encoding cases."""

    id: str
    folder: str
    workshop: bool = False
    project: str | None = None
    project_bytes: bytes | None = None
    localization: tuple[tuple[str, str], ...] = ()
    dirs: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    acf: tuple[tuple[str, str], ...] = ()  # (workshop id, timeupdated) for the acf cache
    mtime: int = MID_MARCH
    project_mtime: int | None = None
    nicknames: tuple[str, ...] = ()  # extra display/sort variants (already whitespace-normalized)

    def digest(self) -> str:
        record = dataclasses.asdict(self)
        if self.project_bytes is not None:
            record["project_bytes"] = self.project_bytes.hex()
        canonical = json.dumps(record, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


LOC_RANKING = (
    ("str_ui_title_banner", "Z Banner Title"),  # priority 2 (title)
    ("hero_class_name_abomination_rework", "Abomination Rework"),  # priority 0 wins
    ("class_name_xyz", "Al"),  # priority 1, shorter but lower priority
    ("str_mod_name", "Mod Name"),  # priority 2
    ("quirk_name_foo", "Quirk"),  # priority 3 (_name_)
    ("hero_class_name_long", "x" * 81),  # > 80 chars: ignored
    ("hero_class_name_bad", "50% Bad"),  # bad title: ignored
    ("tooltip_xyz", "Tooltip"),  # bad title AND no priority
)

LOC_ENTITIES = (
    # CDATA keeps the text literal: the title chain unescapes ONCE, so this title is "A &amp; B"
    ("HERO_CLASS_NAME_AMP", "  A &amp;amp; B  "),  # id lower-cased by the ranking, text stripped
    ("str_mod_name", "Plain &amp; Name"),
    ("hero_class_name_ws", "Two\n  Lines\tHere " + "x" * 70),  # > 80 chars after collapsing
)

CASES: tuple[ModDirSpec, ...] = (
    ModDirSpec(
        id="latin_title",
        folder="0001_my_mod",
        project=project_xml("My Great Mod", major="1", minor="2", tags=("Class", "New Class")),
        dirs=("heroes/mymod",),
        files=("heroes/mymod/mymod.info.darkest",),
        nicknames=("My Nick", "The Nick &amp; Co"),
    ),
    ModDirSpec(
        id="cjk_title_latin_folder",
        folder="sakura_skin",
        project=project_xml("桜のスキン", tags=("Skins",)),
        dirs=("heroes/sakura",),
    ),
    ModDirSpec(
        id="cjk_title_numeric_folder",
        folder="2900000001",
        workshop=True,
        project=project_xml("桜のスキン", tags=("Skins",)),
        dirs=("heroes/sakura", "heroes/zz_other"),
        files=("heroes/sakura/sakura.art.darkest",),
    ),
    ModDirSpec(
        id="percent_title",
        folder="0005_gold_mod",
        project=project_xml("50% more gold", major="0", minor="0"),
    ),
    ModDirSpec(
        id="colour_title",
        folder="colour_mod",
        project=project_xml("{colour_start|red}Mod{colour_end}", major="2", minor="0"),
    ),
    ModDirSpec(
        id="html_title",
        folder="bold_mod",
        project=project_xml("<b>Bold</b>", major="", minor=""),
    ),
    ModDirSpec(
        id="tooltip_title",
        folder="tip_mod",
        project=project_xml("Tooltip"),
    ),
    ModDirSpec(
        id="combats_title",
        folder="0009_combats",
        project=project_xml("Lasts 3 combats", major="1", minor="x"),
    ),
    ModDirSpec(
        id="numeric_folder_workshop",
        folder="1234567890",
        workshop=True,
        project=project_xml(
            "Numeric Workshop Mod",
            published_id="1234567890",
            major="0",
            minor="0",
            tags=("UI", "Quality of Life"),
            preview="preview_icon.png",
        ),
        files=("preview_icon.png",),
        acf=(("1234567890", ACF_MID_NOV),),
        nicknames=("Nicked",),
    ),
    ModDirSpec(
        id="workshop_pid_differs",
        folder="1111111111",
        workshop=True,
        project=project_xml("Renamed Upload", published_id="2222222222", major="3", minor="4"),
    ),
    ModDirSpec(
        id="pid_outside_workshop",
        folder="cool_mod",
        project=project_xml("Cool Mod", published_id="3333333333", tags=("Trinkets",)),
        dirs=("trinkets",),
    ),
    ModDirSpec(
        id="no_project_xml",
        folder="0002_bare_mod",
        localization=(("bare.string_table.xml", string_table(LOC_RANKING)),),
        dirs=("heroes/bare",),
    ),
    ModDirSpec(
        id="no_project_workshop_numeric",
        folder="4444444444",
        workshop=True,
        dirs=("heroes/vestal_rework", "monsters/aaa"),
    ),
    ModDirSpec(
        id="localization_fallback",
        folder="9999_loc_mod",
        project=project_xml("50% off", tags=("Class",)),
        localization=(
            ("loc.string_table.xml", string_table(LOC_RANKING)),
            ("broken.string_table.xml", "<root><language id='english'><entry id='x'>"),
            ("notes.txt", "not xml"),
        ),
        dirs=("heroes/loc",),
    ),
    ModDirSpec(
        id="localization_double_entity",
        folder="amp_mod",
        project=project_xml("50% amp"),  # bad title -> localization fallback
        localization=(("amp.string_table.xml", string_table(LOC_ENTITIES)),),
        dirs=("heroes/amp",),
    ),
    ModDirSpec(
        id="internal_code_title",
        folder="5555555555",
        workshop=True,
        project=project_xml("", published_id="5555555555"),
        dirs=("monsters/zz_beast", "monsters/the-big_one", "dungeons/ruins_x"),
    ),
    ModDirSpec(
        id="black_reliquary",
        folder="br_patch",
        project=project_xml("BR Weapons", tags=("Black_Reliquary", "Trinkets")),
        dirs=("trinkets",),
        nicknames=("[BR] Already", "Plain"),
    ),
    ModDirSpec(
        id="workshop_prefixed_folder",
        folder="1234567_old_style",
        workshop=True,
        project=project_xml("Old Style Upload"),
    ),
    ModDirSpec(
        id="workshop_nonnumeric_no_pid",
        folder="weird_name",
        workshop=True,
        project=project_xml("Weird"),
    ),
    ModDirSpec(
        id="encoding_bom_junk",
        folder="bom_mod",
        project_bytes=b"\xef\xbb\xbf" + b"junk\n" + project_xml("BOM Mod").encode("utf-8"),
    ),
    ModDirSpec(
        id="encoding_gb18030",
        folder="gb_mod",
        project_bytes=project_xml("模组标题", tags=("Enemies",))
        .replace('encoding="utf-8"', 'encoding="gb18030"')
        .encode("gb18030"),
        localization=(
            ("gb.string_table.xml", string_table((("hero_class_name_gb", "Jade Warrior"),))),
        ),
        dirs=("monsters/jade",),
    ),
    ModDirSpec(
        id="newest_file_wins",
        folder="newest_mod",
        project=project_xml("Newest Mod", major="0", minor="0"),
        files=("shared/newer.txt",),
        mtime=MID_JULY,
        project_mtime=MID_MARCH,
    ),
    ModDirSpec(
        id="project_only_mtime",
        folder="only_project",
        project=project_xml("Only Project", major="0", minor="0"),
        mtime=MID_MAY,
    ),
    ModDirSpec(
        id="entities_title",
        folder="0003_rogue",
        project=project_xml('Rogue & Knight\'s "Fate" (v2)', tags=("Class", "A, B/C|D")),
        dirs=("heroes/rogue",),
    ),
    ModDirSpec(
        id="the_prefix",
        folder="the_chorus",
        project=project_xml("The Chorus", tags=("New Class",)),
        dirs=("heroes/chorus", "panels"),
        nicknames=("the other",),
    ),
    ModDirSpec(
        id="version_minor_only",
        folder="minor_only",
        project=project_xml("Minor Only", major="", minor="7"),
    ),
)


def spec_by_id(case_id: str) -> ModDirSpec:
    for spec in CASES:
        if spec.id == case_id:
            return spec
    raise KeyError(case_id)


# ------------------------------------------------------------------ filesystem


def mods_root(base: Path, *, workshop: bool) -> Path:
    return base.joinpath(*WORKSHOP_PARTS) if workshop else base / "mods"


def _write(path: Path, data: bytes, mtime: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))


def materialize(spec: ModDirSpec, base: Path) -> Path:
    """Write the spec's folder under ``base`` (workshop layout when ``spec.workshop``)."""
    folder = mods_root(base, workshop=spec.workshop) / spec.folder
    folder.mkdir(parents=True, exist_ok=True)
    project_mtime = spec.mtime if spec.project_mtime is None else spec.project_mtime
    if spec.project_bytes is not None:
        _write(folder / "project.xml", spec.project_bytes, project_mtime)
    elif spec.project is not None:
        _write(folder / "project.xml", spec.project.encode("utf-8"), project_mtime)
    for name, text in spec.localization:
        _write(folder / "localization" / name, text.encode("utf-8"), spec.mtime)
    for rel in spec.dirs:
        (folder / rel).mkdir(parents=True, exist_ok=True)
    for rel in spec.files:
        _write(folder / rel, b"x", spec.mtime)
    return folder


def materialize_all(base: Path) -> dict[str, Path]:
    return {spec.id: materialize(spec, base) for spec in CASES}


# ------------------------------------------------------------------ snapshot reader (test-side)


def is_workshop_path(path: Path) -> bool:
    """True when the Steam Workshop content fragment occurs anywhere in the path."""
    fragment = str(PurePath(*WORKSHOP_PARTS)).casefold()
    return fragment in str(path.absolute()).casefold()


def path_workshop_id(folder: str, *, under_workshop: bool) -> str:
    """The Workshop id a folder name alone denotes: all digits, or a 7+ digit first/second part."""
    if not under_workshop:
        return ""
    if folder.isdigit():
        return folder
    for part in folder.split("_")[:2]:
        if part.isdigit() and len(part) >= 7:
            return part
    return ""


def _localization_entries(folder: Path) -> tuple[tuple[str, str], ...]:
    """RAW (id, text) per <entry>, as the contract defines ``ModSnapshot.localization_entries``.

    No lower-casing, unescaping or whitespace collapsing here: ``identity.localization_title``
    applies that normalization itself, and the goldens must prove it.
    """
    loc = folder / "localization"
    if not loc.is_dir():
        return ()
    entries: list[tuple[str, str]] = []
    for file in sorted(loc.iterdir()):
        if file.suffix.lower() != ".xml":
            continue
        try:
            root = ET.fromstring(file.read_bytes())
        except ET.ParseError:
            continue
        for elem in root.iter():
            if elem.tag.split("}", 1)[-1].lower() != "entry":
                continue
            entries.append((elem.attrib.get("id", ""), "".join(elem.itertext())))
    return tuple(entries)


def _localization_signature(folder: Path) -> str:
    """``<xml file count>:<newest xml mtime>`` of the localization folder, ``""`` without one."""
    loc = folder / "localization"
    if not loc.is_dir():
        return ""
    xml_files = [f for f in loc.iterdir() if f.suffix.lower() == ".xml"]
    if not xml_files:
        return ""
    newest = max((f.stat().st_mtime for f in xml_files), default=0.0)
    return f"{len(xml_files)}:{int(newest)}"


def _walk_files(folder: Path) -> list[Path]:
    return [p for p in folder.rglob("*") if p.is_file()]


def _code_subdirs(folder: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    result: list[tuple[str, tuple[str, ...]]] = []
    for top in CODE_DIRS:
        top_dir = folder / top
        if not top_dir.is_dir():
            continue
        children = tuple(sorted(c.name for c in top_dir.iterdir() if c.is_dir()))
        result.append((top, children))
    return tuple(result)


def snapshot_from_dir(
    folder: Path, *, acf: Mapping[str, str] | None = None, root: Path | None = None
) -> ModSnapshot:
    """Gather the disk facts of one mod folder (what services feed ``derive_mod_info``)."""
    from src.core.ids import ModId, SourceKind
    from src.core.model import ModSnapshot
    from src.core.project_xml import parse_project

    under_workshop = is_workshop_path(folder)
    key = folder.name
    project_file = folder / "project.xml"
    project = parse_project(project_file.read_bytes()) if project_file.is_file() else None
    project_mtime = project_file.stat().st_mtime if project_file.is_file() else None
    all_files = _walk_files(folder)
    pwid = path_workshop_id(key, under_workshop=under_workshop)
    acf_key = project.published_file_id if under_workshop and project is not None else ""
    acf_timeupdated = (acf or {}).get(acf_key or pwid, "") if under_workshop else ""
    preview = folder / (project.preview_icon_file if project else "")
    has_preview = bool(project and project.preview_icon_file) and preview.is_file()
    mods_dir = folder.parent if root is None else root
    return ModSnapshot(
        key=ModId(key),
        source_id="steam_workshop" if under_workshop else "local_folder",
        kind=SourceKind.WORKSHOP if under_workshop else SourceKind.LOCAL,
        path=PurePath(str(folder)),
        root=PurePath(str(mods_dir)),
        under_workshop=under_workshop,
        path_workshop_id=pwid,
        project=project,
        localization_entries=_localization_entries(folder),
        top_level_dirs=frozenset(c.name.casefold() for c in folder.iterdir() if c.is_dir()),
        code_subdirs=_code_subdirs(folder),
        files=frozenset(
            p.relative_to(folder).as_posix().casefold() for p in all_files if p.parent != folder
        ),
        newest_mtime=max((p.stat().st_mtime for p in all_files), default=None),
        project_mtime=project_mtime,
        localization_signature=_localization_signature(folder),
        acf_timeupdated=acf_timeupdated,
        preview_path=PurePath(str(preview)) if has_preview else None,
        preview_mtime_ns=preview.stat().st_mtime_ns if has_preview else None,
        content_roots_mtime_ns=max(
            [
                folder.stat().st_mtime_ns,
                *(c.stat().st_mtime_ns for c in folder.iterdir() if c.is_dir()),
            ]
        ),
    )


def snapshot_for(spec: ModDirSpec, base: Path) -> ModSnapshot:
    return snapshot_from_dir(
        mods_root(base, workshop=spec.workshop) / spec.folder, acf=dict(spec.acf)
    )


def sample_digest(folder: Path) -> str:
    """project.xml bytes plus the first two directory levels: everything the classifier reads."""
    h = hashlib.sha256((folder / "project.xml").read_bytes())
    for child in sorted(p.name for p in folder.iterdir() if p.is_dir()):
        h.update(b"\0" + child.encode("utf-8"))
        for grandchild in sorted(p.name for p in (folder / child).iterdir() if p.is_dir()):
            h.update(b"/" + grandchild.encode("utf-8"))
    return h.hexdigest()


# ------------------------------------------------------------------ golden record shapes


def identity_record(info: ModInfo) -> dict[str, object]:
    """The identity facts of one mod in the shape the identity goldens freeze."""
    from src.core.identity import (
        category_memory_keys,
        display_name,
        display_name_with_suffix,
        display_suffix,
        duplicate_keys,
        sort_key,
    )

    return {
        "title": info.title,
        "published_file_id": info.workshop_id,
        "save_identity": list(info.save_identity.as_tuple()),
        "version_label": info.version_label,
        "updated_label": info.updated_label,
        "black_reliquary": info.black_reliquary,
        "project_mtime": info.signature.project_mtime,
        "localization_signature": info.signature.localization_signature,
        "workshop_timeupdated": info.signature.workshop_timeupdated,
        "tags": list(info.tags),
        "display_name": display_name(info, None),
        "display_suffix": display_suffix(info),
        "display_name_with_suffix": display_name_with_suffix(info, None),
        "sort_name": sort_key(info, None),
        "duplicate_keys": list(duplicate_keys(info)),
        "category_memory_keys": list(category_memory_keys(info)),
    }


def nickname_record(info: ModInfo, nickname: str) -> dict[str, object]:
    """The nickname-dependent names of one mod."""
    from src.core.identity import display_name, display_name_with_suffix, sort_key

    return {
        "display_name": display_name(info, nickname),
        "display_name_with_suffix": display_name_with_suffix(info, nickname),
        "sort_name": sort_key(info, nickname),
    }


# ------------------------------------------------------------------ corpora for the pure helpers

_IDENTITY_POOL = (
    "abc",
    "Mod",
    "THE",
    "Reliquary",
    "123",
    "0042",
    "_",
    "\\",
    "/",
    "-",
    ":",
    ";",
    ",",
    ".",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    "'",
    '"',
    "!",
    "+",
    "&",
    "&amp;",
    "&#39;",
    "&lt;",
    "&quot;",
    "&nbsp;",
    " ",
    "  ",
    "\t",
    "\n",
    chr(0xA0),
    chr(0x3000),
    "ß",
    "İ",
    "É",
    "桜",
    "模组",
    "한글",
    "\U0001f600",
    "%",
    "#",
    "@",
    "*",
    "=",
    "?",
    "~",
)


def identity_corpus(seed: int = 2024, count: int = 2000) -> list[str]:
    """Seeded strings mixing folded punctuation, entities and non-Latin text."""
    import random

    rng = random.Random(seed)
    corpus: list[str] = []
    for _ in range(count):
        parts = rng.randint(0, 12)
        corpus.append("".join(rng.choice(_IDENTITY_POOL) for _ in range(parts)))
    return corpus


TITLE_CORPUS: tuple[str, ...] = (
    "",
    " ",
    "My Mod",
    "Tooltip",
    "tooltips",
    "TRAY_ICON",
    "Tray Icon",
    "50% more",
    "{colour_start|red}X{colour_end}",
    "{color_x}",
    "{colour",
    "<b>Bold</b>",
    "a > b",
    "&lt;i&gt;",
    "&amp;",
    "Lasts 3 combats",
    "1 combat",
    "10 Combats",
    "combats 3",
    "桜のスキン",
    "Café",
    "1234567890",
    "12 34",
    "-12",
    "١٢",
    "0",
    "x" * 81,
    "Tooltip Tweaks",
)

VERSION_CASES: tuple[tuple[str, str], ...] = (
    ("1", "2"),
    ("0", "0"),
    ("", ""),
    ("01", "02"),
    ("1", ""),
    ("", "3"),
    ("1a", "b"),
    ("2", "0"),
    ("0", "1"),
    ("x", ""),
    ("", "0"),
    ("00", "0"),
    ("10", "007"),
    ("v1", "0"),
)

BLACK_RELIQUARY_CASES: tuple[tuple[str, ...], ...] = (
    (),
    ("Black Reliquary",),
    ("black_reliquary",),
    ("BLACK-RELIQUARY",),
    ("blackreliquary",),
    ("Black Reliquary Patch",),
    ("Class", "Black  Reliquary"),
    ("Black&amp;Reliquary",),
    ("Reliquary Black",),
    ("black.reliquary!",),
    ("[Black] (Reliquary)",),
)

SAVE_NAME_CASES: tuple[str, ...] = (
    "0001_my_mod",
    "12_34_mod",
    "1234567890",
    "_leading",
    "mod_0001",
    "",
    "0_",
    "01__x",
    "abc",
    "7_",
)
