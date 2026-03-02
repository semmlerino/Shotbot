"""Tests for rv_launcher module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rv_launcher import open_plate_in_rv


@pytest.mark.unit
class TestOpenPlateInRV:
    """Tests for open_plate_in_rv function."""

    @patch("publish_plate_finder.find_main_plate", return_value=None)
    def test_no_plate_found_logs_warning_and_notifies(self, mock_find):
        """When no plate is found, logs warning and shows error notification."""
        with patch("notification_manager.error") as mock_notify:
            open_plate_in_rv("/some/workspace")
            mock_notify.assert_called_once()
            assert "No Plate Found" in mock_notify.call_args[0][0]

    @patch("rv_launcher.subprocess.Popen")
    @patch("publish_plate_finder.find_main_plate", return_value="/path/to/plate.exr")
    def test_launches_rv_with_correct_command(self, mock_find, mock_popen):
        """Successfully launches RV with correct flags."""
        open_plate_in_rv("/some/workspace")
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == "bash"
        assert "-ilc" in args

    @patch("rv_launcher.subprocess.Popen", side_effect=FileNotFoundError)
    @patch("publish_plate_finder.find_main_plate", return_value="/path/to/plate.exr")
    def test_rv_not_found_error(self, mock_find, mock_popen):
        """FileNotFoundError shows RV Not Found notification."""
        with patch("notification_manager.error") as mock_notify:
            open_plate_in_rv("/some/workspace")
            mock_notify.assert_called_once()
            assert "RV Not Found" in mock_notify.call_args[0][0]

    @patch("rv_launcher.subprocess.Popen", side_effect=RuntimeError("boom"))
    @patch("publish_plate_finder.find_main_plate", return_value="/path/to/plate.exr")
    def test_generic_launch_error(self, mock_find, mock_popen):
        """Generic exception shows RV Launch Failed notification."""
        with patch("notification_manager.error") as mock_notify:
            open_plate_in_rv("/some/workspace")
            mock_notify.assert_called_once()
            assert "RV Launch Failed" in mock_notify.call_args[0][0]
