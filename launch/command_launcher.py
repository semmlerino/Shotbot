"""Command launcher for executing applications in shot context.

Architecture: CommandLauncher uses a 4-component pattern:
1. CommandLauncher: Orchestrator managing launch lifecycle and state machine (IDLE, VERIFYING_APP,
   SEARCHING_FILES, EXECUTING)
2. AppHandler subclasses: Per-DCC logic (NukeAppHandler, ThreeDEAppHandler, MayaAppHandler,
   RVAppHandler) that build app-specific commands
3. CommandBuilder functions and LaunchOperation: Command construction and execution, including
   environment setup, process execution, and file resolution
4. ResolvedCommand: Immutable representation of the final command with all paths and flags

Callback Injection Pattern: Instead of importing UI or discovery modules directly (which would
create circular dependencies), callbacks are injected into AppHandlers:
- emit_error: Logs errors and prevents circular imports with controllers
- start_async_search: Delegates file discovery to FileSearchCoordinator without direct coupling
- apply_file_result: Attaches resolved scene paths to commands post-discovery
This pattern enables unit testing (callbacks are mocked) and maintains separation between launcher,
UI, and discovery.

Async Launch Lifecycle: For apps that search for files (3DE, Maya):
- ASYNC_IN_PROGRESS (None, True): File lookup will complete via async callback—handler has already
  started the search, return True from caller
- LAUNCH_ERROR (None, False): File resolution failed—handler has emitted error, abort launch
"""

from __future__ import annotations

# Standard library imports
import enum
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, final

# Third-party imports
from PySide6.QtCore import QMetaObject, QObject, Qt, Signal

# Local application imports
from commands import maya_commands
from commands.threede_commands import build_threede_scripts_export
from config import Config
from launch.app_handlers import (
    AppHandler,
    GenericAppHandler,
    MayaAppHandler,
    NukeAppHandler,
    RVAppHandler,
    ThreeDEAppHandler,
)
from launch.command_builder import validate_path
from launch.environment_manager import EnvironmentManager
from launch.file_search_coordinator import FileSearchCoordinator
from launch.launch_operation import LaunchOperation
from launch.process_executor import ProcessExecutor
from managers.notification_manager import NotificationManager
from managers.settings_manager import SettingsManager
from nuke import NukeLaunchHandler, SimpleNukeLauncher


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    # Local application imports
    from cache.latest_file_cache import LatestFileCache
    from launch.launch_request import LaunchRequest
    from type_definitions import Shot


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


class LaunchPhase(enum.Enum):
    """Explicit state machine phases for CommandLauncher's async launch lifecycle."""

    IDLE = "idle"
    VERIFYING_APP = "verifying_app"
    SEARCHING_FILES = "searching_files"
    EXECUTING = "executing"


