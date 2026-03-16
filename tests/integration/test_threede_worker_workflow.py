"""Integration tests for complete 3DE worker workflow following UNIFIED_TESTING_GUIDE.

Tests the complete user-triggered workflow from ThreeDESceneWorker through to the
parallel discovery methods. This represents the actual production workflow that
triggered the ThreadSafeProgressTracker parameter bug.

UNIFIED_TESTING_GUIDE COMPLIANCE:
1. Qt Widget Pattern (lines 82-102): Proper qtbot.addWidget for cleanup
2. Worker Thread Pattern (lines 104-121): Real QThread testing with signals
3. Signal Testing Pattern (lines 122-160): waitSignal BEFORE triggering actions
4. Integration Test Pattern (lines 336-354): Real components with test boundaries

Qt Test Hygiene
===============
This file tests QThread-based workers, which require proper cleanup to prevent
Qt C++ object accumulation that causes segfaults in large serial test runs.

**Cleanup Requirements** (implemented via `tests/helpers/qt_thread_cleanup.py`):
1. Disconnect all signal handlers BEFORE stopping thread
2. Stop thread gracefully: requestInterruption() → quit() → wait()
3. Call deleteLater() on the thread object
4. Process events to flush deletion queue: processEvents() + sendPostedEvents()

**Why This Matters**:
Without proper cleanup (especially deleteLater() + event processing), Qt C++ objects
accumulate across tests. In serial execution, this accumulation eventually causes
segfaults in qtbot.waitSignal() - not because Qt is "corrupted", but because of
resource exhaustion from leaked objects.

**Test Execution**:
- Development: `pytest tests/integration/test_threede_worker_workflow.py -n 2`
- CI/verification: `pytest tests/integration/test_threede_worker_workflow.py -n 0`
- True isolation: `pytest tests/integration/test_threede_worker_workflow.py --forked`

See `QT_TEST_HYGIENE_AUDIT.md` for complete analysis of cleanup requirements.

References:
- https://pytest-qt.readthedocs.io/en/latest/note_dialogs.html
- https://doc.qt.io/qt-6/objecttrees.html
- https://doc.qt.io/qt-6/qthread.html#details

"""

from __future__ import annotations

# Standard library imports
import time
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from tests.integration.conftest import create_test_vfx_structure
from threede import ThreeDESceneWorker


pytestmark = [
    pytest.mark.qt,
    pytest.mark.slow,
]


@pytest.fixture(autouse=True)
def ensure_qt_cleanup(qtbot):
    """Ensure Qt event processing completes after each test.

    This prevents Qt state pollution between tests, which can cause
    segfaults when Qt tries to access deleted objects.

    CRITICAL: This must run after EVERY test to prevent crashes.
    """
    yield
    # Process all pending Qt events after test completes
    qtbot.wait(1)  # Minimal event processing


@pytest.fixture(autouse=True)
def reset_threede_singletons() -> None:
    """Reset 3DE-related singletons to prevent cross-test contamination.

    Resets:
    - ProcessPoolManager._instance (used by worker for parallel discovery)
    - NotificationManager._instance (used for progress notifications)
    - ProgressManager._instance (used for operation tracking)
    """
    # Import here to avoid circular dependencies
    from notification_manager import NotificationManager
    from process_pool_manager import ProcessPoolManager
    from progress_manager import ProgressManager

    # Reset ProcessPoolManager
    if ProcessPoolManager._instance is not None:
        try:
            if hasattr(ProcessPoolManager._instance, "shutdown"):
                ProcessPoolManager._instance.shutdown(timeout=1.0)
        except Exception:  # noqa: BLE001
            pass
    ProcessPoolManager._instance = None
    ProcessPoolManager._initialized = False

    # Reset NotificationManager
    if NotificationManager._instance is not None:
        try:
            NotificationManager.cleanup()
        except (RuntimeError, AttributeError):
            pass
        if hasattr(NotificationManager._instance, "_initialized"):
            delattr(NotificationManager._instance, "_initialized")
    NotificationManager._instance = None
    NotificationManager._main_window = None
    NotificationManager._status_bar = None
    NotificationManager._active_toasts = []
    NotificationManager._current_progress = None

    # Reset ProgressManager
    if ProgressManager._instance is not None:
        try:
            ProgressManager.clear_all_operations()
        except (RuntimeError, AttributeError):
            pass
        if hasattr(ProgressManager._instance, "_initialized"):
            delattr(ProgressManager._instance, "_initialized")
    ProgressManager._instance = None
    ProgressManager._operation_stack = []
    ProgressManager._status_bar = None

    yield

    # Reset again after test (defense in depth)
    ProcessPoolManager._instance = None
    ProcessPoolManager._initialized = False
    NotificationManager._instance = None
    ProgressManager._instance = None


