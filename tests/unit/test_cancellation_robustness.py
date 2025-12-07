"""Tests for CancellationEvent robustness under edge conditions.

This module tests the CancellationEvent class for:

1. Callback exception isolation (one failure doesn't stop others)
2. Concurrent cancel() calls from multiple threads
3. Cancel during callback execution
4. Idempotent behavior

These tests verify the cancellation system handles edge cases gracefully.
"""

from __future__ import annotations

import threading
import time

import pytest

from threading_utils import CancellationEvent


pytestmark = [
    pytest.mark.unit,
    pytest.mark.thread_safety,
]


class TestCallbackExceptionIsolation:
    """Tests that callback exceptions don't prevent other callbacks."""

    def test_exception_in_first_callback_doesnt_stop_others(self) -> None:
        """Exception in first callback doesn't prevent subsequent callbacks."""
        event = CancellationEvent()

        results: list[str] = []

        def callback1() -> None:
            raise ValueError("Intentional test exception")

        def callback2() -> None:
            results.append("callback2_executed")

        def callback3() -> None:
            results.append("callback3_executed")

        # Register all callbacks
        event.add_cleanup_callback(callback1)
        event.add_cleanup_callback(callback2)
        event.add_cleanup_callback(callback3)

        # Cancel - should execute all callbacks despite exception
        event.cancel()

        # Callbacks 2 and 3 should have executed
        assert "callback2_executed" in results
        assert "callback3_executed" in results

    def test_multiple_exceptions_dont_stop_execution(self) -> None:
        """Multiple failing callbacks don't prevent remaining callbacks."""
        event = CancellationEvent()

        results: list[str] = []

        def failing_callback1() -> None:
            raise ValueError("First exception")

        def failing_callback2() -> None:
            raise RuntimeError("Second exception")

        def working_callback() -> None:
            results.append("working_callback_executed")

        # Register in order: fail, fail, work
        event.add_cleanup_callback(failing_callback1)
        event.add_cleanup_callback(failing_callback2)
        event.add_cleanup_callback(working_callback)

        # Cancel
        event.cancel()

        # Working callback should still execute
        assert "working_callback_executed" in results

    def test_all_callbacks_failing_doesnt_crash(self) -> None:
        """All callbacks failing doesn't crash the cancellation."""
        event = CancellationEvent()

        def failing_callback() -> None:
            raise ValueError("Intentional failure")

        # Register multiple failing callbacks
        for _ in range(5):
            event.add_cleanup_callback(failing_callback)

        # Cancel should complete without raising
        event.cancel()  # Should not raise

        # Verify cancellation state
        assert event.is_cancelled()


class TestConcurrentCancelCalls:
    """Tests for concurrent cancel() calls from multiple threads."""

    def test_concurrent_cancel_is_idempotent(self) -> None:
        """Multiple concurrent cancel() calls only execute callbacks once."""
        event = CancellationEvent()

        execution_count = 0
        count_lock = threading.Lock()

        def counting_callback() -> None:
            nonlocal execution_count
            with count_lock:
                execution_count += 1

        event.add_cleanup_callback(counting_callback)

        # Launch multiple threads to cancel concurrently
        threads = []
        for i in range(10):
            t = threading.Thread(target=event.cancel, name=f"CancelThread-{i}")
            threads.append(t)

        # Start all threads simultaneously
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join(timeout=2.0)

        # Callback should have executed exactly once
        assert execution_count == 1, f"Callback executed {execution_count} times"

    def test_concurrent_cancel_with_slow_callback(self) -> None:
        """Concurrent cancel() calls with slow callback still idempotent."""
        event = CancellationEvent()

        execution_count = 0
        count_lock = threading.Lock()

        def slow_callback() -> None:
            nonlocal execution_count
            time.sleep(0.1)  # Simulate slow cleanup
            with count_lock:
                execution_count += 1

        event.add_cleanup_callback(slow_callback)

        # Launch multiple threads to cancel concurrently
        threads = []
        for i in range(5):
            t = threading.Thread(target=event.cancel, name=f"CancelThread-{i}")
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join(timeout=2.0)

        # Still should only execute once
        assert execution_count == 1

    def test_cancel_from_callback_thread_is_safe(self) -> None:
        """Calling cancel() from within a callback is safe (idempotent)."""
        event = CancellationEvent()

        nested_cancel_called = False

        def callback_that_cancels_again() -> None:
            nonlocal nested_cancel_called
            # Try to cancel again from within callback
            event.cancel()  # Should be idempotent
            nested_cancel_called = True

        event.add_cleanup_callback(callback_that_cancels_again)
        event.cancel()

        assert nested_cancel_called
        assert event.is_cancelled()


class TestCallbackRegistrationRaces:
    """Tests for callback registration during cancellation."""

    def test_callback_added_during_cancellation_may_not_execute(self) -> None:
        """Callbacks added during cancel() execution may not execute.

        This is expected behavior - callbacks are copied at start of cancel().
        """
        event = CancellationEvent()

        late_callback_executed = False

        def callback_that_adds_callback() -> None:
            nonlocal late_callback_executed

            def late_callback() -> None:
                nonlocal late_callback_executed
                late_callback_executed = True

            # Add callback during cancellation
            event.add_cleanup_callback(late_callback)

        event.add_cleanup_callback(callback_that_adds_callback)
        event.cancel()

        # Late callback may or may not execute depending on timing
        # The important thing is it doesn't crash
        # (Implementation detail: callbacks are copied at start of cancel())

    def test_concurrent_add_and_cancel_no_crash(self) -> None:
        """Concurrent add_cleanup_callback() and cancel() don't crash."""
        event = CancellationEvent()

        errors: list[Exception] = []

        def add_callbacks() -> None:
            """Repeatedly add callbacks."""
            try:
                for i in range(50):
                    event.add_cleanup_callback(lambda: None)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def do_cancel() -> None:
            """Wait a bit then cancel."""
            try:
                time.sleep(0.01)
                event.cancel()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=add_callbacks),
            threading.Thread(target=do_cancel),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        assert not errors, f"Concurrent operations caused errors: {errors}"


