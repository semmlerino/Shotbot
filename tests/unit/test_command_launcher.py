"""Tests for CommandLauncher following UNIFIED_TESTING_GUIDE.

This test suite validates CommandLauncher behavior using:
- Test doubles for external dependencies
- Real Qt components and signals
- Behavior testing, not implementation details
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from command_launcher import CommandLauncher
from config import Config
from shot_model import Shot
from tests.test_helpers import process_qt_events
from threede_scene_model import ThreeDEScene


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def ensure_qt_cleanup(qtbot: QtBot):
    """Ensure Qt event processing completes after each test.

    This prevents Qt state pollution between tests, specifically:
    - QTimer.singleShot callbacks scheduled by CommandLauncher
    - QObject instances that need proper deletion
    - Event queue cleanup

    CRITICAL: CommandLauncher.launch_app() schedules QTimer.singleShot(100ms)
    callbacks that must complete before the next test starts.
    """
    yield
    # Wait for any pending timers (CommandLauncher uses 100ms timers)
    process_qt_events()


class TestRawPlateFinder:
    """Test double for RawPlateFinder."""

    __test__ = False  # Prevent pytest collection

    @staticmethod
    def find_latest_raw_plate(shot_workspace_path: str, _shot_name: str) -> str | None:
        """Mock finding latest raw plate."""
        if "TEST" in shot_workspace_path:
            return "/path/to/plate.####.exr"
        return None

    @staticmethod
    def verify_plate_exists(plate_path: str) -> bool:
        """Mock verifying plate exists."""
        return "/path/to/plate" in plate_path

    @staticmethod
    def get_version_from_path(plate_path: str) -> str | None:
        """Mock getting version from path."""
        if "plate" in plate_path:
            return "v001"
        return None


class TestNukeScriptGenerator:
    """Test double for NukeScriptGenerator."""

    __test__ = False  # Prevent pytest collection

    @staticmethod
    def create_plate_script(_plate_path: str, shot_name: str) -> str:
        """Mock creating plate script."""
        return f"/tmp/{shot_name}_plate.nk"


class TestThreeDELatestFinder:
    """Test double for ThreeDELatestFinder."""

    __test__ = False  # Prevent pytest collection

    @staticmethod
    def find_latest_3de_scene(shot: Shot) -> str | None:
        """Mock finding latest 3DE scene."""
        if shot.show == "TEST":
            return "/path/to/latest.3de"
        return None


class TestMayaLatestFinder:
    """Test double for MayaLatestFinder."""

    __test__ = False  # Prevent pytest collection

    @staticmethod
    def find_latest_maya_scene(shot: Shot) -> str | None:
        """Mock finding latest Maya scene."""
        if shot.show == "TEST":
            return "/path/to/latest.mb"
        return None


class TestCommandLauncher:
    """Test CommandLauncher functionality."""

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch) -> CommandLauncher:
        """Create CommandLauncher with test doubles."""
        # Mock the modules that will be imported in __init__
        # These need to be mocked at the module level before CommandLauncher imports them
        import sys
        import types

        # Create mock modules
        mock_raw_plate_finder = types.ModuleType("raw_plate_finder")
        mock_raw_plate_finder.RawPlateFinder = TestRawPlateFinder
        sys.modules["raw_plate_finder"] = mock_raw_plate_finder

        mock_nuke_script_generator = types.ModuleType("nuke_script_generator")
        mock_nuke_script_generator.NukeScriptGenerator = TestNukeScriptGenerator
        sys.modules["nuke_script_generator"] = mock_nuke_script_generator

        mock_threede_latest_finder = types.ModuleType("threede_latest_finder")
        mock_threede_latest_finder.ThreeDELatestFinder = TestThreeDELatestFinder
        sys.modules["threede_latest_finder"] = mock_threede_latest_finder

        mock_maya_latest_finder = types.ModuleType("maya_latest_finder")
        mock_maya_latest_finder.MayaLatestFinder = TestMayaLatestFinder
        sys.modules["maya_latest_finder"] = mock_maya_latest_finder

        # Mock is_ws_available to return True (ws isn't available in dev environment)
        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        return CommandLauncher()

    @pytest.fixture
    def test_shot(self) -> Shot:
        """Create a test shot."""
        return Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")

    @pytest.fixture
    def test_scene(self) -> ThreeDEScene:
        """Create a test 3DE scene."""
        return ThreeDEScene(
            show="TEST",
            sequence="seq01",
            shot="0010",
            workspace_path=f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010",
            user="testuser",
            plate="plate_v001",
            scene_path=Path("/path/to/scene.3de"),
        )

    def test_initialization(self, launcher: CommandLauncher) -> None:
        """Test CommandLauncher initializes correctly."""
        assert launcher.current_shot is None
        assert hasattr(launcher, "command_executed")
        assert hasattr(launcher, "command_error")

    def test_set_current_shot(self, launcher: CommandLauncher, test_shot: Shot) -> None:
        """Test setting current shot."""
        launcher.set_current_shot(test_shot)
        assert launcher.current_shot == test_shot

    def test_set_current_shot_none(self, launcher: CommandLauncher) -> None:
        """Test clearing current shot."""
        launcher.set_current_shot(None)
        assert launcher.current_shot is None

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_nuke(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching Nuke application."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch Nuke
        result = launcher.launch_app("nuke")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert (
            "gnome-terminal" in call_args
            or "xterm" in call_args
            or "konsole" in call_args
            or "x-terminal-emulator" in call_args
            or "/bin/bash" in call_args
        )
        assert "nuke" in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_nuke_with_raw_plate(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching Nuke with raw plate."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch Nuke with raw plate
        result = launcher.launch_app("nuke", include_raw_plate=True)

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "nuke" in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_3de(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching 3DE application."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch 3DE
        result = launcher.launch_app("3de")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "3de" in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_3de_with_scene(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_scene: ThreeDEScene,
        qtbot: QtBot,
    ) -> None:
        """Test launching 3DE with specific scene."""
        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch 3DE with scene
        result = launcher.launch_app_with_scene("3de", test_scene)

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "3de" in " ".join(call_args)
        assert str(test_scene.scene_path) in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_maya(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching Maya application."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch Maya
        result = launcher.launch_app("maya")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "maya" in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_rv(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test launching RV application."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch RV
        result = launcher.launch_app("rv")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "rv" in " ".join(call_args)

    def test_no_shot_context_error(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test error when no shot context is set."""
        # Try to launch without shot (no shot set)
        result = launcher.launch_app("nuke")

        # Should return False when no shot is set
        assert result is False

    @pytest.mark.allow_dialogs  # Error dialog is expected side-effect
    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_subprocess_failure(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test handling subprocess failure."""
        launcher.set_current_shot(test_shot)

        # Setup mock to simulate failure for all terminal types
        mock_popen.side_effect = FileNotFoundError("terminal not found")

        # Launch app should fail
        result = launcher.launch_app("nuke")

        # Should return False when subprocess fails
        assert result is False

        # Wait for any pending Qt events (QTimer won't fire due to failure, but process events)
        process_qt_events()

        # Verify subprocess was attempted
        assert mock_popen.called

    @pytest.mark.allow_dialogs  # May show warning dialog
    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("command_launcher.EnvironmentManager.detect_terminal", return_value=None)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_headless_mode_when_no_terminal(
        self,
        mock_popen: MagicMock,
        mock_detect_terminal: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test that launches succeed in headless mode when no terminal is available."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch app - should succeed even without terminal
        result = launcher.launch_app("nuke")

        # Verify launch was successful (headless mode)
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback to complete
        process_qt_events()

        # Verify subprocess was called with direct bash (headless)
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == "/bin/bash"
        assert "-ilc" in call_args
        assert "nuke" in " ".join(call_args)

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_gui_app_with_background_setting_enabled(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test that GUI apps are backgrounded when setting is enabled."""
        # Import modules needed for mocking
        import sys
        import types

        # Create mock modules (same as launcher fixture)
        mock_raw_plate_finder = types.ModuleType("raw_plate_finder")
        mock_raw_plate_finder.RawPlateFinder = TestRawPlateFinder
        sys.modules["raw_plate_finder"] = mock_raw_plate_finder

        mock_nuke_script_generator = types.ModuleType("nuke_script_generator")
        mock_nuke_script_generator.NukeScriptGenerator = TestNukeScriptGenerator
        sys.modules["nuke_script_generator"] = mock_nuke_script_generator

        mock_threede_latest_finder = types.ModuleType("threede_latest_finder")
        mock_threede_latest_finder.ThreeDELatestFinder = TestThreeDELatestFinder
        sys.modules["threede_latest_finder"] = mock_threede_latest_finder

        mock_maya_latest_finder = types.ModuleType("maya_latest_finder")
        mock_maya_latest_finder.MayaLatestFinder = TestMayaLatestFinder
        sys.modules["maya_latest_finder"] = mock_maya_latest_finder

        # Mock is_ws_available
        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        # Create mock settings manager with background_gui_apps enabled
        mock_settings = MagicMock()
        mock_settings.get_background_gui_apps.return_value = True

        # Create launcher with mock settings
        launcher = CommandLauncher(settings_manager=mock_settings)
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch 3DE (a GUI app)
        result = launcher.launch_app("3de")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)

        # Verify the command contains background wrapping
        assert "disown" in command_str
        assert "exit" in command_str

    @patch.object(
        CommandLauncher, "_validate_workspace_before_launch", return_value=True
    )
    @patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False)
    @patch("launch.process_executor.subprocess.Popen")
    def test_launch_gui_app_without_background_setting(
        self,
        mock_popen: MagicMock,
        mock_rez: MagicMock,
        mock_validate: MagicMock,
        launcher: CommandLauncher,
        test_shot: Shot,
        qtbot: QtBot,
    ) -> None:
        """Test that GUI apps are NOT backgrounded when setting is disabled (default)."""
        launcher.set_current_shot(test_shot)

        # Setup mock
        mock_popen.return_value = MagicMock()

        # Launch 3DE (a GUI app) - default setting is False
        result = launcher.launch_app("3de")

        # Verify launch was successful
        assert result is True

        # Wait for QTimer.singleShot(100ms) callback
        process_qt_events()

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        command_str = " ".join(call_args)

        # Verify the command does NOT contain background wrapping
        assert "disown" not in command_str


