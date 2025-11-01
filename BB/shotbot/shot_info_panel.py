"""Shot info panel widget for displaying current shot details."""

import logging
from pathlib import Path
from typing import Optional, Union

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from cache_manager import CacheManager, ThumbnailCacheLoader
from shot_model import Shot

# Set up logger for this module
logger = logging.getLogger(__name__)


class ShotInfoPanel(QWidget):
    """Panel displaying current shot information."""

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        super().__init__()
        self._current_shot: Optional[Shot] = None
        self.cache_manager = cache_manager or CacheManager()  # Make public
        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI."""
        # Main layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)

        # Thumbnail preview
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(128, 128)
        self.thumbnail_label.setScaledContents(True)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("""
            QLabel {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.thumbnail_label)

        # Info section
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)

        # Shot name (large)
        self.shot_name_label = QLabel("No Shot Selected")
        shot_font = QFont()
        shot_font.setPointSize(18)
        shot_font.setWeight(QFont.Weight.Bold)
        self.shot_name_label.setFont(shot_font)
        self.shot_name_label.setStyleSheet("color: #14ffec;")
        info_layout.addWidget(self.shot_name_label)

        # Show and sequence
        self.show_sequence_label = QLabel("")
        show_font = QFont()
        show_font.setPointSize(12)
        self.show_sequence_label.setFont(show_font)
        self.show_sequence_label.setStyleSheet("color: #aaa;")
        info_layout.addWidget(self.show_sequence_label)

        # Workspace path
        self.path_label = QLabel("")
        path_font = QFont()
        path_font.setPointSize(9)
        self.path_label.setFont(path_font)
        self.path_label.setStyleSheet("color: #777;")
        self.path_label.setWordWrap(True)
        info_layout.addWidget(self.path_label)

        info_layout.addStretch()
        layout.addLayout(info_layout, 1)

        # Style the panel
        self.setStyleSheet("""
            ShotInfoPanel {
                background-color: #1a1a1a;
                border: 1px solid #333;
                border-radius: 6px;
            }
        """)

        # Set minimum height
        self.setMinimumHeight(150)

    def set_shot(self, shot: Optional[Shot]):
        """Set the current shot to display."""
        self._current_shot = shot
        self._update_display()

    def _update_display(self):
        """Update the display with current shot info."""
        if self._current_shot:
            # Update labels
            self.shot_name_label.setText(self._current_shot.full_name)
            self.show_sequence_label.setText(
                f"{self._current_shot.show} • {self._current_shot.sequence}"
            )
            self.path_label.setText(f"Workspace: {self._current_shot.workspace_path}")

            # Load thumbnail
            self._load_thumbnail()
        else:
            # Clear display
            self.shot_name_label.setText("No Shot Selected")
            self.show_sequence_label.setText("")
            self.path_label.setText("")
            self._set_placeholder_thumbnail()

    def _load_thumbnail(self):
        """Load thumbnail for current shot."""
        if not self._current_shot:
            return

        # First check cache
        cache_path = self.cache_manager.get_cached_thumbnail(
            self._current_shot.show,
            self._current_shot.sequence,
            self._current_shot.shot,
        )

        if cache_path and cache_path.exists():
            # Load from cache
            self._load_pixmap_from_path(cache_path)
        else:
            # Try to load from source
            thumb_path = self._current_shot.get_thumbnail_path()
            if thumb_path and thumb_path.exists():
                self._load_pixmap_from_path(thumb_path)

                # Also cache it for next time
                cache_loader = ThumbnailCacheLoader(
                    self.cache_manager,
                    thumb_path,
                    self._current_shot.show,
                    self._current_shot.sequence,
                    self._current_shot.shot,
                )
                cache_loader.signals.loaded.connect(self._on_thumbnail_cached)
                QThreadPool.globalInstance().start(cache_loader)
            else:
                # Fall back to placeholder
                self._set_placeholder_thumbnail()

    def _load_pixmap_from_path(self, path: Union[str, Path]):
        """Load and display pixmap from path with bounds checking and error handling."""
        if not path:
            logger.debug("No path provided for thumbnail loading")
            self._set_placeholder_thumbnail()
            return

        path_obj = Path(path) if isinstance(path, str) else path
        if not path_obj.exists():
            logger.debug(f"Thumbnail path does not exist: {path}")
            self._set_placeholder_thumbnail()
            return

        pixmap = None
        scaled = None
        try:
            # Load the image
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                logger.debug(f"Failed to load thumbnail: {path}")
                self._set_placeholder_thumbnail()
                return

            # Use utility for memory bounds checking (with smaller limits for info panel)
            from config import Config
            from utils import ImageUtils

            if not ImageUtils.validate_image_dimensions(
                pixmap.width(),
                pixmap.height(),
                max_dimension=Config.MAX_INFO_PANEL_DIMENSION_PX,
            ):
                self._set_placeholder_thumbnail()
                return

            # Scale to display size
            scaled = pixmap.scaled(
                128,
                128,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            if scaled.isNull():
                logger.warning(f"Failed to scale thumbnail: {path}")
                self._set_placeholder_thumbnail()
                return

            self.thumbnail_label.setPixmap(scaled)
            logger.debug(f"Successfully loaded info panel thumbnail: {path}")

        except FileNotFoundError:
            logger.debug(f"Thumbnail file not found: {path}")
            self._set_placeholder_thumbnail()
        except PermissionError:
            logger.warning(f"Permission denied loading thumbnail: {path}")
            self._set_placeholder_thumbnail()
        except MemoryError:
            logger.error(f"Out of memory loading thumbnail: {path}")
            self._set_placeholder_thumbnail()
        except (OSError, IOError) as e:
            logger.warning(f"I/O error loading thumbnail {path}: {e}")
            self._set_placeholder_thumbnail()
        except Exception as e:
            logger.exception(f"Unexpected error loading thumbnail {path}: {e}")
            self._set_placeholder_thumbnail()
        finally:
            # Clean up Qt objects
            del pixmap, scaled

    def _on_thumbnail_cached(
        self, show: str, sequence: str, shot: str, cache_path: str
    ):
        """Handle thumbnail cached signal."""
        # Update display if this is still the current shot
        if (
            self._current_shot
            and self._current_shot.show == show
            and self._current_shot.sequence == sequence
            and self._current_shot.shot == shot
        ):
            self._load_pixmap_from_path(cache_path)

    def _set_placeholder_thumbnail(self):
        """Set placeholder thumbnail."""
        placeholder = QPixmap(128, 128)
        placeholder.fill(Qt.GlobalColor.transparent)
        self.thumbnail_label.setPixmap(placeholder)
        self.thumbnail_label.setText("No Image")
        self.thumbnail_label.setStyleSheet("""
            QLabel {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 4px;
                color: #666;
            }
        """)
