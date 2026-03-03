"""Cleanup manager for MainWindow resource management."""

# pyright: reportExplicitAny=false, reportAny=false

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from cache import CacheCoordinator
    from command_launcher import CommandLauncher
    from controllers.shot_selection_controller import ShotSelectionController
    from controllers.threede_controller import ThreeDEController
    from previous_shots_model import PreviousShotsModel
    from shot_model import ShotModel


@runtime_checkable
class Cleanable(Protocol):
    def cleanup(self) -> None: ...


class _SessionWarmerProtocol(Protocol):
    """Structural protocol for session warmer thread.

    SessionWarmer is defined inside main_window.py (not importable without
    creating a circular dependency), so we capture only the methods that
    CleanupManager actually calls.
    """

    def isFinished(self) -> bool: ...
    def request_stop(self) -> None: ...
    def wait(self, msecs: int = ...) -> bool: ...
    def safe_terminate(self) -> None: ...
    def is_zombie(self) -> bool: ...
    def deleteLater(self) -> None: ...


class CleanupTarget(Protocol):
    """Protocol defining the MainWindow interface needed by CleanupManager.

    This avoids circular imports while providing proper type safety.
    TYPE_CHECKING imports provide proper types without creating circular
    import cycles at runtime.
    """

    closing: bool  # skylos: ignore
    threede_controller: ThreeDEController | None  # skylos: ignore
    shot_selection_controller: ShotSelectionController | None  # skylos: ignore
    session_warmer: QObject | None  # skylos: ignore
    cache_coordinator: CacheCoordinator  # skylos: ignore
    shot_model: ShotModel  # skylos: ignore
    previous_shots_model: PreviousShotsModel | None  # skylos: ignore
    previous_shots_item_model: QObject | None  # skylos: ignore
    command_launcher: CommandLauncher | None


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

    def __init__(self, main_window: CleanupTarget) -> None:
        """Initialize cleanup manager.

        Args:
            main_window: The MainWindow instance to manage cleanup for

        """
        super().__init__()
        LoggingMixin.__init__(self)
        self.main_window: CleanupTarget = main_window
        self.logger.debug("CleanupManager initialized")

    def perform_cleanup(self) -> None:
        """Main cleanup orchestration method.

        This is the primary entry point for cleanup operations,
        called by MainWindow.cleanup() and MainWindow.closeEvent().

        Cleanup ordering:
            1. Mark window as closing (_mark_closing)
            2. Controllers (threede_controller, shot_selection_controller)
            3. Session warmer thread (_cleanup_session_warmer)
            4. Managers (command_launcher, cache_coordinator)
            5. Models (shot_model, previous_shots_model, previous_shots_item_model)
        """
        self.cleanup_started.emit()
        self.logger.debug("Starting MainWindow cleanup sequence")

        try:
            self._mark_closing()
            self._cleanup_threede_controller()
            self._cleanup_shot_selection_controller()
            self._cleanup_session_warmer()
            self._cleanup_managers()
            self._cleanup_models()
            self._final_cleanup()

            self.logger.debug("MainWindow cleanup sequence completed")
        finally:
            self.cleanup_finished.emit()

    def _mark_closing(self) -> None:
        """Mark that the application is closing to prevent new operations."""
        self.main_window.closing = True

    def _cleanup_threede_controller(self) -> None:
        """Clean up the 3DE controller and its worker."""
        if self.main_window.threede_controller:
            self.logger.debug("Cleaning up 3DE controller")
            self.main_window.threede_controller.cleanup_worker()

    def _cleanup_shot_selection_controller(self) -> None:
        """Clean up the shot selection controller and its discovery worker."""
        if self.main_window.shot_selection_controller:
            self.logger.debug("Cleaning up shot selection controller")
            self.main_window.shot_selection_controller.cleanup()

    def _cleanup_session_warmer(self) -> None:
        """Clean up the session warmer thread."""
        if not self.main_window.session_warmer:
            return

        # Cast to _SessionWarmerProtocol: session_warmer is typed as QObject | None
        # in the protocol (SessionWarmer is defined inside main_window.py and cannot
        # be imported here), but at runtime it's always a ThreadSafeWorker subclass
        # that provides these methods.
        from typing import cast

        warmer = cast("_SessionWarmerProtocol", self.main_window.session_warmer)

        if not warmer.isFinished():
            self.logger.debug("Requesting session warmer to stop")
            warmer.request_stop()

            # Determine timeout based on environment
            import sys

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
            self.main_window.command_launcher
            and hasattr(self.main_window.command_launcher, "nuke_handler")
            and hasattr(self.main_window.command_launcher.nuke_handler, "log_usage_stats")
        ):
            self.logger.debug("Logging Nuke launcher usage statistics")
            self.main_window.command_launcher.nuke_handler.log_usage_stats()

        # Cleanup command launcher
        if (
            self.main_window.command_launcher
            and hasattr(self.main_window.command_launcher, "cleanup")
        ):
            self.logger.debug("Cleaning up command launcher")
            self.main_window.command_launcher.cleanup()

        # Shutdown cache coordinator
        self.logger.debug("Shutting down cache coordinator")
        self.main_window.cache_coordinator.shutdown()

    def _cleanup_models(self) -> None:
        """Clean up model instances and their background workers."""
        # Clean up ShotModel background threads
        if hasattr(self.main_window.shot_model, "cleanup"):
            self.logger.debug("Cleaning up ShotModel background threads")
            self.main_window.shot_model.cleanup()

        # Clean up previous shots model (stops auto-refresh timer and worker)
        if self.main_window.previous_shots_model:
            self.logger.debug("Cleaning up PreviousShotsModel")
            try:
                self.main_window.previous_shots_model.cleanup()
            except Exception:
                self.logger.exception("Error cleaning up PreviousShotsModel")

        # Also clean up the item model if it exists
        if self.main_window.previous_shots_item_model:
            self.logger.debug("Cleaning up PreviousShotsItemModel")
            try:
                item_model = self.main_window.previous_shots_item_model
                if isinstance(item_model, Cleanable):
                    item_model.cleanup()
            except Exception:
                self.logger.exception("Error cleaning up PreviousShotsItemModel")

    def _final_cleanup(self) -> None:
        """Perform final cleanup steps - QRunnables, timers, and garbage collection."""
        # Process pending events BEFORE cleanup to drain event queue safely
        app = QApplication.instance()
        if app:
            app.processEvents()

        # Clean up any remaining QRunnables in the thread pool
        from runnable_tracker import (
            cleanup_all_runnables,
        )

        self.logger.debug("Cleaning up tracked QRunnables")
        cleanup_all_runnables()

        # Force garbage collection to clean up any circular references
        import gc

        _ = gc.collect()

        self.logger.debug("Final cleanup complete - GC collection done")
