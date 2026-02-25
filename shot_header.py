"""Shot header widget for compact shot information display.

Displays shot name, show/sequence, workspace path with copy button,
and a DCC status strip showing latest file versions for each application.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from design_system import design_system
from qt_widget_mixin import QtWidgetMixin
from scene_file import FILE_TYPE_COLORS, FileType


if TYPE_CHECKING:
    from scene_file import SceneFile
    from shot_model import Shot


@final
@dataclass
class DCCStatus:
    """Status information for a DCC application.

    Attributes:
        version: Version string (e.g., "v005") or None if no files
        age: Human-readable age (e.g., "21m ago") or None
        user: Username who last modified, or None

    """

    version: str | None = None
    age: str | None = None
    user: str | None = None


@final
class ShotHeader(QtWidgetMixin, QWidget):
    """Compact shot header with DCC status strip.

    Displays:
    - Shot name (20px bold, cyan)
    - Show | Sequence (12px, muted)
    - Workspace path + copy button (10px, dim)
    - DCC Status Strip (latest version per app)

    """

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the shot header.

        Args:
            parent: Optional parent widget

        """
        super().__init__(parent)
        self._current_shot: Shot | None = None
        self._empty_message: str = "No Shot Selected"
        self._dcc_status: dict[FileType, DCCStatus] = {}

        self._setup_ui()

        # Connect to scale changes for live updates
        _ = design_system.scale_changed.connect(self._apply_styles)

    def _setup_ui(self) -> None:
        """Set up the header UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(4)

        # Row 1: Shot name (bold, cyan)
        self._shot_name_label = QLabel(self._empty_message)
        self._shot_name_label.setStyleSheet("color: #14ffec;")
        main_layout.addWidget(self._shot_name_label)

        # Row 2: Show | Sequence (muted)
        self._show_sequence_label = QLabel("")
        self._show_sequence_label.setStyleSheet("color: #aaa;")
        main_layout.addWidget(self._show_sequence_label)

        # Row 3: Path with copy button
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_row.setContentsMargins(0, 4, 0, 0)

        self._path_label = QLabel("")
        self._path_label.setStyleSheet("color: #666;")
        self._path_label.setWordWrap(True)
        path_row.addWidget(self._path_label, 1)

        self._copy_path_btn = QToolButton()
        self._copy_path_btn.setText("📋")
        self._copy_path_btn.setToolTip("Copy path to clipboard")
        _ = self._copy_path_btn.clicked.connect(self._on_copy_path)
        path_row.addWidget(self._copy_path_btn)

        main_layout.addLayout(path_row)

        # Row 4: DCC Status Strip
        self._status_strip = QWidget()
        status_layout = QHBoxLayout(self._status_strip)
        status_layout.setContentsMargins(0, 8, 0, 0)
        status_layout.setSpacing(12)

        # Create status labels for each DCC type
        self._status_labels: dict[FileType, QLabel] = {}
        for file_type in FileType:
            label = QLabel()
            label.setVisible(False)
            status_layout.addWidget(label)
            self._status_labels[file_type] = label

        status_layout.addStretch()
        main_layout.addWidget(self._status_strip)

        # Panel styling
        self.setStyleSheet("""
            ShotHeader {
                background-color: #1a1a1a;
                border: 1px solid #333;
                border-radius: 6px;
            }
        """)

        # Apply font sizes
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Apply/refresh styles using current design system values."""
        # Shot name font (h2, bold)
        shot_font = QFont()
        shot_font.setPixelSize(design_system.typography.size_h2)
        shot_font.setWeight(QFont.Weight.Bold)
        self._shot_name_label.setFont(shot_font)

        # Show/sequence font (small)
        show_font = QFont()
        show_font.setPixelSize(design_system.typography.size_small)
        self._show_sequence_label.setFont(show_font)

        # Path font (extra tiny)
        path_font = QFont()
        path_font.setPixelSize(design_system.typography.size_extra_tiny)
        self._path_label.setFont(path_font)

        # Copy button
        self._copy_path_btn.setStyleSheet(f"""
            QToolButton {{
                background-color: transparent;
                border: none;
                font-size: {design_system.typography.size_body}px;
                padding: 2px;
            }}
            QToolButton:hover {{
                background-color: #333;
                border-radius: 4px;
            }}
        """)

        # Status labels
        for file_type, label in self._status_labels.items():
            label.setStyleSheet(f"""
                QLabel {{
                    color: {FILE_TYPE_COLORS[file_type]};
                    font-size: {design_system.typography.size_extra_tiny}px;
                    padding: 2px 6px;
                    background-color: #252525;
                    border-radius: 3px;
                }}
            """)

    def _on_copy_path(self) -> None:
        """Handle copy path button click."""
        if self._current_shot and self._current_shot.workspace_path:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(self._current_shot.workspace_path)

    def set_shot(self, shot: Shot | None) -> None:
        """Set the current shot to display.

        Args:
            shot: Shot to display, or None to clear

        """
        self._current_shot = shot
        self._update_display()

    def _update_display(self) -> None:
        """Update the display with current shot info."""
        if self._current_shot:
            self._shot_name_label.setText(self._current_shot.full_name)
            self._show_sequence_label.setText(
                f"{self._current_shot.show} • {self._current_shot.sequence}"
            )
            self._path_label.setText(self._current_shot.workspace_path)
        else:
            self._shot_name_label.setText(self._empty_message)
            self._show_sequence_label.setText("")
            self._path_label.setText("")
            # Clear status strip
            for label in self._status_labels.values():
                label.setVisible(False)

    def set_empty_message(self, message: str) -> None:
        """Set the message shown when no shot is selected.

        Args:
            message: Empty state message

        """
        self._empty_message = message
        if self._current_shot is None:
            self._shot_name_label.setText(self._empty_message)

    def set_dcc_status(self, status: dict[FileType, DCCStatus]) -> None:
        """Set the DCC status information for the status strip.

        Args:
            status: Mapping from FileType to DCCStatus

        """
        self._dcc_status = status
        self._update_status_strip()

    def _update_status_strip(self) -> None:
        """Update the DCC status strip labels."""
        for file_type, label in self._status_labels.items():
            status = self._dcc_status.get(file_type)
            if status and status.version:
                # Format: "3DE v005 (21m)"
                display_name = _FILE_TYPE_SHORT_NAMES.get(file_type, file_type.name)
                text = f"{display_name} {status.version}"
                if status.age:
                    # Shorten age for compact display
                    short_age = self._shorten_age(status.age)
                    text += f" ({short_age})"
                label.setText(text)
                label.setVisible(True)
            else:
                label.setVisible(False)

    def _shorten_age(self, age: str) -> str:
        """Shorten age string for compact display.

        Args:
            age: Full age string (e.g., "21 minutes ago")

        Returns:
            Shortened age (e.g., "21m")

        """
        # Convert "X minutes ago" -> "Xm", "X hours ago" -> "Xh", etc.
        age = age.replace(" ago", "").replace("just now", "now")
        age = age.replace(" minutes", "m").replace(" minute", "m")
        age = age.replace(" hours", "h").replace(" hour", "h")
        age = age.replace(" days", "d").replace(" day", "d")
        age = age.replace(" weeks", "w").replace(" week", "w")
        age = age.replace(" months", "mo").replace(" month", "mo")
        return age.replace("yesterday", "1d")

    def update_from_files(
        self, files_by_type: dict[FileType, list[SceneFile]]
    ) -> None:
        """Update DCC status from discovered scene files.

        Extracts the latest file per type and updates the status strip.

        Args:
            files_by_type: Mapping from FileType to list of SceneFile

        """
        status: dict[FileType, DCCStatus] = {}

        for file_type, files in files_by_type.items():
            if files:
                # Files should be sorted by modified time (newest first)
                latest = files[0]
                version_str = f"v{latest.version:03d}" if latest.version else None
                status[file_type] = DCCStatus(
                    version=version_str,
                    age=latest.relative_age,
                    user=latest.user,
                )
            else:
                status[file_type] = DCCStatus()

        self.set_dcc_status(status)


# Short display names for status strip
_FILE_TYPE_SHORT_NAMES: dict[FileType, str] = {
    FileType.THREEDE: "3DE",
    FileType.MAYA: "Maya",
    FileType.NUKE: "Nuke",
}
