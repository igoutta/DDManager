"""DetailsPane: one page per state, in-place updates, a preview that fits, no leftovers."""

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QToolButton, QWidget

from src.core.findings import Severity
from src.core.ids import ModId
from src.ui.viewmodels import DetailsVM, MultiDetailsVM
from src.ui.widgets.details_pane import MIN_WIDTH_PX, THUMB_PX, tier_text
from tests.ui.helpers import make_finding


def make_details(mod_id: str = "mod_a", **over: Any):
    fields: dict[str, Any] = {
        "mod_id": ModId(mod_id),
        "title": f"Mod {mod_id}",
        "rank_text": "Rank 1 of 3 - entry 0",
        "identity_text": f"{mod_id} · local",
        "folder": mod_id,
        "source_label": "Local",
        "workshop_url": None,
        "path": Path(mod_id),
        "version_text": "1.0",
        "category_label": "Class",
        "tier_label": "Class",
        "tags": ("x", "y"),
        "findings": (make_finding("f1", Severity.WARNING),),
    }
    fields.update(over)
    return DetailsVM(**fields)


def settle() -> None:
    """What the real event loop does between two selections: run the deferred deletes."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def widget_count(pane) -> int:
    return len(pane.findChildren(QWidget))


@pytest.fixture
def pane(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    return main_window.details


# ---------------------------------------------------------------------------- pages


def test_placeholder_is_the_page_without_a_selection(pane):
    pane.show_details(None)
    assert pane.stack.currentWidget() is pane.placeholder
    assert pane.placeholder.text().strip()
    assert pane.placeholder.isVisible()
    assert not pane.scroll_area.isVisible()


def test_content_hides_the_placeholder(pane):
    pane.show_details(make_details())
    assert pane.stack.currentWidget() is pane.scroll_area
    assert not pane.placeholder.isVisible()
    assert pane.title.isVisible()
    assert pane.title.text() == "Mod mod_a"
    pane.show_details(MultiDetailsVM(count=2, tier_breakdown=(("Class", 2),)))
    assert pane.stack.currentWidget() is pane.multi_page
    assert not pane.placeholder.isVisible()
    assert not pane.scroll_area.isVisible()
    assert "Class: 2" in pane.multi_breakdown.text()


# ---------------------------------------------------------------------------- no leftovers


def test_repeated_selections_leave_no_leftover_widgets(pane):
    a = make_details(
        "a",
        tags=("t1", "t2"),
        findings=(make_finding("f1", Severity.WARNING), make_finding("f2", Severity.INFO)),
    )
    b = make_details("b", tags=("t3",), findings=())
    pane.show_details(a)
    settle()
    baseline = widget_count(pane)
    for _ in range(6):
        pane.show_details(b)
        settle()
        pane.show_details(None)
        settle()
        pane.show_details(a)
        settle()
    assert widget_count(pane) == baseline
    buttons = [w for w in pane.findings.findChildren(QToolButton) if w.isVisible()]
    assert [w.text() for w in buttons] == ["Message of f1", "Message of f2"]
    chips = [w for w in pane.tags.findChildren(QLabel) if w.isVisible()]
    assert [w.text() for w in chips] == ["t1", "t2"]


def test_a_mod_without_tags_or_findings_shows_neither_leftover(pane):
    pane.show_details(make_details("a", tags=("t1",)))
    pane.show_details(make_details("b", tags=(), findings=()))
    settle()
    assert not pane.tags.isVisible()
    assert [w for w in pane.tags.findChildren(QLabel) if w.isVisible()] == []
    labels = [w.text() for w in pane.findings.findChildren(QLabel) if w.isVisible()]
    assert len(labels) == 1  # the "no findings" note
    assert [w for w in pane.findings.findChildren(QToolButton) if w.isVisible()] == []


# ---------------------------------------------------------------------------- texts


def test_tier_line_names_the_category_once_when_it_equals_the_tier(pane, translator):
    pane.show_details(make_details(tier_label="Class", category_label="Class"))
    assert pane.tier.text() == translator.tr("ui.details.tier_only", tier="Class")
    assert pane.tier.text().count("Class") == 1
    pane.show_details(make_details(tier_label="Skin", category_label="Custom Skins"))
    expected = translator.tr("ui.details.tier", tier="Skin", category="Custom Skins")
    assert pane.tier.text() == expected


def test_tier_text_helper(translator):
    assert tier_text(translator.tr, "A", "A").count("A") == 1
    assert tier_text(translator.tr, "A", "").count("A") == 1
    assert "(B)" in tier_text(translator.tr, "A", "B")


def test_source_and_buttons_are_on_separate_rows(pane):
    pane.show_details(make_details(workshop_url="https://example/1"))
    QCoreApplication.processEvents()
    assert pane.buttons["page"].isVisible()
    source_bottom = pane.source.mapTo(pane.sheet, QPoint(0, pane.source.height())).y()
    folder_top = pane.buttons["folder"].mapTo(pane.sheet, QPoint(0, 0)).y()
    assert source_bottom <= folder_top
    assert pane.source.width() >= pane.source.sizeHint().width() // 2
    pane.show_details(make_details(workshop_url=None))
    assert not pane.buttons["page"].isVisible()


def test_retranslation_relabels_without_rebuilding(pane, translator):
    pane.show_details(make_details())
    settle()
    before = widget_count(pane)
    translator.set_language("es_ES")  # the window re-renders the pane for the empty selection
    pane.show_details(make_details())
    settle()
    assert pane.buttons["copy"].text() == translator.tr("ui.details.copy")
    assert pane.buttons["copy"].text() != "Copy"
    assert widget_count(pane) == before


# ---------------------------------------------------------------------------- preview and width


def test_thumbnail_scales_to_the_pane_width_and_stays_centred(pane, main_window, monkeypatch):
    source = QPixmap(900, 600)
    source.fill(Qt.GlobalColor.red)
    monkeypatch.setattr(main_window.test_controller.thumbnails, "pixmap", lambda *_a, **_k: source)
    pane.show_details(make_details())
    QCoreApplication.processEvents()
    shown = pane.thumb.pixmap()
    assert not shown.isNull()
    assert shown.width() <= THUMB_PX
    assert shown.width() <= pane.width()
    assert abs(shown.width() / shown.height() - 1.5) < 0.05
    assert pane.thumb.alignment() & Qt.AlignmentFlag.AlignHCenter
    main_window.splitter.setSizes([800, 600, MIN_WIDTH_PX])
    QCoreApplication.processEvents()
    assert pane.width() < THUMB_PX + 20
    assert pane.thumb.pixmap().width() <= pane.width()
    assert not pane.scroll_area.horizontalScrollBar().isVisible()


def test_the_pane_has_a_usable_default_and_minimum_width(main_window, qtbot):
    assert main_window.details.minimumWidth() == MIN_WIDTH_PX >= 200
    main_window.show()
    qtbot.waitExposed(main_window)
    sizes = main_window.splitter.sizes()
    assert sizes[2] >= 300, sizes
    assert sizes[1] > sizes[0] >= sizes[2], sizes
