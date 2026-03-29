"""LaunchOperation — a single traceable unit for executing a prepared launch.

Encapsulates the execute-a-launch flow once the command string is ready:
  - workspace path resolution
  - environment wrapping (ws, Rez)
  - logging redirection
  - terminal spawning via ProcessExecutor

All dependencies are passed explicitly; this module has no import from
command_launcher so the two can evolve independently.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, final

from commands import nuke_commands
from config import Config, RezMode
from launch.command_builder import (
    add_logging,
    build_workspace_command,
    validate_path,
    wrap_for_background,
    wrap_with_rez,
)
from logging_mixin import get_module_logger
from managers.notification_manager import NotificationManager


if TYPE_CHECKING:
    from launch.environment_manager import EnvironmentManager
    from launch.process_executor import ProcessExecutor
    from managers.settings_manager import SettingsManager
    from nuke import NukeLaunchHandler
    from type_definitions import Shot


logger = get_module_logger(__name__)


@final
class LaunchOperation:
    """Execute a prepared launch once the command string is ready.

    Entry points in CommandLauncher build the DCC-specific command string,
    then hand off to LaunchOperation.execute() for the common tail:
    workspace-command wrapping, Rez wrapping, logging redirection, and
    terminal spawning.

    All dependencies are injected; this class does not import CommandLauncher.
    """

    # Maximum command length (bytes) — gnome-terminal buffer is ~8 KB.
    MAX_COMMAND_LENGTH: int = 8000

    def __init__(
        self,
        app_name: str,
        command: str,
        workspace_path: str | None,
        env_manager: EnvironmentManager,
        process_executor: ProcessExecutor,
        settings_manager: SettingsManager,
        nuke_env: NukeLaunchHandler,
        current_shot: Shot | None,
        emit_error: Callable[[str], None],
        # Optional overrides for non-standard entry points:
        command_prefix: str = "",
        log_suffix: str = "",
        error_context: str = "",
    ) -> None:
        """Construct a launch operation ready to be executed.

        Args:
            app_name: Application name (e.g. "nuke", "3de", "maya", "rv").
            command: DCC command string with any scene/file path already embedded.
            workspace_path: Shot workspace directory.  If None, falls back to
                ``current_shot.workspace_path`` at execute time.
            env_manager: Provides Rez and ws availability checks.
            process_executor: Spawns the terminal process.
            settings_manager: Read-only access to launch settings.
            nuke_env: Supplies Nuke environment variable prefixes.
            current_shot: Shot in context (used when workspace_path is None).
            emit_error: Callback that logs and surfaces error messages to the UI.
            command_prefix: Shell fragment inserted between ws-cd and env fixes
                (e.g. ``"export SGTK_FILE_TO_OPEN=... && "``).
            log_suffix: Appended to the debug command log (e.g. ``" (Scene by: …)"``).
            error_context: Appended to the terminal-spawn failure message
                (e.g. ``" with scene"``).

        """
        self._app_name = app_name
        self._command = command
        self._workspace_path = workspace_path
        self._env_manager = env_manager
        self._process_executor = process_executor
        self._settings_manager = settings_manager
        self._nuke_env = nuke_env
        self._current_shot = current_shot
        self._emit_error = emit_error
        self._command_prefix = command_prefix
        self._log_suffix = log_suffix
        self._error_context = error_context

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute(self) -> bool:
        """Complete the launch: ws wrap, Rez wrap, logging, and execute.

        This is the single dispatch point shared between the sync (cache hit)
        and async (cache miss) paths and all public launch methods.

        Returns:
            True if launch succeeded, False otherwise.

        """
        app_name = self._app_name
        command = self._command

        # Resolve workspace path
        workspace_path = self._workspace_path
        if workspace_path is None:
            if self._current_shot is None:
                self._emit_error("Cannot launch - no shot selected")
                return False
            workspace_path = self._current_shot.workspace_path

        # Pre-flight: confirm ws command is available
        if not self._env_manager.is_ws_available():
            self._emit_error(
                "Workspace command 'ws' not found. "
                "Ensure workspace tools are installed and on PATH."
            )
            return False

        # Build the full app command: prefix + Nuke env fixes + DCC command
        try:
            safe_workspace_path = validate_path(workspace_path)
            env_fixes = nuke_commands.build_nuke_environment_prefix(
                self._nuke_env, app_name
            )
            app_command = f"{self._command_prefix}{env_fixes}{command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        if Config.Launch.REZ_MODE != RezMode.DISABLED:
            if app_name in Config.Launch.REZ_BYPASS_APPS:
                logger.debug(
                    "Rez bypass enabled for %s — skipping rez env wrap", app_name
                )
            else:
                rez_packages = self._env_manager.get_rez_packages(app_name, Config)
                if not rez_packages:
                    self._emit_error(
                        f"Cannot launch {app_name}: no Rez packages are configured for this application."
                    )
                    return False
                if not self._env_manager.should_wrap_with_rez(Config):
                    self._emit_error(
                        f"Cannot launch {app_name}: Rez is required, but the 'rez' command was not found on PATH."
                    )
                    return False

                app_command = wrap_with_rez(app_command, rez_packages)

        full_command = build_workspace_command(safe_workspace_path, app_command)
        full_command = add_logging(full_command, Config, app_name=app_name)

        logger.debug(
            "Constructed command for %s:\n  Command: %r\n  Length: %d chars\n  Workspace: %s%s",
            app_name,
            full_command,
            len(full_command),
            workspace_path,
            self._log_suffix,
        )

        return self._launch_in_new_terminal(full_command, app_name, self._error_context)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _launch_in_new_terminal(
        self,
        full_command: str,
        app_name: str,
        error_context: str = "",
    ) -> bool:
        """Spawn the command in a new terminal window.

        Delegates to ProcessExecutor.  Supports headless mode (no terminal).

        Args:
            full_command: Complete shell command to execute.
            app_name: Application name (for verification and error messages).
            error_context: Appended to the failure error message.

        Returns:
            True if the process was spawned successfully, False otherwise.

        """
        # Background-wrap GUI apps when the setting is enabled
        if (
            self._process_executor.is_gui_app(app_name)
            and self._settings_manager.launch.get_background_gui_apps()
        ):
            full_command = wrap_for_background(full_command)
            logger.info(
                "Backgrounding %s — terminal will close immediately", app_name
            )

        # Guard against silent truncation by terminal emulators
        cmd_length = len(full_command)
        if cmd_length > self.MAX_COMMAND_LENGTH:
            self._emit_error(
                f"Cannot launch {app_name}: Command too long "
                f"({cmd_length} chars, max {self.MAX_COMMAND_LENGTH}). "
                "Try shorter paths or fewer rez packages."
            )
            return False

        terminal = self._env_manager.detect_terminal()

        process = self._process_executor.execute_in_new_terminal(
            full_command, app_name, terminal
        )

        if process is None:
            self._emit_error(f"Failed to launch {app_name}{error_context}")
            NotificationManager.error("Launch Failed", f"{app_name} failed to start")
            self._env_manager.reset_cache()
            return False

        return True

    @staticmethod
    def apply_file_result(
        app_name: str,
        command: str,
        file_result: Path | None,
        emit_error: Callable[[str], None],
    ) -> str | None:
        """Apply a scene-file search result to the launch command.

        Static so callers (CommandLauncher entry points and _on_search_result_ready)
        can use it before constructing a LaunchOperation.

        Args:
            app_name: Application name ("3de" or "maya").
            command: Current command string.
            file_result: Scene path found by the async search, or None.
            emit_error: Error callback used by append_scene_to_command.

        Returns:
            Updated command string, or None if appending failed.

        """
        if file_result:
            return LaunchOperation.append_scene_to_command(
                app_name, command, file_result, emit_error
            )
        return command

    @staticmethod
    def append_scene_to_command(
        app_name: str,
        command: str,
        scene_path: Path,
        emit_error: Callable[[str], None],
    ) -> str | None:
        """Append a scene file to a launch command.

        Validates the scene path and builds the app-specific command fragment.
        Calls emit_error and returns None when the path is invalid.

        Args:
            app_name: Application name ("3de" or "maya").
            command: Base command string to append to.
            scene_path: Scene file path to embed.
            emit_error: Error callback invoked on invalid paths.

        Returns:
            Updated command string, or None if path validation failed.

        """
        from commands import maya_commands  # lazy — avoids circular import risk

        try:
            safe_scene_path = validate_path(str(scene_path))
        except ValueError as e:
            emit_error(
                f"Cannot launch {app_name.upper()}: Invalid scene path '{scene_path}': {e!s}"
            )
            return None

        if app_name == "3de":
            from commands.threede_commands import build_threede_scripts_export

            tde_scripts_export = build_threede_scripts_export(Config.Paths.SCRIPTS_DIR)
            sgtk_export = f"export SGTK_FILE_TO_OPEN={safe_scene_path} && "
            return f"{tde_scripts_export}{sgtk_export}{command} -open {safe_scene_path}"

        if app_name == "maya":
            updated = maya_commands.build_maya_context_command(
                command, safe_scene_path, skip_bootstrap=Config.DCC.MAYA_SKIP_CONTEXT_BOOTSTRAP
            )
            return f"export SGTK_FILE_TO_OPEN={safe_scene_path} && {updated}"

        # Unsupported app — caller should not reach this path
        logger.warning(
            "append_scene_to_command called for unsupported app: %s", app_name
        )
        return command
