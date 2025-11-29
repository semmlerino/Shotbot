"""Quick launch bar widget for fast DCC application launching.

Provides labeled pill-shaped buttons with visible keyboard shortcuts
for rapid application launching. This is the primary interaction for
90% of launches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from design_system import design_system
from qt_widget_mixin import QtWidgetMixin


if TYPE_CHECKING:
    from shot_model import Shot


@final
@dataclass
class QuickLaunchConfig:
    """Configuration for a quick launch button."""

    app_name: str  # e.g., "3de", "nuke", "maya", "rv"
    display_name: str  # e.g., "3DE", "Nuke", "Maya", "RV"
    shortcut: str  # e.g., "3", "N", "M", "R"
    color: str  # Hex color for accent


# Default quick launch configurations
DEFAULT_QUICK_LAUNCH_CONFIGS = [
    QuickLaunchConfig("3de", "3DE", "3", "#2b4d6f"),
    QuickLaunchConfig("nuke", "Nuke", "N", "#5d4d2b"),
    QuickLaunchConfig("maya", "Maya", "M", "#4d2b5d"),
    QuickLaunchConfig("rv", "RV", "R", "#2b5d4d"),
]


@final
class QuickLaunchBar(QtWidgetMixin, QWidget):
    """Horizontal bar of quick launch pill buttons.

    Each button shows the app name with keyboard shortcut visible in the label.
    Emits launch_requested signal when clicked.

    Attributes:
        launch_requested: Signal emitted with app_name when button clicked.
    """

    launch_requested = Signal(str)  # app_name

    def __init__(
        self,
        configs: list[QuickLaunchConfig] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the quick launch bar.

        Args:
            configs: List of button configurations. Uses defaults if None.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._configs = configs or DEFAULT_QUICK_LAUNCH_CONFIGS
        self._buttons: dict[str, QPushButton] = {}
        self._current_shot: Shot | None = None
        self._latest_versions: dict[str, str] = {}  # app_name -> version string
        self._quick_label: QLabel | None = None

        self._setup_ui()

        # Connect to scale changes for live updates
        _ = design_system.scale_changed.connect(self._apply_styles)

    def _setup_ui(self) -> None:
        """Set up the quick launch bar UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 10)
        layout.setSpacing(8)

        # Label
        self._quick_label = QLabel("Quick:")
        layout.addWidget(self._quick_label)

        # Create pill buttons
        for config in self._configs:
            btn = self._create_pill_button(config)
            layout.addWidget(btn)
            self._buttons[config.app_name] = btn

        layout.addStretch()

        # Apply dynamic styles
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply/refresh styles using current design system values."""
        # Quick label
        if self._quick_label is not None:
            self._quick_label.setStyleSheet(
                f"color: #888; font-size: {design_system.typography.size_tiny}px;"
            )

        # All pill buttons
        for app_name, btn in self._buttons.items():
            # Find config for this button
            config = next(
                (c for c in self._configs if c.app_name == app_name), None
            )
            if config:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #2a2a2a;
                        border: 1px solid #444;
                        border-left: 3px solid {config.color};
                        border-radius: 4px;
                        padding: 4px 12px;
                        font-size: {design_system.typography.size_tiny}px;
                        font-weight: bold;
                        color: #ddd;
                    }}
                    QPushButton:hover {{
                        background-color: #3a3a3a;
                        border-color: #555;
                        color: #fff;
                    }}
                    QPushButton:pressed {{
                        background-color: #252525;
                    }}
                    QPushButton:disabled {{
                        background-color: #222;
                        border-color: #333;
                        border-left-color: #444;
                        color: #666;
                    }}
                """)

    def _create_pill_button(self, config: QuickLaunchConfig) -> QPushButton:
        """Create a pill-shaped quick launch button.

        Args:
            config: Button configuration

        Returns:
            Configured QPushButton
        """
        # Format: "3DE (3)" - name with shortcut in parentheses
        btn = QPushButton(f"{config.display_name} ({config.shortcut})")
        btn.setEnabled(False)
        btn.setMinimumWidth(70)
        btn.setFixedHeight(28)

        # Style with 3px left border accent (not solid background)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-left: 3px solid {config.color};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: {design_system.typography.size_tiny}px;
                font-weight: bold;
                color: #ddd;
            }}
            QPushButton:hover {{
                background-color: #3a3a3a;
                border-color: #555;
                color: #fff;
            }}
            QPushButton:pressed {{
                background-color: #252525;
            }}
            QPushButton:disabled {{
                background-color: #222;
                border-color: #333;
                border-left-color: #444;
                color: #666;
            }}
        """)

        # Tooltip with version info when available
        self._update_button_tooltip(btn, config)

        # Connect click - capture app_name with default argument to avoid late binding
        _ = btn.clicked.connect(
            lambda checked, app=config.app_name: self._on_button_clicked(app)  # noqa: ARG005 # type: ignore[arg-type]
        )

        return btn

    def _update_button_tooltip(
        self, btn: QPushButton, config: QuickLaunchConfig
    ) -> None:
        """Update button tooltip with version info if available."""
        version = self._latest_versions.get(config.app_name)
        if version:
            btn.setToolTip(
                f"Launch {config.display_name} with latest scene ({version})\n"
                f"Shortcut: {config.shortcut}"
            )
        else:
            btn.setToolTip(
                f"Launch {config.display_name}\n"
                f"Shortcut: {config.shortcut}"
            )

    def _on_button_clicked(self, app_name: str) -> None:
        """Handle button click.

        Args:
            app_name: Name of the app to launch
        """
        if self._current_shot is not None:
            self.launch_requested.emit(app_name)

    def set_shot(self, shot: Shot | None) -> None:
        """Update for the selected shot.

        Enables/disables buttons based on whether a shot is selected.

        Args:
            shot: Currently selected shot, or None
        """
        self._current_shot = shot
        enabled = shot is not None

        for btn in self._buttons.values():
            btn.setEnabled(enabled)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all buttons.

        Args:
            enabled: True to enable, False to disable
        """
        for btn in self._buttons.values():
            btn.setEnabled(enabled)

    def set_latest_version(self, app_name: str, version: str | None) -> None:
        """Set the latest version string for an app.

        Updates the tooltip to show version info.

        Args:
            app_name: App name (e.g., "3de")
            version: Version string (e.g., "v005") or None
        """
        if version:
            self._latest_versions[app_name] = version
        elif app_name in self._latest_versions:
            del self._latest_versions[app_name]

        # Update tooltip if button exists
        btn = self._buttons.get(app_name)
        if btn:
            # Find the config for this app
            for config in self._configs:
                if config.app_name == app_name:
                    self._update_button_tooltip(btn, config)
                    break

    def clear_latest_versions(self) -> None:
        """Clear all cached version info."""
        self._latest_versions.clear()
        # Update all tooltips
        for config in self._configs:
            btn = self._buttons.get(config.app_name)
            if btn:
                self._update_button_tooltip(btn, config)
