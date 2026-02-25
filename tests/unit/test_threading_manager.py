"""Comprehensive tests for threading_manager module.

Tests the ThreadingManager class for thread coordination, lifecycle management,
and resource cleanup following UNIFIED_TESTING_GUIDE patterns.
"""

from __future__ import annotations

import contextlib
import sys
from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch  # Mock kept for boundary checks on external deps

import pytest
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication  # noqa: TC002

from tests.test_helpers import process_qt_events
from thread_safe_worker import ThreadSafeWorker
from threading_manager import ThreadingManager
from typing_compat import override


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytestqt.qtbot import QtBot


# =============================================================================
# Fixtures and Test Doubles
# =============================================================================


class MockWorker(QThread):
    """Real QThread subclass used as a test double for ThreeDESceneWorker.

    Provides real Qt signals matching ThreeDESceneWorker's interface so tests
    can connect signals and emit them to verify manager reactions without
    relying on Mock.connect() call assertions.

    Attributes:
        _stopped: Set to True when stop() is called.
        _paused: Toggled by pause() / resume().
        _force_running: When not None, overrides isRunning() for tests that
            need precise control over the "worker is running" state without
            actually spinning a thread.
    """

    # Match ThreeDESceneWorker signal signatures exactly
    started = Signal()
    progress = Signal(int, int, float, str, str)  # current, total, pct, description, eta
    batch_ready = Signal(list)
    finished = Signal(list)
    error = Signal(str)
    paused = Signal()
    resumed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._stopped = False
        self._paused = False
        self._force_running: bool | None = None

    def isRunning(self) -> bool:
        """Return forced value if set, otherwise delegate to QThread."""
        if self._force_running is not None:
            return self._force_running
        return super().isRunning()

    def run(self) -> None:
        """Minimal run method — returns immediately so threads don't linger."""

    def stop(self) -> None:
        """Record stop request without blocking."""
        self._stopped = True

    def pause(self) -> None:
        """Record pause request."""
        self._paused = True

    def resume(self) -> None:
        """Record resume request."""
        self._paused = False


@pytest.fixture
def mock_threede_worker() -> MockWorker:
    """Create a real MockWorker (QThread subclass) to stand in for ThreeDESceneWorker.

    Using a real QThread subclass with real Qt signals lets tests emit those
    signals and verify that ThreadingManager reacted correctly, rather than
    asserting that .connect() was called (an implementation detail).
    """
    return MockWorker()


@pytest.fixture
def mock_shot_model() -> Mock:
    """Create mock BaseShotModel."""
    model = Mock()
    model.get_shots.return_value = [
        {"name": "shot_010", "path": "/path/to/shot_010"},
        {"name": "shot_020", "path": "/path/to/shot_020"},
    ]
    return model


@pytest.fixture
def mock_threede_model() -> Mock:
    """Create mock ThreeDESceneModel."""
    return Mock()


@pytest.fixture
def threading_manager() -> Generator[ThreadingManager, None, None]:
    """Create ThreadingManager instance."""
    manager = ThreadingManager()
    yield manager
    # Cleanup
    with contextlib.suppress(Exception):
        manager.shutdown_all_threads()


# =============================================================================
# Initialization Tests
# =============================================================================


