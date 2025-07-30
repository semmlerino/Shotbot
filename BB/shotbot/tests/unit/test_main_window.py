"""Unit tests for main_window.py with focus on new features"""

import json
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QTimer

from main_window import MainWindow

# Using qapp fixture from conftest.py


class TestMainWindowNewFeatures:
    """Test MainWindow new features like caching and background refresh."""

    @pytest.fixture
    def main_window(self, qapp, monkeypatch):
        """Create MainWindow instance."""
        # Mock the timer to prevent actual background refresh
        monkeypatch.setattr(QTimer, "start", Mock())

        # Create window
        window = MainWindow()
        yield window
        window.close()

    def test_shot_info_panel_integration(self, main_window):
        """Test shot info panel is properly integrated."""
        assert hasattr(main_window, "shot_info_panel")
        assert main_window.shot_info_panel is not None
        assert main_window.shot_info_panel.parent() is not None

    def test_window_title_update(self, main_window):
        """Test window title updates when shot is selected."""
        from shot_model import Shot

        shot = Shot(
            show="testshow",
            sequence="101_ABC",
            shot="0010",
            workspace_path="/shows/testshow/shots/101_ABC/101_ABC_0010",
        )

        # Trigger shot selection
        main_window._on_shot_selected(shot)

        # Check window title
        expected_title = "ShotBot - 101_ABC_0010 (testshow)"
        assert main_window.windowTitle() == expected_title

    def test_shot_info_panel_update(self, main_window):
        """Test shot info panel updates when shot is selected."""
        from shot_model import Shot

        shot = Shot(
            show="testshow",
            sequence="101_ABC",
            shot="0010",
            workspace_path="/shows/testshow/shots/101_ABC/101_ABC_0010",
        )

        # Mock set_shot method
        main_window.shot_info_panel.set_shot = Mock()

        # Trigger shot selection
        main_window._on_shot_selected(shot)

        # Verify panel was updated
        main_window.shot_info_panel.set_shot.assert_called_once_with(shot)

    def test_background_refresh_timer_setup(self, main_window):
        """Test background refresh timer is set up."""
        assert hasattr(main_window, "refresh_timer")
        assert isinstance(main_window.refresh_timer, QTimer)

        # Timer should be connected to _background_refresh
        # Note: We can't easily test the connection, but we can test the method exists
        assert hasattr(main_window, "_background_refresh")
        assert callable(main_window._background_refresh)

    def test_initial_load_from_cache(self):
        """Test initial load shows cached data immediately."""
        # Import Shot and necessary mocks
        from unittest.mock import MagicMock

        from shot_model import Shot

        # Create a minimal test version of MainWindow
        window = MagicMock(spec=MainWindow)

        # Set up necessary attributes
        window.shot_model = MagicMock()
        window.shot_model.shots = [
            Shot(
                "testshow",
                "101_ABC",
                "0010",
                "/shows/testshow/shots/101_ABC/101_ABC_0010",
            ),
            Shot(
                "testshow",
                "101_ABC",
                "0020",
                "/shows/testshow/shots/101_ABC/101_ABC_0020",
            ),
        ]
        window.shot_model.find_shot_by_name = Mock(return_value=None)

        window.shot_grid = MagicMock()
        window.shot_grid.refresh_shots = Mock()
        window.shot_grid.select_shot = Mock()

        window.status_bar = MagicMock()
        window._update_status = Mock()

        # Call the actual method we want to test from MainWindow
        MainWindow._initial_load(window)

        # Should refresh grid with cached data
        window.shot_grid.refresh_shots.assert_called_once()

        # Should update status with cache info
        window._update_status.assert_called_with("Loaded 2 shots (from cache)")

    def test_background_refresh_no_changes(self, main_window):
        """Test background refresh when no changes detected."""
        # Mock refresh_shots to return no changes
        main_window.shot_model.refresh_shots = Mock(return_value=(True, False))
        main_window.shot_grid.refresh_shots = Mock()

        # Run background refresh
        main_window._background_refresh()

        # Grid should NOT be refreshed
        main_window.shot_grid.refresh_shots.assert_not_called()

    def test_background_refresh_with_changes(self, main_window):
        """Test background refresh when changes are detected."""
        from shot_model import Shot

        # Mock refresh_shots to return changes
        main_window.shot_model.refresh_shots = Mock(return_value=(True, True))
        main_window.shot_grid.refresh_shots = Mock()
        main_window.shot_grid.select_shot = Mock()

        # Set a current selection
        main_window._last_selected_shot_name = "101_ABC_0010"
        shot = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )
        main_window.shot_model.find_shot_by_name = Mock(return_value=shot)

        # Run background refresh
        main_window._background_refresh()

        # Grid should be refreshed
        main_window.shot_grid.refresh_shots.assert_called_once()

        # Status should indicate update
        assert "new changes" in main_window.status_bar.currentMessage()

        # Selection should be restored
        main_window.shot_model.find_shot_by_name.assert_called_with("101_ABC_0010")
        main_window.shot_grid.select_shot.assert_called_once()

    def test_refresh_shots_with_changes(self, main_window):
        """Test manual refresh always updates grid."""
        from shot_model import Shot

        # Mock refresh to show changes vs no changes
        main_window.shot_model.refresh_shots = Mock(return_value=(True, True))
        main_window.shot_model.shots = [
            Shot(
                "testshow",
                "101_ABC",
                "0010",
                "/shows/testshow/shots/101_ABC/101_ABC_0010",
            ),
            Shot(
                "testshow",
                "101_ABC",
                "0020",
                "/shows/testshow/shots/101_ABC/101_ABC_0020",
            ),
        ]
        main_window.shot_grid.refresh_shots = Mock()
        main_window.shot_grid.select_shot = Mock()

        # Ensure no previous selection to avoid selection restoration
        if hasattr(main_window, "_last_selected_shot_name"):
            delattr(main_window, "_last_selected_shot_name")

        # First refresh with changes
        main_window._refresh_shots()

        assert "Loaded 2 shots" in main_window.status_bar.currentMessage()
        main_window.shot_grid.refresh_shots.assert_called_once()

        # Reset mocks
        main_window.shot_grid.refresh_shots.reset_mock()
        main_window.shot_model.refresh_shots.return_value = (True, False)

        # Second refresh with no changes
        main_window._refresh_shots()

        # Should say "no changes" when has_changes is False
        assert "2 shots (no changes)" in main_window.status_bar.currentMessage()
        # Grid should NOT refresh when no changes
        main_window.shot_grid.refresh_shots.assert_not_called()

    @patch("main_window.open")
    @patch("main_window.json.dump")
    def test_save_settings_qbytearray_conversion(
        self, mock_json_dump, mock_open, main_window
    ):
        """Test QByteArray conversion in save settings."""
        # Mock file operations
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        # Trigger save
        main_window._save_settings()

        # Get the saved data
        mock_json_dump.assert_called_once()
        saved_data = mock_json_dump.call_args[0][0]

        # Check geometry and splitter are strings
        assert isinstance(saved_data["geometry"], str)
        assert isinstance(saved_data["splitter"], str)
        assert isinstance(saved_data["thumbnail_size"], int)

        # Check they look like hex strings
        assert all(c in "0123456789abcdef" for c in saved_data["geometry"])
        assert all(c in "0123456789abcdef" for c in saved_data["splitter"])

    def test_load_settings_with_cached_shot(self, main_window, tmp_path, monkeypatch):
        """Test loading settings restores last selected shot."""
        # Create settings file
        settings_file = tmp_path / ".shotbot" / "settings.json"
        settings_file.parent.mkdir(parents=True)

        settings = {
            "geometry": "0123456789abcdef",
            "splitter": "fedcba9876543210",
            "thumbnail_size": 250,
            "last_shot": "101_ABC_0010",
        }

        with open(settings_file, "w") as f:
            json.dump(settings, f)

        # Mock Config.SETTINGS_FILE
        from config import Config

        monkeypatch.setattr(Config, "SETTINGS_FILE", settings_file)

        # Mock restoreGeometry and restoreState
        main_window.restoreGeometry = Mock()
        main_window.splitter.restoreState = Mock()
        main_window.shot_grid.size_slider.setValue = Mock()

        # Load settings
        main_window._load_settings()

        # Check last shot name was loaded
        assert hasattr(main_window, "_last_selected_shot_name")
        assert main_window._last_selected_shot_name == "101_ABC_0010"

        # Check slider was set
        main_window.shot_grid.size_slider.setValue.assert_called_with(250)

    def test_on_shot_double_clicked(self, main_window):
        """Test double-clicking a shot launches default app."""

        from config import Config
        from shot_model import Shot

        shot = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )

        # Mock _launch_app to avoid actual app launching
        main_window._launch_app = Mock()

        # Trigger double click
        main_window._on_shot_double_clicked(shot)

        # Should launch default app
        main_window._launch_app.assert_called_once_with(Config.DEFAULT_APP)

    def test_launch_app_success(self, main_window):
        """Test app launch success path."""
        # Mock command launcher to return success
        main_window.command_launcher.launch_app = Mock(return_value=True)

        # Launch app
        main_window._launch_app("nuke")

        # Should show success message
        assert "Launched nuke" in main_window.status_bar.currentMessage()

    def test_launch_app_failure(self, main_window):
        """Test app launch failure path."""
        # Mock command launcher to return failure
        main_window.command_launcher.launch_app = Mock(return_value=False)

        # Launch app
        main_window._launch_app("nuke")

        # Should show failure message
        assert "Failed to launch nuke" in main_window.status_bar.currentMessage()

    def test_increase_thumbnail_size(self, main_window):
        """Test increasing thumbnail size."""
        from config import Config

        # Set initial size
        initial_size = 200
        main_window.shot_grid.size_slider.setValue(initial_size)
        main_window.shot_grid.size_slider.value = Mock(return_value=initial_size)
        main_window.shot_grid.size_slider.setValue = Mock()

        # Increase size
        main_window._increase_thumbnail_size()

        # Should increase by 20, but not exceed max
        expected_size = min(initial_size + 20, Config.MAX_THUMBNAIL_SIZE)
        main_window.shot_grid.size_slider.setValue.assert_called_with(expected_size)

    def test_increase_thumbnail_size_at_max(self, main_window):
        """Test increasing thumbnail size when already at maximum."""
        from config import Config

        # Set to maximum size
        main_window.shot_grid.size_slider.value = Mock(
            return_value=Config.MAX_THUMBNAIL_SIZE
        )
        main_window.shot_grid.size_slider.setValue = Mock()

        # Try to increase
        main_window._increase_thumbnail_size()

        # Should stay at max
        main_window.shot_grid.size_slider.setValue.assert_called_with(
            Config.MAX_THUMBNAIL_SIZE
        )

    def test_decrease_thumbnail_size(self, main_window):
        """Test decreasing thumbnail size."""
        from config import Config

        # Set initial size
        initial_size = 200
        main_window.shot_grid.size_slider.value = Mock(return_value=initial_size)
        main_window.shot_grid.size_slider.setValue = Mock()

        # Decrease size
        main_window._decrease_thumbnail_size()

        # Should decrease by 20, but not go below min
        expected_size = max(initial_size - 20, Config.MIN_THUMBNAIL_SIZE)
        main_window.shot_grid.size_slider.setValue.assert_called_with(expected_size)

    def test_decrease_thumbnail_size_at_min(self, main_window):
        """Test decreasing thumbnail size when already at minimum."""
        from config import Config

        # Set to minimum size
        main_window.shot_grid.size_slider.value = Mock(
            return_value=Config.MIN_THUMBNAIL_SIZE
        )
        main_window.shot_grid.size_slider.setValue = Mock()

        # Try to decrease
        main_window._decrease_thumbnail_size()

        # Should stay at min
        main_window.shot_grid.size_slider.setValue.assert_called_with(
            Config.MIN_THUMBNAIL_SIZE
        )

    def test_initial_load_with_last_shot_restoration(self, main_window):
        """Test initial load restores last selected shot."""
        from shot_model import Shot

        # Set up shots in model
        shot1 = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )
        shot2 = Shot(
            "testshow", "101_ABC", "0020", "/shows/testshow/shots/101_ABC/101_ABC_0020"
        )
        main_window.shot_model.shots = [shot1, shot2]

        # Set last selected shot
        main_window._last_selected_shot_name = "101_ABC_0020"
        main_window.shot_model.find_shot_by_name = Mock(return_value=shot2)
        main_window.shot_grid.select_shot = Mock()
        main_window.shot_grid.refresh_shots = Mock()

        # Run initial load
        main_window._initial_load()

        # Should restore selection
        main_window.shot_model.find_shot_by_name.assert_called_with("101_ABC_0020")
        main_window.shot_grid.select_shot.assert_called_with(shot2)

    def test_refresh_shots_failure_shows_warning(self, main_window):
        """Test refresh shots failure shows warning dialog."""
        from unittest.mock import patch

        # Mock refresh to fail
        main_window.shot_model.refresh_shots = Mock(return_value=(False, False))

        # Mock message box
        with patch("main_window.QMessageBox.warning") as mock_warning:
            main_window._refresh_shots()

            # Should show warning dialog
            mock_warning.assert_called_once()
            args = mock_warning.call_args[0]
            assert "Failed to load shots" in args[2]  # Message text

        # Should update status
        assert "Failed to load shots" in main_window.status_bar.currentMessage()

    def test_refresh_shots_with_last_shot_restoration(self, main_window):
        """Test refresh shots restores last selected shot on success."""
        from shot_model import Shot

        # Mock successful refresh
        main_window.shot_model.refresh_shots = Mock(return_value=(True, True))
        main_window.shot_model.shots = [
            Shot(
                "testshow",
                "101_ABC",
                "0010",
                "/shows/testshow/shots/101_ABC/101_ABC_0010",
            )
        ]

        # Set up last selected shot
        main_window._last_selected_shot_name = "101_ABC_0010"
        shot = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )
        main_window.shot_model.find_shot_by_name = Mock(return_value=shot)
        main_window.shot_grid.select_shot = Mock()
        main_window.shot_grid.refresh_shots = Mock()

        # Run refresh
        main_window._refresh_shots()

        # Should restore selection
        main_window.shot_model.find_shot_by_name.assert_called_with("101_ABC_0010")
        main_window.shot_grid.select_shot.assert_called_with(shot)

    @patch("main_window.QMessageBox.about")
    def test_show_about_dialog(self, mock_about, main_window):
        """Test showing about dialog."""
        from config import Config

        # Trigger about dialog
        main_window._show_about()

        # Should show about dialog
        mock_about.assert_called_once()
        args = mock_about.call_args[0]
        assert f"About {Config.APP_NAME}" in args[1]  # Title
        assert Config.APP_VERSION in args[2]  # Message

    def test_load_settings_exception_handling(self, main_window, tmp_path, monkeypatch):
        """Test load settings handles exceptions gracefully."""

        from config import Config

        # Create invalid settings file
        settings_file = tmp_path / ".shotbot" / "settings.json"
        settings_file.parent.mkdir(parents=True)

        # Write invalid JSON
        with open(settings_file, "w") as f:
            f.write("invalid json content")

        # Mock Config.SETTINGS_FILE
        monkeypatch.setattr(Config, "SETTINGS_FILE", settings_file)

        # Mock print to capture error message
        with patch("builtins.print") as mock_print:
            # Should not raise exception
            main_window._load_settings()

            # Should print error message
            mock_print.assert_called_once()
            assert "Error loading settings" in str(mock_print.call_args[0][0])

    @patch("main_window.open", side_effect=OSError("Permission denied"))
    def test_save_settings_exception_handling(self, mock_open, main_window):
        """Test save settings handles exceptions gracefully."""
        # Mock print to capture error message
        with patch("builtins.print") as mock_print:
            # Should not raise exception
            main_window._save_settings()

            # Should print error message
            mock_print.assert_called_once()
            assert "Error saving settings" in str(mock_print.call_args[0][0])

    def test_undistortion_checkbox_initialization(self, main_window):
        """Test undistortion checkbox is properly initialized."""
        # Check checkbox exists
        assert hasattr(main_window, "undistortion_checkbox")

        # Check initial state (may be either checked or unchecked depending on settings)
        assert isinstance(main_window.undistortion_checkbox.isChecked(), bool)

        # Check tooltip
        assert "undistortion" in main_window.undistortion_checkbox.toolTip().lower()

    def test_launch_app_with_undistortion_checkbox(self, main_window):
        """Test launch app passes undistortion checkbox state."""
        from shot_model import Shot

        # Set current shot
        shot = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )
        main_window.command_launcher.set_current_shot(shot)

        # Mock launch_app
        main_window.command_launcher.launch_app = Mock(return_value=True)

        # Test with checkbox unchecked (both checkboxes)
        main_window.undistortion_checkbox.setChecked(False)
        main_window.raw_plate_checkbox.setChecked(False)
        main_window._launch_app("nuke")
        main_window.command_launcher.launch_app.assert_called_with("nuke", False, False)

        # Test with undistortion checkbox checked
        main_window.undistortion_checkbox.setChecked(True)
        main_window.raw_plate_checkbox.setChecked(False)
        main_window._launch_app("nuke")
        main_window.command_launcher.launch_app.assert_called_with("nuke", True, False)

        # Test with non-Nuke app (should still pass state)
        main_window._launch_app("maya")
        main_window.command_launcher.launch_app.assert_called_with("maya", False, False)

    def test_undistortion_checkbox_settings_save(self, main_window, tmp_path):
        """Test undistortion checkbox state is saved to settings."""
        from config import Config

        # Override settings path
        Config.SETTINGS_FILE = tmp_path / "test_settings.json"

        # Set checkbox state
        main_window.undistortion_checkbox.setChecked(True)

        # Save settings
        main_window._save_settings()

        # Load settings and check
        import json

        with open(Config.SETTINGS_FILE) as f:
            settings = json.load(f)

        assert "include_undistortion" in settings
        assert settings["include_undistortion"] is True

    def test_undistortion_checkbox_settings_load(self, main_window, tmp_path):
        """Test undistortion checkbox state is loaded from settings."""
        from config import Config

        # Override settings path
        Config.SETTINGS_FILE = tmp_path / "test_settings.json"

        # Create settings with undistortion enabled
        import json

        settings = {"include_undistortion": True}
        Config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(Config.SETTINGS_FILE, "w") as f:
            json.dump(settings, f)

        # Load settings
        main_window._load_settings()

        # Check checkbox state
        assert main_window.undistortion_checkbox.isChecked() is True

    def test_raw_plate_checkbox_initialization(self, main_window):
        """Test raw plate checkbox is properly initialized."""
        # Check checkbox exists
        assert hasattr(main_window, "raw_plate_checkbox")

        # Check initial state
        assert isinstance(main_window.raw_plate_checkbox.isChecked(), bool)

        # Check tooltip
        assert "raw plate" in main_window.raw_plate_checkbox.toolTip().lower()

    def test_launch_app_with_raw_plate_checkbox(self, main_window):
        """Test launch app passes raw plate checkbox state."""
        from shot_model import Shot

        # Set current shot
        shot = Shot(
            "testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"
        )
        main_window.command_launcher.set_current_shot(shot)

        # Mock launch_app
        main_window.command_launcher.launch_app = Mock(return_value=True)

        # Test with both checkboxes unchecked
        main_window.undistortion_checkbox.setChecked(False)
        main_window.raw_plate_checkbox.setChecked(False)
        main_window._launch_app("nuke")
        main_window.command_launcher.launch_app.assert_called_with("nuke", False, False)

        # Test with only raw plate checked
        main_window.undistortion_checkbox.setChecked(False)
        main_window.raw_plate_checkbox.setChecked(True)
        main_window._launch_app("nuke")
        main_window.command_launcher.launch_app.assert_called_with("nuke", False, True)

        # Test with both checkboxes checked
        main_window.undistortion_checkbox.setChecked(True)
        main_window.raw_plate_checkbox.setChecked(True)
        main_window._launch_app("nuke")
        main_window.command_launcher.launch_app.assert_called_with("nuke", True, True)

    def test_raw_plate_checkbox_settings_save(self, main_window, tmp_path):
        """Test raw plate checkbox state is saved to settings."""
        from config import Config

        # Override settings path
        Config.SETTINGS_FILE = tmp_path / "test_settings.json"

        # Set checkbox state
        main_window.raw_plate_checkbox.setChecked(True)

        # Save settings
        main_window._save_settings()

        # Load settings and check
        import json

        with open(Config.SETTINGS_FILE) as f:
            settings = json.load(f)

        assert "include_raw_plate" in settings
        assert settings["include_raw_plate"] is True

    def test_raw_plate_checkbox_settings_load(self, main_window, tmp_path):
        """Test raw plate checkbox state is loaded from settings."""
        from config import Config

        # Override settings path
        Config.SETTINGS_FILE = tmp_path / "test_settings.json"

        # Create settings with raw plate enabled
        import json

        settings = {"include_raw_plate": True}
        Config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(Config.SETTINGS_FILE, "w") as f:
            json.dump(settings, f)

        # Load settings
        main_window._load_settings()

        # Check checkbox state
        assert main_window.raw_plate_checkbox.isChecked() is True
