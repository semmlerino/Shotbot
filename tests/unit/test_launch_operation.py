"""Tests for LaunchOperation.execute() in isolation.

LaunchOperation is the execution unit that takes a fully-built command string
and handles: workspace resolution, ws/Rez wrapping, logging, and terminal
spawning via ProcessExecutor.  All external dependencies are injected, making
it straightforward to test without Qt infrastructure.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from launch.launch_operation import LaunchOperation


pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers / shared doubles
# ---------------------------------------------------------------------------


def _make_operation(
    app_name: str = "nuke",
    command: str = "nuke",
    workspace_path: str | None = "/shows/TEST/shots/seq01/sq0010",
    *,
    current_shot=None,
    emit_error=None,
    env_manager=None,
    process_executor=None,
    settings_manager=None,
    nuke_env=None,
    command_prefix: str = "",
    log_suffix: str = "",
    error_context: str = "",
) -> LaunchOperation:
    """Construct a LaunchOperation with sensible defaults for unit tests."""
    if emit_error is None:
        emit_error = MagicMock()
    if env_manager is None:
        env_manager = _make_env_manager()
    if process_executor is None:
        process_executor = _make_process_executor()
    if settings_manager is None:
        settings_manager = _make_settings_manager()
    if nuke_env is None:
        nuke_env = MagicMock()

    return LaunchOperation(
        app_name=app_name,
        command=command,
        workspace_path=workspace_path,
        env_manager=env_manager,
        process_executor=process_executor,
        settings_manager=settings_manager,
        nuke_env=nuke_env,
        current_shot=current_shot,
        emit_error=emit_error,
        command_prefix=command_prefix,
        log_suffix=log_suffix,
        error_context=error_context,
    )


def _make_env_manager(
    *,
    ws_available: bool = True,
    terminal: str | None = "gnome-terminal",
    rez_packages: list[str] | None = None,
    should_wrap_rez: bool = True,
) -> MagicMock:
    em = MagicMock()
    em.is_ws_available.return_value = ws_available
    em.detect_terminal.return_value = terminal
    em.get_rez_packages.return_value = (
        rez_packages if rez_packages is not None else ["nuke-13"]
    )
    em.should_wrap_with_rez.return_value = should_wrap_rez
    return em


def _make_process_executor(
    *,
    spawn_result: object = MagicMock(),  # non-None = success
    is_gui: bool = False,
) -> MagicMock:
    pe = MagicMock()
    pe.execute_in_new_terminal.return_value = spawn_result
    pe.is_gui_app.return_value = is_gui
    return pe


def _make_settings_manager(*, background_gui: bool = False) -> MagicMock:
    sm = MagicMock()
    sm.launch.get_background_gui_apps.return_value = background_gui
    return sm


# ---------------------------------------------------------------------------
# execute() — workspace resolution
# ---------------------------------------------------------------------------


class TestExecuteWorkspaceResolution:
    """Workspace path can be provided directly or resolved from current_shot."""

    def test_explicit_workspace_path_is_used(self, mocker) -> None:
        """When workspace_path is provided it is used without touching current_shot."""
        from config import RezMode

        em = _make_env_manager()
        pe = _make_process_executor()

        mocker.patch("launch.launch_operation.Config.Launch.REZ_MODE", RezMode.DISABLED)
        mock_ws = mocker.patch(
            "launch.launch_operation.build_workspace_command", return_value="cmd"
        )
        mocker.patch("launch.launch_operation.add_logging", return_value="cmd")
        mocker.patch("launch.launch_operation.validate_path", side_effect=lambda p: p)
        mocker.patch(
            "commands.nuke_commands.build_nuke_environment_prefix", return_value=""
        )
        op = _make_operation(
            workspace_path="/explicit/path",
            env_manager=em,
            process_executor=pe,
        )
        op.execute()

        mock_ws.assert_called_once()
        assert "/explicit/path" in mock_ws.call_args[0][0]

    def test_no_workspace_and_no_shot_emits_error_and_returns_false(self) -> None:
        """execute() returns False and emits error when both workspace_path and shot are None."""
        emit_error = MagicMock()
        op = _make_operation(
            workspace_path=None, current_shot=None, emit_error=emit_error
        )

        result = op.execute()

        assert result is False
        emit_error.assert_called_once()
        assert "no shot" in emit_error.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# execute() — invalid workspace path
# ---------------------------------------------------------------------------


class TestExecuteInvalidWorkspacePath:
    """validate_path raises ValueError for dangerous paths."""

    def test_dangerous_workspace_path_emits_error_and_returns_false(self, mocker) -> None:
        from config import RezMode

        emit_error = MagicMock()
        em = _make_env_manager()

        mocker.patch("launch.launch_operation.Config.Launch.REZ_MODE", RezMode.DISABLED)
        mocker.patch(
            "launch.command_builder.validate_path",
            side_effect=ValueError("dangerous chars"),
        )
        mocker.patch(
            "commands.nuke_commands.build_nuke_environment_prefix", return_value=""
        )
        op = _make_operation(
            workspace_path="/bad/path; evil",
            env_manager=em,
            emit_error=emit_error,
        )
        result = op.execute()

        assert result is False
        emit_error.assert_called_once()


# ---------------------------------------------------------------------------
# execute() — command length guard
# ---------------------------------------------------------------------------


class TestExecuteCommandLengthGuard:
    """Commands exceeding MAX_COMMAND_LENGTH are rejected before spawning."""

    def test_oversized_command_emits_error_and_returns_false(self, mocker) -> None:
        from config import RezMode

        emit_error = MagicMock()
        long_command = "x" * (LaunchOperation.MAX_COMMAND_LENGTH + 1)
        pe = _make_process_executor()
        em = _make_env_manager()

        mocker.patch("launch.launch_operation.Config.Launch.REZ_MODE", RezMode.DISABLED)
        mocker.patch("launch.launch_operation.validate_path", side_effect=lambda p: p)
        mocker.patch(
            "launch.launch_operation.build_workspace_command",
            return_value=long_command,
        )
        mocker.patch(
            "launch.launch_operation.add_logging",
            return_value=long_command,
        )
        mocker.patch(
            "commands.nuke_commands.build_nuke_environment_prefix", return_value=""
        )
        op = _make_operation(
            process_executor=pe,
            env_manager=em,
            emit_error=emit_error,
        )
        result = op.execute()

        assert result is False
        emit_error.assert_called_once()
        pe.execute_in_new_terminal.assert_not_called()


# ---------------------------------------------------------------------------
# execute() — background wrapping for GUI apps
# ---------------------------------------------------------------------------


class TestExecuteBackgroundWrapping:
    """GUI apps are background-wrapped when the setting is enabled."""

    def test_gui_app_backgrounded_when_setting_enabled(self, mocker) -> None:
        from config import RezMode

        pe = _make_process_executor(is_gui=True)
        sm = _make_settings_manager(background_gui=True)
        em = _make_env_manager()

        mocker.patch("launch.launch_operation.Config.Launch.REZ_MODE", RezMode.DISABLED)
        mocker.patch("launch.launch_operation.validate_path", side_effect=lambda p: p)
        mocker.patch(
            "launch.launch_operation.build_workspace_command",
            return_value="base_cmd",
        )
        mocker.patch("launch.launch_operation.add_logging", side_effect=lambda c, _cfg, **kw: c)
        mocker.patch(
            "commands.nuke_commands.build_nuke_environment_prefix", return_value=""
        )
        mock_bg = mocker.patch(
            "launch.launch_operation.wrap_for_background", return_value="bg_cmd"
        )
        op = _make_operation(
            app_name="3de",
            process_executor=pe,
            settings_manager=sm,
            env_manager=em,
        )
        result = op.execute()

        assert result is True
        mock_bg.assert_called_once()

    def test_gui_app_not_backgrounded_when_setting_disabled(self, mocker) -> None:
        from config import RezMode

        pe = _make_process_executor(is_gui=True)
        sm = _make_settings_manager(background_gui=False)
        em = _make_env_manager()

        mocker.patch("launch.launch_operation.Config.Launch.REZ_MODE", RezMode.DISABLED)
        mocker.patch("launch.launch_operation.validate_path", side_effect=lambda p: p)
        mocker.patch(
            "launch.launch_operation.build_workspace_command",
            return_value="base_cmd",
        )
        mocker.patch("launch.launch_operation.add_logging", side_effect=lambda c, _cfg, **kw: c)
        mocker.patch(
            "commands.nuke_commands.build_nuke_environment_prefix", return_value=""
        )
        mock_bg = mocker.patch("launch.launch_operation.wrap_for_background")
        op = _make_operation(
            app_name="3de",
            process_executor=pe,
            settings_manager=sm,
            env_manager=em,
        )
        op.execute()

        mock_bg.assert_not_called()


# ---------------------------------------------------------------------------
# apply_file_result static method
# ---------------------------------------------------------------------------


class TestApplyFileResult:
    """LaunchOperation.apply_file_result delegates to append_scene_to_command."""

    def test_none_result_returns_command_unchanged(self) -> None:
        emit_error = MagicMock()
        result = LaunchOperation.apply_file_result("3de", "base_cmd", None, emit_error)

        assert result == "base_cmd"
        emit_error.assert_not_called()

    def test_valid_path_result_appended_for_3de(self) -> None:
        emit_error = MagicMock()
        scene = Path("/shows/TEST/shots/seq01/sq0010/3de/artist_plate_v001.3de")

        result = LaunchOperation.apply_file_result("3de", "3de_cmd", scene, emit_error)

        assert result is not None
        assert str(scene) in result
        assert "SGTK_FILE_TO_OPEN" in result
        emit_error.assert_not_called()

    def test_invalid_path_calls_emit_error_and_returns_none(self) -> None:
        emit_error = MagicMock()
        bad_scene = Path("/shows/TEST/shot; malicious")

        result = LaunchOperation.apply_file_result(
            "3de", "3de_cmd", bad_scene, emit_error
        )

        assert result is None
        emit_error.assert_called_once()


# ---------------------------------------------------------------------------
# append_scene_to_command static method
# ---------------------------------------------------------------------------


class TestAppendSceneToCommand:
    """LaunchOperation.append_scene_to_command builds app-specific command fragments."""

    def test_3de_command_includes_scripts_export_and_sgtk_context(self) -> None:
        emit_error = MagicMock()
        scene = Path("/shows/TEST/shots/seq01/sq0010/3de/artist_plate_v001.3de")

        result = LaunchOperation.append_scene_to_command(
            "3de", "3de", scene, emit_error
        )

        assert result is not None
        assert "PYTHON_CUSTOM_SCRIPTS_3DE4" in result
        assert "SGTK_FILE_TO_OPEN" in result
        assert str(scene) in result
        assert "-open" in result
        emit_error.assert_not_called()

    def test_maya_command_includes_sgtk_file_to_open(self) -> None:
        emit_error = MagicMock()
        scene = Path("/shows/TEST/shots/seq01/sq0010/maya/artist_plate_v001.ma")

        result = LaunchOperation.append_scene_to_command(
            "maya", "maya", scene, emit_error
        )

        assert result is not None
        assert "SGTK_FILE_TO_OPEN" in result
        assert str(scene) in result
        emit_error.assert_not_called()

    def test_invalid_path_calls_emit_error_and_returns_none(self) -> None:
        emit_error = MagicMock()
        bad_scene = Path("/shows/TEST/shots/seq01/sq0010/3de/scene; rm -rf /")

        result = LaunchOperation.append_scene_to_command(
            "3de", "3de", bad_scene, emit_error
        )

        assert result is None
        emit_error.assert_called_once()

    def test_unsupported_app_returns_original_command(self) -> None:
        emit_error = MagicMock()
        scene = Path("/shows/TEST/shots/seq01/sq0010/rv/output.mov")

        result = LaunchOperation.append_scene_to_command(
            "rv", "rv_cmd", scene, emit_error
        )

        assert result == "rv_cmd"
        emit_error.assert_not_called()


# ---------------------------------------------------------------------------
# execute() — per-app Rez bypass
# ---------------------------------------------------------------------------


class TestRezBypass:
    """Per-app Rez bypass via Config.Launch.REZ_BYPASS_APPS."""

    def test_app_in_bypass_set_skips_rez_wrap(self, mocker) -> None:
        """REZ_BYPASS_APPS = {"maya"} → Maya launch skips wrap_with_rez."""
        from config import RezMode

        mocker.patch("launch.launch_operation.Config.Launch.REZ_MODE", RezMode.AUTO)
        mocker.patch("launch.launch_operation.Config.Launch.REZ_BYPASS_APPS", {"maya"})
        mocker.patch("launch.launch_operation.validate_path", side_effect=lambda p: p)
        mocker.patch(
            "launch.launch_operation.build_workspace_command",
            return_value="ws_cmd",
        )
        mocker.patch("launch.launch_operation.add_logging", side_effect=lambda c, _cfg, **kw: c)
        mocker.patch(
            "commands.nuke_commands.build_nuke_environment_prefix", return_value=""
        )
        mock_rez = mocker.patch("launch.launch_operation.wrap_with_rez")

        em = _make_env_manager()
        pe = _make_process_executor()
        op = _make_operation(
            app_name="maya",
            env_manager=em,
            process_executor=pe,
        )
        result = op.execute()

        assert result is True
        mock_rez.assert_not_called()

    def test_empty_bypass_set_still_wraps_with_rez(self, mocker) -> None:
        """Empty REZ_BYPASS_APPS → all apps still get Rez-wrapped."""
        from config import RezMode

        mocker.patch("launch.launch_operation.Config.Launch.REZ_MODE", RezMode.AUTO)
        mocker.patch("launch.launch_operation.Config.Launch.REZ_BYPASS_APPS", set())
        mocker.patch("launch.launch_operation.validate_path", side_effect=lambda p: p)
        mocker.patch(
            "launch.launch_operation.build_workspace_command",
            return_value="ws_cmd",
        )
        mocker.patch("launch.launch_operation.add_logging", side_effect=lambda c, _cfg, **kw: c)
        mocker.patch(
            "commands.nuke_commands.build_nuke_environment_prefix", return_value=""
        )
        mock_rez = mocker.patch(
            "launch.launch_operation.wrap_with_rez", return_value="rez_cmd"
        )

        em = _make_env_manager()
        pe = _make_process_executor()
        op = _make_operation(
            app_name="nuke",
            env_manager=em,
            process_executor=pe,
        )
        result = op.execute()

        assert result is True
        mock_rez.assert_called_once()
