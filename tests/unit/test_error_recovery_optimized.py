#!/usr/bin/env python3
"""Test error recovery scenarios for ShotModel."""

# Standard library imports
import time
from typing import NoReturn

# Third-party imports
import pytest
from PySide6.QtTest import QSignalSpy

# Local application imports
from shot_model import AsyncShotLoader, ShotModel


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]


# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
class TestProcessPoolDouble:
    """Test double for process pool that can simulate failures."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self, failure_mode=None) -> None:
        self.failure_mode = failure_mode
        self.call_count = 0

    def execute_workspace_command(self, command=None, **kwargs) -> str:
        """Simulate workspace command with controllable failures."""
        self.call_count += 1

        if self.failure_mode == "network_error" and self.call_count == 1:
            raise ConnectionError("Network unreachable")
        if self.failure_mode == "permission_error":
            raise PermissionError("Access denied")
        if self.failure_mode == "timeout_error":
            raise TimeoutError("Command timed out")

        return "workspace /shows/recovered/seq01/0010"


class TestErrorRecovery:
    """Test error handling and recovery in optimized shot model."""

    @pytest.fixture
    def error_prone_model(self, real_cache_manager):
        """Create model for error testing."""
        return ShotModel(real_cache_manager)

    def test_network_failure_recovery(self, error_prone_model, qtbot) -> None:
        """Test recovery from network/filesystem failures."""
        # Use test double that fails first, then succeeds
        failing_pool = TestProcessPoolDouble(failure_mode="network_error")
        error_prone_model._process_pool = failing_pool

        # Setup signal spy for error
        error_spy = QSignalSpy(error_prone_model.error_occurred)

        # First call should fail
        result1 = error_prone_model.initialize_async()
        assert result1.success is True  # initialize_async always returns True

        # Wait for error signal
        qtbot.waitUntil(lambda: error_spy.count() > 0, timeout=3000)

        # Verify error was handled
        assert error_spy.count() == 1
        error_message = error_spy.at(0)[0]
        assert "Network unreachable" in error_message

        # Second call should succeed (failure_mode only affects first call)
        result2 = error_prone_model.refresh_shots()
        assert result2.success is True

    def test_timeout_handling(self, error_prone_model, qtbot) -> None:
        """Test handling of command timeouts."""
        # Use test double that simulates timeout
        timeout_pool = TestProcessPoolDouble(failure_mode="timeout_error")
        error_prone_model._process_pool = timeout_pool

        # Should handle timeout gracefully
        error_spy = QSignalSpy(error_prone_model.error_occurred)

        start_time = time.perf_counter()
        result = error_prone_model.initialize_async()
        assert result.success is True  # initialize_async always returns True

        # Should return immediately even if background times out
        elapsed = time.perf_counter() - start_time
        assert elapsed < 0.1, "Initialization should return immediately"

        # Wait for error signal from background timeout
        qtbot.waitUntil(lambda: error_spy.count() > 0, timeout=3000)
        assert error_spy.count() == 1
        assert "timed out" in error_spy.at(0)[0].lower()

    def test_corrupted_cache_recovery(self, error_prone_model, tmp_path) -> None:
        """Test recovery from corrupted cache data."""
        # Create corrupted cache file to trigger error
        cache_dir = tmp_path / "corrupted_cache"
        cache_dir.mkdir()

        # Write invalid data to cache file
        cache_file = cache_dir / "shots_cache.json"
        cache_file.write_text("invalid json data {corrupt")

        # Replace cache manager with one using corrupted cache
        # Local application imports
        from cache_manager import (
            CacheManager,
        )

        corrupted_cache = CacheManager(cache_dir=cache_dir)
        error_prone_model.cache_manager = corrupted_cache

        # Should handle corrupted cache gracefully
        result = error_prone_model.initialize_async()

        # Should fall back to empty data and trigger background refresh
        assert result.success is True
        assert len(error_prone_model.shots) == 0

    def test_process_pool_failure_fallback(self, error_prone_model) -> None:
        """Test fallback when process pool is unavailable."""
        # Set None process pool to simulate unavailability
        error_prone_model._process_pool = None

        result = error_prone_model.refresh_shots()

        # Should handle gracefully - returns success but with no shots
        assert result.success is True  # Still returns True even with no pool
        assert len(error_prone_model.shots) == 0  # But no shots loaded
        # Should not crash the application

    def test_async_loader_exception_handling(self, qtbot) -> None:
        """Test AsyncShotLoader handles exceptions properly."""

        # Create failing process pool using test double
        class CriticalErrorPool:
            def execute_workspace_command(self, command=None, **kwargs) -> NoReturn:
                raise RuntimeError("Critical error")

        failing_pool = CriticalErrorPool()

        # Need to provide parse_function (from UNIFIED_TESTING_GUIDE)
        # Local application imports
        from base_shot_model import (
            BaseShotModel,
        )

        base_model = BaseShotModel(
            load_cache=False
        )  # Don't load cache to avoid corruption

        loader = AsyncShotLoader(
            failing_pool, parse_function=base_model._parse_ws_output
        )
        # Note: AsyncShotLoader is a QThread, not a QWidget, so no addWidget needed

        error_spy = QSignalSpy(loader.load_failed)
        success_spy = QSignalSpy(loader.shots_loaded)

        loader.start()
        assert loader.wait(3000)

        # Error signal should be emitted, not success
        assert error_spy.count() == 1
        assert success_spy.count() == 0
        assert "Critical error" in error_spy.at(0)[0]

    def test_partial_data_handling(self, tmp_path) -> None:
        """Test handling of partial or malformed workspace data."""
        # Test the parsing directly without async complications
        # Local application imports
        from cache_manager import (
            CacheManager,
        )
        from config import (
            Config,
        )

        # Use test double returning partial data with dynamic SHOWS_ROOT
        class TestProcessPool:  # Named to match the check in refresh_strategy
            def execute_workspace_command(self, command=None, **kwargs) -> str:
                # Use Config.SHOWS_ROOT for proper test isolation
                shows_root = Config.SHOWS_ROOT
                return f"""workspace {shows_root}/test/shots/seq01/seq01_0010
