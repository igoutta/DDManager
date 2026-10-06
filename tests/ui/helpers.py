"""Shared helpers of the UI tests: view-model builders, tolerant constructors and doubles.

``build`` constructs a class by matching its ``__init__`` parameter NAMES against the objects the
test harness has (translator, thumbs, services, ...), so the harness has one place to change when
a constructor gains an argument.  Anything it cannot satisfy raises with the parameter name.
"""

import inspect
from annotationlib import Format
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from itertools import cycle
from typing import Any

from PySide6.QtCore import QObject, Signal

from src.core.ids import ModId

TIER_CYCLE: tuple[tuple[str, str, str, str], ...] = (
    ("class", "CLS", "Class", "#A4B56C"),
    ("ui", "UI", "UI", "#6C8DB5"),
    ("item", "ITM", "Item", "#B58F6C"),
    ("patch", "PCH", "Patch", "#A66A4A"),
    ("unassigned", "---", "Unassigned", "#9D8E77"),
)

_ALIASES = {
    "tr": "translator",
    "thumbnails": "thumbs",
    "thumbnail_provider": "thumbs",
    "thumbnail_source": "thumbs",
    "thumb_source": "thumbs",
    "presenter": "profiles",
    "profiles_presenter": "profiles",
    "main_controller": "controller",
    "port": "profiles",
    "ui_ini": "settings_path",
    "log_dir": "logs_dir",
    "theme": "tokens",
    "icon_set": "icons",
}


def build[T](cls: Callable[..., T], **available: object) -> T:
    """Instantiate ``cls`` passing the ``available`` objects its required parameters ask for."""
    kwargs: dict[str, object] = {}
    # FORWARDREF: modules annotate with names imported only under TYPE_CHECKING (lazy annotations)
    signature = inspect.signature(cls, annotation_format=Format.FORWARDREF)
    for name, param in signature.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        key = _ALIASES.get(name, name)
        if key in available:
            kwargs[name] = available[key]
        elif param.default is param.empty:
            raise TypeError(
                f"{getattr(cls, '__name__', cls)} needs parameter {name!r}; "
                f"the harness only knows {sorted(available)}"
            )
    return cls(**kwargs)


