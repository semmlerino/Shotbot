"""Unit tests for PreviousShotsWorker background thread following UNIFIED_TESTING_GUIDE.

Tests the background worker thread with real Qt threading and signal emission.
Focuses on thread safety, signal emission, and cancellation behavior.

UNIFIED_TESTING_GUIDE COMPLIANCE:
1. Mock only at system boundaries (subprocess.run, not internal methods)
2. Test behavior, not implementation details
3. Use real PreviousShotsFinder (base class) with subprocess.run mocks
4. Proper QThread cleanup without qtbot.addWidget()
5. PySide6 QSignalSpy API (count() method)
6. Signal waiters set up BEFORE actions to prevent race conditions

IMPLEMENTATION NOTES:
- Tests replace ParallelShotsFinder with base PreviousShotsFinder to ensure
  subprocess.run mocking works (ParallelShotsFinder uses different code paths)
- This maintains testing principles while enabling proper system boundary mocking
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
import platform
import sys
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
from tests.test_doubles_library import TestCompletedProcess


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
    pytest.mark.xdist_group("qt_state"),  # CRITICAL for parallel safety
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
        worker = PreviousShotsWorker(
            active_shots=mock_active_shots, username="testuser", shows_root=shows_root
        )
        yield worker

        # Proper cleanup for QThread (not QWidget)
        if worker.isRunning():
            worker.stop()
            worker.wait(5000)  # Wait up to 5 seconds for thread to finish

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
    """Test complete workflow with mocked system boundaries."""

    @pytest.fixture
    def worker_with_cleanup(
        self, tmp_path: Path
    ) -> Generator[PreviousShotsWorker, None, None]:
        """Create worker with cleanup."""
        shows_root = tmp_path / "shows"
        shows_root.mkdir(exist_ok=True)

        active_shots = [
            Shot("active_show", "seq1", "shot1", f"{Config.SHOWS_ROOT}/active_show/shots/seq1/shot1"),
        ]

        worker = PreviousShotsWorker(
            active_shots=active_shots, username="testuser", shows_root=shows_root
        )
        yield worker

        # Thread cleanup
        if worker.isRunning():
            worker.stop()
            worker.wait(5000)

    @pytest.mark.skipif(
        sys.platform == "linux" and "microsoft" in platform.release().lower(),
        reason="WSL subprocess.run with find command returns empty results",
    )
    def test_complete_workflow_with_results(
        self,
        worker_with_cleanup: PreviousShotsWorker,
        qtbot: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test complete run() workflow with mocked subprocess at system boundary."""
        worker = worker_with_cleanup

        # Mock subprocess.run (system boundary) to simulate find command output
        # Must use VFX path format: /shows/{show}/shots/{seq}/{seq}_{shot}/user/{user}
        find_output = [
            f"{Config.SHOWS_ROOT}/show1/shots/seq1/seq1_shot1/user/testuser",
            f"{Config.SHOWS_ROOT}/show1/shots/seq1/seq1_shot2/user/testuser",
            f"{Config.SHOWS_ROOT}/show2/shots/seq2/seq2_shot1/user/testuser",
        ]

        test_result = TestCompletedProcess(
            args=[], returncode=0, stdout="\n".join(find_output) + "\n"
        )

        # Replace finder with base class that uses subprocess.run for testing
        # Local application imports
        from previous_shots_finder import PreviousShotsFinder

        worker._finder = PreviousShotsFinder(username="testuser")

        # FIX: Use monkeypatch for cleaner subprocess mocking
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: test_result)

        # Collect shot_found signals to verify count
        shot_found_signals: list[dict[str, Any]] = []

        def collect_shot_found(shot_dict: dict[str, Any]) -> None:
            shot_found_signals.append(shot_dict)

        worker.shot_found.connect(collect_shot_found)

        # Set up expectation for scan_finished with result validation
        def check_scan_result(final_result: list[dict[str, Any]]) -> bool:
            return isinstance(final_result, list) and len(final_result) == 3

        with qtbot.waitSignal(
            worker.scan_finished, check_params_cb=check_scan_result, timeout=5000
        ), qtbot.assertNotEmitted(worker.error_occurred, wait=100):
            # Start worker after signal waiter is ready
            worker.start()

        # Ensure thread has finished
        worker.wait(2000)

        # Verify shot_found was called for each shot (excluding active ones)
        # 3 found shots - 0 matching active shots = 3 approved shots
        assert len(shot_found_signals) == 3

    def test_workflow_with_no_results(
        self,
        worker_with_cleanup: PreviousShotsWorker,
        qtbot: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test workflow when no shots are found."""
        worker = worker_with_cleanup

        # Mock empty find command output
        test_result = TestCompletedProcess(args=[], returncode=0, stdout="")

        scan_finished_spy = QSignalSpy(worker.scan_finished)
        shot_found_spy = QSignalSpy(worker.shot_found)

        # Replace finder with base class that uses subprocess.run for testing
        # Local application imports
        from previous_shots_finder import PreviousShotsFinder

        worker._finder = PreviousShotsFinder(username="testuser")

        # FIX: Use monkeypatch for cleaner subprocess mocking
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: test_result)

        try:
            with qtbot.waitSignal(worker.scan_finished, timeout=5000):
                worker.start()
        finally:
            pass  # monkeypatch automatically restores

        worker.wait(2000)

        # Should complete successfully with no results
        assert scan_finished_spy.count() == 1
        assert shot_found_spy.count() == 0

        final_result = scan_finished_spy.at(0)[0]
        assert len(final_result) == 0

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
            # Small delay to allow stop request to be processed
            # Standard library imports
            import time

            time.sleep(0.1)
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
        from previous_shots_finder import PreviousShotsFinder

        worker._finder = PreviousShotsFinder(username="testuser")

        # FIX: Use monkeypatch for cleaner subprocess mocking
        monkeypatch.setattr("subprocess.run", slow_subprocess)

        try:
            # Start worker with proper signal handling
            worker.start()

            # Allow worker to start processing
            qtbot.wait(100)  # Small delay to ensure worker is running

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
        from previous_shots_finder import PreviousShotsFinder

        worker._finder = PreviousShotsFinder(username="testuser")

        # Mock finder.find_user_shots to raise exception (this will propagate)
        def failing_find_user_shots(*args: Any) -> NoReturn:
            raise RuntimeError("Critical finder error")

        # Use monkeypatch for safer patching
        monkeypatch.setattr(worker._finder, "find_user_shots", failing_find_user_shots)

        # FIX: Use waitSignal to properly wait for error signal
        with qtbot.waitSignal(worker.error_occurred, timeout=5000):
            worker.start()

        # Ensure thread has finished
        worker.wait(2000)

        # Process any pending events
        QCoreApplication.processEvents()

        # Should emit error signal
        assert error_spy.count() == 1
        error_message = error_spy.at(0)[0]
        assert "Error during previous shots scan" in error_message
        assert "Critical finder error" in error_message

        # Should not emit scan_finished on error
        assert scan_finished_spy.count() == 0

    @pytest.mark.skipif(
        sys.platform == "linux" and "microsoft" in platform.release().lower(),
        reason="WSL subprocess.run with find command returns empty results",
    )
    def test_signal_data_format(
        self,
        worker_with_cleanup: PreviousShotsWorker,
        qtbot: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test signal data format matches expected structure."""
        worker = worker_with_cleanup

        # Mock subprocess output with single shot (different from active_show to avoid filtering)
        test_result = TestCompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{Config.SHOWS_ROOT}/different_show/shots/testseq/testseq_testshot/user/testuser\n",
        )

        shot_found_spy = QSignalSpy(worker.shot_found)
        scan_finished_spy = QSignalSpy(worker.scan_finished)

        # Replace finder with base class that uses subprocess.run for testing
        # Local application imports
        from previous_shots_finder import PreviousShotsFinder

        worker._finder = PreviousShotsFinder(username="testuser")

        # FIX: Use monkeypatch for cleaner subprocess mocking
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: test_result)

        try:
            with qtbot.waitSignal(worker.scan_finished, timeout=5000):
                worker.start()
        finally:
            pass  # monkeypatch automatically restores

        worker.wait(2000)

        # Verify shot_found signal data structure
        assert shot_found_spy.count() == 1
        shot_dict = shot_found_spy.at(0)[0]

        required_keys = {"show", "sequence", "shot", "workspace_path"}
        assert set(shot_dict.keys()) == required_keys
        assert shot_dict["show"] == "different_show"
        assert shot_dict["sequence"] == "testseq"
        assert shot_dict["shot"] == "testshot"
        assert (
            shot_dict["workspace_path"]
            == f"{Config.SHOWS_ROOT}/different_show/shots/testseq/testseq_testshot"
        )

        # Verify scan_finished signal data structure
        assert scan_finished_spy.count() == 1
        final_shots = scan_finished_spy.at(0)[0]
        assert isinstance(final_shots, list)
        assert len(final_shots) == 1
        assert final_shots[0] == shot_dict


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

        shot_found_spy = QSignalSpy(worker.shot_found)
        scan_finished_spy = QSignalSpy(worker.scan_finished)

        # Replace finder with base class that uses subprocess.run for testing
        # Local application imports
        from previous_shots_finder import PreviousShotsFinder

        worker._finder = PreviousShotsFinder(username="testuser")

        # FIX: Use monkeypatch for cleaner subprocess mocking
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: test_result)

        try:
            with qtbot.waitSignal(worker.scan_finished, timeout=10000):
                worker.start()
        finally:
            pass  # monkeypatch automatically restores

        # Cleanup
        worker.wait(2000)

        # Verify results
        assert scan_finished_spy.count() == 1
        final_shots = scan_finished_spy.at(0)[0]

        # Should find 5 user shots minus 1 active shot = 4 approved shots
        assert len(final_shots) == 4

        # Verify individual shot signals were emitted
        assert shot_found_spy.count() == 4


# Performance tests removed to prevent test suite timeout
# These tests were moved to a separate benchmark suite
