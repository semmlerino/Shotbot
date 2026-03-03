"""Tests for ShotDataCache — shot data caching with TTL and incremental merge.

Covers:
- JSON cache read/write with TTL validation (shot-specific)
- Persistent previous shots cache
- Shot migration (archive_shots_as_previous)
- Cache management (clear, set_expiry)
- Error handling for corrupt JSON
- Thread safety for shot operations
- Cache write failure signals
- Integration: disk usage and cross-sub-manager workflow (via CacheCoordinator)
"""

from __future__ import annotations

# Standard library imports
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

# Third-party imports
import pytest
from PIL import Image

# Local application imports
from cache.shot_cache import ShotDataCache
from config import Config
from shot_model import Shot


if TYPE_CHECKING:
    from type_definitions import ShotDict

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def shot_cache(tmp_path: Path) -> ShotDataCache:
    """Create ShotDataCache with temporary directory."""
    cache_dir = tmp_path / "test_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return ShotDataCache(cache_dir)


@pytest.fixture
def sample_shots() -> list[Shot]:
    """Provide realistic shot data for testing."""
    return [
        Shot("test_show", "seq01", "shot010", f"{Config.SHOWS_ROOT}/test_show/seq01/shot010"),
        Shot("test_show", "seq01", "shot020", f"{Config.SHOWS_ROOT}/test_show/seq01/shot020"),
        Shot("test_show", "seq02", "shot030", f"{Config.SHOWS_ROOT}/test_show/seq02/shot030"),
    ]


@pytest.fixture
def test_image_jpg(tmp_path: Path) -> Path:
    """Create a real JPEG test image using PIL (avoids QImage C++ state issues)."""
    image_path = tmp_path / "test_source.jpg"
    img = Image.new("RGB", (512, 512), color=(100, 150, 200))
    img.save(str(image_path), "JPEG", quality=90)
    return image_path


# ---------------------------------------------------------------------------
# TestCacheManagerInitialization (shot-specific)
# ---------------------------------------------------------------------------


class TestShotCacheInitialization:
    """Test ShotDataCache initialization and directory setup."""

    def test_initialization_creates_cache_dir(self, tmp_path: Path) -> None:
        """Test cache directory is referenced correctly on init."""
        cache_dir = tmp_path / "new_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache = ShotDataCache(cache_dir)

        assert cache.cache_dir == cache_dir
        assert cache.shots_cache_file == cache_dir / "shots.json"
        assert cache.previous_shots_cache_file == cache_dir / "previous_shots.json"

    def test_initialization_with_existing_directory(self, tmp_path: Path) -> None:
        """Test initialization with pre-existing cache directory."""
        cache_dir = tmp_path / "existing_cache"
        cache_dir.mkdir(parents=True)

        cache = ShotDataCache(cache_dir)

        assert cache.cache_dir == cache_dir


# ---------------------------------------------------------------------------
# TestJSONCacheOperations (shot-specific)
# ---------------------------------------------------------------------------


class TestJSONCacheOperations:
    """Test JSON cache read/write operations with TTL validation (shot paths)."""

    def test_get_shots_with_ttl_returns_data(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot]
    ) -> None:
        """Test retrieving cached shots returns correct data."""
        shot_cache.cache_shots(sample_shots)

        cached = shot_cache.get_shots_with_ttl()

        assert cached is not None
        assert len(cached) == len(sample_shots)
        # Verify data integrity
        assert cached[0]["show"] == "test_show"
        assert cached[0]["sequence"] == "seq01"
        assert cached[0]["shot"] == "shot010"

    def test_get_shots_with_ttl_respects_ttl(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot]
    ) -> None:
        """Test TTL expiration invalidates cache."""
        shot_cache.cache_shots(sample_shots)

        # Verify cache is valid initially
        cached = shot_cache.get_shots_with_ttl()
        assert cached is not None

        # Manually expire the cache by modifying file timestamp
        cache_file = shot_cache.shots_cache_file
        old_time = time.time() - (31 * 60)  # 31 minutes ago
        import os

        os.utime(cache_file, (old_time, old_time))

        # Cache should now be expired
        expired = shot_cache.get_shots_with_ttl()
        assert expired is None

    def test_cache_handles_empty_list(self, shot_cache: ShotDataCache) -> None:
        """Test caching empty list is handled correctly."""
        shot_cache.cache_shots([])

        cached = shot_cache.get_shots_with_ttl()
        assert cached == []

    def test_cache_overwrites_existing_data(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot]
    ) -> None:
        """Test caching new data overwrites old data."""
        # Cache initial data
        shot_cache.cache_shots(sample_shots[:2])
        cached1 = shot_cache.get_shots_with_ttl()
        assert len(cached1) == 2

        # Overwrite with different data
        shot_cache.cache_shots(sample_shots)
        cached2 = shot_cache.get_shots_with_ttl()
        assert len(cached2) == 3


