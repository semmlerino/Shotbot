"""Integration tests for shot workflow with cache integration."""

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

from __future__ import annotations

# Standard library imports
import json
import shutil
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
# Import real application components for integration testing
from cache_manager import CacheManager
from shot_model import RefreshResult, ShotModel

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.fixtures.doubles_library import (
    TestProcessPool,
    TestSubprocess,
)


pytestmark = [pytest.mark.integration, pytest.mark.allow_main_thread]


class TestShotWorkflowIntegration:
    """Integration tests for shot refresh and caching workflow following UNIFIED_TESTING_GUIDE."""

    def setup_method(self) -> None:
        # Use test double for subprocess (UNIFIED_TESTING_GUIDE)
        self.test_subprocess = TestSubprocess()
        """Minimal setup to avoid pytest fixture overhead."""
        self.temp_dir = Path(tempfile.mkdtemp(prefix="shotbot_shot_workflow_"))
        self.cache_dir = self.temp_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.shows_root = self.temp_dir / "shows"
        self.shows_root.mkdir(parents=True, exist_ok=True)

    def teardown_method(self) -> None:
        """Direct cleanup without fixture dependencies."""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass  # Ignore cleanup errors

    def test_shot_model_refresh_with_cache_integration(self) -> None:
        """Test shot model refreshing from workspace with cache integration."""
        # Import locally to avoid pytest environment issues

        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        # Mock ws command output with realistic shot data
        mock_ws_output = """
workspace /shows/show1/shots/seq01/seq01_0010
workspace /shows/show1/shots/seq01/seq01_0020
workspace /shows/show1/shots/seq02/seq02_0010
""".strip()

        # Create test double for ProcessPoolManager
        # allow_main_thread=True because this test calls refresh_shots() from the main thread
        test_process_pool = TestProcessPool(allow_main_thread=True)
        test_process_pool.set_outputs(mock_ws_output)

        # Create real cache manager with temp directory
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Create shot model and replace ProcessPoolManager with test double
        shot_model = ShotModel(cache_manager=cache_manager)
        shot_model._process_pool = test_process_pool

        # Test initial refresh
        result = shot_model.refresh_shots()

        # Verify result type and success
        assert isinstance(result, RefreshResult)
        assert result.success is True
        assert result.has_changes is True  # First refresh should have changes

        # Verify shots were parsed correctly
        shots = shot_model.get_shots()
        assert len(shots) == 3

        # Verify first shot details
        first_shot = shots[0]
        assert first_shot.show == "show1"
        assert first_shot.sequence == "seq01"
        assert (
            first_shot.shot == "0010"
        )  # Shot name extracted by removing sequence prefix
        assert "seq01_0010" in first_shot.workspace_path

        # Verify test process pool was used
        assert len(test_process_pool.commands) == 1
        assert "ws -sg" in test_process_pool.commands[0]

    def test_shot_data_persistence_through_cache(self) -> None:
        """Test shot data persists correctly through cache storage."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        # Create cache manager
        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Create test shot data
        test_shots_data = [
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "seq01_0010",
                "workspace_path": "/shows/test_show/shots/seq01/seq01_0010",
                "name": "seq01_0010",
            },
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "seq01_0020",
                "workspace_path": "/shows/test_show/shots/seq01/seq01_0020",
                "name": "seq01_0020",
            },
        ]

        # Store shots in cache using public API
        cache_manager.cache_shots(test_shots_data)

        # Create shot model and replace ProcessPoolManager with failing test double
        shot_model = ShotModel(cache_manager=cache_manager)
        test_process_pool = TestProcessPool(allow_main_thread=True)
        # Don't set outputs to simulate command failure
        shot_model._process_pool = test_process_pool

        # Load shots should fall back to cache
        shots = shot_model.get_shots()

        # Verify shots loaded from cache
        assert len(shots) == 2
        assert shots[0].show == "test_show"
        assert shots[0].sequence == "seq01"
        assert shots[0].shot == "seq01_0010"
        assert shots[1].shot == "seq01_0020"

    def test_shot_model_change_detection(self) -> None:
        """Test shot model correctly detects changes between refreshes."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        cache_manager = CacheManager(cache_dir=self.cache_dir)
        shot_model = ShotModel(cache_manager=cache_manager)

        # Initial shot data
        initial_output = "workspace /shows/show1/shots/seq01/seq01_0010"

        # Create test double and replace ProcessPoolManager
        test_process_pool = TestProcessPool(allow_main_thread=True)
        test_process_pool.set_outputs(initial_output)
        shot_model._process_pool = test_process_pool

        # First refresh
        result1 = shot_model.refresh_shots()
        assert result1.success is True
        assert result1.has_changes is True  # First refresh always has changes

        # Second refresh with same data - should detect no changes
        test_process_pool.set_outputs(initial_output)  # Set same output again
        result2 = shot_model.refresh_shots()
        assert result2.success is True
        assert result2.has_changes is False  # No changes

        # Third refresh with new shot - should detect changes
        updated_output = (
            initial_output + "\nworkspace /shows/show1/shots/seq01/seq01_0020"
        )
        test_process_pool.set_outputs(updated_output)

        result3 = shot_model.refresh_shots()
        assert result3.success is True
        assert result3.has_changes is True  # New shot added

        # Verify shot count increased
        shots = shot_model.get_shots()
        assert len(shots) == 2

    def test_shot_model_cache_invalidation_workflow(self) -> None:
        """Test cache invalidation when shots are updated."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        cache_manager = CacheManager(cache_dir=self.cache_dir)
        shot_model = ShotModel(cache_manager=cache_manager)

        # Create test double and replace ProcessPoolManager
        test_process_pool = TestProcessPool(allow_main_thread=True)
        test_process_pool.set_outputs("workspace /shows/show1/shots/seq01/seq01_0010")
        shot_model._process_pool = test_process_pool

        # Refresh shots to populate cache
        shot_model.refresh_shots()

        # Verify cache file was created
        cache_file = self.cache_dir / "shots.json"
        assert cache_file.exists()

        # Read cache data
        with cache_file.open() as f:
            cache_data = json.load(f)

        assert "data" in cache_data
        assert len(cache_data["data"]) == 1
        assert cache_data["data"][0]["show"] == "show1"

        # Update shots and verify cache is updated
        test_process_pool.set_outputs("workspace /shows/show2/shots/seq01/seq01_0010")

        shot_model.refresh_shots()

        # Verify cache was updated
        with cache_file.open() as f:
            updated_cache_data = json.load(f)

        assert updated_cache_data["data"][0]["show"] == "show2"

    def test_shot_model_error_handling_with_cache_fallback(self) -> None:
        """Test shot model error handling with cache fallback."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Pre-populate cache with test data
        cache_data = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "shots": [
                {
                    "show": "cached_show",
                    "sequence": "seq01",
                    "shot": "seq01_0010",
                    "workspace_path": "/shows/cached_show/shots/seq01/seq01_0010",
                    "name": "seq01_0010",
                }
            ],
        }

        cache_file = self.cache_dir / "shots.json"
        with cache_file.open("w") as f:
            json.dump(cache_data, f)

        shot_model = ShotModel(cache_manager=cache_manager)

        # Should load from cache at initialization if available
        shots = shot_model.get_shots()
        assert len(shots) == 1
        assert shots[0].show == "cached_show"


# Allow running as standalone test
if __name__ == "__main__":
    test = TestShotWorkflowIntegration()
    test.setup_method()
    try:
        print("Running shot model refresh with cache integration...")
        test.test_shot_model_refresh_with_cache_integration()
        print("✓ Shot model refresh integration passed")

        print("Running shot data persistence through cache...")
        test.test_shot_data_persistence_through_cache()
        print("✓ Shot data persistence integration passed")

        print("Running shot model change detection...")
        test.test_shot_model_change_detection()
        print("✓ Shot model change detection passed")

        print("Running shot model cache invalidation workflow...")
        test.test_shot_model_cache_invalidation_workflow()
        print("✓ Cache invalidation workflow passed")

        print("Running shot model error handling with cache fallback...")
        test.test_shot_model_error_handling_with_cache_fallback()
        print("✓ Error handling with cache fallback passed")

        print("All shot workflow integration tests passed!")
    except Exception as e:
        print(f"Test failed: {e}")

        traceback.print_exc()
    finally:
        test.teardown_method()
