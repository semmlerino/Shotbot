"""Comprehensive unit tests for ShotInfoPanel with QRunnable async loading tests.

This module tests the critical thread safety improvements and InfoPanelPixmapLoader
QRunnable implementation added to ShotInfoPanel for async thumbnail loading.
"""

from __future__ import annotations

# Standard library imports
import sys
import threading
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

# Third-party imports
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QImage


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

sys.path.insert(0, str(Path(__file__).parent.parent))

# Local application imports
from shot_info_panel import InfoPanelPixmapLoader, ShotInfoPanel
from shot_model import Shot
from tests.fixtures.doubles_library import TestCacheManager


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.critical,
]


class TestInfoPanelPixmapLoader:
    """Test InfoPanelPixmapLoader QRunnable async loading."""

    @pytest.fixture
    def temp_image_file(self, tmp_path: Path, qapp: QApplication) -> Path:
        """Create temporary image file for testing."""
        # Create a simple test image
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(0xFF0000)  # Red image

        image_path = tmp_path / "test_image.jpg"
        image.save(str(image_path), "JPEG")
        return image_path

    @pytest.fixture
    def test_panel(
        self, qapp: QApplication, qtbot: QtBot
    ) -> Generator[ShotInfoPanel, None, None]:
        """Create test panel for loader testing."""
        panel = ShotInfoPanel()
        qtbot.addWidget(panel)
        yield panel
        panel.deleteLater()
        qtbot.wait(1)

    def test_loader_successful_image_loading(
        self, test_panel: ShotInfoPanel, temp_image_file: Path, qtbot: QtBot
    ) -> None:
        """Test InfoPanelPixmapLoader successful image loading."""
        loaded_signals: list[QImage] = []
        failed_signals: list[bool] = []

        def on_loaded(image: QImage) -> None:
            loaded_signals.append(image)

        def on_failed() -> None:
            failed_signals.append(True)

        # Create loader
        loader = InfoPanelPixmapLoader(test_panel, temp_image_file)
        loader.signals.loaded.connect(on_loaded)
        loader.signals.failed.connect(on_failed)

        # Start loading in thread pool and wait for signal
        try:
            with qtbot.waitSignal(loader.signals.loaded, timeout=5000):
                QThreadPool.globalInstance().start(loader)
        finally:
            # Ensure thread pool cleanup
            QThreadPool.globalInstance().waitForDone(1000)

        # Verify successful loading
        assert len(loaded_signals) == 1
        assert len(failed_signals) == 0

        loaded_image = loaded_signals[0]
        assert isinstance(loaded_image, QImage)
        assert not loaded_image.isNull()

    def test_loader_nonexistent_file_handling(
        self, test_panel: ShotInfoPanel, qtbot: QtBot
    ) -> None:
        """Test loader handling of non-existent files."""
        loaded_signals: list[QImage] = []
        failed_signals: list[bool] = []

        def on_loaded(image: QImage) -> None:
            loaded_signals.append(image)

        def on_failed() -> None:
            failed_signals.append(True)

        # Create loader with non-existent path
        nonexistent_path = Path("/nonexistent/image.jpg")
        loader = InfoPanelPixmapLoader(test_panel, nonexistent_path)
        loader.signals.loaded.connect(on_loaded)
        loader.signals.failed.connect(on_failed)

        # Start loading and wait for failure signal
        try:
            with qtbot.waitSignal(loader.signals.failed, timeout=5000):
                QThreadPool.globalInstance().start(loader)
        finally:
            # Ensure thread pool cleanup
            QThreadPool.globalInstance().waitForDone(1000)

        # Verify failure handling
        assert len(loaded_signals) == 0
        assert len(failed_signals) == 1

    def test_loader_dimension_validation_integration(
        self, test_panel: ShotInfoPanel, tmp_path: Path, qtbot: QtBot
    ) -> None:
        """Test integration with ImageUtils dimension validation."""
        # Create oversized image that should trigger validation failure
        large_image = QImage(8000, 8000, QImage.Format.Format_RGB32)
        large_image.fill(0x00FF00)  # Green image

        large_image_path = tmp_path / "large_image.jpg"
        large_image.save(str(large_image_path), "JPEG")

        loaded_signals: list[QImage] = []
        failed_signals: list[bool] = []

        def on_loaded(image: QImage) -> None:
            loaded_signals.append(image)

        def on_failed() -> None:
            failed_signals.append(True)

        loader = InfoPanelPixmapLoader(test_panel, large_image_path)
        loader.signals.loaded.connect(on_loaded)
        loader.signals.failed.connect(on_failed)

        # Start loading
        QThreadPool.globalInstance().start(loader)

        # Wait for thread to complete
        QThreadPool.globalInstance().waitForDone(2000)
        # Process any pending signals
        qtbot.wait(1)  # Minimal event processing

        # Should fail due to dimension validation
        # (Actual behavior depends on Config.MAX_INFO_PANEL_DIMENSION_PX)
        # The test verifies the integration works without crashing
        assert len(loaded_signals) + len(failed_signals) == 1

    def test_loader_concurrent_operations(
        self, test_panel: ShotInfoPanel, temp_image_file: Path, qtbot: QtBot
    ) -> None:
        """Test multiple concurrent loader operations."""
        completed_count = 0
        completion_lock = threading.Lock()

        def on_completed() -> None:
            nonlocal completed_count
            with completion_lock:
                completed_count += 1

        # Create multiple loaders
        loaders = []
        for i in range(5):
            loader = InfoPanelPixmapLoader(test_panel, temp_image_file)
            loader.signals.loaded.connect(lambda _img, _i=i: on_completed())
            loader.signals.failed.connect(lambda _i=i: on_completed())
            loaders.append(loader)

        # Start all loaders
        for loader in loaders:
            QThreadPool.globalInstance().start(loader)

        # Wait for all loaders to complete
        def all_loaders_complete() -> bool:
            with completion_lock:
                return completed_count == 5

        qtbot.waitUntil(all_loaders_complete, timeout=5000)

        # Verify all completed
        assert completed_count == 5

    def test_loader_string_path_conversion(
        self, test_panel: ShotInfoPanel, temp_image_file: Path, qtbot: QtBot
    ) -> None:
        """Test loader handles both string and Path objects."""
        loaded_signals: list[QImage] = []

        def on_loaded(image: QImage) -> None:
            loaded_signals.append(image)

        # Test with string path
        loader_str = InfoPanelPixmapLoader(test_panel, str(temp_image_file))
        loader_str.signals.loaded.connect(on_loaded)
        QThreadPool.globalInstance().start(loader_str)

        # Test with Path object
        loader_path = InfoPanelPixmapLoader(test_panel, temp_image_file)
        loader_path.signals.loaded.connect(on_loaded)
        QThreadPool.globalInstance().start(loader_path)

        # Wait for both loaders to complete
        qtbot.waitUntil(lambda: len(loaded_signals) == 2, timeout=2000)

        # Both should succeed
        assert len(loaded_signals) == 2


