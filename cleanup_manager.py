"""Cleanup manager for MainWindow resource management."""

# pyright: reportExplicitAny=false, reportAny=false

from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from config import Config
from logging_mixin import LoggingMixin


class MainWindowProtocol(Protocol):
    """Protocol defining the MainWindow interface needed by CleanupManager.

    This avoids circular imports while providing proper type safety.
    Attributes are typed as Any because we cannot import MainWindow
    without creating a circular dependency.
    """

    closing: bool
    threede_controller: Any
    session_warmer: Any
    launcher_manager: Any
    cache_manager: Any
    shot_model: Any
    previous_shots_model: Any
    previous_shots_item_model: Any
    persistent_terminal: Any
    command_launcher: Any


class CleanupManager(QObject, LoggingMixin):
    """Manages all cleanup operations for MainWindow.

    This class extracts the complex cleanup logic from MainWindow,
    reducing its size and improving maintainability. It handles cleanup
    of models, workers, cache, UI components, and managers in the
    correct order.
    """

    # Signals
    cleanup_started: Signal = Signal()
    cleanup_finished: Signal = Signal()

    def __init__(self, main_window: MainWindowProtocol) -> None:
        """Initialize cleanup manager.

        Args:
            main_window: The MainWindow instance to manage cleanup for
        """
        super().__init__()
        LoggingMixin.__init__(self)
        self.main_window: MainWindowProtocol = main_window
        self.logger.debug("CleanupManager initialized")

    def perform_cleanup(self) -> None:
        """Main cleanup orchestration method.

        This is the primary entry point for cleanup operations,
        called by MainWindow.cleanup() and MainWindow.closeEvent().
        """
        self.cleanup_started.emit()
        self.logger.debug("Starting MainWindow cleanup sequence")

        try:
            self._mark_closing()
            self._cleanup_threede_controller()
            self._cleanup_session_warmer()
            self._cleanup_managers()
            self._cleanup_models()
            self._cleanup_terminal()
            self._final_cleanup()

            self.logger.debug("MainWindow cleanup sequence completed")
        finally:
            self.cleanup_finished.emit()

    def _mark_closing(self) -> None:
        """Mark that the application is closing to prevent new operations."""
        self.main_window.closing = True

    def _cleanup_threede_controller(self) -> None:
        """Clean up the 3DE controller and its worker."""
        if (
            hasattr(self.main_window, "threede_controller")
            and self.main_window.threede_controller
        ):
            self.logger.debug("Cleaning up 3DE controller")
            self.main_window.threede_controller.cleanup_worker()

    def _cleanup_session_warmer(self) -> None:
        """Clean up the session warmer thread."""
        if not (
            hasattr(self.main_window, "session_warmer")
            and self.main_window.session_warmer
        ):
            return

        warmer = self.main_window.session_warmer

        if not warmer.isFinished():
            self.logger.debug("Requesting session warmer to stop")
            warmer.request_stop()

            # Determine timeout based on environment
            import sys  # noqa: PLC0415 - Lazy import to detect pytest environment

            is_test_environment = "pytest" in sys.modules
            session_timeout_ms = 200 if is_test_environment else 2000

            if not warmer.wait(session_timeout_ms):
                self.logger.warning(
                    f"Session warmer didn't finish gracefully within {session_timeout_ms}ms, using safe termination"
                )
                warmer.safe_terminate()

                final_timeout_ms = 100 if is_test_environment else 1000
                if not warmer.wait(final_timeout_ms):
                    self.logger.warning(
                        "Session warmer thread abandoned - will be cleaned on exit"
                    )

        # Only delete if not a zombie
        if hasattr(warmer, "is_zombie") and warmer.is_zombie():
            self.logger.warning(
                "Session warmer thread is a zombie and will not be deleted"
            )
        else:
            warmer.deleteLater()

        self.main_window.session_warmer = None

    def _cleanup_managers(self) -> None:
        """Clean up manager instances."""
        # Log Nuke launcher usage statistics
        if (
            hasattr(self.main_window, "command_launcher")
            and self.main_window.command_launcher
            and hasattr(self.main_window.command_launcher, "nuke_handler")
            and hasattr(self.main_window.command_launcher.nuke_handler, "log_usage_stats")
        ):
            self.logger.debug("Logging Nuke launcher usage statistics")
            self.main_window.command_launcher.nuke_handler.log_usage_stats()

        # Shutdown launcher manager to stop all worker threads
        if (
            hasattr(self.main_window, "launcher_manager")
            and self.main_window.launcher_manager
            and hasattr(self.main_window.launcher_manager, "shutdown")
        ):
            self.logger.debug("Shutting down launcher manager")
            self.main_window.launcher_manager.shutdown()

        # Shutdown cache manager
        if (
            hasattr(self.main_window, "cache_manager")
            and self.main_window.cache_manager
        ):
            self.logger.debug("Shutting down cache manager")
            self.main_window.cache_manager.shutdown()

    def _cleanup_models(self) -> None:
        """Clean up model instances and their background workers."""
        # Clean up ShotModel background threads
        if (
            hasattr(self.main_window, "shot_model")
            and self.main_window.shot_model
            and hasattr(self.main_window.shot_model, "cleanup")
        ):
            self.logger.debug("Cleaning up ShotModel background threads")
            self.main_window.shot_model.cleanup()

        # Clean up previous shots model (stops auto-refresh timer and worker)
        if (
            hasattr(self.main_window, "previous_shots_model")
            and self.main_window.previous_shots_model
        ):
            self.logger.debug("Cleaning up PreviousShotsModel")
            try:
                self.main_window.previous_shots_model.cleanup()
            except Exception as e:
                self.logger.error(f"Error cleaning up PreviousShotsModel: {e}")

        # Also clean up the item model if it exists
        if (
            hasattr(self.main_window, "previous_shots_item_model")
            and self.main_window.previous_shots_item_model
        ):
            self.logger.debug("Cleaning up PreviousShotsItemModel")
            try:
                if hasattr(self.main_window.previous_shots_item_model, "cleanup"):
                    self.main_window.previous_shots_item_model.cleanup()
            except Exception as e:
                self.logger.error(f"Error cleaning up PreviousShotsItemModel: {e}")

    def _cleanup_terminal(self) -> None:
        """Clean up persistent terminal if it exists."""
        if not (
            hasattr(self.main_window, "persistent_terminal")
            and self.main_window.persistent_terminal
        ):
            return

        self.logger.debug("Cleaning up persistent terminal")

        # Check if we should keep terminal open after exit
        if not getattr(Config, "KEEP_TERMINAL_ON_EXIT", False):
            self.main_window.persistent_terminal.cleanup()
        else:
            # Just cleanup FIFO but leave terminal running
            self.logger.info("Keeping terminal open after application exit")
            if hasattr(self.main_window.persistent_terminal, "cleanup_fifo_only"):
                self.main_window.persistent_terminal.cleanup_fifo_only()

    def _final_cleanup(self) -> None:
        """Perform final cleanup steps - QRunnables, timers, and garbage collection."""
        # Process pending events BEFORE cleanup to drain event queue safely
        app = QApplication.instance()
        if app:
            app.processEvents()

        # Clean up any remaining QRunnables in the thread pool
        from runnable_tracker import (  # noqa: PLC0415 - Lazy import for cleanup
            cleanup_all_runnables,
        )

        self.logger.debug("Cleaning up tracked QRunnables")
        cleanup_all_runnables()

        # Force garbage collection to clean up any circular references
        import gc  # noqa: PLC0415 - Lazy import for garbage collection

        _ = gc.collect()

        self.logger.debug("Final cleanup complete - GC collection done")
