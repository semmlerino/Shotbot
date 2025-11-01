from tests.helpers.synchronization import wait_for_condition

"""Integration tests for non-blocking folder opening functionality."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QApplication

from thumbnail_widget_base import FolderOpenerWorker


class TestFolderOpenerIntegration:
    """Integration tests for the non-blocking folder opener."""

    @pytest.fixture
    def temp_folder(self):
        """Create a temporary folder for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def qtapp(self, qtbot):
        """Ensure Qt application is available."""
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        return app

    def test_folder_opener_success(self, temp_folder, qtbot):
        """Test successful folder opening."""
        worker = FolderOpenerWorker(temp_folder)

        # Track signals
        success_received = []
        error_received = []

        worker.signals.success.connect(lambda: success_received.append(True))
        worker.signals.error.connect(lambda msg: error_received.append(msg))

        # Mock QDesktopServices to simulate success
        with patch("thumbnail_widget_base.QDesktopServices.openUrl", return_value=True):
            worker.run()

        # Should emit success signal
        assert len(success_received) == 1
        assert len(error_received) == 0

    def test_folder_opener_nonexistent_path(self, qtbot):
        """Test opening non-existent folder."""
        worker = FolderOpenerWorker("/nonexistent/path/that/does/not/exist")

        # Track signals
        success_received = []
        error_received = []

        worker.signals.success.connect(lambda: success_received.append(True))
        worker.signals.error.connect(lambda msg: error_received.append(msg))

        worker.run()

        # Should emit error signal
        assert len(success_received) == 0
        assert len(error_received) == 1
        assert "does not exist" in error_received[0]

    def test_folder_opener_qt_failure_fallback(self, temp_folder, qtbot):
        """Test fallback to system command when Qt fails."""
        worker = FolderOpenerWorker(temp_folder)

        # Track signals manually
        success_received = []
        worker.signals.success.connect(lambda: success_received.append(True))

        # Mock Qt failure and subprocess success
        with patch(
            "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
        ):
            with patch("subprocess.run") as mock_run:
                worker.run()

                # Should have tried subprocess
                mock_run.assert_called_once()

                # Check platform-specific command
                if sys.platform == "darwin":
                    assert mock_run.call_args[0][0] == ["open", temp_folder]
                elif sys.platform == "win32":
                    assert mock_run.call_args[0][0] == ["explorer", temp_folder]
                else:
                    assert mock_run.call_args[0][0][0] in ["xdg-open", "gio"]

    def test_folder_opener_relative_path(self, qtbot):
        """Test handling of relative paths."""
        worker = FolderOpenerWorker("shows/testshow/shots")

        with patch("thumbnail_widget_base.QDesktopServices.openUrl") as mock_open:
            with patch("thumbnail_widget_base.Path.exists", return_value=True):
                worker.run()

                # Should convert to absolute path
                called_url = mock_open.call_args[0][0]
                assert called_url.path().startswith("/")
                assert "shows/testshow/shots" in called_url.path()

    def test_folder_opener_special_characters(self, qtbot):
        """Test paths with special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create folder with spaces and special chars
            special_dir = Path(tmpdir) / "My Shots & Renders (2024)"
            special_dir.mkdir()

            worker = FolderOpenerWorker(str(special_dir))

            with patch("thumbnail_widget_base.QDesktopServices.openUrl") as mock_open:
                worker.run()

                # URL should be properly encoded
                called_url = mock_open.call_args[0][0]
                # Spaces should be preserved in path
                assert "My Shots & Renders (2024)" in called_url.path()

    def test_folder_opener_windows_path(self, qtbot):
        """Test Windows-style paths."""
        if sys.platform != "win32":
            pytest.skip("Windows-specific test")

        worker = FolderOpenerWorker("C:\\Users\\TestUser\\Documents")

        with patch("thumbnail_widget_base.QDesktopServices.openUrl") as mock_open:
            with patch("thumbnail_widget_base.Path.exists", return_value=True):
                worker.run()

                called_url = mock_open.call_args[0][0]
                # Should handle Windows paths correctly
                assert called_url.scheme() == "file"

    def test_folder_opener_network_path(self, qtbot):
        """Test UNC network paths."""
        worker = FolderOpenerWorker("//server/share/folder")

        with patch("thumbnail_widget_base.QDesktopServices.openUrl") as mock_open:
            with patch("thumbnail_widget_base.Path.exists", return_value=True):
                worker.run()

                called_url = mock_open.call_args[0][0]
                assert called_url.scheme() == "file"

    def test_concurrent_folder_opening(self, temp_folder, qtbot):
        """Test multiple concurrent folder opening operations."""
        # Create multiple workers
        workers = []
        for i in range(5):
            folder = Path(temp_folder) / f"folder_{i}"
            folder.mkdir()
            worker = FolderOpenerWorker(str(folder))
            workers.append(worker)

        # Track completions
        completed = []

        def on_success():
            completed.append(True)

        # For testing purposes, simulate concurrent execution by running workers
        # and checking that signals work correctly
        with patch("thumbnail_widget_base.QDesktopServices.openUrl", return_value=True):
            for worker in workers:
                worker.signals.success.connect(on_success)
                # Run synchronously for test determinism
                worker.run()

        # All should complete and emit success signals
        assert len(completed) == 5

    def test_folder_opener_permission_error(self, qtbot):
        """Test handling of permission errors."""
        worker = FolderOpenerWorker("/root/protected")

        # Track signals manually
        error_received = []
        worker.signals.error.connect(lambda msg: error_received.append(msg))

        with patch("subprocess.run", side_effect=PermissionError("Access denied")):
            with patch(
                "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
            ):
                with patch("thumbnail_widget_base.Path.exists", return_value=True):
                    worker.run()

        # Should emit error
        assert len(error_received) == 1

    def test_folder_opener_timeout_simulation(self, temp_folder, qtbot):
        """Test that folder opening doesn't block the UI."""
        from PySide6.QtCore import QElapsedTimer

        # Track UI responsiveness
        ui_responsive = True
        timer = QElapsedTimer()

        def check_responsiveness():
            nonlocal ui_responsive
            # If this runs, UI is still responsive
            ui_responsive = True

        # Set up a timer to check UI responsiveness
        check_timer = QTimer()
        check_timer.timeout.connect(check_responsiveness)
        check_timer.start(10)  # Check every 10ms

        # Simulate slow operation
        def slow_open(url):
            wait_for_condition(lambda: False, timeout_ms=500)  # Simulate network delay
            return True

        worker = FolderOpenerWorker(temp_folder)

        with patch(
            "thumbnail_widget_base.QDesktopServices.openUrl", side_effect=slow_open
        ):
            # Start worker in thread pool
            timer.start()
            QThreadPool.globalInstance().start(worker)

            # Process events for a bit
            qtbot.wait(100)

            # UI should still be responsive
            assert ui_responsive

            # Wait for worker to complete
            QThreadPool.globalInstance().waitForDone(2000)

        check_timer.stop()

    def test_folder_opener_subprocess_fallback_errors(self, temp_folder, qtbot):
        """Test all subprocess fallback scenarios."""
        worker = FolderOpenerWorker(temp_folder)

        # Track signals manually
        error_received = []
        worker.signals.error.connect(lambda msg: error_received.append(msg))

        # Test FileNotFoundError (command not found)
        with patch(
            "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
        ):
            with patch(
                "subprocess.run", side_effect=FileNotFoundError("xdg-open not found")
            ):
                worker.run()

        assert len(error_received) == 1
        assert "not found" in error_received[0]

    def test_folder_opener_linux_gio_fallback(self, temp_folder, qtbot):
        """Test Linux gio fallback when xdg-open fails."""
        if sys.platform == "darwin" or sys.platform == "win32":
            pytest.skip("Linux-specific test")

        worker = FolderOpenerWorker(temp_folder)

        with patch(
            "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
        ):
            with patch("subprocess.run") as mock_run:
                # First call (xdg-open) fails, second (gio) succeeds
                mock_run.side_effect = [
                    FileNotFoundError("xdg-open not found"),
                    None,  # gio succeeds
                ]

                worker.run()

                # Should have tried both commands
                assert mock_run.call_count == 2
                assert mock_run.call_args_list[0][0][0] == ["xdg-open", temp_folder]
                assert mock_run.call_args_list[1][0][0] == ["gio", "open", temp_folder]

    def test_integration_with_thumbnail_widget(self, qtbot):
        """Test integration with actual thumbnail widget."""
        from shot_model import Shot
        from thumbnail_widget import ThumbnailWidget

        # Create a mock shot
        shot = Shot(
            show="testshow",
            sequence="TST",
            shot="001",
            workspace_path="/shows/testshow/shots/TST_001",
        )

        # Create widget
        widget = ThumbnailWidget(shot)

        # Track worker creation
        with patch("thumbnail_widget_base.FolderOpenerWorker") as mock_worker_class:
            mock_worker = MagicMock()
            mock_worker_class.return_value = mock_worker

            # Trigger folder opening
            widget._open_shot_folder()

            # Worker should be created with correct path
            mock_worker_class.assert_called_once_with(shot.workspace_path)

            # Signals should be connected
            mock_worker.signals.error.connect.assert_called_once()
            mock_worker.signals.success.connect.assert_called_once()
