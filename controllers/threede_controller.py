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
import time
from typing import TYPE_CHECKING

# Third-party imports
from PySide6.QtCore import (
    Slot,
)


if TYPE_CHECKING:
    # Local application imports
    from managers.progress_manager import ProgressOperation as _ProgressOperation
    from protocols import ThreeDETarget

# Runtime imports (needed at runtime)
from config import Config
from controllers.threede_worker_manager import ThreeDEWorkerManager
from logging_mixin import LoggingMixin
from managers.notification_manager import NotificationManager
from managers.progress_manager import ProgressManager
from timeout_config import TimeoutConfig
from type_definitions import Shot, ThreeDEScene


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
        _worker_manager: Manages the background worker lifecycle

    """

    def __init__(self, window: ThreeDETarget) -> None:
        """Initialize the 3DE controller.

        Args:
            window: MainWindow implementing ThreeDETarget protocol

        """
        super().__init__()
        self.window: ThreeDETarget = window

        # Worker lifecycle management — owns the worker instance and mutex
        self._worker_manager: ThreeDEWorkerManager = ThreeDEWorkerManager(
            on_discovery_started=self.on_discovery_started,  # pyright: ignore[reportAny]
            on_discovery_progress=self.on_discovery_progress,  # pyright: ignore[reportAny]
            on_discovery_finished=self.on_discovery_finished,  # pyright: ignore[reportAny]
            on_discovery_error=self.on_discovery_error,  # pyright: ignore[reportAny]
            on_scan_progress=self.on_scan_progress,  # pyright: ignore[reportAny]
        )

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
        _ = self.window.closing_started.connect(self._on_closing)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAttributeAccessIssue, reportAny]

        # Connect 3DE grid view signals for scene interaction
        grid = self.window.threede_shot_grid

        # Scene selection and interaction
        _ = grid.scene_selected.connect(self.on_scene_selected)  # pyright: ignore[reportAny]
        _ = grid.scene_double_clicked.connect(self.on_scene_double_clicked)  # pyright: ignore[reportAny]

        # Crash recovery
        _ = grid.recover_crashes_requested.connect(self.on_recover_crashes_clicked)  # pyright: ignore[reportAny]

        # Artist filtering
        _ = grid.artist_filter_requested.connect(self._on_artist_filter_requested)  # pyright: ignore[reportAny]

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
        if self._worker_manager.has_active_worker:
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

        # Stop any still-running worker before starting a new one
        if self._worker_manager.has_active_worker:
            self.logger.debug(
                "3DE worker still running, will stop before starting new one",
            )
            self._worker_manager.stop_worker()

        # Check once more if closing (could have changed while stopping worker)
        if self._closing:
            return

        # Final check before creating new worker
        if self._closing or self._worker_manager.has_active_worker:
            return

        # Show loading state
        self.window.threede_item_model.set_loading_state(True)
        status_msg = "Scanning for 3DE scene updates..." if cached_scenes else "Starting enhanced 3DE scene discovery..."
        self.window.update_status(status_msg)

        # Delegate worker creation, signal wiring, and start to the manager
        _ = self._worker_manager.start_worker(shots=self.window.get_active_shots())

    def cleanup_worker(self) -> None:
        """Clean up the 3DE scene discovery worker.

        Called during application shutdown to ensure proper cleanup
        of background threads and prevent zombie threads.
        """
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

        # Delegate worker stopping, signal disconnection, and deletion to the manager
        self._worker_manager.cleanup()

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

        # Surface discovery errors so the user knows results may be incomplete
        worker = self._worker_manager.current_worker
        if worker and worker.discovery_errors > 0:
            n = worker.discovery_errors
            NotificationManager.info(
                f"3DE scan: {n} error(s) — some scenes may not be shown",
                timeout=TimeoutConfig.NOTIFICATION_ERROR_MS,
            )

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
        _ = self.window.command_launcher.launch_app_opening_scene_file("3de", scene)

    @Slot(int)  # pyright: ignore[reportAny]
    def on_tab_activated(self, tab_index: int) -> None:
        """Handle tab activation — update right panel when 3DE tab is selected."""
        from ui.tab_constants import TAB_OTHER_3DE

        if tab_index != TAB_OTHER_3DE:
            return

        selected_scene = self.window.threede_shot_grid.selected_scene
        if selected_scene is not None:
            self.on_scene_selected(selected_scene)  # pyright: ignore[reportAny]
        else:
            self.window.command_launcher.set_current_shot(None)
            self.window.right_panel.set_shot(None)

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

        from controllers.crash_recovery import execute_crash_recovery
        execute_crash_recovery(
            workspace_path=workspace_path,
            display_name=scene.full_name,
            parent_widget=self.window.threede_shot_grid,
            post_recovery_callback=self.refresh_threede_scenes,
        )

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_artist_filter_requested(self, artist: str) -> None:
        """Handle artist filter requests from 3DE grid."""
        filter_artist = artist.strip() if artist else None
        self.window.threede_proxy.set_artist_filter(filter_artist)
        self.logger.debug(f"3DE artist filter applied: {filter_artist!r}")

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
            self.window.threede_scene_model.cache_manager.cache_threede_scenes(
                self.window.threede_scene_model.to_dict(),
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
        self.window.threede_proxy.invalidate()
        visible_count = self.window.threede_proxy.rowCount()
        total_count = len(scene_model.scenes)
        self.logger.info(
            "UI model updated with %s visible scenes from %s total",
            visible_count,
            total_count,
        )

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
                scenes.append(ThreeDEScene.from_dict(scene_data))
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
        return self._worker_manager.has_active_worker
