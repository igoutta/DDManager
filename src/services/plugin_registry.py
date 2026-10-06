"""The collection plugins register into: mod sources, validation rules and save formats."""

from collections.abc import Iterable

from src.core.saves import SaveFormat
from src.core.validation import Rule
from src.services.errors import PluginLoadError
from src.services.sources import ModSource


class PluginRegistry:
    """Holds what plugins contribute; ids are unique per kind, a frozen registry is read-only.

    ``staging()`` returns a scratch registry that also checks ids against its parent, so a
    plugin's ``register()`` either contributes everything (``commit_into``) or nothing.
    """

    def __init__(self, parent: PluginRegistry | None = None) -> None:
        self._parent = parent
        self._frozen = False
        self._sources: list[ModSource] = []
        self._rules: list[Rule] = []
        self._formats: list[SaveFormat] = []

    @property
    def mod_sources(self) -> tuple[ModSource, ...]:
        return tuple(self._sources)

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(self._rules)

    @property
    def save_formats(self) -> tuple[SaveFormat, ...]:
        return tuple(self._formats)

    def _taken(self, kind: str) -> set[str]:
        own = {
            "mod_source": [s.source_id for s in self._sources],
            "rule": [r.rule_id for r in self._rules],
            "save_format": [f.format_id for f in self._formats],
        }[kind]
        inherited = self._parent._taken(kind) if self._parent is not None else set()
        return inherited | set(own)

    def _check_open(self, kind: str, ident: str) -> None:
        if self._frozen:
            raise PluginLoadError(f"The plugin registry is frozen; cannot add {kind} {ident!r}.")
        if ident in self._taken(kind):
            raise PluginLoadError(f"Duplicate {kind} id {ident!r}.", kind=kind, id=ident)

    def add_mod_source(self, source: ModSource) -> None:
        self._check_open("mod_source", source.source_id)
        self._sources.append(source)

    def add_rule(self, rule: Rule) -> None:
        self._check_open("rule", rule.rule_id)
        self._rules.append(rule)

    def add_save_format(self, fmt: SaveFormat) -> None:
        self._check_open("save_format", fmt.format_id)
        self._formats.append(fmt)

    def staging(self) -> PluginRegistry:
        return PluginRegistry(parent=self)

    def contributed(self) -> tuple[str, ...]:
        """``kind:id`` labels of everything this registry itself holds."""
        return (
            *(f"mod_source:{s.source_id}" for s in self._sources),
            *(f"rule:{r.rule_id}" for r in self._rules),
            *(f"save_format:{f.format_id}" for f in self._formats),
        )

    def commit_into(self, parent: PluginRegistry) -> tuple[str, ...]:
        """Move every contribution into ``parent`` (all or nothing); returns what moved."""
        _check_all(parent, "mod_source", [s.source_id for s in self._sources])
        _check_all(parent, "rule", [r.rule_id for r in self._rules])
        _check_all(parent, "save_format", [f.format_id for f in self._formats])
        for source in self._sources:
            parent.add_mod_source(source)
        for rule in self._rules:
            parent.add_rule(rule)
        for fmt in self._formats:
            parent.add_save_format(fmt)
        return self.contributed()

    def freeze(self) -> None:
        self._frozen = True


def _check_all(parent: PluginRegistry, kind: str, idents: Iterable[str]) -> None:
    for ident in idents:
        parent._check_open(kind, ident)
