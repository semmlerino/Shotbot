"""3DE scene discovery controller for MainWindow refactoring.

Manages background 3DE scene discovery with thread-safe worker management,
progressive batch updates, and cache integration.

This controller extracts all 3DE-related functionality from MainWindow into
a focused, testable component. It handles:
- Thread-safe worker management with QMutex protection
- Progressive batch updates for responsive UI
- Complex signal chains for discovery lifecycle
- Scene selection and double-click handling (via ThreeDESelectionHandler)
- Cache loading and writing (via ThreeDECacheAdapter)
- Proper cleanup on shutdown
"""

from __future__ import annotations

# Standard library imports
import time
from typing import TYPE_CHECKING, final

# Third-party imports
from PySide6.QtCore import (
    Slot,
)


if TYPE_CHECKING:
    # Local application imports
    from launch.command_launcher import CommandLauncher
    from managers.progress_manager import ProgressOperation as _ProgressOperation
    from protocols import ThreeDETarget
    from type_definitions import ThreeDEScene

# Runtime imports (needed at runtime)
import logging

from controllers.threede_cache_adapter import ThreeDECacheAdapter
from controllers.threede_selection_handler import ThreeDESelectionHandler
from controllers.threede_worker_manager import ThreeDEWorkerManager
from managers.notification_manager import NotificationManager
from managers.progress_manager import ProgressManager
from timeout_config import TimeoutConfig


logger = logging.getLogger(__name__)


