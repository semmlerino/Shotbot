"""Tests for LatestFileCache — tri-state latest file cache with TTL.

Covers:
- Miss on no entry (cache file absent)
- Miss on expired entry
- Not-found within TTL (confirmed no file exists)
- Hit with existing file within TTL
- Miss when cached file has been deleted
"""

from __future__ import annotations

# Standard library imports
import json
from datetime import UTC, datetime
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from cache.latest_file_cache import LatestFileCache


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def latest_file_cache(tmp_path: Path) -> LatestFileCache:
    """Create LatestFileCache with temporary directory."""
    cache_dir = tmp_path / "test_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return LatestFileCache(cache_dir)


# ---------------------------------------------------------------------------
# TestLatestFileCacheResult
# ---------------------------------------------------------------------------


class TestLatestFileCacheResult:
    """Tests for tri-state latest file cache lookup."""

    def test_miss_on_no_entry(self, latest_file_cache: LatestFileCache) -> None:
        """No cache file → miss."""
        result = latest_file_cache.get_latest_file_cache_result("/workspace", "threede")
        assert result.status == "miss"
        assert result.path is None

    def test_miss_on_expired(self, latest_file_cache: LatestFileCache) -> None:
        """Expired entry → miss."""
        # Cache a file, then expire it
        test_file = latest_file_cache.latest_files_cache_file.parent / "test.3de"
        test_file.touch()
        latest_file_cache.cache_latest_file("/workspace", "threede", test_file)

        # Manually expire by writing old timestamp
        cache_data = json.loads(latest_file_cache.latest_files_cache_file.read_text())
        cache_data["/workspace:threede"]["cached_at"] = 0.0  # epoch = very old
        latest_file_cache.latest_files_cache_file.write_text(json.dumps(cache_data))

        result = latest_file_cache.get_latest_file_cache_result("/workspace", "threede")
        assert result.status == "miss"

    def test_not_found_within_ttl(self, latest_file_cache: LatestFileCache) -> None:
        """Cached None within TTL → not_found."""
        latest_file_cache.cache_latest_file("/workspace", "threede", None)
        result = latest_file_cache.get_latest_file_cache_result("/workspace", "threede")
        assert result.status == "not_found"
        assert result.path is None

    def test_hit_with_existing_file(self, latest_file_cache: LatestFileCache) -> None:
        """Cached path within TTL, file exists → hit."""
        test_file = latest_file_cache.latest_files_cache_file.parent / "test.3de"
        test_file.touch()
        latest_file_cache.cache_latest_file("/workspace", "threede", test_file)

        result = latest_file_cache.get_latest_file_cache_result("/workspace", "threede")
        assert result.status == "hit"
        assert result.path == test_file

    def test_miss_when_file_deleted(self, latest_file_cache: LatestFileCache) -> None:
        """Cached path within TTL, but file deleted → miss."""
        test_file = latest_file_cache.latest_files_cache_file.parent / "test.3de"
        test_file.touch()
        latest_file_cache.cache_latest_file("/workspace", "threede", test_file)
        test_file.unlink()  # Delete the file

        result = latest_file_cache.get_latest_file_cache_result("/workspace", "threede")
        assert result.status == "miss"


# ---------------------------------------------------------------------------
# TestNegativeCacheTTL
# ---------------------------------------------------------------------------


class TestNegativeCacheTTL:
    """Tests for shorter TTL on negative (None) cache entries."""

    def test_negative_result_expires_after_30s(
        self, latest_file_cache: LatestFileCache
    ) -> None:
        """Negative result should expire after LATEST_FILES_NEGATIVE_TTL_SECONDS."""
        latest_file_cache.cache_latest_file("/workspace", "threede", None)

        # Within 30s — should still be "not_found"
        result1 = latest_file_cache.get_latest_file_cache_result(
            "/workspace", "threede"
        )
        assert result1.status == "not_found"

        # Manually set cached_at to 31 seconds ago
        cache_data = json.loads(
            latest_file_cache.latest_files_cache_file.read_text()
        )
        cache_data["/workspace:threede"]["cached_at"] = (
            datetime.now(tz=UTC).timestamp() - 31
        )
        latest_file_cache.latest_files_cache_file.write_text(json.dumps(cache_data))

        # After 30s — should be "miss" (expired)
        result2 = latest_file_cache.get_latest_file_cache_result(
            "/workspace", "threede"
        )
        assert result2.status == "miss"

    def test_positive_result_uses_full_ttl(
        self, latest_file_cache: LatestFileCache
    ) -> None:
        """Positive result should still use the full 5-minute TTL."""
        test_file = latest_file_cache.latest_files_cache_file.parent / "test.3de"
        test_file.touch()
        latest_file_cache.cache_latest_file("/workspace", "threede", test_file)

        # Set cached_at to 60 seconds ago (well past 30s negative TTL, but within 5min)
        cache_data = json.loads(
            latest_file_cache.latest_files_cache_file.read_text()
        )
        cache_data["/workspace:threede"]["cached_at"] = (
            datetime.now(tz=UTC).timestamp() - 60
        )
        latest_file_cache.latest_files_cache_file.write_text(json.dumps(cache_data))

        # Should still be a hit (60s < 300s full TTL)
        result = latest_file_cache.get_latest_file_cache_result(
            "/workspace", "threede"
        )
        assert result.status == "hit"
        assert result.path == test_file
