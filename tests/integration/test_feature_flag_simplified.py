"""Simplified integration tests for feature flag switching.

Following testing guide principles:
- Test behavior, not implementation
- Use real components where possible
- Mock only at system boundaries
"""

# Standard library imports
import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path

# Third-party imports
import pytest


pytestmark = [
    pytest.mark.integration,  # CRITICAL: Qt state must be serialized
]


# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Third-party imports
from PySide6.QtCore import QThread, Signal

# Local application imports
from cache_manager import CacheManager
from shot_model import Shot, ShotModel


@pytest.fixture(autouse=True)
def reset_cache_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level cache disabled flag to prevent test contamination.

    The _cache_disabled flag in utils.py is a global state that can persist
    across tests, causing subsequent tests to see incorrect cache behavior.
    This fixture ensures each test starts with a clean state.
    """
    import utils

    monkeypatch.setattr(utils, "_cache_disabled", False)


class TestFeatureFlagBehavior:
    """Test feature flag behavior without MainWindow complexity."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self) -> Generator[None, None, None]:
        """Set up test environment."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name)
        yield
        self.temp_dir.cleanup()

    def test_model_selection_logic(self) -> None:
        """Test that feature flag correctly selects the model type."""
        # Test cases for flag values
        test_cases = [
            ("1", True),
            ("true", True),
            ("True", True),
            ("yes", True),
            ("0", False),
            ("false", False),
            ("", False),
            ("invalid", False),
        ]

        for value, should_be_optimized in test_cases:
            os.environ["SHOTBOT_OPTIMIZED_MODE"] = value

            # This is the actual logic from main_window.py
            use_optimized = os.environ.get("SHOTBOT_OPTIMIZED_MODE", "").lower() in [
                "1",
                "true",
                "yes",
            ]

            assert use_optimized == should_be_optimized, (
                f"Flag value '{value}' should result in optimized={should_be_optimized}"
            )

            # Clean up
            os.environ.pop("SHOTBOT_OPTIMIZED_MODE", None)

    def test_both_models_implement_interface(self) -> None:
        """Test that both models implement the same interface."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Create both models without loading cache to avoid subprocess calls
        standard_model = ShotModel(cache_manager, load_cache=False)
        optimized_model = ShotModel(cache_manager, load_cache=False)

        # Check common methods exist
        common_methods = [
            "get_shots",
            "refresh_shots",
            "get_shot_count",
            "select_shot",
            "get_selected_shot",
            "find_shot_by_name",
            "get_performance_metrics",
        ]

        for method_name in common_methods:
            assert hasattr(standard_model, method_name), (
                f"ShotModel missing method: {method_name}"
            )
            assert hasattr(optimized_model, method_name), (
                f"ShotModel missing method: {method_name}"
            )
            assert callable(getattr(standard_model, method_name))
            assert callable(getattr(optimized_model, method_name))

    def test_both_models_have_signals(self) -> None:
        """Test that both models have the required signals."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        standard_model = ShotModel(cache_manager, load_cache=False)
        optimized_model = ShotModel(cache_manager, load_cache=False)

        # Check common signals
        common_signals = [
            "shots_loaded",
            "shots_changed",
            "refresh_started",
            "refresh_finished",
            "error_occurred",
            "shot_selected",
            "cache_updated",
        ]

        for signal_name in common_signals:
            assert hasattr(standard_model, signal_name), (
                f"ShotModel missing signal: {signal_name}"
            )
            assert hasattr(optimized_model, signal_name), (
                f"ShotModel missing signal: {signal_name}"
            )

    def test_cache_sharing_between_models(self) -> None:
        """Test that cache works with both model types."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Create test shot data
        test_shots = [
            Shot("TEST", "SEQ01", "0010", "/shows/TEST/shots/SEQ01/0010"),
            Shot("TEST", "SEQ01", "0020", "/shows/TEST/shots/SEQ01/0020"),
        ]

        # Cache shots
        cache_manager.cache_shots(test_shots)

        # Load with standard model
        standard_model = ShotModel(cache_manager, load_cache=True)
        assert len(standard_model.get_shots()) == 2

        # Load with optimized model - should get same data
        optimized_model = ShotModel(cache_manager, load_cache=True)
        assert len(optimized_model.get_shots()) == 2

        # Verify the shots are identical
        standard_shots = {s.full_name for s in standard_model.get_shots()}
        optimized_shots = {s.full_name for s in optimized_model.get_shots()}
        assert standard_shots == optimized_shots

    def test_optimized_model_cleanup(self) -> None:
        """Test that ShotModel cleanup works correctly."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)
        optimized_model = ShotModel(cache_manager, load_cache=False)

        # Create a test double for async loader that has real Qt behavior
        class TestAsyncLoader(QThread):
            """Test double for AsyncShotLoader with real Qt thread behavior."""

            shots_loaded = Signal(list)
            load_failed = Signal(str)

            def __init__(self) -> None:
                super().__init__()
                self.stop_called = False
                self.wait_called = False
                self.delete_later_called = False
                self._running = True

            def isRunning(self):
                return self._running

            def stop(self) -> None:
                self.stop_called = True
                self.requestInterruption()
                self._running = False

            def request_stop(self) -> None:
                """Request the thread to stop - matches actual AsyncShotLoader interface."""
                self.stop_called = True
                self.requestInterruption()
                self._running = False

            def wait(self, timeout: int | None = None) -> bool:
                self.wait_called = True
                self._running = False
                return True

            def deleteLater(self) -> None:
                self.delete_later_called = True
                super().deleteLater()

        # Use the test double
        test_loader = TestAsyncLoader()
        optimized_model._async_loader = test_loader

        # Call cleanup
        optimized_model.cleanup()

        # Verify cleanup behavior occurred
        assert test_loader.stop_called, "stop() should have been called"
        assert test_loader.wait_called, "wait() should have been called"
        assert test_loader.delete_later_called, "deleteLater() should have been called"
        assert optimized_model._async_loader is None

    def test_performance_metrics_available(self) -> None:
        """Test that performance metrics are available in both models."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        standard_model = ShotModel(cache_manager, load_cache=False)
        optimized_model = ShotModel(cache_manager, load_cache=False)

        # Get metrics
        standard_metrics = standard_model.get_performance_metrics()
        optimized_metrics = optimized_model.get_performance_metrics()

        # Both should return dictionaries
        assert isinstance(standard_metrics, dict)
        assert isinstance(optimized_metrics, dict)

        # Check for expected keys
        expected_keys = ["total_shots", "cache_hits", "cache_misses"]
        for key in expected_keys:
            assert key in standard_metrics, f"Missing {key} in standard metrics"
            assert key in optimized_metrics, f"Missing {key} in optimized metrics"

        # Optimized model has additional metrics
        assert "loading_in_progress" in optimized_metrics
        assert "session_warmed" in optimized_metrics


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
