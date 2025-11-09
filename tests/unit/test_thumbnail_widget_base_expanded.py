"""Expanded tests for thumbnail_widget_base.py to improve coverage.

This test module focuses on areas not covered by test_thumbnail_widget_qt.py:
- FolderOpenerWorker background operations
- BaseThumbnailLoader background operations
- ThumbnailWidgetBase thumbnail loading and caching
- Size change operations
- Style updates and selection state changes
- Error handling in background workers

Test Coverage Goals:
- FolderOpenerWorker: Test folder opening on different platforms
- BaseThumbnailLoader: Test thumbnail loading, validation, and error handling
- ThumbnailWidgetBase: Test thumbnail operations, size changes, and state management
- Edge cases: Missing files, permission errors, invalid paths
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock, patch

import pytest
from PySide6.QtCore import Qt, QThreadPool, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QMenu

from cache_manager import CacheManager
from config import Config
from shot_model import Shot
from thumbnail_widget import ThumbnailWidget
from thumbnail_widget_base import (
    BaseThumbnailLoader,
    FolderOpenerWorker,
    LoadingState,
)


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # Prevent Qt state contamination in parallel execution
    pytest.mark.xdist_group(name="qt"),
]

_MINIMAL_PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D4948445200000001000000010802000000907753DE0000000C49444154789C636068F80F00020301802461F5970000000049454E44AE426082"
)


def _make_test_image(
    width: int = 100,
    height: int = 100,
    color: Qt.GlobalColor = Qt.GlobalColor.green,
) -> QImage:
    """Create a simple RGB image for testing without touching QPixmap."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(color)
    return image


def _process_events() -> None:
    """Process pending Qt events without entering qtbot.wait()."""
    app = QApplication.instance()
    if app is not None:
        app.processEvents()

