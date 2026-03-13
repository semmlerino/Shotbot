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
import sys
import time
import warnings
from typing import TYPE_CHECKING, Protocol

# Third-party imports
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    Qt,
    Signal,
    Slot,
)


if TYPE_CHECKING:
    # Local application imports
    from cache.scene_cache_disk import SceneDiskCache
    from command_launcher import CommandLauncher
    from controllers.filter_coordinator import FilterableItemModel
    from progress_manager import (
        _Operation as _ProgressOperation,  # pyright: ignore[reportPrivateUsage]
    )

    # Local type imports
    from right_panel import RightPanelWidget
    from threede_grid_view import ThreeDEGridView
    from threede_item_model import ThreeDEItemModel
    from threede_recovery import CrashFileInfo
    from threede_scene_model import ThreeDESceneModel

# Runtime imports (needed at runtime)
from config import Config
from controllers.filter_helpers import apply_show_filter
from logging_mixin import LoggingMixin
from notification_manager import NotificationManager
from progress_manager import ProgressManager
from shot_model import Shot
from threede_scene_model import ThreeDEScene
from threede_scene_worker import ThreeDESceneWorker


class ThreeDETarget(Protocol):
    """Protocol defining interface required by ThreeDEController.

    This protocol specifies the minimal interface that MainWindow must provide
    to the ThreeDEController for proper operation. It includes widget references,
    model access, and required methods.
    """

    # Widget references needed for 3DE operations
    threede_shot_grid: ThreeDEGridView  # skylos: ignore
    right_panel: RightPanelWidget  # skylos: ignore

    # Model references for data access
    def get_active_shots(self) -> list[Shot]: ...  # skylos: ignore
    threede_scene_model: ThreeDESceneModel  # skylos: ignore
    threede_item_model: ThreeDEItemModel  # skylos: ignore
    scene_disk_cache: SceneDiskCache  # skylos: ignore
    command_launcher: CommandLauncher  # skylos: ignore

    # Required methods
    def setWindowTitle(self, __title: str) -> None: ...
    def update_status(self, message: str) -> None: ...

    # Signals (Signal is a Qt descriptor; pyright can't resolve its methods)
    closing_started: Signal  # pyright: ignore[reportAny]  # skylos: ignore


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

    """

    def __init__(self, window: ThreeDETarget) -> None:
        """Initialize the 3DE controller.

        Args:
            window: MainWindow implementing ThreeDETarget protocol

        """
        super().__init__()
        self.window: ThreeDETarget = window

        # Thread management - mirrors MainWindow's approach
        self._threede_worker: ThreeDESceneWorker | None = None
        self._worker_mutex: QMutex = QMutex()

        # Shutdown state - set to True when closing_started signal is received
        self._closing: bool = False

        # Progress operation tracking for cleanup
        self._current_progress_operation: _ProgressOperation | None = None

        # Scan debouncing to prevent restart spam
        self._last_scan_time: float = 0.0
        self._min_scan_interval: float = 30.0  # Don't scan more than once per 30s

        # Connect UI signals to controller methods
        self._setup_signals()

    def _setup_signals(self) -> None:
        """Connect UI signals to controller slots."""
        # Connect MainWindow lifecycle signal to track shutdown state
        _ = self.window.closing_started.connect(self._on_closing)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAttributeAccessIssue]

        # Connect 3DE grid view signals for scene interaction
        grid = self.window.threede_shot_grid

        # Scene selection and interaction
        _ = grid.scene_selected.connect(self.on_scene_selected)  # pyright: ignore[reportAny]
        _ = grid.scene_double_clicked.connect(self.on_scene_double_clicked)  # pyright: ignore[reportAny]

        # Crash recovery
        if hasattr(grid, "recover_crashes_requested"):
            _ = grid.recover_crashes_requested.connect(self.on_recover_crashes_clicked)  # pyright: ignore[reportAny]

        # Show filtering (if available)
        if hasattr(grid, "show_filter_requested"):
            _ = grid.show_filter_requested.connect(self._on_show_filter_requested)  # pyright: ignore[reportAny]

        # Artist filtering (if available)
        if hasattr(grid, "artist_filter_requested"):
            _ = grid.artist_filter_requested.connect(self._on_artist_filter_requested)  # pyright: ignore[reportAny]

        # Text filtering (if available)
        if hasattr(grid, "text_filter_requested"):
            _ = grid.text_filter_requested.connect(self._on_text_filter_requested)  # pyright: ignore[reportAny]

        self.logger.debug("ThreeDEController signals connected")

    @Slot()  # pyright: ignore[reportAny]
    def _on_closing(self) -> None:
        """Handle MainWindow closing_started signal to set local shutdown flag."""
        self._closing = True

    # ============================================================================
    # Public Interface Methods
    # ============================================================================

    def refresh_threede_scenes(self) -> None:
        """Thread-safe refresh of 3DE scene list using background worker.

        This is the main entry point for 3DE scene discovery. It will:
        1. Load persistent cache immediately for instant UI update
        2. Stop any existing worker thread safely
        3. Create a new worker with current shot data
        4. Connect all signal handlers
        5. Start the background discovery process to update cache
        """
        # First check if we're closing without holding mutex
        if self._closing:
            self.logger.debug("Ignoring refresh request during shutdown")
            return

        # GUARD: If worker is already running, skip this request entirely
        # This prevents duplicate progress operations during rapid refresh calls
        with QMutexLocker(self._worker_mutex):
            if self._threede_worker and not self._threede_worker.isFinished():
                self.logger.debug("3DE worker already running, skipping duplicate refresh request")
                return

        # DEBOUNCE: Prevent scan restart spam (e.g., rapid shot refreshes)
        now = time.time()
        time_since_last_scan = now - self._last_scan_time
        if self._last_scan_time > 0 and time_since_last_scan < self._min_scan_interval:
            self.logger.info(
                f"⏱️  Scan requested too soon ({time_since_last_scan:.1f}s < {self._min_scan_interval}s), using cached data instead"
            )
            return  # Skip scan, use cached data

        # Update last scan time
        self._last_scan_time = now

        # INSTANT UI UPDATE: Load persistent cache first (no TTL check)
        cached_scenes = self._load_cached_scenes()

        # Store worker reference for cleanup outside mutex
        worker_to_stop = None

        # Use mutex only for critical section
        with QMutexLocker(self._worker_mutex):
            # Double-check closing state with mutex held
            if self._closing:
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
            self._stop_existing_worker(worker_to_stop)

        # Check once more if closing (could have changed while stopping worker)
        if self._closing:
            return

        # Now create new worker with mutex protection
        with QMutexLocker(self._worker_mutex):
            # Final check before creating new worker
            if self._closing or self._threede_worker:
                return

            # Show loading state
            self.window.threede_item_model.set_loading_state(True)
            status_msg = "Scanning for 3DE scene updates..." if cached_scenes else "Starting enhanced 3DE scene discovery..."
            self.window.update_status(status_msg)

            # Create enhanced worker with progressive scanning enabled
            # Pass user's shots so the worker knows which shows to scan
            # The worker will scan ALL shots in those shows, not just the user's shots
            self._threede_worker = ThreeDESceneWorker(
                shots=self.window.get_active_shots(),  # Used to determine which shows to scan
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
                _ = worker_to_cleanup.wait(final_timeout_ms)

        # Ensure any open progress operation is finished
        # This handles cases where worker is terminated without emitting finished/error signals
        if self._current_progress_operation is not None:
            # SAFETY: Check if our operation is still on top of the stack
            # If another operation was started after ours, don't finish the wrong one
            current_top = ProgressManager.get_current_operation()
            if current_top == self._current_progress_operation:
                self.logger.debug("Finishing orphaned progress operation during cleanup")
                ProgressManager.finish_operation(success=False, error_message="Operation cancelled during shutdown")
            # Our operation was already finished or another operation is on top
            elif current_top is None:
                self.logger.debug("3DE progress operation already finished during cleanup")
            else:
                self.logger.warning(
                    "3DE progress operation not on top of stack during cleanup - skipping finish to prevent stack corruption"
                )
            self._current_progress_operation = None

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

    @Slot()  # pyright: ignore[reportAny]
    def on_discovery_started(self) -> None:
        """Handle 3DE discovery worker started signal."""
        # Check if we're closing to avoid accessing deleted widgets
        if self._closing:
            return

        # Start progress for 3DE discovery and store reference for cleanup
        self._current_progress_operation = ProgressManager.start_operation("3DE Scenes: Scanning user directories")

    @Slot(int, int, float, str, str)  # pyright: ignore[reportAny]
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
        if self._closing:
            return

        # Update progress operation if active
        operation = ProgressManager.get_current_operation()
        if operation:
            operation.set_total(total)
            operation.update(current, description)

    @Slot(list)  # pyright: ignore[reportAny]
    def on_discovery_finished(self, scenes: list[ThreeDEScene]) -> None:
        """Handle 3DE discovery worker completion.

        Args:
            scenes: List of discovered ThreeDEScene objects

        """
        self.log_discovered_scenes(scenes)

        # Check if we're closing to avoid accessing deleted widgets
        if self._closing:
            return

        # Finish progress operation and hide loading state
        ProgressManager.finish_operation(success=True)
        self._current_progress_operation = None  # Clear reference after finishing
        if self.window.threede_item_model:
            self.window.threede_item_model.set_loading_state(False)

        # Check if we have changes and update accordingly
        has_changes = self.has_scene_changes(scenes)

        if has_changes:
            self.update_scenes_with_changes(scenes)
        else:
            self.update_scenes_no_changes()

    @Slot(str)  # pyright: ignore[reportAny]
    def on_discovery_error(self, error_message: str) -> None:
        """Handle 3DE discovery worker error.

        Args:
            error_message: Error message from worker

        """
        # Check if we're closing to avoid double-finish during shutdown
        if self._closing:
            return

        # Finish progress operation with error
        ProgressManager.finish_operation(success=False, error_message=error_message)
        self._current_progress_operation = None  # Clear reference after finishing

        # Hide loading state
        self.window.threede_item_model.set_loading_state(False)

        # Show error notification for serious issues
        NotificationManager.warning(
            "3DE Discovery Error",
            f"Failed to discover 3DE scenes: {error_message}",
            "Check that you have read permissions for the scan directories.",
        )

    @Slot()  # pyright: ignore[reportAny]
    def on_discovery_paused(self) -> None:
        """Handle worker pause signal."""
        self.window.update_status("3DE scene discovery paused")

    @Slot()  # pyright: ignore[reportAny]
    def on_discovery_resumed(self) -> None:
        """Handle worker resume signal."""
        self.window.update_status("3DE scene discovery resumed")

    @Slot(list)  # pyright: ignore[reportAny]
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

    @Slot(int, int, str)  # pyright: ignore[reportAny]
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

    @Slot(object)  # pyright: ignore[reportAny]
    def on_scene_selected(self, scene: ThreeDEScene) -> None:
        """Handle 3DE scene selection."""
        # DIAGNOSTIC: Verify signal is firing
        self.logger.info("📡 ThreeDEController.on_scene_selected() signal received")
        self.logger.info(f"   Scene: {scene.full_name} (user: {scene.user})")

        # Create a Shot object from the scene for compatibility
        shot = Shot(
            show=scene.show,
            sequence=scene.sequence,
            shot=scene.shot,
            workspace_path=scene.workspace_path,
        )

        # Update right panel with shot info
        self.window.right_panel.set_shot(shot)

        # Update window title with scene info
        self.window.setWindowTitle(
            f"{Config.APP_NAME} - {scene.full_name} ({scene.user} - {scene.plate})",
        )

        # Update status
        self.window.update_status(
            f"Selected: {scene.full_name} - {scene.user} ({scene.plate})",
        )

    @Slot(object)  # pyright: ignore[reportAny]
    def on_scene_double_clicked(self, scene: ThreeDEScene) -> None:
        """Handle 3DE scene double click - launch 3de with the scene."""
        self.logger.info(f"Scene double-clicked: {scene.full_name} - launching 3DE")
        _ = self.window.command_launcher.launch_app_with_scene("3de", scene)

    @Slot()  # pyright: ignore[reportAny]
    def on_recover_crashes_clicked(self) -> None:
        """Handle recovery crashes button click.

        Scans for crash files in the current workspace and presents
        a recovery dialog if any are found.
        """
        # Get current scene from threede grid
        scene = self.window.threede_shot_grid.selected_scene
        if not scene:
            NotificationManager.warning(
                "No Scene Selected",
                "Please select a 3DE scene before attempting crash recovery."
            )
            return

        workspace_path = scene.workspace_path
        self.logger.info(f"Scanning for crash files in: {workspace_path}")

        # Import recovery components - lazy load as this feature may not be used
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
            self.logger.exception("Error scanning for crash files")
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
                _ = result_dialog.exec()

                # Refresh 3DE scenes to show recovered file
                self.logger.info("Refreshing 3DE scenes after recovery")
                self.refresh_threede_scenes()

                NotificationManager.success(f"Recovered: {recovered_path.name}")

            except Exception as e:
                self.logger.exception("Recovery failed")

                # Show error result
                result_dialog = ThreeDERecoveryResultDialog(
                    success=False,
                    error_message=str(e),
                    parent=self.window.threede_shot_grid,
                )
                _ = result_dialog.exec()

                NotificationManager.error(
                    "Recovery Failed",
                    f"Failed to recover crash file: {e}"
                )

        _ = dialog.recovery_requested.connect(on_recovery_requested)
        _ = dialog.exec()

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_show_filter_requested(self, show: str) -> None:
        """Handle show filter requests from 3DE grid."""
        # Apply filter to 3DE scenes
        self._apply_show_filter(
            self.window.threede_item_model,
            self.window.threede_scene_model,
            show,
            "3DE Scenes",
        )

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_artist_filter_requested(self, artist: str) -> None:
        """Handle artist filter requests from 3DE grid."""
        filter_artist = artist.strip() if artist else None
        self.window.threede_scene_model.set_artist_filter(filter_artist)

        filtered_scenes = self._refresh_filtered_scenes()
        self.logger.debug(
            "3DE artist filter applied: %r - %s scenes",
            filter_artist,
            len(filtered_scenes),
        )

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_text_filter_requested(self, text: str) -> None:
        """Handle text filter requests from 3DE grid."""
        # Set text filter on model
        filter_text = text.strip() if text else None
        self.window.threede_scene_model.set_text_filter(filter_text)

        filtered_scenes = self._refresh_filtered_scenes()

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
        self.window.threede_scene_model.set_scenes(
            self.window.threede_scene_model.deduplicate_scenes_by_shot(scenes)
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
        except Exception:  # noqa: BLE001
            self.logger.warning("Failed to cache 3DE scenes", exc_info=True)

    def update_ui(self) -> None:
        """Update the 3DE UI elements with current scenes."""
        scene_model = self.window.threede_scene_model
        active_show = scene_model.get_show_filter()
        available_shows = scene_model.get_unique_shows()
        if active_show is not None and active_show not in available_shows:
            scene_model.set_show_filter(None)

        active_artist = scene_model.get_artist_filter()
        available_artists = scene_model.get_unique_artists()
        if active_artist is not None and active_artist not in available_artists:
            scene_model.set_artist_filter(None)

        self.window.threede_shot_grid.populate_show_filter(available_shows)
        self.window.threede_shot_grid.populate_artist_filter(available_artists)
        visible_scenes = self._refresh_filtered_scenes()
        self.logger.info(
            "✅ UI model updated with %s visible scenes from %s total",
            len(visible_scenes),
            len(scene_model.scenes),
        )

    def _refresh_filtered_scenes(self) -> list[ThreeDEScene]:
        """Rebuild the item model from the currently active scene filters."""
        filtered_scenes = self.window.threede_scene_model.get_filtered_scenes()
        self.window.threede_item_model.set_scenes(filtered_scenes)
        return filtered_scenes

    def _apply_show_filter(
        self, item_model: FilterableItemModel, model: object, show: str, tab_name: str
    ) -> None:
        """Generic show filter handler for all tabs.

        Args:
            item_model: The item model to apply the filter to
            model: The data model to pass to the item model
            show: Show name to filter by, or empty string for all shows
            tab_name: Human-readable tab name for logging

        """
        apply_show_filter(item_model, model, show)
        self.logger.info(f"Applied {tab_name} show filter: {show or 'All Shows'}")

    # ============================================================================
    # Private Helper Methods
    # ============================================================================

    def _load_cached_scenes(self) -> list[ThreeDEScene]:
        """Load 3DE scenes from persistent cache and populate the UI immediately.

        Fetches cached scene data, converts each entry to a ThreeDEScene object
        (skipping any that fail to deserialize), and if any valid scenes are
        found, updates the scene model and refreshes the UI without waiting for
        the background worker.

        Returns:
            List of successfully deserialized ThreeDEScene objects from the
            cache.  An empty list indicates either no cache or no valid entries.

        """
        cached_data = self.window.scene_disk_cache.get_persistent_threede_scenes()
        if not cached_data:
            return []

        scenes: list[ThreeDEScene] = []
        for scene_data in cached_data:
            try:
                scenes.append(ThreeDEScene.from_dict(scene_data))  # pyright: ignore[reportArgumentType]
            except (KeyError, TypeError, ValueError) as e:
                self.logger.debug(f"Skipping invalid cached 3DE scene: {e}")
                continue

        if scenes:
            self.window.threede_scene_model.set_scenes(scenes)
            self.update_ui()
            self.logger.info(
                f"🚀 Loaded {len(scenes)} cached 3DE scenes immediately (scanning for updates in background)"
            )

        return scenes

    def _stop_existing_worker(self, worker_to_stop: ThreeDESceneWorker) -> None:
        """Stop a running worker thread and release its resources.

        Requests a graceful stop, waits up to the configured timeout, falls
        back to safe termination if the worker does not respond in time, then
        schedules the worker for deletion (unless it is a zombie thread) and
        clears the internal worker reference under mutex protection.

        Args:
            worker_to_stop: The worker thread to stop.  Must not be ``None``.

        """
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

    def _setup_worker_signals(self, worker: ThreeDESceneWorker) -> None:
        """Connect all worker signals to controller slots.

        Args:
            worker: The worker thread to connect signals from

        """
        # Connect enhanced worker signals using safe_connect method for proper cleanup
        _ = worker.safe_connect(
            worker.worker_discovery_started,
            self.on_discovery_started,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.batch_ready,
            self.on_batch_ready,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.progress,
            self.on_discovery_progress,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.scan_progress,
            self.on_scan_progress,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.discovery_finished,
            self.on_discovery_finished,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.safe_connect(
            worker.error,
            self.on_discovery_error,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        self.logger.debug("Connected all worker signals to controller")

    def _disconnect_worker_signals(self, worker: ThreeDESceneWorker) -> None:
        """Safely disconnect worker signals.

        Args:
            worker: The worker thread to disconnect signals from

        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            signals_to_disconnect = [
                worker.worker_discovery_started,
                worker.batch_ready,
                worker.progress,
                worker.scan_progress,
                worker.discovery_finished,
                worker.error,
            ]

            for signal in signals_to_disconnect:
                try:
                    if hasattr(signal, "disconnect"):
                        _ = signal.disconnect()
                except (RuntimeError, TypeError):
                    # Signal may already be disconnected or deleted
                    pass

        self.logger.debug("Disconnected worker signals")

    # ============================================================================
    # Properties and State Access
    # ============================================================================

    @property
    def current_scene(self) -> ThreeDEScene | None:
        """Get the currently selected 3DE scene."""
        return self.window.threede_shot_grid.selected_scene

    @property
    def has_active_worker(self) -> bool:
        """Check if there's an active worker thread."""
        with QMutexLocker(self._worker_mutex):
            return (
                self._threede_worker is not None
                and not self._threede_worker.isFinished()
            )
