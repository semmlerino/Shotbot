"""Thumbnail widget for displaying shot thumbnails.

DEPRECATED: This module is deprecated and will be removed in a future version.
The Model/View architecture (shot_grid_view.py with shot_grid_delegate.py)
replaces individual thumbnail widgets with efficient delegate-based rendering,
providing 98.9% memory reduction by eliminating widget creation overhead.

Note: Still used by threede_shot_grid.py which needs migration to Model/View.
"""
# Standard library imports
# Third-party imports
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QMenu, QWidget

# Local application imports
from config import Config
from design_system import design_system
from logging_mixin import LoggingMixin
from shot_model import Shot
from thumbnail_widget_base import ThumbnailWidgetBase
from typing_compat import override


# Set up logger for this module


class ThumbnailWidget(LoggingMixin, ThumbnailWidgetBase):
    """Widget displaying a shot thumbnail and name."""

    # Signals - maintain backward compatibility
    clicked: Signal = Signal(object)  # Shot
    double_clicked: Signal = Signal(object)  # Shot

    def __init__(
        self,
        shot: Shot,
        size: int = Config.DEFAULT_THUMBNAIL_SIZE,
        parent: QWidget | None = None,
    ) -> None:
        # Store shot reference for backward compatibility
        self.shot: Shot = shot
        # Initialize instance variable (set in _setup_custom_ui)
        self.name_label: QLabel | None = None
        super().__init__(shot, size, parent)

    @override
    def _setup_custom_ui(self) -> None:
        """Set up custom UI elements specific to shot thumbnails."""
        # Shot name label
        self.name_label = QLabel(self.shot.full_name)
        self.name_label.setObjectName("name")  # For CSS targeting
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        font = self.name_label.font()
        font.setPixelSize(design_system.typography.size_small)  # Larger font
        self.name_label.setFont(font)

        # Add to content container instead of main layout
        self.content_layout.addWidget(self.name_label)

        # Frame range label (e.g., "1001-1150" or "No plate")
        self.frame_range_label: QLabel = QLabel(self.shot.frame_range_display)
        self.frame_range_label.setObjectName("frame_range")
        self.frame_range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_range_font = self.frame_range_label.font()
        frame_range_font.setPixelSize(design_system.typography.size_extra_small)  # Larger
        self.frame_range_label.setFont(frame_range_font)
        self.frame_range_label.setStyleSheet("color: #88aacc;")  # Blue-ish tint
        self.frame_range_label.setMinimumHeight(16)
        self.content_layout.addWidget(self.frame_range_label)

        # Add spacer to maintain consistent height with 3DE thumbnails
        spacer_label = QLabel(" ")
        spacer_label.setObjectName("spacer")
        spacer_font = spacer_label.font()
        spacer_font.setPixelSize(design_system.typography.size_extra_small)
        spacer_label.setFont(spacer_font)
        spacer_label.setMinimumHeight(18)
        self.content_layout.addWidget(spacer_label)

        # Apply initial style
        self._update_style()

    @override
    def _get_selected_style(self) -> str:
        """Get the CSS style for selected state."""
        return """
            ThumbnailWidget {
                background-color: #0d7377;
                border: 3px solid #14ffec;
                border-radius: 8px;
            }
            QLabel#name {
                color: #14ffec;
                font-weight: bold;
            }
            QLabel#thumbnail {
                border: 1px solid #14ffec;
                border-radius: 4px;
                padding: 2px;
            }
            QLabel#spacer {
                color: transparent;
                background-color: transparent;
                border: none;
            }
            QLabel {
                background-color: transparent;
            }
        """

    @override
    def _get_unselected_style(self) -> str:
        """Get the CSS style for unselected state."""
        return """
            ThumbnailWidget {
                background-color: #2b2b2b;
                border: 2px solid #444;
                border-radius: 6px;
            }
            ThumbnailWidget:hover {
                background-color: #3a3a3a;
                border: 2px solid #888;
            }
            QLabel#spacer {
                color: transparent;
                background-color: transparent;
                border: none;
            }
            QLabel {
                border: none;
                background-color: transparent;
            }
        """

    @override
    def _create_context_menu(self) -> QMenu:
        """Create and return the context menu for this widget."""
        menu = QMenu(self)

        # Add "Open Shot Folder" action
        open_folder_action = menu.addAction("Open Shot Folder")
        _ = open_folder_action.triggered.connect(self._open_shot_folder)

        # Add "Open Main Plate in RV" action
        open_plate_action = menu.addAction("Open Main Plate in RV")
        _ = open_plate_action.triggered.connect(self._open_main_plate_in_rv)

        return menu
