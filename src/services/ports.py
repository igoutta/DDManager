"""Small injectable ports: clock, cancellation, progress and process probing."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware local time."""
        ...


@dataclass(frozen=True, slots=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


@dataclass(frozen=True, slots=True)
class FixedClock:
    at: datetime

    def now(self) -> datetime:
        return self.at


class CancelToken(Protocol):
    def is_cancelled(self) -> bool: ...


@dataclass(slots=True)
class NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


class ProgressReporter(Protocol):
    def report(self, done: int, total: int, message: str = "") -> None: ...


class NullProgress:
    """Progress sink that ignores everything."""

    __slots__ = ()

    def report(self, done: int, total: int, message: str = "") -> None:
        return None


class RunState(StrEnum):
    RUNNING = "running"
    NOT_RUNNING = "not_running"
    UNKNOWN = "unknown"


class ProcessProbe(Protocol):
    def find(self, image_names: Collection[str]) -> RunState:
        """Case-insensitive image names; never raises."""
        ...
