"""AppStatusBar through the window: state rendering is driven by the controller's StatusVM."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QLabel

from src.ui.widgets.elided_label import ElidedLabel
from src.ui.widgets.health_dock import HealthDock
from tests.ui.helpers import make_status, stamp

LONG = Path("C:/Users/someone/Documents/Darkest/a/very/deeply/nested/profile_0/persist.game.json")


@pytest.fixture
def bar(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    return main_window.statusBar()


def push(main_window, **over):
    main_window.test_controller.statusChanged.emit(make_status(**over))


def texts(bar):
    out = [w.text() for w in bar.findChildren(QLabel) if w.isVisible()]
    out += [w.text() for w in bar.findChildren(QAbstractButton) if w.isVisible()]
    return out


def test_profile_label_is_shown(main_window, bar):
    push(main_window, profile_label="Slot 3 (Week 40)")
    assert any("Slot 3 (Week 40)" in t for t in texts(bar))


def test_never_backed_up_shows_never_and_a_known_backup_shows_time_and_age(main_window, bar):
    push(main_window, last_backup=None)
    assert any("never" in t.lower() for t in texts(bar))
    when = stamp(3)
    push(main_window, last_backup=when)
    shown = texts(bar)
    assert not any("never" in t.lower() for t in shown)
    assert any(when.strftime("%H:%M") in t for t in shown)
    assert any("3" in t and "min" in t for t in shown)


def test_save_path_is_elided_with_a_full_path_tooltip(main_window, bar):
    push(main_window, save_path=LONG)
    labels = [w for w in bar.findChildren(ElidedLabel) if str(LONG) in w.toolTip()]
    assert len(labels) == 1
    label = labels[0]
    full_width = label.fontMetrics().horizontalAdvance(str(LONG))
    assert label.minimumSizeHint().width() < full_width


def test_counts_are_rendered_and_clicking_them_opens_the_health_dock(main_window, bar, qtbot):
    push(main_window, counts=(1, 3, 2))
    counts = [
        w
        for w in bar.findChildren(QAbstractButton) + bar.findChildren(QLabel)
        if "1" in w.text() and "3" in w.text() and "2" in w.text() and w.isVisible()
    ]
    assert counts, texts(bar)
    dock = main_window.findChild(HealthDock)
    assert not dock.isVisible()
    qtbot.mouseClick(counts[0], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(dock.isVisible, timeout=2000)


def test_busy_indicator_text(main_window, bar):
    push(main_window, busy=True, busy_text="Scanning mods")
    assert any("Scanning mods" in t for t in texts(bar))
    push(main_window, busy=False, busy_text="")
    assert not any("Scanning mods" in t for t in texts(bar))


def test_conflict_banner_offers_reload_and_keep_mine(main_window, bar):
    push(main_window, conflict=True)
    buttons = [w.text().lower() for w in bar.findChildren(QAbstractButton) if w.isVisible()]
    assert any("reload" in t for t in buttons), buttons
    assert any("keep" in t for t in buttons), buttons
    push(main_window, conflict=False)
    buttons = [w.text().lower() for w in bar.findChildren(QAbstractButton) if w.isVisible()]
    assert not any("reload" in t for t in buttons)


def test_transient_messages_never_clobber_permanent_widgets(main_window, bar):
    push(main_window, profile_label="Slot 9", counts=(0, 1, 0))
    before = texts(bar)
    bar.showMessage("Backup created", 6000)
    assert bar.currentMessage() == "Backup created"
    assert all(t in texts(bar) for t in before if t)
    bar.clearMessage()
    assert all(t in texts(bar) for t in before if t)


def test_retranslation_keeps_the_state(main_window, bar, translator):
    push(main_window, last_backup=None)
    translator.set_language("es_ES")
    translator.set_language("en")
    assert any("never" in t.lower() for t in texts(bar))


# ---------------------------------------------------------------------------- geometry


def rects(bar):
    names = ("profile", "save_path", "backup", "counts")
    return [(n, getattr(bar, n).geometry()) for n in names if getattr(bar, n).isVisible()]


def assert_apart(bar):
    items = rects(bar)
    assert len(items) == 4
    for i, (n1, r1) in enumerate(items):
        for n2, r2 in items[i + 1 :]:
            assert not r1.intersects(r2), (n1, r1, n2, r2)


def test_permanent_widgets_never_overlap_even_with_a_long_path(main_window, bar):
    from PySide6.QtCore import QCoreApplication

    push(main_window, save_path=LONG, last_backup=stamp(16 * 24 * 60), profile_label="Slot 3 · w25")
    QCoreApplication.processEvents()
    assert_apart(bar)
    path = bar.save_path
    assert 160 <= path.width() <= 420
    assert path.minimumSizeHint().width() >= 160
    assert path.sizeHint().width() <= 420
    assert "…" in path.elided_text()


def test_a_narrow_window_keeps_them_apart_too(main_window, bar, qtbot):
    from PySide6.QtCore import QCoreApplication

    push(main_window, save_path=LONG, last_backup=stamp(5), profile_label="Slot 3 · week 25")
    main_window.resize(900, 600)
    qtbot.wait(30)
    QCoreApplication.processEvents()
    assert_apart(bar)
    assert bar.save_path.width() >= 160
