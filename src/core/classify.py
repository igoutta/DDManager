"""Heuristic category suggestion over a ``ModInfo`` (no disk access).

Tag weights, directory weights, title keywords and the decision thresholds are fixed
constants; ``ModInfo.top_level_dirs`` / ``subdirs_of("heroes")`` stand in for ``os.path.isdir`` and
``os.listdir``.
"""

from collections.abc import Iterable
from typing import Final

from src.core.categories import DEFAULT_CATEGORIES
from src.core.identity import display_name, strip_numeric_prefix
from src.core.model import ModInfo

IGNORE_TAGS: Final[frozenset[str]] = frozenset(
    {
        "english",
        "korean",
        "japanese",
        "chinese",
        "russian",
        "spanish",
        "german",
        "french",
        "italian",
        "polish",
        "pets compatible",
        "com",
        "cc",
        "bc",
        "s-purple",
    }
)
"""Which tag adds weight to which category."""

TAG_RULES: Final[tuple[tuple[str, frozenset[str]], ...]] = (
    (
        "UI",
        frozenset(
            {"ui", "interface", "tooltip", "tooltips", "qol", "quality of life", "character_ui"}
        ),
    ),
    ("Districts", frozenset({"district", "districts", "new district"})),
    (
        "Dungeons",
        frozenset(
            {
                "dungeon",
                "dungeons",
                "new dungeon",
                "farmstead",
                "courtyard",
                "quest",
                "butcher's circus",
                "butchers circus",
            }
        ),
    ),
    ("Quirks", frozenset({"quirk", "quirks", "disease", "diseases"})),
    ("Trinkets", frozenset({"trinket", "trinkets", "new trinkets"})),
    (
        "Enemies",
        frozenset(
            {
                "monster",
                "monster mod",
                "monsters",
                "enemy",
                "enemies",
                "boss",
                "bosses",
                "new monsters",
                "new boss",
                "modded boss",
                "roaming boss",
            }
        ),
    ),
    ("Class Patch", frozenset({"class tweaks", "patch", "compatibility", "rework"})),
    ("Class", frozenset({"class", "new class", "class mod", "character mod", "hero", "heroes"})),
    ("Skins", frozenset({"skin", "skins", "spriteset", "sprite", "reskin"})),
)
"""A matching tag adds 4 to its category."""

_TAG_WEIGHT = 4
_UI_DIRS: tuple[str, ...] = ("panels", "overlays", "fe_flow", "cursors", "scrolls")
_TITLE_PATCH_WORDS: tuple[str, ...] = (
    "patch",
    "addon",
    "add-on",
    "compatibility",
    "rebalance",
    "rework",
    "fix",
    "fixes",
    "tweak",
    "tweaks",
)
_CLASS_IDENTITY_WORDS: tuple[str, ...] = ("new class", "class mod", "character mod", " class ")
_SKIN_WORDS: tuple[str, ...] = ("skin", "skins", "sprite", "spriteset", "reskin")

# (category, weight, any of these substrings in the title blob)
_TITLE_RULES: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("UI", 5, ("tooltip", "ui")),
    ("UI", 6, ("character_ui",)),
    ("UI", 5, ("roster", "stack", "size")),
    ("Skins", 2, ("skin", "sprite")),
    ("Districts", 5, ("district",)),
    ("Dungeons", 3, ("dungeon", "quest", "butcher", "circus")),
    ("Trinkets", 2, ("trinket",)),
    ("Quirks", 6, ("quirk", "quirks")),
    ("Dungeons", 6, ("vermintide",)),
    ("Districts", 6, ("smouldering ruin", "smoldering ruin", "kraken society")),
    ("Enemies", 6, ("monster mod",)),
)

_MIN_BEST_SCORE = 4
_MIN_MARGIN = 2


def _title_bits(info: ModInfo, nickname: str | None) -> str:
    """Key, save name, display name and title, lower-cased."""
    return " ".join(
        [info.id, strip_numeric_prefix(info.id), display_name(info, nickname), info.title]
    ).lower()


def _score_tags(scores: dict[str, int], tags: Iterable[str]) -> None:
    """Add the tag weights of ``tags`` to ``scores``."""
    for tag in tags:
        if tag in IGNORE_TAGS:
            continue
        for category, keywords in TAG_RULES:
            if tag in keywords:
                scores[category] += _TAG_WEIGHT


def _score_directories(scores: dict[str, int], info: ModInfo, tags: list[str]) -> None:
    """Content directories other than ``heroes``."""
    dirs = info.top_level_dirs
    if "trinkets" in dirs:
        scores["Trinkets"] += 4
    if "monsters" in dirs:
        scores["Enemies"] += 6
    if "dungeons" in dirs:
        scores["Dungeons"] += 5
    if "quirks" in dirs or "diseases" in dirs:
        scores["Quirks"] += 5
    if "upgrades" in dirs and any("district" in tag for tag in tags):
        scores["Districts"] += 5
    if any(name in dirs for name in _UI_DIRS):
        scores["UI"] += 4


def _score_heroes(scores: dict[str, int], info: ModInfo, tags: list[str], title_bits: str) -> None:
    """The ``heroes`` directory decides Skins / Class / Class Patch."""
    if "heroes" not in info.top_level_dirs:
        return
    tag_blob = " ".join(tags)
    title_has_patch_words = any(word in title_bits for word in _TITLE_PATCH_WORDS)
    has_class_identity = any(word in tag_blob for word in _CLASS_IDENTITY_WORDS)
    hero_children = info.subdirs_of("heroes")
    if any(word in tag_blob for word in _SKIN_WORDS):
        scores["Skins"] += 7
    elif has_class_identity and hero_children and not title_has_patch_words:
        scores["Class"] += 8
    elif "class tweaks" in tag_blob and not has_class_identity:
        scores["Class Patch"] += 7
    elif title_has_patch_words:
        scores["Class Patch"] += 6
    elif hero_children:
        scores["Class"] += 6


def _score_titles(scores: dict[str, int], title_bits: str) -> None:
    """Keyword hits in the title blob."""
    for category, weight, words in _TITLE_RULES:
        if any(word in title_bits for word in words):
            scores[category] += weight


def category_scores(info: ModInfo, *, nickname: str | None = None) -> dict[str, int]:
    """A score per built-in category."""
    scores = dict.fromkeys(DEFAULT_CATEGORIES, 0)
    title_bits = _title_bits(info, nickname)
    tags = [tag.lower() for tag in info.tags]
    _score_tags(scores, tags)
    _score_directories(scores, info, tags)
    _score_heroes(scores, info, tags, title_bits)
    _score_titles(scores, title_bits)
    return scores


def suggest_category(info: ModInfo, *, nickname: str | None = None) -> str | None:
    """One category when the signal is strong, else ``None``.

    Best score below 4 -> ``None``; Dungeons wins ties; Class wins only strictly; any other
    category needs a margin of at least 2 over the runner-up.
    """
    ranked = sorted(
        category_scores(info, nickname=nickname).items(), key=lambda item: item[1], reverse=True
    )
    best_category, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    if best_score < _MIN_BEST_SCORE:
        return None
    if best_category == "Dungeons" and best_score >= second_score:
        return best_category
    if best_category == "Class" and best_score > second_score:
        return best_category
    if best_score - second_score < _MIN_MARGIN:
        return None
    return best_category