@pytest.fixture(autouse=True)
def run_thumbnail_loaders_inline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run ThumbnailWidget threadpool work inline to avoid xdist race crashes.

    Qt's global threadpool keeps background QRunnables alive across tests, and when
    xdist runs other suites concurrently those dangling tasks can emit signals after
    their owning widgets were deleted, triggering intermittent segfaults.

    For this module we only care about the widget logic, not the actual threading
    mechanics, so we replace QThreadPool.globalInstance() with a tiny inline pool
    that executes runnables immediately (and still reports active thread counts so
    qt_cleanup() can observe a consistent state).
    """

    class _InlinePool:
        def __init__(self) -> None:
            self._active = 0

        def start(self, runnable) -> None:
            self._active += 1
            try:
                runnable.run()
            finally:
                self._active -= 1

        def waitForDone(self, *_args) -> bool:
            return True

        def activeThreadCount(self) -> int:
            return self._active

        def clear(self) -> None:
            self._active = 0

    inline_pool = _InlinePool()

    class _InlineQThreadPool:
        @staticmethod
        def globalInstance() -> _InlinePool:
            return inline_pool

    import thumbnail_widget_base as _thumb_module

    # Patch both the module under test and this module's alias so calls are inline.
    monkeypatch.setattr(_thumb_module, "QThreadPool", _InlineQThreadPool)
    monkeypatch.setattr(sys.modules[__name__], "QThreadPool", _InlineQThreadPool)

    return


class TestFolderOpenerWorker:
    """Test FolderOpenerWorker background operations."""

    @pytest.fixture
    def temp_folder(self, tmp_path: Path) -> Path:
        """Create a temporary folder for testing."""
        folder = tmp_path / "test_folder"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def test_folder_opener_initialization(self, temp_folder: Path) -> None:
        """Test FolderOpenerWorker initializes correctly."""
        worker = FolderOpenerWorker(str(temp_folder))

        assert worker.folder_path == str(temp_folder)
        assert hasattr(worker, "signals")
        assert hasattr(worker.signals, "error")
        assert hasattr(worker.signals, "success")

    def test_folder_opener_with_valid_path(
        self, qtbot: QtBot, temp_folder: Path
    ) -> None:
        """Test folder opener with valid existing path."""
        worker = FolderOpenerWorker(str(temp_folder))

        # Set up signal spy
        success_spy = QSignalSpy(worker.signals.success)
        error_spy = QSignalSpy(worker.signals.error)

        # Mock QDesktopServices.openUrl to return success
        with patch(
            "thumbnail_widget_base.QDesktopServices.openUrl", return_value=True
        ):
            worker.run()

        # Should emit success
        assert success_spy.count() == 1
        assert error_spy.count() == 0

    def test_folder_opener_with_missing_path(self, qtbot: QtBot) -> None:
        """Test folder opener with non-existent path."""
        worker = FolderOpenerWorker("/nonexistent/path")

        # Set up signal spy
        error_spy = QSignalSpy(worker.signals.error)

        worker.run()

        # Should emit error
        assert error_spy.count() == 1
        # QSignalSpy stores signals as a list, access via .at(index)
        signal_args = error_spy.at(0)
        error_msg = signal_args[0]
        assert "does not exist" in error_msg

    def test_folder_opener_with_relative_path(
        self, qtbot: QtBot, temp_folder: Path
    ) -> None:
        """Test folder opener converts relative path to absolute."""
        # Use relative path without leading slash
        relative_path = str(temp_folder).lstrip("/")
        worker = FolderOpenerWorker(relative_path)

        # Mock QDesktopServices.openUrl
        with patch(
            "thumbnail_widget_base.QDesktopServices.openUrl", return_value=True
        ) as mock_open:
            worker.run()

            # Should have been called with absolute path
            assert mock_open.called
            # Check that URL path starts with /
            call_args = mock_open.call_args[0][0]
            assert isinstance(call_args, QUrl)
            assert call_args.path().startswith("/")

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific test")
    def test_folder_opener_linux_fallback(
        self, qtbot: QtBot, temp_folder: Path
    ) -> None:
        """Test folder opener uses Linux fallback when QDesktopServices fails."""
        worker = FolderOpenerWorker(str(temp_folder))

        # Mock QDesktopServices to fail, forcing fallback
        with (
            patch(
                "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
            ),
            patch("subprocess.run") as mock_run,
        ):
            worker.run()

            # Should have tried xdg-open
            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            assert "xdg-open" in call_args or "gio" in call_args

    def test_folder_opener_handles_subprocess_error(
        self, qtbot: QtBot, temp_folder: Path
    ) -> None:
        """Test folder opener handles subprocess errors gracefully."""
        worker = FolderOpenerWorker(str(temp_folder))

        error_spy = QSignalSpy(worker.signals.error)

        # Mock both QDesktopServices and subprocess to fail
        with (
            patch(
                "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
            ),
            patch(
                "subprocess.run",
                side_effect=FileNotFoundError("xdg-open not found"),
            ),
        ):
            worker.run()

            # Should emit error
            assert error_spy.count() == 1
            signal_args = error_spy.at(0)
            error_msg = signal_args[0]
            assert "File manager not found" in error_msg or "not found" in error_msg


class TestBaseThumbnailLoaderErrorHandling:
    """Test BaseThumbnailLoader error handling edge cases."""

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create test shot."""
        return Shot(
            "test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010"
        )

    @pytest.fixture
    def test_widget(self, qtbot: QtBot, test_shot: Shot) -> ThumbnailWidget:
        """Create test widget."""
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        return widget

    def test_loader_handles_permission_error(
        self, qtbot: QtBot, test_widget: ThumbnailWidget, tmp_path: Path
    ) -> None:
        """Test loader handles PermissionError gracefully."""
        test_path = tmp_path / "restricted.png"
        test_path.write_text("test")

        # Mock QImage to raise PermissionError
        with patch("thumbnail_widget_base.QImage") as mock_qimage:
            mock_qimage.side_effect = PermissionError("Access denied")

            loader = BaseThumbnailLoader(test_widget, test_path)
            failed_spy = QSignalSpy(loader.signals.failed)

            loader.run()
            qtbot.waitUntil(lambda: failed_spy.count() == 1, timeout=1000)

            # Should emit failed signal
            assert failed_spy.count() == 1

    def test_loader_handles_os_error(
        self, qtbot: QtBot, test_widget: ThumbnailWidget, tmp_path: Path
    ) -> None:
        """Test loader handles OSError gracefully."""
        test_path = tmp_path / "ioerror.png"
        test_path.write_text("test")

        # Mock QImage to raise OSError
        with patch("thumbnail_widget_base.QImage") as mock_qimage:
            mock_qimage.side_effect = OSError("I/O error")

            loader = BaseThumbnailLoader(test_widget, test_path)
            failed_spy = QSignalSpy(loader.signals.failed)

            loader.run()
            qtbot.waitUntil(lambda: failed_spy.count() == 1, timeout=1000)

            # Should emit failed signal
            assert failed_spy.count() == 1

    def test_loader_handles_generic_exception(
        self, qtbot: QtBot, test_widget: ThumbnailWidget, tmp_path: Path
    ) -> None:
        """Test loader handles generic exceptions gracefully."""
        test_path = tmp_path / "exception.png"
        test_path.write_text("test")

        # Mock QImage to raise generic exception
        with patch("thumbnail_widget_base.QImage") as mock_qimage:
            mock_qimage.side_effect = RuntimeError("Unexpected error")

            loader = BaseThumbnailLoader(test_widget, test_path)
            failed_spy = QSignalSpy(loader.signals.failed)

            loader.run()
            qtbot.waitUntil(lambda: failed_spy.count() == 1, timeout=1000)

            # Should emit failed signal
            assert failed_spy.count() == 1


