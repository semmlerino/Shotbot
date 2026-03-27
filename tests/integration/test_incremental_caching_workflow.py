"""Integration tests for incremental caching workflow.

Tests the complete workflow from Phase 1-3:
- Merge algorithm (Phase 1)
- Migration system (Phase 2)
- ShotModel integration (Phase 3)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cache.shot_cache import ShotDataCache
from shots.shot_model import ShotModel


pytestmark = pytest.mark.qt  # CRITICAL: Qt state must be serialized


@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> Path:
    """Create temporary cache directory."""
    return tmp_path / "cache"


@pytest.fixture
def cache_manager_temp(temp_cache_dir: Path) -> ShotDataCache:
    """Create ShotDataCache with temporary cache directory."""
    return ShotDataCache(temp_cache_dir)


@pytest.fixture
def shot_model_temp(cache_manager_temp: ShotDataCache, test_process_pool) -> ShotModel:
    """Create ShotModel with temporary cache."""
    model = ShotModel(cache_manager=cache_manager_temp, load_cache=False)
    # Inject test process pool
    model._process_pool = test_process_pool  # type: ignore[attr-defined]
    model._force_sync_refresh = True
    return model


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestIncrementalCachingWorkflow:
    """Test complete incremental caching workflow."""

    def test_first_refresh_all_new(
        self, shot_model_temp: ShotModel, test_process_pool, qtbot
    ):
        """Test first refresh with empty cache - all shots are new."""
        # Setup: Mock ws -sg output with 3 shots (single string with newlines)
        test_process_pool.set_outputs(
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0010\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0020\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0030\n"
        )

        # Execute refresh
        success, has_changes = shot_model_temp.refresh_shots()

        # Verify
        assert success, "Refresh should succeed"
        assert has_changes, "First refresh should detect changes"
        assert len(shot_model_temp.shots) == 3, "Should have 3 shots"

        # Verify shots are cached persistently
        cached = shot_model_temp.cache_manager.get_shots_no_ttl()
        assert cached is not None, "Shots should be cached"
        assert len(cached) == 3, "Cache should have 3 shots"

        # Verify no migrated shots yet
        migrated = shot_model_temp.cache_manager.get_shots_archive()
        assert migrated is None or len(migrated) == 0, "No migrations on first refresh"

    def test_third_refresh_add_shots(
        self, shot_model_temp: ShotModel, test_process_pool, qtbot
    ):
        """Test third refresh adding 3 new shots."""
        # Setup: Two refresh outputs - first with 3 shots, second with 6 shots
        test_process_pool.set_outputs(
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0010\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0020\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0030\n",
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0010\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0020\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0030\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0040\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0050\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0060\n",
            repeat=False,
        )
        success1, changes1 = shot_model_temp.refresh_shots()
        assert success1
        assert changes1

        # Execute: Third refresh adding 3 new shots (uses second output)
        success2, changes2 = shot_model_temp.refresh_shots()

        # Verify
        assert success2, "Third refresh should succeed"
        assert changes2, "Changes should be detected"
        assert len(shot_model_temp.shots) == 6, "Should have 6 shots total"

        # Verify new shots are in cache
        cached = shot_model_temp.cache_manager.get_shots_no_ttl()
        assert cached is not None
        assert len(cached) == 6, "Cache should have 6 shots"

        # Verify shot names (parser extracts just the shot part, not sequence_shot)
        shot_names = {s.shot for s in shot_model_temp.shots}
        expected = {
            "0010",
            "0020",
            "0030",
            "0040",
            "0050",
            "0060",
        }
        assert shot_names == expected, "Should have all 6 expected shots"

    def test_fourth_refresh_remove_shots(
        self, shot_model_temp: ShotModel, test_process_pool, qtbot
    ):
        """Test fourth refresh with 3 shots removed - migrated to Previous Shots."""
        # Setup: Two refresh outputs - first with 6 shots, second with 3 shots
        test_process_pool.set_outputs(
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0010\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0020\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0030\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0040\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0050\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0060\n",
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0010\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0020\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0030\n",
            repeat=False,
        )
        success1, changes1 = shot_model_temp.refresh_shots()
        assert success1
        assert changes1
        assert len(shot_model_temp.shots) == 6

        # Execute: Fourth refresh with 3 shots removed (uses second output)
        success2, changes2 = shot_model_temp.refresh_shots()

        # Verify
        assert success2, "Fourth refresh should succeed"
        assert changes2, "Changes should be detected (removals)"
        assert len(shot_model_temp.shots) == 3, "Should have 3 remaining shots"

        # Verify removed shots are migrated
        migrated = shot_model_temp.cache_manager.get_shots_archive()
        assert migrated is not None, "Migrated cache should exist"
        assert len(migrated) == 3, "Should have 3 migrated shots"

        # Verify migrated shot names
        migrated_names = {s["shot"] for s in migrated}
        expected_migrated = {"0040", "0050", "0060"}
        assert migrated_names == expected_migrated, "Correct shots should be migrated"

        # Verify remaining shot names
        remaining_names = {s.shot for s in shot_model_temp.shots}
        expected_remaining = {"0010", "0020", "0030"}
        assert remaining_names == expected_remaining, (
            "Correct shots should remain active"
        )

    def test_migration_deduplication(
        self, shot_model_temp: ShotModel, test_process_pool, qtbot
    ):
        """Test that duplicate migrations are prevented via composite keys."""
        # Setup: Two refresh outputs - initial 3 shots, then remove all
        test_process_pool.set_outputs(
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0010\n"
            "workspace /shows/broken_eggs/shots/sq0010/sq0010_0020\n"
            "workspace /shows/gator/shots/sq0010/sq0010_0010\n",  # Same seq/shot, different show
            "",  # Empty ws -sg output (all removed)
            repeat=False,
        )
        success1, changes1 = shot_model_temp.refresh_shots()
        assert success1
        assert changes1
        assert len(shot_model_temp.shots) == 3

        # Execute: Remove all 3 shots (migration)
        success2, changes2 = shot_model_temp.refresh_shots()
        assert success2
        assert changes2
        assert len(shot_model_temp.shots) == 0

        # Verify migration with deduplication
        migrated = shot_model_temp.cache_manager.get_shots_archive()
        assert migrated is not None
        assert len(migrated) == 3, "All 3 shots should be migrated"

        # Verify composite keys work: both shots named "0010" preserved with different shows
        composite_keys = {(s["show"], s["sequence"], s["shot"]) for s in migrated}
        expected_keys = {
            ("broken_eggs", "sq0010", "0010"),
            ("broken_eggs", "sq0010", "0020"),
            ("gator", "sq0010", "0010"),  # Same seq/shot, different show
        }
        assert composite_keys == expected_keys, (
            "Composite keys should preserve cross-show uniqueness"
        )

        # Test duplicate migration prevention by migrating same shots again
        shot_model_temp.cache_manager.archive_shots_as_previous(
            [
                {
                    "show": "broken_eggs",
                    "sequence": "sq0010",
                    "shot": "0010",
                    "workspace_path": "/test1",
                },
                {
                    "show": "gator",
                    "sequence": "sq0010",
                    "shot": "0010",
                    "workspace_path": "/test2",
                },
            ]
        )

        # Verify still only 3 unique shots (duplicates not added)
        migrated_final = shot_model_temp.cache_manager.get_shots_archive()
        assert migrated_final is not None
        assert len(migrated_final) == 3, "Deduplication should prevent duplicates"
