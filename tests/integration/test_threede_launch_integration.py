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
from unittest.mock import MagicMock, patch

import pytest

from command_launcher import CommandLauncher, LaunchContext
from shot_model import Shot
from threede_scene_model import ThreeDEScene


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_env() -> dict[str, str]:
    """Create a mock environment for testing."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/testuser",
        "SHOWS_ROOT": "/shows",
    }


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
def launcher(qapp: Any) -> CommandLauncher:
    """Create a CommandLauncher instance with mocked dependencies."""
    with patch("command_launcher.EnvironmentManager.warm_cache_async"), \
         patch("command_launcher.SettingsManager") as mock_settings:
        mock_settings.return_value.get_terminal_emulator.return_value = "gnome-terminal"

        launcher = CommandLauncher()
        # Pre-populate rez cache so tests don't fail on missing rez binary
        launcher.env_manager._rez_available_cache = True
        yield launcher

        # Cleanup
        launcher.cleanup()


# ============================================================================
# Test Basic Launch Flow
# ============================================================================


class TestBasicLaunchFlow:
    """Test basic launch command construction."""

    def test_launch_fails_without_ws_command(
        self,
        launcher: CommandLauncher,
        sample_shot: Shot,
    ) -> None:
        """Test that launch fails if ws command not available."""
        launcher.set_current_shot(sample_shot)

        # Mock env_manager to report ws not available
        launcher.env_manager.is_ws_available = MagicMock(return_value=False)

        # Mock workspace validation to pass
        with patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        ):
            result = launcher.launch_app("3de")

        assert result is False


# ============================================================================
# Test 3DE Command Building
# ============================================================================


class TestThreeDECommandBuilding:
    """Test 3DE-specific command building."""

    def test_3de_basic_launch_command(
        self,
        launcher: CommandLauncher,
        sample_shot: Shot,
    ) -> None:
        """Test basic 3DE launch command structure."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)
        launcher.set_current_shot(sample_shot)

        # Mock workspace validation and execution
        with patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        ), patch.object(
            launcher, "_launch_in_new_terminal", return_value=True
        ) as mock_execute:
            result = launcher.launch_app("3de")

        assert result is True
        mock_execute.assert_called_once()

        # Verify command structure
        call_args = mock_execute.call_args
        full_command = call_args[0][0]

        # Should contain workspace setup
        assert "ws " in full_command
        assert sample_shot.workspace_path in full_command

    def test_3de_launch_with_latest_scene(
        self,
        launcher: CommandLauncher,
        sample_shot: Shot,
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

        with patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        ), patch.object(
            launcher, "_launch_in_new_terminal", return_value=True
        ) as mock_execute:
            result = launcher.launch_app("3de", context)

        assert result is True

        # Verify -open flag is in command
        call_args = mock_execute.call_args
        full_command = call_args[0][0]
        assert "-open" in full_command
        assert "latest_scene.3de" in full_command

    def test_3de_launch_no_scene_found_continues(
        self,
        launcher: CommandLauncher,
        sample_shot: Shot,
    ) -> None:
        """Test 3DE launch continues when no latest scene found.

        Uses cache hit path (sync) with None result to verify command building.
        Async file search is tested separately.
        """
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)

        # Mock cache to return "not_found" (cached result within TTL, no file)
        from cache.types import LatestFileCacheResult
        launcher._cache_manager.get_latest_file_cache_result = MagicMock(
            return_value=LatestFileCacheResult("not_found")
        )
        launcher.set_current_shot(sample_shot)

        context = LaunchContext(open_latest_threede=True)

        with patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        ), patch.object(
            launcher, "_launch_in_new_terminal", return_value=True
        ) as mock_execute:
            result = launcher.launch_app("3de", context)

        # Should still succeed, just without scene file
        assert result is True

        call_args = mock_execute.call_args
        full_command = call_args[0][0]
        # Should NOT contain -open flag since no scene found
        assert "-open" not in full_command


# ============================================================================
# Test Launch with Scene
# ============================================================================