class TestBaseThumbnailLoader:
    """Test BaseThumbnailLoader background operations."""

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create test shot."""
        return Shot(
            "test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010"
        )

    @pytest.fixture
    def test_widget(self, qtbot: QtBot, test_shot: Shot) -> ThumbnailWidget:
        """Create test widget."""
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        return widget

    @pytest.fixture
    def test_image_path(self, tmp_path: Path) -> Path:
        """Create a test image file."""
        image_path = tmp_path / "test_image.png"
        image_path.write_bytes(_MINIMAL_PNG)
        return image_path

    def test_loader_initialization(
        self, test_widget: ThumbnailWidget, test_image_path: Path
    ) -> None:
        """Test BaseThumbnailLoader initializes correctly."""
        loader = BaseThumbnailLoader(test_widget, test_image_path)

        assert loader.widget == test_widget
        assert loader.path == test_image_path
        assert hasattr(loader, "signals")
        assert hasattr(loader.signals, "loaded")
        assert hasattr(loader.signals, "failed")

    def test_loader_with_valid_image(
        self, qtbot: QtBot, test_widget: ThumbnailWidget, test_image_path: Path
    ) -> None:
        """Test loader successfully loads valid image."""
        loader = BaseThumbnailLoader(test_widget, test_image_path)

        loaded_spy = QSignalSpy(loader.signals.loaded)
        failed_spy = QSignalSpy(loader.signals.failed)

        loader.run()
        qtbot.waitUntil(lambda: loaded_spy.count() == 1, timeout=1000)

        # Should emit loaded signal
        assert loaded_spy.count() == 1
        assert failed_spy.count() == 0

        # Check signal parameters
        signal_args = loaded_spy.at(0)
        widget_arg = signal_args[0]
        image_arg = signal_args[1]
        assert widget_arg == test_widget
        assert isinstance(image_arg, QImage)
        assert not image_arg.isNull()

    def test_loader_with_missing_file(
        self, qtbot: QtBot, test_widget: ThumbnailWidget
    ) -> None:
        """Test loader handles missing file correctly."""
        missing_path = Path("/nonexistent/image.png")
        loader = BaseThumbnailLoader(test_widget, missing_path)

        loaded_spy = QSignalSpy(loader.signals.loaded)
        failed_spy = QSignalSpy(loader.signals.failed)

        loader.run()
        qtbot.waitUntil(lambda: failed_spy.count() == 1, timeout=1000)

        # Should emit failed signal
        assert loaded_spy.count() == 0
        assert failed_spy.count() == 1
        signal_args = failed_spy.at(0)
        assert signal_args[0] == test_widget

    def test_loader_with_none_path(
        self, qtbot: QtBot, test_widget: ThumbnailWidget
    ) -> None:
        """Test loader handles None path correctly."""
        loader = BaseThumbnailLoader(test_widget, None)

        failed_spy = QSignalSpy(loader.signals.failed)

        loader.run()
        qtbot.waitUntil(lambda: failed_spy.count() == 1, timeout=1000)

        # Should emit failed signal
        assert failed_spy.count() == 1

    def test_loader_with_invalid_image(
        self, qtbot: QtBot, test_widget: ThumbnailWidget, tmp_path: Path
    ) -> None:
        """Test loader handles invalid image file."""
        # Create an invalid image file (not a real image)
        invalid_path = tmp_path / "invalid.png"
        invalid_path.write_text("This is not an image")

        loader = BaseThumbnailLoader(test_widget, invalid_path)

        loaded_spy = QSignalSpy(loader.signals.loaded)
        failed_spy = QSignalSpy(loader.signals.failed)

        loader.run()
        qtbot.waitUntil(lambda: failed_spy.count() == 1, timeout=1000)

        # Should emit failed signal because QImage.isNull() will be True
        assert loaded_spy.count() == 0
        assert failed_spy.count() == 1

    def test_loader_with_oversized_image(
        self, qtbot: QtBot, test_widget: ThumbnailWidget, tmp_path: Path
    ) -> None:
        """Test loader validates image dimensions."""
        oversized_path = tmp_path / "oversized.png"

        # Mock ImageUtils.validate_image_dimensions to return False
        with patch("utils.ImageUtils.validate_image_dimensions", return_value=False):
            # Create a valid image (validation will be mocked to fail)
            image = QImage(100, 100, QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.red)
            image.save(str(oversized_path))

            loader = BaseThumbnailLoader(test_widget, oversized_path)
            failed_spy = QSignalSpy(loader.signals.failed)

            loader.run()
            qtbot.waitUntil(lambda: failed_spy.count() == 1, timeout=1000)

            # Should emit failed signal due to validation failure
            assert failed_spy.count() == 1


class TestThumbnailWidgetBaseLoadingOperations:
    """Test ThumbnailWidgetBase thumbnail loading and caching operations."""

    @pytest.fixture(autouse=True)
    def cleanup_cache_manager(self, cache_manager) -> Iterator[None]:
        """Reset ThumbnailWidget cache manager after each test.

        This prevents cache manager pollution between tests.
        Critical for test isolation when tests use set_cache_manager().

        Per UNIFIED_TESTING_V2.MD: Use monkeypatch for global state isolation.
        """
        # Save the current cache manager before test
        ThumbnailWidget._cache_manager if hasattr(ThumbnailWidget, "_cache_manager") else None

        yield

        # Restore to CLEAN cache manager (from fixture) to prevent pollution
        # Don't restore to original_cache as it may already be polluted from previous tests
        ThumbnailWidget.set_cache_manager(cache_manager)

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create test shot."""
        return Shot(
            "test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010"
        )

    @pytest.fixture
    def mock_cache_manager(self) -> CacheManager:
        """Create a mock cache manager."""
        cache = Mock(spec=CacheManager)
        cache.get_cached_thumbnail = Mock(return_value=None)
        return cache

    def test_load_thumbnail_from_cache_when_available(
        self, qtbot: QtBot, test_shot: Shot, tmp_path: Path
    ) -> None:
        """Test widget loads thumbnail from cache when available."""
        # Create a cached thumbnail
        cached_thumb = tmp_path / "cached.png"
        image = _make_test_image(100, 100, Qt.GlobalColor.blue)
        image.save(str(cached_thumb))

        # Mock cache manager to return cached path
        mock_cache = Mock(spec=CacheManager)
        mock_cache.get_cached_thumbnail = Mock(return_value=cached_thumb)

        # Set cache manager before creating widget
        ThumbnailWidget.set_cache_manager(mock_cache)

        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        qtbot.waitUntil(
            lambda: mock_cache.get_cached_thumbnail.called,
            timeout=1000
        )

        # Cache should have been queried
        mock_cache.get_cached_thumbnail.assert_called_once_with(
            test_shot.show, test_shot.sequence, test_shot.shot
        )

    def test_widget_loading_state_progression(
        self, qtbot: QtBot, test_shot: Shot
    ) -> None:
        """Test loading state progresses correctly."""
        # Create widget but don't wait - catch it during loading
        # Note: Loading may complete very quickly in tests
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)

        # State should be LOADING or already transitioned to FAILED (if no thumbnail)
        # In test environment, thumbnails don't exist, so FAILED is expected
        assert widget._loading_state in (LoadingState.LOADING, LoadingState.FAILED)

        # Loading indicator should be stopped if loading failed quickly
        # (This is expected behavior in test environment without real thumbnails)

    def test_on_thumbnail_loaded_updates_state(
        self, qtbot: QtBot, test_shot: Shot
    ) -> None:
        """Test _on_thumbnail_loaded updates state correctly."""
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)

        # Reset to clean state for testing
        widget._loading_state = LoadingState.LOADING
        widget._pixmap = None

        # Create a test image (converted inside _on_thumbnail_loaded)
        test_image = _make_test_image(100, 100, Qt.GlobalColor.green)

        # Simulate thumbnail loaded
        widget._on_thumbnail_loaded(widget, test_image)
        _process_events()

        # State should be LOADED
        assert widget._loading_state == LoadingState.LOADED
        assert widget._pixmap is not None
        # Loading indicator should be stopped
        assert not widget.loading_indicator.isVisible()

    def test_on_thumbnail_failed_updates_state(
        self, qtbot: QtBot, test_shot: Shot
    ) -> None:
        """Test _on_thumbnail_failed updates state correctly."""
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)

        # Reset to clean state for testing
        widget._loading_state = LoadingState.LOADING
        widget._pixmap = None

        # Simulate thumbnail loading failure
        widget._on_thumbnail_failed(widget)
        _process_events()

        # State should be FAILED
        assert widget._loading_state == LoadingState.FAILED
        # Loading indicator should be stopped
        assert not widget.loading_indicator.isVisible()

    def test_on_thumbnail_loaded_ignores_other_widget(
        self, qtbot: QtBot, test_shot: Shot
    ) -> None:
        """Test _on_thumbnail_loaded ignores signals from other widgets."""
        widget1 = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget1)

        widget2 = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget2)

        test_image = _make_test_image(100, 100, Qt.GlobalColor.yellow)

        # Store original state
        original_state = widget1._loading_state

        # Call _on_thumbnail_loaded with widget2
        widget1._on_thumbnail_loaded(widget2, test_image)

        # widget1 state should be unchanged
        assert widget1._loading_state == original_state
        # No pixmap should have been assigned when widget ids mismatch
        assert widget1._pixmap is None