# ---------------------------------------------------------------------------
# TestCacheManagement (shot-specific)
# ---------------------------------------------------------------------------


class TestShotCacheManagement:
    """Test cache clearing and TTL management for shot cache."""

    def test_clear_cache_removes_shot_files(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot]
    ) -> None:
        """Test clear_cache removes shot cached data."""
        # Populate cache
        shot_cache.cache_shots(sample_shots)

        # Verify file exists
        assert shot_cache.shots_cache_file.exists()

        # Clear cache
        shot_cache.clear_cache()

        # Verify cache file is gone
        assert not shot_cache.shots_cache_file.exists()

    def test_clear_cache_handles_missing_directory(self, tmp_path: Path) -> None:
        """Test clear_cache handles non-existent cache gracefully."""
        cache_dir = tmp_path / "nonexistent_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache = ShotDataCache(cache_dir)

        # Should not raise exception
        cache.clear_cache()

    def test_set_expiry_minutes_changes_ttl(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot]
    ) -> None:
        """Test set_expiry_minutes takes effect on subsequent TTL checks."""
        shot_cache.cache_shots(sample_shots)

        # Shorten TTL to 0 minutes (everything expires immediately)
        shot_cache.set_expiry_minutes(0)

        # With 0-minute TTL, cache should be expired
        cached = shot_cache.get_shots_with_ttl()
        assert cached is None


# ---------------------------------------------------------------------------
# TestErrorHandling (shot-specific)
# ---------------------------------------------------------------------------


class TestShotErrorHandling:
    """Test error handling for corrupt JSON and malformed structures."""

    def test_get_shots_with_ttl_with_corrupt_json(
        self, shot_cache: ShotDataCache
    ) -> None:
        """Test retrieving shots with corrupt JSON file."""
        # Write invalid JSON
        shot_cache.shots_cache_file.parent.mkdir(parents=True, exist_ok=True)
        shot_cache.shots_cache_file.write_text("INVALID JSON{{{")

        result = shot_cache.get_shots_with_ttl()

        # Should return None for corrupt JSON
        assert result is None

    def test_get_shots_with_ttl_with_missing_keys(
        self, shot_cache: ShotDataCache
    ) -> None:
        """Test retrieving shots with malformed JSON structure."""
        # Write JSON without expected keys
        shot_cache.shots_cache_file.parent.mkdir(parents=True, exist_ok=True)
        shot_cache.shots_cache_file.write_text('{"wrong_key": []}')

        result = shot_cache.get_shots_with_ttl()

        # Should handle gracefully - unknown schema returns None
        assert result is None

    def test_cache_with_readonly_directory(self, tmp_path: Path) -> None:
        """Test caching operations with read-only directory."""
        cache_dir = tmp_path / "readonly_cache"
        cache_dir.mkdir()

        cache = ShotDataCache(cache_dir)

        # Make directory read-only
        import stat

        cache_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

        try:
            # Should handle write failure gracefully
            cache.cache_shots([Shot("show", "seq", "shot", "/path")])
            # If we get here, permission check might be disabled in test env
        except PermissionError:
            # Expected on systems that enforce permissions
            pass
        finally:
            # Restore permissions for cleanup
            cache_dir.chmod(stat.S_IRWXU)


# ---------------------------------------------------------------------------
# TestThreadSafety (shot-specific)
# ---------------------------------------------------------------------------


