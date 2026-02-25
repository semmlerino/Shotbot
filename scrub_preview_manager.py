"""Scrub preview manager - coordinates scrub preview components.

This module provides the central coordinator for the plate scrub preview
feature, connecting event filter, frame provider, and delegate rendering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import ClassVar

from PySide6.QtCore import QModelIndex, QObject, QRect, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

from plate_frame_provider import PlateFrameProvider, PlateSource


logger = logging.getLogger(__name__)


@dataclass
class ScrubState:
    """Current scrub state for a shot.

    Attributes:
        shot_key: Unique identifier (show/sequence/shot)
        workspace_path: Shot workspace path for plate discovery
        frame_start: First frame number
        frame_end: Last frame number
        current_frame: Currently displayed frame
        plate_source: Discovered plate source (MOV/EXR)
        is_active: Whether scrub is currently active

    """

    shot_key: str
    workspace_path: str
    frame_start: int
    frame_end: int
    current_frame: int = 0
    plate_source: PlateSource | None = None
    is_active: bool = False
    _current_pixmap: QPixmap | None = field(default=None, repr=False)

    @property
    def current_pixmap(self) -> QPixmap | None:
        """Get the current frame's pixmap."""
        return self._current_pixmap

    @current_pixmap.setter
    def current_pixmap(self, value: QPixmap | None) -> None:
        """Set the current frame's pixmap."""
        self._current_pixmap = value

    @property
    def frame_count(self) -> int:
        """Get total frame count."""
        return self.frame_end - self.frame_start + 1

    def ratio_to_frame(self, ratio: float) -> int:
        """Convert x ratio (0.0-1.0) to frame number.

        Args:
            ratio: Horizontal position ratio

        Returns:
            Frame number

        """
        frame_offset = int(ratio * (self.frame_count - 1))
        return self.frame_start + frame_offset


