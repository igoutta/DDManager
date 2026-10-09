"""The application icon (torch + gear badge) is bundled and shown on the main window."""

from importlib import resources

from PySide6.QtWidgets import QApplication, QMainWindow

from src.ui.widgets.actions import application_icon

EXPECTED_SIZES = {16, 24, 32, 48, 64, 128, 256}


def test_the_bundled_icon_loads_with_every_windows_size(qapp: QApplication) -> None:
    del qapp  # QIcon needs a live QGuiApplication; the fixture guarantees one
    assert (resources.files("src") / "resources" / "icons" / "app.ico").is_file()
    icon = application_icon()
    assert not icon.isNull()
    assert {s.width() for s in icon.availableSizes()} == EXPECTED_SIZES


def test_the_main_window_shows_the_application_icon(main_window: QMainWindow) -> None:
    icon = main_window.windowIcon()
    assert not icon.isNull()
    assert 256 in {s.width() for s in icon.availableSizes()}