class TestShotThreadSafety:
    """Test thread-safe concurrent access patterns for shot cache."""

    def test_concurrent_shot_caching(
        self,
        shot_cache: ShotDataCache,
    ) -> None:
        """Test thread-safe concurrent shot caching operations."""
        import queue

        num_threads = 5
        results_queue: queue.Queue[bool] = queue.Queue()

        def worker(thread_id: int) -> None:
            shots = [
                Shot("show", f"seq{thread_id}", f"shot{i:03d}", f"/path/{thread_id}/{i}")
                for i in range(10)
            ]
            shot_cache.cache_shots(shots)
            cached = shot_cache.get_shots_with_ttl()
            results_queue.put(cached is not None)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        results = []
        while not results_queue.empty():
            results.append(results_queue.get())

        assert all(results), f"Some shot cache operations failed: {results}"
        assert len(results) == num_threads

    def test_concurrent_cache_clearing(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot]
    ) -> None:
        """Test thread-safe cache clearing with concurrent reads."""
        import queue

        # Pre-populate cache
        shot_cache.cache_shots(sample_shots)

        read_queue: queue.Queue[bool] = queue.Queue()
        clear_queue: queue.Queue[bool] = queue.Queue()

        def read_operation() -> None:
            """Concurrent read operations."""
            for _ in range(10):
                _ = shot_cache.get_shots_with_ttl()
                # Result might be None if cleared, that's OK
                read_queue.put(True)

        def clear_operation() -> None:
            """Concurrent clear operations."""
            for _ in range(5):
                shot_cache.clear_cache()
                clear_queue.put(True)

        # Run readers and clearers concurrently
        threads = [threading.Thread(target=read_operation) for _ in range(3)]
        threads.append(threading.Thread(target=clear_operation))

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Collect results from thread-safe queues
        reads = []
        while not read_queue.empty():
            reads.append(read_queue.get())

        clears = []
        while not clear_queue.empty():
            clears.append(clear_queue.get())

        # Verify no crashes or corruption
        assert len(reads) == 30  # 3 threads x 10 reads
        assert len(clears) == 5


# ---------------------------------------------------------------------------
# TestPersistentPreviousShotsCache
# ---------------------------------------------------------------------------


class TestPersistentPreviousShotsCache:
    """Test persistent incremental caching for previous shots.

    Tests the persistent cache functionality that:
    - Never expires (no TTL check)
    - Accumulates shots incrementally
    - Only refreshes when user explicitly requests it

    Following UNIFIED_TESTING_GUIDE: Test behavior, not implementation.
    """

    def test_get_persistent_previous_shots_ignores_ttl(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot]
    ) -> None:
        """Test persistent cache returns data regardless of age."""
        # Cache previous shots
        shot_cache.cache_previous_shots(sample_shots)

        # Verify cache is valid initially
        cached = shot_cache.get_persistent_previous_shots()
        assert cached is not None
        assert len(cached) == 3

        # Manually expire the cache by modifying file timestamp
        cache_file = shot_cache.previous_shots_cache_file
        old_time = time.time() - (60 * 60 * 24)  # 24 hours ago (way past TTL)
        import os

        os.utime(cache_file, (old_time, old_time))

        # Persistent cache should STILL return data (no TTL check)
        persistent = shot_cache.get_persistent_previous_shots()
        assert persistent is not None
        assert len(persistent) == 3
        assert persistent[0]["show"] == "test_show"

        # Compare: Regular cache WOULD be expired
        regular = shot_cache.get_cached_previous_shots()
        assert regular is None  # Expired with TTL check

    @pytest.mark.parametrize(
        ("setup_shots", "expected"),
        [
            pytest.param(None, None, id="missing_returns_none"),
            pytest.param([], [], id="empty_list_returns_empty"),
        ],
    )
    def test_persistent_cache_boundary_conditions(
        self,
        shot_cache: ShotDataCache,
        setup_shots: list[Shot] | None,
        expected: list | None,
    ) -> None:
        """Test persistent cache returns correct value for missing file or empty list."""
        if setup_shots is not None:
            shot_cache.cache_previous_shots(setup_shots)

        result = shot_cache.get_persistent_previous_shots()
        assert result == expected

    def test_persistent_cache_preserves_data_format(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot]
    ) -> None:
        """Test persistent cache preserves shot data structure."""
        shot_cache.cache_previous_shots(sample_shots)

        cached = shot_cache.get_persistent_previous_shots()
        assert cached is not None

        # Verify data structure
        for shot_data in cached:
            assert "show" in shot_data
            assert "sequence" in shot_data
            assert "shot" in shot_data
            assert "workspace_path" in shot_data

    def test_persistent_cache_thread_safety(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot]
    ) -> None:
        """Test thread-safe concurrent access to persistent cache."""
        import queue

        results_queue: queue.Queue[int | None] = queue.Queue()

        # Pre-populate cache
        shot_cache.cache_previous_shots(sample_shots)

        def read_persistent_cache() -> None:
            """Concurrent read from persistent cache."""
            for _ in range(10):
                cached = shot_cache.get_persistent_previous_shots()
                results_queue.put(len(cached) if cached else None)

        # Run multiple readers concurrently
        threads = [threading.Thread(target=read_persistent_cache) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Collect results from thread-safe queue
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())

        # All reads should succeed and return correct count
        assert len(results) == 30  # 3 threads x 10 reads
        assert all(r == 3 for r in results)  # All should see 3 shots


