"""Unit tests for thumbnail_widget.py"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent, QPixmap

from shot_model import Shot
from thumbnail_widget import ThumbnailLoader, ThumbnailWidget


class TestThumbnailWidget:
    """Test ThumbnailWidget functionality."""

    @pytest.fixture
    def sample_shot(self):
        """Create a sample shot."""
        return Shot(
            show="testshow",
            sequence="101_ABC",
            shot="0010",
            workspace_path="/shows/testshow/shots/101_ABC/101_ABC_0010",
        )

    @pytest.fixture
    def thumbnail_widget(self, qapp, sample_shot):
        """Create a ThumbnailWidget instance."""
        return ThumbnailWidget(sample_shot)

    def test_initialization(self, qapp, sample_shot):
        """Test ThumbnailWidget initialization."""
        widget = ThumbnailWidget(sample_shot, size=200)

        assert widget.shot == sample_shot
        assert widget._thumbnail_size == 200
        assert widget._selected is False
        assert widget._pixmap is None

        # Check UI elements
        assert widget.thumbnail_label is not None
        assert widget.name_label is not None
        assert widget.name_label.text() == sample_shot.full_name

    def test_set_size(self, thumbnail_widget):
        """Test setting thumbnail size."""
        new_size = 250

        thumbnail_widget.set_size(new_size)

        assert thumbnail_widget._thumbnail_size == new_size
        assert thumbnail_widget.thumbnail_label.size().width() == new_size
        assert thumbnail_widget.thumbnail_label.size().height() == new_size

    def test_set_selected(self, thumbnail_widget):
        """Test setting selection state."""
        # Select
        thumbnail_widget.set_selected(True)
        assert thumbnail_widget._selected is True
        assert "#14ffec" in thumbnail_widget.styleSheet()  # Selected border color

        # Deselect
        thumbnail_widget.set_selected(False)
        assert thumbnail_widget._selected is False
        assert "#14ffec" not in thumbnail_widget.styleSheet()

    def test_mouse_press_event(self, thumbnail_widget):
        """Test mouse press emits clicked signal."""
        signal_received = []
        thumbnail_widget.clicked.connect(lambda s: signal_received.append(s))

        # Create mouse event
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPoint(50, 50),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        thumbnail_widget.mousePressEvent(event)

        assert len(signal_received) == 1
        assert signal_received[0] == thumbnail_widget.shot

    def test_mouse_double_click_event(self, thumbnail_widget):
        """Test mouse double-click emits double_clicked signal."""
        signal_received = []
        thumbnail_widget.double_clicked.connect(lambda s: signal_received.append(s))

        # Create mouse event
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            QPoint(50, 50),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        thumbnail_widget.mouseDoubleClickEvent(event)

        assert len(signal_received) == 1
        assert signal_received[0] == thumbnail_widget.shot

    def test_load_thumbnail_with_cache(self, thumbnail_widget, tmp_path, monkeypatch):
        """Test loading thumbnail from cache."""
        # Create cached thumbnail
        cache_path = tmp_path / "cached_thumb.jpg"
        img = QPixmap(100, 100)
        img.fill(Qt.GlobalColor.blue)
        img.save(str(cache_path))

        # Mock cache manager
        mock_get_cached = Mock(return_value=cache_path)
        monkeypatch.setattr(
            thumbnail_widget._cache_manager, "get_cached_thumbnail", mock_get_cached
        )

        # Load thumbnail
        thumbnail_widget._load_thumbnail()

        # Check cache was used
        mock_get_cached.assert_called_once_with("testshow", "101_ABC", "0010")

        # The actual loading happens asynchronously in thread pool
        # So we can't check _pixmap directly here

    @patch("thumbnail_widget.QThreadPool")
    def test_load_thumbnail_from_source(
        self, mock_threadpool_class, thumbnail_widget, tmp_path, monkeypatch
    ):
        """Test loading thumbnail from source path."""
        # No cache
        mock_get_cached = Mock(return_value=None)
        monkeypatch.setattr(
            thumbnail_widget._cache_manager, "get_cached_thumbnail", mock_get_cached
        )

        # Create source thumbnail
        source_path = tmp_path / "source_thumb.jpg"
        img = QPixmap(100, 100)
        img.fill(Qt.GlobalColor.red)
        img.save(str(source_path))

        thumbnail_widget.shot.get_thumbnail_path = Mock(return_value=source_path)

        # Mock thread pool
        mock_threadpool = Mock()
        mock_threadpool_class.globalInstance.return_value = mock_threadpool

        # Load thumbnail
        thumbnail_widget._load_thumbnail()

        # Check thread pool was used
        assert mock_threadpool.start.called
        # First call should be ThumbnailLoader
        loader = mock_threadpool.start.call_args_list[0][0][0]
        assert isinstance(loader, ThumbnailLoader)
        assert loader.path == source_path

    def test_load_thumbnail_no_source(self, thumbnail_widget, monkeypatch):
        """Test loading thumbnail when no source exists."""
        # No cache
        mock_get_cached = Mock(return_value=None)
        monkeypatch.setattr(
            thumbnail_widget._cache_manager, "get_cached_thumbnail", mock_get_cached
        )

        # No source
        thumbnail_widget.shot.get_thumbnail_path = Mock(return_value=None)

        # Load thumbnail
        thumbnail_widget._load_thumbnail()

        # Should still have placeholder
        assert thumbnail_widget.thumbnail_label.pixmap() is not None

    def test_set_placeholder(self, thumbnail_widget):
        """Test placeholder creation."""
        thumbnail_widget._set_placeholder()

        # Check placeholder is set
        pixmap = thumbnail_widget.thumbnail_label.pixmap()
        assert pixmap is not None
        assert pixmap.width() == thumbnail_widget._thumbnail_size
        assert pixmap.height() == thumbnail_widget._thumbnail_size

    def test_on_thumbnail_loaded(self, thumbnail_widget):
        """Test handling loaded thumbnail."""
        # Create a test pixmap
        pixmap = QPixmap(200, 200)
        pixmap.fill(Qt.GlobalColor.green)

        # Store it
        thumbnail_widget._pixmap = pixmap

        # Update display
        thumbnail_widget._update_thumbnail()

        # Check it was scaled and set
        label_pixmap = thumbnail_widget.thumbnail_label.pixmap()
        assert label_pixmap is not None
        assert label_pixmap.width() <= thumbnail_widget._thumbnail_size
        assert label_pixmap.height() <= thumbnail_widget._thumbnail_size

    def test_style_updates(self, thumbnail_widget):
        """Test style updates on selection."""
        # Initialize style
        thumbnail_widget._update_style()
        initial_style = thumbnail_widget.styleSheet()

        # Select
        thumbnail_widget.set_selected(True)
        selected_style = thumbnail_widget.styleSheet()
        assert selected_style != initial_style
        assert "border: 3px solid #14ffec" in selected_style

        # Deselect
        thumbnail_widget.set_selected(False)
        deselected_style = thumbnail_widget.styleSheet()
        assert "#2b2b2b" in deselected_style  # Deselected background
        assert "#14ffec" not in deselected_style  # No selected border


class TestThumbnailLoader:
    """Test ThumbnailLoader functionality."""

    @pytest.fixture
    def mock_widget(self):
        """Create a mock widget."""
        widget = Mock()
        widget.shot = Mock()
        return widget

    def test_loader_initialization(self, mock_widget):
        """Test ThumbnailLoader initialization."""
        path = Path("/test/image.jpg")

        loader = ThumbnailLoader(mock_widget, path)

        assert loader.widget == mock_widget
        assert loader.path == path
        assert loader.signals is not None

    def test_loader_run_success(self, mock_widget, tmp_path):
        """Test successful thumbnail loading."""
        # Create test image
        image_path = tmp_path / "test.jpg"
        pixmap = QPixmap(50, 50)
        pixmap.fill(Qt.GlobalColor.yellow)
        pixmap.save(str(image_path))

        # Create loader
        loader = ThumbnailLoader(mock_widget, image_path)

        # Track signal
        emitted = []
        loader.signals.loaded.connect(lambda w, p: emitted.append((w, p)))

        # Run loader
        loader.run()

        # Check signal was emitted
        assert len(emitted) == 1
        widget, pixmap = emitted[0]
        assert widget == mock_widget
        assert isinstance(pixmap, QPixmap)
        assert not pixmap.isNull()

    def test_loader_run_invalid_image(self, mock_widget, tmp_path):
        """Test loading invalid image."""
        # Create invalid file
        invalid_path = tmp_path / "invalid.jpg"
        invalid_path.write_text("not an image")

        # Create loader
        loader = ThumbnailLoader(mock_widget, invalid_path)

        # Track signal
        emitted = []
        loader.signals.loaded.connect(lambda w, p: emitted.append((w, p)))

        # Run loader
        loader.run()

        # Signal should not be emitted for invalid image
        assert len(emitted) == 0
