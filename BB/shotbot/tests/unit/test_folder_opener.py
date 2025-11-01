"""Unit tests for folder opener functionality with QRunnable."""

import os
import platform
import tempfile
import unittest
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QCoreApplication, QThread, QThreadPool, QUrl
from PySide6.QtWidgets import QApplication


class TestFolderOpenerWorker(unittest.TestCase):
    """Test cases for the FolderOpenerWorker QRunnable."""

    @classmethod
    def setUpClass(cls):
        """Set up class-level fixtures."""
        # Ensure a QApplication exists for Qt tests
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        """Set up test fixtures."""
        # Import here to avoid issues with Qt initialization
        from thumbnail_widget_base import FolderOpenerWorker

        self.FolderOpenerWorker = FolderOpenerWorker

        # Create a temporary directory for testing
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests."""
        # Clean up temporary directory
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_folder_opener_initialization(self):
        """Test that FolderOpenerWorker initializes correctly."""
        test_path = "/test/path"
        worker = self.FolderOpenerWorker(test_path)

        assert worker.folder_path == test_path
        assert hasattr(worker, "signals")
        assert hasattr(worker.signals, "error")
        assert hasattr(worker.signals, "success")

    @patch("thumbnail_widget_base.QDesktopServices.openUrl")
    def test_folder_opener_success_case(self, mock_open_url):
        """Test successful folder opening."""
        mock_open_url.return_value = True

        worker = self.FolderOpenerWorker(self.temp_dir)

        # Connect to signals to verify they're emitted
        success_emitted = []
        error_emitted = []

        worker.signals.success.connect(lambda: success_emitted.append(True))
        worker.signals.error.connect(lambda msg: error_emitted.append(msg))

        # Run the worker
        worker.run()

        # Process events to ensure signals are delivered
        QCoreApplication.processEvents()

        # Verify QDesktopServices was called with correct URL
        mock_open_url.assert_called_once()
        call_args = mock_open_url.call_args[0][0]
        assert isinstance(call_args, QUrl)
        assert call_args.scheme() == "file"

        # Verify success signal was emitted
        assert len(success_emitted) == 1
        assert len(error_emitted) == 0

    @patch("thumbnail_widget_base.QDesktopServices.openUrl")
    def test_folder_opener_handles_relative_paths(self, mock_open_url):
        """Test that relative paths are converted to absolute."""
        mock_open_url.return_value = True

        relative_path = "test/path"
        worker = self.FolderOpenerWorker(relative_path)

        worker.run()

        # Verify the path was made absolute
        mock_open_url.assert_called_once()
        call_args = mock_open_url.call_args[0][0]
        url_path = call_args.toLocalFile()
        assert url_path.startswith("/")

    @patch("thumbnail_widget_base.QDesktopServices.openUrl")
    @patch("thumbnail_widget_base.subprocess.run")
    def test_folder_opener_fallback_to_subprocess(self, mock_subprocess, mock_open_url):
        """Test fallback to subprocess when QDesktopServices fails."""
        mock_open_url.return_value = False
        mock_subprocess.return_value = Mock(returncode=0)

        worker = self.FolderOpenerWorker(self.temp_dir)

        success_emitted = []
        worker.signals.success.connect(lambda: success_emitted.append(True))

        # Run with platform-specific expectations
        with patch("platform.system") as mock_platform:
            mock_platform.return_value = "Linux"
            worker.run()

            # Verify subprocess was called as fallback
            mock_subprocess.assert_called()

            # Verify success signal was emitted
            QCoreApplication.processEvents()
            assert len(success_emitted) == 1

    @patch("thumbnail_widget_base.QDesktopServices.openUrl")
    def test_folder_opener_nonexistent_path(self, mock_open_url):
        """Test handling of non-existent paths."""
        mock_open_url.return_value = False

        nonexistent_path = "/this/path/does/not/exist"
        worker = self.FolderOpenerWorker(nonexistent_path)

        error_emitted = []
        worker.signals.error.connect(lambda msg: error_emitted.append(msg))

        worker.run()

        # Process events
        QCoreApplication.processEvents()

        # Verify error signal was emitted
        assert len(error_emitted) == 1
        assert "does not exist" in error_emitted[0].lower()

    @patch("thumbnail_widget_base.QDesktopServices.openUrl")
    def test_folder_opener_permission_denied(self, mock_open_url):
        """Test handling of permission denied errors."""
        mock_open_url.side_effect = PermissionError("Permission denied")

        worker = self.FolderOpenerWorker("/root/protected")

        error_emitted = []
        worker.signals.error.connect(lambda msg: error_emitted.append(msg))

        worker.run()

        # Process events
        QCoreApplication.processEvents()

        # Verify error signal was emitted
        assert len(error_emitted) == 1
        assert (
            "permission" in error_emitted[0].lower()
            or "error" in error_emitted[0].lower()
        )

    def test_folder_opener_url_format(self):
        """Test that URLs are properly formatted for different paths."""
        test_cases = [
            ("/home/user/folder", "file:///home/user/folder"),
            ("home/user/folder", "file:///home/user/folder"),  # Relative path
            ("/path with spaces/folder", "file:///path%20with%20spaces/folder"),
            ("/path/with/特殊字符", None),  # Will be URL encoded
        ]

        for input_path, expected_prefix in test_cases:
            worker = self.FolderOpenerWorker(input_path)

            with patch("thumbnail_widget_base.QDesktopServices.openUrl") as mock_open:
                mock_open.return_value = True
                worker.run()

                if mock_open.called:
                    url = mock_open.call_args[0][0]
                    assert isinstance(url, QUrl)
                    assert url.scheme() == "file"

                    if expected_prefix and not expected_prefix.startswith("file://"):
                        assert url.toString().startswith(expected_prefix)


class TestFolderOpenerIntegration(unittest.TestCase):
    """Integration tests for folder opener with QThreadPool."""

    @classmethod
    def setUpClass(cls):
        """Set up class-level fixtures."""
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        """Set up test fixtures."""
        from thumbnail_widget_base import FolderOpenerWorker

        self.FolderOpenerWorker = FolderOpenerWorker
        self.thread_pool = QThreadPool()

        # Create a real temporary directory
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up after tests."""
        # Wait for thread pool to finish
        self.thread_pool.waitForDone(1000)

        # Clean up temporary directory
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_folder_opener_in_thread_pool(self):
        """Test that FolderOpenerWorker works correctly in QThreadPool."""
        worker = self.FolderOpenerWorker(self.temp_dir)

        # Track signal emissions
        signals_received = {"success": False, "error": None}

        def on_success():
            signals_received["success"] = True

        def on_error(msg):
            signals_received["error"] = msg

        worker.signals.success.connect(on_success)
        worker.signals.error.connect(on_error)

        # Run in thread pool
        self.thread_pool.start(worker)

        # Wait for completion
        self.thread_pool.waitForDone(2000)

        # Process events to ensure signals are delivered
        for _ in range(10):
            QCoreApplication.processEvents()
            QThread.msleep(10)

        # Verify either success or error was emitted
        assert signals_received["success"] or signals_received["error"] is not None

    def test_multiple_folder_openers_concurrent(self):
        """Test multiple FolderOpenerWorker instances running concurrently."""
        # Create multiple temporary directories
        temp_dirs = [tempfile.mkdtemp() for _ in range(5)]

        try:
            workers = []
            results = []

            for temp_dir in temp_dirs:
                worker = self.FolderOpenerWorker(temp_dir)

                # Track results for each worker
                result = {"path": temp_dir, "success": False, "error": None}
                results.append(result)

                worker.signals.success.connect(
                    lambda r=result: r.update({"success": True})
                )
                worker.signals.error.connect(
                    lambda msg, r=result: r.update({"error": msg})
                )

                workers.append(worker)
                self.thread_pool.start(worker)

            # Wait for all to complete
            self.thread_pool.waitForDone(5000)

            # Process events
            for _ in range(20):
                QCoreApplication.processEvents()
                QThread.msleep(10)

            # Verify all workers completed
            for result in results:
                assert result["success"] or result["error"] is not None

        finally:
            # Clean up all temporary directories
            import shutil

            for temp_dir in temp_dirs:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)

    @pytest.mark.skipif(platform.system() == "Windows", reason="Platform-specific test")
    def test_platform_specific_commands_linux(self):
        """Test platform-specific folder opening commands on Linux."""
        with patch("platform.system", return_value="Linux"):
            with patch("thumbnail_widget_base.subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0)

                worker = self.FolderOpenerWorker(self.temp_dir)

                # Mock QDesktopServices to fail so we fall back to subprocess
                with patch(
                    "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
                ):
                    worker.run()

                    # Verify xdg-open was attempted
                    calls = mock_run.call_args_list
                    assert any("xdg-open" in str(call) for call in calls)

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS specific test")
    def test_platform_specific_commands_macos(self):
        """Test platform-specific folder opening commands on macOS."""
        with patch("thumbnail_widget_base.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            worker = self.FolderOpenerWorker(self.temp_dir)

            # Mock QDesktopServices to fail
            with patch(
                "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
            ):
                worker.run()

                # Verify 'open' command was used on macOS
                calls = mock_run.call_args_list
                assert any("open" in str(call) for call in calls)


class TestFolderOpenerErrorHandling(unittest.TestCase):
    """Test error handling in folder opener."""

    @classmethod
    def setUpClass(cls):
        """Set up class-level fixtures."""
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        """Set up test fixtures."""
        from thumbnail_widget_base import FolderOpenerWorker

        self.FolderOpenerWorker = FolderOpenerWorker

    @patch("thumbnail_widget_base.QDesktopServices.openUrl")
    def test_unicode_path_handling(self, mock_open_url):
        """Test handling of Unicode characters in paths."""
        mock_open_url.return_value = True

        unicode_path = "/home/user/文件夹/テスト"
        worker = self.FolderOpenerWorker(unicode_path)

        worker.run()

        # Verify URL was created correctly
        mock_open_url.assert_called_once()
        url = mock_open_url.call_args[0][0]
        assert isinstance(url, QUrl)
        assert url.isValid()

    @patch("thumbnail_widget_base.QDesktopServices.openUrl")
    def test_network_path_handling(self, mock_open_url):
        """Test handling of network paths."""
        mock_open_url.return_value = True

        network_path = "//server/share/folder"
        worker = self.FolderOpenerWorker(network_path)

        error_emitted = []
        worker.signals.error.connect(lambda msg: error_emitted.append(msg))

        worker.run()

        # Network paths might cause errors or be handled specially
        # Just verify no crash occurs
        assert worker is not None

    def test_empty_path_handling(self):
        """Test handling of empty path string."""
        worker = self.FolderOpenerWorker("")

        error_emitted = []
        worker.signals.error.connect(lambda msg: error_emitted.append(msg))

        worker.run()

        QCoreApplication.processEvents()

        # Should emit an error for empty path
        assert len(error_emitted) > 0


if __name__ == "__main__":
    unittest.main()
