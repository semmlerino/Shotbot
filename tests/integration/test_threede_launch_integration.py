"""Integration tests for 3DE launch pipeline.

Tests the end-to-end launch flow for 3DEqualizer including:
- Command building with workspace setup
- Rez environment wrapping
- Scene file path handling
- Error handling and validation

Following UNIFIED_TESTING_V2.md best practices:
- Use real CommandLauncher with mocked subprocess execution
- Test complete flows rather than isolated units
- Verify command strings and environment setup
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from launch.command_launcher import CommandLauncher
from launch.launch_operation import LaunchOperation
from launch.launch_request import LaunchContext, LaunchRequest
from type_definitions import Shot, ThreeDEScene


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_shot() -> Shot:
    """Create a sample shot for testing."""
    return Shot(
        show="testshow",
        sequence="sq010",
        shot="sh0010",
        workspace_path="/shows/testshow/shots/sq010/sh0010",
    )


@pytest.fixture
def sample_scene() -> ThreeDEScene:
    """Create a sample 3DE scene for testing."""
    return ThreeDEScene(
        show="testshow",
        sequence="sq010",
        shot="sh0010",
        workspace_path="/shows/testshow/shots/sq010/sh0010",
        user="artist",
        plate="plate_main",
        scene_path=Path("/shows/testshow/shots/sq010/sh0010/3de/artist_plate_main.3de"),
        modified_time=time.time(),
    )


@pytest.fixture
def launcher(qapp: Any, mocker: Any) -> CommandLauncher:
    """Create a CommandLauncher instance with mocked dependencies."""
    mocker.patch("launch.command_launcher.EnvironmentManager.warm_cache_async")
    mock_settings = mocker.patch("launch.command_launcher.SettingsManager")
    mock_settings.return_value.get_terminal_emulator.return_value = "gnome-terminal"

    launcher = CommandLauncher()
    # Pre-populate rez cache so tests don't fail on missing rez binary
    launcher.env_manager._rez_available_cache = True
    yield launcher

    # Cleanup
    launcher.cleanup()


# ============================================================================
# Test 3DE Command Building
# ============================================================================


class TestThreeDECommandBuilding:
    """Test 3DE-specific command building."""

    def test_3de_launch_with_latest_scene(
        self,
        launcher: CommandLauncher,
        sample_shot: Shot,
        mocker,
    ) -> None:
        """Test 3DE launch with open_latest_threede option.

        Uses cache hit path (sync) to verify command building.
        Async file search is tested separately.
        """
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)

        # Mock cache to return a cache hit (triggers sync path)
        cached_scene = Path("/shows/testshow/shots/sq010/sh0010/3de/latest_scene.3de")
        from cache.types import LatestFileCacheResult

        launcher._cache_manager.get_latest_file_cache_result = MagicMock(
            return_value=LatestFileCacheResult("hit", cached_scene)
        )
        launcher.set_current_shot(sample_shot)

        context = LaunchContext(open_latest_threede=True)

        mocker.patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        )
        mock_execute = mocker.patch.object(
            LaunchOperation, "_launch_in_new_terminal", return_value=True
        )
        result = launcher.launch(LaunchRequest(app_name="3de", context=context))

        assert result is True

        # Verify -open flag is in command
        call_args = mock_execute.call_args
        full_command = call_args[0][0]
        assert "-open" in full_command
        assert "latest_scene.3de" in full_command


# ============================================================================
# Test Launch with Scene
# ============================================================================


class TestLaunchWithScene:
    """Test launching with a specific scene file."""

    def test_launch_maya_with_scene(
        self,
        launcher: CommandLauncher,
        sample_scene: ThreeDEScene,
        mocker,
    ) -> None:
        """Test launching Maya with a scene file uses context-only launch."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)

        # Create a Maya scene
        maya_scene = ThreeDEScene(
            show="testshow",
            sequence="sq010",
            shot="sh0010",
            workspace_path="/shows/testshow/shots/sq010/sh0010",
            user="artist",
            plate="plate_main",
            scene_path=Path("/shows/testshow/shots/sq010/sh0010/maya/scene.ma"),
            modified_time=time.time(),
        )

        mocker.patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        )
        mock_execute = mocker.patch.object(
            LaunchOperation, "_launch_in_new_terminal", return_value=True
        )
        result = launcher.launch(LaunchRequest(app_name="maya", scene=maya_scene))

        assert result is True

        # Maya gets plain workspace launch (no scene file, no SGTK_FILE_TO_OPEN)
        call_args = mock_execute.call_args
        full_command = call_args[0][0]
        assert "SGTK_FILE_TO_OPEN" not in full_command
        assert "-file" not in full_command
        assert "scene.ma" not in full_command


# ============================================================================
# Test Path Escaping
# ============================================================================


class TestPathEscaping:
    """Test path validation and escaping."""

    def test_workspace_path_with_spaces(
        self,
        launcher: CommandLauncher,
        tmp_path: Path,
        mocker,
    ) -> None:
        """Test launch handles workspace paths with spaces."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)

        # Create workspace with spaces
        workspace = tmp_path / "shows" / "test show" / "shots" / "sq 010" / "sh 0010"
        workspace.mkdir(parents=True)

        shot = Shot(
            show="test show",
            sequence="sq 010",
            shot="sh 0010",
            workspace_path=str(workspace),
        )
        launcher.set_current_shot(shot)

        mock_execute = mocker.patch.object(
            LaunchOperation, "_launch_in_new_terminal", return_value=True
        )
        result = launcher.launch(LaunchRequest(app_name="3de"))

        assert result is True
        # Command should be properly quoted
        call_args = mock_execute.call_args
        full_command = call_args[0][0]
        # Path with spaces should be quoted
        assert '"' in full_command or "'" in full_command or "\\ " in full_command

    def test_scene_path_with_special_chars(
        self,
        launcher: CommandLauncher,
        tmp_path: Path,
        mocker,
    ) -> None:
        """Test launch handles scene paths with special characters."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)

        # Create workspace
        workspace = tmp_path / "shows" / "testshow" / "shots" / "sq010" / "sh0010"
        workspace.mkdir(parents=True)

        scene = ThreeDEScene(
            show="testshow",
            sequence="sq010",
            shot="sh0010",
            workspace_path=str(workspace),
            user="artist",
            plate="plate_v2",
            scene_path=workspace / "3de" / "scene_v2 (final).3de",
            modified_time=time.time(),
        )

        mocker.patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch.object(LaunchOperation, "_launch_in_new_terminal", return_value=True)
        result = launcher.launch(LaunchRequest(app_name="3de", scene=scene))

        assert result is True


# ============================================================================
# Test Error Handling
# ============================================================================


class TestErrorHandling:
    """Test error handling in launch flow."""

    def test_scene_launch_succeeds(
        self,
        launcher: CommandLauncher,
        sample_scene: ThreeDEScene,
        mocker,
    ) -> None:
        """launch returns True for valid scene."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)

        mocker.patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        )
        mocker.patch.object(LaunchOperation, "_launch_in_new_terminal", return_value=True)
        result = launcher.launch(LaunchRequest(app_name="3de", scene=sample_scene))

        assert result is True
