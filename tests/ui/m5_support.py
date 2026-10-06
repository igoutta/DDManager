"""Harness of the M5 (feature parity) tests: ONE place that knows the names the contract left open.

What the contract fixes is asserted precisely in the tests; what it leaves open (window action
keys, dialog/presenter constructor parameter names, message keys) is looked up here:

* ``ACTION_KEYS``: candidate ``ddm_key`` names of the window actions.
* ``NOTICE_KEYS``: the exact catalog key a user-visible notice is expected to carry.
* ``construct``: builds a dialog by matching its ``__init__`` parameter NAMES (like
  ``helpers.build`` but exact names first, so a ``presenter`` parameter gets the right one).
* ``Messages``: one chronological log of everything the user was told (controller notices,
  ``Prompter.info/error`` calls and ``QMessageBox`` static calls), rendered with the translator.
* ``DialogDriver``: ``QDialog.exec`` replacement that records the dialog and runs a script on it,
  so window actions that open modal dialogs can be driven without an event loop.
* ``RecordingPrompter``: the shared ``FakePrompter`` that also records (and answers) prompter
  methods that did not exist when the fake was written.
"""

import functools
import inspect
import json
import re
from annotationlib import Format
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractButton,
    QColorDialog,
    QDialog,
    QFileDialog,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTableWidget,
    QTabWidget,
    QWidget,
)

from src.ui.i18n import Translator
from tests.ui.helpers import FakePrompter

I18N_DIR = Path(__file__).parents[2] / "src" / "resources" / "i18n"
LANGUAGES = ("en", "zh_CN", "pt_PT", "es_ES")

# ---------------------------------------------------------------------------- open names

ACTION_KEYS: Mapping[str, tuple[str, ...]] = {
    "categories": ("categories", "edit_categories"),
    "paths": ("paths", "file_paths", "edit_paths"),
    "auto_detect": ("auto_detect", "autodetect", "auto_detect_paths", "detect_paths"),
    "settings": ("settings", "preferences", "options"),
    "nickname": ("nickname", "set_nickname", "rename_mod"),
    "apply_order": ("apply_order", "apply_folder_order", "apply_order_folders", "apply_folders"),
    "save_code": ("save_code", "generate_save_code"),
    "check_setup": ("check_setup", "diagnostics", "setup"),
    "copy_debug": ("copy_debug", "copy_debug_info", "debug_info"),
    "auto_categorize": ("auto_categorize", "autocategorize"),
    "launch_game": ("launch_game",),
    "open_local_mods": ("open_local_mods",),
    "forget_missing": ("forget_missing",),
}

NOTICE_KEYS: Mapping[str, str] = {
    # exact catalog keys of the notices the tests look for (existing keys first)
    "no_change": "ui.notice.no_change",
    "action_failed": "ui.notice.action_failed",
    "restored": "ui.notice.restored",
    "import_unmatched": "ui.notice.import_unmatched",
    "profile_saved": "ui.notice.profile_saved",
    "nickname_set": "ui.notice.nickname_set",
    "nickname_cleared": "ui.notice.nickname_cleared",
    "paths_saved": "ui.notice.paths_saved",
    "copied": "ui.notice.copied",
}


def load_attr(module: str, name: str) -> Any:
    """``module.name`` with a failure that says which M5 piece is missing."""
    try:
        return getattr(import_module(module), name)
    except (ImportError, AttributeError) as exc:
        raise AssertionError(f"M5 contract: {module}.{name} is missing ({exc})") from exc


def en_catalog() -> dict[str, str]:
    return json.loads((I18N_DIR / "en.json").read_text(encoding="utf-8"))


