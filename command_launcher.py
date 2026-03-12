"""Command launcher for executing applications in shot context.

This module provides the production launcher system for Shotbot, handling:
- Application launching with shot context
- Rez environment integration
- Process lifecycle management
"""

from __future__ import annotations

# Standard library imports
import base64
import os
import shlex
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, final

# Third-party imports
from PySide6.QtCore import QMetaObject, QObject, Qt, Signal

# Local application imports
from config import Config, RezMode
from latest_file_finder_worker import LatestFileFinderWorker
from launch import (
    AppHandler,
    CommandBuilder,
    EnvironmentManager,
    GenericAppHandler,
    MayaAppHandler,
    NukeAppHandler,
    ProcessExecutor,
    RVAppHandler,
    ThreeDEAppHandler,
)
from logging_mixin import LoggingMixin
from notification_manager import NotificationManager
from nuke_launch_router import NukeLaunchRouter
from settings_manager import SettingsManager


if TYPE_CHECKING:
    # Local application imports
    from cache.latest_file_cache import LatestFileCache
    from shot_model import Shot
    from threede_scene_model import ThreeDEScene


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


@dataclass(frozen=True)
class PendingLaunch:
    """Groups non-worker pending state for async file searches."""

    app_name: str
    context: LaunchContext
    command: str


# Number of consecutive verification timeouts before resetting terminal cache.
# A single timeout is normal (VFX apps boot slowly); repeated failures indicate
# a broken terminal/environment.
_TIMEOUT_THRESHOLD_FOR_CACHE_RESET: int = 3

# Named sentinels for _build_app_command return values.
# Using named constants avoids magic (None, bool) tuples at each return site.
ASYNC_IN_PROGRESS: tuple[None, bool] = (None, True)
LAUNCH_ERROR: tuple[None, bool] = (None, False)


