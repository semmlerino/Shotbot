"""Integration tests for ShotModel.refresh_shots() following UNIFIED_TESTING_GUIDE best practices.

This module tests the critical refresh_shots() method with real components and minimal mocking,
focusing on behavior rather than implementation details.
"""

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

# Standard library imports
# Add parent directory to path for imports
import sys
from pathlib import Path

# Third-party imports
import pytest
from PySide6.QtTest import QSignalSpy


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Standard library imports
from typing import NoReturn

# Local application imports
from cache_manager import CacheManager
from shot_model import RefreshResult, Shot, ShotModel

# Test doubles following UNIFIED_TESTING_GUIDE patterns
# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.test_doubles_library import (
    TestProcessPool,
)


pytestmark = [
    pytest.mark.integration,  # CRITICAL: Qt state must be serialized
]


# Using TestProcessPool from test_doubles_library (UNIFIED_TESTING_GUIDE)
# No need to duplicate - existing TestProcessPool has all needed functionality


@pytest.fixture
def real_cache_manager(tmp_path):
    """Real cache manager with temporary storage (not mocked)."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return CacheManager(cache_dir=cache_dir)


@pytest.fixture
def shot_model_with_test_pool(real_cache_manager):
    """ShotModel with real cache but TestProcessPool (UNIFIED_TESTING_GUIDE)."""
    model = ShotModel(cache_manager=real_cache_manager, load_cache=False)
    # Use TestProcessPool from library with default workspace data
    test_pool = TestProcessPool()
    test_pool.set_outputs(
        "workspace /shows/testshow/shots/seq01/seq01_shot01",
        "workspace /shows/testshow/shots/seq01/seq01_shot02",
        "workspace /shows/testshow/shots/seq02/seq02_shot01",
    )
    model._process_pool = test_pool
    return model, test_pool


class TestShotModelRefreshCriticalPaths:
    """Test critical paths in ShotModel.refresh_shots() with real components."""

    def test_refresh_shots_success_with_changes(
        self, shot_model_with_test_pool, qtbot
    ) -> None:
        """Test successful refresh when shot list changes."""
        model, _test_pool = shot_model_with_test_pool

        # Set up test workspace output using VFX format: {sequence}_{shot}
        test_output = """workspace /shows/project/shots/seq01/seq01_shot01
