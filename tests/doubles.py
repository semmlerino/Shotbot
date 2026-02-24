"""Test doubles and utilities for testing.

This module provides test doubles and utilities used throughout the test suite,
following UNIFIED_TESTING_GUIDE principles for behavior-driven testing.

This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest
from PySide6.QtGui import QColor

# Local application imports
# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.fixtures.doubles_library import (
    SignalDouble,
    ThreadSafeTestImage,
)


pytestmark = [pytest.mark.unit, pytest.mark.integration, pytest.mark.slow]


class LauncherWorkerDouble:
    """Test double for LauncherWorker thread.

    Simulates the behavior of a worker thread that executes launcher commands.
    Uses SignalDouble for proper test signal behavior.
    """

    def __init__(self, launcher_id: str, command: str) -> None:
        """Initialize test launcher worker.

        Args:
            launcher_id: ID of the launcher
            command: Command to execute

        """
        self.launcher_id = launcher_id
        self.command = command
        self.process = None

        # Use SignalDouble for test signals
        self.started = SignalDouble()
        self.output = SignalDouble()
        self.error = SignalDouble()
        self.finished = SignalDouble()

        # Control test behavior
        self._should_succeed = not command.startswith("fail")
        self._output_lines = ["Test output line 1", "Test output line 2"]

    def start(self) -> None:
        """Start the test worker (simulate thread start)."""
        self.started.emit()

        if self._should_succeed:
            for line in self._output_lines:
                self.output.emit(self.launcher_id, line)
            self.finished.emit(self.launcher_id, 0)  # Success
        else:
            self.error.emit(self.launcher_id, "Test error")
            self.finished.emit(self.launcher_id, 1)  # Failure

    def quit(self) -> None:
        """Stop the test worker."""

    def wait(self, timeout: int = 1000) -> None:
        """Wait for test worker to finish.

        Args:
            timeout: Maximum wait time in milliseconds

        """


class MockCacheManager:
    """Mock CacheManager for testing without filesystem access.

    This is a true mock (not a test double) because CacheManager
    is at the system boundary dealing with filesystem operations.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize mock cache manager.

        Args:
            cache_dir: Optional cache directory path

        """
        self.cache_dir = cache_dir or Path("/tmp/test_cache")
        self._cache: dict[str, ThreadSafeTestImage] = {}
        self._call_count = 0
        self._last_cached_path: Path | None = None

    def get_cache_dir(self) -> Path:
        """Get the cache directory path.

        Returns:
            Path to cache directory

        """
        return self.cache_dir

    def cache_thumbnail(
        self,
        source_path: str | Path,
        show: str,
        sequence: str,
        shot: str,
    ) -> ThreadSafeTestImage | None:
        """Mock thumbnail caching.

        Args:
            source_path: Path to source image
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Mock ThreadSafeTestImage if successful, None otherwise

        """
        self._call_count += 1
        self._last_cached_path = Path(source_path)

        # Create cache key
        cache_key = f"{show}_{sequence}_{shot}"

        # Return existing or create new mock pixmap
        if cache_key not in self._cache:
            self._cache[cache_key] = ThreadSafeTestImage(100, 100)
            self._cache[cache_key].fill(QColor(100, 100, 100))

        return self._cache[cache_key]

    def get_cached_thumbnail(
        self, show: str, sequence: str, shot: str
    ) -> ThreadSafeTestImage | None:
        """Get cached thumbnail.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Cached ThreadSafeTestImage if exists, None otherwise

        """
        cache_key = f"{show}_{sequence}_{shot}"
        return self._cache.get(cache_key)

    def clear_cache(self) -> None:
        """Clear all cached thumbnails."""
        self._cache.clear()
        self._call_count = 0
        self._last_cached_path = None


class ImagePoolDouble:
    """Test double for image pooling behavior."""

    def __init__(self, pool_size: int = 10) -> None:
        """Initialize image pool.

        Args:
            pool_size: Maximum pool size

        """
        self.pool_size = pool_size
        self._pool: list[ThreadSafeTestImage] = []

    def get_image(self, width: int = 100, height: int = 100) -> ThreadSafeTestImage:
        """Get image from pool or create new one.

        Args:
            width: Image width
            height: Image height

        Returns:
            ThreadSafeTestImage instance

        """
        if self._pool:
            image = self._pool.pop()
            image.fill()  # Reset to white
            return image
        return ThreadSafeTestImage(width, height)

    def return_image(self, image) -> None:
        """Return image to pool for reuse.

        Args:
            image: ThreadSafeTestImage to return

        """
        if len(self._pool) < self.pool_size:
            self._pool.append(image)