invalid line without workspace prefix
workspace {shows_root}/test/shots/seq02/seq02_0020
workspace incomplete_path_without_enough_parts
workspace {shows_root}/test/shots/seq03/seq03_0030"""

        # Use regular ShotModel (not Optimized) for simpler synchronous testing
        # Local application imports
        from shot_model import (
            ShotModel,
        )

        model = ShotModel(CacheManager(cache_dir=tmp_path / "cache"), load_cache=False)
        model._process_pool = TestProcessPool()

        result = model.refresh_shots()

        # Should parse valid entries and skip invalid ones
        assert result.success is True
        assert len(model.shots) == 3  # Only valid entries

        # Verify valid shots were parsed correctly
        shot_names = [shot.shot for shot in model.shots]
        assert "0010" in shot_names
        assert "0020" in shot_names
        assert "0030" in shot_names

        # All shots should be from the "test" show
        assert all(shot.show == "test" for shot in model.shots)

    def test_cleanup_after_error(self, error_prone_model) -> None:
        """Test that cleanup works properly after errors."""

        # Cause an error state using test double
        class ErrorPool:
            def execute_workspace_command(self, command=None, **kwargs) -> NoReturn:
                raise Exception("Setup error")

        error_pool = ErrorPool()
        error_prone_model._process_pool = error_pool

        # Try to initialize (will fail)
        error_prone_model.initialize_async()

        # Cleanup should work without hanging
        start_time = time.perf_counter()
        error_prone_model.cleanup()
        cleanup_time = time.perf_counter() - start_time

        # Cleanup should complete quickly
        assert cleanup_time < 2.0, f"Cleanup took {cleanup_time:.3f}s, too slow"

    def test_error_metrics_tracking(self, error_prone_model, qtbot) -> None:
        """Test that errors are tracked in performance metrics."""

        # Use test double that always fails
        class TrackedErrorPool:
            def execute_workspace_command(self, command=None, **kwargs) -> NoReturn:
                raise RuntimeError("Tracked error")

        error_pool = TrackedErrorPool()
        error_prone_model._process_pool = error_pool

        # Attempt operations that will fail
        error_prone_model.initialize_async()

        # Wait a moment for background processing
        qtbot.wait(100)  # 100ms for async processing

        # Metrics should be available even after errors
        metrics = error_prone_model.get_performance_metrics()
        assert isinstance(metrics, dict)
        assert "cache_hit_count" in metrics
        assert "cache_miss_count" in metrics
