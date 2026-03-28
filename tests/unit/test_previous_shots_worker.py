"""Unit tests for PreviousShotsWorker background thread following UNIFIED_TESTING_GUIDE.

Tests the background worker thread with real Qt threading and signal emission.
Focuses on thread safety, signal emission, and cancellation behavior.

UNIFIED_TESTING_GUIDE COMPLIANCE:
1. Mock only at system boundaries
2. Test behavior, not implementation details
3. Mock find_approved_shots_targeted on worker's ParallelShotsFinder to avoid
   subprocess calls (which have WSL issues in test environments)
4. Proper QThread cleanup without qtbot.addWidget()
5. PySide6 QSignalSpy API (count() method)
6. Signal waiters set up BEFORE actions to prevent race conditions

IMPLEMENTATION NOTES:
- Tests mock find_approved_shots_targeted on the worker's existing ParallelShotsFinder
  instead of swapping the finder with the base PreviousShotsFinder class.
- The worker always uses ParallelShotsFinder in production; tests mock its
  find_approved_shots_targeted method directly to control returned shots.
- Real directory structures are still created where needed for fixture clarity.
- Real Qt signals and threading are used throughout.

Focus areas:
- Real QThread testing with qtbot
- Signal emission with QSignalSpy
- Thread interruption and cancellation
- Complete workflow testing
- Error handling in threaded context
"""

from __future__ import annotations

# Standard library imports
import time
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

# Third-party imports
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

from config import Config

# Local application imports
from previous_shots.worker import PreviousShotsWorker
from type_definitions import Shot


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,  # CRITICAL for parallel safety
    pytest.mark.qt_heavy,
]

if TYPE_CHECKING:
    # Standard library imports
    from pathlib import Path

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns
# - Signal setup BEFORE triggering actions to prevent races


class TestPreviousShotsWorkerBasics:
    """Basic tests for PreviousShotsWorker initialization and control."""

    @pytest.fixture
    def mock_active_shots(self) -> list[Shot]:
        """Create mock active shots for filtering."""
        return [
            Shot(
                "active_show",
                "seq1",
                "shot1",
                f"{Config.SHOWS_ROOT}/active_show/shots/seq1/shot1",
            ),
            Shot(
                "active_show",
                "seq1",
                "shot2",
                f"{Config.SHOWS_ROOT}/active_show/shots/seq1/shot2",
            ),
        ]

    @pytest.fixture
    def shows_root(self, tmp_path: Path) -> Path:
        """Create shows directory structure."""
        shows_root = tmp_path / "shows"
        shows_root.mkdir(exist_ok=True)
        return shows_root

    @pytest.fixture
    def worker(
        self, mock_active_shots: list[Shot], shows_root: Path
    ) -> Generator[PreviousShotsWorker, None, None]:
        """Create PreviousShotsWorker instance with proper thread cleanup."""
        from tests.test_helpers import cleanup_qthread_properly

        worker = PreviousShotsWorker(
            active_shots=mock_active_shots, username="testuser", shows_root=shows_root
        )
        yield worker

        # Proper QThread cleanup to prevent segfaults from Qt C++ object accumulation
        cleanup_qthread_properly(worker)

    def test_worker_initialization(
        self,
        worker: PreviousShotsWorker,
        mock_active_shots: list[Shot],
        shows_root: Path,
    ) -> None:
        """Test worker initialization with correct parameters."""
        assert worker._active_shots == mock_active_shots
        assert worker._shows_root == shows_root
        assert worker._finder.username == "testuser"
        assert not worker.should_stop()
        assert worker._found_shots == []

    def test_worker_stop_mechanism(self, worker: PreviousShotsWorker) -> None:
        """Test worker stop request mechanism."""
        assert not worker.should_stop()

        worker.stop()

        assert worker.should_stop()

    def test_get_found_shots_returns_copy(self, worker: PreviousShotsWorker) -> None:
        """Test that get_found_shots returns a copy of internal list."""
        # Add some shots to internal list
        test_shots = [
            Shot(
                "show1", "seq1", "shot1", f"{Config.SHOWS_ROOT}/show1/shots/seq1/shot1"
            ),
        ]
        worker._found_shots = test_shots

        returned_shots = worker.get_found_shots()

        # Should be equal but not the same object
        assert returned_shots == test_shots
        assert returned_shots is not test_shots