class TestCommandLauncherSignals:
    """Test CommandLauncher signal emissions."""

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch) -> CommandLauncher:
        """Create CommandLauncher with test doubles."""
        # Mock the modules that will be imported in __init__
        import sys
        import types

        # Create mock modules
        mock_raw_plate_finder = types.ModuleType("raw_plate_finder")
        mock_raw_plate_finder.RawPlateFinder = TestRawPlateFinder
        sys.modules["raw_plate_finder"] = mock_raw_plate_finder

        mock_nuke_script_generator = types.ModuleType("nuke_script_generator")
        mock_nuke_script_generator.NukeScriptGenerator = TestNukeScriptGenerator
        sys.modules["nuke_script_generator"] = mock_nuke_script_generator

        mock_threede_latest_finder = types.ModuleType("threede_latest_finder")
        mock_threede_latest_finder.ThreeDELatestFinder = TestThreeDELatestFinder
        sys.modules["threede_latest_finder"] = mock_threede_latest_finder

        mock_maya_latest_finder = types.ModuleType("maya_latest_finder")
        mock_maya_latest_finder.MayaLatestFinder = TestMayaLatestFinder
        sys.modules["maya_latest_finder"] = mock_maya_latest_finder

        # Mock is_ws_available to return True (ws isn't available in dev environment)
        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        return CommandLauncher()

    def test_signal_data_format(self, launcher: CommandLauncher, qtbot: QtBot) -> None:
        """Test basic launcher functionality."""
        shot = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        launcher.set_current_shot(shot)

        with (
            patch.object(
                CommandLauncher, "_validate_workspace_before_launch", return_value=True
            ),
            patch("launch.process_executor.subprocess.Popen") as mock_popen,
            patch("command_launcher.EnvironmentManager.is_rez_available", return_value=False),
        ):
            mock_popen.return_value = MagicMock()

            # Launch should succeed
            result = launcher.launch_app("nuke")
            assert result is True

            # Wait for QTimer.singleShot(100ms) callback to complete
            process_qt_events()

            # Should have called Popen
            assert mock_popen.called


