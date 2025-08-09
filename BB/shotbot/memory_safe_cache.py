"""Memory-safe cache management with automatic resource cleanup.

This module provides comprehensive memory management for caching with
automatic cleanup, memory pressure detection, and resource lifecycle management.
"""

import gc
import logging
import sys
import threading
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Optional, Tuple, TypeVar

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """Single cache entry with metadata."""

    key: str
    value: T
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    size_bytes: int = 0
    ttl_seconds: Optional[float] = None
    weak_ref: Optional[weakref.ref] = None

    def is_expired(self) -> bool:
        """Check if entry has expired based on TTL."""
        if self.ttl_seconds is None:
            return False
        age = (datetime.now() - self.created_at).total_seconds()
        return age > self.ttl_seconds

    def touch(self):
        """Update last accessed time and increment counter."""
        self.last_accessed = datetime.now()
        self.access_count += 1

    def get_age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return (datetime.now() - self.created_at).total_seconds()

    def get_idle_seconds(self) -> float:
        """Get time since last access in seconds."""
        return (datetime.now() - self.last_accessed).total_seconds()


class MemoryMonitor:
    """Monitor system memory usage and pressure."""

    def __init__(self):
        self._last_check = datetime.now()
        self._check_interval = timedelta(seconds=5)
        self._memory_threshold_percent = 80
        self._cached_info: Optional[Dict[str, Any]] = None

    def get_memory_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Get current memory usage information."""
        now = datetime.now()

        # Use cached info if recent
        if not force_refresh and self._cached_info:
            if now - self._last_check < self._check_interval:
                return self._cached_info

        try:
            import psutil

            process = psutil.Process()
            memory_info = process.memory_info()

            # System memory
            virtual_mem = psutil.virtual_memory()

            info = {
                "process_rss_mb": memory_info.rss / 1024 / 1024,
                "process_vms_mb": memory_info.vms / 1024 / 1024,
                "system_total_mb": virtual_mem.total / 1024 / 1024,
                "system_available_mb": virtual_mem.available / 1024 / 1024,
                "system_percent": virtual_mem.percent,
                "under_pressure": virtual_mem.percent > self._memory_threshold_percent,
            }

        except ImportError:
            # Fallback if psutil not available
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF)
            info = {
                "process_rss_mb": usage.ru_maxrss / 1024,  # Linux/Mac in KB
                "process_vms_mb": 0,  # Not available without psutil
                "system_total_mb": 0,
                "system_available_mb": 0,
                "system_percent": 0,
                "under_pressure": False,
            }

        self._cached_info = info
        self._last_check = now
        return info

    def is_under_pressure(self) -> bool:
        """Check if system is under memory pressure."""
        info = self.get_memory_info()
        return info["under_pressure"]

    def get_recommended_cache_size_mb(self) -> float:
        """Get recommended cache size based on available memory."""
        info = self.get_memory_info()
        available_mb = info.get("system_available_mb", 1024)

        # Use at most 10% of available memory for cache
        return min(available_mb * 0.1, 500)  # Cap at 500MB


class LRUCache(Generic[T]):
    """Thread-safe LRU cache with memory management."""

    def __init__(
        self,
        max_size: int = 1000,
        max_memory_mb: float = 100,
        ttl_seconds: Optional[float] = None,
        cleanup_interval_seconds: float = 60,
        size_calculator: Optional[Callable[[T], int]] = None,
    ):
        self.max_size = max_size
        self.max_memory_mb = max_memory_mb
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.size_calculator = size_calculator or self._default_size_calculator

        self._cache: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = threading.RLock()
        self._total_size_bytes = 0
        self._memory_monitor = MemoryMonitor()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expired": 0,
        }

    def _default_size_calculator(self, value: T) -> int:
        """Default size calculator for cache entries."""
        if isinstance(value, QPixmap):
            # Calculate QPixmap size
            if not value.isNull():
                # Approximate memory usage: width * height * bytes_per_pixel
                bytes_per_pixel = value.depth() // 8
                return value.width() * value.height() * bytes_per_pixel
            return 0
        elif isinstance(value, (str, bytes)):
            return len(value)
        elif isinstance(value, (list, dict)):
            # Rough estimate
            return sys.getsizeof(value)
        else:
            return sys.getsizeof(value)

    def get(self, key: str) -> Optional[T]:
        """Get value from cache."""
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats["misses"] += 1
                return None

            # Check expiration
            if entry.is_expired():
                self._remove_entry(key)
                self._stats["expired"] += 1
                self._stats["misses"] += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.touch()
            self._stats["hits"] += 1

            return entry.value

    def put(
        self,
        key: str,
        value: T,
        ttl_seconds: Optional[float] = None,
        size_hint: Optional[int] = None,
    ) -> bool:
        """Put value in cache."""
        with self._lock:
            # Calculate size
            size_bytes = size_hint or self.size_calculator(value)

            # Check memory constraints
            max_memory_bytes = self.max_memory_mb * 1024 * 1024
            if size_bytes > max_memory_bytes:
                logger.warning(
                    f"Item {key} too large ({size_bytes} bytes) for cache "
                    f"(max {max_memory_bytes} bytes)"
                )
                return False

            # Remove existing entry if present
            if key in self._cache:
                self._remove_entry(key)

            # Evict entries if needed
            self._evict_if_needed(size_bytes)

            # Create new entry
            entry = CacheEntry(
                key=key,
                value=value,
                size_bytes=size_bytes,
                ttl_seconds=ttl_seconds or self.ttl_seconds,
            )

            # Add to cache
            self._cache[key] = entry
            self._total_size_bytes += size_bytes

            return True

    def _remove_entry(self, key: str):
        """Remove entry from cache (must be called under lock)."""
        if key in self._cache:
            entry = self._cache.pop(key)
            self._total_size_bytes -= entry.size_bytes

            # Clean up resources if needed
            if isinstance(entry.value, QPixmap):
                # QPixmap cleanup handled by Qt
                pass

    def _evict_if_needed(self, needed_bytes: int):
        """Evict entries if cache is full or under memory pressure."""
        max_memory_bytes = self.max_memory_mb * 1024 * 1024

        # Check if under memory pressure
        if self._memory_monitor.is_under_pressure():
            # Evict 25% of cache when under pressure
            target_size = int(self._total_size_bytes * 0.75)
            self._evict_to_size(target_size)
            return

        # Evict based on size constraints
        while len(self._cache) >= self.max_size:
            self._evict_lru()

        # Evict based on memory constraints
        while self._total_size_bytes + needed_bytes > max_memory_bytes:
            if not self._evict_lru():
                break

    def _evict_lru(self) -> bool:
        """Evict least recently used entry."""
        if not self._cache:
            return False

        # Get least recently used (first item)
        key = next(iter(self._cache))
        self._remove_entry(key)
        self._stats["evictions"] += 1
        logger.debug(f"Evicted LRU entry: {key}")
        return True

    def _evict_to_size(self, target_bytes: int):
        """Evict entries until cache size is below target."""
        while self._total_size_bytes > target_bytes and self._cache:
            self._evict_lru()

    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            # Clean up resources
            for entry in self._cache.values():
                if isinstance(entry.value, QPixmap):
                    # QPixmap cleanup handled by Qt
                    pass

            self._cache.clear()
            self._total_size_bytes = 0
            logger.info("Cache cleared")

    def cleanup_expired(self) -> int:
        """Remove expired entries from cache."""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items() if entry.is_expired()
            ]

            for key in expired_keys:
                self._remove_entry(key)
                self._stats["expired"] += 1

            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired entries")

            return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            hit_rate = 0
            if self._stats["hits"] + self._stats["misses"] > 0:
                hit_rate = self._stats["hits"] / (
                    self._stats["hits"] + self._stats["misses"]
                )

            return {
                **self._stats,
                "size": len(self._cache),
                "memory_mb": self._total_size_bytes / 1024 / 1024,
                "hit_rate": hit_rate,
            }


class QPixmapCache(QObject):
    """Specialized cache for QPixmap objects with automatic cleanup."""

    # Signals
    cache_cleared = Signal()
    memory_pressure_detected = Signal()

    def __init__(
        self,
        max_size: int = 200,
        max_memory_mb: float = 100,
        ttl_seconds: float = 1800,  # 30 minutes
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)

        self._cache = LRUCache[QPixmap](
            max_size=max_size,
            max_memory_mb=max_memory_mb,
            ttl_seconds=ttl_seconds,
            size_calculator=self._calculate_pixmap_size,
        )

        self._weak_refs: Dict[str, weakref.ref] = {}
        self._lock = threading.RLock()

        # Cleanup timer
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(60000)  # Every minute

        # Memory pressure timer
        self._pressure_timer = QTimer(self)
        self._pressure_timer.timeout.connect(self._check_memory_pressure)
        self._pressure_timer.start(10000)  # Every 10 seconds

    def _calculate_pixmap_size(self, pixmap: QPixmap) -> int:
        """Calculate memory size of a QPixmap."""
        if pixmap.isNull():
            return 0

        # Calculate based on dimensions and depth
        bytes_per_pixel = pixmap.depth() // 8
        size = pixmap.width() * pixmap.height() * bytes_per_pixel

        # Add overhead estimate (metadata, Qt internals)
        overhead = 1024  # 1KB overhead estimate
        return size + overhead

    def get_pixmap(self, key: str) -> Optional[QPixmap]:
        """Get pixmap from cache."""
        with self._lock:
            # Try strong reference first
            pixmap = self._cache.get(key)
            if pixmap and not pixmap.isNull():
                return pixmap

            # Try weak reference
            weak_ref = self._weak_refs.get(key)
            if weak_ref:
                pixmap = weak_ref()
                if pixmap and not pixmap.isNull():
                    # Promote back to strong reference
                    self._cache.put(key, pixmap)
                    return pixmap
                else:
                    # Weak reference is dead
                    del self._weak_refs[key]

            return None

    def cache_pixmap(
        self,
        key: str,
        pixmap: QPixmap,
        ttl_seconds: Optional[float] = None,
        weak_only: bool = False,
    ) -> bool:
        """Cache a pixmap with optional weak reference fallback."""
        if pixmap.isNull():
            logger.warning(f"Attempted to cache null pixmap for key: {key}")
            return False

        with self._lock:
            if weak_only:
                # Store only as weak reference
                self._weak_refs[key] = weakref.ref(pixmap)
                return True
            else:
                # Try to store as strong reference
                success = self._cache.put(key, pixmap, ttl_seconds)

                if not success:
                    # Fallback to weak reference if cache is full
                    self._weak_refs[key] = weakref.ref(pixmap)
                    logger.debug(f"Stored {key} as weak reference due to cache limits")

                return True

    def load_and_cache(
        self,
        key: str,
        file_path: Path,
        max_size: Optional[Tuple[int, int]] = None,
        ttl_seconds: Optional[float] = None,
    ) -> Optional[QPixmap]:
        """Load pixmap from file and cache it."""
        # Check if already cached
        cached = self.get_pixmap(key)
        if cached:
            return cached

        # Load from file
        try:
            pixmap = QPixmap(str(file_path))
            if pixmap.isNull():
                logger.warning(f"Failed to load pixmap from: {file_path}")
                return None

            # Scale if needed
            if max_size and (
                pixmap.width() > max_size[0] or pixmap.height() > max_size[1]
            ):
                from PySide6.QtCore import Qt

                pixmap = pixmap.scaled(
                    max_size[0],
                    max_size[1],
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            # Cache it
            self.cache_pixmap(key, pixmap, ttl_seconds)
            return pixmap

        except Exception as e:
            logger.error(f"Error loading pixmap from {file_path}: {e}")
            return None

    def _periodic_cleanup(self):
        """Periodic cleanup of expired entries and dead weak references."""
        with self._lock:
            # Clean expired entries
            expired_count = self._cache.cleanup_expired()

            # Clean dead weak references
            dead_keys = [
                key
                for key, ref in self._weak_refs.items()
                if ref() is None or ref().isNull()
            ]

            for key in dead_keys:
                del self._weak_refs[key]

            if expired_count > 0 or dead_keys:
                logger.debug(
                    f"Cleaned up {expired_count} expired entries and "
                    f"{len(dead_keys)} dead weak references"
                )

            # Force garbage collection if significant cleanup
            if expired_count > 10 or len(dead_keys) > 10:
                gc.collect()

    def _check_memory_pressure(self):
        """Check for memory pressure and act accordingly."""
        memory_monitor = MemoryMonitor()
        if memory_monitor.is_under_pressure():
            logger.warning("Memory pressure detected, reducing cache size")
            self.memory_pressure_detected.emit()

            with self._lock:
                # Reduce cache to 50% of current size
                target_size = len(self._cache._cache) // 2
                while len(self._cache._cache) > target_size:
                    self._cache._evict_lru()

                # Convert some strong references to weak
                entries_to_weaken = list(self._cache._cache.items())[:10]
                for key, entry in entries_to_weaken:
                    if not entry.value.isNull():
                        self._weak_refs[key] = weakref.ref(entry.value)
                        self._cache._remove_entry(key)

            # Force garbage collection
            gc.collect()

    def clear(self):
        """Clear all cached pixmaps."""
        with self._lock:
            self._cache.clear()
            self._weak_refs.clear()

        self.cache_cleared.emit()

        # Force garbage collection
        gc.collect()

        logger.info("Pixmap cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            stats = self._cache.get_stats()
            stats["weak_refs"] = len(self._weak_refs)
            stats["alive_weak_refs"] = sum(
                1
                for ref in self._weak_refs.values()
                if ref() is not None and not ref().isNull()
            )
            return stats


class ResourceManager(QObject):
    """Central resource manager with automatic cleanup."""

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._resources: Dict[str, Any] = {}
        self._cleaners: Dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._shutdown = False

        # Cleanup timer
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(30000)  # Every 30 seconds

    def register_resource(
        self,
        key: str,
        resource: Any,
        cleanup_func: Optional[Callable[[Any], None]] = None,
    ):
        """Register a resource for management."""
        with self._lock:
            if key in self._resources:
                # Clean up existing resource
                self._cleanup_resource(key)

            self._resources[key] = resource
            if cleanup_func:
                self._cleaners[key] = cleanup_func

    def get_resource(self, key: str) -> Optional[Any]:
        """Get a registered resource."""
        with self._lock:
            return self._resources.get(key)

    def release_resource(self, key: str) -> bool:
        """Release and clean up a resource."""
        with self._lock:
            if key not in self._resources:
                return False

            self._cleanup_resource(key)
            return True

    def _cleanup_resource(self, key: str):
        """Clean up a single resource."""
        if key in self._resources:
            resource = self._resources.pop(key)

            # Call custom cleanup function if provided
            if key in self._cleaners:
                try:
                    self._cleaners[key](resource)
                except Exception as e:
                    logger.error(f"Error cleaning up resource {key}: {e}")
                del self._cleaners[key]

            # Default cleanup for known types
            if isinstance(resource, QPixmap):
                # QPixmap cleanup handled by Qt
                pass
            elif hasattr(resource, "close"):
                try:
                    resource.close()
                except Exception:
                    pass
            elif hasattr(resource, "cleanup"):
                try:
                    resource.cleanup()
                except Exception:
                    pass

    def _periodic_cleanup(self):
        """Periodic cleanup of resources."""
        if self._shutdown:
            return

        # Check memory pressure
        memory_monitor = MemoryMonitor()
        if memory_monitor.is_under_pressure():
            logger.warning("Memory pressure detected in resource manager")
            # Could implement resource prioritization here

        # Force garbage collection periodically
        gc.collect()

    def shutdown(self):
        """Shutdown and clean up all resources."""
        self._shutdown = True
        self._cleanup_timer.stop()

        with self._lock:
            # Clean up all resources
            keys = list(self._resources.keys())
            for key in keys:
                self._cleanup_resource(key)

        logger.info("Resource manager shutdown complete")
