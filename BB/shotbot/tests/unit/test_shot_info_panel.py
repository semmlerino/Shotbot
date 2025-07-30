"""Unit tests for shot_info_panel.py"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from shot_info_panel import ShotInfoPanel
from shot_model import Shot


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestShotInfoPanel:
    """Test ShotInfoPanel class."""

    @pytest.fixture
    def shot_info_panel(self, qapp):
        """Create ShotInfoPanel instance."""
        return ShotInfoPanel()

    @pytest.fixture
    def sample_shot(self):
        """Create sample shot."""
        return Shot(
            show="testshow",
            sequence="101_ABC",
            shot="0010",
            workspace_path="/shows/testshow/shots/101_ABC/101_ABC_0010",
        )

    def test_init(self, shot_info_panel):
        """Test ShotInfoPanel initialization."""
        assert shot_info_panel._current_shot is None
        assert hasattr(shot_info_panel, "_cache_manager")
        assert hasattr(shot_info_panel, "thumbnail_label")
        assert hasattr(shot_info_panel, "shot_name_label")
        assert hasattr(shot_info_panel, "show_sequence_label")
        assert hasattr(shot_info_panel, "path_label")

    def test_initial_display(self, shot_info_panel):
        """Test initial display state."""
        assert shot_info_panel.shot_name_label.text() == "No Shot Selected"
        assert shot_info_panel.show_sequence_label.text() == ""
        assert shot_info_panel.path_label.text() == ""

    def test_set_shot(self, shot_info_panel, sample_shot):
        """Test setting a shot."""
        shot_info_panel.set_shot(sample_shot)

        assert shot_info_panel._current_shot == sample_shot
        assert shot_info_panel.shot_name_label.text() == "101_ABC_0010"
        assert shot_info_panel.show_sequence_label.text() == "testshow • 101_ABC"
        assert (
            shot_info_panel.path_label.text()
            == "Workspace: /shows/testshow/shots/101_ABC/101_ABC_0010"
        )

    def test_set_shot_none(self, shot_info_panel, sample_shot):
        """Test clearing shot selection."""
        # First set a shot
        shot_info_panel.set_shot(sample_shot)

        # Then clear it
        shot_info_panel.set_shot(None)

        assert shot_info_panel._current_shot is None
        assert shot_info_panel.shot_name_label.text() == "No Shot Selected"
        assert shot_info_panel.show_sequence_label.text() == ""
        assert shot_info_panel.path_label.text() == ""

    def test_load_thumbnail_from_cache(
        self, shot_info_panel, sample_shot, monkeypatch, tmp_path
    ):
        """Test loading thumbnail from cache."""
        # Create a cached thumbnail file
        cache_path = tmp_path / "cached_thumb.jpg"
        from PySide6.QtGui import QImage

        img = QImage(1, 1, QImage.Format.Format_RGB32)
        img.fill(Qt.GlobalColor.blue)
        img.save(str(cache_path))

        # Replace cache manager method with mock
        mock_get_cached = Mock(return_value=cache_path)
        monkeypatch.setattr(
            shot_info_panel._cache_manager, "get_cached_thumbnail", mock_get_cached
        )

        # Load thumbnail
        shot_info_panel.set_shot(sample_shot)

        # Verify cache was checked
        mock_get_cached.assert_called_once_with("testshow", "101_ABC", "0010")

        # Verify thumbnail was loaded (not placeholder)
        pixmap = shot_info_panel.thumbnail_label.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()
        assert shot_info_panel.thumbnail_label.text() != "No Image"

    @patch("shot_info_panel.ThumbnailCacheLoader")
    @patch("shot_info_panel.QThreadPool")
    def test_load_thumbnail_from_source(
        self,
        mock_threadpool_class,
        mock_loader_class,
        shot_info_panel,
        sample_shot,
        monkeypatch,
        tmp_path,
    ):
        """Test loading thumbnail from source when not cached."""
        # Replace cache manager method with mock
        mock_get_cached = Mock(return_value=None)
        monkeypatch.setattr(
            shot_info_panel._cache_manager, "get_cached_thumbnail", mock_get_cached
        )

        # Create a source thumbnail file
        thumb_path = tmp_path / "source_thumb.jpg"
        from PySide6.QtGui import QImage

        img = QImage(1, 1, QImage.Format.Format_RGB32)
        img.fill(Qt.GlobalColor.green)
        img.save(str(thumb_path))

        sample_shot.get_thumbnail_path = Mock(return_value=thumb_path)

        # Mock thread pool
        mock_threadpool = Mock()
        mock_threadpool_class.globalInstance.return_value = mock_threadpool

        # Mock cache loader
        mock_loader = Mock()
        mock_loader_class.return_value = mock_loader

        # Load thumbnail
        shot_info_panel.set_shot(sample_shot)

        # Verify thumbnail was loaded from source
        pixmap = shot_info_panel.thumbnail_label.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()

        # Verify cache loader was created
        mock_loader_class.assert_called_once_with(
            shot_info_panel._cache_manager, thumb_path, "testshow", "101_ABC", "0010"
        )

        # Verify loader was started
        mock_threadpool.start.assert_called_once_with(mock_loader)

    def test_load_thumbnail_no_source(self, shot_info_panel, sample_shot, monkeypatch):
        """Test loading thumbnail when no source exists."""
        # Replace cache manager method with mock
        mock_get_cached = Mock(return_value=None)
        monkeypatch.setattr(
            shot_info_panel._cache_manager, "get_cached_thumbnail", mock_get_cached
        )
        sample_shot.get_thumbnail_path = Mock(return_value=None)

        # Load thumbnail
        shot_info_panel.set_shot(sample_shot)

        # Should show placeholder
        assert shot_info_panel.thumbnail_label.text() == "No Image"

    def test_load_pixmap_from_path(self, shot_info_panel, tmp_path):
        """Test _load_pixmap_from_path method."""
        # Create a real test image file
        image_path = tmp_path / "test.jpg"
        # Create a simple 1x1 pixel image
        from PySide6.QtGui import QImage

        img = QImage(1, 1, QImage.Format.Format_RGB32)
        img.fill(Qt.GlobalColor.red)
        img.save(str(image_path))

        # Load the pixmap
        shot_info_panel._load_pixmap_from_path(image_path)

        # Check that a pixmap was set (not checking the exact pixmap)
        pixmap = shot_info_panel.thumbnail_label.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()

    def test_load_pixmap_from_path_invalid(self, shot_info_panel, tmp_path):
        """Test _load_pixmap_from_path with invalid image."""
        # Create an invalid image file
        invalid_path = tmp_path / "invalid.jpg"
        invalid_path.write_text("not an image")

        shot_info_panel._load_pixmap_from_path(invalid_path)

        # Should set placeholder
        assert shot_info_panel.thumbnail_label.text() == "No Image"

    def test_on_thumbnail_cached(self, shot_info_panel, sample_shot):
        """Test _on_thumbnail_cached method."""
        # Set current shot
        shot_info_panel.set_shot(sample_shot)

        # Mock _load_pixmap_from_path
        shot_info_panel._load_pixmap_from_path = Mock()

        cache_path = Path("/cache/thumb.jpg")

        # Call with matching shot
        shot_info_panel._on_thumbnail_cached("testshow", "101_ABC", "0010", cache_path)

        shot_info_panel._load_pixmap_from_path.assert_called_once_with(cache_path)

    def test_on_thumbnail_cached_different_shot(self, shot_info_panel, sample_shot):
        """Test _on_thumbnail_cached with different shot."""
        # Set current shot
        shot_info_panel.set_shot(sample_shot)

        # Mock _load_pixmap_from_path
        shot_info_panel._load_pixmap_from_path = Mock()

        cache_path = Path("/cache/thumb.jpg")

        # Call with different shot
        shot_info_panel._on_thumbnail_cached("othershow", "999_XYZ", "0999", cache_path)

        # Should not update
        shot_info_panel._load_pixmap_from_path.assert_not_called()

    def test_minimum_height(self, shot_info_panel):
        """Test minimum height is set."""
        assert shot_info_panel.minimumHeight() == 150

    def test_style_sheet(self, shot_info_panel):
        """Test style sheet is applied."""
        style = shot_info_panel.styleSheet()
        assert "background-color: #1a1a1a" in style
        assert "border: 1px solid #333" in style
        assert "border-radius: 6px" in style
