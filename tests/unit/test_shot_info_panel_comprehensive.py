"""Comprehensive unit tests for ShotInfoPanel.

This module focuses on higher-level async thumbnail loading behavior and core UI
state, avoiding the unstable low-level QRunnable micro-tests that duplicated
that coverage.
"""

from __future__ import annotations

# Standard library imports
import sys
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

# Third-party imports
import pytest
from PIL import Image


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

sys.path.insert(0, str(Path(__file__).parent.parent))

# Local application imports
from shots.shot_info_panel import ShotInfoPanel
from tests.fixtures.test_doubles import TestCacheManager
from type_definitions import Shot


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.critical,
]


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
        # Create test thumbnail (PIL avoids C++ segfaults from Qt state contamination)
        thumbnail_path = tmp_path / "thumbnail.jpg"
        img = Image.new("RGB", (128, 128), color=(0, 0, 255))
        img.save(str(thumbnail_path), "JPEG")

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
            color = (255, 0, 0) if i % 2 else (0, 255, 0)
            img = Image.new("RGB", (64, 64), color=color)
            img.save(str(thumbnail_path), "JPEG")

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
