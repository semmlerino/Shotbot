"""Integration tests for MainWindow and ShotGrid UI flow."""

from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import Qt

from main_window import MainWindow
from shot_model import Shot


class TestMainWindowShotGridIntegration:
    """Integration tests between MainWindow and ShotGrid."""

    @pytest.fixture
    def mock_shots(self):
        """Create mock shots for testing."""
        shots = []
        for i in range(3):
            shot = Shot(
                show=f"testshow{i}",
                sequence=f"seq{i:03d}",
                shot=f"shot{i:03d}",
                workspace_path=f"/shows/testshow{i}/shots/seq{i:03d}/shot{i:03d}",
            )
            shots.append(shot)
        return shots

    @pytest.fixture
    def main_window(self, qtbot, mock_shots):
        """Create MainWindow instance with mocked shot model."""
        with patch("shot_model.subprocess.run") as mock_run:
            # Mock successful ws command
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            # Create window
            window = MainWindow()
            qtbot.addWidget(window)

            # Show the window to ensure all widgets are initialized
            window.show()
            qtbot.waitExposed(window)

            # Mock shot model to return our test shots
            window.shot_model.shots = mock_shots
            window.shot_model.refresh_shots = Mock(return_value=(True, True))

            # Refresh the UI - use the actual grid type
            window.shot_grid.refresh_shots()

            return window

    def test_window_initialization(self, main_window, qtbot):
        """Test main window initializes properly."""
        assert main_window.isVisible()
        assert hasattr(main_window, "shot_grid")
        assert hasattr(main_window, "shot_info_panel")
        assert hasattr(main_window, "command_launcher")
        assert hasattr(main_window, "log_viewer")

        # Tab widget should exist
        assert hasattr(main_window, "tab_widget")
        assert main_window.tab_widget.count() >= 2  # At least Shots and 3DE tabs

    def test_shot_selection_flow(self, main_window, mock_shots, qtbot):
        """Test the complete shot selection flow."""
        # Get first shot
        shot = mock_shots[0]

        # Select it through the grid's public API
        main_window.shot_grid.select_shot(shot)

        # Verify selection
        assert main_window.shot_grid.selected_shot == shot

        # Verify command launcher has the shot
        assert main_window.command_launcher.current_shot == shot

        # App buttons should be enabled
        assert main_window.app_buttons["nuke"].isEnabled()
        assert main_window.app_buttons["maya"].isEnabled()

    def test_double_click_launches_app(self, main_window, mock_shots, qtbot):
        """Test double-click launches application."""
        # Select a shot first
        shot = mock_shots[0]
        main_window.shot_grid.select_shot(shot)

        # Mock the launch method
        with patch.object(main_window.command_launcher, "launch_app") as mock_launch:
            # Emit the double-click signal directly
            main_window.shot_grid.shot_double_clicked.emit(shot)

            # Verify app was launched (actual implementation includes checkbox states)
            mock_launch.assert_called_once()
            call_args = mock_launch.call_args[0]
            assert call_args[0] == "nuke"  # First arg is app name

    def test_refresh_functionality(self, main_window, qtbot):
        """Test refresh functionality works."""
        with patch.object(main_window.shot_model, "refresh_shots") as mock_refresh:
            mock_refresh.return_value = (True, False)  # Success, no changes

            # Call refresh directly (it's a menu action, not a button)
            main_window._refresh_shots()

            # Verify refresh was called
            mock_refresh.assert_called_once()

    def test_app_buttons_state_change(self, main_window, mock_shots, qtbot):
        """Test app buttons enable/disable based on selection."""
        # Initially no selection - verify buttons disabled
        if main_window.shot_grid.selected_shot is None:
            assert not main_window.app_buttons["nuke"].isEnabled()

        # Select a shot
        shot = mock_shots[0]
        main_window.shot_grid.select_shot(shot)

        # Buttons should be enabled
        assert main_window.app_buttons["nuke"].isEnabled()
        assert main_window.app_buttons["maya"].isEnabled()

    def test_settings_checkboxes(self, main_window, qtbot):
        """Test settings checkboxes work."""
        # Test undistortion checkbox
        initial_state = main_window.undistortion_checkbox.isChecked()
        main_window.undistortion_checkbox.setChecked(not initial_state)
        assert main_window.undistortion_checkbox.isChecked() != initial_state

        # Test raw plate checkbox
        initial_state = main_window.raw_plate_checkbox.isChecked()
        main_window.raw_plate_checkbox.setChecked(not initial_state)
        assert main_window.raw_plate_checkbox.isChecked() != initial_state

    def test_log_viewer_receives_messages(self, main_window, mock_shots, qtbot):
        """Test log viewer receives command messages."""
        # Select a shot
        shot = mock_shots[0]
        main_window.shot_grid.select_shot(shot)

        # Mock subprocess to prevent actual launch
        with patch("command_launcher.subprocess.Popen"):
            # Launch an app
            main_window.app_buttons["nuke"].click()

        # Check log has content
        qtbot.wait(100)  # Give it time to update
        log_text = main_window.log_viewer.log_text.toPlainText()
        assert len(log_text) > 0  # Should have some log content

    def test_keyboard_navigation_basics(self, main_window, mock_shots, qtbot):
        """Test basic keyboard navigation."""
        # Ensure grid has focus
        main_window.shot_grid.setFocus()

        # Select first shot
        if len(mock_shots) > 0:
            main_window.shot_grid.select_shot(mock_shots[0])

            # Try arrow key navigation (if multiple shots exist)
            if len(mock_shots) > 1:
                # Send right arrow
                qtbot.keyClick(main_window.shot_grid, Qt.Key.Key_Right)

                # Selection should have changed
                assert main_window.shot_grid.selected_shot != mock_shots[0]

    def test_thumbnail_size_slider(self, main_window, qtbot):
        """Test thumbnail size slider changes size."""
        initial_size = main_window.shot_grid._thumbnail_size
        new_size = 200 if initial_size != 200 else 250

        # Change slider
        main_window.shot_grid.size_slider.setValue(new_size)

        # Size should update
        assert main_window.shot_grid._thumbnail_size == new_size

    def test_tab_switching(self, main_window, qtbot):
        """Test switching between tabs."""
        # Start on first tab
        assert main_window.tab_widget.currentIndex() == 0

        # Switch to 3DE tab
        main_window.tab_widget.setCurrentIndex(1)
        assert main_window.tab_widget.currentIndex() == 1

        # Switch back
        main_window.tab_widget.setCurrentIndex(0)
        assert main_window.tab_widget.currentIndex() == 0
