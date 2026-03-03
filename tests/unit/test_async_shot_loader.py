#!/usr/bin/env python3
"""Critical tests for AsyncShotLoader thread safety and signal emission.

Refactored to eliminate unittest.mock and fix thread safety issues.
Follows UNIFIED_TESTING_GUIDE patterns with real components and TestProcessPool boundaries.
"""

# Third-party imports
import pytest
from PySide6.QtTest import QSignalSpy

# Local application imports
from base_shot_model import BaseShotModel
from config import Config
from shot_model import AsyncShotLoader, ShotModel
from tests.fixtures.test_doubles import TestProcessPool


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]


class TestAsyncShotLoader:
    """Test AsyncShotLoader thread behavior and signal emission."""

    @pytest.fixture
    def test_process_pool(self, tmp_path, monkeypatch):
        """Create test process pool for testing.

        Args:
            tmp_path: Temporary directory for isolated test state
            monkeypatch: Pytest monkeypatch for config isolation

        Returns:
            Tuple of (pool, tmp_path) so loader fixture can use same tmp_path

        Note:
            Uses tmp_path directly in outputs (not Config.SHOWS_ROOT) to ensure
            the paths always match what the parser expects after monkeypatch.
        """
        monkeypatch.setattr("config.Config.SHOWS_ROOT", str(tmp_path))
        pool = TestProcessPool(allow_main_thread=True)
        # Use tmp_path directly - don't read Config.SHOWS_ROOT which might
        # not reflect the monkeypatch in some edge cases
        pool.set_outputs(
            f"workspace {tmp_path}/TEST/shots/seq01/TEST_seq01_0010\n"
            f"workspace {tmp_path}/TEST/shots/seq01/TEST_seq01_0020\n"
            f"workspace {tmp_path}/TEST/shots/seq02/TEST_seq02_0010"
        )
        return pool, tmp_path

    @pytest.fixture
    def loader(self, test_process_pool, qtbot, shot_cache, monkeypatch):
        """Create AsyncShotLoader for testing."""
        pool, test_tmp_path = test_process_pool

        # Ensure SHOWS_ROOT matches the test_process_pool's tmp_path
        # This is critical for path validation in _parse_ws_output
        monkeypatch.setattr("config.Config.SHOWS_ROOT", str(test_tmp_path))

        # Create BaseShotModel instance to get the parse function
        # Use isolated shot_cache from fixture
        base_model = BaseShotModel(cache_manager=shot_cache)
        loader = AsyncShotLoader(
            pool, parse_function=base_model._parse_ws_output
        )
        # AsyncShotLoader is a QThread, not a QWidget, so we don't use addWidget
        # Instead, ensure it gets properly cleaned up
        yield loader
        if loader.isRunning():
            loader.quit()
            loader.wait(1000)

    def test_successful_shot_loading_signal_emission(self, loader, qtbot) -> None:
        """Test shots_loaded signal is emitted with correct data."""
        # Use QSignalSpy to verify signal emission
        spy = QSignalSpy(loader.shots_loaded)

        # Start loader
        loader.start()

        # Wait for thread completion with timeout
        assert loader.wait(5000), "Thread did not complete within 5 seconds"

        # Verify signal was emitted
        assert spy.count() == 1, "shots_loaded signal was not emitted"

        # Verify signal data
        shots = spy.at(0)[0]  # First argument of first emission
        assert len(shots) == 3
        assert shots[0].show == "TEST"
        assert shots[0].sequence == "seq01"
        assert shots[0].shot == "0010"

    def test_failed_loading_signal_emission(self, qtbot, shot_cache) -> None:
        """Test load_failed signal is emitted on exception."""
        # Create failing process pool
        failing_pool = TestProcessPool(allow_main_thread=True)
        failing_pool.should_fail = True
        failing_pool.fail_with_message = "Command failed"

        base_model = BaseShotModel(cache_manager=shot_cache)
        loader = AsyncShotLoader(
            failing_pool, parse_function=base_model._parse_ws_output
        )
        try:
            # Use QSignalSpy for error signal
            error_spy = QSignalSpy(loader.load_failed)

            loader.start()
            assert loader.wait(5000)

            # Verify error signal emission
            assert error_spy.count() == 1
            assert "Command failed" in error_spy.at(0)[0]
        finally:
            if loader.isRunning():
                loader.quit()
                loader.wait(1000)

    def test_loader_stop_request(self, qtbot, shot_cache) -> None:
        """Test that stop() request prevents signal emission."""
        # Create slow process pool
        slow_pool = TestProcessPool(allow_main_thread=True)
        slow_pool.simulated_delay = 0.1  # Simulate slow operation
        shows_root = Config.SHOWS_ROOT
        slow_pool.set_outputs(f"workspace {shows_root}/TEST/shots/seq01/TEST_seq01_0010")

        base_model = BaseShotModel(cache_manager=shot_cache)
        loader = AsyncShotLoader(slow_pool, parse_function=base_model._parse_ws_output)
        try:
            spy = QSignalSpy(loader.shots_loaded)

            # Start and immediately stop
            loader.start()
            loader.stop()

            assert loader.wait(1000)

            # No signals should be emitted when stopped
            assert spy.count() == 0
        finally:
            if loader.isRunning():
                loader.quit()
                loader.wait(1000)

    def test_thread_cleanup(self, loader, qtbot) -> None:
        """Test proper thread resource cleanup."""
        loader.start()
        assert loader.wait(5000)

        # Thread should be finished
        assert loader.isFinished()
        assert not loader.isRunning()

    def test_concurrent_loader_instances(self, qtbot, shot_cache) -> None:
        """Test multiple AsyncShotLoader instances don't interfere."""
        shows_root = Config.SHOWS_ROOT
        pool1 = TestProcessPool(allow_main_thread=True)
        pool1.set_outputs(f"workspace {shows_root}/SHOW1/shots/seq01/SHOW1_seq01_0010")

        pool2 = TestProcessPool(allow_main_thread=True)
        pool2.set_outputs(f"workspace {shows_root}/SHOW2/shots/seq01/SHOW2_seq01_0020")

        base_model1 = BaseShotModel(cache_manager=shot_cache)
        base_model2 = BaseShotModel(cache_manager=shot_cache)
        loader1 = AsyncShotLoader(pool1, parse_function=base_model1._parse_ws_output)
        loader2 = AsyncShotLoader(pool2, parse_function=base_model2._parse_ws_output)
        # loaders are QThread objects, not widgets

        try:
            spy1 = QSignalSpy(loader1.shots_loaded)
            spy2 = QSignalSpy(loader2.shots_loaded)

            # Start both loaders
            loader1.start()
            loader2.start()

            # Wait for both
            assert loader1.wait(5000)
            assert loader2.wait(5000)

            # Both should complete successfully
            assert spy1.count() == 1
            assert spy2.count() == 1

            # Results should be different
            shots1 = spy1.at(0)[0]
            shots2 = spy2.at(0)[0]
            assert shots1[0].show != shots2[0].show
        finally:
            # Clean up both loaders
            for loader in [loader1, loader2]:
                if loader.isRunning():
                    loader.quit()
                    loader.wait(1000)


