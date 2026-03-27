"""Refresh coordinator for coordinating refresh operations across tabs."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final

from PySide6.QtCore import QObject, QTimer, Signal

from logging_mixin import LoggingMixin
from managers.notification_manager import NotificationManager
from managers.progress_manager import ProgressManager
from ui.tab_constants import TAB_MY_SHOTS, TAB_OTHER_3DE, TAB_PREVIOUS


if TYPE_CHECKING:
    from protocols import RefreshCoordinatorMainWindowProtocol
    from type_definitions import Shot


@final
class RefreshCoordinator(QObject, LoggingMixin):
    """Orchestrates refresh operations across different tabs in MainWindow.

    This class extracts the refresh coordination logic from MainWindow,
    handling refresh operations for shots, 3DE scenes, and previous shots
    with proper progress indication and notifications.

    Debounce/In-Progress Guard:
        The _refresh_in_progress flag prevents overlapping async refreshes while
        ShotModel is loading. Time-based debounce (500ms) deduplicates rapid
        display updates when cached shots arrive before fresh data.

    Delegation:
        Coordinates shot_model, threede_controller, and previous_shots_model
        refresh operations, routing results through signal handlers and UI updates.
    """

    threede_refresh_requested: ClassVar[Signal] = Signal()

    def __init__(self, main_window: RefreshCoordinatorMainWindowProtocol) -> None:
        """Initialize refresh orchestrator.

        Args:
            main_window: The MainWindow instance to coordinate refreshes for

        """
        super().__init__()
        LoggingMixin.__init__(self)
        self.main_window: RefreshCoordinatorMainWindowProtocol = main_window
        # Two-layer refresh guard:
        # 1. Timer-based debounce: prevents rapid-fire display refreshes when
        #    cached shots arrive followed immediately by fresh shots (< 500ms).
        #    First call executes immediately; subsequent calls within the 500ms
        #    cooldown window are dropped.
        # 2. In-progress flag: prevents overlapping async ws -sg subprocess
        #    calls (the flag stays True from _refresh_shots until
        #    handle_refresh_finished completes).
        self._refresh_debounce_timer: QTimer = QTimer(self)
        self._refresh_debounce_timer.setSingleShot(True)
        self._refresh_debounce_timer.setInterval(500)  # ms, was 0.5s
        self._shots_refresh_in_progress: bool = False
        self.logger.debug("RefreshCoordinator initialized")

    def setup_signals(self) -> None:
        """Wire shot model signals to this coordinator's handlers.

        Called by MainWindow._connect_signals() after shot_model is available.
        """
        sm = self.main_window.shot_model
        _ = sm.shots_loaded.connect(self.handle_shots_loaded)  # pyright: ignore[reportAny]
        _ = sm.shots_loaded.connect(self.trigger_previous_shots_refresh)  # pyright: ignore[reportAny]
        _ = sm.shots_changed.connect(self.handle_shots_changed)  # pyright: ignore[reportAny]
        _ = sm.shots_changed.connect(self.trigger_previous_shots_refresh)  # pyright: ignore[reportAny]
        _ = sm.refresh_started.connect(self.handle_refresh_started)  # pyright: ignore[reportAny]
        _ = sm.refresh_finished.connect(self.handle_refresh_finished)  # pyright: ignore[reportAny]

    def refresh_current_tab(self) -> None:
        """Refresh based on the currently active tab."""
        tab_index = self.main_window.tab_widget.currentIndex()
        self.refresh_tab(tab_index)

    def refresh_tab(self, index: int) -> None:
        """Refresh specific tab by index.

        Args:
            index: Tab index (0=My Shots, 1=Other 3DE, 2=Previous)

        """
        if index == TAB_MY_SHOTS:
            self._refresh_shots()
        elif index == TAB_OTHER_3DE:
            self._refresh_threede()
        elif index == TAB_PREVIOUS:
            self._refresh_previous()

    def _refresh_shots(self) -> None:
        """Refresh shot list with progress indication.

        Always bypasses ws command cache for user-initiated refresh.
        Note: Does NOT emit refresh_finished here - that's handled by
        handle_refresh_finished() when ShotModel's async operation completes.

        Progress dialog is started here and closed in handle_refresh_finished()
        to ensure the dialog stays open during the entire async operation.
        """
        # Start progress operation manually (don't use context manager for async)
        # The operation will be finished in handle_refresh_finished()
        _ = ProgressManager.start_operation("Refreshing shots")
        self._shots_refresh_in_progress = True

        # force_fresh=True bypasses ws -sg cache for user-initiated refresh
        # ShotModel.refresh_shots() returns immediately; async loader continues.
        # refresh_finished will be emitted by handle_refresh_finished() when
        # ShotModel emits its refresh_finished signal after async completes.
        _ = self.main_window.shot_model.refresh_shots(force_fresh=True)

    def _refresh_threede(self) -> None:
        """Refresh Other 3DE scenes."""
        self.threede_refresh_requested.emit()

    def _refresh_previous(self) -> None:
        """Refresh Previous Shots."""
        _ = self.main_window.previous_shots_model.refresh_shots()

    def handle_shots_loaded(self, shots: list[Shot]) -> None:
        """Handle shots loaded signal from model.

        Args:
            shots: List of loaded Shot objects

        """
        self.logger.info(f"Shots loaded signal received: {len(shots)} shots")
        self.refresh_shot_display()
        self.main_window.update_status(f"Loaded {len(shots)} shots")
        NotificationManager.info(f"{len(shots)} shots loaded")

    def handle_shots_changed(self, shots: list[Shot]) -> None:
        """Handle shots changed signal from model.

        Args:
            shots: List of updated Shot objects

        """
        self.logger.info(f"Shots changed signal received: {len(shots)} shots")
        self.refresh_shot_display()
        self.main_window.update_status(f"Shot list updated: {len(shots)} shots")
        NotificationManager.success(f"Refreshed {len(shots)} shots")

    def handle_refresh_started(self) -> None:
        """Handle refresh started signal from model."""
        # Update status bar to show refresh in progress
        self.main_window.update_status("Refreshing shots...")

    def handle_refresh_finished(self, success: bool, has_changes: bool) -> None:
        """Handle refresh finished signal from model.

        This is called when ShotModel's async loading completes.
        Emits refresh_finished(0, success) to notify that the shots tab refresh is done.
        Also closes the progress dialog that was started in _refresh_shots().

        Args:
            success: Whether the refresh was successful
            has_changes: Whether the shot list changed

        """
        # Close progress dialog that was started in _refresh_shots()
        if self._shots_refresh_in_progress:
            ProgressManager.finish_operation(success=success)
            self._shots_refresh_in_progress = False

        if success:
            if has_changes:
                # UI update already handled by shots_changed signal
                self.logger.debug("Refresh completed with changes")
            else:
                shot_count = len(self.main_window.shot_model.shots)
                self.main_window.update_status(f"{shot_count} shots (no changes)")
                NotificationManager.info(f"{shot_count} shots (no changes)")
                self.logger.debug("Refresh completed without changes")

            # Restore last selected shot if available
            last_shot_name = self.main_window.last_selected_shot_name
            if last_shot_name is not None:
                shot = self.main_window.shot_model.find_shot_by_name(last_shot_name)
                if shot:
                    self.main_window.shot_grid.select_shot_by_name(shot.full_name)

            # Also refresh 3DE scenes when shots are refreshed
            if self.main_window.shot_model.shots:
                self.threede_refresh_requested.emit()
        else:
            self.main_window.update_status("Failed to refresh shots")
            NotificationManager.error(
                "Failed to Load Shots",
                "Unable to retrieve shot data from the workspace.",
                "Make sure the 'ws -sg' command is available and you're in a valid workspace.",
            )

    def trigger_previous_shots_refresh(self, shots: list[Shot]) -> None:
        """Trigger previous shots refresh only after shots are loaded.

        This method ensures that previous shots scanning only starts when
        active shots are available, preventing the "No target shows found" warning.

        Args:
            shots: The loaded shots (from signal)

        """
        if shots:  # Only refresh if we actually have shots
            self.logger.info(
                f"Triggering previous shots refresh after loading {len(shots)} active shots"
            )
            _ = self.main_window.previous_shots_model.refresh_shots()
        else:
            self.logger.debug("No active shots loaded, skipping previous shots refresh")

    def refresh_shot_display(self) -> None:
        """Refresh the shot display (debounced).

        First call executes immediately and starts a 500ms cooldown. Subsequent
        calls within the cooldown window are dropped to deduplicate rapid-fire
        updates (e.g., cached shots arriving just before fresh shots).
        """
        if not self._refresh_debounce_timer.isActive():
            # First call: execute immediately, start cooldown
            self._do_refresh_shot_display()
            self._refresh_debounce_timer.start()
        else:
            self.logger.debug("Skipping duplicate refresh (debounce active)")

    def _do_refresh_shot_display(self) -> None:
        """Refresh the shot display using Model/View implementation."""
        # Always use Model/View implementation; proxy handles filtering
        self.main_window.shot_item_model.set_shots(self.main_window.shot_model.shots)
        # Populate show filter with available shows.
        # Pass shows as a sorted list — ShotModel.get_available_shows() returns set[str]
        # which doesn't satisfy the HasAvailableShows protocol (requires list[str]),
        # so we convert here explicitly.
        self.main_window.shot_grid.populate_show_filter(
            sorted(self.main_window.shot_model.get_available_shows())
        )