class TestLaunchWithScene:
    """Test launching with a specific scene file."""

    def test_launch_maya_with_scene(
        self,
        launcher: CommandLauncher,
        sample_scene: ThreeDEScene,
    ) -> None:
        """Test launching Maya with a scene file uses -file flag."""
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

        with patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        ), patch.object(
            launcher, "_launch_in_new_terminal", return_value=True
        ) as mock_execute:
            result = launcher.launch_app_with_scene("maya", maya_scene)

        assert result is True

        # Verify Maya uses -file flag
        call_args = mock_execute.call_args
        full_command = call_args[0][0]

        assert "-file" in full_command
        assert "scene.ma" in full_command

    def test_launch_with_scene_rejects_unknown_app(
        self, launcher: CommandLauncher, sample_scene: ThreeDEScene
    ) -> None:
        """Test that launch_app_with_scene rejects unknown apps."""
        result = launcher.launch_app_with_scene("unknown_app", sample_scene)

        assert result is False


# ============================================================================
# Test Workspace Validation
# ============================================================================


class TestWorkspaceValidation:
    """Test workspace path validation."""

    def test_launch_validates_workspace_exists(
        self,
        launcher: CommandLauncher,
        sample_shot: Shot,
    ) -> None:
        """Test that launch validates workspace path exists."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)
        launcher.set_current_shot(sample_shot)

        # Without mocking validation, it should fail for non-existent path
        result = launcher.launch_app("3de")

        # Since /shows/testshow/... doesn't exist, validation should fail
        assert result is False

    def test_launch_with_valid_workspace(
        self,
        launcher: CommandLauncher,
        tmp_path: Path,
    ) -> None:
        """Test launch succeeds with valid workspace path."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)

        # Create a real temporary workspace
        workspace = tmp_path / "shows" / "testshow" / "shots" / "sq010" / "sh0010"
        workspace.mkdir(parents=True)

        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="sh0010",
            workspace_path=str(workspace),
        )
        launcher.set_current_shot(shot)

        with patch.object(
            launcher, "_launch_in_new_terminal", return_value=True
        ):
            result = launcher.launch_app("3de")

        assert result is True


# ============================================================================
# Test Path Escaping
# ============================================================================


class TestPathEscaping:
    """Test path validation and escaping."""

    def test_workspace_path_with_spaces(
        self,
        launcher: CommandLauncher,
        tmp_path: Path,
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

        with patch.object(
            launcher, "_launch_in_new_terminal", return_value=True
        ) as mock_execute:
            result = launcher.launch_app("3de")

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

        with patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        ), patch.object(
            launcher, "_launch_in_new_terminal", return_value=True
        ):
            result = launcher.launch_app_with_scene("3de", scene)

        assert result is True


# ============================================================================
# Test Error Handling
# ============================================================================


class TestErrorHandling:
    """Test error handling in launch flow."""

    def test_launch_returns_false_on_no_shot(
        self, launcher: CommandLauncher
    ) -> None:
        """launch_app returns False when no shot is selected."""
        result = launcher.launch_app("3de")

        assert result is False

    def test_launch_returns_false_on_unknown_app(
        self, launcher: CommandLauncher, sample_shot: Shot
    ) -> None:
        """launch_app returns False for unknown app."""
        launcher.set_current_shot(sample_shot)

        result = launcher.launch_app("invalid_app")

        assert result is False

    def test_error_on_workspace_validation_failure(
        self,
        launcher: CommandLauncher,
        sample_shot: Shot,
    ) -> None:
        """launch_app returns False on workspace validation failure."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)
        launcher.set_current_shot(sample_shot)

        # Don't mock validation - let it fail for non-existent path
        result = launcher.launch_app("3de")

        assert result is False


# ============================================================================
# Test Command Logging
# ============================================================================


class TestCommandLogging:
    """Test command execution logging."""

    def test_command_launch_succeeds(
        self,
        launcher: CommandLauncher,
        sample_shot: Shot,
    ) -> None:
        """launch_app returns True when command executes successfully."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)
        launcher.set_current_shot(sample_shot)

        with patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        ), patch.object(
            launcher, "_launch_in_new_terminal", return_value=True
        ):
            result = launcher.launch_app("3de")

        assert result is True

    def test_scene_launch_succeeds(
        self,
        launcher: CommandLauncher,
        sample_scene: ThreeDEScene,
    ) -> None:
        """launch_app_with_scene returns True for valid scene."""
        launcher.env_manager.is_ws_available = MagicMock(return_value=True)

        with patch.object(
            launcher, "_validate_workspace_before_launch", return_value=True
        ), patch.object(
            launcher, "_launch_in_new_terminal", return_value=True
        ):
            result = launcher.launch_app_with_scene("3de", sample_scene)

        assert result is True
