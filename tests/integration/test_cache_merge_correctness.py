"""Integration tests for cache merge correctness.

This module tests:
1. Shot merge - deduplication by (show, sequence, shot) key
2. Scene merge - deduplication, age-based pruning, last_seen tracking
3. Concurrent merge operations - thread safety
4. Edge cases - empty lists, duplicate keys, deleted items

These are integration tests because they test the interaction between:
- CacheManager merge methods
- Internal data structures (dicts, sets)
- Thread safety mechanisms (QMutex)
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cache_manager import CacheManager, SceneMergeResult, ShotMergeResult
from type_definitions import Shot, ShotDict, ThreeDESceneDict


pytestmark = [
    pytest.mark.integration,
    pytest.mark.legacy,
]


# ==============================================================================
# Test Data Factories
# ==============================================================================


def make_shot_dict(
    show: str = "testshow",
    sequence: str = "sq010",
    shot: str = "0010",
    workspace_path: str | None = None,
    discovered_at: float = 0.0,
) -> ShotDict:
    """Create a ShotDict for testing."""
    if workspace_path is None:
        workspace_path = f"/shows/{show}/shots/{sequence}/{sequence}_{shot}"
    return {
        "show": show,
        "sequence": sequence,
        "shot": shot,
        "workspace_path": workspace_path,
        "discovered_at": discovered_at,
    }


def make_scene_dict(
    show: str = "testshow",
    sequence: str = "sq010",
    shot: str = "0010",
    user: str = "artist",
    filename: str = "scene.3de",
    modified_time: float | None = None,
    last_seen: float | None = None,
) -> ThreeDESceneDict:
    """Create a ThreeDESceneDict for testing."""
    if modified_time is None:
        modified_time = time.time()
    result: ThreeDESceneDict = {
        "filepath": f"/shows/{show}/shots/{sequence}/{sequence}_{shot}/3de/{user}/{filename}",
        "show": show,
        "sequence": sequence,
        "shot": shot,
        "user": user,
        "filename": filename,
        "modified_time": modified_time,
        "workspace_path": f"/shows/{show}/shots/{sequence}/{sequence}_{shot}",
    }
    if last_seen is not None:
        result["last_seen"] = last_seen
    return result


# ==============================================================================
# Shot Merge Tests
# ==============================================================================


@pytest.mark.integration
class TestShotMergeCorrectness:
    """Tests for shot merge algorithm correctness."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_merge_with_empty_cached(self, cache_manager: CacheManager) -> None:
        """Merge with empty cache returns all fresh shots as new."""
        fresh = [
            make_shot_dict(shot="0010"),
            make_shot_dict(shot="0020"),
        ]

        result = cache_manager.merge_shots_incremental(None, fresh)

        assert len(result.updated_shots) == 2
        assert len(result.new_shots) == 2
        assert len(result.removed_shots) == 0
        assert result.has_changes is True

    def test_merge_with_empty_fresh(self, cache_manager: CacheManager) -> None:
        """Merge with empty fresh marks all cached as removed."""
        cached = [
            make_shot_dict(shot="0010"),
            make_shot_dict(shot="0020"),
        ]

        result = cache_manager.merge_shots_incremental(cached, [])

        assert len(result.updated_shots) == 0
        assert len(result.new_shots) == 0
        assert len(result.removed_shots) == 2
        assert result.has_changes is True

    def test_merge_no_changes(self, cache_manager: CacheManager) -> None:
        """Merge with identical cached and fresh has no changes."""
        shots = [
            make_shot_dict(shot="0010"),
            make_shot_dict(shot="0020"),
        ]

        result = cache_manager.merge_shots_incremental(shots, shots)

        assert len(result.updated_shots) == 2
        assert len(result.new_shots) == 0
        assert len(result.removed_shots) == 0
        assert result.has_changes is False

    def test_merge_new_shot_added(self, cache_manager: CacheManager) -> None:
        """Merge detects new shots not in cache."""
        cached = [make_shot_dict(shot="0010")]
        fresh = [
            make_shot_dict(shot="0010"),
            make_shot_dict(shot="0020"),  # New shot
        ]

        result = cache_manager.merge_shots_incremental(cached, fresh)

        assert len(result.updated_shots) == 2
        assert len(result.new_shots) == 1
        assert result.new_shots[0]["shot"] == "0020"
        assert result.has_changes is True

    def test_merge_shot_removed(self, cache_manager: CacheManager) -> None:
        """Merge detects shots removed from fresh data."""
        cached = [
            make_shot_dict(shot="0010"),
            make_shot_dict(shot="0020"),
        ]
        fresh = [make_shot_dict(shot="0010")]  # 0020 removed

        result = cache_manager.merge_shots_incremental(cached, fresh)

        assert len(result.updated_shots) == 1
        assert len(result.removed_shots) == 1
        assert result.removed_shots[0]["shot"] == "0020"
        assert result.has_changes is True

    def test_deduplication_by_composite_key(self, cache_manager: CacheManager) -> None:
        """Shots are deduplicated by (show, sequence, shot) key."""
        # Same shot in both cached and fresh should not create duplicates
        cached = [make_shot_dict(show="showA", sequence="sq01", shot="0010")]
        fresh = [make_shot_dict(show="showA", sequence="sq01", shot="0010")]

        result = cache_manager.merge_shots_incremental(cached, fresh)

        assert len(result.updated_shots) == 1  # Not 2

    def test_different_shows_not_deduplicated(self, cache_manager: CacheManager) -> None:
        """Shots from different shows are kept separate."""
        cached = [make_shot_dict(show="showA", shot="0010")]
        fresh = [
            make_shot_dict(show="showA", shot="0010"),
            make_shot_dict(show="showB", shot="0010"),  # Different show, same shot name
        ]

        result = cache_manager.merge_shots_incremental(cached, fresh)

        assert len(result.updated_shots) == 2  # Both kept
        assert len(result.new_shots) == 1  # showB shot is new

    def test_different_sequences_not_deduplicated(
        self, cache_manager: CacheManager
    ) -> None:
        """Shots from different sequences are kept separate."""
        fresh = [
            make_shot_dict(sequence="sq01", shot="0010"),
            make_shot_dict(sequence="sq02", shot="0010"),  # Same shot, different seq
        ]

        result = cache_manager.merge_shots_incremental(None, fresh)

        assert len(result.updated_shots) == 2

    def test_fresh_data_overrides_cached(self, cache_manager: CacheManager) -> None:
        """Fresh shot data takes precedence over cached."""
        old_time = 1000.0
        new_time = 2000.0

        cached = [make_shot_dict(shot="0010", discovered_at=old_time)]
        fresh = [make_shot_dict(shot="0010", discovered_at=new_time)]

        result = cache_manager.merge_shots_incremental(cached, fresh)

        # Fresh data should be used
        assert result.updated_shots[0]["discovered_at"] == new_time

    def test_merge_accepts_shot_objects(self, cache_manager: CacheManager) -> None:
        """Merge works with Shot objects (not just dicts)."""
        cached = [
            Shot(
                show="testshow",
                sequence="sq010",
                shot="0010",
                workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            )
        ]
        fresh = [
            Shot(
                show="testshow",
                sequence="sq010",
                shot="0010",
                workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            ),
            Shot(
                show="testshow",
                sequence="sq010",
                shot="0020",
                workspace_path="/shows/testshow/shots/sq010/sq010_0020",
            ),
        ]

        result = cache_manager.merge_shots_incremental(cached, fresh)

        assert len(result.updated_shots) == 2
        assert len(result.new_shots) == 1