class TestThumbnailWidgetBaseSizeOperations:
    """Test ThumbnailWidgetBase size change operations."""

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create test shot."""
        return Shot(
            "test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010"
        )

    @pytest.fixture
    def sized_widget(self, qtbot: QtBot, test_shot: Shot) -> ThumbnailWidget:
        """Create widget for size testing."""
        widget = ThumbnailWidget(test_shot, 150)
        qtbot.addWidget(widget)
        return widget

    def test_set_size_updates_dimensions(
        self, qtbot: QtBot, sized_widget: ThumbnailWidget
    ) -> None:
        """Test set_size updates widget dimensions."""
        new_size = 200

        sized_widget.set_size(new_size)
        _process_events()

        # Thumbnail size should be updated
        assert sized_widget._thumbnail_size == new_size
        assert sized_widget.thumbnail_label.size().width() == new_size
        assert sized_widget.thumbnail_label.size().height() == new_size
        assert sized_widget.thumbnail_container.size().width() == new_size
        assert sized_widget.thumbnail_container.size().height() == new_size

    def test_set_size_repositions_loading_indicator(
        self, qtbot: QtBot, sized_widget: ThumbnailWidget
    ) -> None:
        """Test set_size repositions loading indicator correctly."""
        new_size = 250

        sized_widget.set_size(new_size)
        _process_events()

        # Loading indicator should be centered
        expected_x = (new_size - 40) // 2
        expected_y = (new_size - 40) // 2
        assert sized_widget.loading_indicator.x() == expected_x
        assert sized_widget.loading_indicator.y() == expected_y

    def test_set_size_updates_fixed_height(
        self, qtbot: QtBot, sized_widget: ThumbnailWidget
    ) -> None:
        """Test set_size updates widget fixed height."""
        new_size = 180

        sized_widget.set_size(new_size)
        _process_events()

        # Widget height should be recalculated
        expected_height = sized_widget._calculate_widget_height()
        assert sized_widget.height() == expected_height

    def test_set_size_with_loaded_pixmap(
        self, qtbot: QtBot, sized_widget: ThumbnailWidget
    ) -> None:
        """Test set_size updates thumbnail when pixmap is loaded."""
        # Set a pixmap
        image = _make_test_image(200, 200, Qt.GlobalColor.yellow)
        sized_widget._pixmap = QPixmap.fromImage(image)

        new_size = 120

        sized_widget.set_size(new_size)
        _process_events()

        # Thumbnail should be updated with new size
        current_pixmap = sized_widget.thumbnail_label.pixmap()
        assert current_pixmap is not None
        # The scaled pixmap should respect the new size
        assert current_pixmap.width() <= new_size, (
            f"Pixmap width {current_pixmap.width()} should be <= {new_size}"
        )
        assert current_pixmap.height() <= new_size, (
            f"Pixmap height {current_pixmap.height()} should be <= {new_size}"
        )

    def test_set_size_without_pixmap_shows_placeholder(
        self, qtbot: QtBot, sized_widget: ThumbnailWidget
    ) -> None:
        """Test set_size shows placeholder when no pixmap loaded."""
        # Ensure no pixmap
        sized_widget._pixmap = None

        new_size = 160

        sized_widget.set_size(new_size)
        _process_events()

        # Should have a pixmap (the placeholder)
        placeholder = sized_widget.thumbnail_label.pixmap()
        assert placeholder is not None


class TestThumbnailWidgetBaseSelectionOperations:
    """Test ThumbnailWidgetBase selection state operations."""

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create test shot."""
        return Shot(
            "test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010"
        )

    @pytest.fixture
    def selectable_widget(self, qtbot: QtBot, test_shot: Shot) -> ThumbnailWidget:
        """Create widget for selection testing."""
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        return widget

    def test_set_selected_true_updates_state(
        self, qtbot: QtBot, selectable_widget: ThumbnailWidget
    ) -> None:
        """Test set_selected(True) updates state and style."""
        selectable_widget.set_selected(True)
        _process_events()

        assert selectable_widget._selected is True
        # Style should contain selected style elements
        style = selectable_widget.styleSheet()
        assert "#0d7377" in style or "#14ffec" in style  # Selected colors

    def test_set_selected_false_updates_state(
        self, qtbot: QtBot, selectable_widget: ThumbnailWidget
    ) -> None:
        """Test set_selected(False) updates state and style."""
        # First select
        selectable_widget.set_selected(True)
        _process_events()

        # Then deselect
        selectable_widget.set_selected(False)
        _process_events()

        assert selectable_widget._selected is False
        # Style should contain unselected style elements
        style = selectable_widget.styleSheet()
        assert "#2b2b2b" in style or "#444" in style  # Unselected colors

    def test_update_style_called_on_selection_change(
        self, qtbot: QtBot, selectable_widget: ThumbnailWidget
    ) -> None:
        """Test _update_style is called when selection changes."""
        # Mock _update_style to track calls
        original_update = selectable_widget._update_style
        call_count = 0

        def tracked_update():
            nonlocal call_count
            call_count += 1
            original_update()

        selectable_widget._update_style = tracked_update

        # Change selection
        selectable_widget.set_selected(True)
        _process_events()

        # _update_style should have been called
        assert call_count >= 1


