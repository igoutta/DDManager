"""``project.xml`` facts: forgiving parsing plus the tag, version and description helpers.

Ports ``dd2.py:576-589`` (child text, control-character stripping), ``dd2.py:634-666`` (the
encoding retry ladder), ``dd2.py:3406-3430`` (version label, Black Reliquary tag) and
``categories.py:105-131`` (``project_tag_values``).  Pure: takes bytes, never opens a file.
"""

import html
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final
from xml.etree.ElementTree import Element, ParseError, fromstring

from src.core.text import PUNCTUATION_RE, collapse_whitespace

_ENCODINGS: Final[tuple[str, ...]] = ("utf-8-sig", "utf-8", "utf-16", "gb18030", "big5")
_TAG_SPLIT_RE: Final = re.compile(r"[,/|]| {2,}")
_LOAD_AFTER_RE: Final = re.compile(r"load (this|it) after:?", re.IGNORECASE)
_BULLET_RE: Final = re.compile(r"^[-*•]\s+(\S.*?)\s*$")


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    """What a parsed ``project.xml`` says, verbatim (no identity decisions here)."""

    title: str
    """Raw ``<Title>`` text, ``""`` when absent."""
    published_file_id: str
    """Raw ``<PublishedFileId>`` text, ``""`` when absent."""
    version_major: str
    version_minor: str
    legacy_tags: tuple[str, ...]
    """Exact ``categories.py:105-131`` output, including the outer-``<Tags>`` pseudo tag."""
    clean_tags: tuple[str, ...]
    """Leaf ``<Tags>`` texts only: stripped, order and case kept."""
    preview_icon_file: str
    description: str
    """Raw ``<ItemDescription>`` text (stripped), ``""`` when absent."""


def _local_name(element: Element) -> str:
    """Lower-cased tag name with any ``{namespace}`` prefix removed (``dd2.py:578``)."""
    return element.tag.split("}", 1)[-1].lower()


def xml_text_from_child(root: Element, tag_name: str) -> str:
    """Stripped text of the first direct child called ``tag_name`` (``dd2.py:576-582``).

    The match ignores case and namespaces; a matching child without text yields ``""``, and so
    does a missing child.
    """
    wanted = tag_name.lower()
    for child in list(root):
        if _local_name(child) == wanted:
            return child.text.strip() if child.text else ""
    return ""


def strip_invalid_xml_chars(text: str) -> str:
    """Drop control characters other than tab, newline and carriage return (``dd2.py:585-589``)."""
    return "".join(char for char in text if char in "\t\n\r" or ord(char) >= 0x20)


def _trim_leading_junk(text: str) -> str:
    """Cut anything before ``<?xml``, else before the first ``<`` (``dd2.py:651-657``)."""
    xml_start = text.find("<?xml")
    if xml_start > 0:
        return text[xml_start:]
    if xml_start < 0:
        root_start = text.find("<")
        if root_start > 0:
            return text[root_start:]
    return text


def parse_xml_forgiving(raw: bytes) -> Element | None:
    """The ``dd2.py:634-666`` retry ladder over in-memory bytes.

    First the bytes as they are (expat honours the declared encoding); then each of utf-8-sig,
    utf-8, utf-16, gb18030 and big5 after stripping control characters and leading junk.
    ``ValueError`` is expat refusing a multi-byte declared encoding (gb18030, big5) and
    ``LookupError`` an unknown declared encoding; the decoded-text retries then handle both
    (the legacy caught ``Exception`` at every step).  ``None`` when nothing parses.
    """
    try:
        return fromstring(raw)
    except ParseError, ValueError, LookupError:
        pass
    for encoding in _ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        text = _trim_leading_junk(strip_invalid_xml_chars(text).strip())
        try:
            return fromstring(text)
        except ParseError, ValueError, LookupError:
            continue
    return None