# ==============================================================================
# Scene Merge Tests
# ==============================================================================


@pytest.mark.integration
class TestSceneMergeCorrectness:
    """Tests for scene merge algorithm correctness."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_merge_with_empty_cached(self, cache_manager: CacheManager) -> None:
        """Merge with empty cache returns all fresh scenes as new."""
        fresh = [
            make_scene_dict(shot="0010"),
            make_scene_dict(shot="0020"),
        ]

        result = cache_manager.merge_scenes_incremental(None, fresh)

        assert len(result.updated_scenes) == 2
        assert len(result.new_scenes) == 2
        assert result.has_changes is True

    def test_merge_with_empty_fresh_keeps_recent(
        self, cache_manager: CacheManager
    ) -> None:
        """Merge with empty fresh keeps recently-seen cached scenes."""
        now = datetime.now(UTC).timestamp()
        cached = [
            make_scene_dict(shot="0010", last_seen=now),
            make_scene_dict(shot="0020", last_seen=now),
        ]

        result = cache_manager.merge_scenes_incremental(cached, [], max_age_days=60)

        # Scenes with recent last_seen should be kept
        assert len(result.updated_scenes) == 2
        assert len(result.removed_scenes) == 2  # Tracked as "not in fresh"

    def test_merge_prunes_old_scenes(self, cache_manager: CacheManager) -> None:
        """Merge prunes scenes not seen within max_age_days."""
        now = datetime.now(UTC).timestamp()
        old_time = now - (70 * 24 * 60 * 60)  # 70 days ago

        cached = [
            make_scene_dict(shot="0010", last_seen=old_time),  # Too old
            make_scene_dict(shot="0020", last_seen=now),  # Recent
        ]

        result = cache_manager.merge_scenes_incremental(cached, [], max_age_days=60)

        # Only recent scene should be kept
        assert len(result.updated_scenes) == 1
        assert result.updated_scenes[0]["shot"] == "0020"
        assert result.pruned_count == 1

    def test_last_seen_updated_on_merge(self, cache_manager: CacheManager) -> None:
        """Last_seen timestamp is updated when scene is in fresh data."""
        fresh = [make_scene_dict(shot="0010")]

        result = cache_manager.merge_scenes_incremental(None, fresh)

        # last_seen should be set to current time (approximately)
        now = datetime.now(UTC).timestamp()
        assert "last_seen" in result.updated_scenes[0]
        assert result.updated_scenes[0]["last_seen"] >= now - 1  # Within 1 second

    def test_deduplication_by_shot_key(self, cache_manager: CacheManager) -> None:
        """Scenes are deduplicated by (show, sequence, shot) key."""
        # Two scenes for same shot - fresh takes precedence
        cached = [make_scene_dict(shot="0010", user="user1", filename="old.3de")]
        fresh = [make_scene_dict(shot="0010", user="user2", filename="new.3de")]

        result = cache_manager.merge_scenes_incremental(cached, fresh)

        # Should have only 1 scene (fresh version)
        assert len(result.updated_scenes) == 1
        assert result.updated_scenes[0]["user"] == "user2"

    def test_different_shots_not_deduplicated(
        self, cache_manager: CacheManager
    ) -> None:
        """Scenes from different shots are kept separate."""
        fresh = [
            make_scene_dict(shot="0010", user="artist1"),
            make_scene_dict(shot="0020", user="artist2"),
        ]

        result = cache_manager.merge_scenes_incremental(None, fresh)

        assert len(result.updated_scenes) == 2

    def test_cached_scene_without_last_seen_gets_default(
        self, cache_manager: CacheManager
    ) -> None:
        """Cached scenes without last_seen get current time as default."""
        # Legacy cache entry without last_seen field
        cached: list[ThreeDESceneDict] = [
            {
                "filepath": "/path/to/scene.3de",
                "show": "testshow",
                "sequence": "sq010",
                "shot": "0010",
                "user": "artist",
                "filename": "scene.3de",
                "modified_time": 1000.0,
                "workspace_path": "/shows/testshow/shots/sq010/sq010_0010",
                # No last_seen field
            }
        ]

        result = cache_manager.merge_scenes_incremental(cached, [], max_age_days=60)

        # Should be kept (default last_seen = now)
        assert len(result.updated_scenes) == 1


# ==============================================================================
# Thread Safety Tests
# ==============================================================================


@pytest.mark.integration
class TestMergeThreadSafety:
    """Tests for merge operations under concurrent access."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_concurrent_shot_merge_no_crash(
        self, cache_manager: CacheManager
    ) -> None:
        """Multiple threads calling merge_shots_incremental don't crash."""
        errors: list[Exception] = []
        results: list[ShotMergeResult] = []
        lock = threading.Lock()

        def do_merge(thread_id: int) -> None:
            try:
                cached = [make_shot_dict(shot=f"{thread_id:04d}")]
                fresh = [
                    make_shot_dict(shot=f"{thread_id:04d}"),
                    make_shot_dict(shot=f"{thread_id + 100:04d}"),
                ]
                result = cache_manager.merge_shots_incremental(cached, fresh)
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)

        # Run many concurrent merges
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(do_merge, i) for i in range(50)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(results) == 50

    def test_concurrent_scene_merge_no_crash(
        self, cache_manager: CacheManager
    ) -> None:
        """Multiple threads calling merge_scenes_incremental don't crash."""
        errors: list[Exception] = []
        results: list[SceneMergeResult] = []
        lock = threading.Lock()

        def do_merge(thread_id: int) -> None:
            try:
                cached = [make_scene_dict(shot=f"{thread_id:04d}")]
                fresh = [
                    make_scene_dict(shot=f"{thread_id:04d}"),
                    make_scene_dict(shot=f"{thread_id + 100:04d}"),
                ]
                result = cache_manager.merge_scenes_incremental(cached, fresh)
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(do_merge, i) for i in range(50)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(results) == 50

    def test_concurrent_mixed_merges(self, cache_manager: CacheManager) -> None:
        """Shot and scene merges can run concurrently without issues."""
        errors: list[Exception] = []
        lock = threading.Lock()

        def do_shot_merge() -> None:
            try:
                for _ in range(20):
                    cached = [make_shot_dict(shot="0010")]
                    fresh = [make_shot_dict(shot="0010"), make_shot_dict(shot="0020")]
                    cache_manager.merge_shots_incremental(cached, fresh)
            except Exception as e:
                with lock:
                    errors.append(e)

        def do_scene_merge() -> None:
            try:
                for _ in range(20):
                    cached = [make_scene_dict(shot="0010")]
                    fresh = [
                        make_scene_dict(shot="0010"),
                        make_scene_dict(shot="0020"),
                    ]
                    cache_manager.merge_scenes_incremental(cached, fresh)
            except Exception as e:
                with lock:
                    errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(do_shot_merge),
                executor.submit(do_shot_merge),
                executor.submit(do_scene_merge),
                executor.submit(do_scene_merge),
            ]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Thread errors: {errors}"