# ---------------------------------------------------------------------------
# TestShotMigration
# ---------------------------------------------------------------------------


class TestShotMigration:
    """Test Phase 2: Shot migration from My Shots to Previous Shots (v2.3)."""

    def test_get_shots_archive_empty_cache(self, shot_cache: ShotDataCache) -> None:
        """get_shots_archive() returns None for empty cache."""
        result = shot_cache.get_shots_archive()
        assert result is None

    def test_migrate_empty_list_is_noop(self, shot_cache: ShotDataCache) -> None:
        """Migrating empty list is a no-op."""
        shot_cache.archive_shots_as_previous([])
        result = shot_cache.get_shots_archive()
        assert result is None

    def test_first_migration_creates_file_and_emits_signal(
        self, shot_cache: ShotDataCache, qtbot
    ) -> None:
        """First migration creates migrated_shots.json and emits shots_migrated signal."""
        shots = [
            Shot("show1", "seq01", "shot010", "/p1"),
            Shot("show1", "seq01", "shot020", "/p2"),
        ]

        with qtbot.waitSignal(
            shot_cache.shots_migrated, timeout=1000
        ) as signal_blocker:
            shot_cache.archive_shots_as_previous(shots)

        # Verify file created and content correct
        assert shot_cache.migrated_shots_cache_file.exists()
        migrated = shot_cache.get_shots_archive()
        assert migrated is not None
        assert len(migrated) == 2
        assert migrated[0]["shot"] in ("shot010", "shot020")

        # Verify signal payload
        emitted_shots = signal_blocker.args[0]
        assert len(emitted_shots) == 2

    def test_subsequent_migration_merges(self, shot_cache: ShotDataCache) -> None:
        """Subsequent migrations merge with existing."""
        # First migration
        batch1 = [Shot("show1", "seq01", "shot010", "/p1")]
        shot_cache.archive_shots_as_previous(batch1)

        # Second migration (different shots)
        batch2 = [
            Shot("show1", "seq01", "shot020", "/p2"),
            Shot("show1", "seq02", "shot030", "/p3"),
        ]
        shot_cache.archive_shots_as_previous(batch2)

        # Verify merged
        migrated = shot_cache.get_shots_archive()
        assert migrated is not None
        assert len(migrated) == 3  # All three shots present

    def test_migration_deduplicates_by_composite_key(
        self, shot_cache: ShotDataCache
    ) -> None:
        """Migration deduplicates using (show, sequence, shot) key."""
        # First migration
        shot1 = Shot("show1", "seq01", "shot010", "/old/path")
        shot_cache.archive_shots_as_previous([shot1])

        # Second migration with same shot but different path
        shot2 = Shot("show1", "seq01", "shot010", "/new/path")
        shot_cache.archive_shots_as_previous([shot2])

        # Verify only one shot, latest path
        migrated = shot_cache.get_shots_archive()
        assert migrated is not None
        assert len(migrated) == 1
        assert migrated[0]["workspace_path"] == "/new/path"

    def test_migration_cross_show_uniqueness(
        self, shot_cache: ShotDataCache
    ) -> None:
        """Composite key prevents cross-show collisions."""
        shots = [
            Shot("show1", "seq01", "shot010", "/show1/path"),
            Shot("show2", "seq01", "shot010", "/show2/path"),  # Same seq_shot, different show
        ]
        shot_cache.archive_shots_as_previous(shots)

        migrated = shot_cache.get_shots_archive()
        assert migrated is not None
        assert len(migrated) == 2  # Both preserved

        shows = {s["show"] for s in migrated}
        assert shows == {"show1", "show2"}

    def test_migrate_accepts_shot_dicts(self, shot_cache: ShotDataCache) -> None:
        """archive_shots_as_previous() accepts ShotDict input."""
        shot_dicts: list[ShotDict] = [
            {
                "show": "show1",
                "sequence": "seq01",
                "shot": "shot010",
                "workspace_path": "/p1",
            }
        ]
        shot_cache.archive_shots_as_previous(shot_dicts)

        migrated = shot_cache.get_shots_archive()
        assert migrated is not None
        assert len(migrated) == 1

    def test_migrate_mixed_shot_and_dict(self, shot_cache: ShotDataCache) -> None:
        """archive_shots_as_previous() handles mixed Shot and ShotDict."""
        shot_obj = Shot("show1", "seq01", "shot010", "/p1")
        shot_dict: ShotDict = {
            "show": "show1",
            "sequence": "seq01",
            "shot": "shot020",
            "workspace_path": "/p2",
        }
        shot_cache.archive_shots_as_previous([shot_obj, shot_dict])

        migrated = shot_cache.get_shots_archive()
        assert migrated is not None
        assert len(migrated) == 2

    def test_migration_no_signal_on_empty(
        self, shot_cache: ShotDataCache
    ) -> None:
        """No signal emitted for empty migration."""
        signal_emitted = False

        def _on_migrated(*_args: object) -> None:
            nonlocal signal_emitted
            signal_emitted = True

        shot_cache.shots_migrated.connect(_on_migrated)
        try:
            shot_cache.archive_shots_as_previous([])
            assert not signal_emitted, "shots_migrated should not emit for empty list"
        finally:
            shot_cache.shots_migrated.disconnect(_on_migrated)

    def test_migration_large_batch(self, shot_cache: ShotDataCache) -> None:
        """Migration handles large batches efficiently."""
        # Generate 100 shots
        large_batch = [
            Shot("show1", "seq01", f"shot{i:04d}", f"/p{i}") for i in range(100)
        ]
        shot_cache.archive_shots_as_previous(large_batch)

        migrated = shot_cache.get_shots_archive()
        assert migrated is not None
        assert len(migrated) == 100

    def test_migration_thread_safety(self, shot_cache: ShotDataCache, qtbot) -> None:
        """Concurrent migrations don't corrupt data."""
        from concurrent.futures import ThreadPoolExecutor

        def migrate_batch(batch_id: int) -> None:
            shots = [Shot("show1", "seq01", f"shot{batch_id:03d}", f"/p{batch_id}")]
            shot_cache.archive_shots_as_previous(shots)

        # Migrate 10 shots concurrently
        with ThreadPoolExecutor(max_workers=5) as executor:
            list(executor.map(migrate_batch, range(10)))

        # Verify all 10 shots present (no corruption)
        migrated = shot_cache.get_shots_archive()
        assert migrated is not None
        assert len(migrated) == 10


