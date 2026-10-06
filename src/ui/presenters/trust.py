"""Trust presenter: which user plugin / rule files may run (opt-in, hash-pinned).

The state lives in ``settings.json`` (``Settings.plugins`` / ``Settings.rules``, a
:class:`~src.services.settings_repo.PluginTrust` each): code only runs when the switch is on AND
the file's sha256 is the approved one.  Changes are saved at once and take effect the next time
DD Manager starts, because the registry is frozen after start-up.
"""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from PySide6.QtCore import QObject, Signal

from src.services.plugin_loader import plugin_files, sha256_of
from src.services.settings_repo import PluginTrust

if TYPE_CHECKING:
    from src.ui.controller import MainController

type Kind = Literal["plugins", "rules"]

KINDS: Final[tuple[Kind, ...]] = ("plugins", "rules")
NEEDS_APPROVAL: Final = frozenset({"not_approved", "changed"})


@dataclass(frozen=True, slots=True)
class TrustFileVM:
    kind: Kind
    name: str
    sha256: str
    status: str
    """``approved``, ``not_approved``, ``changed``, ``disabled``, ``unreadable``, or the status a
    start-up record carries (``loaded``, ``failed``, ``incompatible``)."""


def trust_status(name: str, digest: str | None, trust: PluginTrust) -> str:
    """What the loader would decide for a file with ``digest`` under ``trust``."""
    if digest is None:
        return "unreadable"
    if name in trust.disabled:
        return "disabled"
    approved = trust.approved.get(name)
    if approved is None:
        return "not_approved"
    return "approved" if approved == digest else "changed"


def _digest(path: Path) -> str | None:
    try:
        return sha256_of(path)
    except OSError:
        return None


class TrustPresenter(QObject):
    changed = Signal()

    def __init__(self, controller: MainController) -> None:
        super().__init__(controller)
        self._c = controller

    # ------------------------------------------------------------------ the switches

    def trust(self, kind: Kind) -> PluginTrust:
        settings = self._c.settings.current()
        return settings.plugins if kind == "plugins" else settings.rules

    def directory(self, kind: Kind) -> Path:
        paths = self._c.services.paths
        return paths.plugins_dir if kind == "plugins" else paths.rules_dir

    def enabled(self, kind: Kind) -> bool:
        return self.trust(kind).enabled

    def set_enabled(self, kind: Kind, *, on: bool) -> bool:
        return self._store(kind, replace(self.trust(kind), enabled=on))

    def _store(self, kind: Kind, trust: PluginTrust) -> bool:
        presenter = self._c.settings
        presenter.save(replace(presenter.current(), **{kind: trust}))
        stored = self.trust(kind) == trust
        self.changed.emit()
        return stored

    # ------------------------------------------------------------------ files

    def files(self, kind: Kind) -> list[TrustFileVM]:
        """Every ``*.py`` file of the plugin or rule folder with its current status."""
        trust = self.trust(kind)
        rows: list[TrustFileVM] = []
        for path in plugin_files(self.directory(kind)):
            digest = _digest(path)
            rows.append(
                TrustFileVM(kind, path.name, digest or "", trust_status(path.name, digest, trust))
            )
        return rows

    def approve(self, kind: Kind, name: str, *, expected: str | None = None) -> bool:
        """Pin the file's current sha256 (refused when it is not the one the user looked at)."""
        if Path(name).name != name:
            return False
        digest = _digest(self.directory(kind) / name)
        if digest is None:
            self._c.post("ui.notice.trust_unreadable", "error", name=name)
            return False
        if expected is not None and digest != expected:
            self._c.post("ui.notice.trust_stale", "warning", name=name)
            self.changed.emit()
            return False
        trust = self.trust(kind)
        approved = {**trust.approved, name: digest}
        return self._store(
            kind, replace(trust, approved=approved, disabled=trust.disabled - {name})
        )

    def revoke(self, kind: Kind, name: str) -> bool:
        trust = self.trust(kind)
        approved = {key: value for key, value in trust.approved.items() if key != name}
        return self._store(kind, replace(trust, approved=approved))

    # ------------------------------------------------------------------ start-up records

    def records(self) -> list[TrustFileVM]:
        """The user files of the last start-up (only exist while the switch was on)."""
        services = self._c.services
        rules_dir = services.paths.rules_dir
        rows: list[TrustFileVM] = []
        for record in services.plugin_records:
            if record.origin != "user" or record.path is None:
                continue
            kind: Kind = "rules" if record.path.parent == rules_dir else "plugins"
            status = record.status
            if status in NEEDS_APPROVAL:
                status = trust_status(record.path.name, record.sha256, self.trust(kind))
            rows.append(TrustFileVM(kind, record.path.name, record.sha256 or "", status))
        return rows

    def needs_approval(self) -> bool:
        return any(row.status in NEEDS_APPROVAL for row in self.records())

    def approve_pending(self) -> int:
        """Approve every listed file that still needs it; returns how many were pinned."""
        count = 0
        for row in self.records():
            if row.status in NEEDS_APPROVAL and self.approve(
                row.kind, row.name, expected=row.sha256
            ):
                count += 1
        return count
