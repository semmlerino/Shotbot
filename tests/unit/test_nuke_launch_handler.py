"""Test the unified Nuke launch handler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from nuke_launch_handler import NukeLaunchHandler
from shot_model import Shot


@pytest.fixture
def mock_shot():
    """Create a mock shot for testing."""
    shot = Mock(spec=Shot)
    shot.workspace_path = "/test/workspace"
    shot.full_name = "TEST_0010"
    return shot


@pytest.fixture
def nuke_handler():
    """Create a NukeLaunchHandler instance for testing."""
    return NukeLaunchHandler()


class TestNukeLaunchHandler:
    """Test the NukeLaunchHandler class."""

    def test_initialization(self, nuke_handler) -> None:
        """Test that handler initializes with required modules."""
        assert nuke_handler.script_generator is not None

    def test_prepare_nuke_command_basic(self, nuke_handler, mock_shot) -> None:
        """Test basic command preparation without any options."""
        command, messages = nuke_handler.prepare_nuke_command(mock_shot, "nuke", {})

        assert command == "nuke"
        assert isinstance(messages, list)

    @patch("nuke_launch_handler.Config.NUKE_FIX_OCIO_CRASH", True)
    def test_prepare_nuke_command_with_ocio_fix(self, nuke_handler, mock_shot) -> None:
        """Test command preparation with OCIO crash fix enabled."""
        command, messages = nuke_handler.prepare_nuke_command(mock_shot, "nuke", {})

        assert command == "nuke"
        assert any("OCIO" in msg for msg in messages)

    def test_handle_workspace_scripts_open_latest(
        self, nuke_handler, mock_shot
    ) -> None:
        """Test handling workspace scripts when opening latest."""
        with patch("nuke_launch_handler.PlateDiscovery.find_existing_scripts") as mock_find:
            mock_find.return_value = [
                (Path("/test/workspace/comp/nuke/FG01/TEST_0010_mm-default_FG01_scene_v001.nk"), 1)
            ]

            options = {"open_latest_scene": True}
            command, messages = nuke_handler._handle_workspace_scripts(
                mock_shot, "nuke", options, "FG01"
            )

            assert "TEST_0010_mm-default_FG01_scene_v001.nk" in command
            assert any("Opening existing Nuke script" in msg for msg in messages)

    def test_handle_workspace_scripts_create_new(self, nuke_handler, mock_shot) -> None:
        """Test handling workspace scripts when creating new."""
        with (
            patch("nuke_launch_handler.PlateDiscovery.get_next_script_version") as mock_get_next,
            patch.object(nuke_handler, "_create_new_workspace_script") as mock_create,
        ):
            mock_get_next.return_value = 2
            mock_create.return_value = "/test/workspace/comp/nuke/FG01/TEST_0010_mm-default_FG01_scene_v002.nk"

            options = {"create_new_file": True}
            command, messages = nuke_handler._handle_workspace_scripts(
                mock_shot, "nuke", options, "FG01"
            )

            assert "TEST_0010_mm-default_FG01_scene_v002.nk" in command
            assert any("Creating new Nuke script for FG01" in msg for msg in messages)

    def test_handle_workspace_scripts_priority(self, nuke_handler, mock_shot) -> None:
        """Test that open_latest_scene takes priority over create_new_file."""
        with patch("nuke_launch_handler.PlateDiscovery.find_existing_scripts") as mock_find:
            mock_find.return_value = [
                (Path("/test/workspace/comp/nuke/FG01/TEST_0010_mm-default_FG01_scene_v001.nk"), 1)
            ]

            options = {"open_latest_scene": True, "create_new_file": True}
            command, messages = nuke_handler._handle_workspace_scripts(
                mock_shot, "nuke", options, "FG01"
            )

            # Should open latest, not create new
            assert "TEST_0010_mm-default_FG01_scene_v001.nk" in command
            assert any("Opening existing Nuke script" in msg for msg in messages)
            assert not any("Creating new" in msg for msg in messages)

    def test_get_environment_fixes_disabled(self, nuke_handler) -> None:
        """Test environment fixes when disabled."""
        with patch("nuke_launch_handler.Config.NUKE_FIX_OCIO_CRASH", False):
            fixes = nuke_handler.get_environment_fixes()
            assert fixes == ""

    def test_get_environment_fixes_with_problematic_plugins(self, nuke_handler) -> None:
        """Test environment fixes with problematic plugin paths."""
        with patch(
            "nuke_launch_handler.Config.NUKE_FIX_OCIO_CRASH", True
        ), patch(
            "nuke_launch_handler.Config.NUKE_SKIP_PROBLEMATIC_PLUGINS", True
        ), patch(
            "nuke_launch_handler.Config.NUKE_PROBLEMATIC_PLUGIN_PATHS",
            ["/bad/plugin1", "/bad/plugin2"],
        ):
            fixes = nuke_handler.get_environment_fixes()

            assert "FILTERED_NUKE_PATH" in fixes
            assert "grep -v" in fixes
            assert "NUKE_DISABLE_CRASH_REPORTING=1" in fixes

    def test_get_environment_fixes_with_ocio_fallback(self, nuke_handler) -> None:
        """Test environment fixes with OCIO fallback config."""
        with patch(
            "nuke_launch_handler.Config.NUKE_FIX_OCIO_CRASH", True
        ), patch(
            "nuke_launch_handler.Config.NUKE_OCIO_FALLBACK_CONFIG",
            "/test/ocio/config.ocio",
        ), patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = True
            fixes = nuke_handler.get_environment_fixes()

            assert 'export OCIO="/test/ocio/config.ocio"' in fixes
            assert "NUKE_DISABLE_CRASH_REPORTING=1" in fixes

    def test_create_new_workspace_script_empty(self, nuke_handler, mock_shot) -> None:
        """Test creating new empty workspace script."""
        with patch.object(
            nuke_handler.script_generator, "create_empty_plate_script"
        ) as mock_create:
            mock_create.return_value = "/test/workspace/comp/nuke/FG01/TEST_0010_mm-default_FG01_scene_v001.nk"

            result = nuke_handler._create_new_workspace_script(mock_shot, 1, "FG01")

            assert result == "/test/workspace/comp/nuke/FG01/TEST_0010_mm-default_FG01_scene_v001.nk"
            mock_create.assert_called_once_with(
                "/test/workspace",
                "TEST_0010",
                "FG01",
                version=1,
            )