class TestShotModelSignals:
    """Test ShotModel signal emission patterns."""

    @pytest.fixture
    def optimized_model(self, shot_cache, qtbot):
        """Create ShotModel for testing."""
        return ShotModel(shot_cache)
        # model is a QObject, not a widget

    def test_background_load_signals(self, optimized_model, qtbot) -> None:
        """Test background_load_started/finished signals."""
        started_spy = QSignalSpy(optimized_model.background_load_started)
        finished_spy = QSignalSpy(optimized_model.background_load_finished)

        # Use TestProcessPool boundary mock to avoid real subprocess
        test_pool = TestProcessPool(allow_main_thread=True)
        shows_root = Config.SHOWS_ROOT
        test_pool.set_outputs(f"workspace {shows_root}/TEST/shots/seq01/TEST_seq01_0010")
        optimized_model._process_pool = test_pool

        # Initialize async
        result = optimized_model.initialize_async()

        # Verify initialization succeeded
        assert result.success is True, "Async initialization should succeed"

        # Wait for background load to complete
        qtbot.waitUntil(lambda: finished_spy.count() == 1, timeout=5000)

        # Verify signal sequence
        assert started_spy.count() == 1
        assert finished_spy.count() == 1

    def test_shots_changed_signal_on_background_update(
        self, optimized_model, qtbot
    ) -> None:
        """Test shots_changed signal emitted when background load finds changes.

        This test verifies that shots_changed is emitted when the background
        load detects structural changes (e.g., new shots added, old ones removed)
        to an already-populated model.
        """
        # Pre-populate cache with initial shots to simulate a real "update" scenario
        from type_definitions import (
            Shot,
        )
        initial_shot = Shot(
            show="OLD",
            sequence="seq01",
            shot="0010",
            workspace_path="/test/workspace"
        )
        # Cache the initial data so initialize_async will load it
        optimized_model.cache_manager.cache_shots([initial_shot])

        shots_changed_spy = QSignalSpy(optimized_model.shots_changed)

        # Use TestProcessPool with different data (simulating workspace change)
        test_pool = TestProcessPool(allow_main_thread=True)
        shows_root = Config.SHOWS_ROOT
        # New data is different from initial shots (NEW shot instead of OLD)
        test_pool.set_outputs(f"workspace {shows_root}/NEW/shots/seq01/NEW_seq01_0010")
        optimized_model._process_pool = test_pool

        optimized_model.initialize_async()

        # Wait for background update to detect changes
        qtbot.waitUntil(lambda: shots_changed_spy.count() == 1, timeout=5000)

        assert len(optimized_model.shots) == 1
        assert optimized_model.shots[0].show == "NEW"

    def test_shots_loaded_signal_re_emitted_after_background_load(
        self, shot_cache, qtbot
    ) -> None:
        """Test shots_loaded signal is re-emitted after background load completes.

        Regression test for bug where Previous Shots tab wasn't loading because
        shots_loaded was only emitted once with empty list on init, never again
        after background load completed with actual shots.

        This test verifies the complete signal flow:
        1. initialize_async() with empty cache -> shots_loaded([])
        2. Background load completes -> shots_loaded([actual_shots])

        Without the fix (before commit 9793a5f), this test would fail because
        shots_loaded was only emitted once.
        """
        # Clear cache to simulate first run without cached data
        shot_cache.clear_cached_data("shots")

        # Create model with empty cache
        model = ShotModel(shot_cache)

        # Set up test process pool with shot data
        test_pool = TestProcessPool(allow_main_thread=True)
        shows_root = Config.SHOWS_ROOT
        test_pool.set_outputs(
            f"workspace {shows_root}/TEST/shots/seq01/TEST_seq01_0010\n"
            f"workspace {shows_root}/TEST/shots/seq01/TEST_seq01_0020"
        )
        model._process_pool = test_pool

        # Spy on shots_loaded signal
        shots_loaded_spy = QSignalSpy(model.shots_loaded)

        # Initialize async with empty cache
        result = model.initialize_async()
        assert result.success is True

        # First emission: empty list (initial load with no cache)
        assert shots_loaded_spy.count() == 1, "First shots_loaded should emit immediately"
        first_emission_shots = shots_loaded_spy.at(0)[0]
        assert len(first_emission_shots) == 0, "First emission should have empty list"

        # Wait for background load to complete
        qtbot.waitUntil(lambda: len(model.shots) > 0, timeout=5000)

        # Second emission: actual shots (CRITICAL - this was missing before fix)
        assert (
            shots_loaded_spy.count() == 2
        ), "shots_loaded should emit twice: empty init + loaded shots"

        second_emission_shots = shots_loaded_spy.at(1)[0]
        assert (
            len(second_emission_shots) == 2
        ), "Second emission should have actual shots"
        assert second_emission_shots[0].show == "TEST"
        assert second_emission_shots[0].sequence == "seq01"

        # Verify model state is correct (shots_changed was emitted but before we could spy)
        assert len(model.shots) == 2

        # Cleanup
        model.cleanup()