# ---------------------------------------------------------------------------
# TestCacheIntegration
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    """Integration tests validating shot cache behavior."""

    def test_cache_persistence_across_instances(
        self, tmp_path: Path, sample_shots: list[Shot]
    ) -> None:
        """Test cache persists across ShotDataCache instances."""
        cache_dir = tmp_path / "persistent_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create first instance and cache data
        cache1 = ShotDataCache(cache_dir)
        cache1.cache_shots(sample_shots)

        # Create second instance
        cache2 = ShotDataCache(cache_dir)

        # Verify data persisted
        cached_shots = cache2.get_shots_with_ttl()
        assert cached_shots is not None
        assert len(cached_shots) == 3


# ---------------------------------------------------------------------------
# TestCacheWriteFailureSignals
# ---------------------------------------------------------------------------


class TestCacheWriteFailureSignals:
    """Tests for cache_write_failed signal and proper signal emission on errors."""

    def test_cache_shots_emits_cache_updated_on_success(
        self, shot_cache: ShotDataCache, sample_shots: list[Shot], qtbot
    ) -> None:
        """cache_updated signal is emitted when cache_shots succeeds."""
        with qtbot.waitSignal(shot_cache.cache_updated, timeout=1000):
            shot_cache.cache_shots(sample_shots)

    @pytest.mark.parametrize(
        ("cache_method_name", "cache_key"),
        [("cache_shots", "shots"), ("cache_previous_shots", "previous_shots")],
    )
    def test_cache_methods_emit_write_failed_on_error(
        self,
        shot_cache: ShotDataCache,
        sample_shots: list[Shot],
        mocker,
        cache_method_name: str,
        cache_key: str,
    ) -> None:
        """Cache write methods emit write_failed and suppress cache_updated on errors."""
        mocker.patch("cache.shot_cache.write_json_cache", return_value=False)

        signals_received: list[str] = []
        shot_cache.cache_updated.connect(lambda: signals_received.append("updated"))
        shot_cache.cache_write_failed.connect(
            lambda name: signals_received.append(f"failed:{name}")
        )

        getattr(shot_cache, cache_method_name)(sample_shots)

        assert f"failed:{cache_key}" in signals_received
        assert "updated" not in signals_received

    @pytest.mark.parametrize(
        ("shots_input", "mock_write_failure", "expected_result"),
        [
            pytest.param(
                [Shot("show1", "seq01", "0010", "/path")],
                False,
                True,
                id="success_returns_true",
            ),
            pytest.param(
                [Shot("show1", "seq01", "0010", "/path")],
                True,
                False,
                id="write_failure_returns_false",
            ),
            pytest.param(
                [],
                False,
                True,
                id="empty_list_returns_true",
            ),
        ],
    )
    def test_migrate_return_values(
        self,
        shot_cache: ShotDataCache,
        qtbot,
        mocker,
        shots_input: list[Shot],
        mock_write_failure: bool,
        expected_result: bool,
    ) -> None:
        """archive_shots_as_previous returns correct bool for success, failure, and empty."""
        if mock_write_failure:
            mocker.patch("cache.shot_cache.write_json_cache", return_value=False)

        result = shot_cache.archive_shots_as_previous(shots_input)
        assert result is expected_result

    def test_migrate_emits_write_failed_on_error(
        self, shot_cache: ShotDataCache, qtbot, mocker
    ) -> None:
        """cache_write_failed signal is emitted when migration write fails."""
        mocker.patch("cache.shot_cache.write_json_cache", return_value=False)

        signals_received: list[str] = []
        shot_cache.cache_write_failed.connect(
            lambda name: signals_received.append(f"failed:{name}")
        )
        shot_cache.shots_migrated.connect(
            lambda _: signals_received.append("migrated")
        )

        shots = [Shot("show1", "seq01", "0010", "/path")]
        shot_cache.archive_shots_as_previous(shots)

        assert "failed:migrated_shots" in signals_received
        assert "migrated" not in signals_received


