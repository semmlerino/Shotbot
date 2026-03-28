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

from typing import TYPE_CHECKING, ClassVar, cast, final

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot
from typing_extensions import override

from config import Config
from logging_mixin import get_module_logger


if TYPE_CHECKING:
    from dcc.scene_file import FileType, SceneFile  # used in cast()
    from launch.command_launcher import CommandLauncher
    from protocols import ShotSelectionTarget
    from type_definitions import Shot


# Module-level logger for non-class code
logger = get_module_logger(__name__)


from workers.runnable_tracker import TrackedQRunnable


@final
class ShotDiscoverySignals(QObject):
    """Signals for ShotDiscoveryWorker."""

    finished: ClassVar[Signal] = Signal(object)  # dict with plates and files
    error: ClassVar[Signal] = Signal(str)


@final
class ShotDiscoveryWorker(TrackedQRunnable):
    """Background worker for discovering shot files and plates.

    This worker runs filesystem operations off the main thread to prevent
    UI freezes during shot selection.
    """

    shot: Shot
    signals: ShotDiscoverySignals
    _cancelled: bool

    def __init__(self, shot: Shot) -> None:
        """Initialize discovery worker.

        Args:
            shot: Shot to discover files for

        """
        super().__init__(auto_delete=True)
        self.shot = shot
        self.signals = ShotDiscoverySignals()
        self._cancelled = False

    def cancel(self) -> None:
        """Cancel the discovery operation."""
        self._cancelled = True

    @override
    def _do_work(self) -> None:
        """Run discovery in background thread."""
        if self._cancelled:
            return

        try:
            # Import here to avoid circular imports
            from discovery import get_available_plates
            from shots.shot_file_finder import ShotFileFinder

            # Discover plates
            plates: list[str] = []
            if not self._cancelled:
                plates = get_available_plates(self.shot.workspace_path)

            # Discover files (result is dict[FileType, list[SceneFile]])
            files_by_type = {}
            if not self._cancelled:
                file_finder = ShotFileFinder()
                files_by_type = file_finder.find_all_files(self.shot)

            # Emit results
            if not self._cancelled:
                self.signals.finished.emit(
                    {
                        "shot": self.shot,
                        "plates": plates,
                        "files": files_by_type,
                    }
                )
        except Exception as e:
            if not self._cancelled:
                logger.exception("Shot discovery failed")
                self.signals.error.emit(str(e))


