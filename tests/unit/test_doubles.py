"""Reusable test doubles following UNIFIED_TESTING_GUIDE best practices.

This module provides lightweight test doubles for use in unit tests,
avoiding excessive mocking and focusing on behavior testing.

Test Doubles Provided:
    - SignalDouble: Lightweight signal emulation for non-Qt components
    - TestProcessPool: Subprocess boundary mock with predictable behavior
    - TestFileSystem: In-memory filesystem for fast testing
    - TestQApplication: Minimal Qt application for widget testing
    - TestCache: In-memory cache for testing cache-dependent components

Usage:
    These test doubles should be used instead of Mock() objects to provide
    more realistic behavior while maintaining test isolation and speed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest


# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

pytestmark = [pytest.mark.unit, pytest.mark.slow]


class TestFileSystem:
    """In-memory filesystem for fast testing without I/O.

    Provides file operations without touching disk, making tests
    faster and more isolated.

    Example:
        fs = TestFileSystem()
        fs.write_file("/test/file.txt", "content")
        assert fs.exists("/test/file.txt")
    """

    __test__ = False

    def __init__(self) -> None:
        """Initialize the test filesystem."""
        self.files: dict[str, bytes] = {}
        self.directories: set[str] = set()
        self.metadata: dict[str, dict[str, Any]] = defaultdict(dict)
        self.access_times: dict[str, datetime] = {}
        self.modification_times: dict[str, datetime] = {}

    def write_file(self, path: str, content: Any) -> None:
        """Write content to a file path.

        Args:
            path: File path to write to
            content: Content to write (str or bytes)
        """
        path = str(Path(path))

        # Convert content to bytes
        if isinstance(content, str):
            content = content.encode("utf-8")
        elif not isinstance(content, bytes):
            content = str(content).encode("utf-8")

        # Store file and update times
        self.files[path] = content
        now = datetime.now(tz=UTC)
        self.modification_times[path] = now
        self.access_times[path] = now

        # Create parent directories
        parent = str(Path(path).parent)
        if parent != path:
            self.mkdir(parent)

    def read_file(self, path: str, mode: str = "r") -> Any:
        """Read content from a file path.

        Args:
            path: File path to read from
            mode: Read mode ('r' for text, 'rb' for binary)

        Returns:
            File contents (str or bytes based on mode)

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        path = str(Path(path))

        if path not in self.files:
            raise FileNotFoundError(f"No such file: {path}")

        self.access_times[path] = datetime.now(tz=UTC)
        content = self.files[path]

        if "b" not in mode:
            return content.decode("utf-8")
        return content

    def exists(self, path: str) -> bool:
        """Check if a path exists.

        Args:
            path: Path to check

        Returns:
            bool: True if path exists
        """
        path = str(Path(path))
        return path in self.files or path in self.directories

    def is_file(self, path: str) -> bool:
        """Check if path is a file.

        Args:
            path: Path to check

        Returns:
            bool: True if path is a file
        """
        return str(Path(path)) in self.files

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory.

        Args:
            path: Path to check

        Returns:
            bool: True if path is a directory
        """
        return str(Path(path)) in self.directories

    def mkdir(self, path: str, parents: bool = True) -> None:
        """Create a directory.

        Args:
            path: Directory path to create
            parents: Create parent directories if needed
        """
        path = str(Path(path))

        if parents:
            # Create all parent directories
            current = Path(path)
            dirs_to_create = []
            while current != current.parent:
                dirs_to_create.append(str(current))
                current = current.parent

            for dir_path in reversed(dirs_to_create):
                self.directories.add(dir_path)
        else:
            self.directories.add(path)

    def listdir(self, path: str) -> list[str]:
        """List directory contents.

        Args:
            path: Directory path to list

        Returns:
            list[str]: Names of files and directories in path
        """
        path = str(Path(path))
        if path not in self.directories:
            raise FileNotFoundError(f"No such directory: {path}")

        results = set()
        path_obj = Path(path)

        # Find all files in this directory
        for file_path in self.files:
            file_obj = Path(file_path)
            if file_obj.parent == path_obj:
                results.add(file_obj.name)

        # Find all subdirectories
        for dir_path in self.directories:
            dir_obj = Path(dir_path)
            if dir_obj.parent == path_obj and dir_obj != path_obj:
                results.add(dir_obj.name)

        return sorted(results)

    def remove(self, path: str) -> None:
        """Remove a file.

        Args:
            path: File path to remove
        """
        path = str(Path(path))
        if path in self.files:
            del self.files[path]
            self.metadata.pop(path, None)
            self.access_times.pop(path, None)
            self.modification_times.pop(path, None)

    def get_size(self, path: str) -> int:
        """Get file size.

        Args:
            path: File path

        Returns:
            int: Size in bytes
        """
        path = str(Path(path))
        if path in self.files:
            return len(self.files[path])
        return 0

    def get_mtime(self, path: str) -> float:
        """Get modification time.

        Args:
            path: File path

        Returns:
            float: Modification time as timestamp
        """
        path = str(Path(path))
        if path in self.modification_times:
            return self.modification_times[path].timestamp()
        return 0.0

    def clear(self) -> None:
        """Clear all files and directories."""
        self.files.clear()
        self.directories.clear()
        self.metadata.clear()
        self.access_times.clear()
        self.modification_times.clear()


class TestCache:
    """In-memory cache for testing cache-dependent components.

    Provides a cache implementation that doesn't persist to disk,
    making tests faster and more isolated.

    Example:
        cache = TestCache()
        cache.set("key", "value", ttl_seconds=60)
        assert cache.get("key") == "value"
    """

    __test__ = False

    def __init__(self) -> None:
        """Initialize the test cache."""
        self.data: dict[str, Any] = {}
        self.expiry_times: dict[str, datetime] = {}
        self.access_counts: dict[str, int] = defaultdict(int)
        self.cache_hits = 0
        self.cache_misses = 0

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache.

        Args:
            key: Cache key
            default: Default value if not found or expired

        Returns:
            Cached value or default
        """
        self.access_counts[key] += 1

        # Check expiry
        if key in self.expiry_times and datetime.now(tz=UTC) > self.expiry_times[key]:
            self.data.pop(key, None)
            self.expiry_times.pop(key, None)

        if key in self.data:
            self.cache_hits += 1
            return self.data[key]

        self.cache_misses += 1
        return default

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time to live in seconds
        """
        self.data[key] = value

        if ttl_seconds is not None:
            self.expiry_times[key] = datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)

    def delete(self, key: str) -> bool:
        """Delete key from cache.

        Args:
            key: Cache key to delete

        Returns:
            bool: True if key existed
        """
        existed = key in self.data
        self.data.pop(key, None)
        self.expiry_times.pop(key, None)
        return existed

    def clear(self) -> None:
        """Clear all cached data."""
        self.data.clear()
        self.expiry_times.clear()
        self.access_counts.clear()
        self.cache_hits = 0
        self.cache_misses = 0

    def expire_all(self) -> None:
        """Expire all cached entries."""
        self.expiry_times = {
            key: datetime.now(tz=UTC) - timedelta(seconds=1) for key in self.data
        }

    def has(self, key: str) -> bool:
        """Check if key exists and is not expired.

        Args:
            key: Cache key to check

        Returns:
            bool: True if key exists and is valid
        """
        if key in self.expiry_times and datetime.now(tz=UTC) > self.expiry_times[key]:
            return False
        return key in self.data

    @property
    def size(self) -> int:
        """Get number of cached items."""
        return len(self.data)

    @property
    def hit_rate(self) -> float:
        """Get cache hit rate."""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total


class TestQApplication:
    """Minimal Qt application mock for widget testing.

    Provides just enough Qt application behavior for testing widgets
    without requiring full Qt application setup.
    """

    __test__ = False

    def __init__(self) -> None:
        """Initialize the test application."""
        self.clipboard_text = ""
        self.style_sheet = ""
        self.application_name = "TestApp"
        self.organization_name = "TestOrg"
        self.quit_called = False

    def clipboard(self):
        """Get clipboard mock."""
        return self

    def setText(self, text: str) -> None:
        """Set clipboard text."""
        self.clipboard_text = text

    def text(self) -> str:
        """Get clipboard text."""
        return self.clipboard_text

    def setStyleSheet(self, style: str) -> None:
        """Set application style sheet."""
        self.style_sheet = style

    def quit(self) -> None:
        """Mark application as quit."""
        self.quit_called = True

    def processEvents(self) -> None:
        """Process events (no-op in test)."""

    @staticmethod
    def instance() -> TestQApplication:
        """Get application instance."""
        if not hasattr(TestQApplication, "_instance"):
            TestQApplication._instance = TestQApplication()
        return TestQApplication._instance
