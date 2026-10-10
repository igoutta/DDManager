"""Display and sort names of a mod, computed from a ``ModInfo`` plus the
user's nickname.  Re-exported by :mod:`src.core.identity` for the contract."""

import html

from src.core.identity_text import split_numeric_prefix, strip_numeric_prefix
from src.core.model import ModInfo


def _clean_nickname(nickname: str | None) -> str:
    """The nickname, whitespace-collapsed; ``""`` when unset."""
    return " ".join(str(nickname).split()) if nickname else ""


def _apply_name_prefixes(info: ModInfo, text: str) -> str:
    """Unescape, strip and prefix ``[BR] `` for Black Reliquary mods."""
    value = html.unescape(str(text or "")).strip()
    if not value:
        return value
    if info.black_reliquary and not value.startswith("[BR] "):
        value = f"[BR] {value}"
    return value


def _display_base(info: ModInfo) -> str:
    """without the prefix step: title with an id suffix, else the folder."""
    mod = info.id
    title = info.title
    if title and title != mod:
        if mod.isdigit():
            return f"{title} [{mod}]"
        if info.workshop_id and info.workshop_id not in mod:
            return f"{title} [{info.workshop_id}]"
        return title
    split = split_numeric_prefix(mod)
    return mod if split is None else split[1]


def display_name(info: ModInfo, nickname: str | None) -> str:
    """The nickname, else the title with its workshop id, prefixed."""
    cleaned = _clean_nickname(nickname)
    if cleaned:
        return _apply_name_prefixes(info, cleaned)
    return _apply_name_prefixes(info, _display_base(info))


def display_suffix(info: ModInfo) -> str:
    """The version label, else the updated label, unwrapped."""
    version = info.version_label.strip()
    return version if version else info.updated_label.strip()


def display_name_with_suffix(info: ModInfo, nickname: str | None) -> str:
    """``"<display name> (<suffix>)"`` when there is a suffix."""
    base = display_name(info, nickname)
    suffix = display_suffix(info)
    return f"{base} ({suffix})" if suffix else base


def _sort_display_name(info: ModInfo, nickname: str | None) -> str:
    """Nickname, else the title if it differs from the key, else save name."""
    cleaned = _clean_nickname(nickname)
    if cleaned:
        return html.unescape(cleaned)
    title = info.title.strip()
    if title and title != info.id:
        return html.unescape(title)
    return strip_numeric_prefix(info.id)


def sort_key(info: ModInfo, nickname: str | None) -> str:
    """The sort display name, lower-cased, without a leading ``the``."""
    name = _sort_display_name(info, nickname).strip()
    if name.lower().startswith("the "):
        name = name[4:]
    return name.lower()