class ScrubPreviewManager(QObject):
    """Manages plate scrub preview state and frame loading.

    This class coordinates:
    - Event filter signals for hover tracking
    - Frame provider for background extraction
    - Scrub state tracking per shot
    - Signal emission for delegate updates

    Signals:
        scrub_frame_ready: Frame ready for display (index, frame_num, pixmap)
        scrub_started: Scrub session started (index)
        scrub_ended: Scrub session ended (index)
        request_repaint: Request view to repaint an index (index)
    """

    scrub_frame_ready: ClassVar[Signal] = Signal(
        QModelIndex, int, QPixmap
    )  # index, frame, pixmap
    scrub_started: ClassVar[Signal] = Signal(QModelIndex)  # index
    scrub_ended: ClassVar[Signal] = Signal(QModelIndex)  # index
    request_repaint: ClassVar[Signal] = Signal(QModelIndex)  # index

    def __init__(
        self,
        parent: QObject | None = None,
        prefetch_radius: int = 10,
    ) -> None:
        """Initialize scrub preview manager.

        Args:
            parent: Parent QObject
            prefetch_radius: Number of frames to prefetch around current

        """
        super().__init__(parent)
        self._prefetch_radius: int = prefetch_radius

        # Frame provider for extraction
        self._frame_provider: PlateFrameProvider = PlateFrameProvider(self)
        _ = self._frame_provider.frame_ready.connect(self._on_frame_ready)
        _ = self._frame_provider.frame_failed.connect(self._on_frame_failed)

        # Active scrub states by index
        self._scrub_states: dict[int, ScrubState] = {}  # row -> ScrubState

        # Map shot_key to row for frame_ready callbacks
        self._key_to_row: dict[str, int] = {}

        # Current active index (only one can be active)
        self._active_index: QModelIndex | None = None

    @Slot(QModelIndex, QRect)
    def start_scrub(self, index: QModelIndex, rect: QRect) -> None:
        """Start scrub preview for an item.

        Called by event filter when hover delay expires.

        Args:
            index: Model index of the item
            rect: Visual rectangle of the item

        """
        if not index.isValid():
            logger.debug("start_scrub: invalid index")
            return

        # Get shot data from model
        from base_item_model import BaseItemRole

        model = index.model()
        # Note: model() theoretically never returns None per Qt docs, but check anyway
        if model is None:  # type: ignore[reportUnnecessaryComparison]
            logger.debug("start_scrub: no model")
            return

        # Try to get the Shot object from the model
        shot_data = model.data(index, BaseItemRole.ObjectRole)
        if shot_data is None:
            logger.info(f"start_scrub: No shot data for index {index.row()}")
            return

        # Extract shot info
        shot_key = self._get_shot_key(shot_data)
        workspace_path = self._get_workspace_path(shot_data)
        frame_start, frame_end = self._get_frame_range(shot_data)

        logger.info(f"start_scrub: {shot_key}, frames {frame_start}-{frame_end}, workspace: {workspace_path}")

        if frame_start is None or frame_end is None:
            logger.info(f"start_scrub: No frame range for {shot_key}")
            return

        # End any existing scrub
        if self._active_index is not None and self._active_index != index:
            self.end_scrub(self._active_index)

        # Discover plate source
        plate_source = self._frame_provider.discover_plate_source(workspace_path)
        if plate_source is None:
            logger.info(f"start_scrub: No plate source for {shot_key} at {workspace_path}")
            return

        logger.info(f"start_scrub: Found plate source {plate_source.source_type} at {plate_source.source_path}")

        # Create scrub state
        state = ScrubState(
            shot_key=shot_key,
            workspace_path=workspace_path,
            frame_start=frame_start,
            frame_end=frame_end,
            current_frame=frame_start,
            plate_source=plate_source,
            is_active=True,
        )

        row = index.row()
        self._scrub_states[row] = state
        self._key_to_row[shot_key] = row
        self._active_index = index

        logger.debug(f"Started scrub for {shot_key} (frames {frame_start}-{frame_end})")

        # Emit scrub started
        self.scrub_started.emit(index)

        # Start prefetching from first frame
        self._frame_provider.prefetch_frames(
            shot_key, plate_source, frame_start, self._prefetch_radius
        )

    @Slot(QModelIndex, float)
    def update_scrub_position(self, index: QModelIndex, x_ratio: float) -> None:
        """Update scrub position based on mouse x ratio.

        Called by event filter as mouse moves.

        Args:
            index: Model index of the item
            x_ratio: Horizontal position ratio (0.0-1.0)

        """
        if not index.isValid():
            return

        row = index.row()
        state = self._scrub_states.get(row)
        if state is None or not state.is_active:
            return

        # Calculate target frame
        target_frame = state.ratio_to_frame(x_ratio)

        if target_frame == state.current_frame:
            return

        old_frame = state.current_frame
        state.current_frame = target_frame

        # Check if frame is cached
        if self._frame_provider.has_cached_frame(state.shot_key, target_frame):
            # Get cached frame and update pixmap
            image = self._frame_provider.get_cached_frame(state.shot_key, target_frame)
            if image is not None:
                state.current_pixmap = QPixmap.fromImage(image)
                self.scrub_frame_ready.emit(index, target_frame, state.current_pixmap)
                self.request_repaint.emit(index)
                logger.debug(f"update_scrub_position: frame {target_frame} CACHED, displaying")
            else:
                logger.debug(f"update_scrub_position: frame {target_frame} has_cached=True but get_cached=None")
        else:
            # Request extraction for the target frame
            logger.debug(f"update_scrub_position: frame {old_frame}->{target_frame} NOT cached, requesting extraction")
            if state.plate_source is not None:
                self._frame_provider.extract_frame(
                    state.shot_key, state.plate_source, target_frame
                )
                # Also prefetch nearby frames
                self._frame_provider.prefetch_frames(
                    state.shot_key,
                    state.plate_source,
                    target_frame,
                    self._prefetch_radius,
                )

            # Show the nearest cached frame while waiting for extraction
            # This provides visual feedback during scrubbing even when frames aren't ready
            nearest_frame = self._find_nearest_cached_frame(state, target_frame)
            if nearest_frame is not None:
                image = self._frame_provider.get_cached_frame(state.shot_key, nearest_frame)
                if image is not None:
                    state.current_pixmap = QPixmap.fromImage(image)
                    # Emit with target_frame (for frame indicator) but show nearest cached frame
                    self.scrub_frame_ready.emit(index, target_frame, state.current_pixmap)
                    self.request_repaint.emit(index)
                    logger.debug(f"update_scrub_position: showing nearest cached frame {nearest_frame} while waiting for {target_frame}")

    @Slot(QModelIndex)
    def end_scrub(self, index: QModelIndex) -> None:
        """End scrub preview for an item.

        Called by event filter when mouse leaves.

        Args:
            index: Model index of the item

        """
        if not index.isValid():
            return

        row = index.row()
        state = self._scrub_states.get(row)

        if state is not None:
            state.is_active = False
            state.current_pixmap = None
            _ = self._key_to_row.pop(state.shot_key, None)
            del self._scrub_states[row]

            logger.debug(f"Ended scrub for {state.shot_key}")

        if self._active_index is not None and self._active_index.row() == row:
            self._active_index = None

        # Emit scrub ended
        self.scrub_ended.emit(index)
        self.request_repaint.emit(index)

    def get_scrub_state(self, index: QModelIndex) -> ScrubState | None:
        """Get scrub state for an index.

        Args:
            index: Model index

        Returns:
            ScrubState if scrubbing, None otherwise

        """
        if not index.isValid():
            return None
        return self._scrub_states.get(index.row())

    def is_scrubbing(self, index: QModelIndex) -> bool:
        """Check if an index is currently being scrubbed.

        Args:
            index: Model index

        Returns:
            True if actively scrubbing

        """
        state = self.get_scrub_state(index)
        return state is not None and state.is_active

    def get_current_frame(self, index: QModelIndex) -> int | None:
        """Get current scrub frame for an index.

        Args:
            index: Model index

        Returns:
            Current frame number, or None if not scrubbing

        """
        state = self.get_scrub_state(index)
        if state is None or not state.is_active:
            return None
        return state.current_frame

    def get_current_pixmap(self, index: QModelIndex) -> QPixmap | None:
        """Get current scrub pixmap for an index.

        Args:
            index: Model index

        Returns:
            Current QPixmap, or None if not available

        """
        state = self.get_scrub_state(index)
        if state is None or not state.is_active:
            return None
        return state.current_pixmap

    def cleanup(self) -> None:
        """Clean up all scrub states and caches."""
        # End all active scrubs
        for row in list(self._scrub_states.keys()):
            state = self._scrub_states[row]
            state.is_active = False
            state.current_pixmap = None

        self._scrub_states.clear()
        self._key_to_row.clear()
        self._active_index = None

        # Clear frame provider caches
        self._frame_provider.clear_all_caches()

    def _find_nearest_cached_frame(self, state: ScrubState, target_frame: int) -> int | None:
        """Find the nearest cached frame to the target frame.

        Args:
            state: Current scrub state
            target_frame: The frame we're trying to display

        Returns:
            Nearest cached frame number, or None if no frames are cached

        """
        cached_frames = self._frame_provider.get_cached_frames(state.shot_key)
        if not cached_frames:
            return None

        # Find the closest frame
        min_distance = float("inf")
        nearest = None
        for frame in cached_frames:
            distance = abs(frame - target_frame)
            if distance < min_distance:
                min_distance = distance
                nearest = frame

        return nearest

    def _on_frame_ready(self, shot_key: str, frame: int, image: QImage) -> None:
        """Handle frame extraction completion.

        Args:
            shot_key: Shot identifier
            frame: Frame number
            image: Extracted QImage

        """
        row = self._key_to_row.get(shot_key)
        if row is None:
            logger.debug(f"_on_frame_ready: {shot_key}:{frame} - no row mapping")
            return

        state = self._scrub_states.get(row)
        if state is None or not state.is_active:
            logger.debug(f"_on_frame_ready: {shot_key}:{frame} - state inactive or None")
            return

        # Only update if this is the current frame
        if frame == state.current_frame:
            pixmap = QPixmap.fromImage(image)
            state.current_pixmap = pixmap

            # Emit signal for delegate
            if self._active_index is not None:
                self.scrub_frame_ready.emit(self._active_index, frame, pixmap)
                self.request_repaint.emit(self._active_index)
                logger.debug(f"_on_frame_ready: {shot_key}:{frame} - DISPLAYED (matches current)")
        else:
            # Frame was extracted but user has moved on - it's now cached for later
            logger.debug(f"_on_frame_ready: {shot_key}:{frame} - CACHED ONLY (current is {state.current_frame})")

    def _on_frame_failed(self, shot_key: str, frame: int, error: str) -> None:
        """Handle frame extraction failure.

        Args:
            shot_key: Shot identifier
            frame: Frame number
            error: Error message

        """
        logger.debug(f"Frame extraction failed for {shot_key}:{frame} - {error}")

    def _get_shot_key(self, shot_data: object) -> str:
        """Extract shot key from shot data.

        Args:
            shot_data: Shot object or ThreeDEScene

        Returns:
            Unique shot key string

        """
        # Handle Shot
        if hasattr(shot_data, "show") and hasattr(shot_data, "sequence"):
            show = getattr(shot_data, "show", "")
            sequence = getattr(shot_data, "sequence", "")
            shot = getattr(shot_data, "shot", "")
            return f"{show}/{sequence}/{shot}"

        # Fallback
        return str(id(shot_data))

    def _get_workspace_path(self, shot_data: object) -> str:
        """Extract workspace path from shot data.

        Args:
            shot_data: Shot object or ThreeDEScene

        Returns:
            Workspace path string

        """
        if hasattr(shot_data, "workspace_path"):
            return str(getattr(shot_data, "workspace_path", ""))
        return ""

    def _get_frame_range(self, shot_data: object) -> tuple[int | None, int | None]:
        """Extract frame range from shot data.

        Args:
            shot_data: Shot object or ThreeDEScene

        Returns:
            Tuple of (frame_start, frame_end)

        """
        frame_start = getattr(shot_data, "frame_start", None)
        frame_end = getattr(shot_data, "frame_end", None)
        return frame_start, frame_end
