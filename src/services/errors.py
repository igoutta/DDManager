"""Typed errors raised by the services layer (all derive from ``DDManagerError``)."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar

from src.core.errors import DDManagerError

if TYPE_CHECKING:
    from src.services.fsutil import FileFingerprint


class ServiceError(DDManagerError):
    """Base class of every services-layer error."""

    family: ClassVar[str] = "service"
    message_key: ClassVar[str] = "error.service"


class DataDirNotWritableError(ServiceError):
    """The portable data directory exists but is read-only: fail loudly, never fork state."""

    family = "data_dir_not_writable"
    message_key = "error.data_dir_not_writable"


class StateConflictError(ServiceError):
    """``mod_state.json`` changed on disk since it was loaded."""

    family = "state_conflict"
    message_key = "error.state_conflict"

    def __init__(
        self,
        message: str,
        *,
        expected: FileFingerprint | None,
        actual: FileFingerprint | None,
        **details: object,
    ) -> None:
        super().__init__(message, **details)
        self.expected = expected
        self.actual = actual


class StateReadOnlyError(ServiceError):
    """The state repository was opened read-only; ``details["reason"]`` says why."""

    family = "state_read_only"
    message_key = "error.state_read_only"


class SaveNotFoundError(ServiceError):
    family = "save_not_found"
    message_key = "error.save_not_found"


class SaveLockedError(ServiceError):
    """The save (or its replacement target) is locked by another process."""

    family = "save_locked"
    message_key = "error.save_locked"


class StaleSaveError(ServiceError):
    """The save changed between ``plan()`` and ``apply()``."""

    family = "stale_save"
    message_key = "error.stale_save"


class GameRunningError(ServiceError):
    family = "game_running"
    message_key = "error.game_running"


class UnacknowledgedRiskError(ServiceError):
    """``apply()`` was called without acknowledging every required risk."""

    family = "unacknowledged_risk"
    message_key = "error.unacknowledged_risk"

    def __init__(self, message: str, *, missing: Iterable[str], **details: object) -> None:
        super().__init__(message, **details)
        self.missing: frozenset[str] = frozenset(missing)


class BackupNotFoundError(ServiceError):
    family = "backup_not_found"
    message_key = "error.backup_not_found"


class BackupInvalidError(ServiceError):
    family = "backup_invalid"
    message_key = "error.backup_invalid"


class ProfileFormatError(ServiceError):
    family = "profile_format"
    message_key = "error.profile_format"


class ProfileExistsError(ServiceError):
    family = "profile_exists"
    message_key = "error.profile_exists"


class PluginLoadError(ServiceError):
    family = "plugin_load"
    message_key = "error.plugin_load"


class RenameFailedError(ServiceError):
    """Folder rename failed; ``details["rolled_back"]`` and ``details["stuck"]`` say how far."""

    family = "rename_failed"
    message_key = "error.rename_failed"


class LaunchError(ServiceError):
    family = "launch"
    message_key = "error.launch"
