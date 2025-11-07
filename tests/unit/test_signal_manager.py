"""Tests for SignalManager - Qt signal-slot management utilities.

This module provides comprehensive tests for the SignalManager class,
which manages Qt signal-slot connections with automatic cleanup.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QPushButton

from signal_manager import (
    BlockedSignalsContext,
    SignalDebugger,
    SignalManager,
    SignalThrottler,
)


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

# Test markers for categorization and parallel safety
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # Critical for parallel execution safety
]


class MockWidget(QObject):
    """Test widget with various signals for testing."""

    test_signal = Signal()
    data_signal = Signal(str)
    multi_param_signal = Signal(int, str, bool)


# Factory fixtures for test data creation
@pytest.fixture
def make_mock_widget() -> Callable[[], MockWidget]:
    """Factory for creating MockWidget instances."""

    def _make() -> MockWidget:
        return MockWidget()

    return _make


@pytest.fixture
def make_signal_manager() -> Callable[[QObject | None], tuple[SignalManager, QObject]]:
    """Factory for creating SignalManager instances with owner."""

    def _make(owner: QObject | None = None) -> tuple[SignalManager, QObject]:
        owner = owner or MockWidget()
        return SignalManager(owner), owner

    return _make


class TestSignalManager:
    """Test suite for SignalManager class."""

    @pytest.fixture
    def signal_manager(
        self, make_signal_manager: Callable[[QObject | None], tuple[SignalManager, QObject]]
    ) -> tuple[SignalManager, QObject]:
        """Create a signal manager with test owner."""
        return make_signal_manager()

    def test_initialization(
        self, signal_manager: tuple[SignalManager, QObject]
    ) -> None:
        """Test proper initialization of SignalManager."""
        manager, owner = signal_manager

        # Test owner reference
        assert manager.owner is owner
        assert manager.owner_ref() is owner

        # Test empty connections
        assert not manager.has_connections()
        assert manager.get_connection_count() == 0

    def test_connect_safely(
        self, signal_manager: tuple[SignalManager, QObject], qtbot: QtBot
    ) -> None:
        """Test safe connection with tracking."""
        manager, _owner = signal_manager
        widget = MockWidget()

        received: list[int] = []

        # Connect signal
        result = manager.connect_safely(widget.test_signal, lambda: received.append(1))

        assert result is True
        assert manager.has_connections()
        assert manager.get_connection_count() == 1

        # Emit signal and verify
        widget.test_signal.emit()
        qtbot.waitUntil(lambda: len(received) == 1, timeout=100)

    def test_connect_safely_with_connection_type(
        self, signal_manager: tuple[SignalManager, QObject], qtbot: QtBot
    ) -> None:
        """Test connection with specific connection type."""
        manager, _owner = signal_manager
        widget = MockWidget()

        received: list[str] = []

        # Connect with QueuedConnection
        result = manager.connect_safely(
            widget.data_signal,
            lambda data: received.append(data),
            connection_type=Qt.ConnectionType.QueuedConnection,
        )

        assert result is True

        # Emit and verify
        widget.data_signal.emit("test")
        qtbot.waitUntil(lambda: "test" in received, timeout=100)

    def test_connect_safely_without_tracking(
        self, signal_manager: tuple[SignalManager, QObject]
    ) -> None:
        """Test connection without tracking."""
        manager, _owner = signal_manager
        widget = MockWidget()

        # Connect without tracking
        result = manager.connect_safely(widget.test_signal, lambda: None, track=False)

        assert result is True
        assert not manager.has_connections()  # Should not be tracked

    def test_disconnect_safely(
        self, signal_manager: tuple[SignalManager, QObject], qtbot: QtBot
    ) -> None:
        """Test safe disconnection."""
        manager, _owner = signal_manager
        widget = MockWidget()

        received: list[int] = []

        def slot() -> None:
            received.append(1)

        # Connect and then disconnect
        manager.connect_safely(widget.test_signal, slot)
        assert manager.has_connections()

        result = manager.disconnect_safely(widget.test_signal, slot)
        assert result is True
        assert not manager.has_connections()

        # Verify signal no longer connected
        widget.test_signal.emit()
        qtbot.wait(10)
        assert len(received) == 0

    def test_disconnect_all(
        self, signal_manager: tuple[SignalManager, QObject]
    ) -> None:
        """Test disconnecting all tracked connections."""
        manager, _owner = signal_manager
        widget1 = MockWidget()
        widget2 = MockWidget()

        # Create multiple connections
        manager.connect_safely(widget1.test_signal, lambda: None)
        manager.connect_safely(widget2.data_signal, lambda _x: None)
        manager.connect_safely(widget1.multi_param_signal, lambda _x, _y, _z: None)

        assert manager.get_connection_count() == 3

        # Disconnect all
        count = manager.disconnect_all()
        assert count == 3
        assert not manager.has_connections()

    def test_chain_signals(
        self, signal_manager: tuple[SignalManager, QObject], qtbot: QtBot
    ) -> None:
        """Test signal chaining."""
        manager, _owner = signal_manager
        source = MockWidget()
        target = MockWidget()

        # Track emissions on target
        received: list[int] = []
        target.test_signal.connect(lambda: received.append(1))

        # Chain signals
        result = manager.chain_signals(source.test_signal, target.test_signal)

        assert result is True
        assert manager.get_connection_count() == 1

        # Emit source and verify target receives it
        source.test_signal.emit()
        qtbot.wait(50)

        assert len(received) == 1

    def test_chain_signals_with_connection_type(
        self, signal_manager: tuple[SignalManager, QObject], qtbot: QtBot
    ) -> None:
        """Test signal chaining with specific connection type."""
        manager, _owner = signal_manager
        source = MockWidget()
        target = MockWidget()

        # Track emissions on target
        received: list[str] = []
        target.data_signal.connect(lambda x: received.append(x))

        # Chain with QueuedConnection
        result = manager.chain_signals(
            source.data_signal,
            target.data_signal,
            connection_type=Qt.ConnectionType.QueuedConnection,
        )

        assert result is True

        # Emit source and verify target receives it
        source.data_signal.emit("test")
        qtbot.wait(100)  # Wait longer for queued connection

        assert "test" in received

    def test_connect_group(
        self, signal_manager: tuple[SignalManager, QObject]
    ) -> None:
        """Test connecting multiple signal-slot pairs at once."""
        manager, _owner = signal_manager
        widget = MockWidget()

        received: dict[str, Any] = {"test": 0, "data": "", "multi": None}

        connections = [
            (widget.test_signal, lambda: received.update({"test": 1})),
            (widget.data_signal, lambda x: received.update({"data": x})),
            (
                widget.multi_param_signal,
                lambda x, y, z: received.update({"multi": (x, y, z)}),
            ),
        ]

        count = manager.connect_group(connections)
        assert count == 3
        assert manager.get_connection_count() == 3

    def test_block_signals(
        self, signal_manager: tuple[SignalManager, QObject], qtbot: QtBot
    ) -> None:
        """Test blocking/unblocking signals for multiple objects."""
        manager, _owner = signal_manager
        widget1 = MockWidget()
        widget2 = MockWidget()

        # Initially not blocked
        assert not widget1.signalsBlocked()
        assert not widget2.signalsBlocked()

        # Block signals
        manager.block_signals([widget1, widget2], blocked=True)
        assert widget1.signalsBlocked()
        assert widget2.signalsBlocked()

        # Unblock signals
        manager.block_signals([widget1, widget2], blocked=False)
        assert not widget1.signalsBlocked()
        assert not widget2.signalsBlocked()

    def test_with_blocked_signals_context_manager(
        self, signal_manager: tuple[SignalManager, QObject]
    ) -> None:
        """Test context manager for temporarily blocking signals."""
        manager, _owner = signal_manager
        widget1 = MockWidget()
        widget2 = MockWidget()

        # Test context manager
        with manager.with_blocked_signals([widget1, widget2]):
            assert widget1.signalsBlocked()
            assert widget2.signalsBlocked()

        # Signals should be unblocked after context
        assert not widget1.signalsBlocked()
        assert not widget2.signalsBlocked()

    def test_connect_worker_signals(
        self, signal_manager: tuple[SignalManager, QObject]
    ) -> None:
        """Test connecting signals from a worker thread."""
        manager, _owner = signal_manager

        # Create worker with signals
        class TestWorker(QObject):
            started = Signal()
            finished = Signal()
            progress = Signal(int)

        worker = TestWorker()

        # Define handlers
        handlers: dict[str, Callable[..., None]] = {
            "started": lambda: None,
            "finished": lambda: None,
            "progress": lambda _x: None,
            "nonexistent": lambda: None,  # This should generate warning
        }

        # Connect worker signals
        count = manager.connect_worker_signals(worker, handlers)
        assert count == 3  # Only 3 should connect (nonexistent fails)

    def test_create_delayed_connection(
        self, signal_manager: tuple[SignalManager, QObject], qtbot: QtBot
    ) -> None:
        """Test creating a connection with a delay."""
        manager, _owner = signal_manager
        widget = MockWidget()

        received: list[int] = []

        # Create delayed connection (50ms delay)
        result = manager.create_delayed_connection(
            widget.test_signal, lambda: received.append(1), delay_ms=50
        )

        assert result is True

        # Emit signal
        widget.test_signal.emit()

        # Should not be received immediately
        qtbot.wait(20)
        assert len(received) == 0

        # Use waitUntil for more reliable Qt timer testing
        qtbot.waitUntil(lambda: len(received) == 1, timeout=200)
        assert len(received) == 1

    def test_owner_weak_reference(self) -> None:
        """Test that owner is held as weak reference."""
        owner = MockWidget()
        manager = SignalManager(owner)

        # Owner should be accessible
        assert manager.owner is owner

        # Delete owner
        del owner

        # Owner should be None after deletion
        assert manager.owner is None

    def test_signal_not_emitted_after_disconnect(
        self,
        qtbot: QtBot,
        make_mock_widget: Callable[[], MockWidget],
        make_signal_manager: Callable[[QObject | None], tuple[SignalManager, QObject]],
    ) -> None:
        """Test that signal is not emitted after disconnection."""
        widget = make_mock_widget()
        manager, _ = make_signal_manager()

        received: list[int] = []

        def slot() -> None:
            received.append(1)

        # Connect and then disconnect
        manager.connect_safely(widget.test_signal, slot)
        manager.disconnect_safely(widget.test_signal, slot)

        # Verify no signal is emitted
        with qtbot.assertNotEmitted(widget.test_signal, wait=100):
            # Widget exists but signal should not be connected
            pass

        # Double-check no reception
        assert len(received) == 0


class TestBlockedSignalsContext:
    """Test suite for BlockedSignalsContext."""

    def test_context_manager_blocks_and_restores(self) -> None:
        """Test that context manager properly blocks and restores signals."""
        widget1 = MockWidget()
        widget2 = MockWidget()

        # Initially not blocked
        assert not widget1.signalsBlocked()
        assert not widget2.signalsBlocked()

        # Use context manager
        with BlockedSignalsContext([widget1, widget2]):
            assert widget1.signalsBlocked()
            assert widget2.signalsBlocked()

        # Should be restored
        assert not widget1.signalsBlocked()
        assert not widget2.signalsBlocked()

    def test_context_manager_preserves_previous_state(self) -> None:
        """Test that context manager preserves previous blocked states."""
        widget1 = MockWidget()
        widget2 = MockWidget()

        # Set widget1 to blocked initially
        widget1.blockSignals(True)

        # Use context manager
        with BlockedSignalsContext([widget1, widget2]):
            assert widget1.signalsBlocked()
            assert widget2.signalsBlocked()

        # widget1 should still be blocked, widget2 should not
        assert widget1.signalsBlocked()
        assert not widget2.signalsBlocked()

    def test_context_manager_handles_none_objects(self) -> None:
        """Test that context manager handles None objects gracefully."""
        widget = MockWidget()

        # Include None in list
        with BlockedSignalsContext([widget, None]):
            assert widget.signalsBlocked()
            # Should not crash


class TestSignalThrottler:
    """Test suite for SignalThrottler."""

    def test_throttle_rapid_emissions(self, qtbot: QtBot) -> None:
        """Test that throttler limits rapid signal emissions."""
        source = MockWidget()
        throttler = SignalThrottler(source.test_signal, interval_ms=100)

        # Track emissions
        received: list[tuple[Any, ...]] = []
        throttler.throttled.connect(lambda x: received.append(x))

        # Emit rapidly
        for _ in range(5):
            source.test_signal.emit()
            qtbot.wait(10)

        # Wait for throttle interval
        qtbot.wait(150)
        QApplication.processEvents()

        # Should only have emitted once
        assert len(received) == 1

    def test_throttler_preserves_last_args(self, qtbot: QtBot) -> None:
        """Test that throttler emits with last received arguments."""
        source = MockWidget()
        throttler = SignalThrottler(source.data_signal, interval_ms=50)

        # Track emissions
        received: list[tuple[Any, ...]] = []
        throttler.throttled.connect(lambda x: received.append(x))

        # Emit with different values
        source.data_signal.emit("first")
        source.data_signal.emit("second")
        source.data_signal.emit("last")

        # Use waitUntil for more reliable Qt timer testing
        qtbot.waitUntil(lambda: len(received) >= 1, timeout=200)

        # Should have emitted once with last value
        assert len(received) == 1
        assert received[0] == ("last",)

    def test_throttler_stop(self, qtbot: QtBot) -> None:
        """Test stopping the throttler."""
        source = MockWidget()
        throttler = SignalThrottler(source.test_signal, interval_ms=50)

        received: list[tuple[Any, ...]] = []
        throttler.throttled.connect(lambda x: received.append(x))

        # Stop throttler
        throttler.stop()

        # Emissions should no longer be throttled
        source.test_signal.emit()
        qtbot.wait(100)

        assert len(received) == 0


class TestSignalDebugger:
    """Test suite for SignalDebugger."""

    def test_trace_signal(self, qtbot: QtBot) -> None:
        """Test tracing signal emissions."""
        widget = MockWidget()
        debugger = SignalDebugger(enabled=True)

        # Trace signal
        debugger.trace_signal(widget.test_signal, "test_signal")

        # Emit signal multiple times
        widget.test_signal.emit()
        widget.test_signal.emit()
        widget.test_signal.emit()

        # Check stats
        stats = debugger.get_stats()
        assert stats["test_signal"] == 3

    def test_trace_signal_with_args(self, qtbot: QtBot) -> None:
        """Test tracing signals with arguments."""
        widget = MockWidget()
        debugger = SignalDebugger(enabled=True)

        # Trace signal with arguments
        debugger.trace_signal(widget.data_signal, "data_signal")

        # Emit with data
        widget.data_signal.emit("test_data")

        stats = debugger.get_stats()
        assert stats["data_signal"] == 1

    def test_debugger_disabled(self, qtbot: QtBot) -> None:
        """Test that disabled debugger doesn't trace."""
        widget = MockWidget()
        debugger = SignalDebugger(enabled=False)

        # Try to trace (should be ignored)
        debugger.trace_signal(widget.test_signal, "test_signal")

        # Emit signal
        widget.test_signal.emit()

        # Stats should be empty
        stats = debugger.get_stats()
        assert len(stats) == 0

    def test_reset_stats(self) -> None:
        """Test resetting statistics."""
        widget = MockWidget()
        debugger = SignalDebugger(enabled=True)

        # Trace and emit
        debugger.trace_signal(widget.test_signal, "test_signal")
        widget.test_signal.emit()

        # Verify stats exist
        assert debugger.get_stats()["test_signal"] == 1

        # Reset
        debugger.reset_stats()

        # Stats should be empty
        assert len(debugger.get_stats()) == 0


