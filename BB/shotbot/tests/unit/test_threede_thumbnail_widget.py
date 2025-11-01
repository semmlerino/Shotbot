"""Unit tests for 3DE thumbnail widget."""

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt

from threede_scene_model import ThreeDEScene
from threede_thumbnail_widget import ThreeDEThumbnailWidget


class TestThreeDEThumbnailWidget:
    """Test ThreeDEThumbnailWidget class."""

    @pytest.fixture
    def scene(self):
        """Create a test 3DE scene."""
        return ThreeDEScene(
            show="test_show",
            sequence="AB_123",
            shot="0010",
            workspace_path="/shows/test_show/shots/AB_123/AB_123_0010",
            user="john-d",
            plate="FG01",
            scene_path=Path("/path/to/scene.3de"),
        )

    def test_initialization(self, qtbot, scene):
        """Test widget initialization."""
        widget = ThreeDEThumbnailWidget(scene)
        qtbot.addWidget(widget)

        assert widget.scene == scene
        assert widget._thumbnail_size == 200  # Default from Config
        assert not widget._selected

    def test_labels_created(self, qtbot, scene):
        """Test that all labels are created."""
        widget = ThreeDEThumbnailWidget(scene)
        qtbot.addWidget(widget)

        # Check labels exist
        assert hasattr(widget, "thumbnail_label")
        assert hasattr(widget, "shot_label")
        assert hasattr(widget, "user_label")
        assert hasattr(widget, "plate_label")

        # Check label content
        assert widget.shot_label.text() == "AB_123_0010"
        assert widget.user_label.text() == "john-d"
        assert widget.plate_label.text() == "FG01"

    def test_label_styling(self, qtbot, scene):
        """Test label styling."""
        widget = ThreeDEThumbnailWidget(scene)
        qtbot.addWidget(widget)

        # Check object names for CSS targeting
        assert widget.shot_label.objectName() == "shot"
        assert widget.user_label.objectName() == "user"
        assert widget.plate_label.objectName() == "plate"
        assert widget.thumbnail_label.objectName() == "thumbnail"

    def test_set_size(self, qtbot, scene):
        """Test setting thumbnail size."""
        widget = ThreeDEThumbnailWidget(scene)
        qtbot.addWidget(widget)

        widget.set_size(200)

        assert widget._thumbnail_size == 200
        assert widget.thumbnail_label.width() == 200
        assert widget.thumbnail_label.height() == 200

    def test_set_selected(self, qtbot, scene):
        """Test setting selection state."""
        widget = ThreeDEThumbnailWidget(scene)
        qtbot.addWidget(widget)

        # Initially not selected
        assert not widget._selected

        # Set selected
        widget.set_selected(True)
        assert widget._selected

        # Unselect
        widget.set_selected(False)
        assert not widget._selected

    def test_mouse_click_signal(self, qtbot, scene):
        """Test mouse click emits signal."""
        widget = ThreeDEThumbnailWidget(scene)
        qtbot.addWidget(widget)

        # Track signal
        signal_received = []
        widget.clicked.connect(lambda s: signal_received.append(s))

        # Simulate mouse click
        qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)

        # Check signal emitted
        assert len(signal_received) == 1
        assert signal_received[0] == scene

    def test_mouse_double_click_signal(self, qtbot, scene):
        """Test mouse double click emits signal."""
        widget = ThreeDEThumbnailWidget(scene)
        qtbot.addWidget(widget)

        # Track signal
        signal_received = []
        widget.double_clicked.connect(lambda s: signal_received.append(s))

        # Simulate mouse double click
        qtbot.mouseDClick(widget, Qt.MouseButton.LeftButton)

        # Check signal emitted
        assert len(signal_received) == 1
        assert signal_received[0] == scene

    def test_load_thumbnail_from_cache(self, qtbot, scene):
        """Test loading thumbnail from cache."""
        with patch.object(ThreeDEThumbnailWidget, "_cache_manager") as mock_cache:
            mock_cache_path = Path("/cache/thumb.jpg")
            mock_cache.get_cached_thumbnail.return_value = mock_cache_path

            widget = ThreeDEThumbnailWidget(scene)
            qtbot.addWidget(widget)

            # Should have tried to load from cache
            mock_cache.get_cached_thumbnail.assert_called_with(
                scene.show, scene.sequence, scene.shot
            )
