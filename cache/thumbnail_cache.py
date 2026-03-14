"""Thumbnail caching with stat result LRU cache.

Manages persistent JPEG thumbnails derived from source images (EXR, PNG, JPEG,
MOV frame extraction). Thumbnails do not expire — they persist until manually
cleared.

Thread Safety:
- QMutex (self._lock): Guards the in-process stat result LRU cache.
  Image processing and file I/O happen outside the lock to reduce contention.
"""

from __future__ import annotations

# Standard library imports
import contextlib
import time
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, final

# Third-party imports
from PIL import Image
from PySide6.QtCore import QMutex, QMutexLocker, QObject, QRunnable, Qt, Signal

# Local application imports
from exceptions import ThumbnailError
from logging_mixin import LoggingMixin
from runnable_tracker import TrackedQRunnable
from typing_compat import override


if TYPE_CHECKING:
    from PySide6.QtGui import QImage

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

THUMBNAIL_SIZE = 256
THUMBNAIL_QUALITY = 85
STAT_CACHE_TTL = 2.0          # Cache stat results for 2 seconds to reduce filesystem I/O
STAT_CACHE_MAX_SIZE = 1000    # Maximum entries in stat cache (LRU eviction)


# ---------------------------------------------------------------------------
# Background loader helpers
# ---------------------------------------------------------------------------

@final
class ThumbnailCacheLoaderSignals(QObject):
    """Signals for ThumbnailCacheLoader."""

    loaded = Signal(str, str, str, Path)  # show, sequence, shot, cache_path
    failed = Signal(str, str, str, str)   # show, sequence, shot, error_message


@final
class ThumbnailCacheLoader(TrackedQRunnable):
    """Background thumbnail cache loader — caches a source thumbnail via ThumbnailCache."""

    def __init__(
        self,
        cache: ThumbnailCache,
        source_path: Path | str,
        show: str,
        sequence: str,
        shot: str,
    ) -> None:
        super().__init__(auto_delete=True)
        self.cache_manager = cache
        self.source_path = source_path
        self.show = show
        self.sequence = sequence
        self.shot = shot
        self.signals = ThumbnailCacheLoaderSignals()

    @override
    def _do_work(self) -> None:
        try:
            result = self.cache_manager.cache_thumbnail(
                self.source_path, self.show, self.sequence, self.shot
            )
            if result:
                self.signals.loaded.emit(self.show, self.sequence, self.shot, result)
            else:
                self.signals.failed.emit(
                    self.show, self.sequence, self.shot, "cache_thumbnail returned None"
                )
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(self.show, self.sequence, self.shot, str(e))


# ---------------------------------------------------------------------------
# ThumbnailCache
# ---------------------------------------------------------------------------