@final
class ThreeDEController:
    """Controller for 3DE scene discovery and management.

    Architecture: ThreeDEController implements a 5-layer pipeline with single responsibilities:

    1. Controller (ThreeDEController): Qt signal routing and UI state management. Dispatches
       worker creation/cleanup, handles scene selection, and forwards discovery results to UI.

    2. Manager (ThreeDEWorkerManager): Thread lifecycle and mutex protection. Creates/stops the
       QThread, guards the worker instance with QMutex, and integrates with cache lifecycle.

    3. Worker (ThreeDESceneWorker): QRunnable execution, cancellation, and progress reporting.
       Encapsulates multi-shot discovery as an atomic cancellable operation with granular
       progress signals for UI feedback.

    4. Coordinator (ThreeDEDiscoveryCoordinator): Multi-shot orchestration and batching logic.
       Manages per-shot discovery sequence, coordinates batch window updates, and handles
       partial failure (continues scanning even if one shot errors).

    5. Scanner (FileSystemScanner): Raw NFS filesystem traversal using subprocess ls for
       performance. Subprocess approach avoids Python pathlib overhead on high-latency mounts.

    Why Depth is Load-Bearing:
    - Manager layer provides Qt thread-safety guarantees (mutex guards worker access)
    - Scanner layer's subprocess approach is necessary for NFS performance (1000+ shots x 10
      users each = millions of stat calls without subprocess batching)
    - Worker's QRunnable infrastructure enables cancellable progress (can't interrupt Python
      for-loops, but can set atomic cancel flag and let Scanner check it between batches)

    Attributes:
        window: The target window that implements ThreeDETarget protocol
        logger: Logger instance for this controller
        _worker_manager: Manages the background worker lifecycle
        _cache_adapter: Handles cache I/O
        _selection_handler: Handles scene selection, filters, and tab activation

    """

    def __init__(
        self,
        window: ThreeDETarget,
        *,
        command_launcher: CommandLauncher,
    ) -> None:
        """Initialize the 3DE controller.

        Args:
            window: MainWindow implementing ThreeDETarget protocol
            command_launcher: Launcher for DCC commands

        """
        super().__init__()
        self.window: ThreeDETarget = window
        self._command_launcher: CommandLauncher = command_launcher

        # Worker lifecycle management — owns the worker instance and mutex
        self._worker_manager: ThreeDEWorkerManager = ThreeDEWorkerManager(
            on_discovery_started=self.on_discovery_started,  # pyright: ignore[reportAny]
            on_discovery_progress=self.on_discovery_progress,  # pyright: ignore[reportAny]
            on_discovery_finished=self.on_discovery_finished,  # pyright: ignore[reportAny]
            on_discovery_error=self.on_discovery_error,  # pyright: ignore[reportAny]
            on_scan_progress=self.on_scan_progress,  # pyright: ignore[reportAny]
        )

        # Cache I/O collaborator
        self._cache_adapter: ThreeDECacheAdapter = ThreeDECacheAdapter(
            scene_disk_cache=window.scene_disk_cache,
            threede_scene_model=window.threede_scene_model,
        )

        # Selection / interaction collaborator
        self._selection_handler: ThreeDESelectionHandler = ThreeDESelectionHandler(
            window,  # pyright: ignore[reportArgumentType]
            command_launcher=command_launcher,
            refresh_callback=self.refresh_threede_scenes,
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

        # Delegate grid signal wiring to the selection handler
        self._selection_handler.setup_signals(self.window.threede_shot_grid)

        logger.debug("ThreeDEController signals connected")

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
            logger.debug("Ignoring refresh request during shutdown")
            return

        # GUARD: If worker is already running, skip this request entirely
        # This prevents duplicate progress operations during rapid refresh calls
        if self._worker_manager.has_active_worker:
            logger.debug(
                "3DE worker already running, skipping duplicate refresh request"
            )
            return

        # DEBOUNCE: Prevent scan restart spam (e.g., rapid shot refreshes)
        now = time.time()
        time_since_last_scan = now - self._last_scan_time
        if self._last_scan_time > 0 and time_since_last_scan < self._min_scan_interval:
            logger.info(
                f"Scan requested too soon ({time_since_last_scan:.1f}s < {self._min_scan_interval}s), using cached data instead"
            )
            return  # Skip scan, use cached data

        # Update last scan time
        self._last_scan_time = now

        # INSTANT UI UPDATE: Load persistent cache first (no TTL check)
        cached_scenes = self._cache_adapter.load_cached_scenes()

        # Apply cached scenes to model and update UI if any were found
        if cached_scenes:
            self.window.threede_scene_model.set_scenes(cached_scenes)
            self.update_ui()
            logger.info(
                f"Loaded {len(cached_scenes)} cached 3DE scenes immediately "
                "(scanning for updates in background)"
            )

        # Check once more if closing (could have changed while stopping worker)
        if self._closing:
            return

        # Show loading state
        self.window.threede_item_model.set_loading_state(True)
        status_msg = (
            "Scanning for 3DE scene updates..."
            if cached_scenes
            else "Starting enhanced 3DE scene discovery..."
        )
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
                logger.debug(
                    "Finishing orphaned progress operation during cleanup"
                )
                ProgressManager.finish_operation(
                    success=False, error_message="Operation cancelled during shutdown"
                )
            # Our operation was already finished or another operation is on top
            elif current_top is None:
                logger.debug(
                    "3DE progress operation already finished during cleanup"
                )
            else:
                logger.warning(
                    "3DE progress operation not on top of stack during cleanup - skipping finish to prevent stack corruption"
                )
            self._current_progress_operation = None

        # Delegate worker stopping, signal disconnection, and deletion to the manager
        self._worker_manager.cleanup()

    # ============================================================================
    # Worker Signal Handlers
    # ============================================================================

    @Slot()  # pyright: ignore[reportAny]
    def on_discovery_started(self) -> None:
        """Handle 3DE discovery worker started signal."""
        # Check if we're closing to avoid accessing deleted widgets
        if self._closing:
            return

        # Start progress for 3DE discovery and store reference for cleanup
        self._current_progress_operation = ProgressManager.start_operation(
            "3DE Scenes: Scanning user directories"
        )

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
    # Public Selection Delegation (preserve existing call-sites on controller)
    # ============================================================================

    @Slot(object)  # pyright: ignore[reportAny]
    def on_scene_selected(self, scene: ThreeDEScene) -> None:
        """Delegate to selection handler."""
        self._selection_handler.on_scene_selected(scene)

    @Slot(object)  # pyright: ignore[reportAny]
    def on_scene_double_clicked(self, scene: ThreeDEScene) -> None:
        """Delegate to selection handler."""
        self._selection_handler.on_scene_double_clicked(scene)

    @Slot(int)  # pyright: ignore[reportAny]
    def on_tab_activated(self, tab_index: int) -> None:
        """Delegate to selection handler."""
        self._selection_handler.on_tab_activated(tab_index)

    @Slot()  # pyright: ignore[reportAny]
    def on_recover_crashes_clicked(self) -> None:
        """Delegate to selection handler."""
        self._selection_handler.on_recover_crashes_clicked()

    # ============================================================================
    # Scene Management Helpers
    # ============================================================================

    def log_discovered_scenes(self, scenes: list[ThreeDEScene]) -> None:
        """Log discovered scenes for debugging."""
        logger.info(
            f"3DE Discovery finished with {len(scenes)} total scenes discovered"
        )
        for i, scene in enumerate(scenes[:5]):  # Log first 5 scenes
            logger.info(
                f"   Scene {i + 1}: {scene.full_name} (user: {scene.user})"
            )
        if len(scenes) > 5:
            logger.info(f"   ... and {len(scenes) - 5} more scenes")

    def has_scene_changes(self, scenes: list[ThreeDEScene]) -> bool:
        """Check if discovered scenes differ from current model."""
        old_scene_data = {
            (scene.full_name, scene.user, scene.plate, str(scene.scene_path))
            for scene in self.window.threede_scene_model.scenes
        }
        logger.info(f"Current model has {len(old_scene_data)} existing scenes")

        new_scene_data = {
            (scene.full_name, scene.user, scene.plate, str(scene.scene_path))
            for scene in scenes
        }
        logger.info(f"New discovery has {len(new_scene_data)} scene data items")

        has_changes = old_scene_data != new_scene_data
        logger.info(f"Has changes: {has_changes}")
        return has_changes

    def update_scenes_with_changes(self, scenes: list[ThreeDEScene]) -> None:
        """Update model and UI when scene changes are detected."""
        # Update the model with new scenes (deduplication happens in model)
        self.window.threede_scene_model.set_scenes(
            self.window.threede_scene_model.deduplicate_scenes_by_shot(scenes)
        )
        logger.info(
            f"After deduplication: {len(self.window.threede_scene_model.scenes)} scenes remain"
        )

        # Sort deduplicated scenes
        self.window.threede_scene_model.scenes.sort(key=lambda s: (s.full_name, s.user))

        # Cache results
        self._cache_adapter.cache_scenes()

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
        self._cache_adapter.cache_scenes()

        logger.info(
            f"No changes detected - existing model has {len(self.window.threede_scene_model.scenes)} scenes"
        )

        if self.window.threede_scene_model.scenes:
            # Re-apply existing scenes to UI
            self.update_ui()
            logger.info(
                f"Re-applied {len(self.window.threede_scene_model.scenes)} existing scenes to UI"
            )
        else:
            logger.info("No existing scenes in model to apply")

        self.window.update_status("3DE scene discovery complete (no changes)")

    def cache_scenes(self) -> None:
        """Cache the current 3DE scenes.

        Delegates to ThreeDECacheAdapter.  Kept on controller to avoid breaking
        any existing call-sites.
        """
        self._cache_adapter.cache_scenes()

    def update_ui(self) -> None:
        """Update the 3DE UI elements with current scenes."""
        scene_model = self.window.threede_scene_model
        proxy = self.window.threede_proxy
        active_show = proxy.get_show_filter()
        available_shows = scene_model.get_unique_shows()
        if active_show is not None and active_show not in available_shows:
            proxy.set_show_filter(None)

        active_artist = proxy.get_artist_filter()
        available_artists = scene_model.get_unique_artists()
        if active_artist is not None and active_artist not in available_artists:
            proxy.set_artist_filter(None)

        self.window.threede_shot_grid.populate_show_filter(available_shows)
        self.window.threede_shot_grid.populate_artist_filter(available_artists)
        self.window.threede_proxy.invalidate()
        visible_count = self.window.threede_proxy.rowCount()
        total_count = len(scene_model.scenes)
        logger.info(
            "UI model updated with %s visible scenes from %s total",
            visible_count,
            total_count,
        )

    # ============================================================================
    # Properties and State Access
    # ============================================================================