class TestVerificationTimeoutCounter:
    """Test verification timeout counter behavior.

    VFX apps can take 30-60+ seconds to boot (Rez resolution + plugin scanning).
    A single timeout doesn't indicate failure. But repeated timeouts suggest
    terminal detection issues, so we reset the environment cache after 3 consecutive
    timeouts to allow fresh terminal detection on next launch.
    """

    @pytest.fixture
    def launcher(self, monkeypatch: pytest.MonkeyPatch) -> CommandLauncher:
        """Create CommandLauncher for verification timeout testing."""
        import sys
        import types

        # Create mock modules
        mock_raw_plate_finder = types.ModuleType("raw_plate_finder")
        mock_raw_plate_finder.RawPlateFinder = TestRawPlateFinder
        sys.modules["raw_plate_finder"] = mock_raw_plate_finder

        mock_nuke_script_generator = types.ModuleType("nuke_script_generator")
        mock_nuke_script_generator.NukeScriptGenerator = TestNukeScriptGenerator
        sys.modules["nuke_script_generator"] = mock_nuke_script_generator

        mock_threede_latest_finder = types.ModuleType("threede_latest_finder")
        mock_threede_latest_finder.ThreeDELatestFinder = TestThreeDELatestFinder
        sys.modules["threede_latest_finder"] = mock_threede_latest_finder

        mock_maya_latest_finder = types.ModuleType("maya_latest_finder")
        mock_maya_latest_finder.MayaLatestFinder = TestMayaLatestFinder
        sys.modules["maya_latest_finder"] = mock_maya_latest_finder

        from launch import EnvironmentManager
        monkeypatch.setattr(EnvironmentManager, "is_ws_available", lambda _self: True)

        return CommandLauncher()

    def test_single_timeout_does_not_reset_cache(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test that a single verification timeout does not reset the env cache."""
        # Initialize counter
        launcher._consecutive_timeout_count = 0

        # Mock reset_cache to verify it's NOT called
        with patch.object(launcher.env_manager, "reset_cache") as mock_reset:
            launcher._on_app_verification_timeout("nuke")

            # Counter should increment
            assert launcher._consecutive_timeout_count == 1

            # Cache should NOT be reset after single timeout
            mock_reset.assert_not_called()

    def test_three_timeouts_triggers_cache_reset(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test that 3 consecutive timeouts trigger environment cache reset."""
        launcher._consecutive_timeout_count = 0

        with patch.object(launcher.env_manager, "reset_cache") as mock_reset:
            # First two timeouts don't reset
            launcher._on_app_verification_timeout("nuke")
            launcher._on_app_verification_timeout("nuke")
            assert mock_reset.call_count == 0
            assert launcher._consecutive_timeout_count == 2

            # Third timeout triggers reset
            launcher._on_app_verification_timeout("nuke")
            mock_reset.assert_called_once()
            # Counter should be reset after cache reset
            assert launcher._consecutive_timeout_count == 0

    def test_successful_verification_resets_counter(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test that successful app verification resets the timeout counter."""
        # Simulate 2 prior timeouts
        launcher._consecutive_timeout_count = 2

        # Successful verification should reset counter
        launcher._on_app_verified("nuke", 12345)

        assert launcher._consecutive_timeout_count == 0

    def test_successful_verification_prevents_cache_reset(
        self, launcher: CommandLauncher, qtbot: QtBot
    ) -> None:
        """Test that a successful verification breaks the timeout sequence."""
        launcher._consecutive_timeout_count = 0

        with patch.object(launcher.env_manager, "reset_cache") as mock_reset:
            # Two timeouts
            launcher._on_app_verification_timeout("nuke")
            launcher._on_app_verification_timeout("nuke")

            # Successful launch
            launcher._on_app_verified("nuke", 12345)
            assert launcher._consecutive_timeout_count == 0

            # Third timeout starts fresh sequence
            launcher._on_app_verification_timeout("nuke")
            assert launcher._consecutive_timeout_count == 1

            # Cache should NOT be reset (only 1 timeout since last success)
            mock_reset.assert_not_called()
