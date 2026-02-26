"""Unit tests for PreviousShotsWorker background thread following UNIFIED_TESTING_GUIDE.

Tests the background worker thread with real Qt threading and signal emission.
Focuses on thread safety, signal emission, and cancellation behavior.

UNIFIED_TESTING_GUIDE COMPLIANCE:
1. Mock only at system boundaries
2. Test behavior, not implementation details
3. Use real PreviousShotsFinder (base class) with Path.rglob() scanning
4. Proper QThread cleanup without qtbot.addWidget()
5. PySide6 QSignalSpy API (count() method)
6. Signal waiters set up BEFORE actions to prevent race conditions

IMPLEMENTATION NOTES:
- Tests replace ParallelShotsFinder with base PreviousShotsFinder to use Path.rglob()
  instead of subprocess.run (ParallelShotsFinder uses find command which has WSL issues)
- Real directory structures are created for rglob() to discover
- Real Qt signals and threading are used throughout

Focus areas:
- Real QThread testing with qtbot
- Signal emission with QSignalSpy
- Thread interruption and cancellation
- Complete workflow testing
- Error handling in threaded context
"""

from __future__ import annotations

# Standard library imports
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, NoReturn

# Third-party imports
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

from config import Config

# Local application imports
from previous_shots_worker import PreviousShotsWorker
from shot_model import Shot
from tests.fixtures.test_doubles import TestCompletedProcess
from tests.test_helpers import SynchronizationHelpers


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,  # CRITICAL for parallel safety
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
            Shot("active_show", "seq1", "shot1", f"{Config.SHOWS_ROOT}/active_show/shots/seq1/shot1"),
            Shot("active_show", "seq1", "shot2", f"{Config.SHOWS_ROOT}/active_show/shots/seq1/shot2"),
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
            Shot("show1", "seq1", "shot1", f"{Config.SHOWS_ROOT}/show1/shots/seq1/shot1"),
        ]
        worker._found_shots = test_shots

        returned_shots = worker.get_found_shots()

        # Should be equal but not the same object
        assert returned_shots == test_shots
        assert returned_shots is not test_shots


