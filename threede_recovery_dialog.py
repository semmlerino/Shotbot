"""Recovery dialog for 3DE crash files.

This dialog displays detected crash files and allows the user to
recover them to the next available version number.
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from logging_mixin import LoggingMixin
from qt_widget_mixin import QtWidgetMixin
from threede_recovery import CrashFileInfo


class ThreeDERecoveryDialog(QDialog, QtWidgetMixin, LoggingMixin):  # pyright: ignore[reportIncompatibleMethodOverride]
    """Dialog for recovering 3DE crash files.

    Displays a list of detected crash files with details:
    - Original scene name
    - Crash file name
    - Target recovery name (next version)
    - File size and modification time

    User can choose to:
    - Recover latest crash file
    - Cancel recovery operation
    """

    # Signals
    recovery_requested = Signal(CrashFileInfo)  # Emitted when user clicks Recover

    def __init__(
        self,
        crash_files: list[CrashFileInfo],
        parent: QWidget | None = None,
    ) -> None:
        """Initialize recovery dialog.

        Args:
            crash_files: List of detected crash files
            parent: Parent widget
        """
        super().__init__(parent)
        self.crash_files = crash_files
        self.selected_crash: CrashFileInfo | None = None

        # Group crash files by base scene name
        self._crash_groups = self._group_crashes_by_scene()

        self.setWindowTitle("Recover 3DE Crash Files")
        self.setModal(True)

        # Setup window geometry management
        self.setup_window_geometry("threede_recovery_dialog", QSize(700, 500))
        self.setMinimumWidth(600)

        self._setup_ui()
        self._connect_signals()

        self.logger.info(f"Recovery dialog opened with {len(crash_files)} crash file(s)")

    def _group_crashes_by_scene(self) -> dict[str, list[CrashFileInfo]]:
        """Group crash files by their base scene name.

        Returns:
            Dictionary mapping base scene names to lists of crash files
        """
        groups: dict[str, list[CrashFileInfo]] = {}

        for crash_info in self.crash_files:
            base_name = crash_info.base_name
            if base_name not in groups:
                groups[base_name] = []
            groups[base_name].append(crash_info)

        # Sort each group by modification time (newest first)
        for crash_list in groups.values():
            crash_list.sort(key=lambda x: x.modification_time, reverse=True)

        return groups

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Header
        header_label = QLabel(

                "The following 3DE crash files were detected. "
                "Select a scene to recover the latest crash file to the next version."

        )
        header_label.setWordWrap(True)
        header_label.setStyleSheet("font-size: 11pt; padding: 10px;")
        layout.addWidget(header_label)

        # Scroll area for crash file groups
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Create a group box for each scene with crash files
        self.radio_buttons: dict[str, QRadioButton] = {}

        for base_name, crash_list in self._crash_groups.items():
            group_box = self._create_crash_group(base_name, crash_list)
            scroll_layout.addWidget(group_box)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # Instructions
        instructions = QLabel(

                "Note: The crash file will be copied to the recovery name, "
                "and the original crash file will be renamed with a timestamp suffix."

        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("font-size: 9pt; color: #888; font-style: italic; padding: 10px;")
        layout.addWidget(instructions)

        # Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.recover_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.recover_button.setText("Recover")
        self.recover_button.setEnabled(False)  # Disabled until a crash is selected

        _ = self.button_box.accepted.connect(self._on_recover)
        _ = self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _create_crash_group(
        self,
        base_name: str,
        crash_list: list[CrashFileInfo],
    ) -> QGroupBox:
        """Create a group box for a scene's crash files.

        Args:
            base_name: Base scene name (e.g., "scene_v010")
            crash_list: List of crash files for this scene (sorted newest first)

        Returns:
            QGroupBox widget containing crash file details
        """
        # Latest crash info (first in sorted list)
        latest_crash = crash_list[0]

        group_box = QGroupBox(f"{base_name}.3de")
        group_box.setCheckable(False)
        group_layout = QVBoxLayout(group_box)

        # Radio button for selection
        radio_text = f"Recover to: {latest_crash.recovery_name}"
        if len(crash_list) > 1:
            radio_text += f"  ({len(crash_list)} crash files found)"

        radio = QRadioButton(radio_text)
        self.radio_buttons[base_name] = radio
        group_layout.addWidget(radio)

        # Crash file details in a form layout
        details_layout = QFormLayout()
        details_layout.setContentsMargins(20, 5, 5, 5)

        # Crash file name
        crash_name_label = QLabel(latest_crash.crash_path.name)
        crash_name_label.setStyleSheet("font-family: monospace;")
        details_layout.addRow("Crash File:", crash_name_label)

        # Recovery target
        recovery_name_label = QLabel(latest_crash.recovery_name)
        recovery_name_label.setStyleSheet("font-family: monospace; font-weight: bold; color: #4caf50;")
        details_layout.addRow("Recovery Name:", recovery_name_label)

        # File size
        size_mb = latest_crash.file_size / (1024 * 1024)
        size_label = QLabel(f"{size_mb:.2f} MB")
        details_layout.addRow("Size:", size_label)

        # Modification time
        time_str = latest_crash.modification_time.strftime("%Y-%m-%d %H:%M:%S")
        time_label = QLabel(time_str)
        details_layout.addRow("Modified:", time_label)

        # Directory path
        dir_path = str(latest_crash.crash_path.parent)
        dir_label = QLabel(dir_path)
        dir_label.setStyleSheet("font-size: 8pt; color: #888; font-family: monospace;")
        dir_label.setWordWrap(True)
        details_layout.addRow("Location:", dir_label)

        group_layout.addLayout(details_layout)

        # Show additional crash files if multiple exist
        if len(crash_list) > 1:
            additional_label = QLabel(

                    f"Note: {len(crash_list) - 1} older crash file(s) also found. "
                    "Only the latest will be recovered."

            )
            additional_label.setStyleSheet(
                "font-size: 8pt; color: #ff9800; font-style: italic; padding-left: 20px;"
            )
            additional_label.setWordWrap(True)
            group_layout.addWidget(additional_label)

        return group_box

    def _connect_signals(self) -> None:
        """Connect signal handlers."""
        # Enable recover button when a radio button is selected
        for base_name, radio in self.radio_buttons.items():
            _ = radio.toggled.connect(self._on_selection_changed)

    def _on_selection_changed(self) -> None:
        """Handle radio button selection changes."""
        # Find which radio button is selected
        for base_name, radio in self.radio_buttons.items():
            if radio.isChecked():
                # Get the latest crash for this scene
                crash_list = self._crash_groups[base_name]
                self.selected_crash = crash_list[0]
                self.recover_button.setEnabled(True)
                self.logger.debug(f"Selected crash: {self.selected_crash.crash_path.name}")
                return

        # No selection
        self.selected_crash = None
        self.recover_button.setEnabled(False)

    def _on_recover(self) -> None:
        """Handle recover button click."""
        if not self.selected_crash:
            self.logger.warning("Recover button clicked with no crash selected")
            return

        self.logger.info(

                f"Recovery requested: {self.selected_crash.crash_path.name} → "
                f"{self.selected_crash.recovery_name}"

        )

        # Emit signal with selected crash info
        self.recovery_requested.emit(self.selected_crash)

        # Accept dialog
        self.accept()

    def get_selected_crash(self) -> CrashFileInfo | None:
        """Get the selected crash file info.

        Returns:
            Selected crash file info, or None if no selection
        """
        return self.selected_crash


class ThreeDERecoveryResultDialog(QDialog, QtWidgetMixin, LoggingMixin):  # pyright: ignore[reportIncompatibleMethodOverride]
    """Dialog showing recovery operation results.

    Displays success/failure message after recovery attempt.
    """

    def __init__(
        self,
        success: bool,
        recovered_path: Path | None = None,
        archived_path: Path | None = None,
        error_message: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize result dialog.

        Args:
            success: Whether recovery was successful
            recovered_path: Path to recovered file (if successful)
            archived_path: Path to archived crash file (if successful)
            error_message: Error message (if failed)
            parent: Parent widget
        """
        super().__init__(parent)
        self.success = success
        self.recovered_path = recovered_path
        self.archived_path = archived_path
        self.error_message = error_message

        self.setWindowTitle("Recovery Result")
        self.setModal(True)
        self.setup_window_geometry("threede_recovery_result_dialog", QSize(600, 300))

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        if self.success:
            # Success message
            status_label = QLabel("✓ Recovery Successful")
            status_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #4caf50;")
            layout.addWidget(status_label)

            info_label = QLabel("The crash file has been successfully recovered.")
            info_label.setWordWrap(True)
            layout.addWidget(info_label)

            # Details
            details_layout = QFormLayout()
            details_layout.setContentsMargins(20, 10, 20, 10)

            if self.recovered_path:
                recovered_label = QLabel(self.recovered_path.name)
                recovered_label.setStyleSheet("font-family: monospace; font-weight: bold;")
                details_layout.addRow("Recovered File:", recovered_label)

                path_label = QLabel(str(self.recovered_path.parent))
                path_label.setStyleSheet("font-family: monospace; font-size: 8pt; color: #888;")
                path_label.setWordWrap(True)
                details_layout.addRow("Location:", path_label)

            if self.archived_path:
                archived_label = QLabel(self.archived_path.name)
                archived_label.setStyleSheet("font-family: monospace;")
                details_layout.addRow("Archived Crash File:", archived_label)

            layout.addLayout(details_layout)

        else:
            # Error message
            status_label = QLabel("✗ Recovery Failed")
            status_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #f44336;")
            layout.addWidget(status_label)

            error_text = self.error_message or "An unknown error occurred during recovery."
            error_label = QLabel(error_text)
            error_label.setWordWrap(True)
            error_label.setStyleSheet("color: #f44336; padding: 10px;")
            layout.addWidget(error_label)

        layout.addStretch()

        # Close button
        close_button = QPushButton("Close")
        _ = close_button.clicked.connect(self.accept)
        close_button.setDefault(True)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        layout.addLayout(button_layout)