def _legacy_tag_values(root: Element) -> tuple[str, ...]:
    """Exact port of ``categories.py:105-131`` ``project_tag_values`` over a parsed root.

    Every element named ``Tags`` at any depth contributes its whole ``itertext`` (whitespace
    collapsed), split on ``,`` ``/`` ``|`` or a double space; parts are HTML-unescaped, stripped
    and de-duplicated case-insensitively.  Because the outer ``<Tags>`` wrapper's text is the
    concatenation of its children, the first value is usually a pseudo tag such as
    ``"Character Mod Class Mod Patch"``; ``clean_tags`` is the fixed variant.
    """
    values: list[str] = []
    seen: set[str] = set()
    for elem in root.iter():
        if _local_name(elem) != "tags":
            continue
        text = collapse_whitespace("".join(elem.itertext()))
        if not text:
            continue
        for part in _TAG_SPLIT_RE.split(text):
            cleaned = html.unescape(part).strip()
            if cleaned and cleaned.lower() not in seen:
                values.append(cleaned)
                seen.add(cleaned.lower())
    return tuple(values)


def _clean_tag_values(root: Element) -> tuple[str, ...]:
    """Texts of the leaf ``<Tags>`` elements only, stripped, in document order, case kept."""
    values: list[str] = []
    for elem in root.iter():
        if _local_name(elem) != "tags" or len(elem) > 0:
            continue
        text = (elem.text or "").strip()
        if text:
            values.append(text)
    return tuple(values)


def localization_entries(root: Element) -> tuple[tuple[str, str], ...]:
    """``(id attribute, raw itertext)`` of every ``<entry>`` element (``dd2.py:3561-3568``).

    The raw text is deliberately untouched here; ``identity.localization_title`` applies the
    legacy strip/unescape/collapse in the same order as the legacy did.
    """
    return tuple(
        (elem.attrib.get("id", ""), "".join(elem.itertext()))
        for elem in root.iter()
        if _local_name(elem) == "entry"
    )


def parse_project(raw: bytes) -> ProjectInfo | None:
    """Parse ``project.xml`` bytes forgivingly; ``None`` when no encoding yields a document."""
    root = parse_xml_forgiving(raw)
    if root is None:
        return None
    return ProjectInfo(
        title=xml_text_from_child(root, "Title"),
        published_file_id=xml_text_from_child(root, "PublishedFileId"),
        version_major=xml_text_from_child(root, "VersionMajor"),
        version_minor=xml_text_from_child(root, "VersionMinor"),
        legacy_tags=_legacy_tag_values(root),
        clean_tags=_clean_tag_values(root),
        preview_icon_file=xml_text_from_child(root, "PreviewIconFile"),
        description=xml_text_from_child(root, "ItemDescription"),
    )


def version_label(major: str, minor: str) -> str:
    """``dd2.py:3406-3421`` ``version_label_from_project`` over the two child texts.

    Both blank -> ``""``; both numeric -> ``"M.m"`` with leading zeros dropped, except ``0.0``
    which is ``""``; otherwise the non-blank parts joined with ``.``.  ``isdecimal`` replaces
    the legacy ``isdigit``: the two differ only on characters (superscripts, circled digits)
    where the legacy ``int()`` crashed.
    """
    if not major and not minor:
        return ""
    if major.strip().isdecimal() and minor.strip().isdecimal():
        if int(major) == 0 and int(minor) == 0:
            return ""
        return f"{int(major)}.{int(minor)}"
    parts = [part for part in (major, minor) if part.strip()]
    return ".".join(parts)


def is_black_reliquary_tagged(tags: Iterable[str]) -> bool:
    """``dd2.py:3423-3430``: any tag that normalises to ``black reliquary``."""
    for tag in tags:
        normalized = collapse_whitespace(PUNCTUATION_RE.sub(" ", html.unescape(str(tag)).lower()))
        compact = normalized.replace(" ", "")
        if normalized == "black reliquary" or compact == "blackreliquary":
            return True
    return False


def load_after_hints(description: str) -> tuple[str, ...]:
    """Bullet lines that follow a ``Load this after:`` / ``Load it after`` line.

    Collection starts at a line matching ``load (this|it) after:?`` (case-insensitive), takes
    every ``- x`` / ``* x`` / ``• x`` line (content stripped), ignores other non-blank
    lines and stops at the first blank line; a later header starts a new block.
    """
    hints: list[str] = []
    collecting = False
    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not collecting:
            collecting = _LOAD_AFTER_RE.search(line) is not None
            continue
        if not line:
            collecting = False
            continue
        match = _BULLET_RE.match(line)
        if match:
            hints.append(match.group(1))
    return tuple(hints)