@final
class ThumbnailCache(LoggingMixin):
    """Thumbnail caching with stat result LRU cache."""

    def __init__(self, cache_dir: Path) -> None:
        """Initialise thumbnail cache.

        Args:
            cache_dir: Root cache directory. Thumbnails are stored under
                       ``cache_dir / "thumbnails"``.

        """
        # Thread safety — guards _stat_cache only
        self._lock = QMutex()

        # Stat result LRU cache: {path_str: (size, mtime, cache_time)}
        self._stat_cache: OrderedDict[str, tuple[int, float, float]] = OrderedDict()

        self.thumbnails_dir = cache_dir / "thumbnails"
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_file_stat_cached(self, path: Path) -> tuple[int, float] | None:
        """Get file size and mtime with caching to reduce filesystem I/O.

        Uses LRU eviction to prevent unbounded memory growth. Cache is limited
        to STAT_CACHE_MAX_SIZE entries, evicting oldest when full.

        Args:
            path: File path to stat

        Returns:
            Tuple of (size, mtime) or None if file doesn't exist or is inaccessible

        """
        path_str = str(path)
        current_time = time.time()

        # Check cache first (inside lock for thread safety)
        with QMutexLocker(self._lock):
            if path_str in self._stat_cache:
                size, mtime, cache_time = self._stat_cache[path_str]
                # Return cached result if still valid
                if current_time - cache_time < STAT_CACHE_TTL:
                    # Move to end (mark as recently used for LRU)
                    self._stat_cache.move_to_end(path_str)
                    return (size, mtime)
                # Expired - will re-stat below
                del self._stat_cache[path_str]

        # Cache miss or expired - do actual stat
        try:
            stat_result = path.stat()
            size = stat_result.st_size
            mtime = stat_result.st_mtime

            # Cache the result with LRU eviction (inside lock for thread safety)
            with QMutexLocker(self._lock):
                # Evict oldest entries if cache is full
                while len(self._stat_cache) >= STAT_CACHE_MAX_SIZE:
                    _ = self._stat_cache.popitem(last=False)  # Remove oldest (first)

                self._stat_cache[path_str] = (size, mtime, current_time)

            return (size, mtime)

        except (OSError, FileNotFoundError):
            # File doesn't exist or is inaccessible
            return None

    def _pil_to_thumbnail(self, source: Path, output: Path) -> None:
        """Resize source image to JPEG thumbnail at output path.

        Uses atomic temp-file-then-rename pattern for crash safety.

        Args:
            source: Source image path
            output: Output thumbnail path

        """
        temp_path = output.with_suffix(".tmp")
        try:
            with Image.open(source) as img:
                img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
                img.convert("RGB").save(temp_path, "JPEG", quality=THUMBNAIL_QUALITY)
            _ = temp_path.replace(output)
        except Exception:
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            raise

    def _process_standard_thumbnail(self, source: Path, output: Path) -> Path:
        """Process standard image formats to thumbnail.

        Falls back to MOV frame extraction when PIL cannot read the source
        (e.g., EXR files). Raises ThumbnailError if both paths fail.

        Args:
            source: Source image path
            output: Output thumbnail path

        Returns:
            Path to created thumbnail

        """
        try:
            self._pil_to_thumbnail(source, output)
            self.logger.debug(f"Created thumbnail: {output}")
            return output
        except Exception as e:
            self.logger.debug(f"PIL thumbnail processing failed: {e}")

            # Try MOV fallback if PIL can't read the image (e.g., EXR files)
            self.logger.debug(f"Attempting MOV fallback for {source.name}")
            fallback_result = self._try_mov_fallback(source, output)
            if fallback_result is not None:
                return fallback_result

            # If MOV fallback didn't work, raise original error
            self.logger.exception("PIL thumbnail processing failed and MOV fallback unavailable")
            msg = f"Failed to process thumbnail: {e}"
            raise ThumbnailError(msg) from e

    def _try_mov_fallback(self, source: Path, output: Path) -> Path | None:
        """Attempt to create a thumbnail via MOV frame extraction.

        Used as a fallback when PIL cannot read the source image directly
        (e.g., EXR files). Looks for a sibling MOV file, extracts one frame,
        then processes that frame into a JPEG thumbnail.

        Args:
            source: Original source image path (used to locate a sibling MOV)
            output: Desired thumbnail output path

        Returns:
            Path to the created thumbnail on success, or None on any failure

        """
        from file_discovery import FileDiscovery
        from utils import ImageUtils

        mov_path = FileDiscovery.find_mov_file_for_path(source)
        if not mov_path:
            self.logger.debug(f"No MOV file found for fallback: {source}")
            return None

        self.logger.debug(f"Found MOV file for fallback: {mov_path.name}")
        extracted_frame = ImageUtils.extract_frame_from_mov(mov_path)

        try:
            if not (extracted_frame and extracted_frame.exists()):
                self.logger.debug("MOV frame extraction failed")
                return None

            self.logger.info(f"Successfully extracted frame from MOV: {mov_path.name}")

            # Process the extracted JPEG frame
            try:
                self._pil_to_thumbnail(extracted_frame, output)
                self.logger.debug(f"Created thumbnail from MOV fallback: {output}")
                return output
            except Exception as fallback_error:  # noqa: BLE001
                self.logger.error(f"Failed to process MOV fallback frame: {fallback_error}")
                return None
        finally:
            # Always clean up extracted frame temp file
            if extracted_frame and extracted_frame.exists():
                with contextlib.suppress(Exception):
                    extracted_frame.unlink()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cached_thumbnail(self, show: str, sequence: str, shot: str) -> Path | None:
        """Get path to cached thumbnail if it exists.

        Thumbnails are persistent and do not expire - they're only regenerated
        when manually cleared by the user.

        Uses cached stat results to reduce filesystem I/O overhead.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to thumbnail or None if not cached

        """
        # Compute path (no lock needed for this)
        cache_path = self.thumbnails_dir / show / sequence / f"{shot}_thumb.jpg"

        # Use cached stat to check if file exists and has content
        stat_result = self._get_file_stat_cached(cache_path)
        if stat_result is not None:
            size, _ = stat_result
            # Return path only if file has content (size > 0)
            if size > 0:
                return cache_path

        return None

    def cache_thumbnail(
        self,
        source_path: str | Path,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Cache a thumbnail from source path.

        Optimized: Lock scope reduced to minimize contention. Most operations
        (path computation, file I/O, image processing) happen outside the lock.

        Args:
            source_path: Source image path
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to cached thumbnail or None on error

        """
        source_path_obj = (
            Path(source_path) if isinstance(source_path, str) else source_path
        )

        # Validate parameters (no lock needed)
        if not all([show, sequence, shot]):
            error_msg = "Missing required parameters for thumbnail caching"
            self.logger.error(error_msg)
            raise ThumbnailError(
                error_msg,
                details={
                    "source_path": str(source_path),
                    "show": show,
                    "sequence": sequence,
                    "shot": shot,
                },
            )

        # Check source exists (no lock needed)
        if not source_path_obj.exists():
            self.logger.warning(f"Source path does not exist: {source_path_obj}")
            return None

        # Compute paths (no lock needed)
        output_dir = self.thumbnails_dir / show / sequence
        output_path = output_dir / f"{shot}_thumb.jpg"

        # Check if already cached using our cached stat (no lock needed)
        stat_result = self._get_file_stat_cached(output_path)
        if stat_result is not None:
            size, _ = stat_result
            if size > 0:
                self.logger.debug(f"Using existing thumbnail: {output_path}")
                return output_path

        # Ensure directory exists (brief lock for thread safety)
        with QMutexLocker(self._lock):
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError):
                self.logger.exception("Failed to create cache directories")
                return None

        # Process thumbnail WITHOUT holding lock (I/O and CPU intensive)
        try:
            return self._process_standard_thumbnail(source_path_obj, output_path)
        except Exception:
            self.logger.exception("Failed to process thumbnail")
            return None

    def cache_thumbnail_direct(
        self,
        image: QImage,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Cache a thumbnail from QImage directly.

        Lock-minimized implementation: I/O and CPU work happen outside the lock.
        Only stat cache invalidation uses a brief lock acquisition.

        Args:
            image: QImage to cache
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to cached thumbnail or None on error

        """
        # Compute paths (no lock needed - deterministic)
        output_dir = self.thumbnails_dir / show / sequence
        output_path = output_dir / f"{shot}_thumb.jpg"
        temp_path = output_path.with_suffix(".tmp")

        try:
            # Create directory (no lock needed - idempotent with exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Scale if needed (no lock needed - pure computation on local copy)
            if image.width() > THUMBNAIL_SIZE or image.height() > THUMBNAIL_SIZE:
                image = image.scaled(
                    THUMBNAIL_SIZE,
                    THUMBNAIL_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            # Save to temp file (no lock needed - unique temp path per shot)
            if not image.save(str(temp_path), b"JPEG", THUMBNAIL_QUALITY):
                temp_path.unlink(missing_ok=True)
                self.logger.error(f"Failed to save QImage to: {output_path}")
                return None

            # Atomic rename (no lock needed - atomic on POSIX)
            _ = temp_path.replace(output_path)

            # Invalidate stat cache for immediate visibility (minimal lock)
            with QMutexLocker(self._lock):
                _ = self._stat_cache.pop(str(output_path), None)

            self.logger.debug(f"Cached QImage thumbnail: {output_path}")
            return output_path

        except Exception:
            # Clean up temp file on any error
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            self.logger.exception("QImage thumbnail caching failed")
            return None


def make_default_thumbnail_cache(base_dir: Path | None = None) -> ThumbnailCache:
    """Create a ThumbnailCache using the env-resolved default directory."""
    from cache._dir_resolver import resolve_default_cache_dir
    resolved = base_dir if base_dir is not None else resolve_default_cache_dir()
    resolved.mkdir(parents=True, exist_ok=True)
    return ThumbnailCache(resolved)
