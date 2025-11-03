"""Process Pool Manager for optimized subprocess handling.

This module provides centralized process management with pooling, caching,
and session reuse to reduce the overhead of repeated subprocess calls.
"""

from __future__ import annotations

# Standard library imports
import concurrent.futures
import hashlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

# Third-party imports
from PySide6.QtCore import QMutex, QMutexLocker, QObject, Signal
from PySide6.QtWidgets import QApplication

# Local application imports
from config import ThreadingConfig
from logging_mixin import LoggingMixin, get_module_logger
from secure_command_executor import get_secure_executor

# Module-level logger
logger = get_module_logger(__name__)

if TYPE_CHECKING:
    # Local application imports
    from persistent_bash_session import PersistentBashSession
    from type_definitions import PerformanceMetricsDict

# Import debug utilities
try:
    # Local application imports
    from debug_utils import setup_enhanced_debugging

    _has_debug_utils = True
except ImportError:
    _has_debug_utils = False

HAS_DEBUG_UTILS = _has_debug_utils

# Note: fcntl is not currently used, setting HAS_FCNTL to False
HAS_FCNTL = False

# Enable verbose debug logging if environment variable is set
DEBUG_VERBOSE = os.environ.get("SHOTBOT_DEBUG_VERBOSE", "").lower() in (
    "1",
    "true",
    "yes",
)
if DEBUG_VERBOSE:
    # Set debug level for verbose logging
    logger.setLevel(logging.DEBUG)
    logger.info("VERBOSE DEBUG MODE ENABLED for ProcessPoolManager")

# Setup enhanced debugging if available
if HAS_DEBUG_UTILS:
    from debug_utils import setup_enhanced_debugging

    setup_enhanced_debugging()


