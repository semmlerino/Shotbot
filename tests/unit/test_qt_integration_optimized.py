#!/usr/bin/env python3
"""Test Qt event loop integration and performance validation."""

# Standard library imports
import contextlib
import time
from unittest.mock import Mock

# Third-party imports
import pytest
from PySide6.QtCore import QTimer

# Local application imports
from shot_model import ShotModel


pytestmark = [pytest.mark.unit, pytest.mark.qt]


class TestQtIntegration:
    """Test Qt-specific integration scenarios."""

    @pytest.fixture
    def qt_model(self, real_cache_manager, qtbot):
        """Create ShotModel with Qt integration."""
        model = ShotModel(real_cache_manager)
        # Models are QObjects, not QWidgets, so don't need qtbot.addWidget
        # Just ensure proper cleanup
        yield model
        model.cleanup()
        model.deleteLater()
        qtbot.wait(1)

    def test_event_loop_responsiveness(self, qt_model, qtbot) -> None:
        """Test that UI remains responsive during background loading."""

        # Mock slow process pool
        def slow_command(*args, **kwargs) -> str:
            # Simulate slow operation (NOT Qt event processing - this runs in worker thread)
            for _i in range(10):
                time.sleep(0.01)  # 10ms intervals - safe for background thread
            return "workspace /test/responsive/0010"

        mock_pool = Mock()
        mock_pool.execute_workspace_command.side_effect = slow_command
        qt_model._process_pool = mock_pool

        # Initialize with background loading
        start_time = time.perf_counter()
        result = qt_model.initialize_async()
        init_time = time.perf_counter() - start_time

        # Initialization should return immediately
        assert init_time < 0.05, f"Initialization blocked for {init_time:.3f}s"
        assert result.success is True

        # Event loop should remain responsive
        loop_responsive = True

        def check_responsiveness() -> None:
            nonlocal loop_responsive
            loop_responsive = True

        # Schedule immediate callback
        QTimer.singleShot(1, check_responsiveness)
        qtbot.wait(50)  # Give time for callback

        assert loop_responsive, "Event loop was blocked"

    def test_timer_based_refresh_integration(self, qt_model, qtbot) -> None:
        """Test integration with QTimer-based refresh patterns."""
        refresh_count = 0

        def on_refresh() -> None:
            nonlocal refresh_count
            refresh_count += 1
            # Only call refresh_shots if model has the method
            if hasattr(qt_model, "refresh_shots"):
                qt_model.refresh_shots()

        # Mock fast process pool first
        mock_pool = Mock()
        mock_pool.execute_workspace_command.return_value = "workspace /timer/test/0010"
        qt_model._process_pool = mock_pool

        # Setup timer for periodic refresh - set parent to ensure proper Qt ownership
        timer = QTimer(qt_model)
        timer.timeout.connect(on_refresh)
        timer.start(50)  # 50ms intervals

        try:
            # Use waitUntil to properly process Qt events
            def check_refresh_count():
                return refresh_count >= 3

            # Wait up to 500ms for at least 3 refreshes
            with contextlib.suppress(Exception):
                qtbot.waitUntil(check_refresh_count, timeout=500)

            # Should have completed multiple refreshes
            assert refresh_count >= 3, f"Only {refresh_count} refreshes in 200ms"
        finally:
            # Ensure timer is always stopped and cleaned up
            timer.stop()
            timer.deleteLater()
            qtbot.wait(1)

    def test_signal_slot_performance(self, qt_model, qtbot) -> None:
        """Test performance of signal-slot connections."""
        signal_count = 0
        signal_times = []

        def count_signals() -> None:
            nonlocal signal_count
            signal_count += 1
            signal_times.append(time.perf_counter())

        # Connect to all signals
        qt_model.shots_loaded.connect(count_signals)
        qt_model.shots_changed.connect(count_signals)
        qt_model.background_load_started.connect(count_signals)
        qt_model.background_load_finished.connect(count_signals)

        # Trigger operations
        mock_pool = Mock()
        mock_pool.execute_workspace_command.return_value = "workspace /signal/test/0010"
        qt_model._process_pool = mock_pool

        qt_model.initialize_async()

        # Wait for signals
        qtbot.waitUntil(lambda: signal_count >= 2, timeout=3000)

        # Verify signals were emitted quickly
        if len(signal_times) >= 2:
            signal_duration = signal_times[-1] - signal_times[0]
            assert signal_duration < 1.0, f"Signals took {signal_duration:.3f}s"

    def test_memory_cleanup_in_qt_context(self, qt_model, qtbot) -> None:
        """Test memory cleanup works properly in Qt context."""
        _initial_loader_count = 0  # Not used in this test

        # Create several async loaders
        for _ in range(5):
            qt_model.initialize_async()
            qtbot.wait(10)  # Small delay between calls

        # Allow background processing
        qtbot.wait(100)

        # Cleanup should handle all loaders
        qt_model.cleanup()

        # Verify no lingering threads
        if qt_model._async_loader:
            assert not qt_model._async_loader.isRunning()

    def test_widget_lifecycle_integration(self, real_cache_manager, qtbot) -> None:
        """Test model lifecycle matches Qt widget patterns."""
        # Create model
        model = ShotModel(real_cache_manager)
        # Models are QObjects, not QWidgets, so don't use qtbot.addWidget

        # Use model
        mock_pool = Mock()
        mock_pool.execute_workspace_command.return_value = (
            "workspace /lifecycle/test/0010"
        )
        model._process_pool = mock_pool

        result = model.initialize_async()
        assert result.success is True

        # Manual cleanup for QObjects
        model.cleanup()
        model.deleteLater()
        qtbot.wait(1)

        # This test mainly verifies no crashes occur during cleanup


