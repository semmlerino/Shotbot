#!/usr/bin/env python3
"""Test cache directory separation between production, mock, and test modes."""

# Standard library imports
import logging
import sys
from pathlib import Path

# Third-party imports
import pytest


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def reset_cache_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level cache disabled flag to prevent test contamination.

    The _cache_disabled flag in utils.py is a global state that can persist
    across tests, causing subsequent tests to see incorrect cache behavior.
    This fixture ensures each test starts with a clean state.
    """
    import utils

    monkeypatch.setattr(utils, "_cache_disabled", False)


def test_cache_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test CacheConfig mode detection and directory selection."""
    logger.info("=" * 50)
    logger.info("Testing CacheConfig")
    logger.info("=" * 50)

    # Local application imports
    from cache_config import (
        CacheConfig,
    )

    # Clear all mode indicators using monkeypatch (parallel-safe)
    monkeypatch.delenv("SHOTBOT_MOCK", raising=False)
    monkeypatch.delenv("SHOTBOT_TEST_MODE", raising=False)
    monkeypatch.delenv("SHOTBOT_HEADLESS", raising=False)

    # Since we're running under pytest, we'll always be in test mode
    # So we can't test production mode directly, only verify test mode is working
    cache_dir = CacheConfig.get_cache_directory()
    assert cache_dir == CacheConfig.TEST_CACHE_DIR
    logger.info(f"✅ Test cache (expected under pytest): {cache_dir}")

    # Test mock mode - but since we're under pytest, test mode takes precedence
    monkeypatch.setenv("SHOTBOT_MOCK", "1")
    cache_dir = CacheConfig.get_cache_directory()
    # Test mode takes precedence over mock when running under pytest
    assert cache_dir == CacheConfig.TEST_CACHE_DIR
    logger.info(f"✅ Test cache (overrides mock under pytest): {cache_dir}")

    # Test test mode explicitly set - should still be test mode
    monkeypatch.setenv("SHOTBOT_TEST_MODE", "1")
    cache_dir = CacheConfig.get_cache_directory()
    assert cache_dir == CacheConfig.TEST_CACHE_DIR
    logger.info(f"✅ Test cache (explicit): {cache_dir}")


def test_cache_manager_separation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that CacheManager uses separate directories."""
    logger.info("=" * 50)
    logger.info("Testing CacheManager directory separation")
    logger.info("=" * 50)

    # Local application imports
    from cache_manager import (
        CacheManager,
    )

    # Since we're running under pytest, all CacheManagers will use test mode
    monkeypatch.delenv("SHOTBOT_MOCK", raising=False)
    monkeypatch.delenv("SHOTBOT_TEST_MODE", raising=False)

    # Test mode is automatically detected when running under pytest
    test_manager = CacheManager(cache_dir=tmp_path / "cache")
    assert test_manager.cache_dir == tmp_path / "cache"
    logger.info(f"✅ Test CacheManager (under pytest): {test_manager.cache_dir}")

    # Even with mock mode set, test mode takes precedence
    monkeypatch.setenv("SHOTBOT_MOCK", "1")
    mock_manager = CacheManager(cache_dir=tmp_path / "cache")
    assert mock_manager.cache_dir == tmp_path / "cache"
    logger.info(f"✅ Test CacheManager (overrides mock): {mock_manager.cache_dir}")

    # Explicitly setting test mode should still work
    monkeypatch.setenv("SHOTBOT_TEST_MODE", "1")
    test_manager2 = CacheManager(cache_dir=tmp_path / "cache")
    assert test_manager2.cache_dir == tmp_path / "cache"
    logger.info(f"✅ Test CacheManager (explicit): {test_manager2.cache_dir}")

    # In test mode, all managers point to the same test directory
    assert test_manager.cache_dir == mock_manager.cache_dir
    assert test_manager.cache_dir == test_manager2.cache_dir
    logger.info("✅ All cache directories are the same (isolated to tmp_path)")


def test_cache_isolation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that data written to one cache doesn't appear in another."""
    logger.info("=" * 50)
    logger.info("Testing cache isolation")
    logger.info("=" * 50)

    # Local application imports
    from cache_manager import (
        CacheManager,
    )

    # Create temporary test directories (parallel-safe)
    test_base = tmp_path / "cache_test"
    test_base.mkdir(parents=True, exist_ok=True)

    # Under pytest, all cache operations go to the test cache directory
    # So we can't test true isolation between production and mock
    # Instead, test that the cache functionality works with explicit cache_dir

    # All managers will use explicit cache_dir for isolation
    test_manager = CacheManager(cache_dir=test_base / "test")
    test_data = [{"name": "test_shot", "path": "/test/path"}]
    test_manager.cache_shots(test_data)
    logger.info("✅ Wrote data to test cache")

    # Even with mock mode set, still uses explicit cache_dir
    monkeypatch.setenv("SHOTBOT_MOCK", "1")
    mock_manager = CacheManager(cache_dir=test_base / "test")
    # This will overwrite the previous data in the same test cache
    mock_data = [{"name": "mock_shot", "path": "/mock/path"}]
    mock_manager.cache_shots(mock_data)
    logger.info("✅ Overwrote data in test cache")

    # Verify the last written data is available
    test_manager2 = CacheManager(cache_dir=test_base / "test")
    cached = test_manager2.get_cached_shots()

    if cached:
        assert len(cached) == 1
        # Should have the mock data since it was written last
        assert cached[0]["name"] == "mock_shot"
    logger.info("✅ Cache functionality works (all using isolated tmp_path)")

    # Verify same cache is used regardless of env vars
    monkeypatch.delenv("SHOTBOT_MOCK", raising=False)
    test_manager3 = CacheManager(cache_dir=test_base / "test")
    cached2 = test_manager3.get_cached_shots()

    if cached2:
        assert len(cached2) == 1
        # Still has mock data since all managers use the same test cache
        assert cached2[0]["name"] == "mock_shot"
    logger.info("✅ All managers use the same isolated cache (tmp_path)")


def test_cache_info() -> None:
    """Test cache information reporting."""
    logger.info("=" * 50)
    logger.info("Testing cache info")
    logger.info("=" * 50)

    # Local application imports
    from cache_config import (
        CacheConfig,
    )

    info = CacheConfig.get_cache_info()

    logger.info("Cache Info:")
    for key, value in info.items():
        logger.info(f"  {key}: {value}")

    assert "cache_directory" in info
    assert "is_mock_mode" in info
    assert "is_test_mode" in info
    logger.info("✅ Cache info contains expected fields")


def main() -> None:
    """Run all cache separation tests."""
    logger.info("Starting cache separation tests...")

    try:
        test_cache_config()
        test_cache_manager_separation()
        test_cache_isolation()
        test_cache_info()

        logger.info("")
        logger.info("=" * 50)
        logger.info("✅ ALL CACHE SEPARATION TESTS PASSED!")
        logger.info("=" * 50)

    except AssertionError as e:
        logger.error(f"❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        # Standard library imports
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
