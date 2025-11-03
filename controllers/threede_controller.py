"""3DE scene discovery controller for MainWindow refactoring.

Manages background 3DE scene discovery with thread-safe worker management,
progressive batch updates, and cache integration.

This controller extracts all 3DE-related functionality from MainWindow into
a focused, testable component. It handles:
- Thread-safe worker management with QMutex protection
- Progressive batch updates for responsive UI
- Complex signal chains for discovery lifecycle
- Scene selection and double-click handling
- Proper cleanup on shutdown
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING, Protocol

# Third-party imports
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    Qt,
    Slot,
)


if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtWidgets import QStatusBar

    # Local application imports
    from cache_manager import CacheManager
    from command_launcher import CommandLauncher
    from controllers.launcher_controller import LauncherController
    from launcher_panel import LauncherPanel

    # Local type imports
    from shot_info_panel import ShotInfoPanel
    from shot_model import ShotModel
    from threede_grid_view import ThreeDEGridView
    from threede_item_model import ThreeDEItemModel
    from threede_recovery import CrashFileInfo
    from threede_scene_model import ThreeDEScene, ThreeDESceneModel
    from threede_scene_worker import ThreeDESceneWorker

# Runtime imports (needed at runtime)
from config import Config
from logging_mixin import LoggingMixin
from notification_manager import NotificationManager
from progress_manager import ProgressManager
from shot_model import Shot
from threede_scene_worker import ThreeDESceneWorker


class ThreeDETarget(Protocol):
    """Protocol defining interface required by ThreeDEController.

    This protocol specifies the minimal interface that MainWindow must provide
    to the ThreeDEController for proper operation. It includes widget references,
    model access, and required methods.
    """

    # Widget references needed for 3DE operations
    threede_shot_grid: ThreeDEGridView
    shot_info_panel: ShotInfoPanel
    launcher_panel: LauncherPanel
    status_bar: QStatusBar

    # Model references for data access
    shot_model: ShotModel
    threede_scene_model: ThreeDESceneModel
    threede_item_model: ThreeDEItemModel
    cache_manager: CacheManager
    command_launcher: CommandLauncher
    launcher_controller: LauncherController

    # Required methods
    def setWindowTitle(self, title: str) -> None: ...
    def update_status(self, message: str) -> None: ...
    def update_launcher_menu_availability(self, available: bool) -> None: ...
    def enable_custom_launcher_buttons(self, enabled: bool) -> None: ...
    def launch_app(self, app_name: str) -> None: ...

    # State tracking
    @property
    def closing(self) -> bool: ...


class ThreeDEController(LoggingMixin):
    """Controller for 3DE scene discovery and management.

    This controller encapsulates all 3DE-related functionality that was previously
    part of MainWindow, providing clean separation of concerns and improved
    testability. It manages:

    - Background worker threads for scene discovery
    - Thread-safe worker lifecycle management
    - Progressive batch updates for responsive UI
    - Scene selection and launching
    - Cache integration for discovered scenes

    Attributes:
        window: The target window that implements ThreeDETarget protocol
        logger: Logger instance for this controller
        _threede_worker: Current background worker thread (if any)
        _worker_mutex: Mutex for thread-safe worker access

    Note:
        Current scene context is managed by window.launcher_controller (single source of truth)
    """

    def __init__(self, window: ThreeDETarget) -> None:
        """Initialize the 3DE controller.

        Args:
            window: MainWindow implementing ThreeDETarget protocol
        """
        super().__init__()
        self.window = window

        # Thread management - mirrors MainWindow's approach
        self._threede_worker: ThreeDESceneWorker | None = None
        self._worker_mutex = QMutex()
        # NOTE: Current scene is managed by launcher_controller (single source of truth)

        # Connect UI signals to controller methods
        self._setup_signals()

    def _setup_signals(self) -> None:
        """Connect UI signals to controller slots."""
        # Connect 3DE grid view signals for scene interaction
        grid = self.window.threede_shot_grid

        # Scene selection and interaction
        _ = grid.scene_selected.connect(self.on_scene_selected)
        _ = grid.scene_double_clicked.connect(self.on_scene_double_clicked)

        # Crash recovery
        if hasattr(grid, "recover_crashes_requested"):
            _ = grid.recover_crashes_requested.connect(self.on_recover_crashes_clicked)

        # Show filtering (if available)
        if hasattr(grid, "show_filter_requested"):
            _ = grid.show_filter_requested.connect(self._on_show_filter_requested)

        # Text filtering (if available)
        if hasattr(grid, "text_filter_requested"):
            _ = grid.text_filter_requested.connect(self._on_text_filter_requested)

        self.logger.debug("ThreeDEController signals connected")

    # ============================================================================
    # Public Interface Methods
    # ============================================================================

    def refresh_threede_scenes(self) -> None:
        """Thread-safe refresh of 3DE scene list using background worker.

        This is the main entry point for 3DE scene discovery. It will:
        1. Stop any existing worker thread safely
        2. Create a new worker with current shot data
        3. Connect all signal handlers
        4. Start the background discovery process
        """
        # First check if we're closing without holding mutex
        if self.window.closing:
            self.logger.debug("Ignoring refresh request during shutdown")
            return

        # Store worker reference for cleanup outside mutex
        worker_to_stop = None

        # Use mutex only for critical section
        with QMutexLocker(self._worker_mutex):
            # Double-check closing state with mutex held
            if self.window.closing:
                return

            # Check existing worker state
            if self._threede_worker and not self._threede_worker.isFinished():
                self.logger.debug(
                    "3DE worker still running, will stop before starting new one",
                )
                worker_to_stop = self._threede_worker
                # Don't clear the reference yet - prevents race condition

        # Stop old worker outside of mutex to avoid deadlock
        if worker_to_stop:
            worker_to_stop.stop()
            if not worker_to_stop.wait(
                Config.WORKER_STOP_TIMEOUT_MS
            ):  # Wait up to 5 seconds
                self.logger.warning(
                    "Failed to stop 3DE worker gracefully, using safe termination",
                )
                # Use safe_terminate which avoids dangerous terminate() call
                worker_to_stop.safe_terminate()

            # Only delete if not a zombie (prevents crash)
            if hasattr(worker_to_stop, "is_zombie") and worker_to_stop.is_zombie():
                self.logger.warning(
                    "3DE worker thread is a zombie and will not be deleted"
                )
            else:
                worker_to_stop.deleteLater()

            # Clear reference after worker is stopped, with mutex protection
            with QMutexLocker(self._worker_mutex):
                if self._threede_worker == worker_to_stop:
                    self._threede_worker = None

        # Check once more if closing (could have changed while stopping worker)
        if self.window.closing:
            return

        # Now create new worker with mutex protection
        with QMutexLocker(self._worker_mutex):
            # Final check before creating new worker
            if self.window.closing or self._threede_worker:
                return

            # Show loading state
            self.window.threede_item_model.set_loading_state(True)
            self.window.update_status("Starting enhanced 3DE scene discovery...")

            # Create enhanced worker with progressive scanning enabled
            # Pass user's shots so the worker knows which shows to scan
            # The worker will scan ALL shots in those shows, not just the user's shots
            self._threede_worker = ThreeDESceneWorker(
                shots=self.window.shot_model.shots,  # Used to determine which shows to scan
                enable_progressive=True,  # Enable progressive scanning for better UI responsiveness
                batch_size=None,  # Use config default
                scan_all_shots=True,  # Scan ALL shots in the shows, not just user's shots
            )

        # Connect worker signals outside of mutex (signals are thread-safe)
        self._setup_worker_signals(self._threede_worker)

        # Start the worker
        self._threede_worker.start()

    def cleanup_worker(self) -> None:
        """Clean up the 3DE scene discovery worker.

        Called during application shutdown to ensure proper cleanup
        of background threads and prevent zombie threads.
        """
        with QMutexLocker(self._worker_mutex):
            worker_to_cleanup = self._threede_worker

        if not worker_to_cleanup:
            return

        if not worker_to_cleanup.isFinished():
            self.logger.debug("Stopping 3DE worker during shutdown")
            worker_to_cleanup.stop()

            # Use shorter timeout in test environments
            # Standard library imports
            import sys

            is_test_environment = "pytest" in sys.modules
            worker_timeout_ms = (
                500 if is_test_environment else Config.WORKER_STOP_TIMEOUT_MS
            )

            if not worker_to_cleanup.wait(worker_timeout_ms):
                self.logger.warning(
                    f"3DE worker didn't stop gracefully within {worker_timeout_ms}ms, using safe termination"
                )
                worker_to_cleanup.safe_terminate()
                final_timeout_ms = 200 if is_test_environment else 1000
                worker_to_cleanup.wait(final_timeout_ms)

        # Disconnect signals after worker has stopped
        self._disconnect_worker_signals(worker_to_cleanup)

        # Clear reference and clean up
        with QMutexLocker(self._worker_mutex):
            if self._threede_worker == worker_to_cleanup:
                self._threede_worker = None

        # Only delete if not a zombie thread
        if hasattr(worker_to_cleanup, "is_zombie") and worker_to_cleanup.is_zombie():
            self.logger.warning(
                "3DE worker thread is a zombie and will not be deleted to prevent crash"
            )
        else:
            worker_to_cleanup.deleteLater()

    # ============================================================================
    # Worker Signal Handlers (Phase 3.4)
    # ============================================================================

    @Slot()
    def on_discovery_started(self) -> None:
        """Handle 3DE discovery worker started signal."""
        # Check if we're closing to avoid accessing deleted widgets
        if self.window.closing:
            return

        # Start progress for 3DE discovery
        _ = ProgressManager.start_operation("Scanning for 3DE scenes")

    @Slot(int, int, float, str, str)
    def on_discovery_progress(
        self,
        current: int,
        total: int,
        _percentage: float,
        description: str,
        _eta: str,
    ) -> None:
        """Handle enhanced 3DE discovery progress updates.

        Args:
            current: Current progress value
            total: Total progress value
            percentage: Completion percentage (0.0-100.0)
            description: Progress description
            eta: Estimated time to completion
        """
        # Check if we're closing to avoid accessing deleted widgets
        if self.window.closing:
            return

        # Update progress operation if active
        operation = ProgressManager.get_current_operation()
        if operation:
            operation.set_total(total)
            operation.update(current, description)

    @Slot(list)
    def on_discovery_finished(self, scenes: list[ThreeDEScene]) -> None:
        """Handle 3DE discovery worker completion.

        Args:
            scenes: List of discovered ThreeDEScene objects
        """
        self.log_discovered_scenes(scenes)

        # Check if we're closing to avoid accessing deleted widgets
        if self.window.closing:
            return

        # Finish progress operation and hide loading state
        ProgressManager.finish_operation(success=True)
        if self.window.threede_item_model:
            self.window.threede_item_model.set_loading_state(False)

        # Check if we have changes and update accordingly
        has_changes = self.has_scene_changes(scenes)

        if has_changes:
            self.update_scenes_with_changes(scenes)
        else:
            self.update_scenes_no_changes()

    @Slot(str)
    def on_discovery_error(self, error_message: str) -> None:
        """Handle 3DE discovery worker error.

        Args:
            error_message: Error message from worker
        """
        # Finish progress operation with error
        ProgressManager.finish_operation(success=False, error_message=error_message)

        # Hide loading state
        self.window.threede_item_model.set_loading_state(False)

        # Show error notification for serious issues
        NotificationManager.warning(
            "3DE Discovery Error",
            f"Failed to discover 3DE scenes: {error_message}",
            "Check that you have read permissions for the scan directories.",
        )

    @Slot()
    def on_discovery_paused(self) -> None:
        """Handle worker pause signal."""
        self.window.update_status("3DE scene discovery paused")

    @Slot()
    def on_discovery_resumed(self) -> None:
        """Handle worker resume signal."""
        self.window.update_status("3DE scene discovery resumed")

    @Slot(list)
    def on_batch_ready(self, scene_batch: list[ThreeDEScene]) -> None:
        """Handle batch of scenes ready from progressive scanning.

        Args:
            scene_batch: List of ThreeDEScene objects in this batch
        """
        if scene_batch:
            # Don't directly add to model - let on_discovery_finished handle deduplication
            # Just log the progress for now
            self.logger.debug(f"Processed batch of {len(scene_batch)} scenes")

            # Note: The scenes are accumulated in the worker itself
            # and will be deduplicated when discovery finishes

    @Slot(int, int, str)
    def on_scan_progress(
        self,
        current_shot: int,
        total_shots: int,
        status: str,
    ) -> None:
        """Handle fine-grained scan progress updates.

        Args:
            current_shot: Current shot being processed
            total_shots: Total number of shots
            status: Current status message
        """
        # This provides more frequent updates than the main progress signal
        # Useful for showing which specific shot/user is being scanned
        self.window.update_status(f"Scanning ({current_shot}/{total_shots}): {status}")

        # Update model progress
        if self.window.threede_item_model:
            self.window.threede_item_model.update_loading_progress(
                current_shot, total_shots
            )

    # ============================================================================
    # Scene Selection Handlers (Phase 3.5)
    # ============================================================================

    @Slot(object)
    def on_scene_selected(self, scene: ThreeDEScene) -> None:
        """Handle 3DE scene selection."""
        # DIAGNOSTIC: Verify signal is firing
        self.logger.info("📡 ThreeDEController.on_scene_selected() signal received")
        self.logger.info(f"   Scene: {scene.full_name} (user: {scene.user})")

        # Set scene context in launcher controller (automatically clears shot context)
        self.logger.info("   Calling launcher_controller.set_current_scene()...")
        self.window.launcher_controller.set_current_scene(scene)
        self.logger.info("   ✓ Done syncing with launcher_controller")

        # Create a Shot object from the scene for compatibility
        shot = Shot(
            show=scene.show,
            sequence=scene.sequence,
            shot=scene.shot,
            workspace_path=scene.workspace_path,
        )

        # Update shot info panel
        self.window.shot_info_panel.set_shot(shot)

        # Update launcher panel to enable buttons (showing scene context)
        self.window.launcher_panel.set_shot(shot)

        # Update custom launcher menu availability
        self.window.update_launcher_menu_availability(True)

        # Enable custom launcher buttons
        self.window.enable_custom_launcher_buttons(True)

        # Update window title with scene info
        self.window.setWindowTitle(
            f"{Config.APP_NAME} - {scene.full_name} ({scene.user} - {scene.plate})",
        )

        # Update status
        self.window.update_status(
            f"Selected: {scene.full_name} - {scene.user} ({scene.plate})",
        )

    @Slot(object)
    def on_scene_double_clicked(self, scene: ThreeDEScene) -> None:
        """Handle 3DE scene double click - launch 3de with the scene."""
        # Set the current scene first, then launch
        self.window.launcher_controller.set_current_scene(scene)
        self.logger.info(f"Scene double-clicked: {scene.full_name} - launching 3DE")
        self.window.launch_app("3de")

    @Slot()
    def on_recover_crashes_clicked(self) -> None:
        """Handle recovery crashes button click.

        Scans for crash files in the current workspace and presents
        a recovery dialog if any are found.
        """
        # Get current workspace path from launcher controller
        scene = self.window.launcher_controller.current_scene
        if not scene:
            NotificationManager.warning(
                "No Scene Selected",
                "Please select a 3DE scene before attempting crash recovery."
            )
            return

        workspace_path = scene.workspace_path
        self.logger.info(f"Scanning for crash files in: {workspace_path}")

        # Import recovery components
        from threede_recovery import ThreeDERecoveryManager
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
            self.logger.error(f"Error scanning for crash files: {e}")
            NotificationManager.error(
                "Scan Error",
                f"Failed to scan for crash files: {e}"
            )
            return

        if not crash_files:
            message = f"No 3DE crash files found in workspace for {scene.full_name}."
            NotificationManager.info(message)
            return

        # Show recovery dialog
        self.logger.info(f"Found {len(crash_files)} crash file(s), showing recovery dialog")
        dialog = ThreeDERecoveryDialog(crash_files, parent=self.window.threede_shot_grid)

        # Connect recovery signal
        def on_recovery_requested(crash_info: CrashFileInfo) -> None:
            self.logger.info(f"Recovery requested for: {crash_info.crash_path.name}")
            try:
                # Perform recovery and archiving
                recovered_path, archived_path = recovery_manager.recover_and_archive(crash_info)

                # Show success result
                result_dialog = ThreeDERecoveryResultDialog(
                    success=True,
                    recovered_path=recovered_path,
                    archived_path=archived_path,
                    parent=self.window.threede_shot_grid,
                )
                result_dialog.exec()

                # Refresh 3DE scenes to show recovered file
                self.logger.info("Refreshing 3DE scenes after recovery")
                self.refresh_threede_scenes()

                from notification_manager import NotificationType
                NotificationManager.toast(
                    f"Recovered: {recovered_path.name}",
                    NotificationType.SUCCESS
                )

            except Exception as e:
                self.logger.error(f"Recovery failed: {e}", exc_info=True)

                # Show error result
                result_dialog = ThreeDERecoveryResultDialog(
                    success=False,
                    error_message=str(e),
                    parent=self.window.threede_shot_grid,
                )
                result_dialog.exec()

                NotificationManager.error(
                    "Recovery Failed",
                    f"Failed to recover crash file: {e}"
                )

        _ = dialog.recovery_requested.connect(on_recovery_requested)
        dialog.exec()

    @Slot(str)
    def _on_show_filter_requested(self, show: str) -> None:
        """Handle show filter requests from 3DE grid."""
        # Apply filter to 3DE scenes
        self._apply_show_filter(
            self.window.threede_item_model,
            self.window.threede_scene_model,
            show,
            "3DE Scenes",
        )

    @Slot(str)
    def _on_text_filter_requested(self, text: str) -> None:
        """Handle text filter requests from 3DE grid."""
        # Set text filter on model
        filter_text = text.strip() if text else None
        self.window.threede_scene_model.set_text_filter(filter_text)

        # Update item model with filtered scenes
        filtered_scenes = self.window.threede_scene_model.get_filtered_scenes()
        self.window.threede_item_model.set_items(filtered_scenes)

        self.logger.debug(
            f"3DE text filter applied: '{filter_text}' - {len(filtered_scenes)} scenes"
        )

    # ============================================================================
    # Scene Management Helpers (Phase 3.5)
    # ============================================================================

    def log_discovered_scenes(self, scenes: list[ThreeDEScene]) -> None:
        """Log discovered scenes for debugging."""
        self.logger.info(
            f"🔍 3DE Discovery finished with {len(scenes)} total scenes discovered"
        )
        for i, scene in enumerate(scenes[:5]):  # Log first 5 scenes
            self.logger.info(
                f"   Scene {i + 1}: {scene.full_name} (user: {scene.user})"
            )
        if len(scenes) > 5:
            self.logger.info(f"   ... and {len(scenes) - 5} more scenes")

    def has_scene_changes(self, scenes: list[ThreeDEScene]) -> bool:
        """Check if discovered scenes differ from current model."""
        old_scene_data = {
            (scene.full_name, scene.user, scene.plate, str(scene.scene_path))
            for scene in self.window.threede_scene_model.scenes
        }
        self.logger.info(f"🗂️ Current model has {len(old_scene_data)} existing scenes")

        new_scene_data = {
            (scene.full_name, scene.user, scene.plate, str(scene.scene_path))
            for scene in scenes
        }
        self.logger.info(f"🔍 New discovery has {len(new_scene_data)} scene data items")

        has_changes = old_scene_data != new_scene_data
        self.logger.info(f"🔄 Has changes: {has_changes}")
        return has_changes

    def update_scenes_with_changes(self, scenes: list[ThreeDEScene]) -> None:
        """Update model and UI when scene changes are detected."""
        # Update the model with new scenes (deduplication happens in model)
        self.window.threede_scene_model.scenes = (
            self.window.threede_scene_model._deduplicate_scenes_by_shot(scenes)  # pyright: ignore[reportPrivateUsage]
        )
        self.logger.info(
            f"🔧 After deduplication: {len(self.window.threede_scene_model.scenes)} scenes remain"
        )

        # Sort deduplicated scenes
        self.window.threede_scene_model.scenes.sort(key=lambda s: (s.full_name, s.user))

        # Cache results
        self.cache_scenes()

        # Update UI
        self.update_ui()

        # Update status
        scene_count = len(self.window.threede_scene_model.scenes)
        if scene_count > 0:
            self.window.update_status(
                f"Found {scene_count} 3DE scenes from other users"
            )
        else:
            self.window.update_status("No 3DE scenes found from other users")

    def update_scenes_no_changes(self) -> None:
        """Update UI when no scene changes are detected."""
        # Still cache the current state to refresh TTL
        self.cache_scenes()

        self.logger.info(
            f"❌ No changes detected - existing model has {len(self.window.threede_scene_model.scenes)} scenes"
        )

        if self.window.threede_scene_model.scenes:
            # Re-apply existing scenes to UI
            self.update_ui()
            self.logger.info(
                f"🔄 Re-applied {len(self.window.threede_scene_model.scenes)} existing scenes to UI"
            )
        else:
            self.logger.info("📭 No existing scenes in model to apply")

        self.window.update_status("3DE scene discovery complete (no changes)")

    def cache_scenes(self) -> None:
        """Cache the current 3DE scenes."""
        try:
            # Type ignore: to_dict() returns list[dict[str, str | Path]] but cache expects
            # list[ThreeDESceneDict]. The cache system handles this gracefully via JSON serialization.
            self.window.threede_scene_model.cache_manager.cache_threede_scenes(
                self.window.threede_scene_model.to_dict(),  # pyright: ignore[reportArgumentType]
            )
        except Exception as e:
            self.logger.warning(f"Failed to cache 3DE scenes: {e}")

    def update_ui(self) -> None:
        """Update the 3DE UI elements with current scenes."""
        self.window.threede_item_model.set_scenes(
            self.window.threede_scene_model.scenes
        )
        # Populate show filter with available shows
        self.window.threede_shot_grid.populate_show_filter(
            self.window.threede_scene_model
        )
        self.logger.info(
            f"✅ UI model updated with {len(self.window.threede_scene_model.scenes)} scenes"
        )

    def _apply_show_filter(
        self, item_model: object, model: object, show: str, tab_name: str
    ) -> None:
        """Generic show filter handler for all tabs.

        Args:
            item_model: The item model to apply the filter to
            model: The data model to pass to the item model
            show: Show name to filter by, or empty string for all shows
            tab_name: Human-readable tab name for logging
        """
        # Convert empty string back to None for the model
        show_filter = show if show else None

        # Apply filter to item model
        # NOTE: item_model uses object type for polymorphism across different item models
        # All item models (ShotItemModel, ThreeDEItemModel, PreviousShotsItemModel)
        # implement set_show_filter with their specific model types
        item_model.set_show_filter(model, show_filter)  # pyright: ignore[reportAttributeAccessIssue]

        self.logger.info(
            f"Applied {tab_name} show filter: {show if show else 'All Shows'}"
        )

    # ============================================================================
    # Private Helper Methods
    # ============================================================================

    def _setup_worker_signals(self, worker: ThreeDESceneWorker) -> None:
        """Connect all worker signals to controller slots.

        Args:
            worker: The worker thread to connect signals from
        """
        # Connect enhanced worker signals using safe_connect method for proper cleanup
        _ = worker.safe_connect(
            worker.started,
            self.on_discovery_started,
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.batch_ready,
            self.on_batch_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.progress,
            self.on_discovery_progress,
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.scan_progress,
            self.on_scan_progress,
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.finished,
            self.on_discovery_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.error,
            self.on_discovery_error,
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.paused,
            self.on_discovery_paused,
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.resumed,
            self.on_discovery_resumed,
            Qt.ConnectionType.QueuedConnection,
        )

        self.logger.debug("Connected all worker signals to controller")

    def _disconnect_worker_signals(self, worker: ThreeDESceneWorker) -> None:
        """Safely disconnect worker signals.

        Args:
            worker: The worker thread to disconnect signals from
        """
        # Standard library imports
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            signals_to_disconnect = [
                worker.started,
                worker.batch_ready,
                worker.progress,
                worker.scan_progress,
                worker.finished,
                worker.error,
                worker.paused,
                worker.resumed,
            ]

            for signal in signals_to_disconnect:
                try:
                    if hasattr(signal, "disconnect"):
                        signal.disconnect()
                except (RuntimeError, TypeError):
                    # Signal may already be disconnected or deleted
                    pass

        self.logger.debug("Disconnected worker signals")

    # ============================================================================
    # Properties and State Access
    # ============================================================================

    @property
    def current_scene(self) -> ThreeDEScene | None:
        """Get the currently selected 3DE scene.

        NOTE: Delegates to launcher_controller (single source of truth).
        """
        return self.window.launcher_controller.current_scene

    @property
    def has_active_worker(self) -> bool:
        """Check if there's an active worker thread."""
        with QMutexLocker(self._worker_mutex):
            return (
                self._threede_worker is not None
                and not self._threede_worker.isFinished()
            )
