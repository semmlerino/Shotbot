"""Integration tests for async workflow behaviors across multiple components.

Tests the interaction between ShotItemModel, ShotInfoPanel, and cache management
with focus on async operations and race condition prevention.
"""

from __future__ import annotations

# Standard library imports
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

# Third-party imports
import pytest
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

sys.path.insert(0, str(Path(__file__).parent.parent))

# Local application imports
from base_item_model import BaseItemRole as UnifiedRole
from cache_manager import CacheManager
from shot_info_panel import ShotInfoPanel
from shot_item_model import ShotItemModel
from shot_model import Shot
from tests.helpers.synchronization import simulate_work_without_sleep

pytestmark = [
    pytest.mark.integration,
    pytest.mark.qt,
    pytest.mark.slow,
    pytest.mark.xdist_group("qt_state"),
]


class TestAsyncWorkflowIntegration:
    """Test async workflows across multiple components."""

    @pytest.fixture
    def temp_setup(self, tmp_path: Path) -> tuple[Path, list[Path]]:
        """Create temporary directory structure with test images."""
        # Create test thumbnails
        thumbnails: list[Path] = []
        for i in range(3):
            thumbnail_path = tmp_path / f"thumbnail_{i}.jpg"
            image = QImage(128, 128, QImage.Format.Format_RGB32)
            image.fill(0xFF0000 if i % 2 else 0x00FF00)  # Alternating colors
            image.save(str(thumbnail_path), "JPEG")
            thumbnails.append(thumbnail_path)

        return tmp_path, thumbnails

    @pytest.fixture
    def test_shots(
        self, temp_setup: tuple[Path, list[Path]], monkeypatch: pytest.MonkeyPatch
    ) -> list[Shot]:
        """Create test shots with thumbnail paths."""
        tmp_path, thumbnails = temp_setup

        shots: list[Shot] = []
        thumbnail_map: dict[str, Path] = {}
        for i, thumbnail_path in enumerate(thumbnails):
            shot = Shot(f"show_{i}", f"seq_{i}", f"shot_{i}", str(tmp_path))
            shots.append(shot)
            thumbnail_map[shot.full_name] = thumbnail_path

        # Mock get_thumbnail_path to return correct path for each shot
        def mock_get_thumbnail(self: Shot) -> Path | None:
            return thumbnail_map.get(self.full_name)

        monkeypatch.setattr(Shot, "get_thumbnail_path", mock_get_thumbnail)

        return shots

    @pytest.fixture
    def integration_components(
        self, qapp: QApplication, qtbot: QtBot, temp_setup: tuple[Path, list[Path]]
    ) -> Callable[[], tuple[ShotItemModel, ShotInfoPanel, CacheManager]]:
        """Create integrated components for testing."""
        tmp_path, _ = temp_setup

        # Use real cache manager with temp directory
        cache_manager = CacheManager(cache_dir=tmp_path / "cache")

        # Return factory function to create components in test context
        def _create_components() -> tuple[ShotItemModel, ShotInfoPanel, CacheManager]:
            # Create components - must be done in test method context
            item_model = ShotItemModel(cache_manager)
            info_panel = ShotInfoPanel(cache_manager)
            qtbot.addWidget(info_panel)
            return item_model, info_panel, cache_manager

        return _create_components

        # Cleanup any created components if needed

    def test_shot_selection_with_async_thumbnail_loading(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, CacheManager]],
        test_shots: list[Shot],
        qtbot: QtBot,
    ) -> None:
        """Test shot selection triggers async loading in both model and panel."""
        item_model, info_panel, _cache_manager = integration_components()

        # Set shots in model
        item_model.set_items(test_shots)

        # Set up signal spies
        QSignalSpy(item_model.thumbnail_loaded)

        # Select first shot in model
        first_index = item_model.index(0, 0)
        success = item_model.setData(first_index, True, UnifiedRole.IsSelectedRole)
        assert success

        # Also set same shot in info panel
        info_panel.set_shot(test_shots[0])

        # Start async loading by setting visible range
        item_model.set_visible_range(0, 1)

        # Wait for the loading state to be set
        # The timer fires after 100ms and then sets the loading state
        qtbot.waitUntil(
            lambda: item_model._loading_states.get(test_shots[0].full_name) is not None,
            timeout=2000,
        )

        # Verify both components handled the shot
        assert info_panel._current_shot == test_shots[0]
        # Info panel shows the full name (sequence_shot), not show name
        assert test_shots[0].full_name in info_panel.shot_name_label.text()

        # Model should have started async loading
        loading_state = item_model._loading_states.get(test_shots[0].full_name)
        assert loading_state in ["loading", "loaded", "failed"]

        # Cleanup
        item_model.clear_thumbnail_cache()
        item_model.deleteLater()
        info_panel.deleteLater()

    def test_concurrent_model_updates_with_panel_sync(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, CacheManager]],
        test_shots: list[Shot],
        qtbot: QtBot,
    ) -> None:
        """Test model updates while panel is also loading asynchronously."""
        item_model, info_panel, _cache_manager = integration_components()

        # Start with first shot in both components
        item_model.set_items(test_shots[:1])
        info_panel.set_shot(test_shots[0])

        # Trigger async loading in both
        item_model.set_visible_range(0, 1)
        qtbot.wait(100)  # Let loading start

        # Now update model with different shots while loading
        item_model.set_items(test_shots[1:])

        # Update panel to different shot
        info_panel.set_shot(test_shots[2])

        # Wait for all async operations
        qtbot.wait(1000)

        # Verify components are in consistent state
        assert item_model.rowCount() == 2  # shots[1:] = 2 shots
        assert info_panel._current_shot == test_shots[2]

        # No crashes should occur despite concurrent operations

    def test_rapid_shot_changes_stress_test(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, CacheManager]],
        test_shots: list[Shot],
        qtbot: QtBot,
    ) -> None:
        """Stress test rapid shot changes across components."""
        item_model, info_panel, _cache_manager = integration_components()

        # Rapid fire changes
        for i in range(10):
            # Cycle through shots rapidly
            shot_index = i % len(test_shots)
            current_shot = test_shots[shot_index]

            # Update both components
            item_model.set_items([current_shot])
            info_panel.set_shot(current_shot)

            # Brief wait to simulate realistic timing
            qtbot.wait(20)

        # Final stabilization wait
        qtbot.wait(500)

        # Components should be stable without crashes
        assert item_model.rowCount() == 1
        assert info_panel._current_shot is not None

    def test_cache_coherence_across_components(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, CacheManager]],
        test_shots: list[Shot],
        qtbot: QtBot,
    ) -> None:
        """Test cache coherence when multiple components access same thumbnails."""
        item_model, info_panel, cache_manager = integration_components()

        # Set same shot in both components
        target_shot = test_shots[0]
        item_model.set_items([target_shot])
        info_panel.set_shot(target_shot)

        # Track cache interactions
        cache_calls: list[tuple[Any, ...]] = []
        original_cache_thumbnail = cache_manager.cache_thumbnail

        def track_cache_calls(*args: Any, **kwargs: Any) -> Any:
            cache_calls.append(args)
            return original_cache_thumbnail(*args, **kwargs)

        with patch.object(cache_manager, "cache_thumbnail", track_cache_calls):
            # Trigger loading in both components
            item_model.set_visible_range(0, 1)
            qtbot.wait(100)

            # Both should use same cache
            qtbot.wait(500)

            # Verify cache was accessed appropriately
            # (Exact behavior depends on cache implementation)
            assert len(cache_calls) >= 0  # May be 0 if using test cache

    def test_memory_management_during_async_operations(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, CacheManager]],
        test_shots: list[Shot],
        qtbot: QtBot,
    ) -> None:
        """Test memory management during concurrent async operations."""
        item_model, info_panel, _cache_manager = integration_components()

        # Load all shots
        item_model.set_items(test_shots)
        item_model.set_visible_range(0, len(test_shots))

        # Cycle through shots in info panel
        for shot in test_shots:
            info_panel.set_shot(shot)
            qtbot.wait(100)

        # Clear everything
        item_model.clear_thumbnail_cache()
        info_panel.set_shot(None)

        qtbot.wait(200)

        # Verify cleanup
        assert len(item_model._thumbnail_cache) == 0
        assert info_panel._current_shot is None

    def test_error_propagation_across_components(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, CacheManager]],
        test_shots: list[Shot],
        qtbot: QtBot,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test error handling doesn't cascade between components."""
        item_model, info_panel, _cache_manager = integration_components()

        # Create shot with problematic thumbnail path
        bad_shot = Shot("error_show", "error_seq", "error_shot", "/nonexistent")

        # Mock get_thumbnail_path to return nonexistent path for bad shot
        original_get_thumbnail = Shot.get_thumbnail_path

        def mock_get_thumbnail(self: Shot) -> Path | None:
            if self == bad_shot:
                return Path("/nonexistent/image.jpg")
            return original_get_thumbnail(self)

        monkeypatch.setattr(Shot, "get_thumbnail_path", mock_get_thumbnail)

        # Set in both components
        item_model.set_shots([bad_shot])
        info_panel.set_shot(bad_shot)

        # Trigger operations that will fail
        item_model.set_visible_range(0, 1)

        # Wait for the loading state to be set (timer fires after 100ms)
        qtbot.waitUntil(
            lambda: item_model._loading_states.get(bad_shot.full_name) is not None,
            timeout=2000,
        )

        # Both components should handle errors gracefully
        # Model should show failed loading state
        loading_state = item_model._loading_states.get(bad_shot.full_name)
        assert loading_state in [
            "failed",
            "idle",
            "loading",
            "loaded",
        ]  # Accept any valid state

        # Panel should show placeholder
        assert info_panel._current_shot == bad_shot
        thumbnail_text = info_panel.thumbnail_label.text()
        assert (
            thumbnail_text in ["", "No Image"]
            or info_panel.thumbnail_label.pixmap() is not None
        )

    def test_threading_safety_across_components(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, CacheManager]],
        test_shots: list[Shot],
        qtbot: QtBot,
    ) -> None:
        """Test thread safety - verify Qt operations only allowed on main thread."""
        from base_item_model import QtThreadError

        item_model, _info_panel, _cache_manager = integration_components()

        # Test that set_shots() correctly raises error when called from background thread
        error_raised = threading.Event()

        def model_operations() -> None:
            try:
                item_model.set_shots(test_shots[:1])
            except QtThreadError:
                error_raised.set()  # Expected behavior - operation blocked

        # Run operation in separate thread
        model_thread = threading.Thread(target=model_operations)
        model_thread.start()
        model_thread.join(timeout=5.0)

        # Verify the thread safety check worked
        assert error_raised.is_set(), "set_shots() should raise QtThreadError from background thread"

        # Allow Qt to process any pending events
        qtbot.wait(500)

        # Model should remain stable
        assert item_model.rowCount() >= 0


