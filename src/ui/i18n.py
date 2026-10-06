"""Key-based translator over the JSON catalogs in ``src/resources/i18n``."""

import json
from collections.abc import Mapping
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Final, Self

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QObject, QTranslator, Signal

DEFAULT_LANGUAGE: Final = "en"

type Catalog = Mapping[str, str]


def _catalog_dir() -> Traversable:
    # src/resources has no __init__.py, so reach it through the ``src`` package.
    return resources.files("src") / "resources" / "i18n"


def _read_catalog(code: str) -> dict[str, str]:
    path = _catalog_dir() / f"{code}.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"i18n catalog {code}.json must be a JSON object")
    return {str(k): v for k, v in raw.items() if isinstance(v, str)}


def available_languages() -> tuple[str, ...]:
    """Language codes that ship a catalog file."""
    names = [
        item.name.removesuffix(".json")
        for item in _catalog_dir().iterdir()
        if item.name.endswith(".json")
    ]
    return tuple(sorted(names))


class Translator(QObject):
    """``tr(key, **params)``: language -> fallback -> the key itself, tolerant of bad templates."""

    languageChanged = Signal(str)

    def __init__(
        self,
        catalogs: Mapping[str, Catalog],
        language: str = DEFAULT_LANGUAGE,
        *,
        fallback: str = DEFAULT_LANGUAGE,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalogs: dict[str, Catalog] = dict(catalogs)
        self._language = language
        self._fallback = fallback
        self._qt_translator: QTranslator | None = None

    @classmethod
    def from_resources(cls, language: str, *, fallback: str = DEFAULT_LANGUAGE) -> Self:
        codes = {language, fallback, *available_languages()}
        catalogs = {code: _read_catalog(code) for code in sorted(codes)}
        translator = cls(catalogs, language, fallback=fallback)
        translator._install_qt_translator()
        return translator

    def tr(self, key: str, **params: object) -> str:  # ty: ignore[invalid-method-override]
        template = self._lookup(key)
        if template is None:
            return key
        if not params:
            return template
        try:
            return template.format(**params)
        except KeyError, IndexError, ValueError:
            return template

    def _lookup(self, key: str) -> str | None:
        for code in (self._language, self._fallback):
            value = self._catalogs.get(code, {}).get(key)
            if value is not None:
                return value
        return None

    def has(self, key: str) -> bool:
        return self._lookup(key) is not None

    def language(self) -> str:
        return self._language

    def languages(self) -> tuple[str, ...]:
        return tuple(sorted(code for code, catalog in self._catalogs.items() if catalog))

    def set_language(self, code: str) -> None:
        if code not in self._catalogs:
            self._catalogs[code] = _read_catalog(code)
        self._language = code
        self._install_qt_translator()
        self.languageChanged.emit(code)

    def _install_qt_translator(self) -> None:
        """Swap the ``qtbase_<lang>.qm`` translator so stock dialog buttons follow the language."""
        app = QCoreApplication.instance()
        if app is None:
            return
        if self._qt_translator is not None:
            app.removeTranslator(self._qt_translator)
            self._qt_translator = None
        translator = QTranslator(self)
        directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(f"qtbase_{self._language}", directory):
            app.installTranslator(translator)
            self._qt_translator = translator