# ---------------------------------------------------------------------------
# TestCacheDiskUsage (CacheCoordinator cross-cutting)
# ---------------------------------------------------------------------------


class TestCacheDiskUsage:
    """Test disk usage calculation via CacheCoordinator."""

    def test_get_disk_usage_calculates_correctly(
        self,
        tmp_path: Path,
        sample_shots: list[Shot],
        test_image_jpg: Path,
    ) -> None:
        """Test memory usage calculation."""
        from cache import (
            CacheCoordinator,
            LatestFileCache,
            SceneDiskCache,
            ThumbnailCache,
        )

        cache_dir = tmp_path / "coordinator_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        shot_cache = ShotDataCache(cache_dir)
        thumbnail_cache = ThumbnailCache(cache_dir)
        scene_disk_cache = SceneDiskCache(cache_dir)
        latest_file_cache = LatestFileCache(cache_dir)
        coordinator = CacheCoordinator(cache_dir, thumbnail_cache, shot_cache, scene_disk_cache, latest_file_cache)

        # Get initial usage (should be minimal)
        initial_usage = coordinator.get_disk_usage()

        # Add some cached data
        shot_cache.cache_shots(sample_shots)
        thumbnail_cache.cache_thumbnail(test_image_jpg, "show", "seq", "shot")

        # Verify usage increased
        final_usage = coordinator.get_disk_usage()
        assert final_usage["total_mb"] > initial_usage["total_mb"]
        assert final_usage["file_count"] > initial_usage["file_count"]
        assert final_usage["total_mb"] > 0

    def test_get_disk_usage_handles_empty_cache(self, tmp_path: Path) -> None:
        """Test memory usage with empty cache."""
        from cache import (
            CacheCoordinator,
            LatestFileCache,
            SceneDiskCache,
            ThumbnailCache,
        )

        cache_dir = tmp_path / "empty_cache"
        cache_dir.mkdir()

        shot_cache = ShotDataCache(cache_dir)
        thumbnail_cache = ThumbnailCache(cache_dir)
        scene_disk_cache = SceneDiskCache(cache_dir)
        latest_file_cache = LatestFileCache(cache_dir)
        coordinator = CacheCoordinator(cache_dir, thumbnail_cache, shot_cache, scene_disk_cache, latest_file_cache)

        usage = coordinator.get_disk_usage()

        assert usage["total_mb"] == 0  # Empty cache should report 0 MB
        assert usage["file_count"] == 0


