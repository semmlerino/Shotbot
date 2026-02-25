"""Temporary directory fixtures for isolated test file operations.

This module provides fixtures for creating isolated temporary directories
used in tests that need filesystem access, caching, or VFX directory structures.

Fixtures:
    temp_cache_dir: Temporary cache directory
    cache_manager: CacheManager instance with temp cache dir
    real_cache_manager: Alias for cache_manager (compatibility)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def temp_cache_dir() -> Iterator[Path]:
    """Create temporary cache directory for testing.

    Yields:
        Path to a temporary directory for cache files

    """
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = Path(temp_dir)
        yield cache_dir


@pytest.fixture
def cache_manager(temp_cache_dir: Path) -> Iterator[object]:
    """Create CacheManager instance for testing.

    Uses temp_cache_dir to ensure isolation between tests.

    Args:
        temp_cache_dir: Temporary cache directory fixture

    Yields:
        CacheManager instance configured with temp directory

    """
    from cache_manager import CacheManager

    manager = CacheManager(cache_dir=temp_cache_dir)
    yield manager
    # Cleanup
    manager.clear_cache()


@pytest.fixture
def real_cache_manager(cache_manager: object) -> Iterator[object]:
    """Alias for cache_manager fixture (for compatibility).

    Some tests were written using 'real_cache_manager' to distinguish
    from mocked versions. This alias maintains compatibility.

    Args:
        cache_manager: The actual cache_manager fixture

    Yields:
        Same CacheManager instance as cache_manager

    """
    return cache_manager