# ==============================================================================
# Edge Case Tests
# ==============================================================================


@pytest.mark.integration
class TestMergeEdgeCases:
    """Tests for merge edge cases and boundary conditions."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_merge_large_shot_lists(self, cache_manager: CacheManager) -> None:
        """Merge handles large lists efficiently."""
        cached = [make_shot_dict(shot=f"{i:04d}") for i in range(500)]
        fresh = [make_shot_dict(shot=f"{i:04d}") for i in range(100, 600)]

        result = cache_manager.merge_shots_incremental(cached, fresh)

        # 500 fresh shots total
        assert len(result.updated_shots) == 500
        # Shots 0-99 removed (not in fresh)
        assert len(result.removed_shots) == 100
        # Shots 500-599 are new
        assert len(result.new_shots) == 100

    def test_merge_with_duplicate_keys_in_fresh(
        self, cache_manager: CacheManager
    ) -> None:
        """Merge iterates fresh data, so duplicates in input produce duplicates in output.

        Note: The implementation doesn't deduplicate fresh data - callers should
        ensure fresh data is already deduplicated before calling merge.
        This test documents the actual behavior.
        """
        fresh = [
            make_shot_dict(shot="0010", discovered_at=1.0),
            make_shot_dict(shot="0010", discovered_at=2.0),  # Duplicate
        ]

        result = cache_manager.merge_shots_incremental(None, fresh)

        # Implementation iterates fresh directly, so duplicates are preserved
        # This is expected - deduplication should happen before merge
        assert len(result.updated_shots) == 2

    def test_merge_preserves_all_fresh_fields(
        self, cache_manager: CacheManager
    ) -> None:
        """Merge preserves all fields from fresh data."""
        fresh = [
            make_shot_dict(
                show="myshow",
                sequence="seq01",
                shot="0010",
                workspace_path="/custom/path",
                discovered_at=12345.0,
            )
        ]

        result = cache_manager.merge_shots_incremental(None, fresh)

        shot = result.updated_shots[0]
        assert shot["show"] == "myshow"
        assert shot["sequence"] == "seq01"
        assert shot["shot"] == "0010"
        assert shot["workspace_path"] == "/custom/path"
        assert shot["discovered_at"] == 12345.0

    def test_scene_merge_with_various_max_age(
        self, cache_manager: CacheManager
    ) -> None:
        """Scene merge respects different max_age_days settings."""
        now = datetime.now(UTC).timestamp()
        days_10_ago = now - (10 * 24 * 60 * 60)

        cached = [make_scene_dict(shot="0010", last_seen=days_10_ago)]

        # With 5 day max age - should be pruned
        result_5days = cache_manager.merge_scenes_incremental(
            cached, [], max_age_days=5
        )
        assert result_5days.pruned_count == 1

        # With 30 day max age - should be kept
        result_30days = cache_manager.merge_scenes_incremental(
            cached, [], max_age_days=30
        )
        assert result_30days.pruned_count == 0
        assert len(result_30days.updated_scenes) == 1

    def test_merge_empty_both_lists(self, cache_manager: CacheManager) -> None:
        """Merge with both empty lists returns empty result."""
        result = cache_manager.merge_shots_incremental([], [])

        assert len(result.updated_shots) == 0
        assert len(result.new_shots) == 0
        assert len(result.removed_shots) == 0
        assert result.has_changes is False

    def test_merge_with_none_cached(self, cache_manager: CacheManager) -> None:
        """Merge handles None cached list gracefully."""
        fresh = [make_shot_dict(shot="0010")]

        result = cache_manager.merge_shots_incremental(None, fresh)

        assert len(result.updated_shots) == 1
        assert len(result.new_shots) == 1


# ==============================================================================
# Result Validation Tests
# ==============================================================================


@pytest.mark.integration
class TestMergeResultCorrectness:
    """Tests that verify merge results are correct and consistent."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_shot_merge_result_invariants(self, cache_manager: CacheManager) -> None:
        """Verify ShotMergeResult invariants hold."""
        cached = [
            make_shot_dict(shot="0010"),
            make_shot_dict(shot="0020"),
        ]
        fresh = [
            make_shot_dict(shot="0020"),
            make_shot_dict(shot="0030"),
        ]

        result = cache_manager.merge_shots_incremental(cached, fresh)

        # Invariant: updated_shots = fresh shots (all fresh data)
        assert len(result.updated_shots) == len(fresh)

        # Invariant: new_shots ⊆ updated_shots
        for new_shot in result.new_shots:
            key = (new_shot["show"], new_shot["sequence"], new_shot["shot"])
            updated_keys = [
                (s["show"], s["sequence"], s["shot"]) for s in result.updated_shots
            ]
            assert key in updated_keys

        # Invariant: removed_shots are from cached, not in fresh
        for removed_shot in result.removed_shots:
            key = (removed_shot["show"], removed_shot["sequence"], removed_shot["shot"])
            fresh_keys = [(s["show"], s["sequence"], s["shot"]) for s in fresh]
            assert key not in fresh_keys

    def test_scene_merge_result_invariants(self, cache_manager: CacheManager) -> None:
        """Verify SceneMergeResult invariants hold."""
        now = datetime.now(UTC).timestamp()
        cached = [
            make_scene_dict(shot="0010", last_seen=now),
            make_scene_dict(shot="0020", last_seen=now),
        ]
        fresh = [
            make_scene_dict(shot="0020"),
            make_scene_dict(shot="0030"),
        ]

        result = cache_manager.merge_scenes_incremental(cached, fresh)

        # Invariant: all updated_scenes have last_seen set
        for scene in result.updated_scenes:
            assert "last_seen" in scene

        # Invariant: new_scenes are in updated_scenes
        for new_scene in result.new_scenes:
            key = (new_scene["show"], new_scene["sequence"], new_scene["shot"])
            updated_keys = [
                (s["show"], s["sequence"], s["shot"]) for s in result.updated_scenes
            ]
            assert key in updated_keys

    def test_has_changes_flag_accuracy(self, cache_manager: CacheManager) -> None:
        """has_changes flag accurately reflects actual changes."""
        shots = [make_shot_dict(shot="0010")]

        # No changes - same data
        result1 = cache_manager.merge_shots_incremental(shots, shots)
        assert result1.has_changes is False

        # Has changes - new shot
        result2 = cache_manager.merge_shots_incremental(
            shots, [*shots, make_shot_dict(shot="0020")]
        )
        assert result2.has_changes is True

        # Has changes - shot removed
        result3 = cache_manager.merge_shots_incremental(shots, [])
        assert result3.has_changes is True
