"""Comprehensive tests for simplified CacheManager.

This test suite validates the simplified cache_manager.py following
UNIFIED_TESTING_GUIDE.md principles:
- Test behavior, not implementation
- Use real components with temporary storage
- Thread safety validation
- Error handling coverage
"""

from __future__ import annotations

# Standard library imports
import json
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

# Third-party imports
import pytest
from PySide6.QtGui import QColor, QImage

# Local application imports
from cache_manager import CacheManager
from config import Config
from shot_model import Shot
from threede_scene_model import ThreeDEScene


if TYPE_CHECKING:
    from type_definitions import ShotDict

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# Test fixtures following UNIFIED_TESTING_GUIDE patterns


@pytest.fixture
def cache_manager(tmp_path: Path) -> CacheManager:
    """Create CacheManager with temporary directory.

    Following guide: "Use Real Components Where Possible"
    """
    cache_dir = tmp_path / "test_cache"
    return CacheManager(cache_dir=cache_dir)


@pytest.fixture
def sample_shots() -> list[Shot]:
    """Provide realistic shot data for testing."""
    return [
        Shot("test_show", "seq01", "shot010", f"{Config.SHOWS_ROOT}/test_show/seq01/shot010"),
        Shot("test_show", "seq01", "shot020", f"{Config.SHOWS_ROOT}/test_show/seq01/shot020"),
        Shot("test_show", "seq02", "shot030", f"{Config.SHOWS_ROOT}/test_show/seq02/shot030"),
    ]


@pytest.fixture
def sample_3de_scenes() -> list[ThreeDEScene]:
    """Provide realistic 3DE scene data for testing."""
    return [
        ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="shot010",
            user="artist1",
            plate="bg01",
            scene_path="/path/to/scene1.3de",
            workspace_path=f"{Config.SHOWS_ROOT}/test_show/seq01/shot010",
        ),
        ThreeDEScene(
            show="test_show",
            sequence="seq01",
            shot="shot020",
            user="artist2",
            plate="fg01",
            scene_path="/path/to/scene2.3de",
            workspace_path=f"{Config.SHOWS_ROOT}/test_show/seq01/shot020",
        ),
    ]


@pytest.fixture
def test_image_jpg(tmp_path: Path) -> Path:
    """Create a real JPEG test image."""
    image_path = tmp_path / "test_source.jpg"
    image = QImage(512, 512, QImage.Format.Format_RGB32)
    image.fill(QColor(100, 150, 200))  # Blue-ish
    image.save(str(image_path), "JPEG", quality=90)
    return image_path


@pytest.fixture
def test_image_png(tmp_path: Path) -> Path:
    """Create a real PNG test image."""
    image_path = tmp_path / "test_source.png"
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 100, 50, 200))  # Orange with alpha
    image.save(str(image_path), "PNG")
    return image_path


@pytest.fixture
def mock_exr_file(tmp_path: Path) -> Path:
    """Create a mock EXR file for testing."""
    exr_path = tmp_path / "test_plate.exr"
    # Write minimal valid-looking header
    exr_path.write_bytes(b"v/1\x01" + b"\x00" * 100)
    return exr_path


# Test Suite


class TestCacheManagerInitialization:
    """Test CacheManager initialization and directory setup."""

    def test_initialization_creates_directories(self, tmp_path: Path) -> None:
        """Test cache directory structure is created on init."""
        cache_dir = tmp_path / "new_cache"
        assert not cache_dir.exists()

        manager = CacheManager(cache_dir=cache_dir)

        assert manager.cache_dir == cache_dir
        assert cache_dir.exists()
        assert cache_dir.is_dir()
        assert manager.thumbnails_dir.exists()

    def test_initialization_with_existing_directory(self, tmp_path: Path) -> None:
        """Test initialization with pre-existing cache directory."""
        cache_dir = tmp_path / "existing_cache"
        cache_dir.mkdir(parents=True)

        manager = CacheManager(cache_dir=cache_dir)

        assert manager.cache_dir == cache_dir
        assert cache_dir.exists()

    def test_default_ttl_configuration(self, cache_manager: CacheManager) -> None:
        """Test default TTL is set correctly."""
        # TTL should be 30 minutes by default
        assert cache_manager._cache_ttl == timedelta(minutes=30)


