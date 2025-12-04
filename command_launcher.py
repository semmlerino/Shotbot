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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, final

# Third-party imports
from PySide6.QtCore import QMetaObject, QObject, Qt, Signal

# Local application imports
from cache_manager import CacheManager
from config import Config
from latest_file_finder_worker import LatestFileFinderWorker
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
        open_latest_threede: Whether to open latest 3DE scene file (3DE only)
        open_latest_maya: Whether to open latest Maya scene file (Maya only)
        open_latest_scene: Whether to open latest Nuke script (Nuke only)
        create_new_file: Whether to create a new version (Nuke only)
        selected_plate: Selected plate space for Nuke workspace scripts
        sequence_path: Image sequence path for RV playback (RV only)
    """

    open_latest_threede: bool = False
    open_latest_maya: bool = False
    open_latest_scene: bool = False
    create_new_file: bool = False
    selected_plate: str | None = None
    sequence_path: str | None = None  # Image sequence path for RV


@final
class CommandLauncher(LoggingMixin, QObject):
    """Handles launching applications in shot context.

    This class uses dependency injection for better testability and following SOLID principles.
    Dependencies are passed as constructor parameters rather than imported directly.
    """

    # Signals
    command_executed = Signal(str, str)  # timestamp, command
    command_error = Signal(str, str)  # timestamp, error
    launch_pending = Signal()  # Emitted when async file search starts
    launch_ready = Signal()  # Emitted when async search completes (ready to launch)

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

        # Cache manager for latest files
        self._cache_manager: CacheManager = CacheManager()

        # Async file search state
        self._pending_worker: LatestFileFinderWorker | None = None
        self._pending_app_name: str | None = None
        self._pending_context: LaunchContext | None = None
        self._pending_command: str | None = None

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
        from threede_latest_finder import ThreeDELatestFinder

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

        # Cancel any pending async file search
        if hasattr(self, "_pending_worker") and self._pending_worker is not None:
            try:
                _ = self._pending_worker.request_stop()
                _ = self._pending_worker.safe_stop(timeout_ms=500)
            except (RuntimeError, TypeError):
                pass
            self._pending_worker = None

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

    # ========================================================================
    # Async Latest File Search Methods
    # ========================================================================

    def _start_async_file_search(
        self,
        app_name: str,
        context: LaunchContext,
        command: str,
    ) -> None:
        """Start async file search for latest Maya/3DE scenes.

        Args:
            app_name: Application being launched ("3de" or "maya")
            context: Launch context with search flags
            command: Base command built so far (before scene path added)
        """
        if self.current_shot is None:
            self._emit_error("Cannot search for files - no shot selected")
            return

        # Store pending state
        self._pending_app_name = app_name
        self._pending_context = context
        self._pending_command = command

        # Determine what to search for
        find_threede = app_name == "3de" and context.open_latest_threede
        find_maya = app_name == "maya" and context.open_latest_maya

        # Create and start worker
        self._pending_worker = LatestFileFinderWorker(
            workspace_path=self.current_shot.workspace_path,
            shot_name=self.current_shot.full_name,
            find_maya=find_maya,
            find_threede=find_threede,
            parent=self,
        )

        # Connect signals
        _ = self._pending_worker.search_complete.connect(
            self._on_async_search_complete,
            Qt.ConnectionType.QueuedConnection,
        )

        # Emit pending signal to update UI (show spinner)
        self.launch_pending.emit()

        # Start search
        self._pending_worker.start()
        self.logger.debug(f"Started async file search for {app_name}")

    def _on_async_search_complete(self, success: bool) -> None:
        """Handle async file search completion.

        Args:
            success: Whether the search completed successfully
        """
        if self._pending_worker is None:
            self.logger.warning("Async search complete but no pending worker")
            return

        # Get results from worker
        maya_result = self._pending_worker.maya_result
        threede_result = self._pending_worker.threede_result

        # Cache results (even None results to avoid re-searching)
        if self.current_shot is not None:
            workspace = self.current_shot.workspace_path
            if self._pending_context and self._pending_context.open_latest_maya:
                self._cache_manager.cache_latest_file(workspace, "maya", maya_result)
            if self._pending_context and self._pending_context.open_latest_threede:
                self._cache_manager.cache_latest_file(workspace, "threede", threede_result)

        # Clean up worker
        self._pending_worker.deleteLater()
        self._pending_worker = None

        # Emit ready signal (hide spinner)
        self.launch_ready.emit()

        # Continue with launch using cached results
        if success:
            self._continue_launch_after_search(maya_result, threede_result)
        else:
            self.logger.warning("Async file search failed or was cancelled")
            # Clear pending state
            self._pending_app_name = None
            self._pending_context = None
            self._pending_command = None

    def _continue_launch_after_search(
        self,
        maya_result: Path | None,
        threede_result: Path | None,
    ) -> None:
        """Continue launch flow after async file search completes.

        Args:
            maya_result: Found Maya scene path (or None)
            threede_result: Found 3DE scene path (or None)
        """
        app_name = self._pending_app_name
        context = self._pending_context
        command = self._pending_command

        # Clear pending state
        self._pending_app_name = None
        self._pending_context = None
        self._pending_command = None

        if app_name is None or context is None or command is None:
            self.logger.error("Missing pending state after async search")
            return

        # Add scene path to command based on results
        if app_name == "3de" and threede_result:
            try:
                safe_scene_path = CommandBuilder.validate_path(str(threede_result))
                command = f"{command} -open {safe_scene_path}"
                self.command_executed.emit(
                    self.timestamp,
                    f"Opening latest 3DE scene: {threede_result.name}",
                )
            except ValueError as e:
                self._emit_error(
                    f"Cannot launch 3DE: Invalid scene path '{threede_result}': {e!s}"
                )
                return
        elif app_name == "3de" and context.open_latest_threede:
            self.command_executed.emit(
                self.timestamp,
                "Info: No 3DE scene files found in workspace",
            )

        if app_name == "maya" and maya_result:
            try:
                safe_scene_path = CommandBuilder.validate_path(str(maya_result))
                command = f"{command} -file {safe_scene_path}"
                self.command_executed.emit(
                    self.timestamp,
                    f"Opening latest Maya scene: {maya_result.name}",
                )
            except ValueError as e:
                self._emit_error(
                    f"Cannot launch Maya: Invalid scene path '{maya_result}': {e!s}"
                )
                return
        elif app_name == "maya" and context.open_latest_maya:
            self.command_executed.emit(
                self.timestamp,
                "Info: No Maya scene files found in workspace",
            )

        # Continue with the rest of launch_app flow (from ws command onwards)
        _ = self._finish_launch(app_name, command)

    def _finish_launch(self, app_name: str, command: str) -> bool:
        """Complete the launch after file search is done.

        This contains the common launch completion logic shared between
        synchronous (cache hit) and async (cache miss) paths.

        Args:
            app_name: Application name
            command: Command with scene path (if any) already added

        Returns:
            True if launch succeeded, False otherwise
        """
        if self.current_shot is None:
            self._emit_error("Cannot launch - no shot selected")
            return False

        # Pre-flight: Check if ws command is available
        if not self.env_manager.is_ws_available():
            self._emit_error(
                "Workspace command 'ws' not found. "
                "Ensure workspace tools are installed and on PATH."
            )
            return False

        # Build full command with ws (workspace setup)
        try:
            safe_workspace_path = CommandBuilder.validate_path(
                self.current_shot.workspace_path
            )
            env_fixes = self._apply_nuke_environment_fixes(app_name)
            ws_command = f"ws {safe_workspace_path} && {env_fixes}{command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        # Determine if rez wrapping should be applied
        should_wrap_rez = self.env_manager.should_wrap_with_rez(Config)
        if should_wrap_rez:
            rez_packages = self.env_manager.get_rez_packages(app_name, Config)
            if rez_packages:
                full_command = CommandBuilder.wrap_with_rez(ws_command, rez_packages)
                packages_str = " ".join(rez_packages)
                self.command_executed.emit(
                    self.timestamp,
                    f"Using rez environment with packages: {packages_str}",
                )
            else:
                full_command = ws_command
                should_wrap_rez = False  # No packages means no actual rez wrapper
        else:
            full_command = ws_command
            # Emit message explaining why Rez wrapping is skipped
            if os.environ.get("REZ_USED"):
                self.command_executed.emit(
                    self.timestamp,
                    f"Note: Already in rez environment - skipping rez wrap for {app_name}",
                )
            else:
                self.command_executed.emit(
                    self.timestamp,
                    f"Note: Using system PATH version of {app_name}",
                )

        # Add logging redirection for debugging
        full_command = CommandBuilder.add_logging(full_command, Config)

        # Log the command to UI
        self.command_executed.emit(self.timestamp, full_command)

        # Enhanced debug logging for command integrity verification
        workspace = self.current_shot.workspace_path
        shot_name = self.current_shot.full_name
        self.logger.debug(
            f"Constructed command for {app_name}:\n"
            f"  Command: {full_command!r}\n"
            f"  Length: {len(full_command)} chars\n"
            f"  Workspace: {workspace}\n"
            f"  Shot: {shot_name}"
        )

        # Execute launch
        return self._execute_launch(full_command, app_name, has_rez_wrapper=should_wrap_rez)

    def cancel_pending_search(self) -> None:
        """Cancel any pending async file search."""
        if self._pending_worker is not None:
            _ = self._pending_worker.request_stop()
            _ = self._pending_worker.safe_stop(timeout_ms=1000)
            self._pending_worker = None
            self._pending_app_name = None
            self._pending_context = None
            self._pending_command = None
            self.launch_ready.emit()  # Clear spinner
            self.logger.debug("Cancelled pending file search")

    @property
    def is_search_pending(self) -> bool:
        """Check if an async file search is in progress."""
        return self._pending_worker is not None

    # Methods removed - now using launch components:
    # - _is_rez_available() → self.env_manager.is_rez_available(Config)
    # - _get_rez_packages_for_app() → self.env_manager.get_rez_packages(app_name, Config)
    # - _detect_available_terminal() → self.env_manager.detect_terminal()
    # - _validate_path_for_shell() → CommandBuilder.validate_path(path)

    def _launch_in_new_terminal(
        self,
        full_command: str,
        app_name: str,
        error_context: str = "",
        has_rez_wrapper: bool = False,
    ) -> bool:
        """Launch command in new terminal window with full error handling.

        Delegates to ProcessExecutor for terminal spawning. Supports headless
        mode when no terminal emulator is available.

        Args:
            full_command: Complete command to execute
            app_name: Application name (for spawn verification and error messages)
            error_context: Additional context for error messages (e.g., " with scene")
            has_rez_wrapper: If True, command contains rez wrapper with inner bash -ilc.
                Enables shell optimization (sh -c instead of bash -ilc for outer shell).

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
            full_command, app_name, terminal, has_rez_wrapper=has_rez_wrapper
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
        self,
        full_command: str,
        app_name: str,
        error_context: str = "",
        has_rez_wrapper: bool = False,
    ) -> bool:
        """Execute command in a new terminal window.

        Template method for all launch operations.

        Args:
            full_command: Complete command to execute (with logging, rez, etc.)
            app_name: Application name (for spawn verification)
            error_context: Additional context for error messages (e.g., " with scene")
            has_rez_wrapper: If True, enables shell optimization for rez-wrapped commands.

        Returns:
            True if launch successful, False otherwise
        """
        return self._launch_in_new_terminal(
            full_command, app_name, error_context, has_rez_wrapper
        )

    def launch_app(
        self,
        app_name: str,
        context: LaunchContext | None = None,
        # Legacy parameters for backward compatibility
        open_latest_threede: bool = False,
        open_latest_maya: bool = False,
        open_latest_scene: bool = False,
        create_new_file: bool = False,
        selected_plate: str | None = None,
        sequence_path: str | None = None,
    ) -> bool:
        """Launch an application in the current shot context.

        Args:
            app_name: Name of the application to launch
            context: Launch context with options (preferred)
            open_latest_threede: (Legacy) Whether to open the latest 3DE scene file (3DE only)
            open_latest_maya: (Legacy) Whether to open the latest Maya scene file (Maya only)
            open_latest_scene: (Legacy) Whether to open the latest Nuke script (Nuke only)
            create_new_file: (Legacy) Whether to create a new version (Nuke only)
            selected_plate: (Legacy) Selected plate space for Nuke workspace scripts
            sequence_path: (Legacy) Image sequence path for RV playback

        Returns:
            True if launch was successful, False otherwise

        Note:
            The context parameter is preferred. Legacy parameters are kept for
            backward compatibility but will be removed in a future version.
        """
        # Handle backward compatibility: if context not provided, create from legacy params
        if context is None:
            context = LaunchContext(
                open_latest_threede=open_latest_threede,
                open_latest_maya=open_latest_maya,
                open_latest_scene=open_latest_scene,
                create_new_file=create_new_file,
                selected_plate=selected_plate,
                sequence_path=sequence_path,
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

        # Handle 3DE/Maya with latest scene file (async-aware)
        needs_file_search = (
            (app_name == "3de" and context.open_latest_threede)
            or (app_name == "maya" and context.open_latest_maya)
        )

        if needs_file_search:
            workspace = self.current_shot.workspace_path

            # Check cache first
            threede_cached: Path | None = None
            maya_cached: Path | None = None
            cache_hit = True

            if app_name == "3de" and context.open_latest_threede:
                threede_cached = self._cache_manager.get_cached_latest_file(
                    workspace, "threede"
                )
                if threede_cached is None:
                    # Check if we have a "not found" cache entry (path is None in cache)
                    # vs no cache entry at all (need to search)
                    cache_data = self._cache_manager._read_latest_files_cache()
                    key = f"{workspace}:threede"
                    if cache_data is None or key not in cache_data:
                        cache_hit = False
                    # else: cache says "not found", use None as result

            if app_name == "maya" and context.open_latest_maya:
                maya_cached = self._cache_manager.get_cached_latest_file(
                    workspace, "maya"
                )
                if maya_cached is None:
                    cache_data = self._cache_manager._read_latest_files_cache()
                    key = f"{workspace}:maya"
                    if cache_data is None or key not in cache_data:
                        cache_hit = False

            if cache_hit:
                # Use cached result - add scene path to command
                if app_name == "3de" and threede_cached:
                    try:
                        safe_scene_path = CommandBuilder.validate_path(
                            str(threede_cached)
                        )
                        command = f"{command} -open {safe_scene_path}"
                        self.command_executed.emit(
                            self.timestamp,
                            f"Opening latest 3DE scene: {threede_cached.name}",
                        )
                    except ValueError as e:
                        self._emit_error(
                            f"Cannot launch 3DE: Invalid scene path '{threede_cached}': {e!s}"
                        )
                        return False
                elif app_name == "3de" and context.open_latest_threede:
                    self.command_executed.emit(
                        self.timestamp,
                        "Info: No 3DE scene files found in workspace",
                    )

                if app_name == "maya" and maya_cached:
                    try:
                        safe_scene_path = CommandBuilder.validate_path(
                            str(maya_cached)
                        )
                        command = f"{command} -file {safe_scene_path}"
                        self.command_executed.emit(
                            self.timestamp,
                            f"Opening latest Maya scene: {maya_cached.name}",
                        )
                    except ValueError as e:
                        self._emit_error(
                            f"Cannot launch Maya: Invalid scene path '{maya_cached}': {e!s}"
                        )
                        return False
                elif app_name == "maya" and context.open_latest_maya:
                    self.command_executed.emit(
                        self.timestamp,
                        "Info: No Maya scene files found in workspace",
                    )
            else:
                # Cache miss - start async search and return
                # Launch will continue when search completes
                self._start_async_file_search(app_name, context, command)
                return True  # Async launch in progress

        # Handle RV with default settings and optional sequence path
        if app_name == "rv":
            # Add default RV settings: 12fps, auto-play, oscillate (ping-pong) mode
            command = f"{command} -fps 12 -play -eval 'setPlayMode(2)'"

            # Add sequence path if provided
            if context.sequence_path:
                try:
                    safe_sequence_path = CommandBuilder.validate_path(
                        context.sequence_path
                    )
                    command = f"{command} {safe_sequence_path}"
                    timestamp = self.timestamp
                    # Extract just the filename for cleaner logging
                    from pathlib import Path

                    seq_name = Path(context.sequence_path).name
                    self.command_executed.emit(
                        timestamp,
                        f"Opening sequence in RV: {seq_name}",
                    )
                except ValueError as e:
                    self._emit_error(
                        f"Cannot launch RV: Invalid sequence path '{context.sequence_path}': {e!s}"
                    )
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

        # Determine if rez wrapping should be applied using the new RezMode enum
        should_wrap_rez = self.env_manager.should_wrap_with_rez(Config)
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
                should_wrap_rez = False  # No packages means no actual rez wrapper
        else:
            full_command = ws_command
            # Emit message explaining why Rez wrapping is skipped
            timestamp = self.timestamp
            if os.environ.get("REZ_USED"):
                self.command_executed.emit(
                    timestamp,
                    f"Note: Already in rez environment - skipping rez wrap for {app_name}",
                )
            else:
                self.command_executed.emit(
                    timestamp,
                    f"Note: Using system PATH version of {app_name}",
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
        return self._execute_launch(
            full_command, app_name, has_rez_wrapper=should_wrap_rez
        )

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

        # Determine if rez wrapping should be applied using the new RezMode enum
        should_wrap_rez = self.env_manager.should_wrap_with_rez(Config)
        if should_wrap_rez:
            rez_packages = self.env_manager.get_rez_packages(app_name, Config)
            if rez_packages:
                # Use CommandBuilder to wrap with rez environment
                full_command = CommandBuilder.wrap_with_rez(ws_command, rez_packages)
            else:
                full_command = ws_command
                should_wrap_rez = False  # No packages means no actual rez wrapper
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
        return self._execute_launch(
            full_command, app_name, " with scene", has_rez_wrapper=should_wrap_rez
        )

    def launch_with_file(
        self,
        app_name: str,
        file_path: Path,
        workspace_path: str,
    ) -> bool:
        """Launch an application with a specific file.

        Args:
            app_name: Name of the application to launch (e.g., '3de', 'maya', 'nuke')
            file_path: Path to the file to open
            workspace_path: Shot workspace path for environment setup

        Returns:
            True if launch was successful, False otherwise
        """
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Include the file in the command
        # Validate and escape file path to prevent injection
        try:
            safe_file_path = CommandBuilder.validate_path(str(file_path))
            # Add app-specific command-line flags for file
            if app_name == "3de":
                command = f"{command} -open {safe_file_path}"
            elif app_name == "maya":
                command = f"{command} -file {safe_file_path}"
            else:
                # Nuke and others accept file without flag
                command = f"{command} {safe_file_path}"
        except ValueError as e:
            self._emit_error(f"Invalid file path: {e!s}")
            return False

        # Validate workspace before attempting launch
        if not self._validate_workspace_before_launch(workspace_path, app_name):
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
            safe_workspace_path = CommandBuilder.validate_path(workspace_path)

            # Apply Nuke environment fixes if needed
            env_fixes = self._apply_nuke_environment_fixes(app_name, "File launch")

            # Build workspace command with environment fixes
            ws_command = f"ws {safe_workspace_path} && {env_fixes}{command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        # Determine if rez wrapping should be applied using the new RezMode enum
        should_wrap_rez = self.env_manager.should_wrap_with_rez(Config)
        if should_wrap_rez:
            rez_packages = self.env_manager.get_rez_packages(app_name, Config)
            if rez_packages:
                full_command = CommandBuilder.wrap_with_rez(ws_command, rez_packages)
            else:
                full_command = ws_command
                should_wrap_rez = False  # No packages means no actual rez wrapper
        else:
            full_command = ws_command

        # Add logging redirection for debugging
        full_command = CommandBuilder.add_logging(full_command, Config)

        # Log the command
        timestamp = self.timestamp
        self.command_executed.emit(
            timestamp,
            f"{full_command} (File: {file_path.name})",
        )

        # Use template method for terminal launch
        return self._execute_launch(
            full_command, app_name, " with file", has_rez_wrapper=should_wrap_rez
        )

    def launch_app_with_scene_context(
        self,
        app_name: str,
        scene: ThreeDEScene,
    ) -> bool:
        """Launch an application in the context of a 3DE scene (shot context only, no scene file).

        Args:
            app_name: Name of the application to launch
            scene: The 3DE scene providing shot context

        Returns:
            True if launch was successful, False otherwise
        """
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Get the command
        command = Config.APPS[app_name]

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

        # Determine if rez wrapping should be applied using the new RezMode enum
        should_wrap_rez = self.env_manager.should_wrap_with_rez(Config)
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
                should_wrap_rez = False  # No packages means no actual rez wrapper
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
        return self._execute_launch(
            full_command, app_name, " in scene context", has_rez_wrapper=should_wrap_rez
        )

    # Methods removed - now using launch components:
    # - _is_gui_app() → self.process_executor.is_gui_app(app_name)
    # - _verify_spawn() → self.process_executor._verify_spawn(process, app_name)

    # Maximum command length (bytes) - gnome-terminal buffer is ~8KB, be conservative
    # Linux ARG_MAX is ~131KB but terminal emulators have smaller buffers
    MAX_COMMAND_LENGTH: int = 8000

    def _validate_workspace_before_launch(
        self, workspace_path: str, app_name: str
    ) -> bool:
        """Validate workspace is accessible before launching application.

        Performs pre-flight checks (advisory):
        1. Workspace directory exists
        2. Workspace path is a directory (not a file)
        3. User has read and execute permissions

        Note:
            Permission checks are advisory only due to TOCTOU (time-of-check to
            time-of-use) race conditions. Permissions could change between check
            and actual use. These checks provide early user feedback but don't
            guarantee success.

            Disk space is NOT checked - VFX production storage always has
            sufficient space, and the statvfs() call can block for 10+ seconds
            on slow NFS mounts, causing UI freezes.

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