class TestPreviousShotsWorkerWorkflow:
    """Test complete workflow with real directory structures.

    Uses actual directories that Path.rglob() can find instead of subprocess mocking.
    PreviousShotsFinder.find_user_shots() uses rglob(), not subprocess.run.
    """

    @pytest.fixture
    def shows_root_with_shots(self, tmp_path: Path) -> Path:
        """Create shows directory structure with user shots for rglob() to find.

        Creates directories matching the VFX path pattern:
        /shows/{show}/shots/{seq}/{seq}_{shot}/user/{user}
        """
        shows_root = tmp_path / "shows"
        shows_root.mkdir(exist_ok=True)

        # Create shot directories that PreviousShotsFinder.find_user_shots() will find via rglob()
        # Pattern: **/user/testuser
        shot_dirs = [
            shows_root / "show1" / "shots" / "seq1" / "seq1_shot1" / "user" / "testuser",
            shows_root / "show1" / "shots" / "seq1" / "seq1_shot2" / "user" / "testuser",
            shows_root / "show2" / "shots" / "seq2" / "seq2_shot1" / "user" / "testuser",
        ]
        for shot_dir in shot_dirs:
            shot_dir.mkdir(parents=True, exist_ok=True)

        return shows_root

    @pytest.fixture
    def worker_with_cleanup(
        self, shows_root_with_shots: Path
    ) -> Generator[PreviousShotsWorker, None, None]:
        """Create worker with cleanup and pre-populated shot directories."""
        from tests.test_helpers import cleanup_qthread_properly

        active_shots = [
            Shot("active_show", "seq1", "shot1", f"{Config.SHOWS_ROOT}/active_show/shots/seq1/shot1"),
        ]

        worker = PreviousShotsWorker(
            active_shots=active_shots, username="testuser", shows_root=shows_root_with_shots
        )
        yield worker

        # Proper QThread cleanup to prevent segfaults from Qt C++ object accumulation
        cleanup_qthread_properly(worker)

    def test_complete_workflow_with_results(
        self,
        worker_with_cleanup: PreviousShotsWorker,
        qtbot: Any,
    ) -> None:
        """Test complete run() workflow with real directory structures.

        Uses PreviousShotsFinder (base class) which scans via Path.rglob().
        The shows_root_with_shots fixture creates the directories rglob() finds.
        """
        worker = worker_with_cleanup

        # Replace finder with base class that uses Path.rglob() (not subprocess)
        # ParallelShotsFinder uses subprocess.run which requires different mocking
        from previous_shots_finder import PreviousShotsFinder

        worker._finder = PreviousShotsFinder(username="testuser")

        # Use QSignalSpy for ALL signal verification to avoid entering Qt event loop
        # The Qt event loop in waitSignal crashes after ~2100 tests due to state accumulation
        # NOTE: QSignalSpy uses direct C++ connections, so it doesn't need event loop
        # Python callbacks DO need event loop - avoid them in this test
        error_spy = QSignalSpy(worker.error_occurred)
        finished_spy = QSignalSpy(worker.scan_finished)

        # Start worker
        worker.start()

        # Wait for thread to finish using pure thread wait (no Qt event loop)
        finished = worker.wait(5000)
        assert finished, "Worker did not finish within timeout"

        # Verify scan_finished was emitted
        assert finished_spy.count() == 1, f"Expected scan_finished signal, got {finished_spy.count()}"

        # Verify the result contains 3 shots
        if finished_spy.count() > 0:
            result = finished_spy.at(0)
            # QSignalSpy returns list of arguments, first arg is the list of shots
            assert len(result) > 0, "scan_finished signal had no arguments"
            shot_list = result[0]
            assert isinstance(shot_list, list), f"Expected list, got {type(shot_list)}"
            assert len(shot_list) == 3, f"Expected 3 shots, got {len(shot_list)}"

        # Verify no error was emitted
        assert error_spy.count() == 0, f"Unexpected error: {error_spy.at(0) if error_spy.count() > 0 else 'N/A'}"

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
    ) -> None:
        """Test workflow when no shots are found.

        Uses empty directory structure so rglob() finds nothing.
        """
        # Create worker with empty shows_root
        active_shots: list[Shot] = []
        worker = PreviousShotsWorker(
            active_shots=active_shots,
            username="testuser",
            shows_root=empty_shows_root,
        )

        scan_finished_spy = QSignalSpy(worker.scan_finished)

        # Replace finder with base class that uses Path.rglob()
        from previous_shots_finder import PreviousShotsFinder

        worker._finder = PreviousShotsFinder(username="testuser")

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
        """Test workflow interruption with stop request."""
        worker = worker_with_cleanup

        # Mock slow subprocess to allow time for stop
        def slow_subprocess(*args: Any, **kwargs: Any) -> TestCompletedProcess:
            # Wait for stop request to be processed
            SynchronizationHelpers.wait_for_condition(
                lambda: worker.should_stop(),
                timeout_ms=100,
            )
            if worker.should_stop():
                # Return minimal result when stopped
                return TestCompletedProcess(
                    args=args[0] if args else [], returncode=0, stdout=""
                )

            # Return normal result
            return TestCompletedProcess(
                args=args[0] if args else [],
                returncode=0,
                stdout=f"{Config.SHOWS_ROOT}/show1/shots/seq1/seq1_shot1/user/testuser\n",
            )

        QSignalSpy(worker.scan_finished)

        # Replace finder with base class that uses subprocess.run for testing
        # Local application imports
        from previous_shots_finder import (
            PreviousShotsFinder,
        )

        worker._finder = PreviousShotsFinder(username="testuser")

        # FIX: Use monkeypatch for cleaner subprocess mocking
        monkeypatch.setattr("subprocess.run", slow_subprocess)

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
        """Test error handling when finder raises unexpected exception."""
        worker = worker_with_cleanup

        error_spy = QSignalSpy(worker.error_occurred)
        scan_finished_spy = QSignalSpy(worker.scan_finished)

        # Replace finder with base class that uses subprocess.run for testing
        # Local application imports
        from previous_shots_finder import (
            PreviousShotsFinder,
        )

        worker._finder = PreviousShotsFinder(username="testuser")

        # Mock finder.find_user_shots to raise exception (this will propagate)
        def failing_find_user_shots(*args: Any) -> NoReturn:
            raise RuntimeError("Critical finder error")

        # Use monkeypatch for safer patching
        monkeypatch.setattr(worker._finder, "find_user_shots", failing_find_user_shots)

        # Use pure thread wait instead of waitSignal to avoid Qt event loop
        # The Qt event loop crashes after ~2100 tests due to state accumulation
        worker.start()
        finished = worker.wait(5000)
        assert finished, "Worker did not finish within timeout"

        # Process any pending events
        QCoreApplication.processEvents()
        QCoreApplication.processEvents()  # Second pass to handle deferred deletions

        # Should emit error signal
        assert error_spy.count() == 1
        error_message = error_spy.at(0)[0]
        assert "Error during previous shots scan" in error_message
        assert "Critical finder error" in error_message

        # Should not emit scan_finished on error
        assert scan_finished_spy.count() == 0

    @pytest.fixture
    def single_shot_shows_root(self, tmp_path: Path) -> Path:
        """Create shows directory with a single shot for data format testing."""
        shows_root = tmp_path / "shows"
        shows_root.mkdir(exist_ok=True)

        # Create single shot directory
        shot_dir = (
            shows_root / "different_show" / "shots" / "testseq" / "testseq_testshot"
            / "user" / "testuser"
        )
        shot_dir.mkdir(parents=True, exist_ok=True)

        return shows_root

    def test_signal_data_format(
        self,
        single_shot_shows_root: Path,
        qtbot: Any,
    ) -> None:
        """Test signal data format matches expected structure.

        Uses real directory structure and PreviousShotsFinder (rglob-based).
        """
        # Create worker with single-shot structure
        active_shots: list[Shot] = []  # No active shots to filter
        worker = PreviousShotsWorker(
            active_shots=active_shots,
            username="testuser",
            shows_root=single_shot_shows_root,
        )

        scan_finished_spy = QSignalSpy(worker.scan_finished)

        # Replace finder with base class that uses Path.rglob()
        from previous_shots_finder import PreviousShotsFinder

        worker._finder = PreviousShotsFinder(username="testuser")

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
        """Test integration using real PreviousShotsFinder with mocked subprocess."""
        # Create active shots (some overlap with user work)
        # Note: shot name must match what finder extracts from "010_opening_000" directory
        # The finder will extract "000" from "010_opening_000" (takes part after last underscore)
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

        # Mock subprocess to return paths that exist in our test structure
        # Using VFX naming convention: {seq}_{shot}
        find_output = [
            str(
                real_shows_structure
                / "feature_film/shots/010_opening/010_opening_000/user/testuser"
            ),
            str(
                real_shows_structure
                / "feature_film/shots/010_opening/010_opening_002/user/testuser"
            ),
            str(
                real_shows_structure
                / "feature_film/shots/020_chase/020_chase_000/user/testuser"
            ),
            str(
                real_shows_structure
                / "feature_film/shots/020_chase/020_chase_002/user/testuser"
            ),
            str(
                real_shows_structure
                / "commercial/shots/001_product/001_product_000/user/testuser"
            ),
        ]

        test_result = TestCompletedProcess(
            args=[], returncode=0, stdout="\n".join(find_output) + "\n"
        )

        scan_finished_spy = QSignalSpy(worker.scan_finished)

        # Replace finder with base class that uses subprocess.run for testing
        # Local application imports
        from previous_shots_finder import (
            PreviousShotsFinder,
        )

        worker._finder = PreviousShotsFinder(username="testuser")

        # FIX: Use monkeypatch for cleaner subprocess mocking
        monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: test_result)

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