@final
class CommandLauncher(QObject):
    """Handles launching applications in shot context.

    This class uses dependency injection for better testability and following SOLID principles.
    Dependencies are passed as constructor parameters rather than imported directly.
    """

    # Signals — forwarded from FileSearchCoordinator so callers need not change.
    launch_pending = Signal()  # Emitted when async file search starts
    launch_ready = Signal()  # Emitted when async search completes (ready to launch)

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

        # Async file search coordinator — owns the worker and pending state
        self._file_search_coordinator = FileSearchCoordinator(
            cache_manager=self._cache_manager, parent=self
        )

        # Current launch phase (state machine tracking)
        self._phase: LaunchPhase = LaunchPhase.IDLE

        # Counter for consecutive verification timeouts; reset on success.
        # See _on_app_verification_timeout and _TIMEOUT_THRESHOLD_FOR_CACHE_RESET.
        self._consecutive_timeout_count: int = 0

        # Initialize launch components
        self.env_manager = EnvironmentManager()
        self.env_manager.warm_cache_async()  # Pre-warm caches in background
        self.process_executor = ProcessExecutor(Config, parent=self)

        # Initialize Nuke launch components
        self.nuke_launcher = SimpleNukeLauncher()
        self.nuke_env = NukeLaunchHandler()

        # Per-DCC handlers for launch_with_file and launch_app command building
        self._app_handlers: dict[str, AppHandler] = {
            "nuke": NukeAppHandler(
                scripts_dir=Config.SCRIPTS_DIR,
                nuke_launcher=self.nuke_launcher,
                emit_error=self._emit_error,
            ),
            "3de": ThreeDEAppHandler(
                scripts_dir=Config.SCRIPTS_DIR,
                cache_manager=self._cache_manager,
                start_async_search=self._start_async_file_search,
                apply_file_result=lambda app, cmd, path: (
                    LaunchOperation.apply_file_result(app, cmd, path, self._emit_error)
                ),
                emit_error=self._emit_error,
            ),
            "maya": MayaAppHandler(
                bootstrap_script=maya_commands.MAYA_BOOTSTRAP_SCRIPT,
                cache_manager=self._cache_manager,
                start_async_search=self._start_async_file_search,
                apply_file_result=lambda app, cmd, path: (
                    LaunchOperation.apply_file_result(app, cmd, path, self._emit_error)
                ),
                emit_error=self._emit_error,
            ),
            "rv": RVAppHandler(emit_error=self._emit_error),
        }
        self._default_handler: AppHandler = GenericAppHandler()

        # Connect process executor signals (track for cleanup)
        # Use QueuedConnection for thread-safe cross-thread signal handling
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
        self._signal_connections.append(
            self.process_executor.headless_launch_warning.connect(
                self._on_headless_launch_warning, Qt.ConnectionType.QueuedConnection
            )
        )
        self._signal_connections.append(
            self.process_executor.launch_crash_detected.connect(
                self._on_launch_crash_detected, Qt.ConnectionType.QueuedConnection
            )
        )

        # Forward coordinator signals onto CommandLauncher so callers don't change
        self._signal_connections.append(
            self._file_search_coordinator.launch_pending.connect(
                self.launch_pending, Qt.ConnectionType.QueuedConnection
            )
        )
        self._signal_connections.append(
            self._file_search_coordinator.launch_ready.connect(
                self.launch_ready, Qt.ConnectionType.QueuedConnection
            )
        )
        self._signal_connections.append(
            self._file_search_coordinator.search_result_ready.connect(
                self._on_search_result_ready, Qt.ConnectionType.QueuedConnection
            )
        )

    @property
    def timestamp(self) -> str:
        """Current UTC timestamp in HH:MM:SS format for logging.

        Returns:
            Formatted timestamp string suitable for log messages and UI display

        """
        return datetime.now(tz=UTC).strftime("%H:%M:%S")

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

        # Cancel any pending async file search via coordinator
        if hasattr(self, "_file_search_coordinator"):
            try:
                self._file_search_coordinator.cancel_pending_search()
            except (RuntimeError, TypeError):
                pass

        # Cleanup ProcessExecutor's signal connections
        try:
            if hasattr(self, "process_executor"):
                self.process_executor.cleanup()
        except (RuntimeError, TypeError, AttributeError):
            pass

    def __del__(self) -> None:
        """Ensure cleanup on destruction."""
        try:
            self.cleanup()
        except Exception:  # noqa: BLE001
            pass

    def set_current_shot(self, shot: Shot | None) -> None:
        """Set the current shot context."""
        self.current_shot = shot

    def _on_execution_completed(self, success: bool, message: str) -> None:
        """Handle execution completion from ProcessExecutor.

        Args:
            success: Whether execution completed successfully
            message: Completion message (empty if success, error if failed)

        """
        self._set_phase(LaunchPhase.IDLE)

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
        self._set_phase(LaunchPhase.IDLE)

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

        # Show user-visible notification for GUI apps that may have failed to start
        if self.process_executor.is_gui_app(app_name):
            NotificationManager.warning(
                "Launch Verification Failed",
                f"{app_name} may have failed to start. "
                "Check terminal or logs for errors.",
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
        logger.debug(f"App {app_name} verified with PID {pid}")

    def _on_headless_launch_warning(self, app_name: str) -> None:
        """Handle headless launch warning from ProcessExecutor."""
        # Local application imports
        NotificationManager.warning(
            "Headless Launch",
            f"No terminal found. {app_name} will run without terminal window. "
            "Install gnome-terminal, konsole, or xterm for better experience.",
        )

    def _on_launch_crash_detected(self, app_name: str) -> None:
        """Handle launch crash detection from ProcessExecutor."""
        # Local application imports
        NotificationManager.error("Launch Failed", f"{app_name} crashed immediately")

    # ========================================================================
    # Async Latest File Search — Coordinator Interface
    # ========================================================================

    def _start_async_file_search(
        self,
        app_name: str,
        context: LaunchContext,
        command: str,
    ) -> None:
        """Delegate async file search to FileSearchCoordinator.

        Args:
            app_name: Application being launched ("3de" or "maya")
            context: Launch context with search flags
            command: Base command built so far (before scene path added)

        """
        self._set_phase(LaunchPhase.SEARCHING_FILES)

        if self.current_shot is None:
            self._emit_error("Cannot search for files - no shot selected")
            return

        pending = PendingLaunch(app_name=app_name, context=context, command=command)
        self._file_search_coordinator.start_async_file_search(
            pending, self.current_shot
        )

    def _on_search_result_ready(
        self,
        pending_launch: object,
        maya_result: object,
        threede_result: object,
    ) -> None:
        """Handle a successful async search result from FileSearchCoordinator.

        This is the second half of the async launch lifecycle. It is connected
        to FileSearchCoordinator.search_result_ready (QueuedConnection) and
        called on the main thread after the coordinator has cleaned up the
        worker and emitted launch_ready to hide the UI spinner.

        Args:
            pending_launch: The PendingLaunch stored before the search started.
            maya_result: Latest Maya scene found, or None.
            threede_result: Latest 3DE scene found, or None.

        """
        self._set_phase(LaunchPhase.EXECUTING)

        # Qt signals carry arguments as `object`; cast to the expected types
        # so downstream code gets proper type narrowing and editor support.
        launch: PendingLaunch | None = pending_launch  # type: ignore[assignment]
        maya: Path | None = maya_result  # type: ignore[assignment]
        threede: Path | None = threede_result  # type: ignore[assignment]

        if launch is None:
            logger.error("Missing pending state after async search")
            self._set_phase(LaunchPhase.IDLE)
            return

        app_name = launch.app_name
        command = launch.command

        # Add scene path to command based on results
        if app_name == "3de":
            result = LaunchOperation.apply_file_result(
                "3de", command, threede, self._emit_error
            )
            if result is None:
                self._set_phase(LaunchPhase.IDLE)
                return
            command = result

        if app_name == "maya":
            result = LaunchOperation.apply_file_result(
                "maya", command, maya, self._emit_error
            )
            if result is None:
                self._set_phase(LaunchPhase.IDLE)
                return
            command = result

        # Continue with the rest of launch_app flow (from ws command onwards)
        _ = LaunchOperation(
            app_name=app_name,
            command=command,
            workspace_path=None,
            env_manager=self.env_manager,
            process_executor=self.process_executor,
            settings_manager=self._settings_manager,
            nuke_env=self.nuke_env,
            current_shot=self.current_shot,
            emit_error=self._emit_error,
        ).execute()

    def _finish_launch(
        self,
        app_name: str,
        command: str,
        workspace_path: str | None = None,
        log_suffix: str = "",
        error_context: str = "",
        command_prefix: str = "",
    ) -> bool:
        """Create a LaunchOperation and execute it.

        Thin shim: all execution logic now lives in LaunchOperation.execute().

        """
        return LaunchOperation(
            app_name=app_name,
            command=command,
            workspace_path=workspace_path,
            env_manager=self.env_manager,
            process_executor=self.process_executor,
            settings_manager=self._settings_manager,
            nuke_env=self.nuke_env,
            current_shot=self.current_shot,
            emit_error=self._emit_error,
            command_prefix=command_prefix,
            log_suffix=log_suffix,
            error_context=error_context,
        ).execute()

    def cancel_pending_search(self) -> None:
        """Cancel any pending async file search."""
        if self._file_search_coordinator.is_search_pending:
            self._set_phase(LaunchPhase.IDLE)
            self._file_search_coordinator.cancel_pending_search()

    @property
    def is_search_pending(self) -> bool:
        """Check if an async file search is in progress."""
        return self._file_search_coordinator.is_search_pending

    def _build_app_command(
        self,
        app_name: str,
        context: LaunchContext,
    ) -> tuple[str | None, bool]:
        """Build the app-specific command string for launch_app.

        Dispatches to the per-DCC AppHandler registered in self._app_handlers.
        Each handler encapsulates the DCC-specific logic (Nuke workspace scripts,
        3DE/Maya async file search, RV sequence path).

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
        assert self.current_shot is not None, (
            "_build_app_command called without a current shot"
        )
        base_cmd = Config.APPS[app_name]
        handler = self._app_handlers.get(app_name, self._default_handler)
        return handler.build_launch_command(base_cmd, context, self.current_shot)

    def launch(self, request: LaunchRequest) -> bool:
        """Unified launch entry point.

        Dispatches to the appropriate internal path based on which fields
        are set on *request*.

        Args:
            request: Launch request with all context.

        Returns:
            True if launch was successful or async search started, False otherwise.
        """

        self._set_phase(LaunchPhase.VERIFYING_APP)

        # --- Common validation ---
        if not self._validate_app_name(request.app_name):
            return False

        if request.app_name in ("nuke", "3de") and not self._validate_scripts_dir(
            request.app_name
        ):
            return False

        # --- Dispatch based on request type ---
        if request.scene is not None:
            return self._launch_with_scene(request)
        if request.file_path is not None:
            return self._launch_with_explicit_file(request)
        return self._launch_standard(request)

    def _launch_standard(self, request: LaunchRequest) -> bool:
        """Standard app launch using current shot context."""
        context = request.context if request.context is not None else LaunchContext()

        if not self.current_shot:
            self._emit_error("No shot selected")
            return False

        if not self._validate_workspace_before_launch(
            self.current_shot.workspace_path, request.app_name
        ):
            return False

        command, is_async = self._build_app_command(request.app_name, context)
        if command is None:
            return is_async
        return self._finish_launch(request.app_name, command)

    def _launch_with_scene(self, request: LaunchRequest) -> bool:
        """Launch opening a specific 3DE scene file."""
        assert request.scene is not None
        scene = request.scene
        app_name = request.app_name
        command = Config.APPS[app_name]

        try:
            safe_scene_path = validate_path(str(scene.scene_path))
            command_prefix = ""
            if app_name == "3de":
                tde_scripts_export = build_threede_scripts_export(Config.SCRIPTS_DIR)
                sgtk_export = f"export SGTK_FILE_TO_OPEN={safe_scene_path} && "
                command = f"{command} -open {safe_scene_path}"
                command_prefix = f"{tde_scripts_export}{sgtk_export}"
        except ValueError as e:
            self._emit_error(f"Invalid scene path: {e!s}")
            return False

        if not self._validate_workspace_before_launch(scene.workspace_path, app_name):
            return False

        return self._finish_launch(
            app_name,
            command,
            workspace_path=scene.workspace_path,
            log_suffix=f" (Scene by: {scene.user}, Plate: {scene.plate})",
            error_context=" with scene",
            command_prefix=command_prefix,
        )

    def _launch_with_explicit_file(self, request: LaunchRequest) -> bool:
        """Launch with a specific file from the DCC file panel."""
        assert request.file_path is not None
        assert request.workspace_path is not None
        app_name = request.app_name
        file_path = request.file_path
        workspace_path = request.workspace_path

        command = Config.APPS[app_name]
        handler = self._app_handlers.get(app_name, self._default_handler)

        try:
            safe_file_path = validate_path(str(file_path))
            command = handler.build_file_command(command, safe_file_path)
            logger.debug(
                f"launch: app={app_name}, file_path={file_path}, "
                f"safe_file_path={safe_file_path}, command={command}"
            )
        except ValueError as e:
            self._emit_error(f"Invalid file path: {e!s}")
            return False

        if not self._validate_workspace_before_launch(workspace_path, app_name):
            return False

        if handler.needs_sgtk_file_to_open():
            sgtk_export = f"export SGTK_FILE_TO_OPEN={safe_file_path} && "
            logger.debug(f"Setting SGTK_FILE_TO_OPEN={safe_file_path}")
        else:
            sgtk_export = ""

        return self._finish_launch(
            app_name,
            command,
            workspace_path=workspace_path,
            log_suffix=f" (File: {file_path.name})",
            error_context=" with file",
            command_prefix=sgtk_export,
        )

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

        Delegates to :func:`launch.workspace_validator.validate_workspace`.
        """
        from launch.workspace_validator import validate_workspace

        error = validate_workspace(workspace_path, app_name)
        if error:
            self._emit_error(error)
            return False
        return True

    def _validate_scripts_dir(self, app_name: str) -> bool:
        """Validate Config.SCRIPTS_DIR exists for apps that depend on hook scripts.

        Args:
            app_name: Name of the application being launched.

        Returns:
            True if scripts dir is valid or app doesn't need it, False if launch should be blocked.

        """
        scripts_dir = Path(Config.SCRIPTS_DIR)
        if not scripts_dir.is_dir():
            self._emit_error(
                f"Scripts directory not found: {Config.SCRIPTS_DIR}. "
                f"{app_name} launch requires hook scripts."
            )
            return False

        # Warn about missing app-specific hook files (non-blocking)
        hook_files: dict[str, str] = {
            "nuke": "init.py",
            "3de": "3de_sgtk_context_callback.py",
        }
        expected_hook = hook_files.get(app_name)
        if expected_hook and not (scripts_dir / expected_hook).exists():
            logger.warning(
                "Expected hook script %s not found in %s — "
                "%s may launch without SGTK context",
                expected_hook,
                scripts_dir,
                app_name,
            )

        return True

    def _emit_error(self, error: str) -> None:
        """Log an error with timestamp."""
        logger.error(error)

    def _set_phase(self, phase: LaunchPhase) -> None:
        """Set the launch phase and log the transition."""
        self._phase = phase
        logger.debug("LaunchPhase: %s", self._phase.value)
