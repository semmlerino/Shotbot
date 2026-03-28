"""Base DCC section widget for individual DCC application launching.

Provides a collapsible section with launch button, options checkboxes,
and plate selector. Shows version info in collapsed header for quick reference.

VFX Glossary:
    DCC — Digital Content Creation application (Maya, Nuke, 3DEqualizer, etc.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.design_system import (
    darken_color,
    design_system,
    get_tinted_background,
    lighten_color,
)
from ui.qt_widget_mixin import QtWidgetMixin


if TYPE_CHECKING:
    from managers.settings_manager import SettingsManager

    from .dcc_config import DCCConfig


class BaseDCCSection(QtWidgetMixin, QWidget):
    """Collapsible DCC section with launch options.

    Shows a header bar with:
    - Expand/collapse indicator
    - DCC name
    - Version info (when available)
    - Keyboard shortcut badge

    Expands to show:
    - Launch button
    - Option checkboxes
    - Plate selector

    Attributes:
        launch_requested: Signal(str, object) - app_name, options dict
        expanded_changed: Signal(str, bool) - app_name, is_expanded

    """

    launch_requested: Signal = Signal(str, object)  # app_name, options
    expanded_changed: Signal = Signal(str, bool)  # app_name, is_expanded

    # Instance attribute type declarations for basedpyright (non-@final class)
    config: DCCConfig
    _settings_manager: SettingsManager | None
    _expanded: bool
    _launch_in_progress: bool
    _should_be_enabled: bool
    _original_button_text: str
    _search_pending: bool
    _container: QWidget
    _expand_btn: QToolButton
    _name_label: QLabel
    _version_label: QLabel
    _content: QWidget
    _content_layout: QVBoxLayout
    _launch_btn: QPushButton
    _launch_description: QLabel

    def __init__(
        self,
        config: DCCConfig,
        settings_manager: SettingsManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the DCC section.

        Args:
            config: Configuration for this DCC
            settings_manager: Settings manager for height persistence
            parent: Optional parent widget

        """
        super().__init__(parent)
        self.config = config
        self._settings_manager = settings_manager
        self._expanded = False
        self._version_info: str | None = None
        self._age_info: str | None = None
        self._launch_in_progress = False
        self._should_be_enabled = False
        self._original_button_text = ""
        self._search_pending = False  # True while async file search is in progress

        # UI components
        self._checkboxes: dict[str, QCheckBox] = {}
        self._plate_selector: QComboBox | None = None

        # Store references for dynamic styling
        self._plate_label: QLabel | None = None

        self._setup_ui()

        # Connect to scale changes for live updates
        _ = design_system.scale_changed.connect(self._apply_styles)

    def _setup_ui(self) -> None:
        """Set up the section UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Container with left accent border
        self._container = QWidget()
        self._container.setStyleSheet(f"""
            QWidget#dccContainer {{
                background-color: {get_tinted_background(self.config.color)};
                border: 1px solid #333;
                border-left: 3px solid {self.config.color};
                border-radius: 4px;
            }}
        """)
        self._container.setObjectName("dccContainer")

        container_layout = QVBoxLayout(self._container)
        container_layout.setContentsMargins(8, 6, 8, 6)
        container_layout.setSpacing(4)

        # Header row (always visible)
        header = QPushButton()
        header.setFlat(True)
        header.setStyleSheet("""
            QPushButton {
                border: none;
                text-align: left;
                padding: 0;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
        """)
        _ = header.clicked.connect(self._toggle_expanded)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # Expand/collapse button (visual indicator only)
        self._expand_btn = QToolButton()
        self._expand_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._expand_btn.setMaximumSize(18, 18)
        self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout.addWidget(self._expand_btn)

        # DCC name
        self._name_label = QLabel(self.config.display_name)
        header_layout.addWidget(self._name_label)

        # Version info (shown when available)
        self._version_label = QLabel()
        self._version_label.setVisible(False)
        header_layout.addWidget(self._version_label)

        header_layout.addStretch()

        container_layout.addWidget(header)

        # Content widget (hidden when collapsed)
        self._content = QWidget()
        self._content.setVisible(False)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(
            26, 4, 0, 4
        )  # Indent under expand arrow
        self._content_layout.setSpacing(8)

        # Launch button
        self._launch_btn = QPushButton("Launch")
        self._launch_btn.setEnabled(False)
        _ = self._launch_btn.clicked.connect(self._on_launch_clicked)

        tooltip = self.config.tooltip or f"Launch {self.config.display_name}"
        tooltip += f" (Shortcut: {self.config.shortcut.upper()})"
        self._launch_btn.setToolTip(tooltip)
        self._content_layout.addWidget(self._launch_btn)

        # Launch description label (shows what will be opened)
        self._launch_description = QLabel()
        self._launch_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._launch_description.setVisible(False)
        self._content_layout.addWidget(self._launch_description)

        # Checkboxes
        if self.config.checkboxes:
            for cb_config in self.config.checkboxes:
                checkbox = QCheckBox(cb_config.label)
                checkbox.setToolTip(cb_config.tooltip)
                checkbox.setChecked(cb_config.default)
                self._content_layout.addWidget(checkbox)
                self._checkboxes[cb_config.key] = checkbox

        # Plate selector (always present in base)
        plate_row = QHBoxLayout()
        plate_row.setContentsMargins(0, 2, 0, 0)
        plate_row.setSpacing(4)

        self._plate_label = QLabel("Plate:")
        plate_row.addWidget(self._plate_label)

        self._plate_selector = QComboBox()
        self._plate_selector.setEnabled(False)
        self._plate_selector.setPlaceholderText("Select...")
        self._plate_selector.setMinimumWidth(80)
        plate_row.addWidget(self._plate_selector)
        plate_row.addStretch()

        self._content_layout.addLayout(plate_row)

        container_layout.addWidget(self._content)
        layout.addWidget(self._container)

        # Apply dynamic styles
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply/refresh styles using current design system values."""
        # Expand/collapse button
        self._expand_btn.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
            }
            QToolButton:hover {
                background-color: #333;
                border-radius: 2px;
            }
        """)

        # DCC name label
        self._name_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: {design_system.typography.size_small}px;
                color: {self.config.color};
            }}
        """)

        # Version label
        self._version_label.setStyleSheet(f"""
            QLabel {{
                color: #888;
                font-size: {design_system.typography.size_small}px;
            }}
        """)

        # Launch button
        self._launch_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.config.color};
                color: #ecf0f1;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: {design_system.typography.size_tiny}px;
            }}
            QPushButton:hover {{
                background-color: {lighten_color(self.config.color, factor=120)};
            }}
            QPushButton:pressed {{
                background-color: {darken_color(self.config.color)};
            }}
            QPushButton:disabled {{
                background-color: #2a2a2a;
                color: #666;
                border: 1px dashed #444;
            }}
        """)

        # Launch description label
        self._launch_description.setStyleSheet(f"""
            QLabel {{
                color: #888;
                font-size: {design_system.typography.size_tiny}px;
                margin-top: -4px;
            }}
        """)

        # Checkboxes
        for checkbox in self._checkboxes.values():
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    color: #aaa;
                    font-size: {design_system.typography.size_small}px;
                }}
                QCheckBox:hover {{
                    color: #ccc;
                }}
            """)

        # Plate label and selector
        if self._plate_label is not None:
            self._plate_label.setStyleSheet(
                f"QLabel {{ color: #888; font-size: {design_system.typography.size_small}px; }}"
            )

        if self._plate_selector is not None:
            self._plate_selector.setStyleSheet(f"""
                QComboBox {{
                    background-color: #2a2a2a;
                    color: #ecf0f1;
                    border: 1px solid #444;
                    border-radius: 3px;
                    padding: 2px 4px;
                    font-size: {design_system.typography.size_small}px;
                }}
                QComboBox:disabled {{
                    background-color: #1e1e1e;
                    color: #666;
                }}
                QComboBox::drop-down {{ border: none; }}
                QComboBox::down-arrow {{ image: none; }}
            """)

    def _toggle_expanded(self) -> None:
        """Toggle the expanded state."""
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        """Set the expanded state.

        Args:
            expanded: True to expand, False to collapse

        """
        if self._expanded != expanded:
            self._expanded = expanded
            self._expand_btn.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            )
            self._content.setVisible(expanded)
            self.expanded_changed.emit(self.config.name, expanded)

    def is_expanded(self) -> bool:
        """Return whether the section is expanded."""
        return self._expanded

    def _on_launch_clicked(self) -> None:
        """Handle launch button click."""
        if self._launch_in_progress:
            return

        self._launch_in_progress = True
        self._original_button_text = self._launch_btn.text()
        self._launch_btn.setEnabled(False)
        self._launch_btn.setText(f"Launching {self.config.display_name}...")

        # Emit with options
        options = self.get_options()
        self.launch_requested.emit(self.config.name, options)

        # Reset after 3 seconds
        QTimer.singleShot(3000, self._safe_reset_button_state)

    def _safe_reset_button_state(self) -> None:
        """Safely reset button state."""
        try:
            if not self.isHidden() and hasattr(self, "_launch_btn"):
                self._reset_button_state()
        except (RuntimeError, AttributeError):
            pass

    def _reset_button_state(self) -> None:
        """Reset button to original state.

        Note: Will not reset if _search_pending is True (async file search in progress).
        """
        # Don't reset while async search is pending - wait for search to complete
        if self._search_pending:
            return

        self._launch_in_progress = False
        self._launch_btn.setText(self._original_button_text)
        self._launch_btn.setEnabled(self._should_be_enabled)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the section.

        Args:
            enabled: True to enable launching

        """
        self._should_be_enabled = enabled
        if not self._launch_in_progress:
            self._launch_btn.setEnabled(enabled)

    def set_search_pending(self, pending: bool) -> None:
        """Set whether an async file search is in progress.

        When *pending* is ``True``, the launch button shows "Scanning…" text
        to indicate background work is happening.  When *pending* becomes
        ``False``, the button is reset to its normal state.

        No-op case: if ``_launch_in_progress`` is ``False`` at the time this
        method is called, neither branch takes effect.  This is intentional —
        the button state is only modified mid-launch so that normal idle state
        is not disrupted by stale search-complete notifications that arrive
        after the user has already cancelled or never started a launch.

        Args:
            pending: True if async search is in progress

        """
        self._search_pending = pending
        if pending:
            # Update button text to show search is in progress
            if self._launch_in_progress:
                self._launch_btn.setText("Scanning...")
        elif self._launch_in_progress:
            # Search complete - reset to normal state
            self._reset_button_state()

    def get_options(self) -> dict[str, bool | str | None]:
        """Get current launch options.

        Returns:
            Dict with checkbox states and selected plate

        """
        options: dict[str, bool | str | None] = {
            key: cb.isChecked() for key, cb in self._checkboxes.items()
        }
        options["selected_plate"] = self.get_selected_plate()
        return options

    def get_checkbox_states(self) -> dict[str, bool]:
        """Get the state of all checkboxes."""
        return {key: cb.isChecked() for key, cb in self._checkboxes.items()}

    def set_available_plates(self, plates: list[str]) -> None:
        """Update plate selector with available plates.

        Args:
            plates: List of plate names (e.g., ['FG01', 'BG01'])

        """
        if not self._plate_selector:
            return

        self._plate_selector.clear()
        if plates:
            self._plate_selector.addItems(plates)
            self._plate_selector.setCurrentIndex(0)  # Pre-select first plate
            self._plate_selector.setEnabled(True)
        else:
            self._plate_selector.setEnabled(False)
            self._plate_selector.setPlaceholderText("No plates available")

    def get_selected_plate(self) -> str | None:
        """Get currently selected plate name."""
        if not self._plate_selector or not self._plate_selector.isEnabled():
            return None
        text = self._plate_selector.currentText()
        return text or None

    def set_version_info(self, version: str | None, age: str | None = None) -> None:
        """Set version info displayed in collapsed header.

        Args:
            version: Version string (e.g., "v005") or None
            age: Age string (e.g., "21m ago") or None

        """
        self._version_info = version
        self._age_info = age
        self._update_version_label()

    def _update_version_label(self) -> None:
        """Update the version label display."""
        if self._version_info:
            text = self._version_info
            if self._age_info:
                text += f" | {self._age_info}"
            self._version_label.setText(text)
            self._version_label.setVisible(True)
        else:
            self._version_label.setVisible(False)

    def set_launch_description(
        self, version: str | None, plate: str | None = None
    ) -> None:
        """Update the 'Opens:' description below launch button.

        Args:
            version: Version string (e.g., "v005") or None to hide
            plate: Plate name (e.g., "FG01") or None

        """
        if version:
            parts = [version]
            if plate:
                parts.append(plate)
            self._launch_description.setText(f"Opens: {' | '.join(parts)}")
            self._launch_description.setVisible(True)
        else:
            self._launch_description.setVisible(False)