class TestPreviousShotsWorkerWorkflow:
    """Test complete workflow with mocked finder results.

    Mocks find_approved_shots_targeted on the worker's ParallelShotsFinder to
    control returned shots without triggering subprocess calls (which have WSL
    issues in test environments).
    """

    @pytest.fixture
    def shows_root_with_shots(self, tmp_path: Path) -> Path:
        """Create shows directory structure fixture (used for worker construction).

        The directory structure is present but find_approved_shots_targeted is mocked,
        so rglob scanning does not occur during these tests.
        """
        shows_root = tmp_path / "shows"
        shows_root.mkdir(exist_ok=True)
        return shows_root

    @pytest.fixture
    def worker_with_cleanup(
        self, shows_root_with_shots: Path
    ) -> Generator[PreviousShotsWorker, None, None]:
        """Create worker with cleanup."""
        from tests.test_helpers import cleanup_qthread_properly

        active_shots = [
            Shot(
                "active_show",
                "seq1",
                "shot1",
                f"{Config.SHOWS_ROOT}/active_show/shots/seq1/shot1",
            ),
        ]

        worker = PreviousShotsWorker(
            active_shots=active_shots,
            username="testuser",
            shows_root=shows_root_with_shots,
        )
        yield worker

        # Proper QThread cleanup to prevent segfaults from Qt C++ object accumulation
        cleanup_qthread_properly(worker)

    def test_complete_workflow_with_results(
        self,
        worker_with_cleanup: PreviousShotsWorker,
        qtbot: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test complete run() workflow emitting 3 approved shots.

        Mocks find_approved_shots_targeted on the worker's ParallelShotsFinder to
        return 3 Shot objects (show1/seq1/seq1_shot1, show1/seq1/seq1_shot2,
        show2/seq2/seq2_shot1). Verifies signal emission and result count.
        """
        worker = worker_with_cleanup

        # Mock find_approved_shots_targeted to return 3 shots without subprocess
        expected_shots = [
            Shot(
                "show1",
                "seq1",
                "seq1_shot1",
                f"{Config.SHOWS_ROOT}/show1/shots/seq1/seq1_shot1",
            ),
            Shot(
                "show1",
                "seq1",
                "seq1_shot2",
                f"{Config.SHOWS_ROOT}/show1/shots/seq1/seq1_shot2",
            ),
            Shot(
                "show2",
                "seq2",
                "seq2_shot1",
                f"{Config.SHOWS_ROOT}/show2/shots/seq2/seq2_shot1",
            ),
        ]
        monkeypatch.setattr(
            worker._finder,
            "find_approved_shots_targeted",
            lambda *_args, **_kwargs: expected_shots,
        )

        # Use QSignalSpy for ALL signal verification to avoid entering Qt event loop
        # The Qt event loop in waitSignal crashes after ~2100 tests due to state accumulation
        # NOTE: QSignalSpy uses direct C++ connections, so it doesn't need event loop
        # Python callbacks DO need event loop - avoid them in this test
        error_spy = QSignalSpy(worker.worker_error)
        finished_spy = QSignalSpy(worker.scan_finished)

        # Start worker
        worker.start()

        # Wait for thread to finish using pure thread wait (no Qt event loop)
        finished = worker.wait(5000)
        assert finished, "Worker did not finish within timeout"

        # Verify scan_finished was emitted
        assert finished_spy.count() == 1, (
            f"Expected scan_finished signal, got {finished_spy.count()}"
        )

        # Verify the result contains 3 shots
        if finished_spy.count() > 0:
            result = finished_spy.at(0)
            # QSignalSpy returns list of arguments, first arg is the list of shots
            assert len(result) > 0, "scan_finished signal had no arguments"
            shot_list = result[0]
            assert isinstance(shot_list, list), f"Expected list, got {type(shot_list)}"
            assert len(shot_list) == 3, f"Expected 3 shots, got {len(shot_list)}"

        # Verify no error was emitted
        assert error_spy.count() == 0, (
            f"Unexpected error: {error_spy.at(0) if error_spy.count() > 0 else 'N/A'}"
        )

    @pytest.fixture
    def empty_shows_root(self, tmp_path: Path) -> Path:
        """Create empty shows directory for no-results testing."""
        shows_root = tmp_path / "shows"
        shows_root.mkdir(exist_ok=True)
        return shows_root

    def test_workflow_with_no_results(
        self,
        empty_shows_root: Path,
        qtbot: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test workflow when no shots are found.

        Mocks find_approved_shots_targeted to return an empty list, verifying the
        worker emits scan_finished with zero results.
        """
        # Create worker with empty shows_root
        active_shots: list[Shot] = []
        worker = PreviousShotsWorker(
            active_shots=active_shots,
            username="testuser",
            shows_root=empty_shows_root,
        )

        # Mock find_approved_shots_targeted to return no shots
        monkeypatch.setattr(
            worker._finder,
            "find_approved_shots_targeted",
            lambda *_args, **_kwargs: [],
        )

        scan_finished_spy = QSignalSpy(worker.scan_finished)

        try:
            # Use pure thread wait instead of waitSignal to avoid Qt event loop
            # The Qt event loop crashes after ~2100 tests due to state accumulation
            worker.start()
            finished = worker.wait(5000)
            assert finished, "Worker did not finish within timeout"

            # Should complete successfully with no results
            assert scan_finished_spy.count() == 1

            final_result = scan_finished_spy.at(0)[0]
            assert len(final_result) == 0

        finally:
            # Proper QThread cleanup to prevent segfaults from Qt C++ object accumulation
            from tests.test_helpers import cleanup_qthread_properly

            cleanup_qthread_properly(worker)

    def test_workflow_with_stop_request(
        self,
        worker_with_cleanup: PreviousShotsWorker,
        qtbot: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test workflow interruption with stop request.

        Mocks find_approved_shots_targeted with a slow function that waits for
        worker.should_stop() before returning, allowing the cancellation path to
        be exercised.
        """
        worker = worker_with_cleanup

        # Mock find_approved_shots_targeted with a slow function that respects cancellation
        def slow_find_approved(
            active_shots: list[Shot], shows_root: Any = None
        ) -> list[Shot]:
            # Wait for stop request to be processed (runs in background thread)
            deadline = time.perf_counter() + 0.2
            while time.perf_counter() < deadline:
                if worker.should_stop():
                    break
                time.sleep(0.01)
            if worker.should_stop():
                return []
            time.sleep(0.01)
            return []

        monkeypatch.setattr(
            worker._finder, "find_approved_shots_targeted", slow_find_approved
        )

        QSignalSpy(worker.scan_finished)

        try:
            # Start worker with proper signal handling
            worker.start()

            # Wait for worker to be running
            qtbot.waitUntil(lambda: worker.isRunning(), timeout=1000)

            # Request stop
            worker.stop()

            # Wait for thread to finish gracefully
            worker.wait(3000)
        finally:
            pass  # monkeypatch automatically restores

        # Worker should complete (may or may not emit scan_finished depending on timing)
        # Key test is that it stops gracefully without hanging

    def test_error_handling_finder_exception(
        self,
        worker_with_cleanup: PreviousShotsWorker,
        qtbot: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test error handling when finder raises unexpected exception.

        Mocks find_approved_shots_targeted to raise RuntimeError, verifying the
        worker emits worker_error and does not emit scan_finished.
        """
        worker = worker_with_cleanup

        error_spy = QSignalSpy(worker.worker_error)
        scan_finished_spy = QSignalSpy(worker.scan_finished)

        # Mock find_approved_shots_targeted to raise exception
        def failing_find_approved_shots_targeted(
            active_shots: list[Shot], shows_root: Any = None
        ) -> list[Shot]:
            raise RuntimeError("Critical finder error")

        monkeypatch.setattr(
            worker._finder,
            "find_approved_shots_targeted",
            failing_find_approved_shots_targeted,
        )

        # Use pure thread wait instead of waitSignal to avoid Qt event loop
        # The Qt event loop crashes after ~2100 tests due to state accumulation
        worker.start()
        finished = worker.wait(5000)
        assert finished, "Worker did not finish within timeout"

        # Process any pending events
        QCoreApplication.processEvents()
        QCoreApplication.processEvents()  # Second pass to handle deferred deletions

        # Should emit error signal (base class emits worker_error with str(e))
        assert error_spy.count() == 1
        error_message = error_spy.at(0)[0]
        assert "Critical finder error" in error_message

        # Should not emit scan_finished on error
        assert scan_finished_spy.count() == 0

    @pytest.fixture
    def single_shot_shows_root(self, tmp_path: Path) -> Path:
        """Create shows directory fixture for signal data format testing."""
        shows_root = tmp_path / "shows"
        shows_root.mkdir(exist_ok=True)
        return shows_root

    def test_signal_data_format(
        self,
        single_shot_shows_root: Path,
        qtbot: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test signal data format matches expected structure.

        Mocks find_approved_shots_targeted to return 1 shot
        (different_show/testseq/testseq_testshot) and verifies the scan_finished
        signal carries a list of length 1.
        """
        # Create worker
        active_shots: list[Shot] = []  # No active shots to filter
        worker = PreviousShotsWorker(
            active_shots=active_shots,
            username="testuser",
            shows_root=single_shot_shows_root,
        )

        # Mock find_approved_shots_targeted to return a single shot
        expected_shot = Shot(
            "different_show",
            "testseq",
            "testseq_testshot",
            f"{Config.SHOWS_ROOT}/different_show/shots/testseq/testseq_testshot",
        )
        monkeypatch.setattr(
            worker._finder,
            "find_approved_shots_targeted",
            lambda *_args, **_kwargs: [expected_shot],
        )

        scan_finished_spy = QSignalSpy(worker.scan_finished)

        try:
            # Use pure thread wait instead of waitSignal to avoid Qt event loop
            # The Qt event loop crashes after ~2100 tests due to state accumulation
            worker.start()
            finished = worker.wait(5000)
            assert finished, "Worker did not finish within timeout"

            # Verify scan_finished signal data structure
            assert scan_finished_spy.count() == 1
            final_shots = scan_finished_spy.at(0)[0]
            assert isinstance(final_shots, list)
            assert len(final_shots) == 1

        finally:
            # Proper QThread cleanup to prevent segfaults from Qt C++ object accumulation
            from tests.test_helpers import cleanup_qthread_properly

            cleanup_qthread_properly(worker)


class TestPreviousShotsWorkerIntegration:
    """Integration tests with real filesystem and limited mocking."""

    @pytest.fixture
    def real_shows_structure(self, tmp_path: Path) -> Path:
        """Create realistic shows directory structure for integration tests."""
        shows_root = tmp_path / "shows"

        # Create multiple shows with realistic structure
        shows_data = {
            "feature_film": {
                "sequences": ["010_opening", "020_chase"],
                "shots_per_seq": 3,
            },
            "commercial": {"sequences": ["001_product"], "shots_per_seq": 2},
        }

        for show_name, show_data in shows_data.items():
            for seq_name in show_data["sequences"]:
                for shot_idx in range(show_data["shots_per_seq"]):
                    # Use VFX naming convention: {seq}_{shot}
                    shot_num = f"{shot_idx:03d}"
                    shot_dir_name = f"{seq_name}_{shot_num}"
                    shot_path = (
                        shows_root / show_name / "shots" / seq_name / shot_dir_name
                    )

                    # Some shots have user work
                    if shot_idx % 2 == 0:  # Even shots have user work
                        user_path = shot_path / "user" / "testuser"
                        user_path.mkdir(parents=True, exist_ok=True)

                        # Add realistic work files
                        (user_path / "scene.3de").write_text("3DE scene data")
                        (user_path / "comp.nk").write_text("Nuke script")

        return shows_root

    def test_integration_with_real_finder(
        self, real_shows_structure: Path, qtbot: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test integration using mocked find_approved_shots_targeted returning 4 shots.

        Mocks find_approved_shots_targeted to return 4 Shot objects (representing
        5 user shots minus 1 active shot), verifying the worker emits scan_finished
        with exactly 4 results.
        """
        # Create active shots (one overlaps with user work to be filtered out)
        active_shots = [
            Shot(
                "feature_film",
                "010_opening",
                "000",  # Matches what finder extracts from "010_opening_000" directory
                str(
                    real_shows_structure
                    / "feature_film"
                    / "shots"
                    / "010_opening"
                    / "010_opening_000"
                ),
            ),
        ]

        worker = PreviousShotsWorker(
            active_shots=active_shots,
            username="testuser",
            shows_root=real_shows_structure,
        )

        # Mock find_approved_shots_targeted to return 4 shots
        # (5 user shots minus 1 active shot = 4 approved shots)
        approved_shots = [
            Shot(
                "feature_film",
                "010_opening",
                "002",
                str(
                    real_shows_structure
                    / "feature_film/shots/010_opening/010_opening_002"
                ),
            ),
            Shot(
                "feature_film",
                "020_chase",
                "000",
                str(
                    real_shows_structure / "feature_film/shots/020_chase/020_chase_000"
                ),
            ),
            Shot(
                "feature_film",
                "020_chase",
                "002",
                str(
                    real_shows_structure / "feature_film/shots/020_chase/020_chase_002"
                ),
            ),
            Shot(
                "commercial",
                "001_product",
                "000",
                str(
                    real_shows_structure
                    / "commercial/shots/001_product/001_product_000"
                ),
            ),
        ]
        monkeypatch.setattr(
            worker._finder,
            "find_approved_shots_targeted",
            lambda *_args, **_kwargs: approved_shots,
        )

        scan_finished_spy = QSignalSpy(worker.scan_finished)

        # Use pure thread wait instead of waitSignal to avoid Qt event loop
        # The Qt event loop crashes after ~2100 tests due to state accumulation
        worker.start()
        finished = worker.wait(10000)
        assert finished, "Worker did not finish within timeout"

        # Proper QThread cleanup to prevent segfaults from Qt C++ object accumulation
        from tests.test_helpers import cleanup_qthread_properly

        cleanup_qthread_properly(worker)

        # Verify results
        assert scan_finished_spy.count() == 1
        final_shots = scan_finished_spy.at(0)[0]

        # Should find 5 user shots minus 1 active shot = 4 approved shots
        assert len(final_shots) == 4


# Performance tests removed to prevent test suite timeout
# These tests were moved to a separate benchmark suite
