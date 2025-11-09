"""Refresh orchestrator for coordinating refresh operations across tabs."""

# pyright: reportExplicitAny=false, reportAny=false

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Protocol

from PySide6.QtCore import QObject, Signal

from logging_mixin import LoggingMixin
from notification_manager import NotificationManager
from progress_manager import ProgressManager


if TYPE_CHECKING:
    from shot_model import Shot


class RefreshOrchestratorMainWindowProtocol(Protocol):
    """Protocol defining the MainWindow interface needed by RefreshOrchestrator.

    This avoids circular imports while providing proper type safety.
    Attributes are typed as Any because we cannot import MainWindow
    without creating a circular dependency.
    """

    tab_widget: Any
    shot_model: Any
    threede_controller: Any
    previous_shots_model: Any
    shot_item_model: Any
    shot_grid: Any
    last_selected_shot_name: str | None

    def update_status(self, message: str) -> None:
        """Update the status bar with a message."""
        ...


class RefreshOrchestrator(QObject, LoggingMixin):
    """Orchestrates refresh operations across different tabs in MainWindow.

    This class extracts the refresh coordination logic from MainWindow,
    handling refresh operations for shots, 3DE scenes, and previous shots
    with proper progress indication and notifications.
    """

    # Signals
    refresh_started: Signal = Signal(int)  # tab_index
    refresh_finished: Signal = Signal(int, bool)  # tab_index, success

    def __init__(self, main_window: RefreshOrchestratorMainWindowProtocol) -> None:
        """Initialize refresh orchestrator.

        Args:
            main_window: The MainWindow instance to coordinate refreshes for
        """
        super().__init__()
        LoggingMixin.__init__(self)
        self.main_window: RefreshOrchestratorMainWindowProtocol = main_window
        self._last_refresh_time: float = 0.0  # Debounce duplicate display refreshes
        self._refresh_debounce_interval: float = 0.5  # 500ms debounce window
        self.logger.debug("RefreshOrchestrator initialized")

    def refresh_current_tab(self) -> None:
        """Refresh based on the currently active tab."""
        tab_index = self.main_window.tab_widget.currentIndex()
        self.refresh_tab(tab_index)

    def refresh_tab(self, index: int) -> None:
        """Refresh specific tab by index.

        Args:
            index: Tab index (0=My Shots, 1=Other 3DE, 2=Previous)
        """
        self.refresh_started.emit(index)

        if index == 0:  # My Shots tab
            self._refresh_shots()
        elif index == 1:  # Other 3DE tab
            self._refresh_threede()
        elif index == 2:  # Previous Shots tab
            self._refresh_previous()

    def _refresh_shots(self) -> None:
        """Refresh shot list with progress indication."""
        self.logger.info(">>> RefreshOrchestrator._refresh_shots() START")
        # Start progress operation for shot refresh
        self.logger.info("Creating ProgressManager.operation context...")
        with ProgressManager.operation(
            "Refreshing shots", cancelable=False
        ) as progress:
            self.logger.info("ProgressManager.operation created, setting indeterminate...")
            progress.set_indeterminate()

            # Simply call refresh_shots on the model
            # The model will emit signals that trigger the appropriate handlers
            self.logger.info("Calling shot_model.refresh_shots()...")
            success, _ = self.main_window.shot_model.refresh_shots()
            self.logger.info(f"shot_model.refresh_shots() returned: success={success}")
            self.refresh_finished.emit(0, success)
            self.logger.info("Emitted refresh_finished signal")

        self.logger.info("<<< RefreshOrchestrator._refresh_shots() COMPLETE")

    def _refresh_threede(self) -> None:
        """Refresh Other 3DE scenes."""
        if (
            hasattr(self.main_window, "threede_controller")
            and self.main_window.threede_controller
        ):
            self.main_window.threede_controller.refresh_threede_scenes()
            self.refresh_finished.emit(1, True)
        else:
            self.logger.warning("3DE controller not available for refresh")
            self.refresh_finished.emit(1, False)

    def _refresh_previous(self) -> None:
        """Refresh Previous Shots."""
        if (
            hasattr(self.main_window, "previous_shots_model")
            and self.main_window.previous_shots_model
        ):
            self.main_window.previous_shots_model.refresh_shots()
            self.refresh_finished.emit(2, True)
        else:
            self.logger.warning("Previous shots model not available for refresh")
            self.refresh_finished.emit(2, False)

    def handle_shots_loaded(self, shots: list[Shot]) -> None:
        """Handle shots loaded signal from model.

        Args:
            shots: List of loaded Shot objects
        """
        self.logger.info(f"Shots loaded signal received: {len(shots)} shots")
        self._refresh_shot_display()
        self._update_status(f"Loaded {len(shots)} shots")
        NotificationManager.info(f"{len(shots)} shots loaded")

    def handle_shots_changed(self, shots: list[Shot]) -> None:
        """Handle shots changed signal from model.

        Args:
            shots: List of updated Shot objects
        """
        self.logger.info(f"Shots changed signal received: {len(shots)} shots")
        self._refresh_shot_display()
        self._update_status(f"Shot list updated: {len(shots)} shots")
        NotificationManager.success(f"Refreshed {len(shots)} shots")

    def handle_refresh_started(self) -> None:
        """Handle refresh started signal from model."""
        # Update status bar to show refresh in progress
        self._update_status("Refreshing shots...")

    def handle_refresh_finished(self, success: bool, has_changes: bool) -> None:
        """Handle refresh finished signal from model.

        Args:
            success: Whether the refresh was successful
            has_changes: Whether the shot list changed
        """
        if success:
            if has_changes:
                # UI update already handled by shots_changed signal
                self.logger.debug("Refresh completed with changes")
            else:
                shot_count = len(self.main_window.shot_model.shots)
                self._update_status(f"{shot_count} shots (no changes)")
                NotificationManager.info(f"{shot_count} shots (no changes)")
                self.logger.debug("Refresh completed without changes")

            # Restore last selected shot if available
            last_shot_name = self.main_window.last_selected_shot_name
            if last_shot_name is not None:
                shot = self.main_window.shot_model.find_shot_by_name(last_shot_name)
                if shot:
                    self.main_window.shot_grid.select_shot_by_name(shot.full_name)

            # Also refresh 3DE scenes when shots are refreshed
            if self.main_window.shot_model.shots and (
                hasattr(self.main_window, "threede_controller")
                and self.main_window.threede_controller
            ):
                self.main_window.threede_controller.refresh_threede_scenes()
        else:
            self._update_status("Failed to refresh shots")
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
            if (
                hasattr(self.main_window, "previous_shots_model")
                and self.main_window.previous_shots_model
            ):
                self.main_window.previous_shots_model.refresh_shots()
        else:
            self.logger.debug("No active shots loaded, skipping previous shots refresh")

    def _refresh_shot_display(self) -> None:
        """Refresh the shot display using Model/View implementation."""
        # Debounce rapid refresh calls (e.g., cached shots followed by fresh shots)
        now = time.time()
        time_since_last_refresh = now - self._last_refresh_time
        if self._last_refresh_time > 0 and time_since_last_refresh < self._refresh_debounce_interval:
            self.logger.debug(
                f"Skipping duplicate refresh (last refresh {time_since_last_refresh:.2f}s ago)"
            )
            return

        self._last_refresh_time = now

        # Always use Model/View implementation
        if hasattr(self.main_window, "shot_item_model") and hasattr(
            self.main_window, "shot_grid"
        ):
            self.main_window.shot_item_model.set_shots(
                self.main_window.shot_model.shots
            )
            # Populate show filter with available shows
            self.main_window.shot_grid.populate_show_filter(self.main_window.shot_model)

    def _update_status(self, message: str) -> None:
        """Update the status bar with a message.

        Args:
            message: The status message to display
        """
        if hasattr(self.main_window, "update_status"):
            self.main_window.update_status(message)