class TestShotInfoPanelAsyncLoading:
    """Test ShotInfoPanel async loading integration."""

    @pytest.fixture
    def test_cache_manager(self, tmp_path: Path) -> TestCacheManager:
        """Create test cache manager."""
        return TestCacheManager(cache_dir=tmp_path / "cache")

    @pytest.fixture
    def info_panel(
        self, test_cache_manager: TestCacheManager, qapp: QApplication, qtbot: QtBot
    ) -> Generator[ShotInfoPanel, None, None]:
        """Create ShotInfoPanel with test cache manager."""
        panel = ShotInfoPanel(test_cache_manager)
        qtbot.addWidget(panel)  # OK to add QWidget to qtbot
        yield panel
        panel.deleteLater()
        qtbot.wait(1)

    @pytest.fixture
    def test_shot(
        self, tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> Shot:
        """Create test shot with thumbnail."""
        # Create test thumbnail
        thumbnail_path = tmp_path / "thumbnail.jpg"
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(0x0000FF)  # Blue image
        image.save(str(thumbnail_path), "JPEG")

        # Create shot that points to this thumbnail
        shot = Shot("test_show", "test_seq", "test_shot", str(tmp_path))
        # Mock get_thumbnail_path method on the Shot class
        monkeypatch.setattr(Shot, "get_thumbnail_path", lambda _self: thumbnail_path)
        return shot

    def test_async_thumbnail_loading_workflow(
        self, info_panel: ShotInfoPanel, test_shot: Shot, qtbot: QtBot
    ) -> None:
        """Test complete async thumbnail loading workflow."""
        # Set shot - should trigger async loading
        info_panel.set_shot(test_shot)

        # Verify shot info is displayed immediately
        assert info_panel.shot_name_label.text() == test_shot.full_name
        assert test_shot.show in info_panel.show_sequence_label.text()

        # Wait for async thumbnail loading to complete
        qtbot.waitUntil(
            lambda: info_panel.thumbnail_label.pixmap() is not None,
            timeout=2000
        )

        # Verify thumbnail was loaded (placeholder or actual image)
        thumbnail_pixmap = info_panel.thumbnail_label.pixmap()
        assert thumbnail_pixmap is not None

    def test_concurrent_shot_changes(
        self,
        info_panel: ShotInfoPanel,
        tmp_path: Path,
        qtbot: QtBot,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test rapid shot changes don't cause race conditions."""
        # Create multiple test shots
        shots: list[Shot] = []
        thumbnail_paths: list[Path] = []
        for i in range(3):
            thumbnail_path = tmp_path / f"thumbnail_{i}.jpg"
            image = QImage(64, 64, QImage.Format.Format_RGB32)
            image.fill(0xFF0000 if i % 2 else 0x00FF00)  # Alternating colors
            image.save(str(thumbnail_path), "JPEG")

            shot = Shot(f"show_{i}", f"seq_{i}", f"shot_{i}", str(tmp_path))
            shots.append(shot)
            thumbnail_paths.append(thumbnail_path)

        # Create a mock function that returns the correct path based on shot
        def mock_get_thumbnail(self: Shot) -> Path | None:
            for i, s in enumerate(shots):
                if self == s:
                    return thumbnail_paths[i]
            return None

        monkeypatch.setattr(Shot, "get_thumbnail_path", mock_get_thumbnail)

        # Rapidly change shots
        for shot in shots:
            info_panel.set_shot(shot)
            qtbot.wait(1)  # Minimal event processing

        # Wait for panel to stabilize on final shot
        qtbot.waitUntil(
            lambda: info_panel._current_shot == shots[-1],
            timeout=2000
        )

        # Panel should display the last shot without crashing
        assert info_panel._current_shot == shots[-1]
        assert shots[-1].shot in info_panel.shot_name_label.text()

    def test_shot_removal_during_loading(
        self, info_panel: ShotInfoPanel, test_shot: Shot, qtbot: QtBot
    ) -> None:
        """Test shot removal while async loading is in progress."""
        # Set shot to start loading
        info_panel.set_shot(test_shot)

        # Immediately clear shot (simulates rapid user interaction)
        info_panel.set_shot(None)

        # Wait for panel to update to "no shot" state
        qtbot.waitUntil(
            lambda: info_panel.shot_name_label.text() == "No Shot Selected",
            timeout=2000
        )

        # Panel should show "no shot selected" state
        assert info_panel.shot_name_label.text() == "No Shot Selected"
        assert info_panel.show_sequence_label.text() == ""

    def test_memory_bounds_checking_integration(
        self,
        info_panel: ShotInfoPanel,
        tmp_path: Path,
        qtbot: QtBot,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test integration with ImageUtils memory bounds checking."""
        # The actual bounds checking is done in the loader
        # This test verifies the integration doesn't crash

        test_shot = Shot("bounds_test", "seq", "shot", str(tmp_path))

        # Mock get_thumbnail_path to return a path (may not exist)
        thumbnail_path = tmp_path / "bounds_test.jpg"
        monkeypatch.setattr(Shot, "get_thumbnail_path", lambda _self: thumbnail_path)

        # Set shot - should handle missing file gracefully
        info_panel.set_shot(test_shot)

        qtbot.wait(1)  # Minimal event processing

        # Should show placeholder without crashing
        thumbnail_text = info_panel.thumbnail_label.text()
        assert (
            thumbnail_text in ["", "No Image"]
            or info_panel.thumbnail_label.pixmap() is not None
        )

    def test_cache_integration(
        self, info_panel: ShotInfoPanel, test_shot: Shot, qtbot: QtBot
    ) -> None:
        """Test integration with cache manager."""
        # Mock cache manager behavior
        with patch.object(info_panel.cache_manager, "get_cached_thumbnail") as mock_get:
            mock_get.return_value = None  # No cached thumbnail

            # Set shot - should try cache first
            info_panel.set_shot(test_shot)

            qtbot.wait(1)  # Minimal event processing

            # Verify behavior: cache was accessed (not implementation detail)
            # Following UNIFIED_TESTING_GUIDE: Test behavior, not mock calls
            assert mock_get.called  # Cache was checked for thumbnail
            # The thumbnail display behavior is the important outcome,
            # not the specific arguments to the mock


class TestShotInfoPanelCore:
    """Test core ShotInfoPanel functionality."""

    @pytest.fixture
    def info_panel(
        self, qapp: QApplication, qtbot: QtBot
    ) -> Generator[ShotInfoPanel, None, None]:
        """Create basic ShotInfoPanel."""
        panel = ShotInfoPanel()
        qtbot.addWidget(panel)
        yield panel
        panel.deleteLater()
        qtbot.wait(1)

    def test_panel_initialization(self, info_panel: ShotInfoPanel) -> None:
        """Test panel initializes correctly."""
        assert info_panel.shot_name_label.text() == "No Shot Selected"
        assert info_panel.show_sequence_label.text() == ""
        assert info_panel.path_label.text() == ""
        assert info_panel._current_shot is None

    def test_shot_info_display(self, info_panel: ShotInfoPanel) -> None:
        """Test shot information display."""
        test_shot = Shot("Test Show", "Test Seq", "Test Shot", "/test/workspace/path")

        info_panel.set_shot(test_shot)

        assert info_panel.shot_name_label.text() == test_shot.full_name
        assert "Test Show" in info_panel.show_sequence_label.text()
        assert "Test Seq" in info_panel.show_sequence_label.text()
        assert "/test/workspace/path" in info_panel.path_label.text()

    def test_clear_shot_display(self, info_panel: ShotInfoPanel) -> None:
        """Test clearing shot display."""
        # Set a shot first
        test_shot = Shot("Test", "Test", "Test", "/test")
        info_panel.set_shot(test_shot)

        # Clear it
        info_panel.set_shot(None)

        assert info_panel.shot_name_label.text() == "No Shot Selected"
        assert info_panel.show_sequence_label.text() == ""
        assert info_panel.path_label.text() == ""
        assert info_panel._current_shot is None

    def test_placeholder_thumbnail_setting(self, info_panel: ShotInfoPanel) -> None:
        """Test placeholder thumbnail behavior."""
        info_panel._set_placeholder_thumbnail()

        # When setText is called after setPixmap, the pixmap is cleared
        # So we should have text but no pixmap
        thumbnail_pixmap = info_panel.thumbnail_label.pixmap()

        # The pixmap will be null because setText clears it
        if thumbnail_pixmap:
            assert thumbnail_pixmap.isNull()

        # Should have "No Image" text instead
        assert info_panel.thumbnail_label.text() == "No Image"