class TestThumbnailWidgetBaseContextMenu:
    """Test ThumbnailWidgetBase context menu operations."""

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create test shot."""
        return Shot(
            "test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010"
        )

    @pytest.fixture
    def menu_widget(self, qtbot: QtBot, test_shot: Shot) -> ThumbnailWidget:
        """Create widget for context menu testing."""
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)
        widget.show()
        return widget

    def test_create_context_menu_returns_menu(
        self, menu_widget: ThumbnailWidget
    ) -> None:
        """Test _create_context_menu returns a QMenu."""
        menu = menu_widget._create_context_menu()

        assert isinstance(menu, QMenu)
        assert menu is not None

    def test_context_menu_has_open_folder_action(
        self, menu_widget: ThumbnailWidget
    ) -> None:
        """Test context menu includes 'Open Shot Folder' action."""
        menu = menu_widget._create_context_menu()
        actions = menu.actions()

        assert len(actions) > 0
        action_texts = [action.text() for action in actions]
        assert "Open Shot Folder" in action_texts

    def test_open_shot_folder_creates_worker(
        self, qtbot: QtBot, menu_widget: ThumbnailWidget
    ) -> None:
        """Test _open_shot_folder creates FolderOpenerWorker."""
        # Mock QThreadPool.globalInstance().start to capture worker
        started_workers = []

        def mock_start(worker):
            started_workers.append(worker)

        with patch(
            "thumbnail_widget_base.QThreadPool.globalInstance"
        ) as mock_pool_instance:
            mock_pool = MagicMock()
            mock_pool.start = mock_start
            mock_pool_instance.return_value = mock_pool

            # Call _open_shot_folder
            menu_widget._open_shot_folder()
            _process_events()

            # Should have started a FolderOpenerWorker
            assert len(started_workers) == 1
            assert isinstance(started_workers[0], FolderOpenerWorker)
            assert started_workers[0].folder_path == menu_widget.data.workspace_path

    def test_on_folder_open_error_logs_error(
        self, menu_widget: ThumbnailWidget
    ) -> None:
        """Test _on_folder_open_error logs error message."""
        error_msg = "Test error message"

        # Should not raise exception
        menu_widget._on_folder_open_error(error_msg)

    def test_on_folder_open_success_logs_success(
        self, menu_widget: ThumbnailWidget
    ) -> None:
        """Test _on_folder_open_success logs success."""
        # Should not raise exception
        menu_widget._on_folder_open_success()


class TestThumbnailWidgetBaseEdgeCases:
    """Test edge cases for ThumbnailWidgetBase."""

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create test shot."""
        return Shot(
            "test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010"
        )

    def test_widget_with_zero_size_thumbnail(
        self, qtbot: QtBot, test_shot: Shot
    ) -> None:
        """Test widget handles zero size gracefully."""
        widget = ThumbnailWidget(test_shot, 0)
        qtbot.addWidget(widget)

        # Widget should be created without crashing
        assert widget._thumbnail_size == 0
        assert widget.thumbnail_label.size().width() == 0

    def test_widget_calculate_height_consistency(
        self, qtbot: QtBot, test_shot: Shot
    ) -> None:
        """Test _calculate_widget_height returns consistent values."""
        widget = ThumbnailWidget(test_shot, 150)
        qtbot.addWidget(widget)

        height1 = widget._calculate_widget_height()
        height2 = widget._calculate_widget_height()

        # Should return same height on repeated calls
        assert height1 == height2
        # Height should be reasonable
        assert height1 > widget._thumbnail_size

    def test_set_placeholder_creates_valid_pixmap(
        self, qtbot: QtBot, test_shot: Shot
    ) -> None:
        """Test _set_placeholder creates a valid pixmap."""
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)

        # Call _set_placeholder explicitly
        widget._set_placeholder()
        _process_events()

        # Should have a valid pixmap
        pixmap = widget.thumbnail_label.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()
        assert pixmap.size().width() == widget._thumbnail_size

    def test_widget_handles_rapid_size_changes(
        self, qtbot: QtBot, test_shot: Shot
    ) -> None:
        """Test widget handles rapid size changes without errors."""
        widget = ThumbnailWidget(test_shot, 100)
        qtbot.addWidget(widget)

        # Rapidly change size
        for size in [120, 140, 160, 180, 200, 150, 100]:
            widget.set_size(size)
            _process_events()

        # Widget should still be functional
        assert widget._thumbnail_size == 100
        assert widget is not None

    def test_widget_handles_selection_toggle_rapidly(
        self, qtbot: QtBot, test_shot: Shot
    ) -> None:
        """Test widget handles rapid selection toggles."""
        widget = ThumbnailWidget(test_shot, Config.DEFAULT_THUMBNAIL_SIZE)
        qtbot.addWidget(widget)

        # Rapidly toggle selection
        for i in range(20):
            widget.set_selected(i % 2 == 0)
            _process_events()

        # Widget should still be functional
        assert isinstance(widget._selected, bool)
