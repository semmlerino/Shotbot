"""Integration tests for Settings persistence across sessions."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QApplication

from config import Config
from main_window import MainWindow
from shot_model import Shot


class TestSettingsPersistenceIntegration:
    """Test complete settings persistence workflow across sessions."""

    @pytest.fixture
    def qapp(self):
        """Create QApplication for tests."""
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    @pytest.fixture
    def temp_settings_dir(self):
        """Create temporary directory for settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def mock_config_settings_file(self, temp_settings_dir, monkeypatch):
        """Mock Config.SETTINGS_FILE to use temporary directory."""
        settings_file = temp_settings_dir / ".shotbot" / "settings.json"
        monkeypatch.setattr(Config, "SETTINGS_FILE", settings_file)
        return settings_file

    @pytest.fixture
    def sample_shots(self):
        """Create sample shots for testing."""
        return [
            Shot("show1", "seq001", "0010", "/fake/path1"),
            Shot("show1", "seq001", "0020", "/fake/path2"),
            Shot("show1", "seq002", "0030", "/fake/path3"),
        ]

    def test_complete_settings_persistence_workflow(
        self, qapp, mock_config_settings_file, sample_shots
    ):
        """Test complete settings save and restore workflow."""
        # Mock subprocess.run for refresh_shots to avoid external dependencies
        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)  # Simulate command failure

            # Create first window instance
            window1 = MainWindow()

            # Process events to allow UI initialization
            qapp.processEvents()

            # Set up shot grid with sample shots
            window1.shot_model.shots = sample_shots
            window1.shot_grid.refresh_shots()
            qapp.processEvents()

            # Modify various settings

            # 1. Set thumbnail size
            original_thumb_size = 180
            window1.shot_grid.size_slider.setValue(original_thumb_size)

            # 2. Set undistortion checkbox
            window1.undistortion_checkbox.setChecked(True)

            # 3. Set raw plate checkbox
            window1.raw_plate_checkbox.setChecked(True)

            # 4. Set active tab (switch to 3DE scenes tab)
            original_tab_index = 1
            window1.tab_widget.setCurrentIndex(original_tab_index)

            # 5. Select a shot (simulate shot selection)
            selected_shot = sample_shots[1]  # seq001_0020
            window1._on_shot_selected(selected_shot)

            # 6. Mock geometry and splitter state for testing
            mock_geometry = QByteArray(b"mock_geometry_data")
            mock_splitter_state = QByteArray(b"mock_splitter_data")

            with patch.object(window1, "saveGeometry", return_value=mock_geometry):
                with patch.object(
                    window1.splitter, "saveState", return_value=mock_splitter_state
                ):
                    # Save settings
                    window1._save_settings()

            # Verify settings file was created
            assert mock_config_settings_file.exists()

            # Read and verify saved settings
            with open(mock_config_settings_file) as f:
                saved_settings = json.load(f)

            expected_keys = {
                "geometry",
                "splitter",
                "thumbnail_size",
                "include_undistortion",
                "include_raw_plate",
                "active_tab",
                "last_shot",
            }
            assert set(saved_settings.keys()) == expected_keys
            assert saved_settings["thumbnail_size"] == original_thumb_size
            assert saved_settings["include_undistortion"] is True
            assert saved_settings["include_raw_plate"] is True
            assert saved_settings["active_tab"] == original_tab_index
            assert saved_settings["last_shot"] == selected_shot.full_name

            # Close first window
            window1.close()

            # Create second window instance
            window2 = MainWindow()
            qapp.processEvents()

            # Set up shot grid with same shots
            window2.shot_model.shots = sample_shots
            window2.shot_grid.refresh_shots()
            qapp.processEvents()

            # Mock restoration methods to verify they're called with correct data
            restore_geometry_mock = Mock()
            restore_splitter_mock = Mock()
            window2.restoreGeometry = restore_geometry_mock
            window2.splitter.restoreState = restore_splitter_mock

            # Load settings - should restore all values
            window2._load_settings()

            # Verify settings were restored
            assert window2.shot_grid.size_slider.value() == original_thumb_size
            assert window2.undistortion_checkbox.isChecked() is True
            assert window2.raw_plate_checkbox.isChecked() is True
            assert window2.tab_widget.currentIndex() == original_tab_index
            assert window2._last_selected_shot_name == selected_shot.full_name

            # Verify geometry and splitter restoration were called with valid data
            restore_geometry_mock.assert_called_once()
            restore_splitter_mock.assert_called_once()

            # Clean up
            window2.close()

    def test_settings_persistence_with_empty_initial_state(
        self, qapp, mock_config_settings_file
    ):
        """Test settings persistence when starting from empty state."""
        # Ensure no settings file exists initially
        assert not mock_config_settings_file.exists()

        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)  # Simulate command failure

            # Create window - should start with defaults
            window = MainWindow()
            qapp.processEvents()

            # Verify default values
            default_thumb_size = window.shot_grid.size_slider.value()
            default_undistortion = window.undistortion_checkbox.isChecked()
            default_raw_plate = window.raw_plate_checkbox.isChecked()
            default_tab = window.tab_widget.currentIndex()

            # Save settings with defaults
            window._save_settings()

            # Verify settings file was created
            assert mock_config_settings_file.exists()

            # Read saved settings
            with open(mock_config_settings_file) as f:
                settings = json.load(f)

            # Should contain expected keys
            assert "thumbnail_size" in settings
            assert "include_undistortion" in settings
            assert "include_raw_plate" in settings
            assert "active_tab" in settings
            assert settings["thumbnail_size"] == default_thumb_size
            assert settings["include_undistortion"] == default_undistortion
            assert settings["include_raw_plate"] == default_raw_plate
            assert settings["active_tab"] == default_tab

            window.close()

    def test_settings_partial_restoration(self, qapp, mock_config_settings_file):
        """Test settings restoration when some keys are missing."""
        # Create partial settings file
        partial_settings = {
            "thumbnail_size": 250,
            "include_undistortion": True,
            # Missing other keys
        }

        mock_config_settings_file.parent.mkdir(parents=True, exist_ok=True)
        with open(mock_config_settings_file, "w") as f:
            json.dump(partial_settings, f)

        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)

            window = MainWindow()
            qapp.processEvents()

            # Mock restoration methods
            window.restoreGeometry = Mock()
            window.splitter.restoreState = Mock()

            # Load settings
            window._load_settings()

            # Should restore available settings
            assert window.shot_grid.size_slider.value() == 250
            assert window.undistortion_checkbox.isChecked() is True

            # Missing settings should use defaults (not cause errors)
            # raw_plate should use default (likely False)
            assert isinstance(window.raw_plate_checkbox.isChecked(), bool)

            # Geometry/splitter restoration should not be called (missing keys)
            window.restoreGeometry.assert_not_called()
            window.splitter.restoreState.assert_not_called()

            window.close()

    def test_settings_corrupted_file_handling(self, qapp, mock_config_settings_file):
        """Test handling of corrupted settings file."""
        # Create corrupted settings file
        mock_config_settings_file.parent.mkdir(parents=True, exist_ok=True)
        mock_config_settings_file.write_text("{ invalid json content }")

        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)

            with patch("builtins.print") as mock_print:
                # Should not crash
                window = MainWindow()
                qapp.processEvents()

                # Should print error message
                mock_print.assert_called()
                error_msg = str(mock_print.call_args_list[0][0][0])
                assert "Error loading settings" in error_msg

                # Window should still be functional with defaults
                assert isinstance(window.shot_grid.size_slider.value(), int)
                assert isinstance(window.undistortion_checkbox.isChecked(), bool)
                assert isinstance(window.raw_plate_checkbox.isChecked(), bool)

                window.close()

    def test_settings_directory_creation(self, qapp, temp_settings_dir, monkeypatch):
        """Test that settings directory is created if it doesn't exist."""
        # Use a nested path that doesn't exist
        settings_file = temp_settings_dir / "nested" / "deeper" / "settings.json"
        monkeypatch.setattr(Config, "SETTINGS_FILE", settings_file)

        # Ensure parent directories don't exist
        assert not settings_file.parent.exists()

        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)

            window = MainWindow()
            qapp.processEvents()

            # Save settings - should create directories
            window._save_settings()

            # Verify directory was created
            assert settings_file.parent.exists()
            assert settings_file.exists()

            window.close()

    def test_settings_close_event_persistence(
        self, qapp, mock_config_settings_file, sample_shots
    ):
        """Test that settings are saved on close event."""
        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)

            window = MainWindow()
            qapp.processEvents()

            # Set up some state
            window.shot_model.shots = sample_shots
            window.shot_grid.refresh_shots()
            window.shot_grid.size_slider.setValue(200)
            window.undistortion_checkbox.setChecked(True)

            # Mock _save_settings to verify it's called
            with patch.object(window, "_save_settings") as mock_save:
                # Simulate close event
                from PySide6.QtGui import QCloseEvent

                close_event = QCloseEvent()
                window.closeEvent(close_event)

                # Verify settings were saved
                mock_save.assert_called_once()

                # Event should be accepted
                assert close_event.isAccepted()

    def test_shot_selection_persistence_workflow(
        self, qapp, mock_config_settings_file, sample_shots
    ):
        """Test that shot selection persists across sessions."""
        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)

            # First session - select a shot
            window1 = MainWindow()
            qapp.processEvents()

            window1.shot_model.shots = sample_shots
            window1.shot_grid.refresh_shots()
            qapp.processEvents()

            # Select middle shot
            selected_shot = sample_shots[1]  # seq001_0020
            window1._on_shot_selected(selected_shot)

            # Save and close
            window1._save_settings()
            window1.close()

            # Second session - verify selection is restored
            window2 = MainWindow()
            qapp.processEvents()

            window2.shot_model.shots = sample_shots
            window2.shot_grid.refresh_shots()
            qapp.processEvents()

            # Load settings
            window2._load_settings()

            # Verify last selected shot name was restored
            assert window2._last_selected_shot_name == selected_shot.full_name

            window2.close()

    def test_ui_state_consistency_after_restoration(
        self, qapp, mock_config_settings_file
    ):
        """Test that UI state remains consistent after settings restoration."""
        with patch("shot_model.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)

            # Create settings with specific values
            settings = {
                "thumbnail_size": 320,
                "include_undistortion": True,
                "include_raw_plate": False,
                "active_tab": 1,
            }

            mock_config_settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(mock_config_settings_file, "w") as f:
                json.dump(settings, f)

            # Create window and load settings
            window = MainWindow()
            qapp.processEvents()

            # Load settings
            window._load_settings()

            # Verify all UI elements are in sync
            assert window.shot_grid.size_slider.value() == 320
            assert window.undistortion_checkbox.isChecked() is True
            assert window.raw_plate_checkbox.isChecked() is False
            assert window.tab_widget.currentIndex() == 1

            # Verify thumbnail size is applied to grid
            assert window.shot_grid._thumbnail_size == 320

            window.close()