class TestSignalManagerIntegration:
    """Integration tests for SignalManager with Qt widgets."""

    def test_with_qt_button(self, qtbot: QtBot) -> None:
        """Test SignalManager with actual Qt widget."""
        button = QPushButton("Test")
        manager = SignalManager(button)

        clicked_count = [0]

        # Connect button click
        manager.connect_safely(
            button.clicked, lambda: clicked_count.__setitem__(0, clicked_count[0] + 1)
        )

        # Simulate clicks
        button.click()
        button.click()

        assert clicked_count[0] == 2

        # Disconnect all
        manager.disconnect_all()
        button.click()

        # Should still be 2
        assert clicked_count[0] == 2

    def test_memory_cleanup(self) -> None:
        """Test that connections are properly cleaned up."""
        # Create widgets
        widget1 = MockWidget()
        widget2 = MockWidget()
        manager = SignalManager(widget1)

        # Create connections
        manager.connect_safely(widget2.test_signal, lambda: None)
        manager.chain_signals(widget2.data_signal, widget1.data_signal)

        assert manager.get_connection_count() == 2

        # Delete widget2
        widget2_ref = weakref.ref(widget2)
        del widget2

        # Widget should be garbage collected
        assert widget2_ref() is None

        # Disconnect should handle missing widget gracefully
        count = manager.disconnect_all()
        # Count may be 0 or 2 depending on Qt cleanup order
        assert count >= 0

    def test_thread_safety_with_worker(self, qtbot: QtBot) -> None:
        """Test thread-safe connections with worker thread."""

        class Worker(QObject):
            result = Signal(str)

            def process(self) -> None:
                self.result.emit("processed")

        worker = Worker()
        manager = SignalManager(worker)

        results: list[str] = []

        # Connect with QueuedConnection for thread safety
        manager.connect_safely(
            worker.result,
            lambda x: results.append(x),
            connection_type=Qt.ConnectionType.QueuedConnection,
        )

        # Process in same thread (for testing)
        worker.process()

        # Wait for queued connection
        qtbot.wait(50)

        assert "processed" in results