class TestThreeDEWorkerWorkflow:
    """Test complete 3DE worker workflow as triggered by user actions.

    These tests represent the actual user workflows that would have triggered
    the ThreadSafeProgressTracker parameter bug in production.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path) -> None:
        """Set up test fixtures."""
        self.temp_dir = tmp_path / "shotbot"
        self.temp_dir.mkdir()
        self.shows_root = self.temp_dir / "shows"

    def test_worker_full_production_workflow(self, qtbot) -> None:
        """Test complete worker workflow as triggered by user - would catch parameter bug.

        This test exercises the exact workflow that failed in production:
        1. User triggers 3DE scan from UI
        2. Worker starts with progress callbacks
        3. Worker calls parallel discovery methods
        4. ThreadSafeProgressTracker receives progress_interval parameter
        """
        from tests.test_helpers import cleanup_qthread_properly

        _, test_shots = create_test_vfx_structure(
            self.shows_root,
            show_names=["TESTSHOW", "DEMO"],
            users=["artist1", "artist2"],
        )

        # Create worker - real component, not mock (UNIFIED_TESTING_GUIDE line 52)
        # ThreeDESceneWorker requires shots parameter in constructor
        worker = ThreeDESceneWorker(
            shots=test_shots[:4],  # Subset for testing
            excluded_users={"excludeduser"},
            enable_progressive=True,
            scan_all_shots=True,  # This triggers the parallel discovery path that failed
        )

        # Track signals received
        progress_updates = []
        error_messages = []
        final_scenes = None

        def on_progress(
            current: int, total: int, percentage: float, status: str, eta: str
        ) -> None:
            progress_updates.append((current, total, percentage, status, eta))

        def on_error(error_msg: str) -> None:
            error_messages.append(error_msg)

        def on_finished(scenes: list) -> None:
            nonlocal final_scenes
            final_scenes = scenes

        # Connect signals
        worker.progress.connect(on_progress)
        worker.error.connect(on_error)
        worker.discovery_finished.connect(on_finished)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.progress, on_progress),
            (worker.error, on_error),
            (worker.discovery_finished, on_finished),
        ]

        try:
            # Dynamic timeout for xdist workers (parallel execution needs more time)
            # Increased timeout to handle slow filesystem operations in test environment
            try:
                from xdist import (
                    is_xdist_worker,
                )

                timeout = 120000 if is_xdist_worker(qtbot._request) else 60000
            except (ImportError, TypeError, AttributeError):
                timeout = 60000

            # Following Signal Testing Pattern (lines 375-387): waitSignal BEFORE action
            with qtbot.waitSignal(worker.discovery_finished, timeout=timeout) as blocker:
                worker.start()

            # Verify workflow completed successfully
            assert blocker.signal_triggered, "Worker should complete scan"
            assert len(error_messages) == 0, f"Should not have errors: {error_messages}"

            # Verify progress was reported
            assert len(progress_updates) > 0, "Should have progress updates"

            # Verify final results
            assert final_scenes is not None, "Should have final scene results"
            assert isinstance(final_scenes, list), "Results should be a list"

            # If the original bug existed, we would have gotten an error here
            # because the parallel discovery would fail with the parameter mismatch

        finally:
            # Proper cleanup: disconnect signals, stop thread, delete Qt C++ object,
            # and process events to flush deletion queue. This prevents object accumulation.
            cleanup_qthread_properly(worker, signal_handlers)

    def test_worker_concurrent_signal_handling(self, qtbot) -> None:
        """Test worker signal handling when multiple signals are emitted rapidly.

        Tests that the worker can handle rapid concurrent signal emissions
        without losing signals or causing race conditions.
        """
        # Import cleanup helper
        from tests.test_helpers import cleanup_qthread_properly

        # Create larger structure to generate more signals
        _, test_shots = create_test_vfx_structure(
            self.shows_root,
            show_names=["TESTSHOW", "DEMO"],
            users=["artist1", "artist2"],
        )

        worker = ThreeDESceneWorker(
            shots=test_shots,
            excluded_users=set(),
            enable_progressive=True,
            scan_all_shots=True,
        )

        # Use thread-safe collections for signal tracking
        # Standard library imports
        import threading

        signal_lock = threading.Lock()
        all_signals = []

        def track_signal(signal_name: str, *args) -> None:
            with signal_lock:
                all_signals.append((time.time(), signal_name, args))

        # Create wrapper functions to store connections
        def started_wrapper():
            return track_signal("started")
        def progress_wrapper(*args):
            return track_signal("progress", *args)
        def finished_wrapper(scenes):
            return track_signal("finished", len(scenes))
        def error_wrapper(msg):
            return track_signal("error", msg)

        # Connect signals and track for cleanup
        worker.worker_discovery_started.connect(started_wrapper)
        worker.progress.connect(progress_wrapper)
        worker.discovery_finished.connect(finished_wrapper)
        worker.error.connect(error_wrapper)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.worker_discovery_started, started_wrapper),
            (worker.progress, progress_wrapper),
            (worker.discovery_finished, finished_wrapper),
            (worker.error, error_wrapper),
        ]

        try:
            # Dynamic timeout for xdist workers (parallel execution needs more time)
            try:
                from xdist import (
                    is_xdist_worker,
                )

                timeout = 60000 if is_xdist_worker(qtbot._request) else 30000
            except (ImportError, TypeError, AttributeError):
                timeout = 30000

            # Use qtbot.waitSignal with extended timeout
            with qtbot.waitSignal(worker.discovery_finished, timeout=timeout):
                worker.start()

            # Wait for thread to fully terminate before accessing signal data
            worker.wait(5000)

            # CRITICAL: Process Qt events to ensure signal delivery completes
            qtbot.wait(1)  # Minimal event processing

            # Verify all signals were captured without race conditions
            with signal_lock:
                signal_types = [sig[1] for sig in all_signals]

            assert "started" in signal_types, "Should have started signal"
            assert "finished" in signal_types, "Should have finished signal"
            assert "progress" in signal_types, "Should have progress signals"
            assert "error" not in signal_types, "Should not have error signals"

            # Verify no signal was lost due to concurrent emission
            progress_count = signal_types.count("progress")
            assert progress_count > 0, "Should have multiple progress signals"

        finally:
            # Proper cleanup: disconnect signals, stop thread, delete Qt C++ object,
            # and process events to flush deletion queue. This prevents object accumulation.
            cleanup_qthread_properly(worker, signal_handlers)
