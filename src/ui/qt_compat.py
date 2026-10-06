"""Small shims over Qt/PySide6 API differences."""

from typing import Final

from PySide6.QtCore import QSortFilterProxyModel, qVersion

_FILTER_CHANGE_API: Final = (6, 10)


def qt_version() -> tuple[int, int, int]:
    """The running Qt version as ``(major, minor, patch)``."""
    parts = [int(p) for p in qVersion().split(".")[:3] if p.isdigit()]
    parts += [0] * (3 - len(parts))
    return (parts[0], parts[1], parts[2])


def has_filter_change_api() -> bool:
    """True when ``beginFilterChange``/``endFilterChange`` exist (Qt 6.10+)."""
    return qt_version()[:2] >= _FILTER_CHANGE_API


def refilter_rows(proxy: QSortFilterProxyModel) -> None:
    """Re-evaluate ``filterAcceptsRow`` after the proxy's own criteria changed.

    Qt 6.10 deprecated ``invalidateRowsFilter`` in favour of the begin/end pair, which must
    bracket the criteria change; the call sites here change the state first, so on 6.10+ the
    pair is issued back to back (equivalent: the proxy re-filters in ``endFilterChange``).
    """
    if has_filter_change_api():
        proxy.beginFilterChange()
        proxy.endFilterChange(QSortFilterProxyModel.Direction.Rows)
    else:
        proxy.invalidateRowsFilter()
