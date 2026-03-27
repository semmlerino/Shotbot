"""App-specific command handlers for CommandLauncher.

Each handler encapsulates the per-DCC command-building logic used by
launch_app.  Adding a new DCC means adding one class
and one dict entry in CommandLauncher._app_handlers.

AppHandler is a Protocol (structural subtyping) — no base class required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from commands import rv_commands
from commands.maya_commands import build_maya_context_command
from commands.threede_commands import build_threede_scripts_export


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from cache.latest_file_cache import LatestFileCache
    from launch.command_launcher import LaunchContext
    from nuke.simple_launcher import SimpleNukeLauncher
    from type_definitions import Shot


# Named sentinels re-exported from command_launcher to avoid circular imports.
# Handlers return these directly instead of (None, True) / (None, False) magic.
_ASYNC_IN_PROGRESS: tuple[None, bool] = (None, True)
_LAUNCH_ERROR: tuple[None, bool] = (None, False)


class AppHandler(Protocol):
    """Protocol for per-DCC command building in launch_with_file and launch_app."""

    def build_file_command(
        self,
        base_cmd: str,
        safe_file_path: str,
    ) -> str:
        """Build the full shell command for launch_with_file.

        Args:
            base_cmd: App base command from Config.APPS (e.g. "nuke").
            safe_file_path: Shell-safe, validated file path string.

        Returns:
            Complete shell command string (without ws/rez wrapping).
        """
        ...

    def needs_sgtk_file_to_open(self) -> bool:
        """Return True if this app needs SGTK_FILE_TO_OPEN set before launch."""
        ...

    def build_launch_command(
        self,
        base_cmd: str,
        context: LaunchContext,
        current_shot: Shot,
    ) -> tuple[str | None, bool]:
        """Build the app-specific command for launch_app.

        Handles any DCC-specific logic: Nuke workspace scripts, 3DE/Maya async
        file search, RV sequence path, etc.

        Args:
            base_cmd: App base command from Config.APPS (e.g. "nuke").
            context: Launch context carrying per-DCC option flags.
            current_shot: The currently selected shot (precondition: not None).

        Returns:
            (command, is_async) where:
            - (str, False)   — command built successfully; proceed with launch.
            - (None, True)   — async file search started; caller must return True.
            - (None, False)  — error emitted; caller must return False.
        """
        ...


class NukeAppHandler:
    """Handler for Nuke launches."""

    def __init__(
        self,
        scripts_dir: str,
        nuke_launcher: SimpleNukeLauncher,
        emit_error: Callable[[str], None],
    ) -> None:
        self._scripts_dir: str = scripts_dir
        self._nuke_launcher: SimpleNukeLauncher = nuke_launcher
        self._emit_error: Callable[[str], None] = emit_error

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        nuke_path_export = f"export NUKE_PATH={self._scripts_dir}:$NUKE_PATH && "
        return f"{nuke_path_export}{base_cmd} {safe_file_path}"

    def needs_sgtk_file_to_open(self) -> bool:
        return True

    def build_launch_command(
        self,
        base_cmd: str,
        context: LaunchContext,
        current_shot: Shot,
    ) -> tuple[str | None, bool]:
        command = base_cmd
        has_workspace_options = context.open_latest_scene or context.create_new_file
        if has_workspace_options:
            if not context.selected_plate:
                self._emit_error("No plate selected. Please select a plate space.")
                return _LAUNCH_ERROR
            if context.create_new_file:
                command, _ = self._nuke_launcher.create_new_version(
                    current_shot, context.selected_plate
                )
            else:
                command, _ = self._nuke_launcher.open_latest_script(
                    current_shot, context.selected_plate, create_if_missing=True
                )
            if not command:
                self._emit_error("Nuke launch aborted - see log messages above")
                return _LAUNCH_ERROR
        return command, False


class ThreeDEAppHandler:
    """Handler for 3DE launches."""

    def __init__(
        self,
        scripts_dir: str,
        cache_manager: LatestFileCache,
        start_async_search: Callable[[str, LaunchContext, str], None],
        apply_file_result: Callable[[str, str, Path | None], str | None],
        emit_error: Callable[[str], None],
    ) -> None:
        self._scripts_dir: str = scripts_dir
        self._cache_manager: LatestFileCache = cache_manager
        self._start_async_search: Callable[[str, LaunchContext, str], None] = (
            start_async_search
        )
        self._apply_file_result: Callable[[str, str, Path | None], str | None] = (
            apply_file_result
        )
        self._emit_error: Callable[[str], None] = emit_error

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        tde_scripts_export = build_threede_scripts_export(self._scripts_dir)
        return f"{tde_scripts_export}{base_cmd} -open {safe_file_path}"

    def needs_sgtk_file_to_open(self) -> bool:
        return True

    def build_launch_command(
        self,
        base_cmd: str,
        context: LaunchContext,
        current_shot: Shot,
    ) -> tuple[str | None, bool]:
        command = base_cmd
        if not context.open_latest_threede:
            return command, False

        workspace = current_shot.workspace_path
        cache_result = self._cache_manager.get_latest_file_cache_result(
            workspace, "threede"
        )

        if cache_result.status == "miss":
            self._start_async_search("3de", context, command)
            return _ASYNC_IN_PROGRESS

        applied = self._apply_file_result("3de", command, cache_result.path)
        if applied is None:
            return _LAUNCH_ERROR
        return applied, False


class MayaAppHandler:
    """Handler for Maya launches."""

    def __init__(
        self,
        bootstrap_script: str,
        cache_manager: LatestFileCache,
        start_async_search: Callable[[str, LaunchContext, str], None],
        apply_file_result: Callable[[str, str, Path | None], str | None],
        emit_error: Callable[[str], None],
    ) -> None:
        self._bootstrap_script: str = bootstrap_script
        self._cache_manager: LatestFileCache = cache_manager
        self._start_async_search: Callable[[str, LaunchContext, str], None] = (
            start_async_search
        )
        self._apply_file_result: Callable[[str, str, Path | None], str | None] = (
            apply_file_result
        )
        self._emit_error: Callable[[str], None] = emit_error

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        return build_maya_context_command(
            base_cmd, safe_file_path, self._bootstrap_script
        )

    def needs_sgtk_file_to_open(self) -> bool:
        return True

    def build_launch_command(
        self,
        base_cmd: str,
        context: LaunchContext,
        current_shot: Shot,
    ) -> tuple[str | None, bool]:
        command = base_cmd
        if not context.open_latest_maya:
            return command, False

        workspace = current_shot.workspace_path
        cache_result = self._cache_manager.get_latest_file_cache_result(
            workspace, "maya"
        )

        if cache_result.status == "miss":
            self._start_async_search("maya", context, command)
            return _ASYNC_IN_PROGRESS

        applied = self._apply_file_result("maya", command, cache_result.path)
        if applied is None:
            return _LAUNCH_ERROR
        return applied, False


class RVAppHandler:
    """Handler for RV launches."""

    def __init__(self, emit_error: Callable[[str], None]) -> None:
        self._emit_error: Callable[[str], None] = emit_error

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        return f"{base_cmd} {safe_file_path}"

    def needs_sgtk_file_to_open(self) -> bool:
        return False

    def build_launch_command(
        self,
        base_cmd: str,
        context: LaunchContext,
        current_shot: Shot,
    ) -> tuple[str | None, bool]:
        rv_command = rv_commands.build_rv_command(base_cmd, context.sequence_path)
        if rv_command is None:
            self._emit_error(
                f"Cannot launch RV: Invalid sequence path '{context.sequence_path}'"
            )
            return _LAUNCH_ERROR
        return rv_command, False


class GenericAppHandler:
    """Fallback handler for unknown or unregistered DCCs."""

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        return f"{base_cmd} {safe_file_path}"

    def needs_sgtk_file_to_open(self) -> bool:
        return False

    def build_launch_command(
        self,
        base_cmd: str,
        context: LaunchContext,
        current_shot: Shot,
    ) -> tuple[str | None, bool]:
        return base_cmd, False