class TestCancellationStateConsistency:
    """Tests for cancellation state consistency."""

    def test_is_cancelled_reflects_state_immediately(self) -> None:
        """is_cancelled() returns True immediately after cancel() returns."""
        event = CancellationEvent()

        assert not event.is_cancelled()
        event.cancel()
        assert event.is_cancelled()

    def test_is_cancelled_visible_from_other_threads(self) -> None:
        """is_cancelled() state is visible from other threads immediately."""
        event = CancellationEvent()

        seen_cancelled: list[bool] = []
        check_complete = threading.Event()

        def checker() -> None:
            """Check is_cancelled() in loop until cancelled."""
            while not event.is_cancelled():
                time.sleep(0.001)
            seen_cancelled.append(True)
            check_complete.set()

        checker_thread = threading.Thread(target=checker)
        checker_thread.start()

        # Small delay to ensure checker is running
        time.sleep(0.01)

        # Cancel from main thread
        event.cancel()

        # Checker should see cancellation quickly
        assert check_complete.wait(timeout=1.0), "Checker didn't see cancellation"
        checker_thread.join(timeout=1.0)

        assert seen_cancelled == [True]

    def test_wait_for_cancellation_returns_on_cancel(self) -> None:
        """wait_for_cancellation() returns when cancel() is called."""
        event = CancellationEvent()

        wait_result: list[bool] = []

        def waiter() -> None:
            result = event.wait_for_cancellation(timeout=5.0)
            wait_result.append(result)

        waiter_thread = threading.Thread(target=waiter)
        waiter_thread.start()

        # Small delay then cancel
        time.sleep(0.05)
        event.cancel()

        # Waiter should return quickly
        waiter_thread.join(timeout=1.0)
        assert not waiter_thread.is_alive()
        assert wait_result == [True]

    def test_wait_for_cancellation_times_out(self) -> None:
        """wait_for_cancellation() returns False on timeout."""
        event = CancellationEvent()

        # Very short timeout, no cancel
        result = event.wait_for_cancellation(timeout=0.05)

        assert result is False
        assert not event.is_cancelled()


class TestCallbackExecutionOrder:
    """Tests for callback execution ordering."""

    def test_callbacks_execute_in_registration_order(self) -> None:
        """Callbacks execute in the order they were registered."""
        event = CancellationEvent()

        execution_order: list[int] = []

        def make_callback(n: int) -> None:
            def callback() -> None:
                execution_order.append(n)

            return callback

        # Register callbacks in order
        for i in range(5):
            event.add_cleanup_callback(make_callback(i))

        event.cancel()

        # Should execute in registration order
        assert execution_order == [0, 1, 2, 3, 4]


class TestCancellationStats:
    """Tests for cancellation statistics."""

    def test_stats_reflect_state(self) -> None:
        """get_stats() reflects current state accurately."""
        event = CancellationEvent()

        # Before any callbacks
        stats = event.get_stats()
        assert stats["cancelled"] is False
        assert stats["callback_count"] == 0
        assert stats["cancel_time"] is None

        # Add callbacks
        event.add_cleanup_callback(lambda: None)
        event.add_cleanup_callback(lambda: None)

        stats = event.get_stats()
        assert stats["callback_count"] == 2
        assert stats["cancelled"] is False

        # After cancellation
        event.cancel()

        stats = event.get_stats()
        assert stats["cancelled"] is True
        assert stats["cancel_time"] is not None
        assert isinstance(stats["cancel_time"], float)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_cancel_with_no_callbacks(self) -> None:
        """cancel() with no registered callbacks doesn't crash."""
        event = CancellationEvent()

        # No callbacks registered
        event.cancel()

        assert event.is_cancelled()

    def test_add_callback_after_cancel(self) -> None:
        """Adding callback after cancel() doesn't crash (but won't execute)."""
        event = CancellationEvent()

        event.cancel()

        executed = False

        def late_callback() -> None:
            nonlocal executed
            executed = True

        # Add after cancel
        event.add_cleanup_callback(late_callback)

        # Callback should NOT execute (cancel already happened)
        assert not executed

    def test_multiple_wait_calls(self) -> None:
        """Multiple wait_for_cancellation() calls work correctly."""
        event = CancellationEvent()

        results: list[bool] = []

        def waiter(timeout: float) -> None:
            result = event.wait_for_cancellation(timeout=timeout)
            results.append(result)

        # Multiple waiters
        threads = [
            threading.Thread(target=waiter, args=(5.0,)),
            threading.Thread(target=waiter, args=(5.0,)),
            threading.Thread(target=waiter, args=(5.0,)),
        ]

        for t in threads:
            t.start()

        # Cancel
        time.sleep(0.05)
        event.cancel()

        # All waiters should return True
        for t in threads:
            t.join(timeout=1.0)

        assert results == [True, True, True]

    def test_repr_includes_useful_info(self) -> None:
        """__repr__ includes id, cancelled state, and callback count."""
        event = CancellationEvent()
        event.add_cleanup_callback(lambda: None)

        repr_str = repr(event)

        assert "CancellationEvent" in repr_str
        assert "cancelled=False" in repr_str
        assert "callbacks=1" in repr_str
