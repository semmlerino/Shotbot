"""Integration tests for parallel 3DE discovery methods that failed in production.

Tests the actual parallel discovery methods that caused the ThreadSafeProgressTracker
parameter bug. These tests use real file structures and exercise the complete
code path that failed in production.

UNIFIED_TESTING_GUIDE COMPLIANCE:
1. Test behavior with real file structures and I/O
2. Use real components, not mocks
3. Exercise the exact production code paths that failed
4. Focus on integration between components
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest

from tests.integration.conftest import create_test_vfx_structure

# Local application imports
from threede.scene_discovery_coordinator import SceneDiscoveryCoordinator
from type_definitions import Shot


pytestmark = [
    pytest.mark.slow,
    pytest.mark.integration_safe,
    pytest.mark.real_subprocess,  # Uses find command for 3DE discovery
]


class TestParallelDiscoveryIntegration:
    """Integration tests for parallel 3DE discovery methods.

    These tests exercise the exact production code paths that failed,
    specifically testing the methods that use ThreadSafeProgressTracker
    with the progress_interval parameter.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path) -> None:
        """Set up test fixtures with realistic VFX directory structure."""
        self.temp_dir = tmp_path / "shotbot_parallel_test"
        self.temp_dir.mkdir()
        self.shows_root = self.temp_dir / "shows"

    def test_parallel_discovery_with_cancellation(self) -> None:
        """Test that cancellation works correctly during parallel discovery."""
        _shows_root, test_shots = create_test_vfx_structure(self.shows_root)

        progress_updates = []
        cancel_after_updates = 2

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        def cancel_flag() -> bool:
            # Cancel after receiving a few progress updates
            return len(progress_updates) >= cancel_after_updates

        # This should be cancelled mid-processing
        scenes = SceneDiscoveryCoordinator.find_all_scenes_in_shows(
            user_shots=test_shots,
            excluded_users=set(),
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
        )

        # Should have partial results (or empty if cancelled very early)
        assert isinstance(scenes, list)

        # Should have received some progress updates before cancellation
        assert len(progress_updates) >= cancel_after_updates

    def test_parallel_discovery_error_handling(self) -> None:
        """Test error handling in parallel discovery with invalid paths."""
        # Mix of valid and invalid paths
        _shows_root, valid_shots = create_test_vfx_structure(self.shows_root)

        # Add invalid shots that don't exist
        invalid_shots = [
            Shot("NONEXISTENT", "seq001", "0010", "/invalid/path"),
            Shot("TESTSHOW", "invalid_seq", "0010", "/another/invalid/path"),
        ]

        all_shots = valid_shots + invalid_shots

        progress_updates = []

        def progress_callback(count: int, status: str) -> None:
            progress_updates.append((count, status))

        # Should handle invalid paths gracefully
        scenes = SceneDiscoveryCoordinator.find_all_scenes_in_shows(
            user_shots=all_shots,
            excluded_users=set(),
            progress_callback=progress_callback,
            cancel_flag=lambda: False,
        )

        # Should return results from valid paths only
        assert isinstance(scenes, list)
        # Should have some scenes from valid structure
        valid_scenes = [s for s in scenes if s.scene_path.exists()]
        assert len(valid_scenes) > 0

    def test_concurrent_parallel_discovery(self) -> None:
        """Test multiple parallel discoveries running concurrently."""
        # Standard library imports
        import threading

        _shows_root, test_shots = create_test_vfx_structure(self.shows_root)

        results = {}
        errors = {}

        def run_discovery(show_name: str, shot_subset: list[Shot]) -> None:
            """Run discovery for a specific show."""
            try:
                progress_updates = []

                def progress_callback(count: int, status: str) -> None:
                    progress_updates.append((count, status))

                scenes = SceneDiscoveryCoordinator.find_all_scenes_in_shows(
                    user_shots=shot_subset,
                    excluded_users=set(),
                    progress_callback=progress_callback,
                    cancel_flag=lambda: False,
                )

                results[show_name] = (scenes, progress_updates)

            except Exception as e:  # noqa: BLE001
                errors[show_name] = e

        # Split shots by show
        testshow_shots = [s for s in test_shots if s.show == "TESTSHOW"]
        anothershow_shots = [s for s in test_shots if s.show == "ANOTHERSHOW"]

        # Run concurrent discoveries
        threads = [
            threading.Thread(
                target=run_discovery, args=("TESTSHOW", testshow_shots[:3])
            ),
            threading.Thread(
                target=run_discovery, args=("ANOTHERSHOW", anothershow_shots[:3])
            ),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join(timeout=30)  # Generous timeout for parallel processing

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent discoveries failed: {errors}"

        # Verify both discoveries completed
        assert len(results) == 2
        assert "TESTSHOW" in results
        assert "ANOTHERSHOW" in results

        # Verify results from both discoveries
        for scenes, progress_updates in results.values():
            assert isinstance(scenes, list)
            assert len(scenes) >= 1
            assert len(progress_updates) >= 1