class CommandCache:
    """TTL-based cache for command results."""

    def __init__(self, default_ttl: int = 30) -> None:
        """Initialize command cache.

        Args:
            default_ttl: Default time-to-live in seconds
        """
        super().__init__()
        self._cache: dict[
            str,
            tuple[str, float, int, str],
        ] = {}  # key -> (result, timestamp, ttl, original_command)
        self._lock = QMutex()  # Use Qt mutex for consistency
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0

    def get(self, command: str) -> str | None:
        """Get cached result if not expired.

        Args:
            command: Command string to look up

        Returns:
            Cached result or None if not found/expired
        """
        key = self._make_key(command)

        with QMutexLocker(self._lock):
            if key in self._cache:
                result, timestamp, ttl, _ = self._cache[key]
                if time.time() - timestamp < ttl:
                    self._hits += 1
                    logger.debug(f"Cache hit for command: {command[:50]}...")
                    return result
                del self._cache[key]

            self._misses += 1
            return None

    def set(self, command: str, result: str, ttl: int | None = None) -> None:
        """Cache command result with TTL.

        Args:
            command: Command string
            result: Result to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        if ttl is None:
            ttl = self._default_ttl

        key = self._make_key(command)

        with QMutexLocker(self._lock):
            self._cache[key] = (result, time.time(), ttl, command)
            self._cleanup_expired()

    def invalidate(self, pattern: str | None = None) -> None:
        """Invalidate cache entries.

        Args:
            pattern: pattern to match (invalidates all if None)
        """
        with QMutexLocker(self._lock):
            if pattern is None:
                self._cache.clear()
                logger.info("Cleared entire command cache")
            else:
                # Check the original command (4th element in tuple) for pattern
                keys_to_remove: list[str] = []
                for key, value in self._cache.items():
                    if len(value) >= 4 and pattern in value[3]:
                        keys_to_remove.append(key)
                for key in keys_to_remove:
                    del self._cache[key]
                logger.info(
                    f"Invalidated {len(keys_to_remove)} cache entries matching '{pattern}'",
                )

    def get_stats(self) -> dict[str, int | float]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        with QMutexLocker(self._lock):
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0

            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "size": len(self._cache),
                "total_requests": total,
            }

    def _make_key(self, command: str) -> str:
        """Generate cache key from command.

        Args:
            command: Command string

        Returns:
            SHA256 hash of command
        """
        return hashlib.sha256(command.encode()).hexdigest()

    def _cleanup_expired(self) -> None:
        """Remove expired entries."""
        if len(self._cache) <= 100:  # Don't cleanup small caches
            return

        current_time = time.time()
        expired = [
            key
            for key, (_, timestamp, ttl, _) in self._cache.items()
            if current_time - timestamp >= ttl
        ]
        for key in expired:
            del self._cache[key]

        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired cache entries")


class ProcessPoolManager(LoggingMixin, QObject):
    """Centralized process management with pooling and caching.

    This singleton class manages all subprocess operations for the application,
    providing session reuse, command caching, and parallel execution.
    """

    # Singleton instance
    _instance = None
    _lock = QMutex()  # Qt mutex for thread-safe singleton access

    # Qt signals
    command_completed = Signal(str, object)  # command_id, result
    command_failed = Signal(str, str)  # command_id, error

    def __new__(
        cls, max_workers: int = 4, sessions_per_type: int = 3
    ) -> ProcessPoolManager:
        """Ensure singleton pattern with proper thread safety using double-checked locking.

        This implementation uses double-checked locking pattern which optimizes
        the common case where the singleton is already initialized by avoiding
        the lock acquisition. The inner check ensures thread safety during creation.
        """
        # Fast path - no lock if already initialized
        if cls._instance is None:
            with QMutexLocker(cls._lock):
                # Double-check inside lock to prevent race condition
                if cls._instance is None:
                    instance = super().__new__(cls)
                    cls._instance = instance
        return cls._instance

    def __init__(self, max_workers: int = 4, sessions_per_type: int = 3) -> None:
        """Initialize process pool manager.

        Args:
            max_workers: Maximum concurrent workers
            sessions_per_type: Number of sessions to maintain per type for parallelism
        """
        # Use instance-level flag to prevent re-initialization
        # This is set AFTER initialization completes
        if hasattr(self, "_init_done") and self._init_done:
            return

        # Lock to ensure only one thread initializes
        with QMutexLocker(ProcessPoolManager._lock):
            # Double-check inside lock
            if hasattr(self, "_init_done") and self._init_done:
                return

            super().__init__()

            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers,
            )
            # Session pools: type -> list of sessions
            # Replace session pools with secure executor
            self._secure_executor = get_secure_executor()
            self._session_pools: dict[str, list[PersistentBashSession]] = {}
            self._session_round_robin: dict[str, int] = {}  # Track next session to use
            self._session_creation_in_progress: dict[
                str, bool
            ] = {}  # Prevent double creation
            self._sessions_per_type = sessions_per_type
            self._cache = CommandCache(default_ttl=30)
            self._session_lock = QMutex()  # Use Qt mutex for consistency
            self._metrics = ProcessMetrics()
            # Instance-level mutex and shutdown flag for thread-safe shutdown
            self._mutex = QMutex()
            self._shutdown_requested = False

            # Mark initialization as complete (must be last)
            self._init_done = True

        self.logger.info(f"ProcessPoolManager initialized with {max_workers} workers")

    @classmethod
    def get_instance(cls) -> ProcessPoolManager:
        """Get singleton instance.

        Thread safety is handled by __new__ method.

        Returns:
            ProcessPoolManager singleton
        """
        # Standard singleton pattern
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def execute_workspace_command(
        self,
        command: str,
        cache_ttl: int = 30,
        timeout: int | None = None,
    ) -> str:
        """Execute workspace command with caching and session reuse.

        Args:
            command: Command to execute
            cache_ttl: Cache time-to-live in seconds
            timeout: Command execution timeout in seconds (default 120s)

        Returns:
            Command output
        """
        if timeout is None:
            timeout = int(ThreadingConfig.SUBPROCESS_TIMEOUT)

        if DEBUG_VERBOSE:
            self.logger.debug(f"execute_workspace_command called: {command[:50]}...")

        # Check cache first
        cached = self._cache.get(command)
        if cached is not None:
            self._metrics.cache_hits += 1
            if DEBUG_VERBOSE:
                self.logger.debug(f"Cache HIT for command: {command[:50]}...")
            return cached

        if DEBUG_VERBOSE:
            self.logger.debug(
                f"Cache MISS for command: {command[:50]}... - will execute"
            )

        self._metrics.cache_misses += 1
        self._metrics.subprocess_calls += 1

        # Use secure executor instead of bash session
        start_time = time.time()
        try:
            # Execute with secure validation
            result = self._secure_executor.execute(
                command,
                timeout=timeout,
                cache_ttl=0,  # Handle caching separately
                allow_workspace_function=True,  # Allow 'ws' commands
            )

            # Cache result
            self._cache.set(command, result, ttl=cache_ttl)

            # Update metrics
            elapsed = (time.time() - start_time) * 1000
            self._metrics.update_response_time(elapsed)

            # Emit completion signal
            self.command_completed.emit(command, result)

            return result

        except Exception as e:
            self.logger.error(f"Command execution failed: {e}")
            self.command_failed.emit(command, str(e))
            raise

    def batch_execute(
        self,
        commands: list[str],
        cache_ttl: int = 30,
        session_type: str = "workspace",
    ) -> dict[str, str | None]:
        """Execute multiple commands in parallel using session pool.

        Leverages multiple sessions for true parallel execution.

        Args:
            commands: List of commands to execute
            cache_ttl: Cache time-to-live in seconds
            session_type: Type of session pool to use

        Returns:
            Dictionary mapping commands to results
        """
        # Check cache first and separate cached from non-cached
        results: dict[str, str | None] = {}
        commands_to_execute: list[str] = []

        for cmd in commands:
            cached = self._cache.get(cmd)
            if cached is not None:
                results[cmd] = cached
                self._metrics.cache_hits += 1
                self.logger.debug(f"Batch: cache hit for {cmd[:50]}...")
            else:
                commands_to_execute.append(cmd)
                self._metrics.cache_misses += 1

        if not commands_to_execute:
            return results  # All results were cached

        # Execute non-cached commands in parallel
        futures: dict[concurrent.futures.Future[str], str] = {}
        for cmd in commands_to_execute:
            future = self._executor.submit(
                self._execute_with_session_pool,
                cmd,
                cache_ttl,
                session_type,
            )
            futures[future] = cmd

        # Collect results
        for future in concurrent.futures.as_completed(futures):
            cmd = futures[future]
            try:
                result = future.result()
                results[cmd] = result
                # Cache successful results
                self._cache.set(cmd, result, ttl=cache_ttl)
            except Exception as e:
                self.logger.error(f"Batch command failed: {cmd} - {e}")
                results[cmd] = None

        return results

    def _execute_with_session_pool(
        self,
        command: str,
        _cache_ttl: int,
        _session_type: str,
    ) -> str:
        """Execute command using session pool for true parallelism.

        This method is designed to be called in parallel threads.

        Args:
            command: Command to execute
            cache_ttl: Cache time-to-live
            session_type: Type of session pool

        Returns:
            Command output
        """
        # Use secure executor for shell commands
        start_time = time.time()
        try:
            # Execute with secure validation
            result = self._secure_executor.execute(
                command,
                timeout=30,  # Default timeout for shell commands
                cache_ttl=0,  # No caching for general shell commands
                allow_workspace_function=False,  # Standard commands only
            )

            # Update metrics
            elapsed = (time.time() - start_time) * 1000
            self._metrics.update_response_time(elapsed)
            self._metrics.subprocess_calls += 1

            return result

        except Exception as e:
            self.logger.error(f"Session pool execution failed: {e}")
            raise

    def find_files_python(self, directory: str, pattern: str) -> list[str]:
        """Find files using Python instead of subprocess.

        Args:
            directory: Directory to search
            pattern: File pattern to match

        Returns:
            List of matching file paths
        """
        # Use Python pathlib instead of subprocess find
        self._metrics.python_operations += 1

        try:
            path = Path(directory)
            if not path.exists():
                return []

            # Use rglob for recursive search
            files = list(path.rglob(pattern))
            return [str(f) for f in files]

        except Exception as e:
            self.logger.error(f"File search failed: {e}")
            return []

    def invalidate_cache(self, pattern: str | None = None) -> None:
        """Invalidate command cache.

        Args:
            pattern: pattern to match
        """
        self._cache.invalidate(pattern)

    def get_metrics(self) -> PerformanceMetricsDict:
        """Get performance metrics.

        Returns:
            Performance metrics dictionary
        """
        metrics = self._metrics.get_report()

        # Build proper PerformanceMetricsDict structure
        # Use defaults for any missing required fields
        # Convert int | float to explicit int/float types
        result: PerformanceMetricsDict = {
            "total_shots": int(metrics.get("total_shots", 0)),
            "total_refreshes": int(metrics.get("total_refreshes", 0)),
            "last_refresh_time": float(metrics.get("last_refresh_time", 0.0)),
            "cache_hits": int(metrics.get("cache_hits", 0)),
            "cache_misses": int(metrics.get("cache_misses", 0)),
            "cache_hit_rate": float(metrics.get("cache_hit_rate", 0.0)),
            "cache_hit_count": int(metrics.get("cache_hit_count", 0)),
            "cache_miss_count": int(metrics.get("cache_miss_count", 0)),
            "loading_in_progress": bool(metrics.get("loading_in_progress", False)),
            "session_warmed": bool(metrics.get("session_warmed", False)),
        }

        return result

    def shutdown(self, timeout: float = 5.0) -> None:
        """Shutdown the process pool manager with enhanced error handling.

        Args:
            timeout: Maximum time to wait for executor shutdown in seconds
        """
        with QMutexLocker(self._mutex):
            if self._shutdown_requested:
                self.logger.debug(
                    "ProcessPoolManager shutdown already requested, skipping"
                )
                return
            self._shutdown_requested = True

        self.logger.debug(f"Starting ProcessPoolManager shutdown (timeout={timeout}s)")

        # Stage 1: Clear session tracking with error handling
        try:
            with QMutexLocker(self._session_lock):
                session_count = len(self._session_round_robin)
                self._session_round_robin.clear()
                if session_count > 0:
                    self.logger.debug(
                        f"Cleared {session_count} session tracking entries"
                    )
        except Exception as e:
            self.logger.warning(f"Error clearing session tracking: {e}")

        # Stage 2: Cancel pending futures if possible
        # Note: Access to ThreadPoolExecutor internals is intentional for graceful shutdown
        # These are private attributes and not part of the public API.
        # Type checking is disabled for this block because we're accessing _pending_work_items
        # which is an internal implementation detail of ThreadPoolExecutor.
        try:
            if hasattr(self._executor, "_pending_work_items"):
                # Access ThreadPoolExecutor._pending_work_items (private API)
                # Required for proper cleanup of pending futures on shutdown
                # Type checking disabled: not in public API but stable across Python versions
                pending_items_raw = self._executor._pending_work_items  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAttributeAccessIssue]
                pending_items = cast("dict[object, object]", pending_items_raw)
                pending_count = len(pending_items)
                if pending_count > 0:
                    self.logger.debug(f"Cancelling {pending_count} pending futures")
                    # Cancel all pending futures
                    for work_item in pending_items.values():
                        if hasattr(work_item, "future"):
                            # Access work_item.future (private ThreadPoolExecutor API)
                            # Required to cancel pending futures during shutdown
                            future = cast(
                                "concurrent.futures.Future[object]",
                                work_item.future,  # pyright: ignore[reportAttributeAccessIssue]
                            )
                            future.cancel()
        except Exception as e:
            self.logger.debug(f"Could not cancel pending futures: {e}")

        # Stage 3: Graceful executor shutdown with enhanced monitoring
        shutdown_successful = False
        try:
            self.logger.debug("Initiating ThreadPoolExecutor shutdown")
            # Try to shutdown with wait and cancel_futures
            # Note: ThreadPoolExecutor.shutdown() doesn't support timeout parameter
            # We use cancel_futures=True (Python 3.9+) to cancel pending work
            try:
                # Python 3.11+ guaranteed to support cancel_futures parameter
                self._executor.shutdown(wait=True, cancel_futures=True)
                shutdown_successful = True
                self.logger.debug("ThreadPoolExecutor shutdown completed normally")
            except Exception as e:
                self.logger.debug(f"Executor shutdown exception: {e}")
                # Force shutdown without wait as fallback
                self._executor.shutdown(wait=False)

        except Exception as e:
            self.logger.error(f"Error during ProcessPoolManager executor shutdown: {e}")

        # Stage 4: Clean up any remaining resources
        try:
            # Clear caches (note: _cache is the actual attribute, not _command_cache)
            if hasattr(self, "_cache"):
                # CommandCache has internal dict, we can get its size via get_stats
                stats = self._cache.get_stats()
                cache_size = stats["size"]
                self._cache.invalidate()  # Clear entire cache
                if cache_size > 0:
                    self.logger.debug(f"Cleared {cache_size} command cache entries")

            # Disconnect Qt signals to prevent crashes during destruction
            # Note: Only disconnect signals that have active connections
            try:
                # Standard library imports
                import warnings

                # Suppress RuntimeWarning about disconnecting signals with no connections
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        category=RuntimeWarning,
                        message=".*Failed to disconnect.*"
                    )
                    if hasattr(self, "command_completed"):
                        self.command_completed.disconnect()
                    if hasattr(self, "command_failed"):
                        self.command_failed.disconnect()
            except (RuntimeError, TypeError):
                # Signals may already be disconnected or in invalid state
                pass

        except Exception as e:
            self.logger.warning(f"Error during resource cleanup: {e}")

        # Stage 5: Force garbage collection to clean up circular references
        try:
            # Standard library imports
            import gc

            gc.collect()
        except Exception as e:
            self.logger.debug(f"Error during garbage collection: {e}")

        status = "successful" if shutdown_successful else "with timeout"
        self.logger.info(f"ProcessPoolManager shutdown complete ({status})")


class ProcessMetrics:
    """Track process optimization metrics."""

    def __init__(self) -> None:
        """Initialize process metrics tracking."""
        super().__init__()
        self.subprocess_calls = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.python_operations = 0
        self.total_response_time = 0.0
        self.response_count = 0
        self.start_time = time.time()

    def update_response_time(self, time_ms: float) -> None:
        """Update response time metrics.

        Args:
            time_ms: Response time in milliseconds
        """
        self.total_response_time += time_ms
        self.response_count += 1

    def get_report(self) -> dict[str, int | float]:
        """Generate performance report.

        Returns:
            Dictionary with performance metrics
        """
        avg_response = (
            self.total_response_time / self.response_count
            if self.response_count > 0
            else 0
        )

        uptime = time.time() - self.start_time

        # Calculate cache hit rate
        total_cache_requests = self.cache_hits + self.cache_misses
        cache_hit_rate = (
            (self.cache_hits / total_cache_requests * 100)
            if total_cache_requests > 0
            else 0.0
        )

        return {
            "subprocess_calls": self.subprocess_calls,
            "python_operations": self.python_operations,
            "average_response_ms": avg_response,
            "uptime_seconds": uptime,
            "calls_per_minute": (self.subprocess_calls / uptime * 60)
            if uptime > 0
            else 0,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": cache_hit_rate,
        }


# Example usage
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Get singleton instance
    pool = ProcessPoolManager.get_instance()

    # Test workspace command with caching
    result1 = pool.execute_workspace_command("echo 'test'", cache_ttl=5)
    print(f"First call: {result1}")

    result2 = pool.execute_workspace_command("echo 'test'", cache_ttl=5)
    print(f"Second call (cached): {result2}")

    # Test batch execution
    commands = ["echo 'one'", "echo 'two'", "echo 'three'"]
    results = pool.batch_execute(commands)
    print(f"Batch results: {results}")

    # Test file finding with Python
    files = pool.find_files_python("/tmp", "*.txt")
    print(f"Found files: {files}")

    # Print metrics
    metrics = pool.get_metrics()
    print(f"\nMetrics: {metrics}")

    # Cleanup
    pool.shutdown()

    sys.exit(0)
