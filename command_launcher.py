"""Command launcher for executing applications in shot context.

This module provides the production launcher system for Shotbot, handling:
- Application launching with shot context
- Rez environment integration
- Process lifecycle management
"""

from __future__ import annotations

# Standard library imports
import errno
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

# Third-party imports
from PySide6.QtCore import QMetaObject, QObject, Qt, QTimer, Signal

# Local application imports
from config import Config
from launch import CommandBuilder, EnvironmentManager, ProcessExecutor
from logging_mixin import LoggingMixin
from notification_manager import NotificationManager
from nuke_launch_router import NukeLaunchRouter


if TYPE_CHECKING:
    # Local application imports
    from shot_model import Shot
    from threede_scene_model import ThreeDEScene
else:
    # Import at runtime to avoid circular imports
    # Local application imports
    pass


def _safe_filename_str(filename: str | bytes | int | None) -> str:
    """Safely convert exception filename attribute to string.

    Exception.filename can be None, str, bytes, or int.
    This helper ensures type-safe conversion to str for error messages.
    """
    if filename is None:
        return "unknown"
    if isinstance(filename, bytes):
        return filename.decode("utf-8", errors="replace")
    return str(filename)


@dataclass(frozen=True)
class LaunchContext:
    """Value object encapsulating application launch parameters.

    This immutable dataclass simplifies CommandLauncher's API by grouping
    related launch options together, reducing parameter coupling.

    Attributes:
        include_raw_plate: Whether to include raw plate Read node (Nuke only)
        open_latest_threede: Whether to open latest 3DE scene file (3DE only)
        open_latest_maya: Whether to open latest Maya scene file (Maya only)
        open_latest_scene: Whether to open latest Nuke script (Nuke only)
        create_new_file: Whether to create a new version (Nuke only)
        selected_plate: Selected plate space for Nuke workspace scripts
    """

    include_raw_plate: bool = False
    open_latest_threede: bool = False
    open_latest_maya: bool = False
    open_latest_scene: bool = False
    create_new_file: bool = False
    selected_plate: str | None = None