class TestThreadingManagerInitialization:
    """Test ThreadingManager initialization."""

    def test_initialization(self, threading_manager: ThreadingManager) -> None:
        """Test manager initializes with correct default state."""
        assert threading_manager._workers == {}
        assert threading_manager._current_threede_worker is None
        assert threading_manager._threede_discovery_active is False
        assert threading_manager._mutex is not None

    def test_initial_thread_count_zero(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test initial active thread count is zero."""
        assert threading_manager.get_active_thread_count() == 0

    def test_initial_thread_status_empty(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test initial thread status is empty dict."""
        status = threading_manager.get_thread_status()
        assert status == {}


# =============================================================================
# 3DE Discovery Lifecycle Tests
# =============================================================================


class TestThreeDEDiscoveryLifecycle:
    """Test 3DE scene discovery worker lifecycle management."""

    def test_start_discovery_creates_worker(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test starting discovery creates and configures worker."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            result = threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            assert result is True
            assert threading_manager._threede_discovery_active is True
            assert threading_manager._current_threede_worker is mock_threede_worker
            # Behavior: worker was registered in the manager's tracking dict
            assert "threede_discovery" in threading_manager._workers

    def test_start_discovery_rejects_concurrent_start(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test starting discovery while already running returns False."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            # First start succeeds
            result1 = threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )
            assert result1 is True

            # Second start fails
            result2 = threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )
            assert result2 is False

    def test_start_discovery_connects_signals(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
        qtbot: QtBot,
    ) -> None:
        """Test discovery worker signals are wired to manager output signals.

        Emits each MockWorker signal and verifies the manager forwards it
        through the corresponding ThreadingManager signal — proving connection
        without inspecting .connect() call counts.
        """
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

        # started → threede_discovery_started
        with qtbot.waitSignal(threading_manager.threede_discovery_started, timeout=1000):
            mock_threede_worker.started.emit()

        # progress → threede_discovery_progress (mapped through _on_progress_update)
        with qtbot.waitSignal(threading_manager.threede_discovery_progress, timeout=1000):
            mock_threede_worker.progress.emit(1, 10, 10.0, "scanning", "~5s")

        # batch_ready → threede_discovery_batch_ready
        with qtbot.waitSignal(
            threading_manager.threede_discovery_batch_ready, timeout=1000
        ):
            mock_threede_worker.batch_ready.emit([])

        # finished → threede_discovery_finished (via _on_threede_discovery_finished)
        with qtbot.waitSignal(
            threading_manager.threede_discovery_finished, timeout=1000
        ):
            # Re-arm the active flag so the slot fires correctly
            threading_manager._threede_discovery_active = True
            mock_threede_worker.finished.emit([])

        # error → threede_discovery_error (via _on_threede_discovery_error)
        # Reset active flag so the error slot runs
        threading_manager._threede_discovery_active = True
        with qtbot.waitSignal(threading_manager.threede_discovery_error, timeout=1000):
            mock_threede_worker.error.emit("test error")

        # paused → threede_discovery_paused
        with qtbot.waitSignal(threading_manager.threede_discovery_paused, timeout=1000):
            mock_threede_worker.paused.emit()

        # resumed → threede_discovery_resumed
        with qtbot.waitSignal(threading_manager.threede_discovery_resumed, timeout=1000):
            mock_threede_worker.resumed.emit()

    def test_is_discovery_active_reflects_state(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test is_threede_discovery_active reflects current state."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            assert threading_manager.is_threede_discovery_active() is False

            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            assert threading_manager.is_threede_discovery_active() is True

    def test_discovery_finished_updates_state(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
        qtbot: QtBot,
    ) -> None:
        """Test discovery finished callback updates active state."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            # Simulate finished signal
            scenes = [{"name": "scene1.3de"}]
            with qtbot.waitSignal(
                threading_manager.threede_discovery_finished, timeout=1000
            ):
                threading_manager._on_threede_discovery_finished(scenes)

            assert threading_manager._threede_discovery_active is False

    def test_discovery_error_updates_state(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
        qtbot: QtBot,
    ) -> None:
        """Test discovery error callback updates active state."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            # Simulate error signal
            with qtbot.waitSignal(
                threading_manager.threede_discovery_error, timeout=1000
            ):
                threading_manager._on_threede_discovery_error("Test error")

            assert threading_manager._threede_discovery_active is False


# =============================================================================
# 3DE Discovery Control Tests
# =============================================================================


class TestThreeDEDiscoveryControl:
    """Test pause/resume/stop controls for 3DE discovery."""

    def test_pause_discovery_when_active(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test pausing active discovery succeeds."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            result = threading_manager.pause_threede_discovery()

            assert result is True
            # Behavior: MockWorker.pause() set the _paused flag
            assert mock_threede_worker._paused is True

    def test_pause_discovery_when_not_active(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test pausing when not active returns False."""
        result = threading_manager.pause_threede_discovery()

        assert result is False

    def test_resume_discovery_when_paused(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test resuming paused discovery succeeds."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )
            threading_manager.pause_threede_discovery()

            result = threading_manager.resume_threede_discovery()

            assert result is True
            # Behavior: MockWorker.resume() cleared the _paused flag
            assert mock_threede_worker._paused is False

    def test_resume_discovery_when_not_active(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test resuming when not active returns False."""
        result = threading_manager.resume_threede_discovery()

        assert result is False

    def test_stop_discovery_when_active(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test stopping active discovery succeeds."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            result = threading_manager.stop_threede_discovery()

            assert result is True
            # Behavior: MockWorker.stop() set the _stopped flag
            assert mock_threede_worker._stopped is True
            assert threading_manager._threede_discovery_active is False

    def test_stop_discovery_when_not_active(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test stopping when not active returns False."""
        result = threading_manager.stop_threede_discovery()

        assert result is False


# =============================================================================
# Custom Worker Management Tests
# =============================================================================


class TestCustomWorkerManagement:
    """Test adding and removing custom workers."""

    def test_add_custom_worker_succeeds(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test adding custom worker starts it and tracks it."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=True)

        result = threading_manager.add_custom_worker("custom_worker", worker)

        assert result is True
        assert "custom_worker" in threading_manager._workers
        worker.start.assert_called_once()

    def test_add_duplicate_worker_fails(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test adding worker with duplicate name fails."""
        worker1 = Mock(spec=QThread)
        worker1.start = Mock()
        worker2 = Mock(spec=QThread)
        worker2.start = Mock()

        threading_manager.add_custom_worker("worker", worker1)
        result = threading_manager.add_custom_worker("worker", worker2)

        assert result is False
        worker2.start.assert_not_called()

    def test_remove_worker_stops_and_cleans_up(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test removing worker stops it and cleans up."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=True)
        worker.stop = Mock()
        worker.wait = Mock(return_value=True)
        worker.deleteLater = Mock()

        threading_manager.add_custom_worker("worker", worker)

        result = threading_manager.remove_worker("worker")

        assert result is True
        worker.stop.assert_called_once()
        worker.wait.assert_called_once()
        worker.deleteLater.assert_called_once()
        assert "worker" not in threading_manager._workers

    def test_remove_nonexistent_worker_returns_false(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test removing non-existent worker returns False."""
        result = threading_manager.remove_worker("nonexistent")

        assert result is False

    def test_remove_worker_with_request_stop_method(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test removing worker uses request_stop if available."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=True)
        worker.request_stop = Mock()
        worker.wait = Mock(return_value=True)
        worker.deleteLater = Mock()

        threading_manager.add_custom_worker("worker", worker)

        threading_manager.remove_worker("worker")

        worker.request_stop.assert_called_once()

    def test_remove_worker_handles_timeout(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test removing worker handles wait timeout gracefully.

        When a worker times out (doesn't stop gracefully), it should be tracked
        as a zombie and deleteLater should NOT be called (it's unsafe on running threads).
        """
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=True)
        worker.stop = Mock()
        worker.wait = Mock(return_value=False)  # Timeout
        worker.deleteLater = Mock()

        threading_manager.add_custom_worker("worker", worker)

        result = threading_manager.remove_worker("worker")

        # Should still complete despite timeout
        assert result is True
        # deleteLater should NOT be called on zombie workers (they're still running!)
        worker.deleteLater.assert_not_called()
        # Worker should be tracked as zombie instead
        assert worker in threading_manager._zombie_workers


# =============================================================================
# Thread Status and Monitoring Tests
# =============================================================================


class TestThreadStatusMonitoring:
    """Test thread status reporting and monitoring."""

    def test_get_active_thread_count_with_running_threads(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test counting active threads."""
        worker1 = Mock(spec=QThread)
        worker1.start = Mock()
        worker1.isRunning = Mock(return_value=True)

        worker2 = Mock(spec=QThread)
        worker2.start = Mock()
        worker2.isRunning = Mock(return_value=False)

        threading_manager.add_custom_worker("worker1", worker1)
        threading_manager.add_custom_worker("worker2", worker2)

        count = threading_manager.get_active_thread_count()

        assert count == 1  # Only worker1 is running

    @pytest.mark.parametrize(
        ("is_running", "is_finished", "expected_status"),
        [
            (True, False, "running"),
            (False, True, "finished"),
            (False, False, "ready"),
        ],
    )
    def test_get_thread_status_single_worker(
        self,
        threading_manager: ThreadingManager,
        is_running: bool,
        is_finished: bool,
        expected_status: str,
    ) -> None:
        """Test thread status reporting for running, finished, and ready threads."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=is_running)
        worker.isFinished = Mock(return_value=is_finished)

        threading_manager.add_custom_worker("worker", worker)

        status = threading_manager.get_thread_status()

        assert status == {"worker": expected_status}

    def test_get_thread_status_multiple_workers(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test thread status with multiple workers."""
        worker1 = Mock(spec=QThread)
        worker1.start = Mock()
        worker1.isRunning = Mock(return_value=True)
        worker1.isFinished = Mock(return_value=False)

        worker2 = Mock(spec=QThread)
        worker2.start = Mock()
        worker2.isRunning = Mock(return_value=False)
        worker2.isFinished = Mock(return_value=True)

        threading_manager.add_custom_worker("worker1", worker1)
        threading_manager.add_custom_worker("worker2", worker2)

        status = threading_manager.get_thread_status()

        assert status == {"worker1": "running", "worker2": "finished"}


# =============================================================================
# Cleanup and Shutdown Tests
# =============================================================================


class TestCleanupAndShutdown:
    """Test resource cleanup and shutdown procedures."""

    def test_start_discovery_cleans_up_existing_worker(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test start_threede_discovery cleans up existing running worker."""
        # Start first worker
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

        # Force isRunning() to True so the non-blocking cleanup path triggers
        mock_threede_worker._force_running = True
        first_worker = mock_threede_worker

        # Second worker uses another MockWorker so its real signals work correctly
        second_worker = MockWorker()

        # Start second worker — should trigger cleanup of first worker
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=second_worker
        ):
            # Mark first discovery as inactive so second can start
            threading_manager._threede_discovery_active = False
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

        # Process Qt events for non-blocking cleanup
        process_qt_events()

        # Behavior: stop() was called on the old worker
        assert first_worker._stopped is True
        # Behavior: a cleanup timer was registered (non-blocking path was taken)
        # The timer may have already fired and removed itself, but the stop flag
        # confirms the cleanup sequence was initiated correctly.
        # Alternatively: the manager no longer holds first_worker as current
        assert threading_manager._current_threede_worker is second_worker

    def test_start_discovery_handles_cleanup_timeout(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test start_threede_discovery handles worker timeout gracefully."""
        # Force isRunning() to True so the non-blocking cleanup path triggers
        mock_threede_worker._force_running = True

        # Start first worker
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

        first_worker = mock_threede_worker

        # Second worker uses another MockWorker so its real signals work correctly
        second_worker = MockWorker()

        # Should not raise exception even when old worker reports running
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=second_worker
        ):
            # Mark first discovery as inactive so second can start
            threading_manager._threede_discovery_active = False
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

        # Process Qt events for non-blocking cleanup
        process_qt_events()

        # Behavior: stop() was called on the old worker to initiate cleanup
        assert first_worker._stopped is True
        # Behavior: new worker is now active — cleanup did not prevent start
        assert threading_manager._current_threede_worker is second_worker

    def test_shutdown_all_threads_stops_all_workers(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test shutdown stops all managed workers."""
        worker1 = Mock(spec=QThread)
        worker1.start = Mock()
        worker1.isRunning = Mock(return_value=True)
        worker1.wait = Mock(return_value=True)
        worker1.deleteLater = Mock()

        worker2 = Mock(spec=QThread)
        worker2.start = Mock()
        worker2.isRunning = Mock(return_value=True)
        worker2.wait = Mock(return_value=True)
        worker2.deleteLater = Mock()

        threading_manager.add_custom_worker("worker1", worker1)
        threading_manager.add_custom_worker("worker2", worker2)

        threading_manager.shutdown_all_threads()

        worker1.wait.assert_called_once()
        worker2.wait.assert_called_once()
        worker1.deleteLater.assert_called_once()
        worker2.deleteLater.assert_called_once()
        assert len(threading_manager._workers) == 0

    def test_shutdown_handles_timeouts(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test shutdown handles worker timeouts gracefully."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=True)
        worker.wait = Mock(return_value=False)  # Timeout
        worker.deleteLater = Mock()

        threading_manager.add_custom_worker("worker", worker)

        # Should not raise exception
        threading_manager.shutdown_all_threads()

        worker.deleteLater.assert_called_once()

    def test_shutdown_clears_threede_worker_state(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test shutdown clears 3DE worker state."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            threading_manager.shutdown_all_threads()

            assert threading_manager._current_threede_worker is None
            assert threading_manager._threede_discovery_active is False

    def test_schedule_worker_cleanup_removes_from_dict(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test scheduled cleanup removes worker from tracking."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.deleteLater = Mock()

        threading_manager.add_custom_worker("worker", worker)

        threading_manager._schedule_worker_cleanup("worker")

        worker.deleteLater.assert_called_once()
        assert "worker" not in threading_manager._workers


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestThreadSafety:
    """Test mutex protection and thread safety."""

    def test_start_discovery_uses_mutex(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test start_discovery protects state with mutex."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            # Mutex should prevent race conditions
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )
            # If mutex not working, concurrent call could corrupt state
            result = threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            # Second call should be rejected due to mutex protection
            assert result is False



# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling."""

    def test_remove_threede_discovery_worker_clears_state(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test removing 3DE discovery worker clears special state."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            threading_manager.remove_worker("threede_discovery")

            assert threading_manager._current_threede_worker is None
            assert threading_manager._threede_discovery_active is False

    def test_start_discovery_cleans_up_previous_worker(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: MockWorker,
    ) -> None:
        """Test starting discovery cleans up any existing worker."""
        old_worker = Mock(spec=QThread)
        old_worker.isRunning = Mock(return_value=True)
        old_worker.stop = Mock()
        old_worker.wait = Mock(return_value=True)
        old_worker.deleteLater = Mock()
        old_worker.finished = Mock()
        old_worker.finished.connect = Mock()

        threading_manager._current_threede_worker = old_worker
        threading_manager._workers["threede_discovery"] = old_worker

        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

        # Process Qt events for non-blocking cleanup
        process_qt_events()

        # Old worker cleanup was initiated (non-blocking approach)
        # Uses finished signal instead of blocking wait()
        old_worker.stop.assert_called_once()
        old_worker.finished.connect.assert_called()

    def test_shutdown_with_no_workers(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test shutdown with no active workers completes gracefully."""
        # Should not raise exception
        threading_manager.shutdown_all_threads()

        assert len(threading_manager._workers) == 0

    def test_schedule_cleanup_nonexistent_worker(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test scheduling cleanup for nonexistent worker is safe."""
        # Should not raise exception
        threading_manager._schedule_worker_cleanup("nonexistent")

    def test_control_operations_without_worker_attribute(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test control operations handle missing worker methods gracefully."""
        # Create worker without stop method
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=True)
        worker.wait = Mock(return_value=True)
        worker.deleteLater = Mock()
        # No stop or request_stop attributes

        threading_manager.add_custom_worker("worker", worker)

        # Should handle missing method gracefully
        result = threading_manager.remove_worker("worker")

        assert result is True
        worker.deleteLater.assert_called_once()


# =============================================================================
# Qt Signal Warning Tests (merged from test_qt_signal_warnings.py)
# =============================================================================


class _SignalWarningDummyWorker(ThreadSafeWorker):
    """Minimal worker for testing signal connections."""

    test_signal = Signal(str)

    @override
    def do_work(self) -> None:
        """Dummy work implementation."""
        self.test_signal.emit("test")


class TestQtSignalWarnings:
    """Tests that Qt signal connections don't produce runtime warnings."""

    def test_safe_connect_produces_no_qt_warnings(
        self, qapp: QApplication, qtbot
    ) -> None:
        """Test that safe_connect doesn't produce Qt unique connection warnings.

        Qt warnings like "unique connections require a pointer to member function"
        indicate the code is trying to use features that don't work with Python.
        """
        old_stderr = sys.stderr
        sys.stderr = captured_stderr = StringIO()

        try:
            worker = _SignalWarningDummyWorker()
            slot_called = []

            def test_slot(msg: str) -> None:
                slot_called.append(msg)

            # Connect signal using safe_connect
            worker.safe_connect(
                worker.test_signal,
                test_slot,
                Qt.ConnectionType.QueuedConnection,
            )

            # Emit signal and wait for queued connection to be processed
            worker.test_signal.emit("hello")
            qtbot.waitUntil(lambda: len(slot_called) > 0, timeout=100)

            # Check no Qt warnings were produced
            stderr_output = captured_stderr.getvalue()
            assert "unique connections require" not in stderr_output, (
                f"Qt warning detected in stderr:\n{stderr_output}"
            )
            assert "QObject::connect" not in stderr_output, (
                f"Qt connection warning detected:\n{stderr_output}"
            )

            # Verify connection actually worked
            assert slot_called == ["hello"], "Signal should have triggered slot"

            # Test cleanup
            worker.disconnect_all()
            qtbot.waitUntil(lambda: True, timeout=50)  # Drain event queue

        finally:
            sys.stderr = old_stderr

    def test_safe_connect_deduplication(self, qapp: QApplication, qtbot) -> None:
        """Test that duplicate connections are prevented at application level."""
        worker = _SignalWarningDummyWorker()
        call_count = []

        def counting_slot(msg: str) -> None:
            call_count.append(msg)

        # Connect same slot twice
        worker.safe_connect(worker.test_signal, counting_slot)
        worker.safe_connect(worker.test_signal, counting_slot)  # Should be ignored

        # Emit and wait for slot to be called
        worker.test_signal.emit("test")
        qtbot.waitUntil(lambda: len(call_count) > 0, timeout=100)

        # Should only be called once due to deduplication
        assert len(call_count) == 1, "Duplicate connection should be prevented"

        worker.disconnect_all()

    def test_disconnect_produces_no_warnings(
        self, qapp: QApplication, qtbot
    ) -> None:
        """Test that disconnect_all doesn't produce RuntimeWarnings."""
        old_stderr = sys.stderr
        sys.stderr = captured_stderr = StringIO()

        try:
            worker = _SignalWarningDummyWorker()

            def dummy_slot(msg: str) -> None:
                pass

            worker.safe_connect(worker.test_signal, dummy_slot)

            # Disconnect should be silent
            worker.disconnect_all()
            qtbot.waitUntil(lambda: True, timeout=50)  # Drain event queue

            stderr_output = captured_stderr.getvalue()
            assert "Failed to disconnect" not in stderr_output, (
                f"Disconnect warning detected:\n{stderr_output}"
            )
            assert "RuntimeWarning" not in stderr_output, (
                f"RuntimeWarning detected:\n{stderr_output}"
            )

        finally:
            sys.stderr = old_stderr
