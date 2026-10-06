"""Categories presenter: the editor's draft, its rules and the commit (no widgets).

The draft is a :class:`~src.core.categories.CategoryEditorState`; every operation replaces it with
a modified copy and emits ``changed``.  Nothing reaches the controller until :meth:`commit`, so
the dialog's Save/Cancel is atomic.  The legacy messages (``dd2.py:5380-5547``) become
:class:`Problem` s the dialog shows.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QObject, Signal

from src.core.categories import (
    PSEUDO_CATEGORIES,
    CategoryEditorState,
    add_custom_category,
    category_color,
    default_color_for_new_category,
    move_category,
    move_category_to_index,
    normalize_hex_color,
    remove_custom_category,
    rename_custom_category,
)
from src.ui.catalog import category_label
from src.ui.theme.tokens import TIER_TOKENS

if TYPE_CHECKING:
    from src.ui.controller import MainController

_CUSTOM_COLOR = TIER_TOKENS["custom"].color
_RESERVED = frozenset(name.lower() for name in PSEUDO_CATEGORIES)


@dataclass(frozen=True, slots=True)
class Problem:
    """A refused operation: the message key, its parameters and how loudly to show it."""

    key: str
    params: tuple[tuple[str, str], ...] = ()
    level: Literal["info", "warning"] = "warning"


@dataclass(frozen=True, slots=True)
class CategoryRowVM:
    name: str
    label: str
    color: str
    builtin: bool
    custom_color: bool


class CategoriesPresenter(QObject):
    changed = Signal()

    def __init__(self, controller: MainController) -> None:
        super().__init__(controller)
        self._c = controller
        self._state = controller.labels.editor_state()

    # ------------------------------------------------------------------ draft

    def begin(self) -> None:
        """Start a new draft from the controller's current categories."""
        self._state = self._c.labels.editor_state()
        self.changed.emit()

    @property
    def state(self) -> CategoryEditorState:
        return self._state

    def names(self) -> tuple[str, ...]:
        return self._state.categories

    def is_builtin(self, index: int) -> bool:
        names = self._state.categories
        return 0 <= index < len(names) and names[index] not in self._state.custom_categories

    def builtin_problem(self, index: int, action: Literal["rename", "remove"]) -> Problem | None:
        """Why the category at ``index`` cannot be renamed / removed (built-in ones cannot)."""
        if self.is_builtin(index):
            return Problem(f"ui.categories.builtin_{action}", level="info")
        return None

    def color_of(self, name: str) -> str:
        """The draft color of ``name``: the user's, else the built-in default."""
        return category_color(name, self._state.category_colors, _CUSTOM_COLOR)

    def default_color(self) -> str:
        """The first cycle color no category uses yet (the add dialog's starting point)."""
        return default_color_for_new_category(self._state.category_colors, _CUSTOM_COLOR)

    def rows(self) -> tuple[CategoryRowVM, ...]:
        c = self._c
        suffix = c.tr("category_builtin_suffix")
        rows: list[CategoryRowVM] = []
        for index, name in enumerate(self._state.categories):
            builtin = self.is_builtin(index)
            label = category_label(name, c.tr, c.has)
            rows.append(
                CategoryRowVM(
                    name=name,
                    label=f"{label} ({suffix})" if builtin else label,
                    color=self.color_of(name),
                    builtin=builtin,
                    custom_color=bool(
                        normalize_hex_color(self._state.category_colors.get(name, ""))
                    ),
                )
            )
        return tuple(rows)

    def _set(self, **fields: object) -> None:
        self._state = dataclasses.replace(self._state, **fields)
        self.changed.emit()

    # ------------------------------------------------------------------ order

    def move(self, index: int, delta: int) -> int:
        """Swap with the neighbour ``delta`` away; returns the row to select."""
        names = self._state.categories
        moved = move_category(names, index, delta)
        if moved == names:
            return index
        self._set(categories=moved)
        return index + delta

    def move_to_index(self, index: int, target: int) -> int:
        """Move the category at ``index`` so it ends up at ``target`` (the drag result)."""
        names = self._state.categories
        moved = move_category_to_index(names, index, target)
        if moved == names:
            return index
        self._set(categories=moved)
        return target

    def reorder(self, names: Sequence[str]) -> bool:
        """Adopt a new order of the same names (the list widget moved them itself)."""
        current = self._state.categories
        if tuple(names) == current or sorted(names) != sorted(current):
            return False
        self._set(categories=tuple(names))
        return True

    # ------------------------------------------------------------------ names

    def check_name(self, raw: str, *, renaming: str | None = None) -> tuple[str, Problem | None]:
        """The cleaned name and why it is refused (``dd2.py:5473-5485``, ``5497-5510``)."""
        name = " ".join(raw.strip().split())
        if not name:
            return name, Problem("ui.categories.empty")
        if name.lower() in _RESERVED:
            return name, Problem("ui.categories.reserved", (("name", name),))
        taken = {cat.lower() for cat in self._state.categories if cat != renaming}
        if name.lower() in taken:
            return name, Problem("ui.categories.exists")
        return name, None

    def add(self, raw: str, color: str | None = None) -> Problem | None:
        """Append a custom category; a missing or invalid ``color`` takes the next cycle color."""
        name, problem = self.check_name(raw)
        if problem is not None:
            return problem
        chosen = normalize_hex_color(color or "") or self.default_color()
        self._state = add_custom_category(self._state, name, chosen)
        self.changed.emit()
        return None

    def rename(self, index: int, raw: str) -> Problem | None:
        """Rename the custom category at ``index`` (built-in ones cannot be renamed)."""
        names = self._state.categories
        if not 0 <= index < len(names):
            return None
        old = names[index]
        problem = self.builtin_problem(index, "rename")
        if problem is not None:
            return problem
        name, problem = self.check_name(raw, renaming=old)
        if problem is not None:
            return problem
        if name != old:
            self._state = rename_custom_category(self._state, index, old, name)
            self.changed.emit()
        return None

    def remove(self, index: int) -> Problem | None:
        """Remove the custom category at ``index``; its mods become unassigned on commit."""
        names = self._state.categories
        if not 0 <= index < len(names):
            return None
        problem = self.builtin_problem(index, "remove")
        if problem is not None:
            return problem
        self._state = remove_custom_category(self._state, index, names[index])
        self.changed.emit()
        return None

    # ------------------------------------------------------------------ colors

    def set_color(self, index: int, color: str) -> bool:
        names = self._state.categories
        normalized = normalize_hex_color(color)
        if not normalized or not 0 <= index < len(names):
            return False
        self._set(category_colors={**self._state.category_colors, names[index]: normalized})
        return True

    def reset_color(self, index: int) -> None:
        names = self._state.categories
        if 0 <= index < len(names) and names[index] in self._state.category_colors:
            colors = dict(self._state.category_colors)
            del colors[names[index]]
            self._set(category_colors=colors)

    # ------------------------------------------------------------------ commit

    def commit(self) -> None:
        """Write the draft through the controller as one change, then start a fresh draft."""
        self._c.labels.commit_categories(self._state)
        self.begin()