def catalog_of(language: str) -> dict[str, str]:
    return json.loads((I18N_DIR / f"{language}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------- constructors

_ALIASES = {"tr": "translator", "theme": "tokens", "icon_set": "icons", "owner": "parent"}


def construct[T](cls: Callable[..., T], **available: object) -> T:
    """Instantiate ``cls`` from the ``available`` objects its parameter names ask for.

    Unlike ``helpers.build`` the names are matched exactly first (``presenter`` means the
    presenter the caller passed, not the profiles presenter), then through a few aliases.
    """
    kwargs: dict[str, object] = {}
    signature = inspect.signature(cls, annotation_format=Format.FORWARDREF)
    for name, param in signature.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        key = name if name in available else _ALIASES.get(name, name)
        if key in available:
            kwargs[name] = available[key]
        elif param.default is param.empty:
            raise TypeError(
                f"{getattr(cls, '__name__', cls)} needs parameter {name!r}; "
                f"the harness only knows {sorted(available)}"
            )
    return cls(**kwargs)


# ---------------------------------------------------------------------------- prompter


class RecordingPrompter(FakePrompter):
    """``FakePrompter`` plus every prompter method it does not know yet.

    An unknown method records its call (``calls``) and answers ``True`` for questions
    (``confirm*``, ``review*``, ``ask*``, ``approve*``) and ``None`` for everything else,
    unless ``answers`` says otherwise.
    """

    DEFAULTS = {**FakePrompter.DEFAULTS, "confirm": True, "review_rename": True}  # noqa: RUF012

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_") or name in {"answers", "calls"}:
            raise AttributeError(name)
        return functools.partial(self._ask_unknown, name)

    def _ask(self, method: str, /, *args: Any, **kwargs: Any) -> Any:
        """``FakePrompter._ask`` with a positional-only name: a ``name=`` parameter of the
        question itself (``confirm("...", name=file)``) must not collide with it."""
        self.calls.append((method, args, kwargs))
        answer = self.answers[method]
        if callable(answer):
            return answer(*args, **kwargs)
        if isinstance(answer, list):
            return answer.pop(0) if len(answer) > 1 else answer[0]
        return answer

    def _ask_unknown(self, method: str, /, *args: Any, **kwargs: Any) -> Any:
        if method not in self.answers:
            question = method.startswith(("confirm", "review", "ask", "approve"))
            self.answers[method] = True if question else None
        return self._ask(method, *args, **kwargs)

    def calls_named(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for call, args, kwargs in self.calls if call == name]

    def confirm_keys(self) -> list[str]:
        return [str(args[0]) for args, _ in self.calls_named("confirm")]

    def objects_of(self, kind: type) -> list[Any]:
        """Every argument of every recorded call that is an instance of ``kind`` (a VM)."""
        return [
            arg
            for _name, args, kwargs in self.calls
            for arg in (*args, *kwargs.values())
            if isinstance(arg, kind)
        ]


# ---------------------------------------------------------------------------- messages


@dataclass(frozen=True, slots=True)
class Msg:
    """One thing the user was told: where, which catalog key, its parameters, its rendering."""

    channel: str  # "notice" | "prompt" | "qt"
    name: str  # "notice" | "info" | "error" | "information" | "warning" | ...
    key: str
    params: Mapping[str, Any]
    level: str
    text: str


@dataclass
class Messages:
    """Chronological log of controller notices, ``Prompter.info/error`` and ``QMessageBox``."""

    translator: Translator
    log: list[Msg] = field(default_factory=list)
    confirm_answer: bool = True

    def attach(self, controller: Any, prompter: FakePrompter, monkeypatch: Any) -> None:
        controller.notice.connect(self._on_notice)
        original = prompter._ask

        def spy(method: str, /, *args: Any, **kwargs: Any) -> Any:
            if method in {"info", "error"}:
                self._record_prompt(method, args, kwargs)
            return original(method, *args, **kwargs)

        monkeypatch.setattr(prompter, "_ask", spy)
        self._patch_qt(monkeypatch)

    def _on_notice(self, notice: Any) -> None:
        params = dict(notice.params)
        self.log.append(
            Msg(
                "notice",
                "notice",
                notice.key,
                params,
                notice.level,
                self.translator.tr(notice.key, **params),
            )
        )

    def _record_prompt(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        key = str(args[0])
        params = dict(kwargs)
        if name == "error" and len(args) > 1 and args[1]:
            params["details"] = args[1]
        level = "error" if name == "error" else "info"
        self.log.append(Msg("prompt", name, key, params, level, self.translator.tr(key, **kwargs)))

    def _patch_qt(self, monkeypatch: Any) -> None:
        for name, level in (
            ("information", "info"),
            ("warning", "warning"),
            ("critical", "error"),
        ):
            monkeypatch.setattr(QMessageBox, name, staticmethod(self._qt_box(name, level)))
        monkeypatch.setattr(QMessageBox, "question", staticmethod(self._qt_question))

    def _qt_box(self, name: str, level: str) -> Callable[..., Any]:
        def show(_parent: Any, title: str = "", text: str = "", *_rest: Any) -> Any:
            self.log.append(Msg("qt", name, "", {"title": title}, level, str(text)))
            return QMessageBox.StandardButton.Ok

        return show

    def _qt_question(self, _parent: Any, title: str = "", text: str = "", *_rest: Any) -> Any:
        self.log.append(Msg("qt", "question", "", {"title": title}, "info", str(text)))
        yes = QMessageBox.StandardButton.Yes
        return yes if self.confirm_answer else QMessageBox.StandardButton.No

    # ------------------------------------------------------------------ queries

    def keys(self) -> list[str]:
        return [m.key for m in self.log if m.key]

    def texts(self) -> list[str]:
        return [m.text for m in self.log]

    def with_key(self, key: str) -> list[Msg]:
        return [m for m in self.log if m.key == key]

    def only(self, key: str) -> Msg:
        found = self.with_key(key)
        assert len(found) == 1, f"expected exactly one {key!r}, the user was told: {self.keys()}"
        return found[0]

    def clear(self) -> None:
        self.log.clear()


# ---------------------------------------------------------------------------- dialogs


class DialogDriver:
    """Replaces ``QDialog.exec``: records the dialog, runs the matching script, returns its result.

    A dialog nobody scripted comes back ``Rejected`` (the user closed it).  Scripts get the
    dialog and typically fill widgets, click a button and call ``accept()``.
    """

    def __init__(self) -> None:
        self.opened: list[QDialog] = []
        self._scripts: list[tuple[Callable[[QDialog], bool], Callable[[QDialog], None]]] = []

    def install(self, monkeypatch: Any) -> None:
        driver = self

        def fake_exec(dialog: QDialog) -> int:
            driver.opened.append(dialog)
            for matches, script in driver._scripts:
                if matches(dialog):
                    script(dialog)
                    break
            return int(dialog.result())

        monkeypatch.setattr(QDialog, "exec", fake_exec)

    def on(self, kind: type | str, script: Callable[[Any], None]) -> None:
        """Run ``script`` for the next dialogs that are an instance of ``kind`` (or named so)."""
        if isinstance(kind, str):
            self._scripts.insert(0, (lambda d: type(d).__name__ == kind, script))
        else:
            self._scripts.insert(0, (lambda d: isinstance(d, kind), script))

    def accept_all(self, kind: type | str) -> None:
        self.on(kind, lambda dialog: dialog.accept())

    def last(self, kind: type | str | None = None) -> QDialog:
        pool = [
            d
            for d in self.opened
            if kind is None
            or (type(d).__name__ == kind if isinstance(kind, str) else isinstance(d, kind))
        ]
        assert pool, f"no {kind!r} dialog was opened; opened: {self.names()}"
        return pool[-1]

    def names(self) -> list[str]:
        return [type(d).__name__ for d in self.opened]


class StaticPrompts:
    """The Qt statics a dialog may use for small questions, with scripted answers."""

    def __init__(self) -> None:
        self.text_answers: list[str | None] = []
        self.colors: list[str | None] = []
        self.texts_asked: list[tuple[str, str, str]] = []
        self.colors_asked: list[str] = []
        self.folders: list[str] = []
        self.files: list[str] = []

    def install(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(self._get_text))
        monkeypatch.setattr(QColorDialog, "getColor", staticmethod(self._get_color))
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(self._get_dir))
        monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(self._get_file))

    def _get_text(self, _parent: Any, title: str = "", label: str = "", *rest: Any, **kw: Any):
        initial = kw.get("text") or (rest[1] if len(rest) > 1 else "")
        self.texts_asked.append((title, label, str(initial)))
        answer = self.text_answers.pop(0) if self.text_answers else None
        return ("", False) if answer is None else (answer, True)

    def _get_color(self, initial: Any = None, *_rest: Any, **_kw: Any) -> QColor:
        name = initial.name() if isinstance(initial, QColor) else str(initial)
        self.colors_asked.append(name)
        answer = self.colors.pop(0) if self.colors else None
        return QColor() if answer is None else QColor(answer)

    def _get_dir(self, *_args: Any, **_kw: Any) -> str:
        return self.folders.pop(0) if self.folders else ""

    def _get_file(self, *_args: Any, **_kw: Any) -> tuple[str, str]:
        return (self.files.pop(0), "") if self.files else ("", "")


# ---------------------------------------------------------------------------- widgets


def plain(text: str) -> str:
    """A label without its keyboard accelerator marker and surrounding space."""
    return text.replace("&", "").strip()


def buttons_of(root: QWidget) -> list[QAbstractButton]:
    return [b for b in root.findChildren(QAbstractButton) if not b.objectName().startswith("qt_")]


def find_buttons(root: QWidget, *texts: str) -> list[QAbstractButton]:
    wanted = {t.casefold() for t in texts}
    return [b for b in buttons_of(root) if plain(b.text()).casefold() in wanted]


def find_button(root: QWidget, *texts: str) -> QAbstractButton:
    """The single button whose visible text is one of ``texts`` (case-insensitive)."""
    found = find_buttons(root, *texts)
    assert len(found) == 1, (
        f"expected one button named {texts}, found {[b.text() for b in found]}; "
        f"all buttons: {[plain(b.text()) for b in buttons_of(root)]}"
    )
    return found[0]


def button_in_row(root: QWidget, line_edit: QLineEdit, *texts: str) -> QAbstractButton:
    """The button named ``texts`` that sits on the same visual line as ``line_edit``."""
    assert root.isVisible(), "show() the dialog before looking for widgets by position"
    top = line_edit.mapTo(root, line_edit.rect().topLeft()).y()
    bottom = top + line_edit.height()
    row = [
        b
        for b in find_buttons(root, *texts)
        if top - 4 <= b.mapTo(root, b.rect().center()).y() <= bottom + 4
    ]
    assert len(row) == 1, f"buttons {texts} on the line of {line_edit.text()!r}: {row}"
    return row[0]


def visible_texts(root: QWidget) -> list[str]:
    """Every label/button/table/list text of ``root`` (for 'the dialog shows X' assertions)."""
    from PySide6.QtWidgets import QListWidget, QPlainTextEdit

    out = [w.text() for w in root.findChildren(QLabel)]
    out += [b.text() for b in buttons_of(root)]
    out += [w.toPlainText() for w in root.findChildren(QPlainTextEdit)]
    for table in root.findChildren(QTableWidget):
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item is not None:
                    out.append(item.text())
    for lst in root.findChildren(QListWidget):
        out += [lst.item(r).text() for r in range(lst.count())]
    return out


# ---------------------------------------------------------------------------- retranslation


def _snapshot(root: QWidget) -> list[tuple[Any, str, str]]:
    """``(object, kind, text)`` of every translatable text of ``root``, in a stable order."""
    items: list[tuple[Any, str, str]] = []

    def add(obj: Any, kind: str, text: str) -> None:
        text = plain(text)
        if text:
            items.append((obj, kind, text))

    add(root, "window", root.windowTitle())
    for label in root.findChildren(QLabel):
        if label.textFormat() != label.textFormat().RichText:
            add(label, "label", label.text())
    for button in buttons_of(root):
        add(button, "button", button.text())
        add(button, "button_tip", button.toolTip())
    for box in root.findChildren(QGroupBox):
        add(box, "group", box.title())
    for tabs in root.findChildren(QTabWidget):
        for i in range(tabs.count()):
            add((tabs, i), "tab", tabs.tabText(i))
    for menu in root.findChildren(QMenu):
        add(menu, "menu", menu.title())
    for action in root.findChildren(QAction):
        if action.property("ddm_key"):
            add(action, "action", action.text())
    for table in root.findChildren(QTableWidget):
        for c in range(table.columnCount()):
            header = table.horizontalHeaderItem(c)
            if header is not None:
                add((table, c), "header", header.text())
    return items


_CURRENT: Mapping[str, Callable[[Any], str]] = {
    "window": lambda o: o.windowTitle(),
    "label": lambda o: o.text(),
    "button": lambda o: o.text(),
    "button_tip": lambda o: o.toolTip(),
    "group": lambda o: o.title(),
    "tab": lambda o: o[0].tabText(o[1]),
    "menu": lambda o: o.title(),
    "action": lambda o: o.text(),
    "header": lambda o: o[0].horizontalHeaderItem(o[1]).text(),
}


def _now(obj: Any, kind: str) -> str:
    return plain(_CURRENT[kind](obj))


@dataclass(frozen=True, slots=True)
class LanguageCheck:
    checked: int
    changed: int
    unchanged: list[str]


def _is_chrome_tip(kind: str, text: str, chrome: set[str]) -> bool:
    """The generic tooltips Qt's own unlabeled buttons get (``ui.window.*.tip``)."""
    return kind == "button_tip" and text in chrome


def follow_language(
    root: QWidget, translator: Translator, language: str, *, chrome: bool = False
) -> LanguageCheck:
    """Switch ``translator`` to ``language`` and prove every label of ``root`` followed.

    With ``chrome`` only the generic tooltips of Qt's own buttons are checked, otherwise they are
    left out (they are a separate concern: nobody labels those buttons by hand).
    Each text that was an English catalog template (no placeholders) must afterwards equal
    ``translator.tr(key)`` for one of the keys that had that text: the translated string when
    the catalog of ``language`` has the key, the English fallback while it does not.  Where the
    language does have a real translation for all candidate keys the text must also differ.
    """
    en = en_catalog()
    by_text: dict[str, list[str]] = defaultdict(list)
    for key, value in en.items():
        by_text[plain(value)].append(key)
    other = catalog_of(language) if language != "en" else {}
    chrome_texts = {
        plain(v) for k, v in en.items() if k.startswith("ui.window.") and k.endswith(".tip")
    }
    before = [
        item for item in _snapshot(root) if _is_chrome_tip(item[1], item[2], chrome_texts) == chrome
    ]
    translator.set_language(language)
    settle()
    checked = changed = 0
    unchanged: list[str] = []
    for obj, kind, old in before:
        keys = by_text.get(old)
        if not keys:
            continue
        try:
            new = _now(obj, kind)
        except RuntimeError:  # the widget was replaced by a fresh one while re-translating
            continue
        expected = {plain(translator.tr(k)) for k in keys}
        assert new in expected, f"{kind} {old!r} became {new!r}; expected one of {sorted(expected)}"
        checked += 1
        real = all(other.get(k, en[k]) != en[k] for k in keys)
        if new != old:
            changed += 1
        elif real:
            unchanged.append(f"{kind} {old!r}")
    return LanguageCheck(checked, changed, unchanged)


# ---------------------------------------------------------------------------- misc


def action_for(window: Any, name: str) -> QAction:
    """The window action called ``name`` (see ``ACTION_KEYS`` for the accepted ``ddm_key`` s)."""
    keys = ACTION_KEYS.get(name, (name,))
    hub = window.hub.actions
    for key in keys:
        if key in hub:
            return hub[key]
    raise AssertionError(
        f"M5 contract: the window has no action for {name!r} (tried {list(keys)}); "
        f"it has {sorted(hub)}"
    )


def trigger(window: Any, name: str) -> QAction:
    action = action_for(window, name)
    assert action.isEnabled(), f"action {name!r} is disabled"
    action.trigger()
    return action


def names_of(items: Iterable[Any]) -> list[str]:
    return [str(i) for i in items]


def tr_all(translator: Translator, keys: Sequence[str], **params: object) -> list[str]:
    return [translator.tr(key, **params) for key in keys]


# ---------------------------------------------------------------------------- the rig


@dataclass(slots=True)
class Rig:
    """A controller (and optionally a window) over fake services, plus every recorder."""

    services: Any
    controller: Any
    prompter: RecordingPrompter
    translator: Translator
    messages: Messages
    driver: DialogDriver
    prompts: StaticPrompts
    window: Any = None

    @property
    def state(self) -> Any:
        """The fake state repository (``saves`` = every ``StateChanges`` written)."""
        return self.services.state

    def flush(self) -> Any:
        """Write the pending state now and return the document as the 'file' now holds it."""
        assert self.controller.flush()
        return self.services.state.doc

    @property
    def mods(self) -> Mapping[Any, Any]:
        return self.services.catalog

    def settings_written(self) -> dict[str, Any]:
        self.controller.flush()
        return self.services.state.settings_written()


def tool_dialog(rig: Rig, action: str, dialog_cls: type, vm_cls: type) -> Any:
    """Trigger window action ``action`` and return the dialog it ends up showing.

    The window may open the dialog itself (captured by the driver) or hand a view model to the
    prompter; in that case the dialog is built from the model exactly like ``QtPrompter`` would.
    """
    seen = len(rig.prompter.calls)
    trigger(rig.window, action)
    opened = [d for d in rig.driver.opened if isinstance(d, dialog_cls)]
    if opened:
        return opened[-1]
    models = [
        arg
        for _name, args, kwargs in rig.prompter.calls[seen:]
        for arg in (*args, *kwargs.values())
        if isinstance(arg, vm_cls)
    ]
    assert models, (
        f"action {action!r} showed no {dialog_cls.__name__}; "
        f"prompter calls: {[c[0] for c in rig.prompter.calls[seen:]]}, "
        f"dialogs: {rig.driver.names()}, told: {rig.messages.texts()}"
    )
    return construct(
        dialog_cls,
        vm=models[-1],
        translator=rig.translator,
        icons=rig.window.icons,
        parent=rig.window,
    )


def shown_models(rig: Rig, action: str, vm_cls: type) -> list[Any]:
    """The ``vm_cls`` view models the prompter received while ``action`` ran (may be empty)."""
    seen = len(rig.prompter.calls)
    trigger(rig.window, action)
    return [
        arg
        for _name, args, kwargs in rig.prompter.calls[seen:]
        for arg in (*args, *kwargs.values())
        if isinstance(arg, vm_cls)
    ]


RAW_KEY = re.compile(r"^ui\.[a-z0-9_]+(\.[a-z0-9_]+)+$")


def assert_no_raw_keys(root: QWidget) -> None:
    """No label, button or title shows a catalog key because its text is missing from en.json."""
    shown = [text for _obj, _kind, text in _snapshot(root)]
    shown += [plain(t) for t in visible_texts(root)]
    leaked = sorted({t for t in shown if RAW_KEY.match(t)})
    assert not leaked, f"{type(root).__name__} shows raw catalog keys: {leaked}"


def popup_actions(open_menu: Callable[[], object]) -> list[QAction]:
    """The actions of the popup menu that ``open_menu()`` shows (it blocks in ``QMenu.exec``).

    ``QMenu.exec`` cannot be replaced, so a timer grabs the active popup from inside its event
    loop and closes it.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    seen: list[QAction] = []
    attempts = [0]

    def grab() -> None:
        menu = QApplication.activePopupWidget()
        if menu is None:
            attempts[0] += 1
            if attempts[0] < 100:
                QTimer.singleShot(10, grab)
            return
        seen.extend(menu.actions())
        menu.close()

    QTimer.singleShot(0, grab)
    open_menu()
    return seen


def texts_of(root: QWidget) -> list[str]:
    """Every translatable text of ``root`` (labels, buttons, tips, titles, actions, headers)."""
    return [text for _obj, _kind, text in _snapshot(root)]


def settle() -> None:
    """Run what a language switch leaves queued: deferred deletes of replaced widgets, slots."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