@final
class CommandLauncher(LoggingMixin, QObject):
    """Handles launching applications in shot context.

    This class uses dependency injection for better testability and following SOLID principles.
    Dependencies are passed as constructor parameters rather than imported directly.
    """

    # Signals
    launch_pending = Signal()  # Emitted when async file search starts
    launch_ready = Signal()  # Emitted when async search completes (ready to launch)

    # Maya bootstrap script that upgrades SGTK context from Shot → Shot+Task.
    # Uses a background thread to poll for SGTK engine availability with real
    # time.sleep() delays (immune to event-loop blocking during plugin loading),
    # then dispatches the context update to the main thread.
    _MAYA_BOOTSTRAP_SCRIPT = """
import maya.cmds
import maya.utils
import traceback
import threading
import time

def _shotbot_wait_for_sgtk():
    for _ in range(50):
        time.sleep(0.5)
        try:
            import sgtk
            if sgtk.platform.current_engine():
                maya.utils.executeDeferred(_shotbot_update_context)
                return
        except ImportError:
            return
    maya.utils.executeDeferred(
        lambda: print("[Shotbot] No SGTK engine available after retries")
    )

def _shotbot_update_context():
    try:
        import sgtk
    except ImportError:
        return

    engine = sgtk.platform.current_engine()
    if not engine:
        return

    scene_path = maya.cmds.file(query=True, sceneName=True)
    if not scene_path:
        print("[Shotbot] No scene file loaded")
        return

    if engine.context.task:
        return

    try:
        new_context = engine.sgtk.context_from_path(scene_path)
    except Exception as e:
        print(f"[Shotbot] Error deriving context from path: {e}")
        return

    if not new_context:
        print(f"[Shotbot] Could not derive context from: {scene_path}")
        return

    if not new_context.task:
        print(f"[Shotbot] File path doesn't match task template: {scene_path}")
        return

    try:
        sgtk.platform.change_context(new_context)
        print(f"[Shotbot] Context updated to: {new_context}")
    except Exception as e:
        print(f"[Shotbot] Error changing context: {e}")
        traceback.print_exc()

threading.Thread(target=_shotbot_wait_for_sgtk, daemon=True).start()
"""

    def __init__(
        self,
        parent: QObject | None = None,
        settings_manager: SettingsManager | None = None,
        cache_manager: LatestFileCache | None = None,
    ) -> None:
        """Initialize CommandLauncher with optional dependencies.

        Args:
            parent: Optional parent QObject for proper Qt ownership
            settings_manager: Optional SettingsManager for configuration.
                If not provided, creates a new instance.
            cache_manager: Optional LatestFileCache for file caching.
                If not provided, creates a new instance.

        """
        super().__init__(parent)
        self.current_shot: Shot | None = None
        self._settings_manager = settings_manager or SettingsManager()

        # Track signal connections for proper cleanup
        self._signal_connections: list[QMetaObject.Connection] = []

        # Cache manager for latest files
        if cache_manager is None:
            from cache.latest_file_cache import make_default_latest_file_cache
            cache_manager = make_default_latest_file_cache()
        self._cache_manager = cache_manager

        # Async file search state
        self._pending_worker: LatestFileFinderWorker | None = None
        self._pending_launch: PendingLaunch | None = None

        # Counter for consecutive verification timeouts; reset on success.
        # See _on_app_verification_timeout and _TIMEOUT_THRESHOLD_FOR_CACHE_RESET.
        self._consecutive_timeout_count: int = 0

        # Initialize launch components
        self.env_manager = EnvironmentManager()
        self.env_manager.warm_cache_async()  # Pre-warm caches in background
        self.process_executor = ProcessExecutor(Config, parent=self)

        # Initialize the Nuke launch handler
        self.nuke_handler = NukeLaunchRouter()

        # Per-DCC handlers for launch_with_file command building
        self._app_handlers: dict[str, AppHandler] = {
            "nuke": NukeAppHandler(scripts_dir=Config.SCRIPTS_DIR),
            "3de": ThreeDEAppHandler(scripts_dir=Config.SCRIPTS_DIR),
            "maya": MayaAppHandler(bootstrap_script=self._MAYA_BOOTSTRAP_SCRIPT),
            "rv": RVAppHandler(),
        }
        self._default_handler: AppHandler = GenericAppHandler()

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

        return env_fixes

    def _build_maya_context_command(
        self,
        base_command: str,
        file_path: str,
        context_script: str | None = None,
    ) -> str:
        """Build Maya launch command with SGTK context update.

        Uses environment variable approach to avoid complex quote escaping.
        The base64-encoded script is passed via SHOTBOT_MAYA_SCRIPT env var,
        and a static bootstrap command reads and executes it.

        Args:
            base_command: Base maya command (e.g., "maya")
            file_path: Path to Maya file to open
            context_script: Python script to execute after file loads.
                            If None, uses self._MAYA_BOOTSTRAP_SCRIPT.

        Returns:
            Full command string with env var export and maya invocation

        """
        script_to_run = context_script if context_script is not None else self._MAYA_BOOTSTRAP_SCRIPT
        encoded = base64.b64encode(script_to_run.encode()).decode()
        # Static bootstrap - reads from env var, no dynamic content in -c argument
        # This avoids the quote escaping nightmare when passing through bash -ilc
        mel_bootstrap = (
            'python("import os,base64;'
            "s=os.environ.get('SHOTBOT_MAYA_SCRIPT','');"
            'exec(base64.b64decode(s).decode()) if s else None")'
        )
        return (
            f"export SHOTBOT_MAYA_SCRIPT={encoded} && "
            f"{base_command} -file {file_path} -c {shlex.quote(mel_bootstrap)}"
        )

    def _apply_file_result(
        self,
        app_name: str,
        command: str,
        file_result: Path | None,
        wanted: bool,
    ) -> str | None:
        """Apply a scene file search result to the launch command.

        Args:
            app_name: Application name ("3de" or "maya")
            command: Current command string
            file_result: Path found by search, or None
            wanted: Whether the user requested this file type

        Returns:
            Updated command string, or None if _append_scene_to_command failed.

        """
        if file_result:
            return self._append_scene_to_command(app_name, command, file_result)
        return command

    def _append_scene_to_command(
        self, app_name: str, command: str, scene_path: Path
    ) -> str | None:
        """Append a scene file to a launch command, returning the updated command.

        Validates the scene path and builds the app-specific command fragment.
        Emits an error signal and returns None if the path is invalid.

        Args:
            app_name: Application name ("3de" or "maya").
            command: Base command string to append to.
            scene_path: Validated scene file path to append.

        Returns:
            Updated command string, or None if path validation failed.

        """
        try:
            safe_scene_path = CommandBuilder.validate_path(str(scene_path))
        except ValueError as e:
            self._emit_error(
                f"Cannot launch {app_name.upper()}: Invalid scene path '{scene_path}': {e!s}"
            )
            return None

        if app_name == "3de":
            tde_scripts_export = (
                f"export PYTHON_CUSTOM_SCRIPTS_3DE4={Config.SCRIPTS_DIR}:"
                "$PYTHON_CUSTOM_SCRIPTS_3DE4 && "
            )
            sgtk_export = f"export SGTK_FILE_TO_OPEN={safe_scene_path} && "
            return f"{tde_scripts_export}{sgtk_export}{command} -open {safe_scene_path}"

        if app_name == "maya":
            updated = self._build_maya_context_command(command, safe_scene_path)
            return f"export SGTK_FILE_TO_OPEN={safe_scene_path} && {updated}"

        # Unsupported app — caller should not reach this path
        self.logger.warning(f"_append_scene_to_command called for unsupported app: {app_name}")
        return command

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

    # Maximum command length (bytes) - gnome-terminal buffer is ~8KB, be conservative
    # Linux ARG_MAX is ~131KB but terminal emulators have smaller buffers
    MAX_COMMAND_LENGTH: int = 8000

    def _on_app_verification_timeout(self, app_name: str) -> None:
        """Handle app verification timeout from ProcessExecutor.

        VFX apps can take 30-60+ seconds to boot (Rez resolution + plugin scanning).
        A single timeout doesn't necessarily mean the terminal is broken - the app
        may still be starting. Only reset cache after repeated consecutive failures.

        Args:
            app_name: Name of the application that failed verification

        """
        self._consecutive_timeout_count += 1

        if self._consecutive_timeout_count >= _TIMEOUT_THRESHOLD_FOR_CACHE_RESET:
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
        self._pending_launch = PendingLaunch(app_name=app_name, context=context, command=command)

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
        """Handle async file search completion (Qt slot, QueuedConnection).

        This is the second half of the async launch lifecycle initiated by
        _start_async_file_search. It is connected to
        LatestFileFinderWorker.search_complete and called on the main thread
        via QueuedConnection after the worker thread finishes.

        Pending state when this fires:
          - self._pending_worker   — the worker that just completed
          - self._pending_app_name — "3de" or "maya"
          - self._pending_context  — original LaunchContext
          - self._pending_command  — base command built before async started

        Cleanup: this method always clears the pending worker and emits
        launch_ready to hide the UI spinner regardless of success. On
        success it delegates to _continue_launch_after_search; on failure
        it clears all pending state and returns without launching.

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
            if self._pending_launch and self._pending_launch.context.open_latest_maya:
                self._cache_manager.cache_latest_file(workspace, "maya", maya_result)
            if self._pending_launch and self._pending_launch.context.open_latest_threede:
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
            self._clear_pending_state()

    def _continue_launch_after_search(
        self,
        maya_result: Path | None,
        threede_result: Path | None,
    ) -> None:
        """Finish the launch sequence after an async file search succeeds.

        Called from _on_async_search_complete only when success=True. By the
        time this runs, the pending worker has already been cleaned up and the
        UI spinner hidden.

        This method consumes and clears the remaining pending state
        (app_name, context, command), then calls _append_scene_to_command to
        build the final command and _finish_launch to execute it. If any
        pending state is missing (shouldn't happen in normal flow), it logs an
        error and returns without launching.

        Args:
            maya_result: Latest Maya scene found by the worker, or None.
            threede_result: Latest 3DE scene found by the worker, or None.

        """
        launch = self._pending_launch

        # Clear pending state
        self._clear_pending_state()

        if launch is None:
            self.logger.error("Missing pending state after async search")
            return

        app_name = launch.app_name
        context = launch.context
        command = launch.command

        # Add scene path to command based on results
        if app_name == "3de":
            result = self._apply_file_result("3de", command, threede_result, context.open_latest_threede)
            if result is None:
                return
            command = result

        if app_name == "maya":
            result = self._apply_file_result("maya", command, maya_result, context.open_latest_maya)
            if result is None:
                return
            command = result

        # Continue with the rest of launch_app flow (from ws command onwards)
        _ = self._finish_launch(app_name, command)

    def _finish_launch(
        self,
        app_name: str,
        command: str,
        workspace_path: str | None = None,
        nuke_env_context: str = "",
        log_suffix: str = "",
        error_context: str = "",
        command_prefix: str = "",
    ) -> bool:
        """Complete the launch: ws wrap, rez wrap, logging, and execute.

        This is the single dispatch point for all launch operations, shared
        between the sync (cache hit) and async (cache miss) paths and all
        four public launch methods.

        Args:
            app_name: Application name
            command: Command with scene path (if any) already added
            workspace_path: Workspace directory for the ws command.
                If None, falls back to self.current_shot.workspace_path.
            nuke_env_context: Context string for Nuke environment fix log message
            log_suffix: Appended to the emitted full_command (e.g., " (Scene by: ...)")
            error_context: Context for error messages in _launch_in_new_terminal
            command_prefix: Shell prefix inserted between ws and env_fixes
                (e.g., "export SGTK_FILE_TO_OPEN=... && ")

        Returns:
            True if launch succeeded, False otherwise

        """
        # Resolve workspace path
        if workspace_path is None:
            if self.current_shot is None:
                self._emit_error("Cannot launch - no shot selected")
                return False
            workspace_path = self.current_shot.workspace_path

        # Pre-flight: Check if ws command is available
        if not self.env_manager.is_ws_available():
            self._emit_error(
                "Workspace command 'ws' not found. "
                "Ensure workspace tools are installed and on PATH."
            )
            return False

        # Build app command first; workspace setup stays outside the Rez wrapper.
        try:
            safe_workspace_path = CommandBuilder.validate_path(workspace_path)
            env_fixes = self._apply_nuke_environment_fixes(app_name, nuke_env_context)
            app_command = f"{command_prefix}{env_fixes}{command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        has_rez_wrapper = False
        if Config.REZ_MODE != RezMode.DISABLED:
            rez_packages = self.env_manager.get_rez_packages(app_name, Config)
            if not rez_packages:
                self._emit_error(
                    f"Cannot launch {app_name}: no Rez packages are configured for this application."
                )
                return False
            if not self.env_manager.should_wrap_with_rez(Config):
                self._emit_error(
                    f"Cannot launch {app_name}: Rez is required, but the 'rez' command was not found on PATH."
                )
                return False

            app_command = CommandBuilder.wrap_with_rez(app_command, rez_packages)
            has_rez_wrapper = True

        full_command = CommandBuilder.build_workspace_command(
            safe_workspace_path, app_command
        )

        # Add logging redirection for debugging
        full_command = CommandBuilder.add_logging(full_command, Config)

        # Enhanced debug logging for command integrity verification
        self.logger.debug(
            f"Constructed command for {app_name}:\n"
            f"  Command: {full_command!r}\n"
            f"  Length: {len(full_command)} chars\n"
            f"  Workspace: {workspace_path}"
        )

        # Execute launch
        return self._launch_in_new_terminal(
            full_command, app_name, error_context, has_rez_wrapper=has_rez_wrapper
        )

    def _clear_pending_state(self) -> None:
        """Clear pending async launch state."""
        self._pending_launch = None

    def cancel_pending_search(self) -> None:
        """Cancel any pending async file search."""
        if self._pending_worker is not None:
            _ = self._pending_worker.request_stop()
            _ = self._pending_worker.safe_stop(timeout_ms=1000)
            self._pending_worker = None
            self._clear_pending_state()
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


    def _build_rv_command(
        self,
        command: str,
        context: LaunchContext,
    ) -> str | None:
        """Build the RV playback command with default flags and optional sequence path.

        Appends standard RV playback flags and, when a sequence path is provided,
        validates and appends it to the command.

        Args:
            command: Base RV command string (e.g. "rv").
            context: Launch context; only sequence_path is used here.

        Returns:
            Complete RV command string, or None if the sequence path is invalid.

        """
        command = f"{command} -fps 12 -play -eval 'setPlayMode(2)'"
        if context.sequence_path:
            try:
                safe_sequence_path = CommandBuilder.validate_path(context.sequence_path)
                command = f"{command} {safe_sequence_path}"
            except ValueError as e:
                self._emit_error(
                    f"Cannot launch RV: Invalid sequence path '{context.sequence_path}': {e!s}"
                )
                return None
        return command

    def _build_app_command(
        self,
        app_name: str,
        context: LaunchContext,
    ) -> tuple[str | None, bool]:
        """Build the app-specific command string for launch_app.

        Handles app-specific command building for Nuke, 3DE, Maya, and RV.
        Emits log signals as a side effect.

        Args:
            app_name: Application name (must already be validated against Config.APPS)
            context: Launch context with options

        Returns:
            (command, is_async) tuple where:
            - command is the built command string, or None to stop
            - is_async is True when an async file search was started (return True from caller)
            - (None, False) means an error was emitted; caller should return False
            - (None, True) means async search started; caller should return True

        """
        # Precondition: caller must have verified current_shot is not None
        assert self.current_shot is not None, "_build_app_command called without a current shot"
        command = Config.APPS[app_name]

        # Handle Nuke-specific launching logic
        if app_name == "nuke":
            options = {
                "open_latest_scene": context.open_latest_scene,
                "create_new_file": context.create_new_file,
            }
            command, _ = self.nuke_handler.prepare_nuke_command(
                self.current_shot, command, options, selected_plate=context.selected_plate
            )
            if not command:
                self._emit_error("Nuke launch aborted - see log messages above")
                return LAUNCH_ERROR

        # Handle 3DE/Maya with latest scene file (async-aware)
        needs_file_search = (
            (app_name == "3de" and context.open_latest_threede)
            or (app_name == "maya" and context.open_latest_maya)
        )

        if needs_file_search:
            workspace = self.current_shot.workspace_path
            file_type = "threede" if app_name == "3de" else "maya"
            wanted = context.open_latest_threede if app_name == "3de" else context.open_latest_maya
            cache_result = self._cache_manager.get_latest_file_cache_result(workspace, file_type)

            if cache_result.status == "miss":
                # Cache miss - start async search and return
                # Launch will continue when search completes
                self._start_async_file_search(app_name, context, command)
                return ASYNC_IN_PROGRESS

            # Cache hit (or "not_found") - apply result immediately
            applied = self._apply_file_result(app_name, command, cache_result.path, wanted)
            if applied is None:
                return LAUNCH_ERROR
            command = applied

        # Handle RV with default settings and optional sequence path
        if app_name == "rv":
            rv_command = self._build_rv_command(command, context)
            if rv_command is None:
                return LAUNCH_ERROR
            command = rv_command

        return command, False

    def launch_app(
        self,
        app_name: str,
        context: LaunchContext | None = None,
    ) -> bool:
        """Launch an application in the current shot context.

        Args:
            app_name: Name of the application to launch
            context: Launch context with options

        Returns:
            True if launch was successful, False otherwise

        """
        if context is None:
            context = LaunchContext()

        if not self.current_shot:
            self._emit_error("No shot selected")
            return False

        if not self._validate_app_name(app_name):
            return False

        # Validate workspace before launching
        if not self._validate_workspace_before_launch(
            self.current_shot.workspace_path, app_name
        ):
            return False

        command, is_async = self._build_app_command(app_name, context)
        if command is None:
            return is_async  # True = async started, False = error

        return self._finish_launch(app_name, command)

    def launch_app_with_scene(self, app_name: str, scene: ThreeDEScene) -> bool:
        """Launch an application with a specific 3DE scene file.

        Args:
            app_name: Name of the application to launch
            scene: The 3DE scene to open

        Returns:
            True if launch was successful, False otherwise

        """
        if not self._validate_app_name(app_name):
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Include the scene file in the command
        # Validate and escape scene path to prevent injection
        try:
            safe_scene_path = CommandBuilder.validate_path(str(scene.scene_path))
            command_prefix = ""
            # Add app-specific command-line flags for scene file
            if app_name == "3de":
                # 3DE gets the scene file + scripts export + SGTK context
                tde_scripts_export = (
                    f"export PYTHON_CUSTOM_SCRIPTS_3DE4={Config.SCRIPTS_DIR}:"
                    "$PYTHON_CUSTOM_SCRIPTS_3DE4 && "
                )
                sgtk_export = f"export SGTK_FILE_TO_OPEN={safe_scene_path} && "
                command = f"{command} -open {safe_scene_path}"
                command_prefix = f"{tde_scripts_export}{sgtk_export}"
            elif app_name == "nuke":
                # Nuke gets context-only launch with NUKE_PATH for startup hooks
                nuke_path_export = f"export NUKE_PATH={Config.SCRIPTS_DIR}:$NUKE_PATH && "
                sgtk_export = f"export SGTK_FILE_TO_OPEN={safe_scene_path} && "
                command_prefix = f"{nuke_path_export}{sgtk_export}"
            elif app_name == "maya":
                # Maya gets context-only launch with SGTK_FILE_TO_OPEN
                command_prefix = f"export SGTK_FILE_TO_OPEN={safe_scene_path} && "
        except ValueError as e:
            self._emit_error(f"Invalid scene path: {e!s}")
            return False

        # Validate workspace before attempting launch
        if not self._validate_workspace_before_launch(scene.workspace_path, app_name):
            return False

        return self._finish_launch(
            app_name,
            command,
            workspace_path=scene.workspace_path,
            nuke_env_context="Nuke scene launch",
            log_suffix=f" (Scene by: {scene.user}, Plate: {scene.plate})",
            error_context=" with scene",
            command_prefix=command_prefix,
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
        if not self._validate_app_name(app_name):
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Include the file in the command
        # Validate and escape file path to prevent injection
        try:
            safe_file_path = CommandBuilder.validate_path(str(file_path))
            handler = self._app_handlers.get(app_name, self._default_handler)
            command = handler.build_file_command(command, safe_file_path)

            # Log file launch details for debugging file dialog issues
            self.logger.debug(
                f"launch_with_file: app={app_name}, "
                f"file_path={file_path}, "
                f"safe_file_path={safe_file_path}, "
                f"command={command}"
            )
        except ValueError as e:
            self._emit_error(f"Invalid file path: {e!s}")
            return False

        # Validate workspace before attempting launch
        if not self._validate_workspace_before_launch(workspace_path, app_name):
            return False

        # Set SGTK_FILE_TO_OPEN for SGTK-enabled apps (Maya, Nuke, 3DE)
        # This tells ShotGrid Toolkit to bootstrap context from the file path,
        # ensuring the full environment is loaded when opening via command line
        # safe_file_path was validated above in the command-building block
        handler = self._app_handlers.get(app_name, self._default_handler)
        if handler.needs_sgtk_file_to_open():
            sgtk_export = f"export SGTK_FILE_TO_OPEN={safe_file_path} && "
            self.logger.debug(f"Setting SGTK_FILE_TO_OPEN={safe_file_path}")
        else:
            sgtk_export = ""

        return self._finish_launch(
            app_name,
            command,
            workspace_path=workspace_path,
            nuke_env_context="File launch",
            log_suffix=f" (File: {file_path.name})",
            error_context=" with file",
            command_prefix=sgtk_export,
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
        if not self._validate_app_name(app_name):
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Validate workspace before attempting launch
        if not self._validate_workspace_before_launch(scene.workspace_path, app_name):
            return False

        return self._finish_launch(
            app_name,
            command,
            workspace_path=scene.workspace_path,
            nuke_env_context="scene context launch",
            log_suffix=f" (Context: {scene.user}'s {scene.plate})",
            error_context=" in scene context",
        )

    # Methods removed - now using launch components:
    # - _is_gui_app() → self.process_executor.is_gui_app(app_name)
    # - _verify_spawn() → self.process_executor._verify_spawn(process, app_name)

    def _validate_app_name(self, app_name: str) -> bool:
        """Return True if app_name is valid, emit error and return False otherwise."""
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False
        return True

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
        """Log an error with timestamp."""
        self.logger.error(error)

    # Old terminal signal handlers removed - now using ProcessExecutor signals:
    # - _on_terminal_progress() → _on_execution_progress()
    # - _on_terminal_command_result() → _on_execution_completed()
