"""Thumbnail widget for displaying shot thumbnails."""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from cache_manager import CacheManager, ThumbnailCacheLoader
from config import Config
from shot_model import Shot


class ThumbnailLoader(QRunnable):
    """Runnable for loading thumbnails in background."""

    class Signals(QObject):
        loaded = Signal(object, QPixmap)  # widget, pixmap

    def __init__(self, widget: "ThumbnailWidget", path: Path):
        super().__init__()
        self.widget = widget
        self.path = path
        self.signals = self.Signals()

    def run(self):
        """Load the thumbnail."""
        pixmap = QPixmap(str(self.path))
        if not pixmap.isNull():
            self.signals.loaded.emit(self.widget, pixmap)


class ThumbnailWidget(QFrame):
    """Widget displaying a shot thumbnail and name."""

    # Signals
    clicked = Signal(object)  # Shot
    double_clicked = Signal(object)  # Shot

    # Shared cache manager
    _cache_manager = CacheManager()

    def __init__(self, shot: Shot, size: int = Config.DEFAULT_THUMBNAIL_SIZE):
        super().__init__()
        self.shot = shot
        self._thumbnail_size = size
        self._selected = False
        self._pixmap: Optional[QPixmap] = None
        self._setup_ui()
        self._load_thumbnail()

    def _setup_ui(self):
        """Set up the UI."""
        # Configure frame - removed since we're using CSS styling
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # Thumbnail label
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setObjectName("thumbnail")  # For CSS targeting
        self.thumbnail_label.setFixedSize(self._thumbnail_size, self._thumbnail_size)
        self.thumbnail_label.setScaledContents(True)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Set placeholder
        self._set_placeholder()

        layout.addWidget(self.thumbnail_label)

        # Shot name label
        self.name_label = QLabel(self.shot.full_name)
        self.name_label.setObjectName("name")  # For CSS targeting
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        font = self.name_label.font()
        font.setPointSize(9)
        self.name_label.setFont(font)

        layout.addWidget(self.name_label)

        # Set cursor
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Apply initial style
        self._update_style()

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
        # First check cache
        cache_path = self._cache_manager.get_cached_thumbnail(
            self.shot.show, self.shot.sequence, self.shot.shot
        )

        if cache_path and cache_path.exists():
            # Load from cache
            loader = ThumbnailLoader(self, cache_path)
            loader.signals.loaded.connect(self._on_thumbnail_loaded)
            QThreadPool.globalInstance().start(loader)
        else:
            # Try to load from source
            thumb_path = self.shot.get_thumbnail_path()
            if thumb_path and thumb_path.exists():
                # Load in background thread
                loader = ThumbnailLoader(self, thumb_path)
                loader.signals.loaded.connect(self._on_thumbnail_loaded)
                QThreadPool.globalInstance().start(loader)

                # Also cache it for next time
                cache_loader = ThumbnailCacheLoader(
                    self._cache_manager,
                    thumb_path,
                    self.shot.show,
                    self.shot.sequence,
                    self.shot.shot,
                )
                QThreadPool.globalInstance().start(cache_loader)

    def _on_thumbnail_loaded(self, widget: "ThumbnailWidget", pixmap: QPixmap):
        """Handle loaded thumbnail."""
        if widget == self:
            self._pixmap = pixmap
            self._update_thumbnail()

    def _update_thumbnail(self):
        """Update thumbnail display."""
        if self._pixmap:
            scaled = self._pixmap.scaled(
                QSize(self._thumbnail_size, self._thumbnail_size),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumbnail_label.setPixmap(scaled)

    def set_size(self, size: int):
        """Set thumbnail size."""
        self._thumbnail_size = size
        self.thumbnail_label.setFixedSize(size, size)
        if self._pixmap:
            self._update_thumbnail()
        else:
            self._set_placeholder()

    def set_selected(self, selected: bool):
        """Set selection state."""
        self._selected = selected
        self._update_style()

    def _update_style(self):
        """Update widget style based on state."""
        if self._selected:
            # Use QFrame styling with bright cyan border
            self.setStyleSheet("""
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
                QLabel {
                    background-color: transparent;
                }
            """)
        else:
            self.setStyleSheet("""
                ThumbnailWidget {
                    background-color: #2b2b2b;
                    border: 2px solid #444;
                    border-radius: 6px;
                }
                ThumbnailWidget:hover {
                    background-color: #3a3a3a;
                    border: 2px solid #888;
                }
                QLabel {
                    border: none;
                    background-color: transparent;
                }
            """)
        
        # Update the widget display
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.shot)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.shot)
