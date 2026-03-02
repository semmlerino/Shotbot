"""Shot selection controller for MainWindow refactoring.

Manages shot selection lifecycle including:
- Selection/deselection handling across My Shots and Previous Shots tabs
- Async file discovery (plates, scene files) via background worker
- Crash recovery workflow for selected shots
- Right panel updates and window title management

This controller extracts shot selection functionality from MainWindow into
a focused, testable component following the Protocol-based dependency
injection pattern established by SettingsController and ThreeDEController.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast, final

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from config import Config
from logging_mixin import LoggingMixin, get_module_logger
from typing_compat import override


if TYPE_CHECKING:
    from command_launcher import CommandLauncher
    from controllers.settings_controller import SettingsController
    from previous_shots_view import PreviousShotsView
    from right_panel import RightPanelWidget
    from scene_file import FileType, SceneFile
    from shot_grid_view import ShotGridView
    from threede_grid_view import ThreeDEGridView


# Module-level logger for non-class code
logger = get_module_logger(__name__)


class ShotSelectionTarget(Protocol):
    """Protocol defining interface required by ShotSelectionController.

    This protocol specifies the minimal interface that MainWindow must provide
    to the ShotSelectionController for proper operation.
    """

    # Widget references needed for shot selection
    right_panel: RightPanelWidget
    shot_grid: ShotGridView
    previous_shots_grid: PreviousShotsView
    threede_shot_grid: ThreeDEGridView

    # Controller and launcher references
    command_launcher: CommandLauncher
    settings_controller: SettingsController

    # State tracking
    last_selected_shot_name: str | None

    # Required methods
    def setWindowTitle(self, title: str) -> None: ...
    def update_status(self, message: str) -> None: ...

    # Closing state for guard checks
    @property
    def closing(self) -> bool: ...


@final
class ShotDiscoverySignals(QObject):
    """Signals for ShotDiscoveryWorker."""

    finished: Signal = Signal(object)  # dict with plates and files
    error: Signal = Signal(str)


@final
class ShotDiscoveryWorker(QRunnable):
    """Background worker for discovering shot files and plates.

    This worker runs filesystem operations off the main thread to prevent
    UI freezes during shot selection.
    """

    shot: Any  # Shot type at runtime
    signals: ShotDiscoverySignals
    _cancelled: bool

    def __init__(self, shot: Any) -> None:
        """Initialize discovery worker.

        Args:
            shot: Shot to discover files for

        """
        super().__init__()
        self.shot = shot
        self.signals = ShotDiscoverySignals()
        self._cancelled = False

    def cancel(self) -> None:
        """Cancel the discovery operation."""
        self._cancelled = True

    @override
    def run(self) -> None:
        """Run discovery in background thread."""
        if self._cancelled:
            return

        try:
            # Import here to avoid circular imports
            from plate_discovery import PlateDiscovery
            from shot_file_finder import ShotFileFinder

            # Discover plates
            plates: list[str] = []
            if not self._cancelled:
                plates = PlateDiscovery.get_available_plates(self.shot.workspace_path)

            # Discover files (result is dict[FileType, list[SceneFile]])
            files_by_type = {}
            if not self._cancelled:
                file_finder = ShotFileFinder()
                files_by_type = file_finder.find_all_files(self.shot)

            # Emit results
            if not self._cancelled:
                self.signals.finished.emit({
                    "shot": self.shot,
                    "plates": plates,
                    "files": files_by_type,
                })
        except Exception as e:
            if not self._cancelled:
                logger.exception("Shot discovery failed")
                self.signals.error.emit(str(e))


class ShotSelectionController(LoggingMixin):
    """Controller for shot selection, discovery, and crash recovery.

    This controller encapsulates all shot selection functionality that was
    previously part of MainWindow, providing clean separation of concerns
    and improved testability. It manages:

    - Shot selection/deselection handling
    - Background file discovery with cancellation support
    - Crash recovery workflow for 3DE crash files
    - Right panel and window state updates
    """

    def __init__(self, window: ShotSelectionTarget) -> None:
        """Initialize shot selection controller.

        Args:
            window: MainWindow instance implementing ShotSelectionTarget protocol

        """
        super().__init__()
        self.window: ShotSelectionTarget = window
        self._discovery_worker: ShotDiscoveryWorker | None = None
        self._setup_signals()
        self.logger.debug("ShotSelectionController initialized")

    def _setup_signals(self) -> None:
        """Connect UI signals to controller slots."""
        # My Shots grid signals
        _ = self.window.shot_grid.shot_selected.connect(self.on_shot_selected)
        _ = self.window.shot_grid.shot_double_clicked.connect(self.on_shot_double_clicked)
        _ = self.window.shot_grid.recover_crashes_requested.connect(
            self.on_recover_crashes_requested
        )

        # Previous Shots grid signals (reuses same handlers)
        _ = self.window.previous_shots_grid.shot_selected.connect(self.on_shot_selected)
        _ = self.window.previous_shots_grid.shot_double_clicked.connect(
            self.on_shot_double_clicked
        )

        self.logger.debug("ShotSelectionController signals connected")

    def cleanup(self) -> None:
        """Clean up controller resources.

        Cancels any pending discovery work. Should be called during
        application shutdown.
        """
        if self._discovery_worker is not None:
            self._discovery_worker.cancel()
            self._discovery_worker = None
        self.logger.debug("ShotSelectionController cleaned up")

    @Slot(object)
    def on_shot_selected(self, shot: Any) -> None:
        """Handle shot selection or deselection.

        Args:
            shot: Shot object or None to clear selection

        """
        # Cancel any pending discovery
        if self._discovery_worker is not None:
            self._discovery_worker.cancel()
            self._discovery_worker = None

        if shot is None:
            # Handle deselection
            self.window.command_launcher.set_current_shot(None)
            self.window.right_panel.set_shot(None, discover_files=False)

            # Clear plate selectors
            self.window.right_panel.set_available_plates([])

            # Reset window title
            self.window.setWindowTitle(Config.APP_NAME)

            # Update status
            self.window.update_status("No shot selected")

            # Clear saved selection
            self.window.last_selected_shot_name = None
            self.window.settings_controller.save_settings()
        else:
            # Handle selection
            self.window.command_launcher.set_current_shot(shot)

            # Update right panel immediately (without file discovery - that's async)
            self.window.right_panel.set_shot(shot, discover_files=False)

            # Update window title
            self.window.setWindowTitle(f"{Config.APP_NAME} - {shot.full_name} ({shot.show})")

            # Update status
            self.window.update_status(f"Selected: {shot.full_name} ({shot.show})")

            # Save selection
            self.window.last_selected_shot_name = shot.full_name
            self.window.settings_controller.save_settings()

            # Start async discovery for plates and files (non-blocking)
            self._discovery_worker = ShotDiscoveryWorker(shot)
            _ = self._discovery_worker.signals.finished.connect(self._on_discovery_complete)
            _ = self._discovery_worker.signals.error.connect(self._on_discovery_error)
            QThreadPool.globalInstance().start(self._discovery_worker)

    @Slot(object)
    def on_shot_double_clicked(self, _shot: Any) -> None:
        """Handle shot double click - launch default app."""
        _ = self.window.command_launcher.launch_app(Config.DEFAULT_APP)

    @Slot(object)
    def _on_discovery_complete(self, result: dict[str, object]) -> None:
        """Handle completed shot discovery.

        Args:
            result: Dictionary with 'shot', 'plates', and 'files' keys

        """
        # Import Shot type for runtime checks
        from shot_model import Shot

        shot = result.get("shot")
        plates = result.get("plates", [])
        files = result.get("files", {})

        # Verify this result is for the currently selected shot (may have changed)
        current_shot = self.window.command_launcher.current_shot
        if current_shot is None or not isinstance(shot, Shot):
            return
        if current_shot.full_name != shot.full_name:
            # Shot changed while discovery was running - discard result
            return

        # Update plates
        if isinstance(plates, list):
            self.window.right_panel.set_available_plates(cast("list[str]", plates))

        # Update files
        if isinstance(files, dict):
            self.window.right_panel.set_files(cast("dict[FileType, list[SceneFile]]", files))

        # Discover RV sequences (Maya playblasts, Nuke renders)
        self.window.right_panel.discover_rv_sequences(shot)

    @Slot(str)
    def _on_discovery_error(self, error_message: str) -> None:
        """Handle discovery error.

        Args:
            error_message: Error description

        """
        self.logger.warning(f"Shot discovery failed: {error_message}")

    @Slot()
    def on_recover_crashes_requested(self) -> None:
        """Handle recovery crashes request from My Shots grid view.

        Scans for crash files in the current shot's workspace and presents
        a recovery dialog if any are found.
        """
        # Get current shot or scene
        # Check both since either can provide workspace context
        current_shot = self.window.command_launcher.current_shot
        current_scene = self.window.threede_shot_grid.selected_scene

        if not current_shot and not current_scene:
            # Local application imports
            from notification_manager import NotificationManager
            NotificationManager.warning(
                "No Shot Selected",
                "Please select a shot before attempting crash recovery."
            )
            return

        # Use shot if available, otherwise derive from scene
        # At this point, at least one must be non-None due to guard above
        if current_shot:
            workspace_path = current_shot.workspace_path
            full_name = current_shot.full_name
        else:
            # current_scene must be non-None here
            assert current_scene is not None  # Type narrowing
            workspace_path = current_scene.workspace_path
            full_name = current_scene.full_name
        self.logger.info(f"Scanning for crash files in shot workspace: {workspace_path}")

        # Import recovery components
        from threede_recovery import CrashFileInfo, ThreeDERecoveryManager
        from threede_recovery_dialog import (
            ThreeDERecoveryDialog,
            ThreeDERecoveryResultDialog,
        )

        # Create recovery manager
        recovery_manager = ThreeDERecoveryManager()

        # Find crash files in workspace
        try:
            crash_files = recovery_manager.find_crash_files(workspace_path, recursive=True)
        except Exception as e:
            self.logger.exception("Error scanning for crash files")
            # Local application imports
            from notification_manager import NotificationManager
            NotificationManager.error(
                "Scan Error",
                f"Failed to scan for crash files: {e}"
            )
            return

        if not crash_files:
            # Local application imports
            from notification_manager import NotificationManager
            message = f"No 3DE crash files found in workspace for {full_name}."
            NotificationManager.info(message)
            return

        # Show recovery dialog
        self.logger.info(f"Found {len(crash_files)} crash file(s), showing recovery dialog")
        dialog = ThreeDERecoveryDialog(crash_files, parent=self.window.shot_grid)

        # Connect recovery signal
        def on_recovery_requested(crash_info: CrashFileInfo) -> None:  # type: ignore[name-defined]
            self.logger.info(f"Recovery requested for: {crash_info.crash_path.name}")
            try:
                # Perform recovery and archiving
                recovered_path, archived_path = recovery_manager.recover_and_archive(crash_info)

                # Show success result
                result_dialog = ThreeDERecoveryResultDialog(
                    success=True,
                    recovered_path=recovered_path,
                    archived_path=archived_path,
                    parent=self.window.shot_grid,
                )
                _ = result_dialog.exec()

                # Local application imports
                from notification_manager import NotificationManager, NotificationType
                NotificationManager.toast(
                    f"Recovered: {recovered_path.name}",
                    NotificationType.SUCCESS
                )

            except Exception as e:
                self.logger.exception("Failed to recover crash file")
                # Show error result
                result_dialog = ThreeDERecoveryResultDialog(
                    success=False,
                    error_message=str(e),
                    parent=self.window.shot_grid,
                )
                _ = result_dialog.exec()

        _ = dialog.recovery_requested.connect(on_recovery_requested)
        _ = dialog.exec()
