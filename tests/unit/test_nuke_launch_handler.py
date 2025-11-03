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
        assert nuke_handler.workspace_manager is not None
        assert nuke_handler.script_generator is not None
        assert nuke_handler.raw_plate_finder is not None
        assert nuke_handler.undistortion_finder is not None

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

    def test_handle_media_loading_plate_only(self, nuke_handler, mock_shot) -> None:
        """Test media loading with plate only."""
        with (
            patch.object(
                nuke_handler.raw_plate_finder, "find_latest_raw_plate"
            ) as mock_find_plate,
            patch.object(
                nuke_handler.raw_plate_finder, "verify_plate_exists"
            ) as mock_verify,
            patch.object(
                nuke_handler.script_generator, "create_plate_script"
            ) as mock_create_script,
            patch.object(
                nuke_handler.raw_plate_finder, "get_version_from_path"
            ) as mock_get_version,
        ):
            mock_find_plate.return_value = "/test/plates/TEST_0010_v001.exr"
            mock_verify.return_value = True
            mock_create_script.return_value = "/tmp/nuke_script.nk"
            mock_get_version.return_value = "v001"

            options = {"include_raw_plate": True}
            command, messages = nuke_handler._handle_media_loading(
                mock_shot, "nuke", options
            )

            assert "/tmp/nuke_script.nk" in command
            assert any(
                "Generated Nuke script with plate: v001" in msg for msg in messages
            )

    def test_handle_media_loading_undistortion_only(
        self, nuke_handler, mock_shot
    ) -> None:
        """Test media loading with undistortion only."""
        with (
            patch.object(
                nuke_handler.undistortion_finder, "find_latest_undistortion"
            ) as mock_find_undist,
            patch.object(
                nuke_handler.undistortion_finder, "get_version_from_path"
            ) as mock_get_version,
            patch("nuke_launch_handler.Config.NUKE_UNDISTORTION_MODE", "direct"),
        ):
            mock_find_undist.return_value = Path("/test/undist/TEST_0010_v001.nk")
            mock_get_version.return_value = "v001"

            options = {"include_undistortion": True}
            command, messages = nuke_handler._handle_media_loading(
                mock_shot, "nuke", options
            )

            assert "/test/undist/TEST_0010_v001.nk" in command
            assert any(
                "Opening undistortion file directly: v001" in msg for msg in messages
            )

    def test_handle_media_loading_plate_and_undistortion(
        self, nuke_handler, mock_shot
    ) -> None:
        """Test media loading with both plate and undistortion."""
        with (
            patch.object(
                nuke_handler.raw_plate_finder, "find_latest_raw_plate"
            ) as mock_find_plate,
            patch.object(
                nuke_handler.raw_plate_finder, "verify_plate_exists"
            ) as mock_verify,
            patch.object(
                nuke_handler.undistortion_finder, "find_latest_undistortion"
            ) as mock_find_undist,
            patch.object(
                nuke_handler.script_generator, "create_loader_script"
            ) as mock_create_loader,
            patch("nuke_launch_handler.Config.NUKE_USE_LOADER_SCRIPT", True),
        ):
            mock_find_plate.return_value = "/test/plates/TEST_0010_v001.exr"
            mock_verify.return_value = True
            mock_find_undist.return_value = Path("/test/undist/TEST_0010_v001.nk")
            mock_create_loader.return_value = "/tmp/loader_script.nk"

            # Mock version getters
            with (
                patch.object(
                    nuke_handler.raw_plate_finder, "get_version_from_path"
                ) as mock_plate_ver,
                patch.object(
                    nuke_handler.undistortion_finder,
                    "get_version_from_path",
                ) as mock_undist_ver,
            ):
                mock_plate_ver.return_value = "v001"
                mock_undist_ver.return_value = "v002"

                options = {
                    "include_raw_plate": True,
                    "include_undistortion": True,
                }
                command, messages = nuke_handler._handle_media_loading(
                    mock_shot, "nuke", options
                )

                assert "/tmp/loader_script.nk" in command
                assert any("Created loader script" in msg for msg in messages)
                assert any("(v001)" in msg and "(v002)" in msg for msg in messages)

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
        ), patch("nuke_launch_handler.os.path.exists") as mock_exists:
            mock_exists.return_value = True
            fixes = nuke_handler.get_environment_fixes()

            assert 'export OCIO="/test/ocio/config.ocio"' in fixes
            assert "NUKE_DISABLE_CRASH_REPORTING=1" in fixes

    def test_create_new_workspace_script_with_plate(
        self, nuke_handler, mock_shot
    ) -> None:
        """Test creating new workspace script with plate."""
        with (
            patch.object(
                nuke_handler.raw_plate_finder, "find_plate_for_space"
            ) as mock_find,
            patch.object(
                nuke_handler.raw_plate_finder, "verify_plate_exists"
            ) as mock_verify,
            patch.object(
                nuke_handler.script_generator, "create_plate_directory_script"
            ) as mock_create,
        ):
            mock_find.return_value = "/test/plates/TEST_0010_v001.exr"
            mock_verify.return_value = True
            mock_create.return_value = "/test/workspace/comp/nuke/FG01/TEST_0010_mm-default_FG01_scene_v001.nk"

            options = {"include_raw_plate": True}
            result = nuke_handler._create_new_workspace_script(mock_shot, 1, options, "FG01")

            assert result == "/test/workspace/comp/nuke/FG01/TEST_0010_mm-default_FG01_scene_v001.nk"
            mock_create.assert_called_once_with(
                "/test/plates/TEST_0010_v001.exr",
                "/test/workspace",
                "TEST_0010",
                "FG01",
                version=1,
            )

    def test_create_new_workspace_script_empty(self, nuke_handler, mock_shot) -> None:
        """Test creating new empty workspace script."""
        with patch.object(
            nuke_handler.script_generator, "create_empty_plate_script"
        ) as mock_create:
            mock_create.return_value = "/test/workspace/comp/nuke/FG01/TEST_0010_mm-default_FG01_scene_v001.nk"

            options = {}
            result = nuke_handler._create_new_workspace_script(mock_shot, 1, options, "FG01")

            assert result == "/test/workspace/comp/nuke/FG01/TEST_0010_mm-default_FG01_scene_v001.nk"
            mock_create.assert_called_once_with(
                "/test/workspace",
                "TEST_0010",
                "FG01",
                version=1,
            )
