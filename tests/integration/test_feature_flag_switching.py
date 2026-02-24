"""Integration tests for feature flag switching between ShotModel implementations."""

# Standard library imports
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

# Third-party imports
import pytest

# Removed sys.path modification - can cause import issues
# sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# Local application imports
from base_shot_model import BaseShotModel
from cache_manager import CacheManager

# Moved to lazy import to fix Qt initialization
# from main_window import MainWindow
from shot_model import Shot, ShotModel

# Import test doubles instead of using raw Mock()
# Removed sys.path modification - can cause import issues
# sys.path.insert(0, str(Path(__file__).parent.parent))
# Third-party imports
from tests.fixtures.doubles_library import TestCacheManager


# Integration tests may show error dialogs when mocks are incomplete
pytestmark = [
    pytest.mark.integration,
    pytest.mark.qt,
    pytest.mark.allow_dialogs,
    pytest.mark.permissive_process_pool,  # MainWindow tests, not subprocess output
]


if TYPE_CHECKING:
    from collections.abc import Generator

    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def reset_cache_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level cache disabled flag to prevent test contamination.

    The _cache_disabled flag in path_validators.py is a global state that can persist
    across tests, causing subsequent tests to see incorrect cache behavior.
    This fixture ensures each test starts with a clean state.
    """
    import path_validators

    monkeypatch.setattr(path_validators, "_cache_disabled", False)


# Module-level fixture to handle lazy imports after Qt initialization
@pytest.fixture(autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow  # noqa: PLW0603
    from main_window import (
        MainWindow,
    )


class ExtendedTestCacheManager(TestCacheManager):
    """Extended TestCacheManager with 3DE scene support."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize with additional 3DE scene support."""
        super().__init__(cache_dir)
        self._cached_threede_scenes: list = []

    def get_cached_threede_scenes(self) -> list:
        """Get cached 3DE scenes (for MainWindow compatibility)."""
        return self._cached_threede_scenes

    def shutdown(self) -> None:
        """Shutdown method for MainWindow compatibility."""
        # Test double: just clear caches
        self.clear_cache()

    def get_cached_data(self, key: str) -> object | None:
        """Get cached generic data by key (MainWindow compatibility)."""
        return None

    def get_migrated_shots(self) -> list | None:
        """Get migrated shots (PreviousShotsModel compatibility)."""
        return None


