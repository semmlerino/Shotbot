"""Menu bar construction and dialog display for MainWindow."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMessageBox

from config import Config


if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow, QWidget


class MenuTargets(Protocol):
    """Minimal interface the menu needs from its caller."""

    @property
    def settings_controller(self) -> _SettingsControllerProtocol: ...

    @property
    def thumbnail_size_manager(self) -> _ThumbnailSizeManagerProtocol: ...


class _SettingsControllerProtocol(Protocol):
    def import_settings(self) -> None: ...
    def export_settings(self) -> None: ...
    def reset_layout(self) -> None: ...
    def show_preferences(self) -> None: ...


class _ThumbnailSizeManagerProtocol(Protocol):
    def increase_size(self) -> None: ...
    def decrease_size(self) -> None: ...


def build_menu(
    window: QMainWindow,
    targets: MenuTargets,
    refresh_callback: Callable[[], None],
) -> QAction:
    """Build the application menu bar. Returns the refresh action (for keyboard shortcut)."""
    menubar = window.menuBar()

    # File menu
    file_menu = menubar.addMenu("&File")

    refresh_action = QAction("&Refresh Shots", window)
    refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
    _ = refresh_action.triggered.connect(refresh_callback)
    file_menu.addAction(refresh_action)

    _ = file_menu.addSeparator()

    import_settings_action = QAction("&Import Settings...", window)
    _ = import_settings_action.triggered.connect(targets.settings_controller.import_settings)
    file_menu.addAction(import_settings_action)

    export_settings_action = QAction("&Export Settings...", window)
    _ = export_settings_action.triggered.connect(targets.settings_controller.export_settings)
    file_menu.addAction(export_settings_action)

    _ = file_menu.addSeparator()

    exit_action = QAction("&Exit", window)
    exit_action.setShortcut(QKeySequence.StandardKey.Quit)
    _ = exit_action.triggered.connect(window.close)
    file_menu.addAction(exit_action)

    # View menu
    view_menu = menubar.addMenu("&View")

    increase_size_action = QAction("&Increase Thumbnail Size", window)
    increase_size_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
    _ = increase_size_action.triggered.connect(targets.thumbnail_size_manager.increase_size)
    view_menu.addAction(increase_size_action)

    decrease_size_action = QAction("&Decrease Thumbnail Size", window)
    decrease_size_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
    _ = decrease_size_action.triggered.connect(targets.thumbnail_size_manager.decrease_size)
    view_menu.addAction(decrease_size_action)

    _ = view_menu.addSeparator()

    reset_layout_action = QAction("&Reset Layout", window)
    _ = reset_layout_action.triggered.connect(targets.settings_controller.reset_layout)
    view_menu.addAction(reset_layout_action)

    # Edit menu
    edit_menu = menubar.addMenu("&Edit")

    preferences_action = QAction("&Preferences...", window)
    preferences_action.setShortcut("Ctrl+,")
    _ = preferences_action.triggered.connect(targets.settings_controller.show_preferences)
    edit_menu.addAction(preferences_action)

    # Help menu
    help_menu = menubar.addMenu("&Help")

    shortcuts_action = QAction("&Keyboard Shortcuts", window)
    shortcuts_action.setShortcut(QKeySequence.StandardKey.HelpContents)
    _ = shortcuts_action.triggered.connect(lambda: show_shortcuts(window))
    help_menu.addAction(shortcuts_action)

    _ = help_menu.addSeparator()

    about_action = QAction("&About", window)
    _ = about_action.triggered.connect(lambda: show_about(window))
    help_menu.addAction(about_action)

    return refresh_action


def show_shortcuts(parent: QWidget) -> None:
    """Show keyboard shortcuts dialog."""
    shortcuts_text = """<h3>Keyboard Shortcuts</h3>
    <table cellpadding="5">
    <tr><td><b>Navigation:</b></td><td></td></tr>
    <tr><td>Arrow Keys</td><td>Navigate through shots/scenes</td></tr>
    <tr><td>Home/End</td><td>Jump to first/last shot</td></tr>
    <tr><td>Enter</td><td>Launch default app (3de)</td></tr>
    <tr><td>Ctrl+Wheel</td><td>Adjust thumbnail size</td></tr>
    <tr><td>&nbsp;</td><td></td></tr>
    <tr><td><b>Applications:</b></td><td></td></tr>
    <tr><td>3</td><td>Launch 3de</td></tr>
    <tr><td>N</td><td>Launch Nuke</td></tr>
    <tr><td>M</td><td>Launch Maya</td></tr>
    <tr><td>R</td><td>Launch RV</td></tr>
    <tr><td>P</td><td>Launch Publish</td></tr>
    <tr><td>&nbsp;</td><td></td></tr>
    <tr><td><b>View:</b></td><td></td></tr>
    <tr><td>Ctrl++</td><td>Increase thumbnail size</td></tr>
    <tr><td>Ctrl+-</td><td>Decrease thumbnail size</td></tr>
    <tr><td>&nbsp;</td><td></td></tr>
    <tr><td><b>General:</b></td><td></td></tr>
    <tr><td>F5</td><td>Refresh shots</td></tr>
    <tr><td>F1</td><td>Show this help</td></tr>
    </table>
    """
    _ = QMessageBox.information(parent, "Keyboard Shortcuts", shortcuts_text)


def show_about(parent: QWidget) -> None:
    """Show about dialog."""
    _ = QMessageBox.about(
        parent,
        f"About {Config.APP_NAME}",
        (
            f"{Config.APP_NAME} v{Config.APP_VERSION}\n\n"
            "VFX Shot Launcher\n\n"
            "A tool for browsing and launching applications in shot context."
        ),
    )
