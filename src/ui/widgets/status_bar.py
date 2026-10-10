"""The status bar: slot, save path, last backup, finding counts, busy indicator, conflict banner."""

from datetime import datetime
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QToolButton,
    QWidget,
)

from src.ui.i18n import Translator
from src.ui.theme.theme import set_role
from src.ui.theme.tokens import ThemeTokens
from src.ui.viewmodels import StatusVM
from src.ui.widgets.actions import IconSet
from src.ui.widgets.elided_label import ElidedLabel

MESSAGE_MS: Final = 6000
_MINUTE: Final = 60
_HOUR: Final = 3600
_DAY: Final = 86400
_TONES: Final = ("error", "warning", "info")
_SAVE_PATH_MIN_PX: Final = 160
_SAVE_PATH_MAX_PX: Final = 420


def ago_text(created: datetime, now: datetime, tr: Translator) -> str:
    """``3 min ago`` style text for a backup time."""
    seconds = max(0, int((now - created).total_seconds()))
    if seconds < _MINUTE:
        return tr.tr("ui.status.ago.now")
    if seconds < _HOUR:
        return tr.tr("ui.status.ago.minutes", count=seconds // _MINUTE)
    if seconds < _DAY:
        return tr.tr("ui.status.ago.hours", count=seconds // _HOUR)
    return tr.tr("ui.status.ago.days", count=seconds // _DAY)


class AppStatusBar(QStatusBar):
    countsClicked = Signal()
    saveFolderRequested = Signal()
    reloadRequested = Signal()
    keepMineRequested = Signal()

    def __init__(
        self,
        translator: Translator,
        tokens: ThemeTokens,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = translator
        self._tokens = tokens
        self._vm: StatusVM | None = None
        self.profile = QLabel(self)
        self.save_path = ElidedLabel("", self, minimum_px=_SAVE_PATH_MIN_PX)
        self.backup = QLabel(self)
        self._icons = icons
        self.counts = QToolButton(self)
        self.counts.setObjectName("status_counts")
        self.counts.setAutoRaise(True)
        self.counts.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.counts.clicked.connect(self.countsClicked)
        self.busy_text = QLabel(self)
        self.busy_bar = QProgressBar(self)
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setMaximumWidth(90)
        self.busy_bar.setTextVisible(False)
        self.conflict = self._conflict_banner()
        self.save_path.doubleClicked.connect(self.saveFolderRequested)
        self.save_path.setMaximumWidth(_SAVE_PATH_MAX_PX)
        # Everything is permanent: a transient ``showMessage`` must never hide any of it.  The
        # labels keep their size hints (the path shrinks to its minimum first) and a thin line
        # separates them, so they never overlap.
        self.addPermanentWidget(self.conflict)
        for widget in (self.profile, self.save_path, self.backup, self.counts):
            self.addPermanentWidget(self._separator())
            self.addPermanentWidget(widget)
        for widget in (self.busy_text, self.busy_bar):
            self.addPermanentWidget(widget)
        self.setSizeGripEnabled(False)
        self.retranslate_ui()

    def _separator(self) -> QFrame:
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setFixedWidth(1)
        line.setStyleSheet(f"color: {self._tokens.palette.border};")
        return line

    def _conflict_banner(self) -> QWidget:
        banner = QWidget(self)
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(0, 0, 0, 0)
        self.conflict_label = QLabel(banner)
        set_role(self.conflict_label, "warning")
        self.reload_button = QPushButton(banner)
        self.keep_button = QPushButton(banner)
        self.reload_button.clicked.connect(self.reloadRequested)
        self.keep_button.clicked.connect(self.keepMineRequested)
        for widget in (self.conflict_label, self.reload_button, self.keep_button):
            layout.addWidget(widget)
        banner.setVisible(False)
        return banner

    # ------------------------------------------------------------------ rendering

    def set_status(self, vm: StatusVM, now: datetime | None = None) -> None:
        self._vm = vm
        tr = self._tr.tr
        self.profile.setText(vm.profile_label)
        self.profile.setToolTip(tr("ui.status.profile.tip", summary=vm.summary_text))
        path = str(vm.save_path) if vm.save_path else tr("ui.status.no_save")
        self.save_path.setText(path)
        self.save_path.setToolTip(tr("ui.status.save_path.tip", path=path))
        self._set_backup(vm.last_backup, now or datetime.now().astimezone())
        self._set_counts(vm.counts)
        self.busy_bar.setVisible(vm.busy)
        self.busy_text.setVisible(vm.busy)
        self.busy_text.setText(vm.busy_text)
        self.busy_text.setToolTip(tr("ui.status.busy.tip"))
        self.conflict.setVisible(vm.conflict)

    def _set_backup(self, created: datetime | None, now: datetime) -> None:
        tr = self._tr.tr
        if created is None:
            self.backup.setText(tr("ui.status.backup_never"))
            self.backup.setStyleSheet(f"color: {self._tokens.palette.amber};")
            self.backup.setToolTip(tr("ui.status.backup_never.tip"))
            return
        self.backup.setStyleSheet("")
        when = created.astimezone().strftime("%H:%M")
        self.backup.setText(tr("ui.status.backup", time=when, ago=ago_text(created, now, self._tr)))
        self.backup.setToolTip(
            tr("ui.status.backup.tip", when=created.astimezone().isoformat(" ", "seconds"))
        )

    def _set_counts(self, counts: tuple[int, int, int]) -> None:
        errors, warnings, infos = counts
        params = {"errors": errors, "warnings": warnings, "infos": infos}
        self.counts.setText(self._tr.tr("ui.status.counts", **params))
        self.counts.setToolTip(self._tr.tr("ui.status.counts.tip", **params))
        worst = next((t for t, n in zip(_TONES, counts, strict=True) if n), None)
        self.counts.setIcon(self._icons.get(worst, worst) if worst else QIcon())

    def notify(self, text: str) -> None:
        """A transient message; the permanent widgets stay in place."""
        self.showMessage(text, MESSAGE_MS)

    def retranslate_ui(self) -> None:
        tr = self._tr.tr
        self.conflict_label.setText(tr("ui.status.conflict"))
        self.conflict_label.setToolTip(tr("ui.status.conflict.tip"))
        self.reload_button.setText(tr("ui.status.reload"))
        self.reload_button.setToolTip(tr("ui.status.reload.tip"))
        self.keep_button.setText(tr("ui.status.keep_mine"))
        self.keep_button.setToolTip(tr("ui.status.keep_mine.tip"))
        self.set_status(self._vm or StatusVM(profile_label=tr("ui.slot.none")))
