"""Caching fixtures for test isolation and cache behavior testing.

This module provides fixtures for tests that need to:
- Test with caching explicitly enabled (for cache behavior tests)
- Test with caching explicitly disabled (for isolation)
- Use isolated cache directories
- Ensure clean (empty) disk cache state
- Clean thumbnail cache (for thumbnail-specific tests)

Fixtures:
    caching_enabled: Enable caching with isolated temp directory
    caching_disabled: Explicitly disable caching for a test
    isolated_cache_manager: CacheManager with isolated temp directory
    clean_disk_cache: Guaranteed empty disk cache for test
    clean_thumbnails: Clear and isolate thumbnail directory for test
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator

    from cache_manager import CacheManager

_logger = logging.getLogger(__name__)


@pytest.fixture
def caching_enabled(tmp_path: Path) -> Iterator[Path]:
    """Enable caching with isolated temp directory for cache behavior tests.

    This fixture:
    - Creates an isolated cache directory in tmp_path
    - Sets SHOTBOT_TEST_CACHE_DIR environment variable
    - Enables path caching (re-enables if disabled)
    - Clears all caches before test

    Use this for tests that verify cache hit/miss behavior, TTL expiration,
    cache persistence, etc.

    Yields:
        Path to the isolated cache directory

    Example:
        def test_cache_hit_returns_cached_result(caching_enabled):
            cache_dir = caching_enabled
            # Test cache behavior with caching enabled

    """
    from utils import clear_all_caches, enable_caching

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)

    # Save original env var if set
    original_cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")

    # Set isolated cache directory
    os.environ["SHOTBOT_TEST_CACHE_DIR"] = str(cache_dir)

    # Ensure caching is enabled and caches are clear
    clear_all_caches()
    enable_caching()

    _logger.debug("Caching enabled with isolated directory: %s", cache_dir)

    yield cache_dir

    # Cleanup: restore original state
    clear_all_caches()

    if original_cache_dir is not None:
        os.environ["SHOTBOT_TEST_CACHE_DIR"] = original_cache_dir
    else:
        os.environ.pop("SHOTBOT_TEST_CACHE_DIR", None)


@pytest.fixture
def caching_disabled() -> Iterator[None]:
    """Explicitly disable caching for a test.

    This fixture:
    - Disables path caching
    - Clears all caches

    Use this for tests that need to verify behavior without caching,
    or that are sensitive to cache state.

    Note: Most tests don't need this - cleanup_state_lite already clears
    caches between tests. This is for tests that specifically need to
    verify uncached behavior.

    Example:
        def test_path_validation_without_cache(caching_disabled):
            # Test behavior with caching explicitly disabled

    """
    from utils import clear_all_caches, disable_caching, enable_caching

    clear_all_caches()
    disable_caching()

    _logger.debug("Caching explicitly disabled for test")

    yield

    # Re-enable caching after test (cleanup_state_lite doesn't do this anymore)
    enable_caching()
    clear_all_caches()


@pytest.fixture
def isolated_cache_manager(tmp_path: Path) -> Iterator[CacheManager]:
    """Provide a CacheManager instance with isolated temp directory.

    This fixture:
    - Creates an isolated cache directory
    - Instantiates a real CacheManager (not a test double)
    - Properly shuts down the manager after test

    Use this for integration tests that need to test CacheManager behavior
    with real file I/O but isolated from the production cache.

    Yields:
        CacheManager instance with isolated cache directory

    Example:
        def test_cache_persistence(isolated_cache_manager):
            manager = isolated_cache_manager
            manager.cache_shots([shot_data])
            # Verify data is persisted

    """
    from cache_manager import CacheManager

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)

    # Create subdirectories CacheManager expects
    (cache_dir / "thumbnails").mkdir(exist_ok=True)
    (cache_dir / "production").mkdir(exist_ok=True)

    manager = CacheManager(cache_dir=cache_dir)

    _logger.debug("Created isolated CacheManager at: %s", cache_dir)

    yield manager

    # Cleanup
    try:
        manager.shutdown()
    except Exception as e:
        _logger.debug("CacheManager shutdown exception: %s", e)


@pytest.fixture
def clean_disk_cache(tmp_path: Path) -> Iterator[Path]:
    """Guaranteed empty disk cache for test - prevents cache leakage.

    This fixture:
    - Creates a fresh, empty cache directory per test
    - Sets SHOTBOT_TEST_CACHE_DIR to the new directory
    - Ensures no stale cache data from previous tests
    - Completely removes the directory after test

    Use this when tests need guaranteed empty cache state, such as:
    - Testing cold start behavior
    - Verifying cache miss scenarios
    - Ensuring no leakage from previous tests

    Yields:
        Path to the clean, empty cache directory

    Example:
        def test_cold_start_loads_from_filesystem(clean_disk_cache):
            cache_dir = clean_disk_cache
            assert not list(cache_dir.iterdir())  # Empty!
            # Test behavior with empty cache

    """
    cache_dir = tmp_path / "clean_cache"
    cache_dir.mkdir(exist_ok=True)

    # Save original env var
    original_cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")

    # Set new clean cache directory
    os.environ["SHOTBOT_TEST_CACHE_DIR"] = str(cache_dir)

    _logger.debug("Clean disk cache created: %s", cache_dir)

    yield cache_dir

    # Complete cleanup: remove directory entirely
    try:
        shutil.rmtree(cache_dir, ignore_errors=True)
    except Exception as e:
        _logger.debug("clean_disk_cache cleanup exception: %s", e)

    # Restore original env var
    if original_cache_dir is not None:
        os.environ["SHOTBOT_TEST_CACHE_DIR"] = original_cache_dir
    else:
        os.environ.pop("SHOTBOT_TEST_CACHE_DIR", None)


@pytest.fixture
def clean_thumbnails(tmp_path: Path) -> Iterator[Path]:
    """Clear and isolate thumbnail directory for thumbnail-specific tests.

    This fixture:
    - Creates a clean, isolated thumbnails directory
    - Clears any existing thumbnails in the test cache dir
    - Provides a fresh directory for thumbnail generation tests

    WARNING: Thumbnails are expensive to regenerate. Only use this fixture
    for tests that specifically need thumbnail isolation:
    - Testing thumbnail generation
    - Testing thumbnail cache miss behavior
    - Testing thumbnail cleanup

    Most tests should NOT use this fixture - thumbnails are intentionally
    preserved between tests for performance reasons.

    Yields:
        Path to the clean thumbnails directory

    Example:
        def test_thumbnail_generation_creates_file(clean_thumbnails):
            thumbnails_dir = clean_thumbnails
            assert not list(thumbnails_dir.iterdir())  # Empty!
            # Generate thumbnail and verify

    """
    thumbnails_dir = tmp_path / "thumbnails"
    thumbnails_dir.mkdir(exist_ok=True)

    # Also clear any thumbnails in the current test cache dir
    cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")
    if cache_dir:
        existing_thumbnails = Path(cache_dir) / "thumbnails"
        if existing_thumbnails.exists():
            try:
                shutil.rmtree(existing_thumbnails, ignore_errors=True)
                existing_thumbnails.mkdir(exist_ok=True)
            except Exception as e:
                _logger.debug("clean_thumbnails clear exception: %s", e)

    _logger.debug("Clean thumbnails directory created: %s", thumbnails_dir)

    yield thumbnails_dir

    # Cleanup: remove the isolated thumbnails directory
    try:
        shutil.rmtree(thumbnails_dir, ignore_errors=True)
    except Exception as e:
        _logger.debug("clean_thumbnails cleanup exception: %s", e)


@pytest.fixture
def seed_cache_file(tmp_path: Path) -> Iterator[SeedCacheFile]:  # noqa: F821
    """Fixture for seeding cache files with specific content for persistence tests.

    Use this fixture with @pytest.mark.persistent_cache to test:
    - Cache file loading behavior
    - Corrupted JSON handling
    - Missing field handling
    - Schema migration paths
    - Permission error handling

    The fixture creates an isolated cache directory and provides a helper
    function to write cache files with specific content.

    Yields:
        SeedCacheFile: A callable that writes cache files with given content

    Example:
        @pytest.mark.persistent_cache
        def test_loads_valid_cache(seed_cache_file):
            cache_dir = seed_cache_file.cache_dir
            seed_cache_file("shots.json", '{"version": 1, "shots": []}')

            # Now test cache loading behavior
            manager = CacheManager(cache_dir=cache_dir)
            ...

    """
    import json
    from dataclasses import dataclass

    cache_dir = tmp_path / "seeded_cache"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / "production").mkdir(exist_ok=True)
    (cache_dir / "thumbnails").mkdir(exist_ok=True)

    # Save and set environment variable
    original_cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")
    os.environ["SHOTBOT_TEST_CACHE_DIR"] = str(cache_dir)

    @dataclass
    class SeedCacheFile:
        """Helper for seeding cache files with specific content."""

        cache_dir: Path

        def __call__(
            self,
            filename: str,
            content: str | dict | list,
            *,
            in_production: bool = True,
        ) -> Path:
            """Write a cache file with the given content.

            Args:
                filename: Name of the cache file (e.g., "shots.json")
                content: File content - string for raw content, dict/list for JSON
                in_production: If True, write to production/ subdirectory

            Returns:
                Path to the created cache file

            """
            if in_production:
                target_dir = self.cache_dir / "production"
            else:
                target_dir = self.cache_dir

            target_dir.mkdir(exist_ok=True)
            file_path = target_dir / filename

            if isinstance(content, str):
                file_path.write_text(content, encoding="utf-8")
            else:
                file_path.write_text(
                    json.dumps(content, indent=2), encoding="utf-8"
                )

            _logger.debug("Seeded cache file: %s", file_path)
            return file_path

        def corrupt(self, filename: str, *, in_production: bool = True) -> Path:
            """Write a corrupted (invalid JSON) cache file.

            Args:
                filename: Name of the cache file
                in_production: If True, write to production/ subdirectory

            Returns:
                Path to the corrupted cache file

            """
            return self(
                filename,
                "{invalid json: [",  # Syntactically invalid JSON
                in_production=in_production,
            )

        def truncated(self, filename: str, *, in_production: bool = True) -> Path:
            """Write a truncated (incomplete) cache file.

            Args:
                filename: Name of the cache file
                in_production: If True, write to production/ subdirectory

            Returns:
                Path to the truncated cache file

            """
            return self(
                filename,
                '{"version": 1, "shots": [{"show": "test"',  # Cut off mid-object
                in_production=in_production,
            )

        def empty(self, filename: str, *, in_production: bool = True) -> Path:
            """Write an empty cache file.

            Args:
                filename: Name of the cache file
                in_production: If True, write to production/ subdirectory

            Returns:
                Path to the empty cache file

            """
            return self(filename, "", in_production=in_production)

    seeder = SeedCacheFile(cache_dir=cache_dir)

    _logger.debug("seed_cache_file fixture created at: %s", cache_dir)

    yield seeder

    # Cleanup: restore original env var
    if original_cache_dir is not None:
        os.environ["SHOTBOT_TEST_CACHE_DIR"] = original_cache_dir
    else:
        os.environ.pop("SHOTBOT_TEST_CACHE_DIR", None)

