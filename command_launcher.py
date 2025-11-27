"""Command launcher for executing applications in shot context.

This module provides the production launcher system for Shotbot, handling:
- Application launching with shot context
- Rez environment integration
- Process lifecycle management
"""

from __future__ import annotations

# Standard library imports
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, final

# Third-party imports
from PySide6.QtCore import QMetaObject, QObject, Qt, Signal

# Local application imports
from config import Config
from launch import CommandBuilder, EnvironmentManager, ProcessExecutor
from logging_mixin import LoggingMixin
from notification_manager import NotificationManager
from nuke_launch_router import NukeLaunchRouter
from settings_manager import SettingsManager


if TYPE_CHECKING:
    # Local application imports
    from shot_model import Shot
    from threede_scene_model import ThreeDEScene
else:
    # Import at runtime to avoid circular imports
    # Local application imports
    pass


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
        settings_manager: SettingsManager | None = None,
    ) -> None:
        """Initialize CommandLauncher with optional dependencies.

        Args:
            parent: Optional parent QObject for proper Qt ownership
            settings_manager: Optional SettingsManager for configuration.
                If not provided, creates a new instance.
        """
        super().__init__(parent)
        self.current_shot: Shot | None = None
        self._settings_manager = settings_manager or SettingsManager()

        # Track signal connections for proper cleanup
        self._signal_connections: list[QMetaObject.Connection] = []

        # Initialize launch components
        self.env_manager = EnvironmentManager()
        self.env_manager.warm_cache_async()  # Pre-warm caches in background
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
        self._signal_connections.append(
            self.process_executor.app_verification_timeout.connect(
                self._on_app_verification_timeout, Qt.ConnectionType.QueuedConnection
            )
        )
        self._signal_connections.append(
            self.process_executor.app_verified.connect(
                self._on_app_verified, Qt.ConnectionType.QueuedConnection
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

    # Counter for consecutive verification timeouts (used to avoid cache reset on first timeout)
    _consecutive_timeout_count: int = 0
    _TIMEOUT_THRESHOLD_FOR_CACHE_RESET: int = 3

    def _on_app_verification_timeout(self, app_name: str) -> None:
        """Handle app verification timeout from ProcessExecutor.

        VFX apps can take 30-60+ seconds to boot (Rez resolution + plugin scanning).
        A single timeout doesn't necessarily mean the terminal is broken - the app
        may still be starting. Only reset cache after repeated consecutive failures.

        Args:
            app_name: Name of the application that failed verification
        """
        self._consecutive_timeout_count += 1

        if self._consecutive_timeout_count >= self._TIMEOUT_THRESHOLD_FOR_CACHE_RESET:
            # Multiple consecutive timeouts suggest terminal detection issue
            self.env_manager.reset_cache()
            self._consecutive_timeout_count = 0
            self._emit_error(
                f"[{app_name}] Verification timeout (repeated) - terminal cache reset for next attempt"
            )
        else:
            # First timeout - app may still be starting, don't reset cache
            self._emit_error(
                f"[{app_name}] Verification timeout - app may still be starting"
            )

    def _on_app_verified(self, app_name: str, pid: int) -> None:
        """Handle successful app verification from ProcessExecutor.

        Reset the consecutive timeout counter on successful launch, since
        the terminal and environment are working correctly.

        Args:
            app_name: Name of the application that was verified
            pid: Process ID of the verified application
        """
        # Reset timeout counter on success - terminal is working
        self._consecutive_timeout_count = 0
        self.logger.debug(f"App {app_name} verified with PID {pid}")

    # Methods removed - now using launch components:
    # - _is_rez_available() → self.env_manager.is_rez_available(Config)
    # - _get_rez_packages_for_app() → self.env_manager.get_rez_packages(app_name, Config)
    # - _detect_available_terminal() → self.env_manager.detect_terminal()
    # - _validate_path_for_shell() → CommandBuilder.validate_path(path)

    def _launch_in_new_terminal(
        self, full_command: str, app_name: str, error_context: str = ""
    ) -> bool:
        """Launch command in new terminal window with full error handling.

        Delegates to ProcessExecutor for terminal spawning. Supports headless
        mode when no terminal emulator is available.

        Args:
            full_command: Complete command to execute
            app_name: Application name (for spawn verification and error messages)
            error_context: Additional context for error messages (e.g., " with scene")

        Returns:
            True if launch successful, False otherwise
        """
        # Apply background wrapping for GUI apps if setting is enabled
        # This closes the terminal immediately after launching, reducing clutter
        if (
            self.process_executor.is_gui_app(app_name)
            and self._settings_manager.get_background_gui_apps()
        ):
            full_command = CommandBuilder.wrap_for_background(full_command)
            self.logger.info(
                f"Backgrounding {app_name} - terminal will close immediately"
            )

        # Validate command length to prevent silent truncation
        cmd_length = len(full_command)
        if cmd_length > self.MAX_COMMAND_LENGTH:
            self._emit_error(
                f"Cannot launch {app_name}: Command too long "
                f"({cmd_length} chars, max {self.MAX_COMMAND_LENGTH}). "
                "Try shorter paths or fewer rez packages."
            )
            return False

        # Detect available terminal (None = headless mode, use direct bash)
        terminal = self.env_manager.detect_terminal()

        # Record enqueue time for process verification
        enqueue_time = time.time()

        # Delegate to ProcessExecutor for terminal spawning
        process = self.process_executor.execute_in_new_terminal(
            full_command, app_name, terminal
        )

        if process is None:
            # ProcessExecutor already logged the error details
            self._emit_error(f"Failed to launch {app_name}{error_context}")
            NotificationManager.error("Launch Failed", f"{app_name} failed to start")
            # Clear cache on failure - terminal may have been uninstalled
            self.env_manager.reset_cache()
            return False

        # Start async app verification for GUI apps (runs in background thread)
        # This detects if the actual application (not just terminal) launched successfully
        self.process_executor.start_app_verification(app_name, enqueue_time)

        return True

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

            # Check for empty command (signals failure, e.g., missing plate)
            if not command:
                self._emit_error("Nuke launch aborted - see log messages above")
                return False

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
                    # Abort launch on invalid scene path to prevent data loss
                    self._emit_error(
                        f"Cannot launch 3DE: Invalid scene path '{latest_scene}': {e!s}"
                    )
                    return False
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
                    # Abort launch on invalid scene path to prevent data loss
                    self._emit_error(
                        f"Cannot launch Maya: Invalid scene path '{latest_scene}': {e!s}"
                    )
                    return False
            else:
                timestamp = self.timestamp
                self.command_executed.emit(
                    timestamp,
                    "Info: No Maya scene files found in workspace",
                )

        # Pre-flight: Check if ws command is available
        if not self.env_manager.is_ws_available():
            self._emit_error(
                "Workspace command 'ws' not found. "
                "Ensure workspace tools are installed and on PATH."
            )
            return False

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

        # Wrap with rez environment if:
        # - REZ_FORCE_WRAP=True (force wrapping even in existing rez env), OR
        # - REZ_ALREADY_AVAILABLE=False (no shell init rez setup)
        # When REZ_FORCE_WRAP is True, we add app-specific packages (nuke-16, OCIO, etc.)
        # on top of the base rez environment.
        should_wrap_rez = self.env_manager.is_rez_available(Config) and (
            Config.REZ_FORCE_WRAP or not Config.REZ_ALREADY_AVAILABLE
        )
        if should_wrap_rez:
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
            # Emit visible message explaining why Rez wrapping is skipped
            # This helps users understand which app version will be used
            timestamp = self.timestamp
            if Config.REZ_ALREADY_AVAILABLE and not Config.REZ_FORCE_WRAP:
                self.command_executed.emit(
                    timestamp,
                    f"Note: Rez wrap skipped - shell init already provides rez for {app_name}",
                )
            elif os.environ.get("REZ_USED"):
                self.command_executed.emit(
                    timestamp,
                    f"Note: Already in rez environment - skipping rez wrap for {app_name}",
                )
            elif not Config.USE_REZ_ENVIRONMENT:
                # Rez explicitly disabled by configuration
                self.command_executed.emit(
                    timestamp,
                    f"Note: Rez disabled by config - {app_name} will use system PATH version",
                )
            else:
                # Rez enabled but command not found on system
                self.command_executed.emit(
                    timestamp,
                    f"Warning: Rez command not found - {app_name} will use system PATH version",
                )

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

        # Pre-flight: Check if ws command is available
        if not self.env_manager.is_ws_available():
            self._emit_error(
                "Workspace command 'ws' not found. "
                "Ensure workspace tools are installed and on PATH."
            )
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

        # Wrap with rez environment if:
        # - REZ_FORCE_WRAP=True (force wrapping even in existing rez env), OR
        # - REZ_ALREADY_AVAILABLE=False (no shell init rez setup)
        should_wrap_rez = self.env_manager.is_rez_available(Config) and (
            Config.REZ_FORCE_WRAP or not Config.REZ_ALREADY_AVAILABLE
        )
        if should_wrap_rez:
            rez_packages = self.env_manager.get_rez_packages(app_name, Config)
            if rez_packages:
                # Use CommandBuilder to wrap with rez environment
                full_command = CommandBuilder.wrap_with_rez(ws_command, rez_packages)
            else:
                full_command = ws_command
        else:
            full_command = ws_command
            # Log that Rez wrapping is skipped
            if Config.REZ_ALREADY_AVAILABLE and not Config.REZ_FORCE_WRAP:
                self.logger.debug(
                    f"Rez wrapping skipped for {app_name} scene launch (REZ_ALREADY_AVAILABLE=True)"
                )

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

        # Pre-flight: Check if ws command is available
        if not self.env_manager.is_ws_available():
            self._emit_error(
                "Workspace command 'ws' not found. "
                "Ensure workspace tools are installed and on PATH."
            )
            return False

        # Build full command with ws (workspace setup)
        # Validate and escape workspace path to prevent injection
        try:
            safe_workspace_path = CommandBuilder.validate_path(scene.workspace_path)

            # Apply Nuke environment fixes if needed (same as other launch paths)
            env_fixes = self._apply_nuke_environment_fixes(app_name, "scene context launch")

            # Build workspace command with environment fixes
            ws_command = f"ws {safe_workspace_path} && {env_fixes}{command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        # Wrap with rez environment if:
        # - REZ_FORCE_WRAP=True (force wrapping even in existing rez env), OR
        # - REZ_ALREADY_AVAILABLE=False (no shell init rez setup)
        should_wrap_rez = self.env_manager.is_rez_available(Config) and (
            Config.REZ_FORCE_WRAP or not Config.REZ_ALREADY_AVAILABLE
        )
        if should_wrap_rez:
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
            # Log that Rez wrapping is skipped
            if Config.REZ_ALREADY_AVAILABLE and not Config.REZ_FORCE_WRAP:
                self.logger.debug(
                    f"Rez wrapping skipped for {app_name} scene context (REZ_ALREADY_AVAILABLE=True)"
                )

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

    # Minimum disk space required (MB)
    MIN_DISK_SPACE_MB: int = 100

    # Timeout for disk space check (seconds) - prevents blocking on NFS hangs
    DISK_CHECK_TIMEOUT_SEC: float = 2.0

    # Maximum command length (bytes) - gnome-terminal buffer is ~8KB, be conservative
    # Linux ARG_MAX is ~131KB but terminal emulators have smaller buffers
    MAX_COMMAND_LENGTH: int = 8000

    def _validate_workspace_before_launch(
        self, workspace_path: str, app_name: str
    ) -> bool:
        """Validate workspace is accessible before launching application.

        Performs pre-flight checks (advisory):
        1. Workspace directory exists
        2. User has read and execute permissions
        3. User has write permission (for apps that need it)
        4. Sufficient disk space available

        Note:
            Permission checks are advisory only due to TOCTOU (time-of-check to
            time-of-use) race conditions. Permissions could change between check
            and actual use. These checks provide early user feedback but don't
            guarantee success. The application may still fail if permissions
            change after validation.

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

        # Check disk space availability with timeout (prevents NFS hang blocking UI)
        try:
            # Run statvfs in a thread with timeout - NFS mounts can block indefinitely
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(os.statvfs, workspace_path)
                stat = future.result(timeout=self.DISK_CHECK_TIMEOUT_SEC)
            available_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
            if available_mb < self.MIN_DISK_SPACE_MB:
                self._emit_error(
                    f"Cannot launch {app_name}: Insufficient disk space "
                    f"({available_mb:.0f}MB available, {self.MIN_DISK_SPACE_MB}MB required)"
                )
                return False
        except FutureTimeoutError:
            # Disk space check timed out (likely NFS hang) - log warning but proceed
            self.logger.warning(
                f"Disk space check timed out for {workspace_path} "
                f"(may be slow NFS mount) - proceeding with launch"
            )
        except OSError as e:
            # Log warning but don't block launch if we can't check disk space
            self.logger.warning(f"Could not check disk space for {workspace_path}: {e}")

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
