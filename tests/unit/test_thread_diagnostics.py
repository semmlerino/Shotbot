"""Tests for thread diagnostics infrastructure."""

from __future__ import annotations

import threading
import time

import pytest

from workers.thread_diagnostics import ThreadDiagnosticReport, ThreadDiagnostics


class TestThreadDiagnosticReport:
    """Tests for ThreadDiagnosticReport dataclass."""

    def test_create_report(self) -> None:
        """Test creating a diagnostic report."""
        report = ThreadDiagnosticReport(
            thread_id=12345,
            thread_name="test-thread",
            stack_trace=["line1", "line2"],
            state="RUNNING",
            time_running_seconds=5.5,
            abandon_reason="test reason",
        )

        assert report.thread_id == 12345
        assert report.thread_name == "test-thread"
        assert report.stack_trace == ["line1", "line2"]
        assert report.state == "RUNNING"
        assert report.time_running_seconds == 5.5
        assert report.abandon_reason == "test reason"
        assert report.timestamp > 0

    def test_format_summary(self) -> None:
        """Test formatting a summary of the report."""
        report = ThreadDiagnosticReport(
            thread_id=12345,
            thread_name="test-thread",
            stack_trace=["  File 'a.py'", "  File 'b.py'", "  File 'c.py'"],
            state="RUNNING",
            time_running_seconds=5.5,
            abandon_reason="test reason",
        )

        summary = report.format_summary()

        assert "test-thread" in summary
        assert "12345" in summary
        assert "RUNNING" in summary
        assert "5.5" in summary
        assert "test reason" in summary


class TestThreadDiagnostics:
    """Tests for ThreadDiagnostics class."""

    @pytest.fixture(autouse=True)
    def reset_diagnostics(self) -> None:
        """Reset diagnostics state before each test."""
        ThreadDiagnostics.reset()

    def test_capture_current_thread_state(self) -> None:
        """Test capturing state of the current thread."""
        thread = threading.current_thread()
        start_time = time.time() - 1.0  # 1 second ago

        report = ThreadDiagnostics.capture_thread_state(thread, start_time)

        assert isinstance(report, ThreadDiagnosticReport)
        assert report.thread_id > 0
        assert report.thread_name == thread.name
        assert len(report.stack_trace) > 0  # Should have captured stack
        assert report.state in ("ALIVE", "DEAD")
        assert report.time_running_seconds >= 1.0

    def test_capture_thread_state_without_start_time(self) -> None:
        """Test capturing state without start time."""
        thread = threading.current_thread()

        report = ThreadDiagnostics.capture_thread_state(thread)

        assert report.time_running_seconds == 0.0

    def test_log_abandonment_records_metrics(self) -> None:
        """Test that log_abandonment records metrics."""
        thread = threading.current_thread()
        report = ThreadDiagnostics.capture_thread_state(thread)

        ThreadDiagnostics.log_abandonment(thread, "test reason", report)

        metrics = ThreadDiagnostics.get_abandonment_metrics()
        assert metrics["total_abandoned"] == 1
        assert "test reason" in metrics["recent_reasons"]

    def test_log_abandonment_sets_reason(self) -> None:
        """Test that log_abandonment sets the abandon reason on the report."""
        thread = threading.current_thread()
        report = ThreadDiagnostics.capture_thread_state(thread)
        assert report.abandon_reason == ""

        ThreadDiagnostics.log_abandonment(thread, "test reason", report)

        assert report.abandon_reason == "test reason"

    def test_get_abandonment_metrics_empty(self) -> None:
        """Test metrics when no abandonments have occurred."""
        metrics = ThreadDiagnostics.get_abandonment_metrics()

        assert metrics["total_captured"] == 0
        assert metrics["total_abandoned"] == 0
        assert metrics["recent_reasons"] == []
        assert metrics["avg_runtime_before_abandon"] == 0.0

    def test_get_abandonment_metrics_with_data(self) -> None:
        """Test metrics with multiple abandonments."""
        thread = threading.current_thread()

        for i in range(3):
            report = ThreadDiagnostics.capture_thread_state(
                thread, time.time() - (i + 1)
            )
            ThreadDiagnostics.log_abandonment(thread, f"reason-{i}", report)

        metrics = ThreadDiagnostics.get_abandonment_metrics()

        assert metrics["total_captured"] == 3
        assert metrics["total_abandoned"] == 3
        assert len(metrics["recent_reasons"]) == 3
        assert metrics["avg_runtime_before_abandon"] > 0

    def test_get_recent_reports(self) -> None:
        """Test getting recent abandonment reports."""
        thread = threading.current_thread()

        for i in range(5):
            report = ThreadDiagnostics.capture_thread_state(thread)
            ThreadDiagnostics.log_abandonment(thread, f"reason-{i}", report)

        reports = ThreadDiagnostics.get_recent_reports(count=3)

        assert len(reports) == 3
        # Most recent should be last
        assert reports[-1].abandon_reason == "reason-4"

    def test_reset_clears_state(self) -> None:
        """Test that reset clears all state."""
        thread = threading.current_thread()
        report = ThreadDiagnostics.capture_thread_state(thread)
        ThreadDiagnostics.log_abandonment(thread, "test", report)

        metrics_before = ThreadDiagnostics.get_abandonment_metrics()
        assert metrics_before["total_abandoned"] == 1

        ThreadDiagnostics.reset()

        metrics_after = ThreadDiagnostics.get_abandonment_metrics()
        assert metrics_after["total_captured"] == 0
        assert metrics_after["total_abandoned"] == 0

    def test_thread_safety(self) -> None:
        """Test that diagnostics are thread-safe."""
        results: list[bool] = []

        def worker() -> None:
            try:
                thread = threading.current_thread()
                for _ in range(10):
                    report = ThreadDiagnostics.capture_thread_state(thread)
                    ThreadDiagnostics.log_abandonment(thread, "concurrent", report)
                results.append(True)
            except Exception:  # noqa: BLE001
                results.append(False)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)
        assert len(results) == 5

        metrics = ThreadDiagnostics.get_abandonment_metrics()
        assert metrics["total_abandoned"] == 50  # 5 threads * 10 abandonments each
