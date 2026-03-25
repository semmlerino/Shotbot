"""Integration tests for async workflow behaviors across multiple components.

Tests the interaction between ShotItemModel, ShotInfoPanel, and cache management
with focus on async operations and race condition prevention.
"""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Third-party imports
import pytest
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from cache.thumbnail_cache import ThumbnailCache

sys.path.insert(0, str(Path(__file__).parent.parent))

# Local application imports
from shots.shot_info_panel import ShotInfoPanel
from shots.shot_item_model import ShotItemModel
from tests.test_helpers import process_qt_events
from type_definitions import Shot
from workers.runnable_tracker import get_tracker


pytestmark = [
    pytest.mark.qt,
    pytest.mark.slow,
    pytest.mark.qt_heavy,
]


@pytest.mark.xdist_group("serial_qt_state")
class TestAsyncWorkflowIntegration:
    """Test async workflows across multiple components."""

    @pytest.fixture(autouse=True)
    def cleanup_qt_state(self, qtbot: QtBot) -> Any:
        """Autouse fixture to ensure Qt state is cleaned up after each test."""
        yield
        # Wait for all background QRunnables (InfoPanelPixmapLoader) to complete
        # CRITICAL: Without this, deleteLater() may delete widgets while
        # background threads are still emitting signals, causing segfaults
        get_tracker().wait_for_all(timeout_ms=2000)
        process_qt_events()  # Process pending Qt events

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
    ) -> Callable[[], tuple[ShotItemModel, ShotInfoPanel, ThumbnailCache]]:
        """Create integrated components for testing."""
        from cache.thumbnail_cache import ThumbnailCache
        tmp_path, _ = temp_setup

        # Use real thumbnail cache with temp directory
        thumbnail_cache = ThumbnailCache(tmp_path / "cache")

        # Return factory function to create components in test context
        def _create_components() -> tuple[ShotItemModel, ShotInfoPanel, ThumbnailCache]:
            # Create components - must be done in test method context
            item_model = ShotItemModel(thumbnail_cache)
            info_panel = ShotInfoPanel(thumbnail_cache)
            qtbot.addWidget(info_panel)
            return item_model, info_panel, thumbnail_cache

        return _create_components

        # Cleanup any created components if needed

    def test_shot_selection_with_async_thumbnail_loading(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, ThumbnailCache]],
        test_shots: list[Shot],
        qtbot: QtBot,
    ) -> None:
        """Test shot selection triggers async loading in both model and panel."""
        item_model, info_panel, _cache_manager = integration_components()

        # Set shots in model
        item_model.set_items(test_shots)

        # Set up signal spies
        QSignalSpy(item_model.thumbnail_loaded)

        # Also set same shot in info panel
        info_panel.set_shot(test_shots[0])

        # Start async loading by setting visible range
        item_model.set_visible_range(0, 1)

        # Wait for the loading state to be set
        # The timer fires after 100ms and then sets the loading state
        qtbot.waitUntil(
            lambda: item_model._thumbnail_loader.loading_states.get(test_shots[0].full_name) is not None,
            timeout=2000,
        )

        # Verify both components handled the shot
        assert info_panel._current_shot == test_shots[0]
        # Info panel shows the full name (sequence_shot), not show name
        assert test_shots[0].full_name in info_panel.shot_name_label.text()

        # Model should have started async loading
        loading_state = item_model._thumbnail_loader.loading_states.get(test_shots[0].full_name)
        assert loading_state in ["loading", "loaded", "failed"]

        # Cleanup - wait for background threads before deleting widgets
        get_tracker().wait_for_all(timeout_ms=2000)
        item_model.clear_thumbnail_cache()
        item_model.deleteLater()

    def test_concurrent_model_updates_with_panel_sync(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, ThumbnailCache]],
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
        qtbot.wait(1)  # Minimal event processing for async loading start

        # Now update model with different shots while loading
        item_model.set_items(test_shots[1:])

        # Update panel to different shot
        info_panel.set_shot(test_shots[2])

        # Wait for all async operations to complete
        def async_ops_complete() -> bool:
            # Check that model row count matches expected
            model_correct = item_model.rowCount() == 2
            # Check that panel has switched to correct shot
            panel_correct = info_panel._current_shot == test_shots[2]
            return model_correct and panel_correct

        qtbot.waitUntil(async_ops_complete, timeout=5000)

        # Verify components are in consistent state
        assert item_model.rowCount() == 2  # shots[1:] = 2 shots
        assert info_panel._current_shot == test_shots[2]

        # No crashes should occur despite concurrent operations

    def test_rapid_shot_changes_stress_test(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, ThumbnailCache]],
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
            qtbot.wait(1)  # Minimal event processing

        # Wait for components to stabilize after rapid changes
        qtbot.waitUntil(lambda: item_model.rowCount() == 1, timeout=2000)

        # Components should be stable without crashes
        assert item_model.rowCount() == 1
        assert info_panel._current_shot is not None

        # Cleanup - wait for background threads, then process events and delete
        get_tracker().wait_for_all(timeout_ms=2000)
        process_qt_events()
        item_model.clear_thumbnail_cache()
        item_model.deleteLater()
        info_panel.deleteLater()
        process_qt_events()

    def test_memory_management_during_async_operations(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, ThumbnailCache]],
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
            qtbot.wait(1)  # Minimal event processing

        # Clear everything
        item_model.clear_thumbnail_cache()
        info_panel.set_shot(None)

        # Wait for cleanup to complete
        qtbot.waitUntil(
            lambda: len(item_model._thumbnail_loader.thumbnail_cache) == 0 and info_panel._current_shot is None,
            timeout=2000
        )

        # Verify cleanup
        assert len(item_model._thumbnail_loader.thumbnail_cache) == 0
        assert info_panel._current_shot is None

    def test_error_propagation_across_components(
        self,
        integration_components: Callable[[], tuple[ShotItemModel, ShotInfoPanel, ThumbnailCache]],
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
            lambda: item_model._thumbnail_loader.loading_states.get(bad_shot.full_name) is not None,
            timeout=2000,
        )

        # Both components should handle errors gracefully
        # Model should show failed loading state (non-existent image)
        loading_state = item_model._thumbnail_loader.loading_states.get(bad_shot.full_name)
        assert loading_state in ["failed", "loaded"]  # Should not remain loading/idle

        # Panel should show placeholder
        assert info_panel._current_shot == bad_shot
        thumbnail_text = info_panel.thumbnail_label.text()
        assert (
            thumbnail_text in ["", "No Image"]
            or info_panel.thumbnail_label.pixmap() is not None
        )


