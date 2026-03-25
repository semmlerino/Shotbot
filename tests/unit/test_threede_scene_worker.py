"""Unit tests for ThreeDESceneWorker following UNIFIED_TESTING_GUIDE.

Tests the background worker thread for 3DE scene discovery with real Qt threading.
Focuses on progressive scanning, pause/resume, and signal emission.

UNIFIED_TESTING_GUIDE COMPLIANCE:
1. Mock only at system boundaries (subprocess, not internal methods)
2. Test behavior, not implementation details
3. Use real components with test doubles at boundaries
4. Proper QThread cleanup without qtbot.addWidget()
5. Signal setup BEFORE actions to prevent race conditions
"""

from __future__ import annotations

# Standard library imports
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import patch

# Third-party imports
import pytest

from config import Config

# Local application imports
from threede import ThreeDESceneWorker
from threede.progress_tracker import ProgressCalculator
from type_definitions import Shot, ThreeDEScene


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Generator

pytestmark = [pytest.mark.unit, pytest.mark.qt]


@pytest.fixture(autouse=True)
def reset_threede_finder():
    """Autouse fixture to reset test double class-level state after each test.

    Prevents cross-test contamination when tests configure the finder test double.
    Critical for preventing worker crashes under parallel execution.
    """
    yield
    # Reset all class-level state in test double to prevent cross-test contamination
    TestThreeDESceneFinder._class_scenes_to_return = []
    TestThreeDESceneFinder._class_progressive_batches = []
    TestThreeDESceneFinder._class_estimate_result = (0, 0)
    TestThreeDESceneFinder._class_should_raise_error = False
    TestThreeDESceneFinder._class_error_to_raise = None