@final
class CommandLauncher(LoggingMixin, QObject):
    """Handles launching applications in shot context.

    This class uses dependency injection for better testability and following SOLID principles.
    Dependencies are passed as constructor parameters rather than imported directly.
    """

    # Signals
    command_executed = Signal(str, str)  # timestamp, command
    command_error = Signal(str, str)  # timestamp, error

    def __init__(
        self,
        parent: QObject | None = None,
    ) -> None:
        """Initialize CommandLauncher with optional dependencies.

        Args:
            parent: Optional parent QObject for proper Qt ownership
        """
        super().__init__(parent)
        self.current_shot: Shot | None = None

        # Track signal connections for proper cleanup
        self._signal_connections: list[QMetaObject.Connection] = []

        # Initialize launch components
        self.env_manager = EnvironmentManager()
        self.process_executor = ProcessExecutor(Config, parent=self)

        # Initialize the Nuke launch handler
        self.nuke_handler = NukeLaunchRouter()

        # Connect process executor signals (track for cleanup)
        # Use QueuedConnection for thread-safe cross-thread signal handling
        self._signal_connections.append(
            self.process_executor.execution_progress.connect(
                self._on_execution_progress, Qt.ConnectionType.QueuedConnection
            )
        )
        self._signal_connections.append(
            self.process_executor.execution_completed.connect(
                self._on_execution_completed, Qt.ConnectionType.QueuedConnection
            )
        )
        self._signal_connections.append(
            self.process_executor.execution_error.connect(
                self._on_execution_error, Qt.ConnectionType.QueuedConnection
            )
        )

        # Initialize scene/file finders (created internally, not injected)
        # Local application imports
        from maya_latest_finder import MayaLatestFinder
        from nuke_script_generator import NukeScriptGenerator
        from raw_plate_finder import RawPlateFinder
        from threede_latest_finder import ThreeDELatestFinder

        self._raw_plate_finder = RawPlateFinder()
        self._nuke_script_generator = NukeScriptGenerator()
        self._threede_latest_finder = ThreeDELatestFinder()
        self._maya_latest_finder = MayaLatestFinder()

    @property
    def timestamp(self) -> str:
        """Current UTC timestamp in HH:MM:SS format for logging.

        Returns:
            Formatted timestamp string suitable for log messages and UI display
        """
        return datetime.now(tz=UTC).strftime("%H:%M:%S")

    def _apply_nuke_environment_fixes(self, app_name: str, context: str = "") -> str:
        """Apply Nuke environment fixes and emit status signals.

        Extracts the Nuke environment fix logic to eliminate code duplication
        across launch_app(), launch_app_with_scene(), and related methods.

        Args:
            app_name: The application name (only applies fixes if "nuke")
            context: Optional context string for the status message (e.g., "scene launch")

        Returns:
            Environment fix prefix string (empty if not Nuke or no fixes needed)
        """
        if app_name != "nuke":
            return ""

        env_fixes = self.nuke_handler.get_environment_fixes()
        if not env_fixes:
            return ""

        # Build fix details list
        fix_details: list[str] = []
        if Config.NUKE_SKIP_PROBLEMATIC_PLUGINS:
            fix_details.append("runtime NUKE_PATH filtering")
        if Config.NUKE_OCIO_FALLBACK_CONFIG:
            fix_details.append("OCIO fallback")
        fix_details.append("crash reporting disabled")

        # Emit status signal
        timestamp = self.timestamp
        context_str = f"for {context}" if context else "to prevent Nuke crashes"
        self.command_executed.emit(
            timestamp,
            f"Applied environment fixes {context_str}: {', '.join(fix_details)}",
        )

        return env_fixes

    def cleanup(self) -> None:
        """Disconnect signals and cleanup resources.

        This method should be called when CommandLauncher is being destroyed
        to prevent memory leaks and ensure proper resource cleanup.

        Notes:
            Safe to call multiple times. Silently handles already-disconnected signals.
            Safe to call even if __init__ failed partway through.
        """
        # Disconnect all tracked signal connections
        # Using QObject.disconnect() with connection handle works even if sender is destroyed
        if hasattr(self, "_signal_connections"):
            for connection in self._signal_connections:
                try:
                    _ = QObject.disconnect(connection)
                except (RuntimeError, TypeError):
                    # Connection already disconnected or sender/receiver destroyed
                    pass
            self._signal_connections.clear()

        # Cleanup ProcessExecutor's signal connections
        try:
            if hasattr(self, "process_executor"):
                self.process_executor.cleanup()
        except (RuntimeError, TypeError, AttributeError):
            pass

    def __del__(self) -> None:
        """Ensure cleanup on destruction."""
        self.cleanup()

    def set_current_shot(self, shot: Shot | None) -> None:
        """Set the current shot context."""
        self.current_shot = shot

    def _on_execution_progress(self, operation: str, message: str) -> None:
        """Handle execution progress from ProcessExecutor.

        Args:
            operation: Name of the operation
            message: Progress status message
        """
        timestamp = self.timestamp
        self.command_executed.emit(timestamp, f"[{operation}] {message}")

    def _on_execution_completed(self, success: bool, message: str) -> None:
        """Handle execution completion from ProcessExecutor.

        Args:
            success: Whether execution completed successfully
            message: Completion message (empty if success, error if failed)
        """
        if not success and message:
            self._emit_error(f"Execution failed: {message}")

    def _on_execution_error(self, operation: str, error_message: str) -> None:
        """Handle execution error from ProcessExecutor.

        Args:
            operation: Name of the operation that failed
            error_message: Error message
        """
        self._emit_error(f"[{operation}] {error_message}")

    # Methods removed - now using launch components:
    # - _is_rez_available() → self.env_manager.is_rez_available(Config)
    # - _get_rez_packages_for_app() → self.env_manager.get_rez_packages(app_name, Config)
    # - _detect_available_terminal() → self.env_manager.detect_terminal()
    # - _validate_path_for_shell() → CommandBuilder.validate_path(path)

    def _launch_in_new_terminal(
        self, full_command: str, app_name: str, error_context: str = ""
    ) -> bool:
        """Launch command in new terminal window with full error handling.

        Template method helper for new terminal window execution.

        Args:
            full_command: Complete command to execute
            app_name: Application name (for spawn verification and error messages)
            error_context: Additional context for error messages (e.g., " with scene")

        Returns:
            True if launch successful, False otherwise
        """
        # Pre-check for available terminal
        terminal = self.env_manager.detect_terminal()
        if terminal is None:
            self._emit_error(
                "No terminal emulator found (checked: gnome-terminal, konsole, xfce4-terminal, "
                "mate-terminal, alacritty, kitty, terminology, xterm, x-terminal-emulator)"
            )
            return False

        try:
            # Build command for the detected terminal
            if terminal == "gnome-terminal":
                term_cmd = ["gnome-terminal", "--", "bash", "-ilc", full_command]
            elif terminal == "konsole":
                term_cmd = ["konsole", "-e", "bash", "-ilc", full_command]
            elif terminal == "kitty":
                # kitty uses different syntax: kitty bash -ilc "command"
                term_cmd = ["kitty", "bash", "-ilc", full_command]
            elif terminal in [
                "xterm",
                "x-terminal-emulator",
                "xfce4-terminal",
                "mate-terminal",
                "alacritty",
                "terminology",
            ]:
                # These terminals all use -e flag for command execution
                term_cmd = [terminal, "-e", "bash", "-ilc", full_command]
            else:
                # Fallback to direct execution
                term_cmd = ["/bin/bash", "-ilc", full_command]

            process = subprocess.Popen(term_cmd)

            # Verify spawn after 100ms (asynchronous to avoid blocking UI) - Task 5.1
            # Use functools.partial for safe reference capture (avoids lambda race conditions)
            QTimer.singleShot(
                100, partial(self.process_executor.verify_spawn, process, app_name)
            )

            return True

        except FileNotFoundError as e:
            # Type-safe: e.filename can be None, str, bytes, or int - Task 6.3
            filename_not_found: str = _safe_filename_str(
                cast("str | bytes | int | None", e.filename)
            )
            self._emit_error(
                f"Cannot launch {app_name}{error_context}: Application or terminal not found. Details: {filename_not_found}"
            )
            NotificationManager.error(
                "Launch Failed", f"{app_name} executable not found"
            )
            # Clear cache on failure - terminal may have been uninstalled
            self.env_manager.reset_cache()
            return False

        except PermissionError as e:
            # Type-safe: e.filename can be None, str, bytes, or int - Task 6.3
            filename_perm: str = _safe_filename_str(
                cast("str | bytes | int | None", e.filename)
            )
            self._emit_error(
                f"Cannot launch {app_name}{error_context}: Permission denied. Check file permissions for: {filename_perm}"
            )
            return False

        except OSError as e:
            # Type-safe: e.errno and e.strerror can be None - Task 6.3
            if e.errno == errno.EACCES:
                msg = "Permission denied - check file permissions"
            elif e.errno == errno.ENOSPC:
                msg = "No space left on device"
            elif e.errno == errno.EMFILE:
                msg = "Too many open files"
            elif e.errno == errno.ENOMEM:
                msg = "Out of memory"
            else:
                errno_str = str(e.errno) if e.errno is not None else "unknown"
                strerror = e.strerror if e.strerror else "unknown error"
                msg = f"{strerror} (errno {errno_str})"

            self._emit_error(f"Cannot launch {app_name}{error_context}: {msg}")
            return False

        except Exception as e:
            # Fallback for unexpected errors - Task 6.3
            # Clear cache on failure - terminal may have been uninstalled
            self.env_manager.reset_cache()
            self._emit_error(f"Failed to launch {app_name}{error_context}: {e!s}")
            return False

    def _execute_launch(
        self, full_command: str, app_name: str, error_context: str = ""
    ) -> bool:
        """Execute command in a new terminal window.

        Template method for all launch operations.

        Args:
            full_command: Complete command to execute (with logging, rez, etc.)
            app_name: Application name (for spawn verification)
            error_context: Additional context for error messages (e.g., " with scene")

        Returns:
            True if launch successful, False otherwise
        """
        return self._launch_in_new_terminal(full_command, app_name, error_context)

    def launch_app(
        self,
        app_name: str,
        context: LaunchContext | None = None,
        # Legacy parameters for backward compatibility
        include_raw_plate: bool = False,
        open_latest_threede: bool = False,
        open_latest_maya: bool = False,
        open_latest_scene: bool = False,
        create_new_file: bool = False,
        selected_plate: str | None = None,
    ) -> bool:
        """Launch an application in the current shot context.

        Args:
            app_name: Name of the application to launch
            context: Launch context with options (preferred)
            include_raw_plate: (Legacy) Whether to include raw plate Read node (Nuke only)
            open_latest_threede: (Legacy) Whether to open the latest 3DE scene file (3DE only)
            open_latest_maya: (Legacy) Whether to open the latest Maya scene file (Maya only)
            open_latest_scene: (Legacy) Whether to open the latest Nuke script (Nuke only)
            create_new_file: (Legacy) Whether to create a new version (Nuke only)
            selected_plate: (Legacy) Selected plate space for Nuke workspace scripts

        Returns:
            True if launch was successful, False otherwise

        Note:
            The context parameter is preferred. Legacy parameters are kept for
            backward compatibility but will be removed in a future version.
        """
        # Handle backward compatibility: if context not provided, create from legacy params
        if context is None:
            context = LaunchContext(
                include_raw_plate=include_raw_plate,
                open_latest_threede=open_latest_threede,
                open_latest_maya=open_latest_maya,
                open_latest_scene=open_latest_scene,
                create_new_file=create_new_file,
                selected_plate=selected_plate,
            )

        if not self.current_shot:
            self._emit_error("No shot selected")
            return False

        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Validate workspace before launching (Task 5.4)
        if not self._validate_workspace_before_launch(
            self.current_shot.workspace_path, app_name
        ):
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Handle Nuke-specific launching logic
        if app_name == "nuke":
            # Use the unified Nuke handler for all Nuke-specific logic
            options = {
                "open_latest_scene": context.open_latest_scene,
                "create_new_file": context.create_new_file,
                "include_raw_plate": context.include_raw_plate,
            }

            command, log_messages = self.nuke_handler.prepare_nuke_command(
                self.current_shot, command, options, selected_plate=context.selected_plate
            )

            # Emit log messages
            timestamp = self.timestamp
            for msg in log_messages:
                self.command_executed.emit(timestamp, msg)

        # Old Nuke handling code has been removed - see NukeLaunchHandler

        # Handle 3DE with latest scene file
        if app_name == "3de" and context.open_latest_threede:
            latest_scene = self._threede_latest_finder.find_latest_threede_scene(
                self.current_shot.workspace_path,
                self.current_shot.full_name,
            )
            if latest_scene:
                # Add the scene file to the command
                try:
                    safe_scene_path = CommandBuilder.validate_path(str(latest_scene))
                    command = f"{command} -open {safe_scene_path}"
                    timestamp = self.timestamp
                    self.command_executed.emit(
                        timestamp,
                        f"Opening latest 3DE scene: {latest_scene.name}",
                    )
                except ValueError as e:
                    timestamp = self.timestamp
                    self.command_executed.emit(
                        timestamp,
                        f"Warning: Invalid 3DE scene path: {e!s}",
                    )
            else:
                timestamp = self.timestamp
                self.command_executed.emit(
                    timestamp,
                    "Info: No 3DE scene files found in workspace",
                )

        # Handle Maya with latest scene file
        if app_name == "maya" and context.open_latest_maya:
            latest_scene = self._maya_latest_finder.find_latest_maya_scene(
                self.current_shot.workspace_path,
                self.current_shot.full_name,
            )
            if latest_scene:
                # Add the scene file to the command
                try:
                    safe_scene_path = CommandBuilder.validate_path(str(latest_scene))
                    command = f"{command} -file {safe_scene_path}"
                    timestamp = self.timestamp
                    self.command_executed.emit(
                        timestamp,
                        f"Opening latest Maya scene: {latest_scene.name}",
                    )
                except ValueError as e:
                    timestamp = self.timestamp
                    self.command_executed.emit(
                        timestamp,
                        f"Warning: Invalid Maya scene path: {e!s}",
                    )
            else:
                timestamp = self.timestamp
                self.command_executed.emit(
                    timestamp,
                    "Info: No Maya scene files found in workspace",
                )

        # Build full command with ws (workspace setup)
        # Validate and escape workspace path to prevent injection
        try:
            safe_workspace_path = CommandBuilder.validate_path(
                self.current_shot.workspace_path
            )

            # Apply Nuke environment fixes if needed
            env_fixes = self._apply_nuke_environment_fixes(app_name)

            # Build workspace command with environment fixes
            ws_command = f"ws {safe_workspace_path} && {env_fixes}{command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        # Wrap with rez environment if available
        if self.env_manager.is_rez_available(Config):
            rez_packages = self.env_manager.get_rez_packages(app_name, Config)
            if rez_packages:
                # Use CommandBuilder to wrap with rez environment
                full_command = CommandBuilder.wrap_with_rez(ws_command, rez_packages)
                timestamp = self.timestamp
                packages_str = " ".join(rez_packages)
                self.command_executed.emit(
                    timestamp, f"Using rez environment with packages: {packages_str}"
                )
            else:
                full_command = ws_command
        else:
            full_command = ws_command

        # Add logging redirection for debugging
        full_command = CommandBuilder.add_logging(full_command, Config)

        # Log the command to UI
        timestamp = self.timestamp
        self.command_executed.emit(timestamp, full_command)

        # Enhanced debug logging for command integrity verification
        workspace = self.current_shot.workspace_path if self.current_shot else "None"
        shot_name = self.current_shot.full_name if self.current_shot else "None"
        self.logger.debug(
            f"Constructed command for {app_name}:\n  Command: {full_command!r}\n  Length: {len(full_command)} chars\n  Workspace: {workspace}\n  Shot: {shot_name}"
        )

        # Use template method for terminal launch
        return self._execute_launch(full_command, app_name)

    def launch_app_with_scene(self, app_name: str, scene: ThreeDEScene) -> bool:
        """Launch an application with a specific 3DE scene file.

        Args:
            app_name: Name of the application to launch
            scene: The 3DE scene to open

        Returns:
            True if launch was successful, False otherwise
        """
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Include the scene file in the command
        # Validate and escape scene path to prevent injection
        try:
            safe_scene_path = CommandBuilder.validate_path(str(scene.scene_path))
            # Add app-specific command-line flags for scene file
            if app_name == "3de":
                command = f"{command} -open {safe_scene_path}"
            elif app_name == "maya":
                command = f"{command} -file {safe_scene_path}"
            else:
                # Nuke and others accept scene file without flag
                command = f"{command} {safe_scene_path}"
        except ValueError as e:
            self._emit_error(f"Invalid scene path: {e!s}")
            return False

        # Validate workspace before attempting launch
        if not self._validate_workspace_before_launch(scene.workspace_path, app_name):
            return False

        # Build full command with ws (workspace setup)
        # Validate and escape workspace path to prevent injection
        try:
            safe_workspace_path = CommandBuilder.validate_path(scene.workspace_path)

            # Apply Nuke environment fixes if needed (same as regular launch)
            env_fixes = self._apply_nuke_environment_fixes(app_name, "Nuke scene launch")

            # Build workspace command with environment fixes
            ws_command = f"ws {safe_workspace_path} && {env_fixes}{command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        # Wrap with rez environment if available
        if self.env_manager.is_rez_available(Config):
            rez_packages = self.env_manager.get_rez_packages(app_name, Config)
            if rez_packages:
                # Use CommandBuilder to wrap with rez environment
                full_command = CommandBuilder.wrap_with_rez(ws_command, rez_packages)
            else:
                full_command = ws_command
        else:
            full_command = ws_command

        # Add logging redirection for debugging
        full_command = CommandBuilder.add_logging(full_command, Config)

        # Log the command
        timestamp = self.timestamp
        self.command_executed.emit(
            timestamp,
            f"{full_command} (Scene by: {scene.user}, Plate: {scene.plate})",
        )

        # Use template method for terminal launch
        return self._execute_launch(full_command, app_name, " with scene")

    def launch_app_with_scene_context(
        self,
        app_name: str,
        scene: ThreeDEScene,
        include_raw_plate: bool = False,
    ) -> bool:
        """Launch an application in the context of a 3DE scene (shot context only, no scene file).

        Args:
            app_name: Name of the application to launch
            scene: The 3DE scene providing shot context
            include_raw_plate: Whether to include raw plate Read node (Nuke only)

        Returns:
            True if launch was successful, False otherwise
        """
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Handle raw plate for Nuke
        if app_name == "nuke" and include_raw_plate:
            raw_plate_path = self._raw_plate_finder.find_latest_raw_plate(
                scene.workspace_path,
                scene.full_name,
            )

            if raw_plate_path:
                # Verify at least one frame exists
                if self._raw_plate_finder.verify_plate_exists(raw_plate_path):
                    # Create a Nuke script with the plate loaded
                    script_path = self._nuke_script_generator.create_plate_script(
                        raw_plate_path,
                        scene.full_name,
                    )

                    if script_path:
                        # Launch Nuke with the generated script
                        command = f"{command} {script_path}"
                        timestamp = self.timestamp
                        version = self._raw_plate_finder.get_version_from_path(
                            raw_plate_path
                        )
                        self.command_executed.emit(
                            timestamp,
                            f"Created Nuke script with plate: {version}/{raw_plate_path.split('/')[-1]}",
                        )
                    else:
                        # Fallback to just passing the path (safely escaped)
                        safe_plate_path = CommandBuilder.validate_path(raw_plate_path)
                        command = f"{command} {safe_plate_path}"
                        timestamp = self.timestamp
                        version = self._raw_plate_finder.get_version_from_path(
                            raw_plate_path
                        )
                        self.command_executed.emit(
                            timestamp,
                            f"Found raw plate: {version}/{raw_plate_path.split('/')[-1]}",
                        )
                else:
                    # Log warning if plate path found but no frames exist
                    timestamp = self.timestamp
                    self.command_executed.emit(
                        timestamp,
                        "Warning: Raw plate path found but no frames exist",
                    )
            else:
                # Log warning if raw plate requested but not found
                timestamp = self.timestamp
                self.command_executed.emit(
                    timestamp,
                    "Warning: Raw plate not found for this shot",
                )

        # Validate workspace before attempting launch
        if not self._validate_workspace_before_launch(scene.workspace_path, app_name):
            return False

        # Build full command with ws (workspace setup)
        # Validate and escape workspace path to prevent injection
        try:
            safe_workspace_path = CommandBuilder.validate_path(scene.workspace_path)
            ws_command = f"ws {safe_workspace_path} && {command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        # Wrap with rez environment if available
        if self.env_manager.is_rez_available(Config):
            rez_packages = self.env_manager.get_rez_packages(app_name, Config)
            if rez_packages:
                # Use CommandBuilder to wrap with rez environment
                full_command = CommandBuilder.wrap_with_rez(ws_command, rez_packages)
                timestamp = self.timestamp
                packages_str = " ".join(rez_packages)
                self.command_executed.emit(
                    timestamp, f"Using rez environment with packages: {packages_str}"
                )
            else:
                full_command = ws_command
        else:
            full_command = ws_command

        # Add logging redirection for debugging
        full_command = CommandBuilder.add_logging(full_command, Config)

        # Log the command
        timestamp = self.timestamp
        self.command_executed.emit(
            timestamp,
            f"{full_command} (Context: {scene.user}'s {scene.plate})",
        )

        # Use template method for terminal launch
        return self._execute_launch(full_command, app_name, " in scene context")

    # Methods removed - now using launch components:
    # - _is_gui_app() → self.process_executor.is_gui_app(app_name)
    # - _verify_spawn() → self.process_executor._verify_spawn(process, app_name)

    def _validate_workspace_before_launch(
        self, workspace_path: str, app_name: str
    ) -> bool:
        """Validate workspace is accessible before launching application.

        Performs two critical checks:
        1. Workspace directory exists
        2. User has read and execute permissions

        Args:
            workspace_path: Path to the workspace directory
            app_name: Name of the application (for error messages)

        Returns:
            True if validation passes, False otherwise
        """
        # Check directory exists
        ws_path = Path(workspace_path)
        if not ws_path.exists():
            self._emit_error(
                f"Cannot launch {app_name}: Workspace path does not exist: {workspace_path}"
            )
            return False

        # Check it's actually a directory
        if not ws_path.is_dir():
            self._emit_error(
                f"Cannot launch {app_name}: Workspace path is not a directory: {workspace_path}"
            )
            return False

        # Check read/execute permissions
        if not os.access(workspace_path, os.R_OK | os.X_OK):
            self._emit_error(
                f"Cannot launch {app_name}: No read/execute permission for: {workspace_path}"
            )
            return False

        return True

    # Method removed - now using launch components:
    # - _add_dispatcher_logging() → CommandBuilder.add_logging(command)

    def _emit_error(self, error: str) -> None:
        """Emit error with timestamp."""
        timestamp = self.timestamp
        self.command_error.emit(timestamp, error)

    # Old terminal signal handlers removed - now using ProcessExecutor signals:
    # - _on_terminal_progress() → _on_execution_progress()
    # - _on_terminal_command_result() → _on_execution_completed()
