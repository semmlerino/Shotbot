"""Shot info panel widget for displaying current shot details."""

from __future__ import annotations

# Standard library imports
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Third-party imports
from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from cache.thumbnail_cache import ThumbnailCache
from design_system import design_system
from qt_widget_mixin import QtWidgetMixin
from shot_files_panel import ShotFilesPanel
from typing_compat import override
from utils import ImageUtils


if TYPE_CHECKING:
    # Local application imports
    from file_pin_manager import FilePinManager
    from notes_manager import NotesManager
    from shot_model import Shot


class ShotInfoPanel(QtWidgetMixin, QWidget):
    """Panel displaying current shot information and associated files."""

    # Instance attributes
    _files_panel: ShotFilesPanel
    _copy_path_btn: QToolButton
    _notes_manager: NotesManager | None
    _file_pin_manager: FilePinManager | None
    _notes_edit: QTextEdit

    def __init__(
        self,
        cache_manager: ThumbnailCache | None = None,
        notes_manager: NotesManager | None = None,
        file_pin_manager: FilePinManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        # Ensure we're in the main thread for Qt widget creation
        # Third-party imports
        from PySide6.QtCore import (
            QCoreApplication,
            QThread,
        )
        from PySide6.QtWidgets import (
            QApplication,
        )

        # Check if QApplication exists
        app_instance = QCoreApplication.instance()
        if app_instance is None:
            msg = "ShotInfoPanel: No QApplication instance found"
            raise RuntimeError(msg)

        # Check if we're in the main thread
        current_thread = QThread.currentThread()
        main_thread = app_instance.thread()
        if current_thread != main_thread:
            msg = (
                f"ShotInfoPanel must be created in the main thread. "
                f"Current thread: {current_thread}, "
                f"Main thread: {main_thread}"
            )
            raise RuntimeError(msg)

        # Additional safety check for QApplication type (relaxed for tests)
        # In test environments, QCoreApplication is acceptable since pytest-qt may create it
        # Standard library imports
        is_test_environment = "pytest" in sys.modules or "unittest" in sys.modules

        if not isinstance(app_instance, QApplication) and not is_test_environment:
            msg = (
                f"ShotInfoPanel: QCoreApplication instance is not a QApplication. "
                f"Type: {type(app_instance)}"
            )
            raise RuntimeError(msg)

        super().__init__(parent)
        self._current_shot: Shot | None = None
        self._empty_message: str = "No Shot Selected"

        if cache_manager is not None:
            self.cache_manager: ThumbnailCache = cache_manager
        else:
            test_dir = os.getenv("SHOTBOT_TEST_CACHE_DIR")
            if test_dir:
                default_dir = Path(test_dir)
            elif "pytest" in sys.modules or os.getenv("SHOTBOT_MODE") == "test":
                default_dir = Path.home() / ".shotbot" / "cache_test"
            elif os.getenv("SHOTBOT_MODE") == "mock":
                default_dir = Path.home() / ".shotbot" / "cache" / "mock"
            else:
                default_dir = Path.home() / ".shotbot" / "cache" / "production"
            default_dir.mkdir(parents=True, exist_ok=True)
            self.cache_manager = ThumbnailCache(default_dir)

        self._notes_manager = notes_manager
        self._file_pin_manager = file_pin_manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI with redesigned header layout."""
        # Main vertical layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # === HEADER SECTION (full width) ===
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        # Shot name (large, full width) - 24px bold
        self.shot_name_label: QLabel = QLabel("No Shot Selected")
        shot_font = QFont()
        shot_font.setPixelSize(design_system.typography.size_h2)
        shot_font.setWeight(QFont.Weight.Bold)
        self.shot_name_label.setFont(shot_font)
        self.shot_name_label.setStyleSheet("color: #14ffec;")
        header_layout.addWidget(self.shot_name_label)

        # Show | Sequence (smaller, muted) - 14px
        self.show_sequence_label: QLabel = QLabel("")
        show_font = QFont()
        show_font.setPixelSize(design_system.typography.size_small)
        self.show_sequence_label.setFont(show_font)
        self.show_sequence_label.setStyleSheet("color: #aaa;")
        header_layout.addWidget(self.show_sequence_label)

        # Frame range (e.g., "1001-1150" or "No plate")
        self.frame_range_label: QLabel = QLabel("")
        frame_range_font = QFont()
        frame_range_font.setPixelSize(design_system.typography.size_small)  # Larger
        self.frame_range_label.setFont(frame_range_font)
        self.frame_range_label.setStyleSheet("color: #88aacc;")  # Blue-ish tint
        header_layout.addWidget(self.frame_range_label)

        # Path row with copy button
        path_row = QHBoxLayout()
        path_row.setSpacing(8)

        self.path_label: QLabel = QLabel("")
        path_font = QFont()
        path_font.setPixelSize(design_system.typography.size_extra_tiny)
        self.path_label.setFont(path_font)
        self.path_label.setStyleSheet("color: #666;")
        self.path_label.setWordWrap(True)
        path_row.addWidget(self.path_label, 1)

        # Copy path button
        self._copy_path_btn = QToolButton()
        self._copy_path_btn.setText("📋")
        self._copy_path_btn.setToolTip("Copy path to clipboard")
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
        _ = self._copy_path_btn.clicked.connect(self._copy_path_to_clipboard)
        path_row.addWidget(self._copy_path_btn)

        header_layout.addLayout(path_row)
        main_layout.addWidget(header_widget)

        # === THUMBNAIL ROW (smaller, 96x96) ===
        thumb_row = QHBoxLayout()
        thumb_row.setContentsMargins(0, 5, 0, 5)

        self.thumbnail_label: QLabel = QLabel()
        self.thumbnail_label.setFixedSize(96, 96)
        self.thumbnail_label.setScaledContents(True)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("""
            QLabel {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        thumb_row.addWidget(self.thumbnail_label)
        thumb_row.addStretch()

        main_layout.addLayout(thumb_row)

        # === FILES PANEL ===
        self._files_panel = ShotFilesPanel(
            file_pin_manager=self._file_pin_manager,
            parent=self,
        )
        main_layout.addWidget(self._files_panel)

        # === NOTES SECTION ===
        notes_label = QLabel("Notes")
        notes_font = QFont()
        notes_font.setPixelSize(design_system.typography.size_small)
        notes_font.setWeight(QFont.Weight.Bold)
        notes_label.setFont(notes_font)
        notes_label.setStyleSheet("color: #888; margin-top: 8px;")
        main_layout.addWidget(notes_label)

        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("Add notes for this shot...")
        self._notes_edit.setMaximumHeight(100)
        self._notes_edit.setStyleSheet("""
            QTextEdit {
                background-color: #252525;
                color: #ddd;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 5px;
                font-size: 12px;
            }
            QTextEdit:focus {
                border: 1px solid #666;
            }
        """)
        _ = self._notes_edit.textChanged.connect(self._on_notes_changed)
        main_layout.addWidget(self._notes_edit)

        # Style the panel
        self.setStyleSheet("""
            ShotInfoPanel {
                background-color: #1a1a1a;
                border: 1px solid #333;
                border-radius: 6px;
            }
        """)

        # Set minimum height
        self.setMinimumHeight(200)

    def set_shot(self, shot: Shot | None) -> None:
        """Set the current shot to display."""
        self._current_shot = shot
        self._update_display()
        self._update_notes_display()
        # Update files panel
        self._files_panel.set_shot(shot)

    def set_empty_message(self, message: str) -> None:
        """Set the message shown when no shot/scene is selected.

        Args:
            message: The empty state message (e.g., "No Shot Selected" or "No Scene Selected")

        """
        self._empty_message = message
        if self._current_shot is None:
            self.shot_name_label.setText(self._empty_message)

    def _copy_path_to_clipboard(self) -> None:
        """Copy current shot workspace path to clipboard."""
        if self._current_shot and self._current_shot.workspace_path:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(self._current_shot.workspace_path)

    def _update_display(self) -> None:
        """Update the display with current shot info."""
        if self._current_shot:
            # Update labels
            self.shot_name_label.setText(self._current_shot.full_name)
            self.show_sequence_label.setText(
                f"{self._current_shot.show} • {self._current_shot.sequence}",
            )
            self.frame_range_label.setText(self._current_shot.frame_range_display)
            self.path_label.setText(f"Workspace: {self._current_shot.workspace_path}")

            # Load thumbnail
            self._load_thumbnail()
        else:
            # Clear display
            self.shot_name_label.setText(self._empty_message)
            self.show_sequence_label.setText("")
            self.frame_range_label.setText("")
            self.path_label.setText("")
            self._set_placeholder_thumbnail()

    def _update_notes_display(self) -> None:
        """Update notes display for current shot."""
        if self._current_shot and self._notes_manager:
            note = self._notes_manager.get_note(self._current_shot)
            _ = self._notes_edit.blockSignals(True)  # Avoid triggering save during load
            self._notes_edit.setPlainText(note)
            _ = self._notes_edit.blockSignals(False)
            self._notes_edit.setEnabled(True)
        else:
            _ = self._notes_edit.blockSignals(True)
            self._notes_edit.setPlainText("")
            _ = self._notes_edit.blockSignals(False)
            self._notes_edit.setEnabled(self._current_shot is not None)

    def _on_notes_changed(self) -> None:
        """Handle notes text change - save to manager."""
        if self._current_shot and self._notes_manager:
            self._notes_manager.set_note(
                self._current_shot, self._notes_edit.toPlainText()
            )

    def _load_thumbnail(self) -> None:
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
            # Load from cache asynchronously
            self._load_pixmap_async(cache_path)
        else:
            # Try to load from source
            thumb_path = self._current_shot.get_thumbnail_path()
            if thumb_path and thumb_path.exists():
                self._load_pixmap_async(thumb_path)

                # Cache in background thread to avoid UI freeze (50-500ms for PIL operations)
                cache_runnable = ThumbnailCacheRunnable(
                    thumb_path,
                    self._current_shot.show,
                    self._current_shot.sequence,
                    self._current_shot.shot,
                    self.cache_manager,
                )
                QThreadPool.globalInstance().start(cache_runnable)
            else:
                # Fall back to placeholder
                self._set_placeholder_thumbnail()

    def _load_pixmap_from_path(self, path: str | Path) -> None:
        """Load and display pixmap from path with bounds checking and error handling."""
        if not path:
            self.logger.debug("No path provided for thumbnail loading")
            self._set_placeholder_thumbnail()
            return

        path_obj = Path(path) if isinstance(path, str) else path
        if not path_obj.exists():
            self.logger.debug(f"Thumbnail path does not exist: {path}")
            self._set_placeholder_thumbnail()
            return

        image = None
        scaled_image = None
        try:
            # Load the image using QImage for thread safety
            image = QImage(str(path))
            if image.isNull():
                self.logger.debug(f"Failed to load thumbnail: {path}")
                self._set_placeholder_thumbnail()
                return

            # Use utility for memory bounds checking (with smaller limits for info panel)
            # Local application imports
            from config import Config

            if not ImageUtils.validate_image_dimensions(
                image.width(),
                image.height(),
                max_dimension=Config.MAX_INFO_PANEL_DIMENSION_PX,
            ):
                self._set_placeholder_thumbnail()
                return

            # Scale to display size
            scaled_image = image.scaled(
                128,
                128,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            if scaled_image.isNull():
                self.logger.warning(f"Failed to scale thumbnail: {path}")
                self._set_placeholder_thumbnail()
                return

            # Convert to QPixmap only in main thread for display
            # Third-party imports
            from PySide6.QtCore import QThread

            app_instance = QCoreApplication.instance()
            assert app_instance is not None  # Guaranteed by __init__ checks
            if QThread.currentThread() == app_instance.thread():
                pixmap = QPixmap.fromImage(scaled_image)
                self.thumbnail_label.setPixmap(pixmap)
            self.logger.debug(f"Successfully loaded info panel thumbnail: {path}")

        except FileNotFoundError:
            self.logger.debug(f"Thumbnail file not found: {path}")
            self._set_placeholder_thumbnail()
        except PermissionError:
            self.logger.warning(f"Permission denied loading thumbnail: {path}")
            self._set_placeholder_thumbnail()
        except MemoryError:
            self.logger.error(f"Out of memory loading thumbnail: {path}")
            self._set_placeholder_thumbnail()
        except OSError:
            self.logger.warning(f"I/O error loading thumbnail {path}", exc_info=True)
            self._set_placeholder_thumbnail()
        except Exception:
            self.logger.exception(f"Unexpected error loading thumbnail {path}")
            self._set_placeholder_thumbnail()
        finally:
            # Clean up Qt objects
            del image, scaled_image

    def _set_placeholder_thumbnail(self) -> None:
        """Set placeholder thumbnail - thread-safe using QImage."""
        # Use QImage for thread safety instead of QPixmap
        placeholder_image = QImage(128, 128, QImage.Format.Format_ARGB32)
        placeholder_image.fill(Qt.GlobalColor.transparent)

        # Convert to QPixmap only when setting on label (main thread only)
        # Third-party imports
        from PySide6.QtCore import QThread

        app_instance = QCoreApplication.instance()
        assert app_instance is not None  # Guaranteed by __init__ checks
        if QThread.currentThread() == app_instance.thread():
            placeholder = QPixmap.fromImage(placeholder_image)
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

    def _load_pixmap_async(self, path: str | Path) -> None:
        """Load pixmap asynchronously to avoid blocking UI."""
        # Create and start async loader
        loader = InfoPanelPixmapLoader(self, path)
        _ = loader.signals.loaded.connect(
            self._on_pixmap_loaded,
            type=Qt.ConnectionType.QueuedConnection,
        )
        _ = loader.signals.failed.connect(
            self._on_pixmap_failed,
            type=Qt.ConnectionType.QueuedConnection,
        )
        QThreadPool.globalInstance().start(loader)

    @Slot(QImage)
    def _on_pixmap_loaded(self, image: QImage) -> None:
        """Handle successful image loading - convert to pixmap in main thread."""
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        self.thumbnail_label.setPixmap(pixmap)

    @Slot()
    def _on_pixmap_failed(self) -> None:
        """Handle failed pixmap loading."""
        self._set_placeholder_thumbnail()


class InfoPanelPixmapLoader(QRunnable):
    """Async loader for info panel thumbnails."""

    class Signals(QObject):
        loaded: Signal = Signal(QImage)
        failed: Signal = Signal()

    def __init__(self, panel: ShotInfoPanel, path: str | Path) -> None:
        super().__init__()
        self.panel: ShotInfoPanel = panel  # Keep reference to prevent GC
        self.path: str | Path = path
        self.signals: InfoPanelPixmapLoader.Signals = self.Signals()
        self._target_dpr: float = max(1.0, panel.devicePixelRatioF())

    @override
    def run(self) -> None:
        """Load pixmap in background thread."""
        # Use module-level logger since QRunnable can't inherit from LoggingMixin
        logger = logging.getLogger(__name__)

        try:
            # Local application imports
            from PIL import Image
            from PySide6.QtCore import QSize

            from config import Config

            path_obj = Path(self.path) if isinstance(self.path, str) else self.path

            if not path_obj.exists():
                logger.debug(f"Thumbnail path does not exist: {self.path}")
                self.signals.failed.emit()
                return

            # Decode via Pillow first. Direct QImage(path) construction has proven
            # crash-prone in worker threads on some Qt builds under parallel load.
            try:
                with Image.open(path_obj) as pil_image:
                    _ = pil_image.load()

                    # Use utility for memory bounds checking (smaller limits for info panel)
                    if ImageUtils.is_image_too_large_for_thumbnail(
                        QSize(pil_image.width, pil_image.height),
                        Config.MAX_INFO_PANEL_DIMENSION_PX,
                    ):
                        logger.warning(
                            f"Image too large for info panel: {pil_image.width}x{pil_image.height}"
                        )
                        self.signals.failed.emit()
                        return

                    # Scale to appropriate size for info panel (larger than grid thumbnails)
                    max_size = 256  # Info panel can be larger than grid thumbnails
                    if pil_image.width > max_size or pil_image.height > max_size:
                        pil_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

                    rgba_image = pil_image.convert("RGBA")
            except OSError:
                logger.debug(f"Failed to load thumbnail: {self.path}")
                self.signals.failed.emit()
                return

            image = QImage(
                rgba_image.tobytes(),
                rgba_image.width,
                rgba_image.height,
                rgba_image.width * 4,
                QImage.Format.Format_RGBA8888,
            ).copy()
            if image.isNull():
                logger.warning(f"Failed to construct info panel image: {self.path}")
                self.signals.failed.emit()
                return

            if image.format() != QImage.Format.Format_ARGB32_Premultiplied:
                image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

            image.setDevicePixelRatio(self._target_dpr)
            image = image.copy()

            self.signals.loaded.emit(image)
            logger.debug(f"Successfully loaded info panel thumbnail: {self.path}")

        except Exception:
            logger.exception(f"Error loading info panel thumbnail {self.path}")
            self.signals.failed.emit()


class ThumbnailCacheRunnable(QRunnable):
    """Background runnable for caching thumbnails without blocking the UI.

    This runnable performs the potentially slow thumbnail caching operation
    (PIL image decode, resize, and JPEG encode) in a background thread,
    preventing UI freezes of 50-500ms that occurred with synchronous caching.
    """

    # Instance attributes
    thumbnail_path: Path
    show: str
    sequence: str
    shot: str
    cache_manager: ThumbnailCache

    def __init__(
        self,
        thumbnail_path: Path,
        show: str,
        sequence: str,
        shot: str,
        cache_manager: ThumbnailCache,
    ) -> None:
        """Initialize the thumbnail cache runnable.

        Args:
            thumbnail_path: Path to the source thumbnail image
            show: Show name for cache organization
            sequence: Sequence name for cache organization
            shot: Shot name for cache organization
            cache_manager: ThumbnailCache instance for thumbnail caching

        """
        super().__init__()
        self.thumbnail_path = thumbnail_path
        self.show = show
        self.sequence = sequence
        self.shot = shot
        self.cache_manager = cache_manager
        # Auto-delete when done since we don't need callbacks
        self.setAutoDelete(True)

    @override
    def run(self) -> None:
        """Execute thumbnail caching in background thread."""
        logger = logging.getLogger(__name__)
        try:
            _ = self.cache_manager.cache_thumbnail(
                self.thumbnail_path,
                self.show,
                self.sequence,
                self.shot,
            )
        except Exception as e:  # noqa: BLE001
            # Log but don't propagate - caching failure is non-critical
            logger.debug(f"Background thumbnail caching failed: {e}")