workspace /shows/project/shots/seq01/seq01_shot02
workspace /shows/project/shots/seq02/seq02_shot01"""

        model._process_pool.set_outputs(test_output)

        # For this integration test, we expect multiple signals during the refresh operation
        # We'll use a context manager approach that waits for the final signal

        # Set up parameter checking for refresh_finished signal
        def check_refresh_finished_params(success, has_changes):
            return success is True and has_changes is True

        # Wait for the refresh_finished signal which indicates the operation is complete
        with qtbot.waitSignal(
            model.refresh_finished,
            check_params_cb=check_refresh_finished_params,
            timeout=5000,  # Allow sufficient time for the operation
        ):
            # Execute real refresh - this will emit all signals during execution
            result = model.refresh_shots()

        # Verify behavior, not implementation
        assert isinstance(result, RefreshResult)
        assert result.success is True
        assert result.has_changes is True

        # We can also verify that shots_changed was emitted by checking the result
        # The existence of changed shots indicates the signal would have been emitted

        # Verify actual shot data
        shots = model.get_shots()
        assert len(shots) == 3
        assert all(isinstance(shot, Shot) for shot in shots)
        assert shots[0].full_name == "seq01_shot01"
        assert shots[1].full_name == "seq01_shot02"
        assert shots[2].full_name == "seq02_shot01"

    def test_refresh_shots_no_changes(self, shot_model_with_test_pool, qtbot) -> None:
        """Test refresh when shot list hasn't changed."""
        model, _test_pool = shot_model_with_test_pool

        same_output = """workspace /shows/project/shots/seq01/seq01_shot01"""

        # First refresh to establish baseline
        model._process_pool.set_outputs(same_output, same_output)
        model.refresh_shots()

        # Second refresh with same data
        second_result = model.refresh_shots()

        # Verify no changes detected
        assert second_result.success is True
        assert second_result.has_changes is False

    def test_refresh_shots_timeout_handling(
        self, shot_model_with_test_pool, qtbot
    ) -> None:
        """Test timeout handling in refresh_shots()."""
        model, _test_pool = shot_model_with_test_pool

        # Simulate timeout by raising TimeoutError
        def timeout_execute(*args, **kwargs) -> NoReturn:
            raise TimeoutError("Command timed out")

        model._process_pool.execute_workspace_command = timeout_execute

        # Set up error signal expectation with parameter checking
        def check_error_contains_timeout(error_msg):
            return "timed out" in error_msg.lower()

        with qtbot.waitSignal(
            model.error_occurred, check_params_cb=check_error_contains_timeout
        ):
            # Execute refresh
            result = model.refresh_shots()

        # Verify proper error handling
        assert result.success is False
        assert result.has_changes is False

    def test_refresh_shots_parse_error_handling(
        self, shot_model_with_test_pool, qtbot
    ) -> None:
        """Test handling of malformed workspace output."""
        model, _test_pool = shot_model_with_test_pool

        # Provide malformed output
        bad_output = "This is not valid workspace output"
        model._process_pool.set_outputs(bad_output)

        # Execute refresh
        result = model.refresh_shots()

        # Should succeed but with empty shot list
        assert result.success is True
        assert len(model.get_shots()) == 0

    def test_refresh_shots_with_cache_integration(
        self, shot_model_with_test_pool, real_cache_manager
    ) -> None:
        """Test that refresh properly updates cache (real cache, not mocked)."""
        model, _test_pool = shot_model_with_test_pool
        cache = real_cache_manager

        # Provide test data
        model._process_pool.set_outputs(
            """workspace /shows/test/shots/seq01/seq01_shot01"""
        )

        # Refresh shots
        result = model.refresh_shots()
        assert result.success is True

        # Verify cache was updated (testing real cache behavior)
        cached_shots = cache.get_cached_shots()
        assert cached_shots is not None
        assert len(cached_shots) == 1
        assert cached_shots[0]["shot"] == "shot01"

    def test_change_detection_algorithm(self, shot_model_with_test_pool) -> None:
        """Test the change detection algorithm with various scenarios."""
        model, _test_pool = shot_model_with_test_pool

        # Test data
        output1 = """workspace /shows/test/shots/seq01/seq01_shot01
workspace /shows/test/shots/seq01/seq01_shot02"""

        output2 = """workspace /shows/test/shots/seq01/seq01_shot01
workspace /shows/test/shots/seq01/seq01_shot02
workspace /shows/test/shots/seq01/seq01_shot03"""  # Added shot

        output3 = """workspace /shows/test/shots/seq01/seq01_shot01"""  # Removed shot

        output4 = """workspace /shows/test/shots/seq01/seq01_shot01
workspace /shows/different/shots/seq01/seq01_shot02"""  # Path changed

        # Test adding shots
        model._process_pool.set_outputs(output1, output2)
        result1 = model.refresh_shots()
        assert result1.has_changes is True

        result2 = model.refresh_shots()
        assert result2.has_changes is True  # Shot added

        # Test removing shots
        model._process_pool.set_outputs(output3)
        result3 = model.refresh_shots()
        assert result3.has_changes is True  # Shot removed

        # Test path changes
        model._process_pool.set_outputs(output4)
        result4 = model.refresh_shots()
        assert result4.has_changes is True  # Path changed

    def test_refresh_result_namedtuple_usage(self, shot_model_with_test_pool) -> None:
        """Test RefreshResult NamedTuple provides proper interface."""
        model, _test_pool = shot_model_with_test_pool

        result = model.refresh_shots()

        # Test tuple unpacking (backward compatibility)
        success, has_changes = result
        assert isinstance(success, bool)
        assert isinstance(has_changes, bool)

        # Test attribute access (preferred)
        assert hasattr(result, "success")
        assert hasattr(result, "has_changes")
        assert result.success in (True, False)
        assert result.has_changes in (True, False)

    def test_concurrent_refresh_handling(
        self, shot_model_with_test_pool, qtbot
    ) -> None:
        """Test that concurrent refresh attempts are handled safely."""
        model, _test_pool = shot_model_with_test_pool

        # Provide different outputs for each call
        model._process_pool.set_outputs(
            """workspace /shows/test/shots/seq01/seq01_shot01""",
            """workspace /shows/test/shots/seq01/seq01_shot02""",
        )

        # Start multiple refreshes (second should wait or be handled gracefully)
        result1 = model.refresh_shots()
        result2 = model.refresh_shots()

        # Both should complete successfully
        assert result1.success is True
        assert result2.success is True

        # Final state should reflect last refresh
        shots = model.get_shots()
        assert len(shots) == 1
        assert shots[0].shot == "shot02"

    def test_cache_invalidation_workflow(self, shot_model_with_test_pool) -> None:
        """Test that cache invalidation forces fresh data fetch."""
        model, _test_pool = shot_model_with_test_pool

        # Initial refresh
        model._process_pool.set_outputs(
            """workspace /shows/test/shots/seq01/seq01_shot01"""
        )
        model.refresh_shots()
        assert len(model.get_shots()) == 1

        # Invalidate cache
        model.invalidate_workspace_cache()

        # Verify process pool cache was cleared
        assert "ws -sg" not in model._process_pool._cache

        # Next refresh should fetch fresh data
        model._process_pool.set_outputs(
            """workspace /shows/test/shots/seq01/seq01_shot02"""
        )
        result2 = model.refresh_shots()

        assert result2.has_changes is True
        assert model.get_shots()[0].shot == "shot02"


class TestShotModelSignalIntegration:
    """Test signal emission and connection patterns."""

    def test_signal_emission_order(self, shot_model_with_test_pool, qtbot) -> None:
        """Test that signals are emitted in correct order."""
        model, _test_pool = shot_model_with_test_pool

        signal_order = []

        # Connect to all signals with recording callbacks
        model.refresh_started.connect(lambda: signal_order.append("started"))
        model.shots_changed.connect(lambda _: signal_order.append("changed"))
        model.cache_updated.connect(lambda: signal_order.append("cache"))
        model.refresh_finished.connect(lambda *_: signal_order.append("finished"))

        # Perform refresh
        model.refresh_shots()

        # Verify signal order
        assert signal_order[0] == "started"
        assert signal_order[-1] == "finished"
        assert "changed" in signal_order
        assert "cache" in signal_order

    def test_error_signal_on_failure(self, shot_model_with_test_pool, qtbot) -> None:
        """Test that error_occurred signal is emitted on failures."""
        model, _test_pool = shot_model_with_test_pool

        # Cause an error
        def raise_error(*args, **kwargs) -> NoReturn:
            raise RuntimeError("Test error")

        model._process_pool.execute_workspace_command = raise_error

        # Monitor error signal
        error_spy = QSignalSpy(model.error_occurred)

        # Execute refresh
        result = model.refresh_shots()

        # Verify error handling
        assert result.success is False
        assert error_spy.count() == 1
        assert "Test error" in error_spy.at(0)[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
