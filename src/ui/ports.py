"""UI-side ports: what the controller needs from the Qt shell, injected for tests."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from src.ui.viewmodels import OrderDiffVM, PatchPreviewVM


class CancelToken(Protocol):
    def is_cancelled(self) -> bool: ...


class TaskHandle(Protocol):
    def cancel(self) -> None: ...

    @property
    def done(self) -> bool: ...


class Executor(Protocol):
    def submit[T](
        self,
        fn: Callable[[CancelToken], T],
        *,
        on_ok: Callable[[T], None],
        on_err: Callable[[BaseException], None],
        key: str | None = None,
        pool: str = "io",
    ) -> TaskHandle:
        """Run ``fn`` off the GUI thread and deliver the result on it.

        A new submit with the same ``key`` cancels the previous token and drops its result.
        """
        ...


@dataclass(frozen=True, slots=True)
class PatchDecision:
    proceed: bool
    acknowledged: frozenset[str] = frozenset()
    override_errors: bool = False


class Prompter(Protocol):
    def confirm_disable_active(self, titles: Sequence[str], slot_label: str) -> bool: ...

    def review_order_change(self, vm: OrderDiffVM, title_key: str) -> bool: ...

    def review_patch(self, vm: PatchPreviewVM) -> PatchDecision: ...

    def resolve_state_conflict(self) -> Literal["reload", "overwrite", "cancel"]: ...

    def info(self, key: str, **params: object) -> None: ...

    def error(self, key: str, details: str = "", **params: object) -> None: ...

    def pick_save_file(self, start_dir: Path | None) -> Path | None: ...

    def pick_folder(self, start_dir: Path | None) -> Path | None: ...

    def pick_profile_file(self, save: bool) -> Path | None: ...
