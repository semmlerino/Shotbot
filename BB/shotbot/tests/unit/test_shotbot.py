"""Unit tests for shotbot.py - Application initialization and entry point."""

import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

# Mock the modules before importing shotbot
sys.modules["main_window"] = MagicMock()
sys.modules["config"] = MagicMock()


class TestShotBotApplication(unittest.TestCase):
    """Test cases for the main ShotBot application initialization."""

    def setUp(self):
        """Set up test fixtures."""
        # Ensure no QApplication exists before each test
        app = QApplication.instance()
        if app:
            app.quit()
            del app

    def tearDown(self):
        """Clean up after tests."""
        # Clean up any QApplication instance
        app = QApplication.instance()
        if app:
            app.quit()
            del app

    @patch("shotbot.QApplication")
    @patch("shotbot.MainWindow")
    @patch("shotbot.logging")
    def test_application_initialization(
        self, mock_logging, mock_main_window, mock_qapp
    ):
        """Test that the application initializes correctly."""
        # Setup mocks
        mock_app_instance = MagicMock()
        mock_qapp.return_value = mock_app_instance
        mock_qapp.instance.return_value = None  # No existing instance

        mock_window_instance = MagicMock()
        mock_main_window.return_value = mock_window_instance

        # Import and run main
        from shotbot import main

        with patch("sys.exit"):
            main()

            # Verify QApplication was created
            mock_qapp.assert_called_once()

            # Verify MainWindow was created and shown
            mock_main_window.assert_called_once()
            mock_window_instance.show.assert_called_once()

            # Verify app.exec() was called
            mock_app_instance.exec.assert_called_once()

    @patch("shotbot.QApplication")
    def test_existing_qapplication_reuse(self, mock_qapp):
        """Test that existing QApplication instance is reused."""
        # Setup mock with existing instance
        existing_app = MagicMock()
        mock_qapp.instance.return_value = existing_app

        from shotbot import main

        with patch("shotbot.MainWindow"):
            with patch("sys.exit"):
                main()

                # Verify QApplication constructor was NOT called
                mock_qapp.assert_not_called()

    @patch("shotbot.os.environ")
    @patch("shotbot.logging")
    def test_debug_mode_initialization(self, mock_logging, mock_environ):
        """Test that debug mode is properly initialized from environment."""
        # Set debug environment variable
        mock_environ.get.return_value = "1"

        # Import module to trigger debug setup
        import importlib

        import shotbot

        importlib.reload(shotbot)

        # Verify debug logging was configured
        mock_logging.basicConfig.assert_called()
        call_kwargs = mock_logging.basicConfig.call_args[1]
        assert call_kwargs["level"] == mock_logging.DEBUG

    @patch("shotbot.QApplication")
    @patch("shotbot.MainWindow")
    def test_application_name_and_version(self, mock_main_window, mock_qapp):
        """Test that application name and version are set correctly."""
        mock_app_instance = MagicMock()
        mock_qapp.return_value = mock_app_instance
        mock_qapp.instance.return_value = None

        from shotbot import main

        with patch("sys.exit"):
            main()

            # Verify application properties were set
            mock_app_instance.setApplicationName.assert_called_with("ShotBot")
            mock_app_instance.setOrganizationName.assert_called()

    @patch("shotbot.QApplication")
    @patch("shotbot.MainWindow")
    def test_window_exception_handling(self, mock_main_window, mock_qapp):
        """Test that exceptions during window creation are handled."""
        mock_app_instance = MagicMock()
        mock_qapp.return_value = mock_app_instance
        mock_qapp.instance.return_value = None

        # Make MainWindow raise an exception
        mock_main_window.side_effect = Exception("Window creation failed")

        from shotbot import main

        with patch("sys.exit") as mock_exit:
            with patch("shotbot.logging.error") as mock_log_error:
                main()

                # Verify error was logged
                mock_log_error.assert_called()

                # Verify application still tries to exit gracefully
                mock_exit.assert_called()


class TestShotBotIntegration(unittest.TestCase):
    """Integration tests for the ShotBot application."""

    @pytest.mark.skipif(not hasattr(pytest, "qt"), reason="Requires pytest-qt")
    def test_real_application_startup(self, qtbot):
        """Test real application startup with Qt."""
        from main_window import MainWindow

        # Create application
        QApplication.instance() or QApplication(sys.argv)

        # Create main window
        window = MainWindow()
        qtbot.addWidget(window)

        # Verify window is created
        assert window is not None
        assert window.windowTitle() == "ShotBot"

        # Test window can be shown
        window.show()
        qtbot.wait(100)  # Wait for window to be shown

        assert window.isVisible()

    def test_module_imports(self):
        """Test that all required modules can be imported."""
        try:
            import shotbot
            from config import Config
            from main_window import MainWindow

            # Verify key attributes exist
            assert hasattr(shotbot, "main")
            assert hasattr(MainWindow, "show")
            assert hasattr(Config, "APP_NAME")

        except ImportError as e:
            pytest.fail(f"Failed to import required module: {e}")


class TestCommandLineArguments(unittest.TestCase):
    """Test command-line argument handling."""

    @patch("shotbot.QApplication")
    @patch("shotbot.MainWindow")
    def test_command_line_args_passed_to_qapp(self, mock_main_window, mock_qapp):
        """Test that command-line arguments are passed to QApplication."""
        mock_app_instance = MagicMock()
        mock_qapp.return_value = mock_app_instance
        mock_qapp.instance.return_value = None

        test_args = ["shotbot.py", "--test-arg", "value"]

        with patch("sys.argv", test_args):
            from shotbot import main

            with patch("sys.exit"):
                main()

                # Verify QApplication received the arguments
                mock_qapp.assert_called_once_with(test_args)

    @patch("shotbot.os.environ")
    def test_environment_variables(self, mock_environ):
        """Test that environment variables are properly read."""
        # Set up environment variables
        mock_environ.get.side_effect = lambda key, default=None: {
            "SHOTBOT_DEBUG": "1",
            "SHOTBOT_CACHE_DIR": "/custom/cache",
            "HOME": "/home/testuser",
        }.get(key, default)

        import importlib

        import shotbot

        importlib.reload(shotbot)

        # Verify environment variables were checked
        mock_environ.get.assert_any_call("SHOTBOT_DEBUG")


if __name__ == "__main__":
    unittest.main()
