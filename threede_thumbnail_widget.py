"""Enhanced thumbnail widget for displaying 3DE scene thumbnails with additional info."""

# Standard library imports

# Third-party imports
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QMenu

# Local application imports
from config import Config
from logging_mixin import LoggingMixin
from threede_scene_model import ThreeDEScene
from thumbnail_widget_base import ThumbnailWidgetBase


# Set up logger for this module


class ThreeDEThumbnailWidget(LoggingMixin, ThumbnailWidgetBase):
    """Widget displaying a 3DE scene thumbnail with shot, user, and plate info."""

    # Signals - maintain backward compatibility
    clicked = Signal(object)  # ThreeDEScene
    double_clicked = Signal(object)  # ThreeDEScene

    def __init__(
        self, scene: ThreeDEScene, size: int = Config.DEFAULT_THUMBNAIL_SIZE
    ) -> None:
        # Store scene reference for backward compatibility
        self.scene = scene
        # Initialize instance variables (set in _setup_custom_ui)
        self.shot_label: QLabel | None = None
        self.user_label: QLabel | None = None
        self.plate_label: QLabel | None = None
        super().__init__(scene, size)

    def _setup_custom_ui(self) -> None:
        """Set up custom UI elements specific to 3DE scene thumbnails."""
        # Shot name label (larger, bold)
        self.shot_label = QLabel(self.scene.full_name)
        self.shot_label.setObjectName("shot")
        self.shot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shot_label.setWordWrap(True)
        shot_font = self.shot_label.font()
        shot_font.setPointSize(10)
        shot_font.setBold(True)
        self.shot_label.setFont(shot_font)

        self.content_layout.addWidget(self.shot_label)

        # User label (smaller)
        self.user_label = QLabel(self.scene.user)
        self.user_label.setObjectName("user")
        self.user_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        user_font = self.user_label.font()
        user_font.setPointSize(8)
        self.user_label.setFont(user_font)

        self.content_layout.addWidget(self.user_label)

        # Plate label (highlighted)
        self.plate_label = QLabel(self.scene.plate)
        self.plate_label.setObjectName("plate")
        self.plate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plate_font = self.plate_label.font()
        plate_font.setPointSize(9)
        plate_font.setBold(True)
        self.plate_label.setFont(plate_font)

        self.content_layout.addWidget(self.plate_label)

        # Apply initial style
        self._update_style()

    def _get_selected_style(self) -> str:
        """Get the CSS style for selected state."""
        return """
            ThreeDEThumbnailWidget {
                background-color: #0d7377;
                border: 3px solid #14ffec;
                border-radius: 8px;
            }
            QLabel#shot {
                color: #14ffec;
                font-weight: bold;
                background-color: transparent;
            }
            QLabel#user {
                color: #aaffff;
                background-color: transparent;
            }
            QLabel#plate {
                color: #ffff14;
                font-weight: bold;
                background-color: #0d7377;
                padding: 2px 6px;
                border-radius: 3px;
            }
            QLabel#thumbnail {
                border: 1px solid #14ffec;
                border-radius: 4px;
                padding: 2px;
                background-color: transparent;
            }
        """

    def _get_unselected_style(self) -> str:
        """Get the CSS style for unselected state."""
        return """
            ThreeDEThumbnailWidget {
                background-color: #2b2b2b;
                border: 2px solid #444;
                border-radius: 6px;
            }
            ThreeDEThumbnailWidget:hover {
                background-color: #3a3a3a;
                border: 2px solid #888;
            }
            QLabel#shot {
                color: white;
                font-weight: bold;
                background-color: transparent;
            }
            QLabel#user {
                color: #ccc;
                background-color: transparent;
            }
            QLabel#plate {
                color: #ffd700;
                font-weight: bold;
                background-color: #444;
                padding: 2px 6px;
                border-radius: 3px;
            }
            QLabel {
                border: none;
                background-color: transparent;
            }
        """

    def _create_context_menu(self) -> QMenu:
        """Create and return the context menu for this widget."""
        menu = QMenu(self)

        # Add "Open Shot Folder" action only - matching ThumbnailWidget behavior
        open_folder_action = menu.addAction("Open Shot Folder")
        _ = open_folder_action.triggered.connect(self._open_shot_folder)

        return menu