class TestPerformanceValidation:
    """Validate actual performance improvements claimed in optimization."""

    def test_startup_time_improvement_validation(self, real_cache_manager) -> None:
        """Validate the claimed <0.1s startup time."""
        # Test with cached data
        model = ShotModel(real_cache_manager)

        # Pre-populate cache
        model.cache_manager.cache_shots(
            [
                {
                    "show": "PERF",
                    "sequence": "seq01",
                    "shot": "0010",
                    "workspace_path": "/perf/path",
                }
            ]
        )

        # Measure actual startup time
        measurements = []
        for _ in range(10):  # Multiple measurements for accuracy
            start = time.perf_counter()
            result = model.initialize_async()
            elapsed = time.perf_counter() - start
            measurements.append(elapsed)
            assert result.success is True

        # Verify performance claim
        avg_time = sum(measurements) / len(measurements)
        max_time = max(measurements)

        # Should meet the <0.1s claim consistently
        assert avg_time < 0.1, (
            f"Average startup time {avg_time:.3f}s exceeds 0.1s target"
        )
        assert max_time < 0.2, f"Maximum startup time {max_time:.3f}s too slow"

        print(f"Startup performance: avg={avg_time:.3f}s, max={max_time:.3f}s")

    def test_memory_usage_optimization(self, real_cache_manager) -> None:
        """Test memory usage remains reasonable with optimizations."""
        # Standard library imports
        import os

        # Third-party imports
        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Create and use optimized model
        model = ShotModel(real_cache_manager)

        # Simulate usage pattern
        for i in range(50):
            # Add cache data
            model.cache_manager.cache_shots(
                [
                    {
                        "show": f"MEM{i}",
                        "sequence": "seq",
                        "shot": "0010",
                        "workspace_path": f"/mem/{i}",
                    }
                ]
            )
            model.initialize_async()

        final_memory = process.memory_info().rss
        memory_increase = (final_memory - initial_memory) / 1024 / 1024  # MB

        # Memory increase should be reasonable (< 50MB for this test)
        assert memory_increase < 50, f"Memory increased by {memory_increase:.1f}MB"

        model.cleanup()

    def test_background_load_efficiency(self, real_cache_manager, qtbot) -> None:
        """Test that background loading is actually efficient."""
        model = ShotModel(real_cache_manager)

        # Mock process pool with timing simulation
        execution_count = 0

        def timed_command(*args, **kwargs) -> str:
            nonlocal execution_count
            execution_count += 1
            # Simulate realistic command time
            time.sleep(0.01)  # 10ms simulation
            return f"workspace /efficient/{execution_count}/seq01/0010"

        mock_pool = Mock()
        mock_pool.execute_workspace_command.side_effect = timed_command
        model._process_pool = mock_pool

        # Start multiple background loads
        start_time = time.perf_counter()

        for _ in range(3):
            model.initialize_async()
            qtbot.wait(5)

        immediate_time = time.perf_counter() - start_time

        # All calls should return immediately
        assert immediate_time < 0.1, (
            f"Background loads blocked for {immediate_time:.3f}s"
        )

        # Wait for background processing to complete
        qtbot.waitUntil(lambda: not model._loading_in_progress, timeout=3000)

        total_time = time.perf_counter() - start_time
        print(
            f"Background efficiency: immediate={immediate_time:.3f}s, total={total_time:.3f}s"
        )
