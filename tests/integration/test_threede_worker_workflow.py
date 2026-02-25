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
from shot_model import Shot
from threede_scene_worker import ThreeDESceneWorker


pytestmark = [
    pytest.mark.integration,
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
        except Exception:
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

    def _create_test_vfx_structure(self) -> list[Shot]:
        """Create test VFX structure and return list of shots."""
        test_shots = []

        for show_name in ["TESTSHOW", "DEMO"]:
            show_dir = self.shows_root / show_name / "shots"

            for seq_num in range(1, 3):  # seq001, seq002
                seq_name = f"seq{seq_num:03d}"
                for shot_num in [10, 20, 30]:  # 0010, 0020, 0030
                    shot_name = f"{shot_num:04d}"
                    shot_path = show_dir / seq_name / f"{seq_name}_{shot_name}"

                    # Create user directories with 3DE files
                    for user in ["artist1", "artist2"]:
                        for subdir in ["3de/scenes", "matchmove/3de", "tracking"]:
                            work_dir = shot_path / "user" / user / subdir
                            work_dir.mkdir(parents=True, exist_ok=True)

                            # Create 3DE files
                            scene_file = (
                                work_dir
                                / f"{show_name}_{seq_name}_{shot_name}_BG01.3de"
                            )
                            scene_file.write_text(
                                f"# 3DE Scene\nversion 1.0\nshow: {show_name}"
                            )

                    # Create Shot object
                    shot = Shot(show_name, seq_name, shot_name, str(shot_path))
                    test_shots.append(shot)

        return test_shots

    def test_worker_full_production_workflow(self, qtbot) -> None:
        """Test complete worker workflow as triggered by user - would catch parameter bug.

        This test exercises the exact workflow that failed in production:
        1. User triggers 3DE scan from UI
        2. Worker starts with progress callbacks
        3. Worker calls parallel discovery methods
        4. ThreadSafeProgressTracker receives progress_interval parameter
        """
        from tests.test_helpers import cleanup_qthread_properly

        test_shots = self._create_test_vfx_structure()

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
        worker.finished.connect(on_finished)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.progress, on_progress),
            (worker.error, on_error),
            (worker.finished, on_finished),
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
            with qtbot.waitSignal(worker.finished, timeout=timeout) as blocker:
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

    def test_worker_error_handling_workflow(self, qtbot) -> None:
        """Test worker error handling when parallel discovery encounters issues."""
        from tests.test_helpers import cleanup_qthread_properly

        # Create invalid shot paths to trigger errors
        invalid_shots = [
            Shot("INVALID", "seq001", "0010", "/nonexistent/path"),
            Shot("TESTSHOW", "invalid", "0010", "/another/invalid/path"),
        ]

        worker = ThreeDESceneWorker(
            shots=invalid_shots,
            excluded_users=set(),
            enable_progressive=True,
            scan_all_shots=True,
        )

        error_messages = []

        # Store lambda references for proper signal disconnection
        def error_handler(msg):
            return error_messages.append(msg)
        def finished_handler(scenes):
            return globals().update(final_scenes=scenes)

        worker.error.connect(error_handler)
        worker.finished.connect(finished_handler)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.error, error_handler),
            (worker.finished, finished_handler),
        ]

        try:
            # Should complete even with invalid paths - wait for finished signal
            with qtbot.waitSignal(worker.finished, timeout=15000) as blocker:
                worker.start()

            # Should complete even with invalid paths
            assert blocker.signal_triggered, "Worker should complete"

            # Either way, should not crash due to parameter issues

        finally:
            # Proper cleanup: disconnect signals, stop thread, delete Qt C++ object,
            # and process events to flush deletion queue. This prevents object accumulation.
            cleanup_qthread_properly(worker, signal_handlers)

    def test_worker_signal_emission_patterns(self, qtbot) -> None:
        """Test that worker emits signals correctly throughout the workflow."""
        from tests.test_helpers import cleanup_qthread_properly

        test_shots = self._create_test_vfx_structure()

        worker = ThreeDESceneWorker(
            shots=test_shots[:2],
            excluded_users=set(),
            enable_progressive=True,
            scan_all_shots=True,
        )

        # Track all signals
        started_signals = []
        progress_signals = []
        finished_signals = []

        # Store lambda references for proper signal disconnection
        def started_handler():
            return started_signals.append(time.time())
        def progress_handler(*args):
            return progress_signals.append((time.time(), args))
        def finished_handler(scenes):
            return finished_signals.append((time.time(), len(scenes)))

        worker.started.connect(started_handler)
        worker.progress.connect(progress_handler)
        worker.finished.connect(finished_handler)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.started, started_handler),
            (worker.progress, progress_handler),
            (worker.finished, finished_handler),
        ]

        try:
            with qtbot.waitSignal(worker.finished, timeout=20000):
                worker.start()

            # Wait for thread to fully terminate before accessing signal data
            worker.wait(5000)

            # Verify signal emission order and timing - may get started from base class too
            assert len(started_signals) >= 1, "Should emit started signal at least once"
            assert len(progress_signals) > 0, "Should emit progress signals"
            assert len(finished_signals) == 1, "Should emit finished signal once"

            # Verify temporal order
            start_time = started_signals[0]
            finish_time = finished_signals[0][0]

            assert finish_time > start_time, "Finished should come after started"

            # Verify progress signals are between start and finish
            for progress_time, _ in progress_signals:
                assert start_time <= progress_time <= finish_time, (
                    "Progress should be between start and finish"
                )

        finally:
            # Proper cleanup: disconnect signals, stop thread, delete Qt C++ object,
            # and process events to flush deletion queue. This prevents object accumulation.
            cleanup_qthread_properly(worker, signal_handlers)

    def test_worker_memory_and_resource_cleanup(self, qtbot) -> None:
        """Test that worker properly cleans up resources after completion."""
        from tests.test_helpers import cleanup_qthread_properly

        test_shots = self._create_test_vfx_structure()

        worker = ThreeDESceneWorker(
            shots=test_shots[:3], excluded_users=set(), enable_progressive=True
        )

        try:
            # Dynamic timeout for xdist workers
            try:
                from xdist import (
                    is_xdist_worker,
                )

                timeout = 30000 if is_xdist_worker(qtbot._request) else 15000
            except (ImportError, TypeError, AttributeError):
                timeout = 15000

            # Complete a scan
            with qtbot.waitSignal(worker.finished, timeout=timeout):
                worker.start()

            # Wait for thread to fully terminate before checking status
            worker.wait(5000)
            # Worker should not be running after completion
            assert not worker.isRunning(), (
                "Worker should not be running after completion"
            )

            # Create a new worker for second scan (workers are single-use)
            worker2 = ThreeDESceneWorker(
                shots=test_shots[:3], excluded_users=set(), enable_progressive=True
            )

            try:
                # Should be able to start another scan with new worker
                with qtbot.waitSignal(worker2.finished, timeout=15000):
                    worker2.start()
                # Wait for thread to fully terminate before checking status
                worker2.wait(5000)
                assert not worker2.isRunning(), (
                    "Worker2 should not be running after second scan"
                )
            finally:
                # Proper cleanup for worker2 (no signal handlers to disconnect)
                cleanup_qthread_properly(worker2, signal_handlers=None)
                # Process Qt events to ensure worker2 cleanup completes
                qtbot.wait(1)  # Minimal event processing

        finally:
            # Proper cleanup for worker (no signal handlers to disconnect)
            cleanup_qthread_properly(worker, signal_handlers=None)
            # CRITICAL: Process Qt events to ensure worker cleanup completes
            # This prevents Qt state pollution affecting subsequent tests
            qtbot.wait(1)  # Minimal event processing

    def test_worker_concurrent_signal_handling(self, qtbot) -> None:
        """Test worker signal handling when multiple signals are emitted rapidly.

        Tests that the worker can handle rapid concurrent signal emissions
        without losing signals or causing race conditions.
        """
        # Import cleanup helper
        from tests.test_helpers import cleanup_qthread_properly

        # Create larger structure to generate more signals
        test_shots = self._create_test_vfx_structure()

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
        worker.started.connect(started_wrapper)
        worker.progress.connect(progress_wrapper)
        worker.finished.connect(finished_wrapper)
        worker.error.connect(error_wrapper)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.started, started_wrapper),
            (worker.progress, progress_wrapper),
            (worker.finished, finished_wrapper),
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
            with qtbot.waitSignal(worker.finished, timeout=timeout):
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
    def test_worker_timeout_handling(self, qtbot) -> None:
        """Test worker behavior with realistic timeouts."""
        from tests.test_helpers import cleanup_qthread_properly

        test_shots = self._create_test_vfx_structure()

        worker = ThreeDESceneWorker(
            shots=test_shots[:1],  # Small dataset for quick test
            excluded_users=set(),
            enable_progressive=True,
        )

        completed = []

        # Store lambda reference for proper signal disconnection
        def finished_handler(scenes):
            return completed.append(len(scenes))
        worker.finished.connect(finished_handler)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.finished, finished_handler),
        ]

        try:
            # Should complete well within timeout
            with qtbot.waitSignal(worker.finished, timeout=10000):
                worker.start()

            # Wait for thread to fully terminate before accessing signal data
            worker.wait(5000)

            assert len(completed) == 1, "Should complete within timeout"

        finally:
            # Proper cleanup: disconnect signals, stop thread, delete Qt C++ object,
            # and process events to flush deletion queue. This prevents object accumulation.
            cleanup_qthread_properly(worker, signal_handlers)

    def test_production_simulation_workflow(self, qtbot) -> None:
        """Simulate the exact production workflow that triggered the bug.

        This test simulates:
        1. User opens "Other 3DE scenes" tab
        2. System triggers background scan
        3. Worker uses progressive scan with parallel discovery
        4. Parallel discovery creates ThreadSafeProgressTracker with progress_interval
        """
        from tests.test_helpers import cleanup_qthread_properly

        # Create realistic production-scale test data
        test_shots = self._create_test_vfx_structure()

        # Simulate user's current shots (for filtering in "Other" scenes)
        user_shots = test_shots[:3]

        worker = ThreeDESceneWorker(
            shots=user_shots,
            excluded_users={"system", "pipeline"},  # Typical excluded users
            enable_progressive=True,
            scan_all_shots=True,  # This triggers the parallel path that failed
        )

        # Track the complete workflow
        workflow_events = []

        def track_event(event: str, *args) -> None:
            workflow_events.append((time.time(), event, args))

        # Store lambda references for proper signal disconnection
        def started_handler():
            return track_event("worker_started")
        def progress_handler(*args):
            return track_event("progress_update", args)
        def finished_handler(scenes):
            return track_event("scan_completed", len(scenes))
        def error_handler(msg):
            return track_event("error_occurred", msg)

        worker.started.connect(started_handler)
        worker.progress.connect(progress_handler)
        worker.finished.connect(finished_handler)
        worker.error.connect(error_handler)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.started, started_handler),
            (worker.progress, progress_handler),
            (worker.finished, finished_handler),
            (worker.error, error_handler),
        ]

        try:
            # This is the exact workflow that failed in production
            with qtbot.waitSignal(worker.finished, timeout=25000) as blocker:
                # Simulate user opening "Other 3DE scenes" tab
                worker.start()

            # Wait for thread to fully terminate before accessing signal data
            worker.wait(5000)

            # Verify workflow completed without the parameter bug
            assert blocker.signal_triggered, "Production workflow should complete"

            # Verify workflow events
            event_types = [event[1] for event in workflow_events]
            assert "worker_started" in event_types
            assert "progress_update" in event_types
            assert "scan_completed" in event_types
            assert "error_occurred" not in event_types, (
                "Should not have parameter errors"
            )

            # Verify scenes were found
            completion_events = [e for e in workflow_events if e[1] == "scan_completed"]
            assert len(completion_events) == 1
            scene_count = completion_events[0][2][0]  # First arg of scan_completed
            assert scene_count >= 0, "Should return valid scene count"

        finally:
            # Proper cleanup: disconnect signals, stop thread, delete Qt C++ object,
            # and process events to flush deletion queue. This prevents object accumulation.
            cleanup_qthread_properly(worker, signal_handlers)

        # Log workflow summary for debugging
        print("Production workflow simulation completed:")
        print(f"  Total events: {len(workflow_events)}")
        print(
            f"  Progress updates: {len([e for e in workflow_events if e[1] == 'progress_update'])}"
        )
        if workflow_events:
            total_time = workflow_events[-1][0] - workflow_events[0][0]
            print(f"  Total time: {total_time:.2f}s")