@pytest.mark.slow
@pytest.mark.gui_mainwindow
class TestFeatureFlagSwitching:
    """Test feature flag switching between shot model implementations."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, qtbot: "QtBot") -> "Generator[None, None, None]":
        """Set up test environment with qtbot."""
        self.qtbot = qtbot
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name)
        yield
        self.temp_dir.cleanup()

    def test_standard_model_when_flag_not_set(self, monkeypatch: pytest.MonkeyPatch, qapp: "QApplication", qtbot: "QtBot") -> None:
        """Test that ShotModel is used when legacy flag is not set (default behavior)."""
        # Clear environment variable to use default (parallel-safe)
        monkeypatch.delenv("SHOTBOT_USE_LEGACY_MODEL", raising=False)

        # Create main window with proper Qt management
        # Use real test double instead of Mock()
        test_cache = ExtendedTestCacheManager(self.cache_dir)

        with patch("main_window.CacheManager") as mock_cache_manager:
            mock_cache_manager.return_value = test_cache

            # Mock QTimer to prevent delayed operations
            with patch("PySide6.QtCore.QTimer.singleShot"), patch(
                "process_pool_manager.ProcessPoolManager.get_instance"
            ) as mock_get_instance:
                # Return a test double for ProcessPoolManager
                # Local application imports
                from tests.fixtures.doubles_library import (
                    TestProcessPool,
                )

                mock_get_instance.return_value = TestProcessPool(allow_main_thread=True)
                window = MainWindow()
                qtbot.addWidget(window)  # CRITICAL: Register for cleanup

                # Verify ShotModel is used by default
                assert isinstance(window.shot_model, ShotModel)
                assert isinstance(window.shot_model, BaseShotModel)

                # Clean up any threads if present
                if (
                    hasattr(window, "_threede_worker")
                    and window._threede_worker
                    and window._threede_worker.isRunning()
                ):
                    window._threede_worker.quit()
                    window._threede_worker.wait(1000)
                window.close()

    def test_legacy_model_when_flag_set(self, monkeypatch: pytest.MonkeyPatch, qapp: "QApplication", qtbot: "QtBot") -> None:
        """Test that ShotModel is used when legacy flag is set."""
        # Set environment variable (parallel-safe)
        monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")

        # Create main window with proper Qt management
        # Use real test double instead of Mock()
        test_cache = ExtendedTestCacheManager(self.cache_dir)

        with patch("main_window.CacheManager") as mock_cache_manager:
            mock_cache_manager.return_value = test_cache

            # Mock QTimer to prevent delayed operations
            with patch("PySide6.QtCore.QTimer.singleShot"):
                window = MainWindow()
                qtbot.addWidget(window)  # CRITICAL: Register for cleanup

                # Verify ShotModel is used when legacy flag is set
                # Note: Currently both shot_model.py and shot_model_legacy.py define ShotModel class
                # The feature flag switching isn't implemented yet, so this just verifies we have a ShotModel
                assert isinstance(window.shot_model, ShotModel)

                # Clean up any threads if present
                if (
                    hasattr(window, "_threede_worker")
                    and window._threede_worker
                    and window._threede_worker.isRunning()
                ):
                    window._threede_worker.quit()
                    window._threede_worker.wait(1000)
                window.close()

    def test_flag_values_recognized(self, monkeypatch: pytest.MonkeyPatch, qapp: "QApplication", qtbot: "QtBot") -> None:
        """Test that various flag values are recognized correctly for legacy model."""
        test_cases = [
            ("1", True),  # Use legacy ShotModel
            ("true", True),  # Use legacy ShotModel
            ("True", True),  # Use legacy ShotModel
            ("TRUE", True),  # Use legacy ShotModel
            ("yes", True),  # Use legacy ShotModel
            ("Yes", True),  # Use legacy ShotModel
            ("YES", True),  # Use legacy ShotModel
            ("0", False),  # Use default ShotModel
            ("false", False),  # Use default ShotModel
            ("no", False),  # Use default ShotModel
            ("invalid", False),  # Use default ShotModel
            ("", False),  # Use default ShotModel
        ]

        for value, expected_legacy in test_cases:
            # Set environment variable (parallel-safe)
            monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", value)

            # Use real test double instead of Mock()
            test_cache = ExtendedTestCacheManager(self.cache_dir)

            with patch("main_window.CacheManager") as mock_cache_manager:
                mock_cache_manager.return_value = test_cache

                # Mock QTimer to prevent delayed operations
                with patch("PySide6.QtCore.QTimer.singleShot"):
                    # Handle different model types with appropriate mocking
                    if not expected_legacy:
                        # Use ShotModel, need to mock ProcessPoolManager
                        with patch(
                            "process_pool_manager.ProcessPoolManager.get_instance"
                        ) as mock_get_instance:
                            # Local application imports
                            from tests.fixtures.doubles_library import (
                                TestProcessPool,
                            )

                            mock_get_instance.return_value = TestProcessPool(allow_main_thread=True)
                            window = MainWindow()
                            qtbot.addWidget(
                                window
                            )  # CRITICAL: Register for cleanup

                            assert isinstance(window.shot_model, ShotModel), (
                                f"Expected ShotModel for value '{value}'"
                            )

                            # Clean up any threads if present
                            if (
                                hasattr(window, "_threede_worker")
                                and window._threede_worker
                            ) and window._threede_worker.isRunning():
                                window._threede_worker.quit()
                                window._threede_worker.wait(1000)
                            window.close()
                    else:
                        # Use legacy ShotModel, no ProcessPoolManager needed
                        window = MainWindow()
                        qtbot.addWidget(window)  # CRITICAL: Register for cleanup

                        # Since both models are currently ShotModel class, just verify it exists
                        # TODO: When legacy model is a separate class, update this assertion
                        assert isinstance(window.shot_model, ShotModel), (
                            f"Expected ShotModel for value '{value}'"
                        )

                        # Clean up any threads if present
                        if (
                            hasattr(window, "_threede_worker")
                            and window._threede_worker
                        ) and window._threede_worker.isRunning():
                            window._threede_worker.quit()
                            window._threede_worker.wait(1000)
                        window.close()

    def test_both_models_share_same_interface(self) -> None:
        """Test that both models implement the same interface."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Create both models
        standard_model = ShotModel(cache_manager, load_cache=False)
        optimized_model = ShotModel(cache_manager, load_cache=False)

        # Check common methods exist in both
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

            # Verify they're callable
            assert callable(getattr(standard_model, method_name))
            assert callable(getattr(optimized_model, method_name))

    def test_signal_compatibility(self) -> None:
        """Test that both models emit compatible signals."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Create both models
        standard_model = ShotModel(cache_manager, load_cache=False)
        optimized_model = ShotModel(cache_manager, load_cache=False)

        # Check common signals exist
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
        """Test that cache is properly shared when switching models."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Create mock shot data
        test_shots = [
            Shot("TEST", "SEQ01", "0010", "/shows/TEST/shots/SEQ01/0010"),
            Shot("TEST", "SEQ01", "0020", "/shows/TEST/shots/SEQ01/0020"),
        ]

        # Cache shots using standard model
        cache_manager.cache_shots(test_shots)

        # Load with standard model
        standard_model = ShotModel(cache_manager, load_cache=True)
        assert len(standard_model.get_shots()) == 2

        # Load with optimized model - should get same cached data
        optimized_model = ShotModel(cache_manager, load_cache=True)
        assert len(optimized_model.get_shots()) == 2

        # Verify the shots are the same
        standard_shots = {s.full_name for s in standard_model.get_shots()}
        optimized_shots = {s.full_name for s in optimized_model.get_shots()}
        assert standard_shots == optimized_shots

    def test_cleanup_on_model_switch(self) -> None:
        """Test that cleanup is properly handled when switching models."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Create optimized model
        optimized_model = ShotModel(cache_manager, load_cache=False)

        # Create a test double for async loader
        class TestAsyncLoader:
            def __init__(self) -> None:
                self.is_running = True
                self.stopped = False
                self.waited = False
                self.deleted = False
                self.request_stop_called = False
                self.safe_terminated = False

            def isRunning(self):
                return self.is_running

            def stop(self) -> None:
                self.stopped = True
                self.is_running = False

            def wait(self, timeout: int | None = None) -> bool:
                self.waited = True
                return True

            def deleteLater(self) -> None:
                self.deleted = True

            def request_stop(self) -> bool:
                """Request the thread to stop gracefully."""
                self.request_stop_called = True
                self.is_running = False
                return True

            def safe_terminate(self) -> None:
                """Safely terminate the thread."""
                self.safe_terminated = True
                self.is_running = False

        test_loader = TestAsyncLoader()
        optimized_model._async_loader = test_loader

        # Call cleanup
        optimized_model.cleanup()

        # Verify behavior (not implementation)
        assert test_loader.request_stop_called, "request_stop should be called"
        assert test_loader.waited, "Should wait for loader to finish"
        assert test_loader.deleted, "Loader should be scheduled for deletion"

        # Verify loader was cleared
        assert optimized_model._async_loader is None

    def test_performance_metrics_available_in_both(self) -> None:
        """Test that performance metrics are available in both models."""
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Create both models
        standard_model = ShotModel(cache_manager, load_cache=False)
        optimized_model = ShotModel(cache_manager, load_cache=False)

        # Get metrics from both
        standard_metrics = standard_model.get_performance_metrics()
        optimized_metrics = optimized_model.get_performance_metrics()

        # Both should return dictionaries with some common keys
        assert isinstance(standard_metrics, dict)
        assert isinstance(optimized_metrics, dict)

        # Check for some expected keys
        expected_keys = ["total_shots", "cache_hits", "cache_misses"]
        for key in expected_keys:
            assert key in standard_metrics, f"Missing {key} in standard metrics"
            assert key in optimized_metrics, f"Missing {key} in optimized metrics"

        # Optimized model should have additional metrics
        assert "loading_in_progress" in optimized_metrics
        assert "session_warmed" in optimized_metrics


@pytest.mark.gui_mainwindow
class TestMainWindowIntegration:
    """Test MainWindow integration with different shot models."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, qtbot: "QtBot") -> None:
        """Set up test environment with qtbot."""
        self.qtbot = qtbot

    def test_window_initialization_with_default_model(self, monkeypatch: pytest.MonkeyPatch, qapp: "QApplication", qtbot: "QtBot", tmp_path: Path) -> None:
        """Test that MainWindow initializes correctly with default optimized model."""
        # Clear environment variable (parallel-safe)
        monkeypatch.delenv("SHOTBOT_USE_LEGACY_MODEL", raising=False)

        # Use real test double instead of Mock()
        test_cache = ExtendedTestCacheManager(cache_dir=tmp_path / "cache")

        with patch("main_window.CacheManager") as mock_cache_manager:
            mock_cache_manager.return_value = test_cache

            # Mock QTimer to prevent delayed operations
            with patch("PySide6.QtCore.QTimer.singleShot"), patch(
                "process_pool_manager.ProcessPoolManager.get_instance"
            ) as mock_get_instance:
                # Local application imports
                from tests.fixtures.doubles_library import (
                    TestProcessPool,
                )

                mock_get_instance.return_value = TestProcessPool(allow_main_thread=True)
                # Should not raise any exceptions
                window = MainWindow()
                qtbot.addWidget(window)  # CRITICAL: Register for cleanup
                assert window is not None
                assert window.shot_model is not None
                assert isinstance(window.shot_model, ShotModel)

                # Clean up any threads if present
                if (
                    hasattr(window, "_threede_worker")
                    and window._threede_worker
                    and window._threede_worker.isRunning()
                ):
                    window._threede_worker.quit()
                    window._threede_worker.wait(1000)
                window.close()

    def test_window_initialization_with_legacy_model(self, monkeypatch: pytest.MonkeyPatch, qapp: "QApplication", qtbot: "QtBot", tmp_path: Path) -> None:
        """Test that MainWindow initializes correctly with legacy model."""
        # Set environment variable (parallel-safe)
        monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")

        # Use real test double instead of Mock()
        test_cache = ExtendedTestCacheManager(cache_dir=tmp_path / "cache")

        with patch("main_window.CacheManager") as mock_cache_manager:
            mock_cache_manager.return_value = test_cache

            # Mock QTimer to prevent delayed operations
            with patch("PySide6.QtCore.QTimer.singleShot"):
                # Should not raise any exceptions
                window = MainWindow()
                qtbot.addWidget(window)  # CRITICAL: Register for cleanup
                assert window is not None
                assert window.shot_model is not None
                assert isinstance(window.shot_model, ShotModel)
                # Note: Both regular and legacy models are named ShotModel,
                # so we can't distinguish them by class name alone

                # Clean up any threads if present
                if (
                    hasattr(window, "_threede_worker")
                    and window._threede_worker
                    and window._threede_worker.isRunning()
                ):
                    window._threede_worker.quit()
                    window._threede_worker.wait(1000)
                window.close()

    def test_closeEvent_handles_optimized_model(self, monkeypatch: pytest.MonkeyPatch, qapp: "QApplication", qtbot: "QtBot", tmp_path: Path) -> None:
        """Test that closeEvent properly handles ShotModel cleanup (default behavior)."""
        # Use default ShotModel (no environment variable needed, parallel-safe)
        monkeypatch.delenv("SHOTBOT_USE_LEGACY_MODEL", raising=False)

        # Use real test double instead of Mock()
        test_cache = ExtendedTestCacheManager(cache_dir=tmp_path / "cache")

        with patch("main_window.CacheManager") as mock_cache_manager:
            mock_cache_manager.return_value = test_cache

            # Mock QTimer to prevent delayed operations
            with (
                patch("PySide6.QtCore.QTimer.singleShot"),
                patch(
                    "process_pool_manager.ProcessPoolManager.get_instance"
                ) as mock_get_instance,
            ):
                # Local application imports
                from tests.fixtures.doubles_library import (
                    TestProcessPool,
                )

                mock_get_instance.return_value = TestProcessPool(allow_main_thread=True)
                window = MainWindow()
                qtbot.addWidget(window)  # CRITICAL: Register for cleanup

                # Track cleanup behavior
                cleanup_called = False
                original_cleanup = window.shot_model.cleanup

                def track_cleanup() -> None:
                    nonlocal cleanup_called
                    cleanup_called = True
                    original_cleanup()

                window.shot_model.cleanup = track_cleanup

                # Create test close event
                class TestCloseEvent:
                    def accept(self) -> None:
                        pass

                test_event = TestCloseEvent()

                # Call closeEvent
                window.closeEvent(test_event)

                # Verify behavior (cleanup was called)
                assert cleanup_called, "Cleanup should be called on close"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
