"""Test the Nuke launch router."""

from __future__ import annotations

import logging
from unittest.mock import Mock, patch

import pytest

from nuke_launch_router import NukeLaunchRouter
from shot_model import Shot


@pytest.fixture
def mock_shot():
    """Create a mock shot for testing."""
    shot = Mock(spec=Shot)
    shot.workspace_path = "/test/workspace"
    shot.full_name = "TEST_0010"
    return shot


@pytest.fixture
def router():
    """Create a NukeLaunchRouter instance for testing."""
    return NukeLaunchRouter()


class TestNukeLaunchRouter:
    """Test the NukeLaunchRouter class."""

    def test_route_to_simple_open_latest(self, router, mock_shot) -> None:
        """Test routing to simple launcher for open_latest_scene."""
        with patch.object(router.simple_launcher, "open_latest_script") as mock_open:
            mock_open.return_value = ("nuke /path/to/script.nk", ["Opening: script.nk"])

            options = {"open_latest_scene": True}
            _command, _messages = router.prepare_nuke_command(
                mock_shot, "nuke", options, selected_plate="FG01"
            )

            assert router.simple_launches == 1
            mock_open.assert_called_once_with(
                mock_shot, "FG01", create_if_missing=True
            )

    def test_route_to_simple_create_new(self, router, mock_shot) -> None:
        """Test routing to simple launcher for create_new_file."""
        with patch.object(
            router.simple_launcher, "create_new_version"
        ) as mock_create:
            mock_create.return_value = ("nuke /path/to/script.nk", ["Created: script.nk"])

            options = {"create_new_file": True}
            _command, _messages = router.prepare_nuke_command(
                mock_shot, "nuke", options, selected_plate="FG01"
            )

            assert router.simple_launches == 1
            mock_create.assert_called_once_with(mock_shot, "FG01")

    def test_no_options_opens_empty_nuke(self, router, mock_shot) -> None:
        """Test that no options results in opening empty Nuke."""
        options = {}
        command, messages = router.prepare_nuke_command(
            mock_shot, "nuke", options, selected_plate="FG01"
        )

        assert command == "nuke"
        assert router.simple_launches == 1  # Counts as simple workflow
        assert any("no options selected" in msg.lower() for msg in messages)

    def test_no_plate_selected_error(self, router, mock_shot) -> None:
        """Test error handling when no plate is selected.

        When plate is required but not selected, returns empty command to
        prevent launching empty Nuke (caller should check and abort).
        """
        options = {"open_latest_scene": True}
        command, messages = router.prepare_nuke_command(
            mock_shot, "nuke", options, selected_plate=None
        )

        # Empty command signals failure - prevents launching empty Nuke
        assert command == ""
        assert any("no plate selected" in msg.lower() for msg in messages)

    def test_create_new_takes_priority_over_open_latest(self, router, mock_shot) -> None:
        """Test that create_new_file takes priority over open_latest_scene."""
        with patch.object(
            router.simple_launcher, "create_new_version"
        ) as mock_create:
            mock_create.return_value = ("nuke /path/to/script.nk", ["Created: script.nk"])

            options = {"open_latest_scene": True, "create_new_file": True}
            _command, _messages = router.prepare_nuke_command(
                mock_shot, "nuke", options, selected_plate="FG01"
            )

            mock_create.assert_called_once()

    def test_usage_statistics_tracking(self, router, mock_shot) -> None:
        """Test that usage statistics are tracked correctly."""
        with patch.object(router.simple_launcher, "open_latest_script") as mock_open:
            mock_open.return_value = ("nuke /path/to/script.nk", ["Opening: script.nk"])

            # Perform 3 simple launches
            for _ in range(3):
                router.prepare_nuke_command(
                    mock_shot, "nuke", {"open_latest_scene": True}, selected_plate="FG01"
                )

        assert router.simple_launches == 3

    def test_log_usage_stats(self, router, caplog) -> None:
        """Test that usage statistics are logged correctly."""
        # Configure caplog to capture INFO level logs from the router's logger
        caplog.set_level(logging.INFO, logger="nuke_launch_router.NukeLaunchRouter")

        router.simple_launches = 47

        router.log_usage_stats()

        assert "Nuke Launcher Usage Statistics" in caplog.text
        assert "Simple workflow:" in caplog.text
        assert "47" in caplog.text

    def test_log_usage_stats_empty(self, router, caplog) -> None:
        """Test that log_usage_stats handles zero launches gracefully."""
        router.simple_launches = 0

        router.log_usage_stats()

        # Should not log anything if total is 0
        assert "Nuke Launcher Usage Statistics" not in caplog.text

    def test_routing_decision_logging(self, router, mock_shot, caplog) -> None:
        """Test that routing decisions are logged appropriately."""
        # Configure caplog to capture INFO level logs from the router's logger
        caplog.set_level(logging.INFO, logger="nuke_launch_router.NukeLaunchRouter")

        with patch.object(router.simple_launcher, "open_latest_script") as mock_open:
            mock_open.return_value = ("nuke /path/to/script.nk", ["Opening: script.nk"])

            options = {"open_latest_scene": True}
            router.prepare_nuke_command(
                mock_shot, "nuke", options, selected_plate="FG01"
            )

            assert "SIMPLE launcher" in caplog.text