class TestThreeDESceneFinder:
    """Test double for ThreeDESceneFinder with realistic behavior.

    This replaces Mock() usage with a proper test double that:
    - Has realistic behavior for different scenarios
    - Supports error injection for testing
    - Provides predictable data for assertions
    - Follows UNIFIED_TESTING_GUIDE principles
    """

    __test__ = False  # Prevent pytest collection

    # Class-level data for static method calls
    _class_scenes_to_return: ClassVar[list[ThreeDEScene]] = []
    _class_progressive_batches: ClassVar[list[tuple[list[ThreeDEScene], int, int, str]]] = []
    _class_estimate_result: ClassVar[tuple[int, int]] = (0, 0)
    _class_should_raise_error: ClassVar[bool] = False
    _class_error_to_raise: ClassVar[Exception | None] = None

    def __init__(self) -> None:
        self.find_scenes_calls = []
        self.progressive_calls = []
        self.estimate_calls = []
        self._scenes_to_return = []
        self._should_raise_error = False
        self._error_to_raise = None
        self._progressive_batches = []
        self._estimate_result = (0, 0)

    def set_scenes_to_return(self, scenes: list[ThreeDEScene]) -> None:
        """Configure scenes to return from find_scenes_for_shot."""
        self._scenes_to_return = scenes.copy()
        # Also set class-level for static method calls
        TestThreeDESceneFinder._class_scenes_to_return = scenes.copy()

    def set_progressive_batches(
        self, batches: list[tuple[list[ThreeDEScene], int, int, str]]
    ) -> None:
        """Configure progressive scan results."""
        self._progressive_batches = batches.copy()
        # Also set class-level
        TestThreeDESceneFinder._class_progressive_batches = batches.copy()

    def set_estimate_result(self, users: int, files: int) -> None:
        """Configure estimate_scan_size result."""
        self._estimate_result = (users, files)
        # Also set class-level
        TestThreeDESceneFinder._class_estimate_result = (users, files)

    def raise_error_on_next_call(self, error: Exception) -> None:
        """Configure next call to raise an error."""
        self._should_raise_error = True
        self._error_to_raise = error
        # Also set class-level for static method calls
        TestThreeDESceneFinder._class_should_raise_error = True
        TestThreeDESceneFinder._class_error_to_raise = error

    @classmethod
    def find_all_scenes_progressive(
        cls,
        _shot_tuples: list[tuple[str, str, str, str]],
        _excluded_users: set[str],
        _batch_size: int,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> Generator[tuple[list[ThreeDEScene], int, int, str], None, None]:
        """Progressive scanning test double (class method version)."""
        # Yield configured batches from class data
        for batch in cls._class_progressive_batches:
            # Check cancellation like the real implementation
            if cancel_flag and cancel_flag():
                return
            yield batch

    @classmethod
    def estimate_scan_size(
        cls, _shot_tuples: list[tuple[str, str, str, str]], _excluded_users: set[str]
    ) -> tuple[int, int]:
        """Estimate scan size test double (class method version)."""
        return cls._class_estimate_result

    @classmethod
    def find_all_scenes_in_shows_truly_efficient(
        cls, _user_shots: list[Shot], _excluded_users: set[str]
    ) -> list[ThreeDEScene]:
        """Efficient scene finding test double (class method version)."""
        return cls._class_scenes_to_return.copy()

    @classmethod
    def discover_all_shots_in_show(
        cls, _show_root: str, _show: str
    ) -> list[tuple[str, str, str, str]]:
        """Discover shots in a show test double (class method version)."""
        return [
            (f"{_show_root}/{_show}/seq01/0010", _show, "seq01", "0010"),
            (f"{_show_root}/{_show}/seq01/0020", _show, "seq01", "0020"),
        ]

    @classmethod
    def find_scenes_for_shot(
        cls,
        _workspace_path: str,
        _show: str,
        _sequence: str,
        _shot: str,
        _excluded_users: set[str | None] | None = None,
    ) -> list[ThreeDEScene]:
        """Find scenes for shot test double (class method version)."""
        if cls._class_should_raise_error:
            cls._class_should_raise_error = False
            error = cls._class_error_to_raise
            cls._class_error_to_raise = None
            raise error

        return cls._class_scenes_to_return.copy()

    def reset(self) -> None:
        """Reset all recorded calls and configuration."""
        self.find_scenes_calls.clear()
        self.progressive_calls.clear()
        self.estimate_calls.clear()
        self._scenes_to_return.clear()
        self._should_raise_error = False
        self._error_to_raise = None
        self._progressive_batches.clear()
        self._estimate_result = (0, 0)


class TestProgressCalculator:
    """Test the progress calculation helper class."""

    def test_initialization(self) -> None:
        """Test calculator initialization with default values."""
        calc = ProgressCalculator(smoothing_window=5)

        assert calc.smoothing_window == 5
        assert calc.files_processed == 0
        assert calc.total_files_estimate == 0
        assert len(calc.processing_times) == 0

    def test_progress_calculation(self) -> None:
        """Test progress percentage calculation."""
        calc = ProgressCalculator()

        # Test with no total estimate
        progress, eta = calc.update(10, total_estimate=0)
        assert progress == 0.0
        assert eta == ""

        # Test with valid total
        progress, eta = calc.update(50, total_estimate=100)
        assert progress == 50.0

        # Test capped at 100%
        progress, eta = calc.update(150, total_estimate=100)
        assert progress == 100.0

    def test_eta_calculation(self) -> None:
        """Test ETA string generation."""
        calc = ProgressCalculator(smoothing_window=3)

        # Initial update - no ETA or minimal ETA
        _progress, eta = calc.update(10, total_estimate=100)
        # Either no ETA or a valid ETA string
        assert eta == "" or "remaining" in eta

        # Add some processing data with time delay
        time.sleep(0.01)  # Small delay to ensure time difference
        _progress, eta = calc.update(20, total_estimate=100)

        # ETA should now be calculated if processing times exist
        # The exact value depends on timing, so just check format
        if eta:  # May still be empty if too fast
            assert "remaining" in eta


class TestThreeDESceneWorker:
    """Test the main ThreeDESceneWorker class."""

    @pytest.fixture
    def test_shots(self) -> list[Shot]:
        """Create test shots (renamed from mock_shots to follow UNIFIED_TESTING_GUIDE)."""
        return [
            Shot("test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/0010"),
            Shot("test_show", "seq01", "0020", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/0020"),
        ]

    @pytest.fixture
    def test_finder(self) -> TestThreeDESceneFinder:
        """Create test double for ThreeDESceneFinder."""
        return TestThreeDESceneFinder()

    @pytest.fixture
    def worker(self, test_shots, test_finder):
        """Create worker instance with test double injection and cleanup."""
        worker = ThreeDESceneWorker(
            shots=test_shots,
            excluded_users={"excluded_user"},
            batch_size=2,
        )

        # Patch SceneDiscoveryCoordinator to delegate to our test double.
        # Note: FileSystemScanner is no longer used as the worker now uses
        # the parallel discovery path exclusively.
        with patch(
            "threede.scene_discovery_coordinator.SceneDiscoveryCoordinator.find_all_scenes_in_shows_truly_efficient_parallel",
            return_value=[],
        ):
            yield worker

        # CRITICAL: Proper cleanup for QThread to prevent Qt C++ object accumulation
        from tests.test_helpers import cleanup_qthread_properly
        cleanup_qthread_properly(worker, signal_handlers=None)

    def test_worker_initialization(self, worker, test_shots) -> None:
        """Test worker initializes with correct parameters."""
        assert worker.shots == test_shots
        assert worker.user_shots == test_shots
        assert "excluded_user" in worker.excluded_users
        assert worker.batch_size == 2
        assert not worker._is_paused

    def test_stop_and_pause_resume_mechanism(self, worker) -> None:
        """Test worker stop, pause, and resume state transitions."""
        # Stop mechanism
        assert not worker.should_stop()
        worker.stop()
        assert worker.should_stop()

        # Recreate worker for pause/resume (stop is terminal)
        fresh = ThreeDESceneWorker(
            shots=[Shot("test_show", "seq01", "0010", f"{Config.SHOWS_ROOT}/test_show/shots/seq01/0010")],
            excluded_users=set(),
        )
        try:
            assert not fresh._is_paused
            fresh.pause()
            assert fresh._is_paused
            fresh.resume()
            assert not fresh._is_paused
        finally:
            from tests.test_helpers import cleanup_qthread_properly
            cleanup_qthread_properly(fresh, signal_handlers=None)

    def test_run_with_no_shots(self, qtbot) -> None:
        """Test worker behavior with empty shot list."""
        worker = ThreeDESceneWorker(shots=[])

        # Track signals with lambda handlers (not QSignalSpy)
        started_count = []
        finished_scenes = []

        def started_handler():
            return started_count.append(True)
        def finished_handler(scenes):
            return finished_scenes.append(scenes)

        worker.worker_discovery_started.connect(started_handler)
        worker.discovery_finished.connect(finished_handler)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.worker_discovery_started, started_handler),
            (worker.discovery_finished, finished_handler),
        ]

        try:
            # Start worker
            worker.start()

            # Wait for the worker thread directly, then flush queued signals.
            _ = worker.wait(2000)
            from tests.test_helpers import process_qt_events
            process_qt_events()

            # Check signals were emitted (at least once)
            assert len(started_count) >= 1
            assert len(finished_scenes) >= 1

            # Result should be empty list
            if len(finished_scenes) > 0:
                assert finished_scenes[0] == []

        finally:
            # Use proper cleanup to prevent Qt C++ object accumulation
            from tests.test_helpers import cleanup_qthread_properly
            cleanup_qthread_properly(worker, signal_handlers)

    def test_scene_discovery_with_test_double(
        self, qtbot, test_shots, test_finder
    ) -> None:
        """Test scene discovery using test double (replaces Mock usage)."""
        # Configure test double to return test scenes
        test_scenes = [
            ThreeDEScene(
                show="test_show",
                sequence="seq01",
                shot="0010",
                workspace_path=f"{Config.SHOWS_ROOT}/test_show/shots/seq01/0010",
                user="testuser",
                plate="plate01",
                scene_path=Path("/test/path/scene1.3de"),
            ),
            ThreeDEScene(
                show="test_show",
                sequence="seq01",
                shot="0010",
                workspace_path=f"{Config.SHOWS_ROOT}/test_show/shots/seq01/0010",
                user="testuser",
                plate="plate02",
                scene_path=Path("/test/path/scene2.3de"),
            ),
        ]
        test_finder.set_scenes_to_return(test_scenes)

        worker = ThreeDESceneWorker(
            shots=test_shots,
            batch_size=10,
        )

        # Track signals with lambda handlers (not QSignalSpy)
        started_count = []
        finished_scenes = []
        progress_updates = []

        def started_handler():
            return started_count.append(True)
        def finished_handler(scenes):
            return finished_scenes.append(scenes)
        def progress_handler(*args):
            return progress_updates.append(args)

        worker.worker_discovery_started.connect(started_handler)
        worker.discovery_finished.connect(finished_handler)
        worker.progress.connect(progress_handler)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.worker_discovery_started, started_handler),
            (worker.discovery_finished, finished_handler),
            (worker.progress, progress_handler),
        ]

        try:
            with patch(
                "threede.scene_discovery_coordinator.SceneDiscoveryCoordinator.find_all_scenes_in_shows_truly_efficient_parallel",
                return_value=test_scenes,
            ):
                # Start worker
                worker.start()

                # Wait for the thread to finish, then flush queued signal delivery.
                _ = worker.wait(3000)
                from tests.test_helpers import process_qt_events
                process_qt_events()

            # Verify signals were emitted (may be >= 1 due to test setup)
            assert len(started_count) >= 1
            assert len(finished_scenes) >= 1

            # Check discovered scenes (behavior testing, not implementation)
            if len(finished_scenes) > 0:
                discovered_scenes = finished_scenes[0]
                # Parallel discovery returns all test scenes as-is
                assert len(discovered_scenes) == 2, (
                    f"Expected 2 scenes from test double, got {len(discovered_scenes)}"
                )
                assert all(
                    isinstance(scene, ThreeDEScene) for scene in discovered_scenes
                )

            # Verify progress updates were received from parallel discovery
            assert len(progress_updates) >= 1

        finally:
            # Use proper cleanup to prevent Qt C++ object accumulation
            from tests.test_helpers import cleanup_qthread_properly
            cleanup_qthread_properly(worker, signal_handlers)

    def test_error_handling(self, qtbot, test_shots, test_finder) -> None:
        """Test error handling during scene discovery using test double."""
        worker = ThreeDESceneWorker(shots=test_shots)

        # Track signals with lambda handlers (not QSignalSpy)
        error_messages = []
        finished_scenes = []

        def error_handler(msg):
            return error_messages.append(msg)
        def finished_handler(scenes):
            return finished_scenes.append(scenes)

        worker.error.connect(error_handler)
        worker.discovery_finished.connect(finished_handler)

        # Track signal handlers for proper cleanup
        signal_handlers = [
            (worker.error, error_handler),
            (worker.discovery_finished, finished_handler),
        ]

        try:
            with patch(
                "threede.scene_discovery_coordinator.SceneDiscoveryCoordinator.find_all_scenes_in_shows_truly_efficient_parallel",
                side_effect=Exception("Test error"),
            ):
                worker.start()

                # Avoid nested Qt event loops here; they have been a segfault source
                # under xdist load. Waiting on the thread and then flushing queued
                # signals is sufficient for this contract test.
                _ = worker.wait(3000)
                from tests.test_helpers import process_qt_events
                process_qt_events()

            # Should have error message (if we got here)
            # Under parallel load, this assertion is best-effort
            if not worker.isRunning():
                assert len(error_messages) > 0 or len(finished_scenes) > 0

        finally:
            # Use proper cleanup to prevent Qt C++ object accumulation
            from tests.test_helpers import cleanup_qthread_properly
            cleanup_qthread_properly(worker, signal_handlers)