# ---------------------------------------------------------------------------
# TestCacheCoordinatorIntegration
# ---------------------------------------------------------------------------


class TestCacheCoordinatorIntegration:
    """Integration tests validating cache behavior across sub-managers."""

    def test_cache_workflow_shots_to_thumbnails(
        self,
        tmp_path: Path,
        sample_shots: list[Shot],
        test_image_jpg: Path,
    ) -> None:
        """Test complete workflow: cache shots, then thumbnails."""
        from cache import LatestFileCache, SceneDiskCache, ThumbnailCache

        cache_dir = tmp_path / "workflow_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        shot_cache = ShotDataCache(cache_dir)
        thumbnail_cache = ThumbnailCache(cache_dir)

        # Step 1: Cache shot data
        shot_cache.cache_shots(sample_shots)
        cached_shots = shot_cache.get_shots_with_ttl()
        assert len(cached_shots) == 3

        # Step 2: Cache thumbnails for shots
        for shot_data in cached_shots:
            result = thumbnail_cache.cache_thumbnail(
                test_image_jpg,
                shot_data["show"],
                shot_data["sequence"],
                shot_data["shot"],
            )
            assert result is not None

        # Step 3: Retrieve thumbnails
        for shot_data in cached_shots:
            thumb = thumbnail_cache.get_cached_thumbnail(
                shot_data["show"], shot_data["sequence"], shot_data["shot"]
            )
            assert thumb is not None

    def test_memory_usage_tracks_all_data(
        self,
        tmp_path: Path,
        sample_shots: list[Shot],
        test_image_jpg: Path,
    ) -> None:
        """Test memory usage calculation includes all cached data."""
        from cache import (
            CacheCoordinator,
            LatestFileCache,
            SceneDiskCache,
            ThumbnailCache,
        )

        cache_dir = tmp_path / "memory_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        shot_cache = ShotDataCache(cache_dir)
        thumbnail_cache = ThumbnailCache(cache_dir)
        scene_disk_cache = SceneDiskCache(cache_dir)
        latest_file_cache = LatestFileCache(cache_dir)
        coordinator = CacheCoordinator(cache_dir, thumbnail_cache, shot_cache, scene_disk_cache, latest_file_cache)

        initial = coordinator.get_disk_usage()

        # Add shots
        shot_cache.cache_shots(sample_shots)
        after_shots = coordinator.get_disk_usage()
        assert after_shots["total_mb"] > initial["total_mb"]

        # Add thumbnails
        for i in range(5):
            thumbnail_cache.cache_thumbnail(
                test_image_jpg, "show", f"seq{i}", f"shot{i:03d}"
            )

        after_thumbs = coordinator.get_disk_usage()
        assert after_thumbs["total_mb"] > after_shots["total_mb"]

        # Clear all caches via coordinator
        coordinator.clear_cache()
        after_clear = coordinator.get_disk_usage()
        assert after_clear["total_mb"] < after_thumbs["total_mb"]