def first_attr(obj: object, names: Sequence[str]) -> Any:
    """The first attribute of ``obj`` named in ``names`` (the contract leaves the name open)."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AssertionError(
        f"contract ambiguity: {type(obj).__name__} has none of {list(names)}; "
        f"public members: {[n for n in dir(obj) if not n.startswith('_')][:40]}"
    )


def make_row(mod_id: str, **over: Any):
    """A ``ModRowVM`` with defaults for every field; ``over`` replaces any of them."""
    from src.ui.viewmodels import ModRowVM

    title = over.pop("title", mod_id.replace("_", " ").title())
    fields: dict[str, Any] = {
        "mod_id": ModId(mod_id),
        "title": title,
        "subtitle": "Local · Class",
        "folder": mod_id,
        "source_id": "local_folder",
        "source_label": "Local",
        "save_identity_text": f"{title} · mod_local_source",
        "tier_id": "class",
        "tier_badge": "CLS",
        "tier_label": "Class",
        "category_label": "Class",
        "color": "#A4B56C",
        "enabled": True,
        "is_new": False,
        "missing": False,
        "worst_severity": 0,
        "finding_count": 0,
        "finding_summary": "",
        "search_blob": f"{title} {mod_id}".casefold(),
        "sort_key": str(title).casefold(),
        "icon_path": None,
        "icon_stamp": None,
        "black_reliquary": False,
        "version_label": "1.0",
        "updated_label": "",
    }
    fields.update(over)
    return ModRowVM(**fields)


def make_rows(n: int, tiers: Sequence[tuple[str, str, str, str]] = TIER_CYCLE, **over: Any):
    pool = cycle(tiers)
    rows = []
    for i in range(n):
        tier_id, badge, label, color = next(pool)
        rows.append(
            make_row(
                f"mod_{i:03d}",
                title=f"Mod {i:03d}",
                tier_id=tier_id,
                tier_badge=badge,
                tier_label=label,
                category_label=label,
                color=color,
                **over,
            )
        )
    return rows


def make_status(**over: Any):
    from src.ui.viewmodels import StatusVM

    fields: dict[str, Any] = {
        "profile_label": "Slot 1 (Week 32)",
        "save_path": None,
        "last_backup": None,
        "counts": (0, 0, 0),
        "summary_text": "",
        "busy": False,
        "busy_text": "",
        "conflict": False,
        "direction_top_label": "Loads first",
        "direction_bottom_label": "Loads last",
        "direction_verified": True,
    }
    fields.update(over)
    return StatusVM(**fields)


def make_finding(key: str, severity: int, **over: Any):
    from src.core.findings import Severity
    from src.ui.viewmodels import FindingVM

    fields: dict[str, Any] = {
        "key": key,
        "rule_id": "core.test",
        "severity": Severity(severity),
        "message": f"Message of {key}",
        "mod_ids": (),
        "fix_label": None,
        "details": (),
    }
    fields.update(over)
    return FindingVM(**fields)


class FakeThumbs(QObject):
    """A ``ThumbnailSource``: never has a pixmap, can announce one is ready."""

    ready = Signal(str)

    def pixmap(self, mod_id: str, path: object, stamp: object, px: int = 0) -> None:
        return None


class FakePrompter:
    """Records every question; ``answers`` maps method name -> value | callable | list (queue)."""

    DEFAULTS: Mapping[str, object] = {
        "confirm_disable_active": True,
        "review_order_change": True,
        "resolve_state_conflict": "cancel",
        "confirm": True,
        "pick_save_file": None,
        "pick_folder": None,
        "pick_profile_file": None,
        "info": None,
        "error": None,
    }

    def __init__(self, answers: Mapping[str, object] | None = None) -> None:
        self.answers: dict[str, object] = {**self.DEFAULTS, **(answers or {})}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call[0] == name)

    def _ask(self, name: str, /, *args: Any, **kwargs: Any) -> Any:
        """Record and answer ``name``; the name is positional-only so a question's own ``name=``
        parameter (``confirm("...", name=file)``) cannot collide with it."""
        self.calls.append((name, args, kwargs))
        answer = self.answers[name]
        if callable(answer):
            return answer(*args, **kwargs)
        if isinstance(answer, list):
            return answer.pop(0) if len(answer) > 1 else answer[0]
        return answer

    def confirm_disable_active(self, titles: Sequence[str], slot_label: str) -> bool:
        return self._ask("confirm_disable_active", titles, slot_label)

    def review_order_change(self, vm: object, title_key: str) -> bool:
        return self._ask("review_order_change", vm, title_key)

    def review_patch(self, vm: object):
        from src.ui.ports import PatchDecision

        if "review_patch" not in self.answers:
            self.answers["review_patch"] = PatchDecision(True, frozenset(), False)
        return self._ask("review_patch", vm)

    def resolve_state_conflict(self) -> str:
        return self._ask("resolve_state_conflict")

    def confirm(self, key: str, **params: object) -> bool:
        return self._ask("confirm", key, **params)

    def info(self, key: str, **params: object) -> None:
        self._ask("info", key, **params)

    def error(self, key: str, details: str = "", **params: object) -> None:
        self._ask("error", key, details, **params)

    def pick_save_file(self, start_dir: object) -> object:
        return self._ask("pick_save_file", start_dir)

    def pick_folder(self, start_dir: object) -> object:
        return self._ask("pick_folder", start_dir)

    def pick_profile_file(self, save: bool) -> object:
        return self._ask("pick_profile_file", save)


def stamp(minutes_ago: int = 0) -> datetime:
    from datetime import timedelta

    return datetime.now().astimezone() - timedelta(minutes=minutes_ago)


def make_diff_vm(moved: int = 2, total: int = 5):
    from src.ui.viewmodels import OrderDiffRow, OrderDiffVM

    rows = tuple(
        OrderDiffRow(ModId(f"m{i}"), f"Mod {i}", i + 1, (i + 2) if i < moved else i + 1)
        for i in range(total)
    )
    return OrderDiffVM(rows=rows, moved_count=moved, total=total, added=0, removed=0)


def make_patch_vm(*, blocking: bool = False, acks: tuple[tuple[str, str], ...] = ()):
    from pathlib import Path

    from src.core.findings import Severity
    from src.ui.viewmodels import PatchPreviewVM

    findings = (make_finding("err", Severity.ERROR),) if blocking else ()
    return PatchPreviewVM(
        save_path=Path("C:/saves/profile_0/persist.game.json"),
        slot_label="Slot 1",
        backup_dir=Path("C:/data/backups"),
        before=("A", "B"),
        after=("B", "A", "C"),
        diff=make_diff_vm(),
        findings=findings,
        required_acks=acks,
        blocking=blocking,
    )


def action_specs_of(window) -> list:
    """``ActionSpec`` s mirroring the window's actions (for the shortcuts cheat sheet)."""
    from PySide6.QtGui import QAction

    from src.ui.widgets.actions import ActionSpec

    return [
        ActionSpec(
            key=a.property("ddm_key"), icon="", slot=lambda: None, shortcuts=tuple(a.shortcuts())
        )
        for a in window.findChildren(QAction)
        if a.property("ddm_key")
    ]