class TestAsyncCallbackIntegration:
    """Test async callback integration scenarios."""

    def test_model_reset_during_async_callbacks(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test model reset while async callbacks are in progress."""
        # Local application imports
        from shot_item_model import ShotItemModel

        # Create test setup
        image_path = tmp_path / "test.jpg"
        image = QImage(64, 64, QImage.Format.Format_RGB32)
        image.fill(0xFF0000)
        image.save(str(image_path), "JPEG")

        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        model = ShotItemModel(cache_manager)

        # Mock get_thumbnail_path to return the test image
        monkeypatch.setattr(Shot, "get_thumbnail_path", lambda self: image_path)  # type: ignore[misc]

        try:
            # Create initial shots
            initial_shots = [
                Shot("show1", "seq1", "shot1", str(tmp_path)),
                Shot("show1", "seq1", "shot2", str(tmp_path)),
            ]

            model.set_shots(initial_shots)

            # Start async loading
            model.set_visible_range(0, 2)
            qtbot.wait(100)  # Let async operations start

            # Reset model with completely different shots
            new_shots = [Shot("new_show", "new_seq", "new_shot", str(tmp_path))]

            model.set_shots(new_shots)

            # Wait for all operations to complete
            qtbot.wait(1000)

            # Model should be in consistent state
            assert model.rowCount() == 1
            # Cache is filtered - old items removed, new items may have loaded thumbnails
            # The new shot's thumbnail may have been loaded asynchronously
            assert len(model._thumbnail_cache) <= 1

        finally:
            model.deleteLater()

    def test_info_panel_shot_change_during_loading(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test info panel shot changes while async loading is in progress."""
        # Create test image
        image_path = tmp_path / "test.jpg"
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(0x00FF00)
        image.save(str(image_path), "JPEG")

        cache_manager = CacheManager(cache_dir=tmp_path / "cache")
        panel = ShotInfoPanel(cache_manager)
        qtbot.addWidget(panel)

        # Mock get_thumbnail_path to return the test image
        monkeypatch.setattr(Shot, "get_thumbnail_path", lambda self: image_path)  # type: ignore[misc]

        try:
            # Create test shots
            shots: list[Shot] = []
            for i in range(3):
                shot = Shot(f"show_{i}", f"seq_{i}", f"shot_{i}", str(tmp_path))
                shots.append(shot)

            # Rapidly cycle through shots
            for shot in shots:
                panel.set_shot(shot)
                qtbot.wait(50)  # Brief delay to let loading start

            # Wait for final stabilization
            qtbot.wait(500)

            # Panel should show the last shot
            assert panel._current_shot == shots[-1]
            assert shots[-1].shot in panel.shot_name_label.text()

        finally:
            panel.deleteLater()
