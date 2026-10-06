"""The status view model and the direction labels (pure)."""

from collections.abc import Callable

from src.core.load_order import PriorityDirection, PrioritySetting
from src.ui.catalog import counts
from src.ui.session import Session
from src.ui.viewmodels import StatusVM

type Tr = Callable[..., str]


def direction_labels(priority: PrioritySetting, tr: Tr) -> tuple[str, str]:
    """``(top, bottom)`` captions of the load-order pane for the configured direction."""
    if not priority.verified:
        return tr("ui.dir.top_unverified"), tr("ui.dir.bottom_unverified")
    if priority.direction is PriorityDirection.FIRST_WINS:
        return tr("ui.dir.top_wins"), tr("ui.dir.bottom_plain")
    return tr("ui.dir.top_plain"), tr("ui.dir.bottom_wins")


def status_vm(s: Session, priority: PrioritySetting, tr: Tr, *, label: str, busy: bool) -> StatusVM:
    top, bottom = direction_labels(priority, tr)
    return StatusVM(
        profile_label=label,
        save_path=s.save_path,
        last_backup=s.last_backup,
        counts=counts(s.findings),
        summary_text=tr(
            "ui.status.summary", enabled=len(s.order.active()), total=len(s.order.entries)
        ),
        busy=busy,
        busy_text=s.busy_text,
        conflict=s.conflict,
        direction_top_label=top,
        direction_bottom_label=bottom,
        direction_verified=priority.verified,
    )