class ShotSelectionController(QObject):
    """Controller for shot selection, discovery, and crash recovery.

    This controller encapsulates all shot selection functionality that was
    previously part of MainWindow, providing clean separation of concerns
    and improved testability. It manages:

    - Shot selection/deselection handling
    - Background file discovery with cancellation support
    - Crash recovery workflow for 3DE crash files
    - Right panel and window state updates
    """

    settings_save_requested: ClassVar[Signal] = Signal()

    def __init__(
        self,
        window: ShotSelectionTarget,
        *,
        command_launcher: CommandLauncher,
        parent: QObject | None = None,
    ) -> None:
        """Initialize shot selection controller.

        Args:
            window: MainWindow instance implementing ShotSelectionTarget protocol
            command_launcher: Launcher for DCC commands
            parent: Optional Qt parent object

        """
        super().__init__(parent)
        self.window: ShotSelectionTarget = window
        self._command_launcher: CommandLauncher = command_launcher
        self._discovery_worker: ShotDiscoveryWorker | None = None
        self._setup_signals()
        logger.debug("ShotSelectionController initialized")

    def _setup_signals(self) -> None:
        """Connect UI signals to controller slots."""
        # My Shots grid signals
        _ = self.window.shot_grid.shot_selected.connect(self.on_shot_selected)  # pyright: ignore[reportAny]
        _ = self.window.shot_grid.shot_double_clicked.connect(
            self.on_shot_double_clicked
        )  # pyright: ignore[reportAny]
        _ = self.window.shot_grid.recover_crashes_requested.connect(
            self.on_recover_crashes_requested  # pyright: ignore[reportAny]
        )

        # Previous Shots grid signals (reuses same handlers)
        _ = self.window.previous_shots_grid.shot_selected.connect(self.on_shot_selected)  # pyright: ignore[reportAny]
        _ = self.window.previous_shots_grid.shot_double_clicked.connect(
            self.on_shot_double_clicked  # pyright: ignore[reportAny]
        )

        logger.debug("ShotSelectionController signals connected")

    def cleanup(self) -> None:
        """Clean up controller resources.

        Cancels any pending discovery work. Should be called during
        application shutdown.
        """
        if self._discovery_worker is not None:
            self._discovery_worker.cancel()
            self._discovery_worker = None
        logger.debug("ShotSelectionController cleaned up")

    @Slot(object)  # pyright: ignore[reportAny]
    def on_shot_selected(self, shot: Shot | None) -> None:
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
            self._command_launcher.set_current_shot(None)
            self.window.right_panel.set_shot(None, discover_files=False)

            # Clear plate selectors
            self.window.right_panel.set_available_plates([])

            # Reset window title
            self.window.setWindowTitle(Config.APP_NAME)

            # Update status
            self.window.update_status("No shot selected")

            # Clear saved selection
            self.window.last_selected_shot_name = None
            self.settings_save_requested.emit()
        else:
            # Handle selection
            self._command_launcher.set_current_shot(shot)

            # Update right panel immediately (without file discovery - that's async)
            self.window.right_panel.set_shot(shot, discover_files=False)

            # Update window title
            self.window.setWindowTitle(
                f"{Config.APP_NAME} - {shot.full_name} ({shot.show})"
            )

            # Update status
            self.window.update_status(f"Selected: {shot.full_name} ({shot.show})")

            # Save selection
            self.window.last_selected_shot_name = shot.full_name
            self.settings_save_requested.emit()

            # Start async discovery for plates and files (non-blocking)
            self._discovery_worker = ShotDiscoveryWorker(shot)
            _ = self._discovery_worker.signals.finished.connect(
                self._on_discovery_complete
            )  # pyright: ignore[reportAny]
            _ = self._discovery_worker.signals.error.connect(self._on_discovery_error)  # pyright: ignore[reportAny]
            QThreadPool.globalInstance().start(self._discovery_worker)

    def on_shot_double_clicked(self, _shot: Shot) -> None:
        """Handle shot double click - launch default app."""
        from launch.launch_request import LaunchRequest

        _ = self._command_launcher.launch(LaunchRequest(app_name=Config.DEFAULT_APP))

    @Slot(object)  # pyright: ignore[reportAny]
    def _on_discovery_complete(self, result: dict[str, object]) -> None:
        """Handle completed shot discovery.

        Args:
            result: Dictionary with 'shot', 'plates', and 'files' keys

        """
        # Import Shot type for runtime checks
        from type_definitions import Shot

        shot = result.get("shot")
        plates = result.get("plates", [])
        files = result.get("files", {})

        # Verify this result is for the currently selected shot (may have changed)
        current_shot = self._command_launcher.current_shot
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
            self.window.right_panel.set_files(
                cast("dict[FileType, list[SceneFile]]", files)
            )

        # Discover RV sequences (Maya playblasts, Nuke renders)
        self.window.right_panel.discover_rv_sequences(shot)

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_discovery_error(self, error_message: str) -> None:
        """Handle discovery error.

        Args:
            error_message: Error description

        """
        logger.warning(f"Shot discovery failed: {error_message}")

    @Slot(int)  # pyright: ignore[reportAny]
    def on_tab_activated(self, tab_index: int) -> None:
        """Handle tab activation — update right panel when shot tabs are selected."""
        from ui.tab_constants import TAB_MY_SHOTS, TAB_PREVIOUS

        if tab_index == TAB_MY_SHOTS:
            selected_shot = self.window.shot_grid.selected_shot
            self.on_shot_selected(selected_shot)  # pyright: ignore[reportAny]
        elif tab_index == TAB_PREVIOUS:
            selected_shot = self.window.previous_shots_grid.selected_shot
            self.on_shot_selected(selected_shot)  # pyright: ignore[reportAny]

    @Slot()  # pyright: ignore[reportAny]
    def on_recover_crashes_requested(self) -> None:
        """Handle recovery crashes request from My Shots grid view.

        Scans for crash files in the current shot's workspace and presents
        a recovery dialog if any are found.
        """
        # Get current shot or scene
        # Check both since either can provide workspace context
        current_shot = self._command_launcher.current_shot
        current_scene = self.window.threede_shot_grid.selected_scene

        if not current_shot and not current_scene:
            # Local application imports
            from managers.notification_manager import NotificationManager

            NotificationManager.warning(
                "No Shot Selected",
                "Please select a shot before attempting crash recovery.",
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
        logger.info(f"Scanning for crash files in shot workspace: {workspace_path}")

        from controllers.crash_recovery import execute_crash_recovery

        execute_crash_recovery(
            workspace_path=workspace_path,
            display_name=full_name,
            parent_widget=self.window.shot_grid,
        )
