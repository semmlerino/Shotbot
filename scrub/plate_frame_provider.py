"""Plate frame extraction provider for scrub preview.

This module provides background frame extraction from plate MOV proxies
or EXR sequences for the scrubbing preview feature.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

import image_utils as utils_module
from scrub.scrub_frame_cache import ScrubFrameCache
from typing_compat import override


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlateSource:
    """Information about a plate source for frame extraction.

    Attributes:
        source_path: Path to MOV file or first EXR frame
        source_type: Either "mov" or "exr"
        frame_start: First frame number (for EXR sequences)
        frame_end: Last frame number (for EXR sequences)
        duration_seconds: Duration in seconds (for MOV files)

    """

    source_path: Path
    source_type: str  # "mov" or "exr"
    frame_start: int | None = None
    frame_end: int | None = None
    duration_seconds: float | None = None

    def frame_to_time(self, frame: int, fps: float = 24.0) -> float:
        """Convert frame number to time in seconds (for MOV sources).

        Args:
            frame: Frame number
            fps: Frames per second (default 24 for film)

        Returns:
            Time in seconds from start of video

        """
        if self.frame_start is None:
            return 0.0
        offset_frames = frame - self.frame_start
        return offset_frames / fps

    def get_exr_path_for_frame(self, frame: int) -> Path | None:
        """Get the EXR file path for a specific frame.

        Args:
            frame: Frame number

        Returns:
            Path to EXR file, or None if can't be determined

        """
        if self.source_type != "exr":
            return None

        # The source_path is the first EXR file
        # Replace the frame number in the filename
        name = self.source_path.name
        # Match patterns like .1001.exr or _1001.exr
        pattern = re.compile(r"[._](\d{4,})(\.exr)$", re.IGNORECASE)
        match = pattern.search(name)

        if not match:
            return None

        # Replace the frame number
        frame_str = str(frame).zfill(len(match.group(1)))
        new_name = name[: match.start() + 1] + frame_str + match.group(2)
        return self.source_path.parent / new_name


class FrameExtractionSignals(QObject):
    """Signals for frame extraction completion.

    Provides thread-safe communication from background extraction
    to the main thread via Qt signals.
    """

    finished: ClassVar[Signal] = Signal(str, int, QImage)  # shot_key, frame, image
    failed: ClassVar[Signal] = Signal(str, int, str)  # shot_key, frame, error


class FrameExtractionRunnable(QRunnable):
    """Background worker for extracting a single frame from a plate source."""

    def __init__(
        self,
        shot_key: str,
        frame: int,
        plate_source: PlateSource,
        thumbnail_width: int = 200,
    ) -> None:
        """Initialize frame extraction runnable.

        Args:
            shot_key: Unique identifier for the shot
            frame: Frame number to extract
            plate_source: PlateSource with extraction info
            thumbnail_width: Width to scale extracted frame to

        """
        super().__init__()
        self.shot_key: str = shot_key
        self.frame: int = frame
        self.plate_source: PlateSource = plate_source
        self.thumbnail_width: int = thumbnail_width
        self.signals: FrameExtractionSignals = FrameExtractionSignals()
        # CRITICAL: Do NOT use setAutoDelete(True) - signals must survive
        self.setAutoDelete(False)

    @override
    def run(self) -> None:
        """Execute frame extraction in background thread."""
        try:
            extracted_path: Path | None = None

            if self.plate_source.source_type == "mov":
                # Extract from MOV using time-based seeking
                time_seconds = self.plate_source.frame_to_time(self.frame)
                logger.debug(f"Extracting frame {self.frame} from MOV at {time_seconds:.2f}s: {self.plate_source.source_path}")
                # basedpyright can't resolve new ImageUtils methods (Python 3.13 compat)
                extracted_path = utils_module.ImageUtils.extract_frame_at_time(  # type: ignore[reportUnknownMemberType]
                    self.plate_source.source_path,
                    time_seconds,
                    width=self.thumbnail_width,
                )
            else:
                # Extract from EXR sequence
                exr_path = self.plate_source.get_exr_path_for_frame(self.frame)
                if exr_path and exr_path.exists():
                    logger.debug(f"Extracting frame {self.frame} from EXR: {exr_path}")
                    # basedpyright can't resolve new ImageUtils methods (Python 3.13 compat)
                    extracted_path = utils_module.ImageUtils.extract_frame_from_exr(  # type: ignore[reportUnknownMemberType]
                        exr_path,
                        width=self.thumbnail_width,
                    )
                else:
                    logger.debug(f"EXR path not found for frame {self.frame}: {exr_path}")

            if extracted_path is not None and extracted_path.exists():  # type: ignore[reportUnknownMemberType]
                # Load as QImage (thread-safe)
                image = QImage(str(extracted_path))  # type: ignore[reportUnknownArgumentType]
                if not image.isNull():
                    logger.debug(f"Frame {self.frame} extracted successfully: {extracted_path}")
                    self.signals.finished.emit(self.shot_key, self.frame, image)
                    # Clean up temp file
                    try:
                        extracted_path.unlink()  # type: ignore[reportUnusedCallResult]
                    except OSError:
                        pass
                    return
                logger.debug(f"Frame {self.frame} image is null from: {extracted_path}")

            logger.debug(f"Frame {self.frame} extraction failed - no path or path doesn't exist")
            self.signals.failed.emit(
                self.shot_key, self.frame, "Failed to extract frame"
            )

        except Exception as e:  # noqa: BLE001
            logger.debug(f"Frame {self.frame} extraction exception: {e}")
            self.signals.failed.emit(self.shot_key, self.frame, str(e))


class PlateFrameProvider(QObject):
    """Provides plate frames for scrub preview via background extraction.

    This class coordinates frame extraction from plate MOV proxies or
    EXR sequences, caching results for smooth scrubbing.

    Signals:
        frame_ready: Emitted when a frame is ready (shot_key, frame, QImage)
        frame_failed: Emitted when extraction fails (shot_key, frame, error)
    """

    frame_ready: ClassVar[Signal] = Signal(str, int, QImage)  # shot_key, frame, image
    frame_failed: ClassVar[Signal] = Signal(str, int, str)  # shot_key, frame, error

    def __init__(
        self,
        parent: QObject | None = None,
        max_concurrent: int = 8,
        thumbnail_width: int = 200,
    ) -> None:
        """Initialize plate frame provider.

        Args:
            parent: Parent QObject
            max_concurrent: Maximum concurrent extraction workers
            thumbnail_width: Width to scale extracted frames to

        """
        super().__init__(parent)
        self._thumbnail_width: int = thumbnail_width
        self._cache: ScrubFrameCache = ScrubFrameCache()
        self._thread_pool: QThreadPool = QThreadPool.globalInstance()
        self._thread_pool.setMaxThreadCount(max_concurrent)

        # Track active extractions to avoid duplicates
        self._pending_extractions: set[tuple[str, int]] = set()

        # Cache plate sources to avoid repeated discovery
        self._plate_sources: dict[str, PlateSource | None] = {}

        # Track runnables for cleanup
        self._active_runnables: list[FrameExtractionRunnable] = []

    def discover_plate_source(self, workspace_path: str) -> PlateSource | None:
        """Discover plate source (MOV proxy or EXR sequence) for a workspace.

        Prefers MOV proxy for faster extraction, falls back to EXR.

        Args:
            workspace_path: Shot workspace path

        Returns:
            PlateSource if found, None otherwise

        """
        # Lazy import to avoid circular import with utils -> file_discovery
        from file_discovery import FileDiscovery

        # Check cache first
        if workspace_path in self._plate_sources:
            return self._plate_sources[workspace_path]

        # Try to find MOV proxy first (preferred - faster extraction)
        mov_path = FileDiscovery.find_plate_mov_proxy(workspace_path)
        if mov_path:
            # Get duration for time-based seeking
            # type: ignore - basedpyright can't resolve new ImageUtils methods
            duration: float | None = utils_module.ImageUtils.get_mov_duration(mov_path)  # type: ignore[reportUnknownMemberType]

            # Try to get frame range from Shot or filesystem
            # For MOV, we'll use the EXR sequence to get frame range if available
            exr_info = FileDiscovery.find_plate_exr_sequence(workspace_path)
            frame_start = exr_info[1] or 1001
            frame_end = exr_info[2] or 1100

            source = PlateSource(
                source_path=mov_path,
                source_type="mov",
                frame_start=frame_start,
                frame_end=frame_end,
                duration_seconds=duration,  # type: ignore[reportUnknownArgumentType]
            )
            self._plate_sources[workspace_path] = source
            logger.debug(f"Found MOV proxy for {workspace_path}: {mov_path.name}")
            return source

        # Fall back to EXR sequence
        exr_path, frame_start, frame_end = FileDiscovery.find_plate_exr_sequence(
            workspace_path
        )
        if exr_path:
            source = PlateSource(
                source_path=exr_path,
                source_type="exr",
                frame_start=frame_start,
                frame_end=frame_end,
            )
            self._plate_sources[workspace_path] = source
            logger.debug(f"Found EXR sequence for {workspace_path}: {exr_path.name}")
            return source

        # No plate source found
        self._plate_sources[workspace_path] = None
        logger.debug(f"No plate source found for {workspace_path}")
        return None

    def get_cached_frame(self, shot_key: str, frame: int) -> QImage | None:
        """Get a cached frame if available (thread-safe).

        Args:
            shot_key: Unique identifier for the shot
            frame: Frame number

        Returns:
            QImage if cached, None otherwise

        """
        return self._cache.get_image(shot_key, frame)

    def has_cached_frame(self, shot_key: str, frame: int) -> bool:
        """Check if a frame is cached (thread-safe).

        Args:
            shot_key: Unique identifier for the shot
            frame: Frame number

        Returns:
            True if frame is cached

        """
        return self._cache.has_frame(shot_key, frame)

    def extract_frame(
        self,
        shot_key: str,
        plate_source: PlateSource,
        frame: int,
    ) -> None:
        """Request extraction of a single frame (async).

        Args:
            shot_key: Unique identifier for the shot
            plate_source: PlateSource with extraction info
            frame: Frame number to extract

        """
        # Skip if already cached
        if self._cache.has_frame(shot_key, frame):
            image = self._cache.get_image(shot_key, frame)
            if image:
                self.frame_ready.emit(shot_key, frame, image)
            return

        # Skip if already pending
        key = (shot_key, frame)
        if key in self._pending_extractions:
            return

        self._pending_extractions.add(key)

        # Create and start runnable
        runnable = FrameExtractionRunnable(
            shot_key=shot_key,
            frame=frame,
            plate_source=plate_source,
            thumbnail_width=self._thumbnail_width,
        )

        # Connect signals
        _ = runnable.signals.finished.connect(self._on_extraction_finished)
        _ = runnable.signals.failed.connect(self._on_extraction_failed)

        # Track runnable for cleanup
        self._active_runnables.append(runnable)

        # Start extraction
        self._thread_pool.start(runnable)

    def prefetch_frames(
        self,
        shot_key: str,
        plate_source: PlateSource,
        center_frame: int,
        radius: int = 5,
    ) -> None:
        """Prefetch frames around a center frame for smooth scrubbing.

        Args:
            shot_key: Unique identifier for the shot
            plate_source: PlateSource with extraction info
            center_frame: Frame to center prefetch around
            radius: Number of frames to prefetch on each side

        """
        if plate_source.frame_start is None or plate_source.frame_end is None:
            return

        start = max(plate_source.frame_start, center_frame - radius)
        end = min(plate_source.frame_end, center_frame + radius)

        for frame in range(start, end + 1):
            self.extract_frame(shot_key, plate_source, frame)

    def clear_shot_cache(self, shot_key: str) -> None:
        """Clear cached frames for a shot.

        Args:
            shot_key: Unique identifier for the shot

        """
        self._cache.clear_shot(shot_key)

    def clear_all_caches(self) -> None:
        """Clear all cached frames and plate sources."""
        self._cache.clear_all()
        self._plate_sources.clear()
        self._pending_extractions.clear()

    def get_cache_stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with cache size information

        """
        return self._cache.get_stats()

    def get_cached_frames(self, shot_key: str) -> list[int]:
        """Get list of cached frame numbers for a shot.

        Args:
            shot_key: Unique identifier for the shot

        Returns:
            List of cached frame numbers

        """
        return self._cache.get_cached_frames(shot_key)

    def _on_extraction_finished(
        self, shot_key: str, frame: int, image: QImage
    ) -> None:
        """Handle successful frame extraction.

        Args:
            shot_key: Unique identifier for the shot
            frame: Frame number
            image: Extracted QImage

        """
        # Remove from pending
        self._pending_extractions.discard((shot_key, frame))

        # Cache the result
        self._cache.store(shot_key, frame, image)

        # Emit signal
        self.frame_ready.emit(shot_key, frame, image)

        # Clean up runnable reference
        self._cleanup_finished_runnables()

    def _on_extraction_failed(self, shot_key: str, frame: int, error: str) -> None:
        """Handle failed frame extraction.

        Args:
            shot_key: Unique identifier for the shot
            frame: Frame number
            error: Error message

        """
        # Remove from pending
        self._pending_extractions.discard((shot_key, frame))

        # Emit signal
        self.frame_failed.emit(shot_key, frame, error)

        # Clean up runnable reference
        self._cleanup_finished_runnables()

    def _cleanup_finished_runnables(self) -> None:
        """Clean up references to finished runnables."""
        # Remove runnables that are no longer in the thread pool
        # This is a simple cleanup - just keep the list reasonable
        if len(self._active_runnables) > 100:
            self._active_runnables = self._active_runnables[-50:]
