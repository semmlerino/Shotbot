"""Unit tests for memory-optimized grid functionality."""

from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QScrollArea, QWidget

from memory_optimized_grid import MemoryOptimizedGrid, ThumbnailPlaceholder
from shot_model import Shot
from threede_scene_model import ThreeDEScene


class _TestableMemoryOptimizedGrid(MemoryOptimizedGrid):
    """Testable implementation of MemoryOptimizedGrid (not a test class)."""

    def __init__(self):
        super().__init__()
        self._thumbnail_size = 150
        self._remove_from_grid_calls = []
        self._update_visible_calls = []
        self._load_at_index_calls = []

    def _update_visible_thumbnails(self):
        """Track calls for testing."""
        self._update_visible_calls.append(True)

    def _load_thumbnail_at_index(self, index: int):
        """Track calls for testing."""
        self._load_at_index_calls.append(index)

    def _remove_from_grid(self, widget: QWidget):
        """Track calls for testing."""
        self._remove_from_grid_calls.append(widget)

    def _get_current_visible_indices(self) -> set:
        """Return test visible indices."""
        return self._visible_indices


class TestMemoryOptimizedGrid:
    """Test MemoryOptimizedGrid functionality."""

    @pytest.fixture
    def grid(self):
        """Create testable grid instance."""
        return _TestableMemoryOptimizedGrid()

    @pytest.fixture
    def sample_shot(self):
        """Create sample shot."""
        return Shot(
            show="testshow",
            sequence="seq01",
            shot="shot001",
            workspace_path="/test/path",
        )

    @pytest.fixture
    def sample_scene(self):
        """Create sample 3DE scene."""
        from pathlib import Path

        return ThreeDEScene(
            show="testshow",
            sequence="seq01",
            shot="shot001",
            workspace_path="/test/path",
            user="user1",
            plate="plate01",
            scene_path=Path("/test/scene.3de"),
        )

    def test_initialization(self, grid):
        """Test grid initialization."""
        assert grid._loaded_thumbnails == {}
        assert grid._placeholders == {}
        assert grid._visible_indices == set()
        assert grid.MAX_LOADED_THUMBNAILS == 50
        assert grid.VIEWPORT_BUFFER == 2
        assert grid.UNLOAD_DELAY_MS == 5000

    def test_get_item_key_shot(self, grid, sample_shot):
        """Test getting key for shot."""
        key = grid._get_item_key(sample_shot)
        assert key == "seq01_shot001"

    def test_get_item_key_scene(self, grid, sample_scene):
        """Test getting key for 3DE scene."""
        key = grid._get_item_key(sample_scene)
        # Display name no longer includes plate after deduplication
        assert key == "seq01_shot001 - user1"

    def test_create_thumbnail_shot(self, qtbot, grid, sample_shot):
        """Test creating thumbnail for shot."""
        thumbnail = grid._create_thumbnail(sample_shot, 200)
        qtbot.addWidget(thumbnail)
        assert thumbnail.__class__.__name__ == "ThumbnailWidget"
        assert thumbnail.shot == sample_shot

    def test_create_thumbnail_scene(self, qtbot, grid, sample_scene):
        """Test creating thumbnail for 3DE scene."""
        thumbnail = grid._create_thumbnail(sample_scene, 200)
        qtbot.addWidget(thumbnail)
        assert thumbnail.__class__.__name__ == "ThreeDEThumbnailWidget"
        assert thumbnail.scene == sample_scene

    def test_setup_viewport_tracking(self, qtbot, grid):
        """Test viewport tracking setup."""
        scroll_area = QScrollArea()
        qtbot.addWidget(scroll_area)

        # Setup tracking
        grid._setup_viewport_tracking(scroll_area)

        # Create a widget to scroll
        content = QWidget()
        content.setMinimumSize(400, 1000)
        scroll_area.setWidget(content)

        # Process events to ensure setup is complete
        qtbot.wait(10)

        # Trigger scrollbar change
        scroll_area.verticalScrollBar().setValue(100)

        # Process events
        qtbot.wait(10)

        # Check that update was called
        assert len(grid._update_visible_calls) > 0

    def test_get_visible_range_empty(self, qtbot, grid):
        """Test visible range calculation with no items."""
        scroll_area = QScrollArea()
        qtbot.addWidget(scroll_area)

        start, end = grid._get_visible_range(scroll_area, 4, 0)
        assert start == 0
        assert end == 0

    def test_get_visible_range_with_items(self, qtbot, grid):
        """Test visible range calculation with items."""
        scroll_area = QScrollArea()
        scroll_area.resize(600, 400)
        container = QWidget()
        container.resize(600, 1000)
        scroll_area.setWidget(container)
        qtbot.addWidget(scroll_area)

        # Calculate visible range
        # With 150px thumbnails + 20px spacing = 170px per item
        # 600px width / 170px = ~3 columns
        # 400px height / 170px = ~2.3 rows visible
        # With buffer of 2 rows, should load ~4-5 rows
        start, end = grid._get_visible_range(scroll_area, 3, 50)

        assert start >= 0
        assert end <= 50
        assert end > start

    def test_unload_thumbnail(self, qtbot, grid, sample_shot):
        """Test unloading a thumbnail."""
        # Create mock thumbnail
        mock_thumbnail = Mock()
        key = grid._get_item_key(sample_shot)
        grid._loaded_thumbnails[key] = mock_thumbnail

        # Unload it
        grid._unload_thumbnail(key)

        # Check it was removed
        assert key not in grid._loaded_thumbnails
        assert mock_thumbnail in grid._remove_from_grid_calls
        mock_thumbnail.deleteLater.assert_called_once()

    def test_unload_invisible_thumbnails_respects_limit(self, grid, sample_shot):
        """Test that unloading respects memory limit."""
        # Create many loaded thumbnails
        for i in range(60):
            shot = Shot(
                show="show",
                sequence="seq",
                shot=f"shot{i:03d}",
                workspace_path=f"/path/{i}",
            )
            key = grid._get_item_key(shot)
            mock_thumb = Mock()
            grid._loaded_thumbnails[key] = mock_thumb
            grid._placeholders[key] = ThumbnailPlaceholder(i, i // 4, i % 4, shot)

        # Set some as visible
        grid._visible_indices = set(range(10))

        # Trigger unload
        grid._unload_invisible_thumbnails()

        # Should have unloaded down to max limit
        assert len(grid._loaded_thumbnails) <= grid.MAX_LOADED_THUMBNAILS

    def test_unload_timer_behavior(self, qtbot, grid):
        """Test unload timer starts and stops correctly."""
        assert not grid._unload_timer.isActive()

        # Trigger viewport change
        grid._on_viewport_changed()

        # Timer should be active
        assert grid._unload_timer.isActive()
        assert grid._unload_timer.isSingleShot()

        # Another viewport change should restart timer
        grid._on_viewport_changed()
        assert grid._unload_timer.isActive()

    def test_create_placeholder_widget(self, grid):
        """Test placeholder widget creation."""
        widget = grid._create_placeholder_widget(0, 0)

        assert widget.width() == grid._thumbnail_size
        assert widget.height() == grid._thumbnail_size
        assert "#1a1a1a" in widget.styleSheet()

    def test_get_memory_usage(self, grid, sample_shot):
        """Test memory usage statistics."""
        # Add some data
        for i in range(10):
            shot = Shot(
                show="show",
                sequence="seq",
                shot=f"shot{i:03d}",
                workspace_path=f"/path/{i}",
            )
            key = grid._get_item_key(shot)

            # Add placeholder
            grid._placeholders[key] = ThumbnailPlaceholder(i, i // 4, i % 4, shot)

            # Load half of them
            if i < 5:
                grid._loaded_thumbnails[key] = Mock()
                grid._visible_indices.add(i)

        usage = grid.get_memory_usage()

        assert usage["loaded_thumbnails"] == 5
        assert usage["total_items"] == 10
        assert usage["max_allowed"] == 50
        assert usage["visible_count"] == 5

    def test_abstract_methods_raise_not_implemented(self, grid):
        """Test that abstract methods raise NotImplementedError."""
        base_grid = MemoryOptimizedGrid()

        with pytest.raises(NotImplementedError):
            base_grid._update_visible_thumbnails()

        with pytest.raises(NotImplementedError):
            base_grid._load_thumbnail_at_index(0)

        with pytest.raises(NotImplementedError):
            base_grid._remove_from_grid(Mock())

        with pytest.raises(NotImplementedError):
            base_grid._get_current_visible_indices()