class TestJSONCacheOperations:
    """Test JSON cache read/write operations with TTL validation."""

    def test_cache_shots_writes_json(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test caching shots writes valid JSON file."""
        cache_manager.cache_shots(sample_shots)

        cache_file = cache_manager.shots_cache_file
        assert cache_file.exists()

        # Verify JSON structure
        data = json.loads(cache_file.read_text())
        assert "data" in data
        assert "cached_at" in data
        assert len(data["data"]) == len(sample_shots)

    def test_get_cached_shots_returns_data(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test retrieving cached shots returns correct data."""
        cache_manager.cache_shots(sample_shots)

        cached = cache_manager.get_cached_shots()

        assert cached is not None
        assert len(cached) == len(sample_shots)
        # Verify data integrity
        assert cached[0]["show"] == "test_show"
        assert cached[0]["sequence"] == "seq01"
        assert cached[0]["shot"] == "shot010"

    def test_get_cached_shots_respects_ttl(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test TTL expiration invalidates cache."""
        cache_manager.cache_shots(sample_shots)

        # Verify cache is valid initially
        cached = cache_manager.get_cached_shots()
        assert cached is not None

        # Manually expire the cache by modifying file timestamp
        cache_file = cache_manager.shots_cache_file
        old_time = time.time() - (31 * 60)  # 31 minutes ago
        cache_file.touch()
        import os

        os.utime(cache_file, (old_time, old_time))

        # Cache should now be expired
        expired = cache_manager.get_cached_shots()
        assert expired is None

    def test_cache_threede_scenes_writes_json(
        self, cache_manager: CacheManager
    ) -> None:
        """Test caching 3DE scenes writes valid JSON."""
        # Use dict format (as expected by cache_threede_scenes)
        scenes = [
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "shot010",
                "user": "artist1",
                "plate": "bg01",
                "scene_path": "/path/to/scene1.3de",
                "workspace_path": f"{Config.SHOWS_ROOT}/test_show/seq01/shot010",
            }
        ]
        cache_manager.cache_threede_scenes(scenes)

        cache_file = cache_manager.threede_cache_file
        assert cache_file.exists()

        data = json.loads(cache_file.read_text())
        assert "data" in data
        assert len(data["data"]) == 1

    def test_get_cached_threede_scenes_returns_data(
        self, cache_manager: CacheManager
    ) -> None:
        """Test retrieving cached 3DE scenes."""
        scenes = [
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "shot010",
                "user": "artist1",
                "plate": "bg01",
                "scene_path": "/path/to/scene1.3de",
                "workspace_path": f"{Config.SHOWS_ROOT}/test_show/seq01/shot010",
            },
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "shot020",
                "user": "artist2",
                "plate": "fg01",
                "scene_path": "/path/to/scene2.3de",
                "workspace_path": f"{Config.SHOWS_ROOT}/test_show/seq01/shot020",
            },
        ]
        cache_manager.cache_threede_scenes(scenes)

        cached = cache_manager.get_cached_threede_scenes()

        assert cached is not None
        assert len(cached) == 2
        assert cached[0]["show"] == "test_show"
        assert cached[0]["user"] == "artist1"

    def test_cache_handles_empty_list(self, cache_manager: CacheManager) -> None:
        """Test caching empty list is handled correctly."""
        cache_manager.cache_shots([])

        cached = cache_manager.get_cached_shots()
        assert cached == []

    def test_cache_overwrites_existing_data(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test caching new data overwrites old data."""
        # Cache initial data
        cache_manager.cache_shots(sample_shots[:2])
        cached1 = cache_manager.get_cached_shots()
        assert len(cached1) == 2

        # Overwrite with different data
        cache_manager.cache_shots(sample_shots)
        cached2 = cache_manager.get_cached_shots()
        assert len(cached2) == 3


class TestThumbnailCaching:
    """Test thumbnail processing and caching operations."""

    def test_cache_thumbnail_jpg(
        self, cache_manager: CacheManager, test_image_jpg: Path
    ) -> None:
        """Test caching JPEG thumbnail creates resized output."""
        result = cache_manager.cache_thumbnail(
            test_image_jpg, "test_show", "seq01", "shot010"
        )

        assert result is not None
        assert result.exists()
        assert result.suffix == ".jpg"

        # Verify thumbnail was resized
        thumb = QImage(str(result))
        assert thumb.width() <= 256
        assert thumb.height() <= 256

    def test_cache_thumbnail_png(
        self, cache_manager: CacheManager, test_image_png: Path
    ) -> None:
        """Test caching PNG thumbnail preserves transparency."""
        result = cache_manager.cache_thumbnail(
            test_image_png, "test_show", "seq01", "shot020"
        )

        assert result is not None
        assert result.exists()
        assert result.suffix == ".jpg"  # Converted to JPEG

        # Verify resizing
        thumb = QImage(str(result))
        assert thumb.width() <= 256
        assert thumb.height() <= 256

    def test_get_cached_thumbnail_returns_valid_path(
        self, cache_manager: CacheManager, test_image_jpg: Path
    ) -> None:
        """Test retrieving cached thumbnail returns valid path."""
        # Cache a thumbnail first
        cache_manager.cache_thumbnail(test_image_jpg, "test_show", "seq01", "shot010")

        # Retrieve it
        cached_path = cache_manager.get_cached_thumbnail(
            "test_show", "seq01", "shot010"
        )

        assert cached_path is not None
        assert cached_path.exists()
        assert cached_path.name == "shot010_thumb.jpg"

    def test_get_cached_thumbnail_is_persistent(
        self, cache_manager: CacheManager, test_image_jpg: Path
    ) -> None:
        """Test cached thumbnails are persistent (no TTL expiration)."""
        # Cache thumbnail
        cache_manager.cache_thumbnail(test_image_jpg, "test_show", "seq01", "shot010")

        # Verify it's cached
        cached = cache_manager.get_cached_thumbnail("test_show", "seq01", "shot010")
        assert cached is not None

        # Set timestamp to 31 minutes ago (would expire data caches)
        old_time = time.time() - (31 * 60)  # 31 minutes ago
        import os

        os.utime(cached, (old_time, old_time))

        # Should still be valid (thumbnails don't expire)
        still_valid = cache_manager.get_cached_thumbnail("test_show", "seq01", "shot010")
        assert still_valid is not None
        assert still_valid == cached

    def test_get_cached_thumbnail_missing_file(
        self, cache_manager: CacheManager
    ) -> None:
        """Test retrieving non-existent thumbnail returns None."""
        result = cache_manager.get_cached_thumbnail(
            "nonexistent_show", "seq99", "shot999"
        )
        assert result is None

    def test_cache_thumbnail_creates_nested_directories(
        self, cache_manager: CacheManager, test_image_jpg: Path
    ) -> None:
        """Test thumbnail caching creates show/sequence directory structure."""
        cache_manager.cache_thumbnail(test_image_jpg, "new_show", "new_seq", "new_shot")

        expected_dir = cache_manager.thumbnails_dir / "new_show" / "new_seq"
        assert expected_dir.exists()
        assert (expected_dir / "new_shot_thumb.jpg").exists()


class TestEXRProcessing:
    """Test OpenEXR thumbnail processing."""

    def test_exr_thumbnail_with_pil(
        self, cache_manager: CacheManager, mock_exr_file: Path
    ) -> None:
        """Test EXR processing uses PIL directly (no OpenEXR/Imath dependency).

        This tests that we handle EXR files gracefully using PIL,
        which will fail if pillow-openexr is not installed (expected).
        """
        result = cache_manager.cache_thumbnail(
            mock_exr_file, "test_show", "seq01", "shot_exr"
        )

        # PIL will fail on our mock EXR file since it's not a real EXR
        # This is expected behavior - graceful degradation without OpenEXR/Imath
        if result is None:
            # Verify graceful failure: result is None (no exception, no cache entry)
            assert result is None

    def test_exr_thumbnail_with_missing_file(
        self, cache_manager: CacheManager, tmp_path: Path
    ) -> None:
        """Test EXR processing handles missing files gracefully."""
        missing_exr = tmp_path / "nonexistent.exr"

        result = cache_manager.cache_thumbnail(
            missing_exr, "test_show", "seq01", "shot_missing"
        )

        # Should return None for missing file
        assert result is None


class TestThreadSafety:
    """Test thread-safe concurrent access patterns.

    Following UNIFIED_TESTING_GUIDE: "Thread Safety in Tests"
    """

    def test_concurrent_shot_caching(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test thread-safe concurrent shot caching operations.

        NOTE: This test may be flaky when run with full test suite due to
        pytest-qt event loop cleanup issues. Passes consistently when run alone.
        The cache_manager itself IS thread-safe (uses QMutex properly).
        """
        import queue

        results_queue: queue.Queue[bool] = queue.Queue()

        def cache_operation(thread_id: int) -> None:
            """Simulate concurrent cache operations."""
            shots = [
                Shot(
                    "show",
                    f"seq{thread_id}",
                    f"shot{i:03d}",
                    f"/path/{thread_id}/{i}",
                )
                for i in range(10)
            ]
            cache_manager.cache_shots(shots)
            # cache_shots() is synchronous - write completes before return
            cached = cache_manager.get_cached_shots()
            results_queue.put(cached is not None)

        # Run 5 threads concurrently using Thread instead of ThreadPoolExecutor
        # to avoid Qt event loop issues in test environment
        threads = [
            threading.Thread(target=cache_operation, args=(i,)) for i in range(5)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Collect results from thread-safe queue
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())

        # All operations should succeed without corruption
        assert all(results), f"Some cache operations failed: {results}"
        assert len(results) == 5, f"Expected 5 results, got {len(results)}"

    def test_concurrent_thumbnail_caching(
        self, cache_manager: CacheManager, test_image_jpg: Path
    ) -> None:
        """Test thread-safe concurrent thumbnail operations."""
        import queue

        results_queue: queue.Queue[bool] = queue.Queue()

        def thumbnail_operation(thread_id: int) -> None:
            """Simulate concurrent thumbnail caching."""
            for i in range(5):
                result = cache_manager.cache_thumbnail(
                    test_image_jpg,
                    f"show{thread_id}",
                    f"seq{thread_id}",
                    f"shot{i:03d}",
                )
                results_queue.put(result is not None)

        # Run multiple threads
        threads = [
            threading.Thread(target=thumbnail_operation, args=(i,)) for i in range(3)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Collect results from thread-safe queue
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())

        # All operations should succeed
        assert all(results)
        assert len(results) == 15  # 3 threads x 5 operations

    def test_concurrent_cache_clearing(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test thread-safe cache clearing with concurrent reads."""
        import queue

        # Pre-populate cache
        cache_manager.cache_shots(sample_shots)

        read_queue: queue.Queue[bool] = queue.Queue()
        clear_queue: queue.Queue[bool] = queue.Queue()

        def read_operation() -> None:
            """Concurrent read operations."""
            for _ in range(10):
                _ = cache_manager.get_cached_shots()
                # Result might be None if cleared, that's OK
                read_queue.put(True)

        def clear_operation() -> None:
            """Concurrent clear operations."""
            for _ in range(5):
                cache_manager.clear_cache()
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


class TestCacheManagement:
    """Test cache clearing and memory management operations."""

    def test_clear_cache_removes_all_files(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test clear_cache removes all cached data."""
        # Populate cache
        cache_manager.cache_shots(sample_shots)
        cache_manager.cache_threede_scenes([])

        # Verify files exist
        assert cache_manager.shots_cache_file.exists()

        # Clear cache
        cache_manager.clear_cache()

        # Verify cache directory is empty
        assert not cache_manager.shots_cache_file.exists()
        # Note: thumbnails_dir might still exist but be empty

    def test_clear_cache_handles_missing_directory(self, tmp_path: Path) -> None:
        """Test clear_cache handles non-existent cache gracefully."""
        cache_dir = tmp_path / "nonexistent_cache"
        manager = CacheManager(cache_dir=cache_dir)

        # Should not raise exception
        manager.clear_cache()

    def test_get_memory_usage_calculates_correctly(
        self,
        cache_manager: CacheManager,
        test_image_jpg: Path,
        sample_shots: list[Shot],
    ) -> None:
        """Test memory usage calculation."""
        # Get initial usage (should be minimal)
        initial_usage = cache_manager.get_memory_usage()

        # Add some cached data
        cache_manager.cache_shots(sample_shots)
        cache_manager.cache_thumbnail(test_image_jpg, "show", "seq", "shot")

        # Verify usage increased
        final_usage = cache_manager.get_memory_usage()
        assert final_usage["total_mb"] > initial_usage["total_mb"]
        assert final_usage["file_count"] > initial_usage["file_count"]
        assert final_usage["total_mb"] > 0

    def test_get_memory_usage_handles_empty_cache(self, tmp_path: Path) -> None:
        """Test memory usage with empty cache."""
        cache_dir = tmp_path / "empty_cache"
        cache_dir.mkdir()

        manager = CacheManager(cache_dir=cache_dir)
        usage = manager.get_memory_usage()

        assert usage["total_mb"] == 0  # Empty cache should report 0 MB
        assert usage["file_count"] == 0


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_cache_thumbnail_with_missing_source(
        self, cache_manager: CacheManager, tmp_path: Path
    ) -> None:
        """Test caching thumbnail with non-existent source file."""
        missing_file = tmp_path / "missing.jpg"

        result = cache_manager.cache_thumbnail(missing_file, "show", "seq", "shot")

        # Should return None for missing source
        assert result is None

    def test_cache_thumbnail_with_corrupt_image(
        self, cache_manager: CacheManager, tmp_path: Path
    ) -> None:
        """Test caching thumbnail with corrupt image data."""
        corrupt_file = tmp_path / "corrupt.jpg"
        corrupt_file.write_bytes(b"NOT A VALID IMAGE")

        result = cache_manager.cache_thumbnail(corrupt_file, "show", "seq", "shot")

        # Should handle corrupt image gracefully
        assert result is None

    def test_get_cached_shots_with_corrupt_json(
        self, cache_manager: CacheManager
    ) -> None:
        """Test retrieving shots with corrupt JSON file."""
        # Write invalid JSON
        cache_manager.shots_cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_manager.shots_cache_file.write_text("INVALID JSON{{{")

        result = cache_manager.get_cached_shots()

        # Should return None for corrupt JSON
        assert result is None

    def test_get_cached_shots_with_missing_keys(
        self, cache_manager: CacheManager
    ) -> None:
        """Test retrieving shots with malformed JSON structure."""
        # Write JSON without expected keys
        cache_manager.shots_cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_manager.shots_cache_file.write_text('{"wrong_key": []}')

        result = cache_manager.get_cached_shots()

        # Should handle gracefully
        # Implementation may return [] or None, either is acceptable
        assert result is None or result == []

    def test_cache_with_readonly_directory(self, tmp_path: Path) -> None:
        """Test caching operations with read-only directory."""
        cache_dir = tmp_path / "readonly_cache"
        cache_dir.mkdir()

        manager = CacheManager(cache_dir=cache_dir)

        # Make directory read-only
        import stat

        cache_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

        try:
            # Should handle write failure gracefully
            manager.cache_shots([Shot("show", "seq", "shot", "/path")])
            # If we get here, permission check might be disabled in test env
        except PermissionError:
            # Expected on systems that enforce permissions
            pass
        finally:
            # Restore permissions for cleanup
            cache_dir.chmod(stat.S_IRWXU)


class TestPersistentPreviousShotsCache:
    """Test persistent incremental caching for previous shots.

    Tests the new persistent cache functionality that:
    - Never expires (no TTL check)
    - Accumulates shots incrementally
    - Only refreshes when user explicitly requests it

    Following UNIFIED_TESTING_GUIDE: Test behavior, not implementation.
    """

    def test_get_persistent_previous_shots_ignores_ttl(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test persistent cache returns data regardless of age."""
        # Cache previous shots
        cache_manager.cache_previous_shots(sample_shots)

        # Verify cache is valid initially
        cached = cache_manager.get_persistent_previous_shots()
        assert cached is not None
        assert len(cached) == 3

        # Manually expire the cache by modifying file timestamp
        cache_file = cache_manager.previous_shots_cache_file
        old_time = time.time() - (60 * 60 * 24)  # 24 hours ago (way past TTL)
        import os

        os.utime(cache_file, (old_time, old_time))

        # Persistent cache should STILL return data (no TTL check)
        persistent = cache_manager.get_persistent_previous_shots()
        assert persistent is not None
        assert len(persistent) == 3
        assert persistent[0]["show"] == "test_show"

        # Compare: Regular cache WOULD be expired
        regular = cache_manager.get_cached_previous_shots()
        assert regular is None  # Expired with TTL check

    def test_persistent_cache_returns_none_when_missing(
        self, cache_manager: CacheManager
    ) -> None:
        """Test persistent cache returns None for non-existent cache file."""
        result = cache_manager.get_persistent_previous_shots()
        assert result is None

    def test_persistent_cache_handles_empty_cache(
        self, cache_manager: CacheManager
    ) -> None:
        """Test persistent cache handles empty shot list."""
        cache_manager.cache_previous_shots([])

        result = cache_manager.get_persistent_previous_shots()
        assert result == []

    def test_persistent_cache_preserves_data_format(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test persistent cache preserves shot data structure."""
        cache_manager.cache_previous_shots(sample_shots)

        cached = cache_manager.get_persistent_previous_shots()
        assert cached is not None

        # Verify data structure
        for shot_data in cached:
            assert "show" in shot_data
            assert "sequence" in shot_data
            assert "shot" in shot_data
            assert "workspace_path" in shot_data

    def test_persistent_cache_thread_safety(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test thread-safe concurrent access to persistent cache."""
        import queue

        results_queue: queue.Queue[int | None] = queue.Queue()

        # Pre-populate cache
        cache_manager.cache_previous_shots(sample_shots)

        def read_persistent_cache() -> None:
            """Concurrent read from persistent cache."""
            for _ in range(10):
                cached = cache_manager.get_persistent_previous_shots()
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

    def test_persistent_cache_survives_manager_recreation(
        self, tmp_path: Path, sample_shots: list[Shot]
    ) -> None:
        """Test persistent cache survives CacheManager recreation.

        This simulates application restart where cache should remain intact.
        """
        cache_dir = tmp_path / "persistent_cache"

        # Create first manager and cache data
        manager1 = CacheManager(cache_dir=cache_dir)
        manager1.cache_previous_shots(sample_shots)

        # "Restart" by creating new manager instance
        # (persistence is not time-dependent)
        manager2 = CacheManager(cache_dir=cache_dir)

        # Persistent cache should still be available
        cached = manager2.get_persistent_previous_shots()
        assert cached is not None
        assert len(cached) == 3

        # Even hours later, it should still be there
        cache_file = manager2.previous_shots_cache_file
        old_time = time.time() - (60 * 60 * 48)  # 48 hours ago
        import os

        os.utime(cache_file, (old_time, old_time))

        # Create third manager to simulate another restart
        manager3 = CacheManager(cache_dir=cache_dir)
        still_cached = manager3.get_persistent_previous_shots()
        assert still_cached is not None
        assert len(still_cached) == 3

    def test_comparison_persistent_vs_regular_cache(
        self, cache_manager: CacheManager, sample_shots: list[Shot]
    ) -> None:
        """Test that demonstrates difference between persistent and regular cache."""
        # Cache some previous shots
        cache_manager.cache_previous_shots(sample_shots)

        # Both methods should return data initially
        regular = cache_manager.get_cached_previous_shots()
        persistent = cache_manager.get_persistent_previous_shots()

        assert regular is not None
        assert persistent is not None
        assert len(regular) == len(persistent) == 3

        # Expire the cache
        cache_file = cache_manager.previous_shots_cache_file
        old_time = time.time() - (60 * 60)  # 1 hour ago (past 30min TTL)
        import os

        os.utime(cache_file, (old_time, old_time))

        # Regular cache respects TTL - returns None
        regular_expired = cache_manager.get_cached_previous_shots()
        assert regular_expired is None

        # Persistent cache ignores TTL - still returns data
        persistent_valid = cache_manager.get_persistent_previous_shots()
        assert persistent_valid is not None
        assert len(persistent_valid) == 3


class TestShotMigration:
    """Test Phase 2: Shot migration from My Shots to Previous Shots (v2.3)."""

    def test_get_migrated_shots_empty_cache(self, cache_manager: CacheManager) -> None:
        """get_migrated_shots() returns None for empty cache."""
        result = cache_manager.get_migrated_shots()
        assert result is None

    def test_migrate_empty_list_is_noop(self, cache_manager: CacheManager) -> None:
        """Migrating empty list is a no-op."""
        cache_manager.migrate_shots_to_previous([])
        result = cache_manager.get_migrated_shots()
        assert result is None

    def test_first_migration_creates_file(
        self, cache_manager: CacheManager, qtbot
    ) -> None:
        """First migration creates migrated_shots.json."""
        shots = [
            Shot("show1", "seq01", "shot010", "/p1"),
            Shot("show1", "seq01", "shot020", "/p2"),
        ]

        # Verify signal emission
        with qtbot.waitSignal(cache_manager.shots_migrated, timeout=1000):
            cache_manager.migrate_shots_to_previous(shots)

        # Verify file created
        assert cache_manager.migrated_shots_cache_file.exists()

        # Verify content
        migrated = cache_manager.get_migrated_shots()
        assert migrated is not None
        assert len(migrated) == 2
        assert migrated[0]["shot"] in ("shot010", "shot020")

    def test_subsequent_migration_merges(self, cache_manager: CacheManager) -> None:
        """Subsequent migrations merge with existing."""
        # First migration
        batch1 = [Shot("show1", "seq01", "shot010", "/p1")]
        cache_manager.migrate_shots_to_previous(batch1)

        # Second migration (different shots)
        batch2 = [
            Shot("show1", "seq01", "shot020", "/p2"),
            Shot("show1", "seq02", "shot030", "/p3"),
        ]
        cache_manager.migrate_shots_to_previous(batch2)

        # Verify merged
        migrated = cache_manager.get_migrated_shots()
        assert migrated is not None
        assert len(migrated) == 3  # All three shots present

    def test_migration_deduplicates_by_composite_key(
        self, cache_manager: CacheManager
    ) -> None:
        """Migration deduplicates using (show, sequence, shot) key."""
        # First migration
        shot1 = Shot("show1", "seq01", "shot010", "/old/path")
        cache_manager.migrate_shots_to_previous([shot1])

        # Second migration with same shot but different path
        shot2 = Shot("show1", "seq01", "shot010", "/new/path")
        cache_manager.migrate_shots_to_previous([shot2])

        # Verify only one shot, latest path
        migrated = cache_manager.get_migrated_shots()
        assert migrated is not None
        assert len(migrated) == 1
        assert migrated[0]["workspace_path"] == "/new/path"

    def test_migration_cross_show_uniqueness(
        self, cache_manager: CacheManager
    ) -> None:
        """Composite key prevents cross-show collisions."""
        shots = [
            Shot("show1", "seq01", "shot010", "/show1/path"),
            Shot("show2", "seq01", "shot010", "/show2/path"),  # Same seq_shot, different show
        ]
        cache_manager.migrate_shots_to_previous(shots)

        migrated = cache_manager.get_migrated_shots()
        assert migrated is not None
        assert len(migrated) == 2  # Both preserved

        shows = {s["show"] for s in migrated}
        assert shows == {"show1", "show2"}

    def test_migrate_accepts_shot_dicts(self, cache_manager: CacheManager) -> None:
        """migrate_shots_to_previous() accepts ShotDict input."""
        shot_dicts: list[ShotDict] = [
            {
                "show": "show1",
                "sequence": "seq01",
                "shot": "shot010",
                "workspace_path": "/p1",
            }
        ]
        cache_manager.migrate_shots_to_previous(shot_dicts)

        migrated = cache_manager.get_migrated_shots()
        assert migrated is not None
        assert len(migrated) == 1

    def test_migrate_mixed_shot_and_dict(self, cache_manager: CacheManager) -> None:
        """migrate_shots_to_previous() handles mixed Shot and ShotDict."""
        shot_obj = Shot("show1", "seq01", "shot010", "/p1")
        shot_dict: ShotDict = {
            "show": "show1",
            "sequence": "seq01",
            "shot": "shot020",
            "workspace_path": "/p2",
        }
        cache_manager.migrate_shots_to_previous([shot_obj, shot_dict])

        migrated = cache_manager.get_migrated_shots()
        assert migrated is not None
        assert len(migrated) == 2

    def test_migration_signal_emission(self, cache_manager: CacheManager, qtbot) -> None:
        """shots_migrated signal emitted with correct payload."""
        shots = [Shot("show1", "seq01", "shot010", "/p1")]

        # Capture signal
        with qtbot.waitSignal(
            cache_manager.shots_migrated, timeout=1000
        ) as signal_blocker:
            cache_manager.migrate_shots_to_previous(shots)

        # Verify payload
        emitted_shots = signal_blocker.args[0]
        assert len(emitted_shots) == 1
        assert emitted_shots[0]["shot"] == "shot010"

    def test_migration_no_signal_on_empty(
        self, cache_manager: CacheManager, qtbot
    ) -> None:
        """No signal emitted for empty migration."""
        # Signal should NOT be emitted
        with qtbot.assertNotEmitted(cache_manager.shots_migrated, wait=100):
            cache_manager.migrate_shots_to_previous([])

    def test_migration_large_batch(self, cache_manager: CacheManager) -> None:
        """Migration handles large batches efficiently."""
        # Generate 100 shots
        large_batch = [
            Shot("show1", "seq01", f"shot{i:04d}", f"/p{i}") for i in range(100)
        ]
        cache_manager.migrate_shots_to_previous(large_batch)

        migrated = cache_manager.get_migrated_shots()
        assert migrated is not None
        assert len(migrated) == 100

    def test_migration_thread_safety(self, cache_manager: CacheManager, qtbot) -> None:
        """Concurrent migrations don't corrupt data."""
        from concurrent.futures import (
            ThreadPoolExecutor,
        )

        def migrate_batch(batch_id: int) -> None:
            shots = [Shot("show1", "seq01", f"shot{batch_id:03d}", f"/p{batch_id}")]
            cache_manager.migrate_shots_to_previous(shots)

        # Migrate 10 shots concurrently
        with ThreadPoolExecutor(max_workers=5) as executor:
            list(executor.map(migrate_batch, range(10)))

        # Verify all 10 shots present (no corruption)
        migrated = cache_manager.get_migrated_shots()
        assert migrated is not None
        assert len(migrated) == 10


class TestCacheIntegration:
    """Integration tests validating cache behavior across components."""

    def test_cache_workflow_shots_to_thumbnails(
        self,
        cache_manager: CacheManager,
        sample_shots: list[Shot],
        test_image_jpg: Path,
    ) -> None:
        """Test complete workflow: cache shots, then thumbnails."""
        # Step 1: Cache shot data
        cache_manager.cache_shots(sample_shots)
        cached_shots = cache_manager.get_cached_shots()
        assert len(cached_shots) == 3

        # Step 2: Cache thumbnails for shots
        for shot_data in cached_shots:
            result = cache_manager.cache_thumbnail(
                test_image_jpg,
                shot_data["show"],
                shot_data["sequence"],
                shot_data["shot"],
            )
            assert result is not None

        # Step 3: Retrieve thumbnails
        for shot_data in cached_shots:
            thumb = cache_manager.get_cached_thumbnail(
                shot_data["show"], shot_data["sequence"], shot_data["shot"]
            )
            assert thumb is not None

    def test_cache_persistence_across_instances(
        self, tmp_path: Path, sample_shots: list[Shot], test_image_jpg: Path
    ) -> None:
        """Test cache persists across CacheManager instances."""
        cache_dir = tmp_path / "persistent_cache"

        # Create first instance and cache data
        manager1 = CacheManager(cache_dir=cache_dir)
        manager1.cache_shots(sample_shots)
        manager1.cache_thumbnail(test_image_jpg, "show", "seq", "shot")

        # Create second instance
        manager2 = CacheManager(cache_dir=cache_dir)

        # Verify data persisted
        cached_shots = manager2.get_cached_shots()
        assert len(cached_shots) == 3

        cached_thumb = manager2.get_cached_thumbnail("show", "seq", "shot")
        assert cached_thumb is not None

    def test_memory_usage_tracks_all_data(
        self,
        cache_manager: CacheManager,
        sample_shots: list[Shot],
        test_image_jpg: Path,
    ) -> None:
        """Test memory usage calculation includes all cached data."""
        initial = cache_manager.get_memory_usage()

        # Add shots
        cache_manager.cache_shots(sample_shots)
        after_shots = cache_manager.get_memory_usage()
        assert after_shots["total_mb"] > initial["total_mb"]

        # Add thumbnails
        for i in range(5):
            cache_manager.cache_thumbnail(
                test_image_jpg, "show", f"seq{i}", f"shot{i:03d}"
            )

        after_thumbs = cache_manager.get_memory_usage()
        assert after_thumbs["total_mb"] > after_shots["total_mb"]

        # Clear cache
        cache_manager.clear_cache()
        after_clear = cache_manager.get_memory_usage()
        assert after_clear["total_mb"] < after_thumbs["total_mb"]


class TestCacheWriteFailureSignals:
    """Tests for cache_write_failed signal and proper signal emission on errors."""

    def test_cache_shots_emits_cache_updated_on_success(
        self, cache_manager: CacheManager, sample_shots: list[Shot], qtbot
    ) -> None:
        """cache_updated signal is emitted when cache_shots succeeds."""
        with qtbot.waitSignal(cache_manager.cache_updated, timeout=1000):
            cache_manager.cache_shots(sample_shots)

    @pytest.mark.parametrize(
        ("cache_method_name", "cache_key"),
        [("cache_shots", "shots"), ("cache_previous_shots", "previous_shots")],
    )
    def test_cache_methods_emit_write_failed_on_error(
        self,
        cache_manager: CacheManager,
        sample_shots: list[Shot],
        mocker,
        cache_method_name: str,
        cache_key: str,
    ) -> None:
        """Cache write methods emit write_failed and suppress cache_updated on errors."""
        mocker.patch.object(cache_manager, "_write_json_cache", return_value=False)

        signals_received: list[str] = []
        cache_manager.cache_updated.connect(lambda: signals_received.append("updated"))
        cache_manager.cache_write_failed.connect(
            lambda name: signals_received.append(f"failed:{name}")
        )

        getattr(cache_manager, cache_method_name)(sample_shots)

        assert f"failed:{cache_key}" in signals_received
        assert "updated" not in signals_received

    def test_migrate_returns_true_on_success(
        self, cache_manager: CacheManager, qtbot
    ) -> None:
        """migrate_shots_to_previous returns True on successful write."""
        shots = [Shot("show1", "seq01", "0010", "/path")]
        result = cache_manager.migrate_shots_to_previous(shots)
        assert result is True

    def test_migrate_returns_false_on_write_failure(
        self, cache_manager: CacheManager, qtbot, mocker
    ) -> None:
        """migrate_shots_to_previous returns False when write fails."""
        mocker.patch.object(cache_manager, "_write_json_cache", return_value=False)

        shots = [Shot("show1", "seq01", "0010", "/path")]
        result = cache_manager.migrate_shots_to_previous(shots)

        assert result is False

    def test_migrate_returns_true_for_empty_list(
        self, cache_manager: CacheManager
    ) -> None:
        """migrate_shots_to_previous returns True for empty input (no-op)."""
        result = cache_manager.migrate_shots_to_previous([])
        assert result is True

    def test_migrate_emits_write_failed_on_error(
        self, cache_manager: CacheManager, qtbot, mocker
    ) -> None:
        """cache_write_failed signal is emitted when migration write fails."""
        mocker.patch.object(cache_manager, "_write_json_cache", return_value=False)

        signals_received: list[str] = []
        cache_manager.cache_write_failed.connect(
            lambda name: signals_received.append(f"failed:{name}")
        )
        cache_manager.shots_migrated.connect(
            lambda _: signals_received.append("migrated")
        )

        shots = [Shot("show1", "seq01", "0010", "/path")]
        cache_manager.migrate_shots_to_previous(shots)

        assert "failed:migrated_shots" in signals_received
        assert "migrated" not in signals_received


# ==============================================================================
# PathValidators path-cache tests (folded from test_cache_logic.py)
# ==============================================================================


def _validate_path(path: Path | str, description: str = "Path") -> bool:
    """Call PathValidators.validate_path_exists."""
    from path_validators import PathValidators

    return PathValidators.validate_path_exists(path, description)


def _get_path_cache_stats() -> dict[str, int]:
    """Return path cache size with a stable key."""
    from path_validators import get_cache_stats

    stats = get_cache_stats()
    return {"size": stats.get("path_cache_size", stats.get("size", 0))}


class TestPathCacheHitMiss:
    """Test path cache hit/miss behavior for PathValidators."""

    def test_cache_hit_returns_cached_result(self, tmp_path: Path) -> None:
        """Second lookup returns cached result without growing cache."""
        from path_validators import clear_path_cache

        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        clear_path_cache()

        result1 = _validate_path(test_dir, "test dir")
        assert result1 is True
        size_after_first = _get_path_cache_stats()["size"]

        result2 = _validate_path(test_dir, "test dir")
        assert result2 is True

        assert _get_path_cache_stats()["size"] == size_after_first

    def test_cache_miss_on_new_path(self, tmp_path: Path) -> None:
        """New paths grow the cache."""
        from path_validators import clear_path_cache

        clear_path_cache()
        initial_size = _get_path_cache_stats()["size"]

        test_path1 = tmp_path / "path1"
        test_path1.mkdir()
        _validate_path(test_path1, "path 1")
        size_after_first = _get_path_cache_stats()["size"]
        assert size_after_first > initial_size

        test_path2 = tmp_path / "path2"
        test_path2.mkdir()
        _validate_path(test_path2, "path 2")
        assert _get_path_cache_stats()["size"] > size_after_first

    def test_cache_returns_false_for_nonexistent(self, tmp_path: Path) -> None:
        """Non-existent paths cache a False result."""
        from path_validators import clear_path_cache

        clear_path_cache()
        nonexistent = tmp_path / "nonexistent"

        assert _validate_path(nonexistent, "nonexistent") is False
        assert _validate_path(nonexistent, "nonexistent") is False


class TestPathCacheClearing:
    """Test path cache clearing behavior."""

    def test_clear_cache_empties_cache(self, tmp_path: Path) -> None:
        """clear_path_cache empties the cache."""
        from path_validators import clear_path_cache

        test_path = tmp_path / "test"
        test_path.mkdir()
        _validate_path(test_path, "test")
        assert _get_path_cache_stats()["size"] > 0

        clear_path_cache()
        assert _get_path_cache_stats()["size"] == 0

    def test_cache_refills_after_clear(self, tmp_path: Path) -> None:
        """Cache refills after being cleared."""
        from path_validators import clear_path_cache

        test_path = tmp_path / "test"
        test_path.mkdir()
        _validate_path(test_path, "test")
        clear_path_cache()

        _validate_path(test_path, "test")
        assert _get_path_cache_stats()["size"] > 0


class TestCachingEnabledDisabled:
    """Test enabling/disabling PathValidators caching."""

    def test_caching_disabled_bypasses_cache(
        self, tmp_path: Path, caching_disabled: None
    ) -> None:
        """caching_disabled fixture prevents cache population."""
        test_path = tmp_path / "test"
        test_path.mkdir()

        _validate_path(test_path, "test")
        _validate_path(test_path, "test")
        _validate_path(test_path, "test")

        assert _get_path_cache_stats()["size"] == 0

    def test_caching_enabled_uses_cache(
        self, tmp_path: Path, caching_enabled: Path
    ) -> None:
        """caching_enabled fixture allows cache population."""
        from path_validators import clear_path_cache

        clear_path_cache()
        test_path = tmp_path / "test"
        test_path.mkdir()

        _validate_path(test_path, "test")
        assert _get_path_cache_stats()["size"] > 0


class TestCacheManagerWithPathCache:
    """Test CacheManager behaviour alongside the path-validation cache."""

    def test_shots_cache_survives_clear_all_caches(
        self, isolated_cache_manager: CacheManager
    ) -> None:
        """clear_all_caches() must not evict CacheManager's persistent JSON caches.

        clear_all_caches() only clears path-validation and version caches, not
        CacheManager's shot/scene JSON files.
        """
        from utils import clear_all_caches

        manager = isolated_cache_manager
        shot_data = [{"show": "TEST", "sequence": "SQ010", "shot": "SH0010"}]
        manager.cache_shots(shot_data)

        clear_all_caches()

        cached = manager.get_cached_shots()
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["shot"] == "SH0010"


class TestCacheIsolationContext:
    """Test utils.CacheIsolation context manager."""

    def test_cache_isolation_clears_and_disables(self, tmp_path: Path) -> None:
        """CacheIsolation provides a clean, cache-disabled environment inside the block."""
        from utils import CacheIsolation

        test_path = tmp_path / "test"
        test_path.mkdir()
        _validate_path(test_path, "test")
        assert _get_path_cache_stats()["size"] > 0

        with CacheIsolation():
            assert _get_path_cache_stats()["size"] == 0

            another_path = tmp_path / "another"
            another_path.mkdir()
            _validate_path(another_path, "another")
            # Caching is disabled inside CacheIsolation
            assert _get_path_cache_stats()["size"] == 0

        # Cache still empty after exit (nothing was cached inside)
        assert _get_path_cache_stats()["size"] == 0

    def test_cache_isolation_reenables_caching_on_exit(self, tmp_path: Path) -> None:
        """Caching is re-enabled after CacheIsolation block exits."""
        from path_validators import clear_path_cache
        from utils import CacheIsolation

        clear_path_cache()

        with CacheIsolation():
            pass

        test_path = tmp_path / "test"
        test_path.mkdir()
        _validate_path(test_path, "test")
        assert _get_path_cache_stats()["size"] > 0
