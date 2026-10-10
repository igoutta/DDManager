"""Plain data of the per-mod labels (assign category, nickname); no services, no widgets."""

from dataclasses import dataclass

from src.core.ids import ModId


@dataclass(frozen=True, slots=True)
class CategoryChoiceVM:
    """One entry of the "Assign Category" submenu."""

    name: str
    label: str
    color: str


@dataclass(frozen=True, slots=True)
class NicknameVM:
    """What the nickname dialog starts from.

    ``initial`` is the saved nickname, else the default display name; typing the default display
    name back clears the nickname.
    """

    mod_id: ModId
    title: str
    default_name: str
    current: str
    initial: str
