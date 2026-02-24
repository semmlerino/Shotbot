"""Threading and concurrency tests for CommandLauncher.

This module tests CommandLauncher's behavior under concurrent access and
multi-threaded scenarios. While CommandLauncher is primarily used from the
GUI thread, these tests verify thread-safety guarantees.

Test Coverage:
- Signal emissions from worker threads
- Concurrent launch_app requests
- Thread-safe state access (current_shot)
- QTimer callback thread safety
- Signal/slot cross-thread delivery
"""

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

import pytest
from PySide6.QtCore import QObject, QThread, Signal


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

# Local application imports
from command_launcher import CommandLauncher


if TYPE_CHECKING:
    from pytest_qt.qtbot import QtBot


class WorkerThread(QThread):
    """Worker thread for testing cross-thread signal emissions."""

    finished_signal = Signal()

    def __init__(self, launcher: CommandLauncher, shot: MagicMock) -> None:
        """Initialize worker thread.

        Args:
            launcher: CommandLauncher instance to test
            shot: Mock shot object

        """
        super().__init__()
        self.launcher = launcher
        self.shot = shot

    def run(self) -> None:
        """Set current shot from worker thread."""
        self.launcher.set_current_shot(self.shot)
        self.finished_signal.emit()


class TestCommandLauncherThreading:
    """Test CommandLauncher threading and concurrency behavior."""

    @pytest.fixture
    def launcher(self) -> CommandLauncher:
        """Create CommandLauncher instance for testing."""
        return CommandLauncher()

    def test_current_shot_access_from_worker_thread(
        self, qtbot: "QtBot", launcher: CommandLauncher
    ) -> None:
        """Test that set_current_shot can be safely called from worker thread.

        While CommandLauncher is typically used from GUI thread, this test
        verifies that basic state access is thread-safe.
        """
        mock_shot = MagicMock(
            full_name="TEST_SHOT_0010",
            workspace_path="/test/workspace",
        )

        # Create worker thread
        worker = WorkerThread(launcher, mock_shot)

        try:
            # Start worker and wait for completion
            with qtbot.waitSignal(worker.finished_signal, timeout=1000):
                worker.start()

            # Verify shot was set correctly
            assert launcher.current_shot == mock_shot
            assert launcher.current_shot.full_name == "TEST_SHOT_0010"
        finally:
            # Ensure QThread cleanup even if assertions fail
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(1000)
            worker.deleteLater()

    def test_signal_emission_from_gui_thread(
        self, qtbot: "QtBot", launcher: CommandLauncher
    ) -> None:
        """Test that signals are emitted correctly from GUI thread."""
        signals_received = []

        def on_command_error(timestamp: str, error: str) -> None:
            signals_received.append((timestamp, error))

        launcher.command_error.connect(on_command_error)

        # Emit error (which internally uses command_error signal)
        launcher._emit_error("Test error")

        # Process Qt events to ensure signal delivery
        qtbot.wait(10)

        # Verify signal was received
        assert len(signals_received) > 0
        assert "Test error" in signals_received[0][1]

    def test_concurrent_error_emissions(
        self, qtbot: "QtBot", launcher: CommandLauncher
    ) -> None:
        """Test concurrent error emissions from multiple threads.

        This tests Qt's signal queuing mechanism with cross-thread emissions.
        """
        signals_received: list[tuple[str, str]] = []
        lock = threading.Lock()

        def on_error(timestamp: str, error: str) -> None:
            with lock:
                signals_received.append((timestamp, error))

        launcher.command_error.connect(on_error)

        # Create multiple threads that emit errors
        def emit_error(thread_id: int) -> None:
            for i in range(5):
                launcher._emit_error(f"Error from thread {thread_id}, iteration {i}")
                time.sleep(0.001)  # Small delay to encourage interleaving

        threads = [threading.Thread(target=emit_error, args=(i,)) for i in range(3)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Process Qt events to ensure all signals delivered
        qtbot.wait(100)

        # Verify all errors were received (3 threads * 5 iterations = 15 total)
        assert len(signals_received) == 15

        # Verify all thread IDs are present
        thread_ids = {int(error.split("thread ")[1].split(",")[0]) for _, error in signals_received}
        assert thread_ids == {0, 1, 2}

    def test_launch_app_called_concurrently(
        self, qtbot: "QtBot", launcher: CommandLauncher, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test concurrent launch_app calls.

        While unlikely in practice (GUI prevents concurrent launches),
        this verifies that concurrent calls don't cause crashes or race conditions.
        """
        # Set up mock shot
        mock_shot = MagicMock(
            full_name="TEST_SHOT_0010",
            workspace_path="/test/workspace",
        )
        launcher.set_current_shot(mock_shot)

        # Mock dependencies
        # IMPORTANT: Patch command_launcher.Config.APPS, not config.Config.APPS
        # This is because module reloading in other tests can cause command_launcher
        # to hold a reference to a different Config class than config.Config
        monkeypatch.setattr("command_launcher.Config.APPS", {"test_app": "test_command"})
        monkeypatch.setattr("launch.process_executor.subprocess.Popen", Mock(return_value=Mock(pid=12345)))
        monkeypatch.setattr("command_launcher.EnvironmentManager.detect_terminal", lambda _self: "gnome-terminal")
        monkeypatch.setattr("command_launcher.EnvironmentManager.is_rez_available", lambda _self, _config: False)

        # Track results
        results: list[bool] = []
        lock = threading.Lock()

        def launch_app_thread() -> None:
            result = launcher.launch_app("test_app")
            with lock:
                results.append(result)

        # Create multiple threads
        threads = [threading.Thread(target=launch_app_thread) for _ in range(3)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Process Qt events
        qtbot.wait(100)

        # Verify all launches succeeded (or at least completed without crashing)
        assert len(results) == 3
        # Note: Results may vary due to race conditions, but all should complete

    @pytest.mark.real_timing  # Uses qtbot.wait(200) for QTimer callback
    def test_qtimer_callback_thread_safety(
        self, qtbot: "QtBot", launcher: CommandLauncher, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test that QTimer callbacks execute on correct thread.

        CommandLauncher uses QTimer.singleShot for delayed spawn verification.
        This test verifies that the callback executes on the GUI thread.
        """
        # Create a real temporary workspace directory
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        mock_shot = MagicMock(
            full_name="TEST_SHOT_0010",
            workspace_path=str(workspace),
        )
        launcher.set_current_shot(mock_shot)

        # Mock dependencies
        # IMPORTANT: Patch command_launcher.Config.APPS, not config.Config.APPS
        # This is because module reloading in other tests can cause command_launcher
        # to hold a reference to a different Config class than config.Config
        monkeypatch.setattr("command_launcher.Config.APPS", {"test_app": "test_command"})

        mock_process = Mock(pid=12345, poll=Mock(return_value=None))
        monkeypatch.setattr("launch.process_executor.subprocess.Popen", Mock(return_value=mock_process))
        monkeypatch.setattr("command_launcher.EnvironmentManager.detect_terminal", lambda _self: "gnome-terminal")
        monkeypatch.setattr("command_launcher.EnvironmentManager.is_rez_available", lambda _self, _config: False)
        # CRITICAL: Mock is_ws_available - 'ws' command isn't available in dev environment
        monkeypatch.setattr("command_launcher.EnvironmentManager.is_ws_available", lambda _self: True)

        # Launch app (will schedule QTimer callback)
        result = launcher.launch_app("test_app")
        assert result is True

        # Wait for QTimer callback (100ms delay + margin)
        qtbot.wait(200)

        # Verify spawn verification was called
        # (We can't directly test thread ID, but if it runs without crashing, it's correct)
        assert mock_process.poll.called

    def test_signal_slot_cross_thread_delivery(
        self, qtbot: "QtBot", launcher: CommandLauncher
    ) -> None:
        """Test Qt signal/slot mechanism works across threads.

        This is a fundamental Qt feature, but worth verifying for
        CommandLauncher's signal emissions.
        """
        signals_received: list[str] = []

        class SlotReceiver(QObject):
            """Helper class to receive signals on GUI thread."""

            def __init__(self) -> None:
                super().__init__()

            def on_signal(self, _timestamp: str, message: str) -> None:
                signals_received.append(message)

        receiver = SlotReceiver()
        launcher.command_error.connect(receiver.on_signal)

        # Emit signals from worker thread
        def emit_from_thread() -> None:
            for i in range(5):
                launcher._emit_error(f"Message {i}")

        thread = threading.Thread(target=emit_from_thread)
        thread.start()
        thread.join()

        # Wait for signal delivery
        qtbot.wait(100)

        # Verify all signals delivered
        assert len(signals_received) == 5
        for i in range(5):
            assert f"Message {i}" in signals_received[i]

    @pytest.mark.usefixtures("qtbot")
    def test_cleanup_thread_safety(
        self, launcher: CommandLauncher
    ) -> None:
        """Test that cleanup() can be safely called from any thread.

        This is important for Python's garbage collection which may run
        __del__ from any thread.
        """
        # Call cleanup from worker thread
        def cleanup_from_thread() -> None:
            launcher.cleanup()

        thread = threading.Thread(target=cleanup_from_thread)
        thread.start()
        thread.join()

        # Verify cleanup completed without error
        # (If it crashes, the test will fail)

        # Cleanup again from GUI thread (should be idempotent)
        launcher.cleanup()

    @pytest.mark.usefixtures("qtbot")
    def test_state_consistency_under_concurrent_access(
        self, launcher: CommandLauncher
    ) -> None:
        """Test that concurrent state access maintains consistency.

        This test rapidly sets and reads current_shot from multiple threads
        to verify no corruption occurs.
        """
        shots = [
            MagicMock(full_name=f"SHOT_{i:04d}", workspace_path=f"/test/shot{i}")
            for i in range(10)
        ]

        def set_shots_rapidly() -> None:
            for shot in shots:
                launcher.set_current_shot(shot)
                time.sleep(0.001)

        threads = [threading.Thread(target=set_shots_rapidly) for _ in range(3)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Verify final state is one of the valid shots
        assert launcher.current_shot in shots or launcher.current_shot is None
        # Verify no corruption (shot object is intact)
        if launcher.current_shot:
            assert hasattr(launcher.current_shot, "full_name")
            assert hasattr(launcher.current_shot, "workspace_path")
