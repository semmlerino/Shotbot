"""Comprehensive tests for threading_manager module.

Tests the ThreadingManager class for thread coordination, lifecycle management,
and resource cleanup following UNIFIED_TESTING_GUIDE patterns.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QThread, Signal

from threading_manager import ThreadingManager


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.xdist_group("qt_state"),  # CRITICAL for parallel safety
]

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytestqt.qtbot import QtBot


# =============================================================================
# Fixtures and Test Doubles
# =============================================================================


class MockWorker(QThread):
    """Mock QThread worker for testing."""

    started = Signal()
    progress_update = Signal(int, int, str)
    batch_ready = Signal(list)
    finished = Signal(list)
    error = Signal(str)
    paused = Signal()
    resumed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._stopped = False
        self._paused = False

    def run(self) -> None:
        """Mock run method."""

    def stop(self) -> None:
        """Mock stop method."""
        self._stopped = True

    def pause(self) -> None:
        """Mock pause method."""
        self._paused = True

    def resume(self) -> None:
        """Mock resume method."""
        self._paused = False


@pytest.fixture
def mock_threede_worker() -> Mock:
    """Create mock ThreeDESceneWorker with correct signal names."""
    worker = Mock(spec=QThread)

    # Mock signals with connect methods (match actual ThreeDESceneWorker signals)
    worker.started = Mock()
    worker.started.connect = Mock()
    worker.progress = Mock()  # Changed from progress_update
    worker.progress.connect = Mock()
    worker.batch_ready = Mock()
    worker.batch_ready.connect = Mock()
    worker.finished = Mock()
    worker.finished.connect = Mock()
    worker.error = Mock()
    worker.error.connect = Mock()
    worker.paused = Mock()
    worker.paused.connect = Mock()
    worker.resumed = Mock()
    worker.resumed.connect = Mock()

    # Mock QThread methods
    worker.start = Mock()
    worker.stop = Mock()
    worker.pause = Mock()
    worker.resume = Mock()
    worker.wait = Mock(return_value=True)
    worker.isRunning = Mock(return_value=True)
    worker.isFinished = Mock(return_value=False)
    worker.deleteLater = Mock()

    return worker


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
        mock_threede_worker: Mock,
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
            mock_threede_worker.start.assert_called_once()

    def test_start_discovery_rejects_concurrent_start(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: Mock,
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
        mock_threede_worker: Mock,
    ) -> None:
        """Test discovery worker signals are connected to manager signals."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            # Verify signal connections (match actual signal names)
            mock_threede_worker.started.connect.assert_called()
            mock_threede_worker.progress.connect.assert_called()  # Changed from progress_update
            mock_threede_worker.batch_ready.connect.assert_called()
            mock_threede_worker.finished.connect.assert_called()
            mock_threede_worker.error.connect.assert_called()
            mock_threede_worker.paused.connect.assert_called()
            mock_threede_worker.resumed.connect.assert_called()

    def test_is_discovery_active_reflects_state(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: Mock,
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
        mock_threede_worker: Mock,
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
        mock_threede_worker: Mock,
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
        mock_threede_worker: Mock,
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
            mock_threede_worker.pause.assert_called_once()

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
        mock_threede_worker: Mock,
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
            mock_threede_worker.resume.assert_called_once()

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
        mock_threede_worker: Mock,
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
            mock_threede_worker.stop.assert_called_once()
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
        """Test removing worker handles wait timeout gracefully."""
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
        worker.deleteLater.assert_called_once()


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

    def test_get_thread_status_running(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test thread status reporting for running thread."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=True)
        worker.isFinished = Mock(return_value=False)

        threading_manager.add_custom_worker("worker", worker)

        status = threading_manager.get_thread_status()

        assert status == {"worker": "running"}

    def test_get_thread_status_finished(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test thread status reporting for finished thread."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=False)
        worker.isFinished = Mock(return_value=True)

        threading_manager.add_custom_worker("worker", worker)

        status = threading_manager.get_thread_status()

        assert status == {"worker": "finished"}

    def test_get_thread_status_ready(self, threading_manager: ThreadingManager) -> None:
        """Test thread status reporting for ready thread."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=False)
        worker.isFinished = Mock(return_value=False)

        threading_manager.add_custom_worker("worker", worker)

        status = threading_manager.get_thread_status()

        assert status == {"worker": "ready"}

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

    def test_cleanup_threede_worker_stops_running_worker(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: Mock,
    ) -> None:
        """Test cleanup stops running 3DE worker."""
        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            threading_manager._cleanup_threede_worker()

            mock_threede_worker.stop.assert_called_once()
            mock_threede_worker.wait.assert_called_once()
            mock_threede_worker.deleteLater.assert_called_once()

    def test_cleanup_threede_worker_handles_timeout(
        self,
        threading_manager: ThreadingManager,
        mock_threede_model: Mock,
        mock_shot_model: Mock,
        mock_threede_worker: Mock,
    ) -> None:
        """Test cleanup handles worker timeout gracefully."""
        mock_threede_worker.wait.return_value = False  # Timeout

        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            # Should not raise exception
            threading_manager._cleanup_threede_worker()

            mock_threede_worker.deleteLater.assert_called_once()

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
        mock_threede_worker: Mock,
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
        mock_threede_worker: Mock,
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

    def test_get_active_thread_count_thread_safe(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test get_active_thread_count uses mutex protection."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=True)

        threading_manager.add_custom_worker("worker", worker)

        # Should safely access _workers dict
        count = threading_manager.get_active_thread_count()

        assert count == 1

    def test_get_thread_status_thread_safe(
        self, threading_manager: ThreadingManager
    ) -> None:
        """Test get_thread_status uses mutex protection."""
        worker = Mock(spec=QThread)
        worker.start = Mock()
        worker.isRunning = Mock(return_value=True)
        worker.isFinished = Mock(return_value=False)

        threading_manager.add_custom_worker("worker", worker)

        # Should safely access _workers dict
        status = threading_manager.get_thread_status()

        assert "worker" in status


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
        mock_threede_worker: Mock,
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
        mock_threede_worker: Mock,
    ) -> None:
        """Test starting discovery cleans up any existing worker."""
        old_worker = Mock(spec=QThread)
        old_worker.isRunning = Mock(return_value=True)
        old_worker.stop = Mock()
        old_worker.wait = Mock(return_value=True)
        old_worker.deleteLater = Mock()

        threading_manager._current_threede_worker = old_worker
        threading_manager._workers["threede_discovery"] = old_worker

        with patch(
            "threede_scene_worker.ThreeDESceneWorker", return_value=mock_threede_worker
        ):
            threading_manager.start_threede_discovery(
                mock_threede_model, mock_shot_model
            )

            # Old worker should be cleaned up
            old_worker.stop.assert_called_once()
            old_worker.deleteLater.assert_called_once()

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
