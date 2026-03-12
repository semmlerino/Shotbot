"""Tests for cache infrastructure: CacheIsolation context manager.

Covers:
- CacheIsolation clears and disables caching inside the block
- CacheIsolation re-enables caching on exit
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.smoke,
]


# ---------------------------------------------------------------------------
# Helpers (scoped to this module)
# ---------------------------------------------------------------------------


def _validate_path(path: Path | str, description: str = "Path") -> bool:
    """Call PathValidators.validate_path_exists."""
    from path_validators import PathValidators

    return PathValidators.validate_path_exists(path, description)


def _get_path_cache_stats() -> dict[str, int]:
    """Return path cache size with a stable key."""
    from path_validators import get_cache_stats

    stats = get_cache_stats()
    return {"size": stats.get("path_cache_size", stats.get("size", 0))}


# ---------------------------------------------------------------------------
# TestCacheIsolationContext
# ---------------------------------------------------------------------------


class TestCacheIsolationContext:
    """Test tests.fixtures.caching.CacheIsolation context manager."""

    def test_cache_isolation_clears_and_disables(self, tmp_path: Path) -> None:
        """CacheIsolation provides a clean, cache-disabled environment inside the block."""
        from tests.fixtures.caching import CacheIsolation

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
        from tests.fixtures.caching import CacheIsolation

        clear_path_cache()

        with CacheIsolation():
            pass

        test_path = tmp_path / "test"
        test_path.mkdir()
        _validate_path(test_path, "test")
        assert _get_path_cache_stats()["size"] > 0
