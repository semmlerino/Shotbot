"""Base class for thumbnail widgets to eliminate code duplication."""

import logging
import subprocess
import sys
from abc import abstractmethod
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, TypeVar

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QDesktopServices,
    QFont,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QFrame, QLabel, QMenu, QSizePolicy, QVBoxLayout, QWidget

from cache_manager import CacheManager, ThumbnailCacheLoader
from config import Config
from thumbnail_loading_indicator import ThumbnailLoadingIndicator

# Set up logger for this module
logger = logging.getLogger(__name__)

# Type variable for data objects
T = TypeVar("T", bound="ThumbnailDataProtocol")


class FolderOpenerSignals(QObject):
    """Signals for the folder opener worker."""

    error = Signal(str)
    success = Signal()


class FolderOpenerWorker(QRunnable):
    """Worker to open folders in a non-blocking way."""

    def __init__(self, folder_path: str):
        """Initialize the worker.

        Args:
            folder_path: Path to the folder to open
        """
        super().__init__()
        self.folder_path = folder_path
        self.signals = FolderOpenerSignals()

    @Slot()
    def run(self):
        """Open the folder using the appropriate method for the platform."""
        try:
            # Ensure we have a proper absolute path
            folder_path = self.folder_path
            if not folder_path.startswith("/"):
                folder_path = "/" + folder_path

            # Check if path exists
            if not Path(folder_path).exists():
                self.signals.error.emit(f"Path does not exist: {folder_path}")
                return

            # Try Qt method first (cross-platform)
            url = QUrl()
            url.setScheme("file")
            url.setPath(folder_path)

            logger.debug(f"Opening folder: {folder_path} with URL: {url.toString()}")

            # Use QDesktopServices but with proper error handling
            success = QDesktopServices.openUrl(url)

            if not success:
                # Fallback to system-specific commands
                logger.debug("QDesktopServices failed, trying system command")

                if sys.platform == "darwin":  # macOS
                    subprocess.run(["open", folder_path], check=True)
                elif sys.platform == "win32":  # Windows
                    subprocess.run(["explorer", folder_path], check=True)
                else:  # Linux/Unix
                    # Try xdg-open first, then alternatives
                    try:
                        subprocess.run(["xdg-open", folder_path], check=True)
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        # Try gio as fallback
                        subprocess.run(["gio", "open", folder_path], check=True)

            self.signals.success.emit()

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to open folder: {e}"
            logger.error(error_msg)
            self.signals.error.emit(error_msg)
        except FileNotFoundError as e:
            error_msg = f"File manager not found: {e}"
            logger.error(error_msg)
            self.signals.error.emit(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error opening folder: {e}"
            logger.error(error_msg)
            self.signals.error.emit(error_msg)


class LoadingState(Enum):
    """Thumbnail loading states."""

    IDLE = "idle"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"


class ThumbnailDataProtocol(Protocol):
    """Protocol defining the interface for thumbnail data objects."""

    show: str
    sequence: str
    shot: str
    workspace_path: str

    @property
    def full_name(self) -> str:
        """Get full display name."""
        ...

    def get_thumbnail_path(self) -> Optional[Path]:
        """Get thumbnail path or None."""
        ...


class BaseThumbnailLoader(QRunnable):
    """Base runnable for loading thumbnails in background."""

    class Signals(QObject):
        loaded = Signal(object, QPixmap)  # widget, pixmap
        failed = Signal(object)  # widget

    def __init__(self, widget: "ThumbnailWidgetBase", path: Path):
        super().__init__()
        self.widget = widget
        self.path = path
        self.signals = self.Signals()

    def run(self):
        """Load the thumbnail with memory bounds checking and proper error handling."""
        if not self.path or not self.path.exists():
            logger.warning(f"Thumbnail path does not exist: {self.path}")
            self.signals.failed.emit(self.widget)
            return

        pixmap = None
        try:
            # Load the image
            pixmap = QPixmap(str(self.path))
            if pixmap.isNull():
                logger.debug(f"Failed to load thumbnail image: {self.path}")
                self.signals.failed.emit(self.widget)
                return

            # Use utility for memory bounds checking
            from utils import ImageUtils

            if not ImageUtils.validate_image_dimensions(
                pixmap.width(), pixmap.height()
            ):
                self.signals.failed.emit(self.widget)
                return

            # Success - emit the loaded signal
            self.signals.loaded.emit(self.widget, pixmap)
            logger.debug(f"Successfully loaded thumbnail: {self.path}")

        except FileNotFoundError:
            logger.debug(f"Thumbnail file not found: {self.path}")
            self.signals.failed.emit(self.widget)
        except PermissionError:
            logger.warning(f"Permission denied loading thumbnail: {self.path}")
            self.signals.failed.emit(self.widget)
        except MemoryError:
            logger.error(f"Out of memory loading thumbnail: {self.path}")
            self.signals.failed.emit(self.widget)
        except (OSError, IOError) as e:
            logger.warning(f"I/O error loading thumbnail {self.path}: {e}")
            self.signals.failed.emit(self.widget)
        except Exception as e:
            logger.exception(f"Unexpected error loading thumbnail {self.path}: {e}")
            self.signals.failed.emit(self.widget)
        finally:
            # Clean up Qt objects
            del pixmap


class ThumbnailWidgetBase(QFrame):
    """Base class for thumbnail widgets with common functionality."""

    # Signals - derived classes can override signal types if needed
    clicked = Signal(object)  # Data object
    double_clicked = Signal(object)  # Data object

    # Shared cache manager
    _cache_manager = CacheManager()

    @classmethod
    def set_cache_manager(cls, cache_manager: CacheManager):
        """Set the shared cache manager for all thumbnail widgets."""
        cls._cache_manager = cache_manager

    def __init__(self, data: T, size: int = Config.DEFAULT_THUMBNAIL_SIZE):
        super().__init__()
        self.data = data
        self._thumbnail_size = size
        self._selected = False
        self._pixmap: Optional[QPixmap] = None
        self._loading_state = LoadingState.IDLE

        # Set up UI - template method pattern
        self._setup_base_ui()
        self._setup_custom_ui()
        self._load_thumbnail()

        # Set size policy to ensure consistent heights
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._calculate_widget_height())

    def _setup_base_ui(self):
        """Set up the common UI elements."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # Thumbnail label
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setObjectName("thumbnail")
        self.thumbnail_label.setFixedSize(self._thumbnail_size, self._thumbnail_size)
        self.thumbnail_label.setScaledContents(True)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Set placeholder
        self._set_placeholder()

        # Create a container for thumbnail and loading indicator
        self.thumbnail_container = QWidget()
        self.thumbnail_container.setFixedSize(
            self._thumbnail_size, self._thumbnail_size
        )
        container_layout = QVBoxLayout(self.thumbnail_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.thumbnail_label)

        # Loading indicator (overlay)
        self.loading_indicator = ThumbnailLoadingIndicator(self.thumbnail_container)
        self.loading_indicator.move(
            (self._thumbnail_size - 40) // 2,  # Center horizontally
            (self._thumbnail_size - 40) // 2,  # Center vertically
        )
        self.loading_indicator.hide()

        layout.addWidget(self.thumbnail_container)

        # Create a content container for labels that will maintain consistent height
        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(3)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Add content container with stretch
        layout.addWidget(self.content_container)
        layout.addStretch()  # Push content to top

        # Set cursor
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @abstractmethod
    def _setup_custom_ui(self):
        """Set up custom UI elements specific to the derived class."""
        pass

    @abstractmethod
    def _get_selected_style(self) -> str:
        """Get the CSS style for selected state."""
        pass

    @abstractmethod
    def _get_unselected_style(self) -> str:
        """Get the CSS style for unselected state."""
        pass

    @abstractmethod
    def _create_context_menu(self) -> QMenu:
        """Create and return the context menu for this widget."""
        pass

    def _set_placeholder(self):
        """Set placeholder image."""
        placeholder = QPixmap(self._thumbnail_size, self._thumbnail_size)
        placeholder.fill(QColor(Config.PLACEHOLDER_COLOR))

        # Draw text on placeholder
        painter = QPainter(placeholder)
        painter.setPen(QColor("#888"))
        painter.setFont(QFont("Arial", 12))
        painter.drawText(placeholder.rect(), Qt.AlignmentFlag.AlignCenter, "No Image")
        painter.end()

        self.thumbnail_label.setPixmap(placeholder)

    def _load_thumbnail(self):
        """Load thumbnail from cache or source."""
        # Set loading state and show indicator
        self._loading_state = LoadingState.LOADING
        self.loading_indicator.start()

        # First check cache
        cache_path = self._cache_manager.get_cached_thumbnail(
            self.data.show, self.data.sequence, self.data.shot
        )

        if cache_path and cache_path.exists():
            # Load from cache
            loader = BaseThumbnailLoader(self, cache_path)
            loader.signals.loaded.connect(self._on_thumbnail_loaded)
            loader.signals.failed.connect(self._on_thumbnail_failed)
            QThreadPool.globalInstance().start(loader)
        else:
            # Try to load from source
            thumb_path = self.data.get_thumbnail_path()
            if thumb_path and thumb_path.exists():
                # Load in background thread
                loader = BaseThumbnailLoader(self, thumb_path)
                loader.signals.loaded.connect(self._on_thumbnail_loaded)
                loader.signals.failed.connect(self._on_thumbnail_failed)
                QThreadPool.globalInstance().start(loader)

                # Also cache it for next time
                cache_loader = ThumbnailCacheLoader(
                    self._cache_manager,
                    thumb_path,
                    self.data.show,
                    self.data.sequence,
                    self.data.shot,
                )
                QThreadPool.globalInstance().start(cache_loader)
            else:
                # No thumbnail available
                self._on_thumbnail_failed(self)

    def _on_thumbnail_loaded(self, widget: "ThumbnailWidgetBase", pixmap: QPixmap):
        """Handle loaded thumbnail."""
        if widget == self:
            self._loading_state = LoadingState.LOADED
            self.loading_indicator.stop()
            self._pixmap = pixmap
            self._update_thumbnail()

    def _on_thumbnail_failed(self, widget: "ThumbnailWidgetBase"):
        """Handle failed thumbnail loading."""
        if widget == self:
            self._loading_state = LoadingState.FAILED
            self.loading_indicator.stop()
            # Keep the placeholder image

    def _update_thumbnail(self):
        """Update thumbnail display."""
        if self._pixmap:
            scaled = self._pixmap.scaled(
                QSize(self._thumbnail_size, self._thumbnail_size),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumbnail_label.setPixmap(scaled)

    def _calculate_widget_height(self) -> int:
        """Calculate consistent widget height based on thumbnail size and label content."""
        # Base height: thumbnail + margins (8+8) + spacing (5)
        base_height = self._thumbnail_size + 16 + 5

        # Content area height: approximately 3 lines of text with spacing
        # This ensures both widget types have similar total heights
        content_height = 60  # Approximately 3 lines at normal font sizes

        return base_height + content_height

    def set_size(self, size: int):
        """Set thumbnail size."""
        self._thumbnail_size = size
        self.thumbnail_label.setFixedSize(size, size)
        self.thumbnail_container.setFixedSize(size, size)

        # Reposition loading indicator
        self.loading_indicator.move(
            (size - 40) // 2,  # Center horizontally
            (size - 40) // 2,  # Center vertically
        )

        if self._pixmap:
            self._update_thumbnail()
        else:
            self._set_placeholder()

        # Update fixed height
        self.setFixedHeight(self._calculate_widget_height())

    def set_selected(self, selected: bool):
        """Set selection state."""
        self._selected = selected
        self._update_style()

    def _update_style(self):
        """Update widget style based on state."""
        if self._selected:
            self.setStyleSheet(self._get_selected_style())
        else:
            self.setStyleSheet(self._get_unselected_style())

        # Update the widget display
        self.update()

    # Base context menu actions
    def _open_shot_folder(self):
        """Open the shot's workspace folder in system file manager (non-blocking)."""
        folder_path = self.data.workspace_path

        # Create worker to open folder in background
        worker = FolderOpenerWorker(folder_path)

        # Connect signals for error handling
        worker.signals.error.connect(self._on_folder_open_error)
        worker.signals.success.connect(self._on_folder_open_success)

        # Start the worker
        QThreadPool.globalInstance().start(worker)

    @Slot(str)
    def _on_folder_open_error(self, error_msg: str):
        """Handle folder opening errors.

        Args:
            error_msg: Error message to display
        """
        logger.error(f"Failed to open folder: {error_msg}")
        # Could emit a signal here to show error in UI if needed

    @Slot()
    def _on_folder_open_success(self):
        """Handle successful folder opening."""
        logger.debug("Folder opened successfully")

    # Mouse events
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.data)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double click - can be overridden by derived classes."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.data)

    def contextMenuEvent(self, event: QContextMenuEvent):
        """Handle right-click context menu."""
        menu = self._create_context_menu()
        menu.exec(event.globalPos())