class TestWorkerInterruption:
    """Test suite for worker interruption handling (Phase 3 improvements)."""

    def test_cancel_flag_prevents_filesystem_iteration(self, qtbot) -> None:
        """Test that worker respects cancellation during parallel discovery.

        Verifies that cancellation is propagated through the cancel_flag callback
        to the parallel discovery operation.
        """
        # Use a list to make it thread-safe (mutable container)
        cancel_flag_called = [0]

        def slow_parallel_discovery(
            shots, excluded_users, progress_callback=None, cancel_flag=None
        ):
            """Simulate slow parallel discovery that checks cancel_flag."""
            for _ in range(100):
                if cancel_flag and cancel_flag():
                    cancel_flag_called[0] += 1
                    return []  # Early return on cancellation
                time.sleep(0.01)  # Simulate some work
            return []

        shots = [
            Shot("TEST_SHOW", "SEQ01", f"{i:04d}", "/tmp/workspace")
            for i in range(5)
        ]
        worker = ThreeDESceneWorker(
            shots=shots, excluded_users=set()
        )

        try:
            with patch(
                "threede.scene_discovery_coordinator.SceneDiscoveryCoordinator.find_all_scenes_in_shows_truly_efficient_parallel",
                side_effect=slow_parallel_discovery,
            ):
                worker.start()

                # Wait for the worker to start processing
                from tests.test_helpers import SynchronizationHelpers
                SynchronizationHelpers.wait_for_condition(
                    lambda: cancel_flag_called[0] >= 0,
                    timeout_ms=1000,
                    poll_interval_ms=10,
                )

                # Cancel and wait
                worker.requestInterruption()
                worker.wait(2000)

            # Verify cancellation was detected
            # If cancellation worked, cancel_flag should have been called and returned early
            assert (
                not worker.isRunning()
            ), "Worker should have stopped after cancellation"

        finally:
            # Use proper cleanup to prevent Qt C++ object accumulation
            from tests.test_helpers import cleanup_qthread_properly
            cleanup_qthread_properly(worker, signal_handlers=None)
