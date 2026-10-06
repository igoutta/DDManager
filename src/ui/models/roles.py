"""Custom item-data roles and the drag-and-drop payload shared by the mod views."""

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from operator import attrgetter
from typing import Final

from PySide6.QtCore import QByteArray, QMimeData, Qt

from src.core.ids import ModId
from src.ui.viewmodels import ModRowVM

MIME_MOD_IDS: Final = "application/x-ddmanager-mod-ids+json"
_USER: Final = int(Qt.ItemDataRole.UserRole)
_PAYLOAD_VERSION: Final = 1


class Role(IntEnum):
    MOD_ID = _USER + 1
    RANK = _USER + 2
    TIER = _USER + 3
    TIER_COLOR = _USER + 4
    SOURCE = _USER + 5
    SEARCH_BLOB = _USER + 6
    SORT_KEY = _USER + 7
    ENABLED = _USER + 8
    IS_NEW = _USER + 9
    WORST_SEVERITY = _USER + 10
    FINDING_COUNT = _USER + 11
    CATEGORY = _USER + 12
    MISSING = _USER + 13
    VM = _USER + 14


class DragOrigin(StrEnum):
    AVAILABLE = "available"
    LOAD_ORDER = "load_order"


@dataclass(frozen=True, slots=True)
class DragPayload:
    origin: DragOrigin
    ids: tuple[ModId, ...]
    pid: int


def encode_payload(origin: DragOrigin, ids: Sequence[ModId]) -> QMimeData:
    """A mime object carrying the JSON payload plus a newline list as ``text/plain``."""
    body = json.dumps(
        {"v": _PAYLOAD_VERSION, "origin": origin.value, "pid": os.getpid(), "ids": list(ids)}
    )
    mime = QMimeData()
    mime.setData(MIME_MOD_IDS, QByteArray(body.encode("utf-8")))
    mime.setText("\n".join(ids))
    return mime


def _parse(raw: object) -> DragPayload:
    if not isinstance(raw, dict) or not isinstance(raw["ids"], list):
        raise TypeError("malformed drag payload")
    return DragPayload(
        DragOrigin(raw["origin"]),
        tuple(ModId(str(i)) for i in raw["ids"]),
        int(raw["pid"]),
    )


def decode_payload(mime: QMimeData | None) -> DragPayload | None:
    """The payload, or ``None`` when absent, malformed, empty or from another process."""
    if mime is None or not mime.hasFormat(MIME_MOD_IDS):
        return None
    try:
        payload = _parse(json.loads(bytes(mime.data(MIME_MOD_IDS).data()).decode("utf-8")))
    except ValueError, KeyError, TypeError:
        return None
    return payload if payload.ids and payload.pid == os.getpid() else None


VM_ROLES: Final[Mapping[int, Callable[[ModRowVM], object]]] = {
    Role.MOD_ID: attrgetter("mod_id"),
    Role.TIER: attrgetter("tier_id"),
    Role.TIER_COLOR: attrgetter("color"),
    Role.SOURCE: attrgetter("source_id"),
    Role.SEARCH_BLOB: attrgetter("search_blob"),
    Role.SORT_KEY: attrgetter("sort_key"),
    Role.ENABLED: attrgetter("enabled"),
    Role.IS_NEW: attrgetter("is_new"),
    Role.WORST_SEVERITY: attrgetter("worst_severity"),
    Role.FINDING_COUNT: attrgetter("finding_count"),
    Role.CATEGORY: attrgetter("category_label"),
    Role.MISSING: attrgetter("missing"),
    Role.VM: lambda vm: vm,
}
"""Custom roles that read one field of the row view model (``RANK`` is model specific)."""