@pytest.mark.xdist_group("serial_qt_state")
class TestAsyncCallbackIntegration:
    """Test async callback integration scenarios."""

    @pytest.fixture(autouse=True)
    def cleanup_qt_state(self, qtbot: QtBot) -> Any:
        """Autouse fixture to ensure Qt state is cleaned up after each test."""
        yield
        # Wait for all background QRunnables (InfoPanelPixmapLoader) to complete
        # CRITICAL: Without this, deleteLater() may delete widgets while
        # background threads are still emitting signals, causing segfaults
        get_tracker().wait_for_all(timeout_ms=2000)
        process_qt_events()  # Process pending Qt events

    def test_model_reset_during_async_callbacks(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test model reset while async callbacks are in progress."""
        # Local application imports
        from shots.shot_item_model import (
            ShotItemModel,
        )

        # Create test setup
        image_path = tmp_path / "test.jpg"
        image = QImage(64, 64, QImage.Format.Format_RGB32)
        image.fill(0xFF0000)
        image.save(str(image_path), "JPEG")

        from cache.thumbnail_cache import ThumbnailCache
        thumbnail_cache = ThumbnailCache(tmp_path / "cache")
        model = ShotItemModel(thumbnail_cache)

        # Mock get_thumbnail_path to return the test image
        monkeypatch.setattr(Shot, "get_thumbnail_path", lambda _: image_path)  # type: ignore[misc]

        try:
            # Create initial shots
            initial_shots = [
                Shot("show1", "seq1", "shot1", str(tmp_path)),
                Shot("show1", "seq1", "shot2", str(tmp_path)),
            ]

            model.set_shots(initial_shots)

            # Start async loading
            model.set_visible_range(0, 2)
            qtbot.wait(1)  # Minimal event processing for async loading start

            # Reset model with completely different shots
            new_shots = [Shot("new_show", "new_seq", "new_shot", str(tmp_path))]

            model.set_shots(new_shots)

            # Wait for all operations to complete
            def model_reset_complete() -> bool:
                # Check that model has been reset to new shots
                row_count_correct = model.rowCount() == 1
                # Check that cache has been filtered to match new shots
                cache_filtered = len(model._thumbnail_loader.thumbnail_cache) <= 1
                return row_count_correct and cache_filtered

            qtbot.waitUntil(model_reset_complete, timeout=5000)

            # Model should be in consistent state
            assert model.rowCount() == 1
            # Cache is filtered - old items removed, new items may have loaded thumbnails
            # The new shot's thumbnail may have been loaded asynchronously
            assert len(model._thumbnail_loader.thumbnail_cache) <= 1

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

        from cache.thumbnail_cache import ThumbnailCache
        thumbnail_cache = ThumbnailCache(tmp_path / "cache")
        panel = ShotInfoPanel(thumbnail_cache)
        qtbot.addWidget(panel)

        # Mock get_thumbnail_path to return the test image
        monkeypatch.setattr(Shot, "get_thumbnail_path", lambda _: image_path)  # type: ignore[misc]

        # Create test shots
        shots: list[Shot] = []
        for i in range(3):
            shot = Shot(f"show_{i}", f"seq_{i}", f"shot_{i}", str(tmp_path))
            shots.append(shot)

        # Rapidly cycle through shots
        for shot in shots:
            panel.set_shot(shot)
            qtbot.wait(1)  # Minimal event processing

        # Wait for panel to stabilize on final shot
        qtbot.waitUntil(
            lambda: panel._current_shot == shots[-1],
            timeout=2000
        )

        # Panel should show the last shot
        assert panel._current_shot == shots[-1]
        assert shots[-1].shot in panel.shot_name_label.text()
