"""Accessibility manager for ShotBot application.

Provides centralized accessibility support including screen reader compatibility,
keyboard navigation, and tooltip management.
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable


# Qt imports needed at runtime for Protocol definitions

if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QListView,
        QPushButton,
        QSlider,
        QStatusBar,
        QTabWidget,
        QWidget,
    )


@runtime_checkable
class GridWidget(Protocol):
    """Protocol for grid widgets that may have accessibility features."""

    def setAccessibleName(self, name: str) -> None: ...
    def setAccessibleDescription(self, description: str) -> None: ...

    # attributes - checked with hasattr at runtime
    size_slider: QSlider | None
    list_view: QListView | None


@runtime_checkable
class MainWindowProtocol(Protocol):
    """Protocol for main window with UI elements for accessibility setup."""

    # Core window methods
    def setTabOrder(self, first: QWidget, second: QWidget) -> None: ...

    # Menu actions (optional - checked with hasattr)
    refresh_action: QAction | None  # skylos: ignore
    settings_action: QAction | None  # skylos: ignore
    exit_action: QAction | None  # skylos: ignore
    increase_size_action: QAction | None  # skylos: ignore
    decrease_size_action: QAction | None  # skylos: ignore
    reset_layout_action: QAction | None  # skylos: ignore
    shortcuts_action: QAction | None  # skylos: ignore
    about_action: QAction | None  # skylos: ignore

    # UI components (optional - checked with hasattr)
    status_bar: QStatusBar | None  # skylos: ignore
    tab_widget: QTabWidget | None  # skylos: ignore
    shot_grid: GridWidget | None  # skylos: ignore
    app_buttons: dict[str, QPushButton] | None  # skylos: ignore


class AccessibilityManager:
    """Manages accessibility features across the application."""

    @staticmethod
    def setup_main_window_accessibility(window: QWidget) -> None:
        """Set up accessibility for the main window.

        Args:
            window: The main application window

        """
        window.setAccessibleName("ShotBot VFX Launcher")
        window.setAccessibleDescription(
            "Browse and launch VFX applications for shots. Use Tab to navigate, Arrow keys to select shots, Enter to launch applications."
        )

    @staticmethod
    def setup_shot_grid_accessibility(
        grid_widget: QWidget, grid_type: str = "shots"
    ) -> None:
        """Set up accessibility for shot grid widgets.

        Args:
            grid_widget: The grid widget to configure
            grid_type: Type of grid ("shots", "3de", "previous")

        """
        descriptions = {
            "shots": "Grid of assigned shots with thumbnails. Navigate with arrow keys, press Enter to select.",
            "3de": "Grid of 3DE scene files. Navigate with arrow keys, double-click to open.",
            "previous": "Grid of previously completed shots. Browse your shot history.",
        }

        names = {
            "shots": "My Shots Grid",
            "3de": "3DE Scenes Grid",
            "previous": "Previous Shots Grid",
        }

        grid_widget.setAccessibleName(names.get(grid_type, "Shot Grid"))
        grid_widget.setAccessibleDescription(
            descriptions.get(grid_type, "Grid of shots")
        )

        # Set up for child widgets if they exist
        if hasattr(grid_widget, "list_view"):
            # Cast to GridWidget protocol to access list_view attribute safely
            grid = cast("GridWidget", cast("object", grid_widget))
            if grid.list_view is not None:
                grid.list_view.setAccessibleName(f"{grid_type.title()} List")
                grid.list_view.setAccessibleDescription(
                    f"List of {grid_type} items. Use arrow keys to navigate, Enter to select."
                )

    @staticmethod
    def setup_tab_widget_accessibility(tab_widget: QTabWidget) -> None:
        """Set up accessibility for tab widget.

        Args:
            tab_widget: The tab widget to configure

        """
        tab_widget.setAccessibleName("Shot View Tabs")
        tab_widget.setAccessibleDescription(
            "Switch between different shot views. Use Ctrl+Tab to cycle through tabs."
        )

        # Set up individual tabs
        tab_descriptions = [
            ("My Shots", "View shots assigned to you"),
            ("Other 3DE Scenes", "Browse 3DE scene files from other users"),
            ("Previous Shots", "View your previously completed shots"),
            ("Command History", "View history of launched commands"),
        ]

        for i, (_name, description) in enumerate(tab_descriptions):
            if i < tab_widget.count():
                tab_widget.setTabToolTip(i, description)
                # Note: Tab text is already set, just adding tooltip

    @staticmethod
    def setup_comprehensive_tooltips(window: MainWindowProtocol) -> None:
        """Add comprehensive tooltips to all UI elements.

        Args:
            window: Main window with UI elements

        """
        # File menu tooltips
        if hasattr(window, "refresh_action") and window.refresh_action is not None:
            window.refresh_action.setToolTip(
                "Refresh shot list from workspace (Ctrl+R)"
            )

        if hasattr(window, "settings_action") and window.settings_action is not None:
            window.settings_action.setToolTip("Open application settings dialog")

        if hasattr(window, "exit_action") and window.exit_action is not None:
            window.exit_action.setToolTip("Exit ShotBot application")

        # View menu tooltips
        if (
            hasattr(window, "increase_size_action")
            and window.increase_size_action is not None
        ):
            window.increase_size_action.setToolTip("Increase thumbnail size (Ctrl++)")

        if (
            hasattr(window, "decrease_size_action")
            and window.decrease_size_action is not None
        ):
            window.decrease_size_action.setToolTip("Decrease thumbnail size (Ctrl+-)")

        if (
            hasattr(window, "reset_layout_action")
            and window.reset_layout_action is not None
        ):
            window.reset_layout_action.setToolTip(
                "Reset window layout to default configuration"
            )

        # Help menu tooltips
        if hasattr(window, "shortcuts_action") and window.shortcuts_action is not None:
            window.shortcuts_action.setToolTip("Show keyboard shortcuts reference")

        if hasattr(window, "about_action") and window.about_action is not None:
            window.about_action.setToolTip("About ShotBot application")

        # Status bar tooltip
        if hasattr(window, "status_bar") and window.status_bar is not None:
            window.status_bar.setToolTip("Application status and messages")
