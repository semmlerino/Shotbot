"""Unit tests for PlateFrameProvider - frame extraction for scrub preview.

Tests focus on:
- PlateSource dataclass behavior
- Frame extraction request deduplication
- Signal emission on frame completion
- Prefetch behavior
- Cache integration
- Error handling
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtGui import QImage

from plate_frame_provider import (
    FrameExtractionRunnable,
    FrameExtractionSignals,
    PlateFrameProvider,
    PlateSource,
)
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

pytestmark = [pytest.mark.unit, pytest.mark.qt]


class TestPlateSource:
    """Tests for PlateSource dataclass."""

    def test_plate_source_immutable(self) -> None:
        """Test PlateSource is frozen (immutable)."""
        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1100,
        )
        with pytest.raises(AttributeError):
            source.source_path = Path("/other/path")  # type: ignore[misc]

    def test_frame_to_time_converts_correctly(self) -> None:
        """Test frame number to time conversion."""
        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1100,
        )

        # Frame 1001 = 0.0 seconds
        assert source.frame_to_time(1001) == 0.0

        # Frame 1025 = 24 frames = 1.0 second at 24fps
        assert source.frame_to_time(1025) == pytest.approx(1.0)

        # Frame 1049 = 48 frames = 2.0 seconds at 24fps
        assert source.frame_to_time(1049) == pytest.approx(2.0)

    def test_frame_to_time_with_custom_fps(self) -> None:
        """Test frame to time with non-default fps."""
        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1100,
        )

        # Frame 1031 = 30 frames = 1.0 second at 30fps
        assert source.frame_to_time(1031, fps=30.0) == pytest.approx(1.0)

    def test_frame_to_time_with_no_frame_start(self) -> None:
        """Test frame_to_time returns 0.0 when frame_start is None."""
        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=None,
            frame_end=None,
        )
        assert source.frame_to_time(1050) == 0.0

    def test_get_exr_path_for_frame_mov_returns_none(self) -> None:
        """Test get_exr_path_for_frame returns None for MOV source."""
        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1100,
        )
        assert source.get_exr_path_for_frame(1050) is None

    def test_get_exr_path_for_frame_constructs_path(self) -> None:
        """Test get_exr_path_for_frame constructs correct EXR path."""
        source = PlateSource(
            source_path=Path("/shows/test/plate.1001.exr"),
            source_type="exr",
            frame_start=1001,
            frame_end=1100,
        )
        result = source.get_exr_path_for_frame(1050)
        assert result is not None
        assert result.name == "plate.1050.exr"
        assert result.parent == Path("/shows/test")

    def test_get_exr_path_with_underscore_separator(self) -> None:
        """Test EXR path with underscore separator."""
        source = PlateSource(
            source_path=Path("/shows/test/plate_1001.exr"),
            source_type="exr",
            frame_start=1001,
            frame_end=1100,
        )
        result = source.get_exr_path_for_frame(1050)
        assert result is not None
        assert result.name == "plate_1050.exr"

    def test_get_exr_path_preserves_padding(self) -> None:
        """Test EXR path preserves frame number padding."""
        # 4-digit padding
        source = PlateSource(
            source_path=Path("/shows/test/plate.1001.exr"),
            source_type="exr",
            frame_start=1001,
            frame_end=1100,
        )
        result = source.get_exr_path_for_frame(50)
        assert result is not None
        assert "0050" in result.name

        # 5-digit padding
        source5 = PlateSource(
            source_path=Path("/shows/test/plate.10001.exr"),
            source_type="exr",
            frame_start=10001,
            frame_end=10100,
        )
        result5 = source5.get_exr_path_for_frame(50)
        assert result5 is not None
        assert "00050" in result5.name

    def test_get_exr_path_no_match_returns_none(self) -> None:
        """Test EXR path returns None if pattern doesn't match."""
        source = PlateSource(
            source_path=Path("/shows/test/plate.exr"),  # No frame number
            source_type="exr",
            frame_start=1001,
            frame_end=1100,
        )
        assert source.get_exr_path_for_frame(1050) is None


class TestFrameExtractionSignals:
    """Tests for FrameExtractionSignals."""

    def test_signals_exist(self, qapp: QApplication) -> None:
        """Test that signals are properly defined."""
        signals = FrameExtractionSignals()
        assert hasattr(signals, "finished")
        assert hasattr(signals, "failed")


class TestFrameExtractionRunnable:
    """Tests for FrameExtractionRunnable."""

    def test_runnable_initialization(self, qapp: QApplication) -> None:
        """Test runnable is properly initialized."""
        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1100,
        )
        runnable = FrameExtractionRunnable(
            shot_key="test/seq/shot",
            frame=1050,
            plate_source=source,
            thumbnail_width=200,
        )

        assert runnable.shot_key == "test/seq/shot"
        assert runnable.frame == 1050
        assert runnable.plate_source == source
        assert runnable.thumbnail_width == 200
        assert runnable.signals is not None

    def test_runnable_auto_delete_disabled(self, qapp: QApplication) -> None:
        """Test autoDelete is False to preserve signals."""
        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1100,
        )
        runnable = FrameExtractionRunnable(
            shot_key="test/seq/shot",
            frame=1050,
            plate_source=source,
        )
        assert runnable.autoDelete() is False


class TestPlateFrameProvider:
    """Tests for PlateFrameProvider."""

    def test_initialization(self, qapp: QApplication) -> None:
        """Test provider is properly initialized."""
        provider = PlateFrameProvider()

        assert provider._thumbnail_width == 200  # Default
        assert provider._cache is not None
        assert provider._thread_pool is not None
        assert len(provider._pending_extractions) == 0
        assert len(provider._plate_sources) == 0

    def test_initialization_with_custom_params(self, qapp: QApplication) -> None:
        """Test provider with custom parameters."""
        provider = PlateFrameProvider(
            max_concurrent=8,
            thumbnail_width=300,
        )

        assert provider._thumbnail_width == 300

    def test_has_cached_frame_delegates_to_cache(self, qapp: QApplication) -> None:
        """Test has_cached_frame delegates to underlying cache."""
        provider = PlateFrameProvider()

        # Nothing cached initially
        assert not provider.has_cached_frame("test/shot", 1001)

        # Store directly in cache
        from PySide6.QtGui import QImage

        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        provider._cache.store("test/shot", 1001, image)

        assert provider.has_cached_frame("test/shot", 1001)

    def test_get_cached_frame_returns_cached_image(self, qapp: QApplication) -> None:
        """Test get_cached_frame returns image from cache."""
        provider = PlateFrameProvider()

        # Store in cache
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        image.fill(0xFFFF0000)
        provider._cache.store("test/shot", 1001, image)

        result = provider.get_cached_frame("test/shot", 1001)
        assert result is not None
        assert not result.isNull()

    def test_get_cached_frame_returns_none_if_not_cached(
        self, qapp: QApplication
    ) -> None:
        """Test get_cached_frame returns None for uncached frame."""
        provider = PlateFrameProvider()
        result = provider.get_cached_frame("test/shot", 1001)
        assert result is None

    def test_extract_frame_skips_if_already_cached(self, qapp: QApplication) -> None:
        """Test extract_frame emits signal immediately if cached."""
        provider = PlateFrameProvider()

        # Pre-cache the frame
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        provider._cache.store("test/shot", 1001, image)

        # Track signal emission
        signals_received: list[tuple[str, int]] = []

        def on_ready(shot_key: str, frame: int, img: QImage) -> None:
            signals_received.append((shot_key, frame))

        provider.frame_ready.connect(on_ready)

        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1100,
        )

        provider.extract_frame("test/shot", source, 1001)
        process_qt_events()

        # Should have emitted immediately from cache
        assert ("test/shot", 1001) in signals_received

    def test_extract_frame_skips_if_already_pending(self, qapp: QApplication) -> None:
        """Test extract_frame doesn't duplicate pending extractions."""
        provider = PlateFrameProvider()

        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1100,
        )

        # Manually add to pending
        provider._pending_extractions.add(("test/shot", 1001))

        # Track if new runnable is created
        initial_runnables = len(provider._active_runnables)

        provider.extract_frame("test/shot", source, 1001)

        # Should not have added new runnable
        assert len(provider._active_runnables) == initial_runnables

    def test_prefetch_frames_calls_extract_for_range(
        self, qapp: QApplication
    ) -> None:
        """Test prefetch_frames extracts frames around center."""
        provider = PlateFrameProvider()

        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1100,
        )

        # Mock extract_frame to track calls
        extracted_frames: list[int] = []

        def mock_extract(key: str, src: PlateSource, frame: int) -> None:
            extracted_frames.append(frame)

        provider.extract_frame = mock_extract  # type: ignore[method-assign]

        provider.prefetch_frames("test/shot", source, center_frame=1050, radius=3)

        # Should have called extract for 1047-1053
        assert set(extracted_frames) == {1047, 1048, 1049, 1050, 1051, 1052, 1053}

    def test_prefetch_frames_respects_frame_bounds(self, qapp: QApplication) -> None:
        """Test prefetch_frames doesn't go outside frame range."""
        provider = PlateFrameProvider()

        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=1001,
            frame_end=1010,
        )

        extracted_frames: list[int] = []

        def mock_extract(key: str, src: PlateSource, frame: int) -> None:
            extracted_frames.append(frame)

        provider.extract_frame = mock_extract  # type: ignore[method-assign]

        # Center near start
        provider.prefetch_frames("test/shot", source, center_frame=1003, radius=5)
        assert min(extracted_frames) >= 1001  # Respects start bound

        extracted_frames.clear()

        # Center near end
        provider.prefetch_frames("test/shot", source, center_frame=1008, radius=5)
        assert max(extracted_frames) <= 1010  # Respects end bound

    def test_prefetch_with_no_frame_range(self, qapp: QApplication) -> None:
        """Test prefetch_frames does nothing if no frame range."""
        provider = PlateFrameProvider()

        source = PlateSource(
            source_path=Path("/shows/test/plate.mov"),
            source_type="mov",
            frame_start=None,
            frame_end=None,
        )

        extracted_frames: list[int] = []

        def mock_extract(key: str, src: PlateSource, frame: int) -> None:
            extracted_frames.append(frame)

        provider.extract_frame = mock_extract  # type: ignore[method-assign]

        provider.prefetch_frames("test/shot", source, center_frame=1050, radius=5)

        assert len(extracted_frames) == 0

    def test_clear_shot_cache_clears_specific_shot(self, qapp: QApplication) -> None:
        """Test clear_shot_cache clears frames for specific shot."""
        provider = PlateFrameProvider()

        # Store frames for two shots
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        provider._cache.store("test/shot1", 1001, image)
        provider._cache.store("test/shot2", 1001, image)

        provider.clear_shot_cache("test/shot1")

        assert not provider.has_cached_frame("test/shot1", 1001)
        assert provider.has_cached_frame("test/shot2", 1001)

    def test_clear_all_caches_clears_everything(self, qapp: QApplication) -> None:
        """Test clear_all_caches clears all state."""
        provider = PlateFrameProvider()

        # Store various state
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        provider._cache.store("test/shot1", 1001, image)
        provider._plate_sources["path1"] = PlateSource(
            source_path=Path("/test"),
            source_type="mov",
        )
        provider._pending_extractions.add(("test", 1001))

        provider.clear_all_caches()

        assert not provider.has_cached_frame("test/shot1", 1001)
        assert len(provider._plate_sources) == 0
        assert len(provider._pending_extractions) == 0

    def test_get_cache_stats_returns_dict(self, qapp: QApplication) -> None:
        """Test get_cache_stats returns statistics dict."""
        provider = PlateFrameProvider()

        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        provider._cache.store("test/shot1", 1001, image)
        provider._cache.store("test/shot1", 1002, image)

        stats = provider.get_cache_stats()

        assert isinstance(stats, dict)
        assert stats["shot_count"] == 1
        assert stats["total_frames"] == 2

    def test_on_extraction_finished_caches_and_emits(
        self, qapp: QApplication
    ) -> None:
        """Test _on_extraction_finished caches frame and emits signal."""
        provider = PlateFrameProvider()

        # Add to pending
        provider._pending_extractions.add(("test/shot", 1001))

        # Track signal emission
        signals_received: list[tuple[str, int]] = []

        def on_ready(shot_key: str, frame: int, img: QImage) -> None:
            signals_received.append((shot_key, frame))

        provider.frame_ready.connect(on_ready)

        # Simulate extraction complete
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        provider._on_extraction_finished("test/shot", 1001, image)
        process_qt_events()

        # Should be cached
        assert provider.has_cached_frame("test/shot", 1001)

        # Should have emitted signal
        assert ("test/shot", 1001) in signals_received

        # Should be removed from pending
        assert ("test/shot", 1001) not in provider._pending_extractions

    def test_on_extraction_failed_emits_signal(self, qapp: QApplication) -> None:
        """Test _on_extraction_failed emits failure signal."""
        provider = PlateFrameProvider()

        # Add to pending
        provider._pending_extractions.add(("test/shot", 1001))

        # Track signal emission
        failures_received: list[tuple[str, int, str]] = []

        def on_failed(shot_key: str, frame: int, error: str) -> None:
            failures_received.append((shot_key, frame, error))

        provider.frame_failed.connect(on_failed)

        provider._on_extraction_failed("test/shot", 1001, "Test error")
        process_qt_events()

        # Should have emitted failure
        assert len(failures_received) == 1
        assert failures_received[0] == ("test/shot", 1001, "Test error")

        # Should be removed from pending
        assert ("test/shot", 1001) not in provider._pending_extractions


class TestDiscoverPlateSource:
    """Tests for plate source discovery (with mocked file operations)."""

    def test_discover_returns_cached_source(
        self, qapp: QApplication
    ) -> None:
        """Test discover_plate_source returns cached result."""
        provider = PlateFrameProvider()

        # Pre-cache a source
        cached_source = PlateSource(
            source_path=Path("/cached/plate.mov"),
            source_type="mov",
        )
        provider._plate_sources["/workspace/path"] = cached_source

        result = provider.discover_plate_source("/workspace/path")

        assert result == cached_source

    @patch("file_discovery.FileDiscovery.find_plate_mov_proxy")
    @patch("file_discovery.FileDiscovery.find_plate_exr_sequence")
    @patch("plate_frame_provider.utils_module.ImageUtils.get_mov_duration")
    def test_discover_finds_mov_proxy(
        self,
        mock_get_duration: MagicMock,
        mock_exr_seq: MagicMock,
        mock_mov_proxy: MagicMock,
        qapp: QApplication,
    ) -> None:
        """Test discover_plate_source finds MOV proxy."""
        provider = PlateFrameProvider()

        mov_path = Path("/shows/test/plate/v001/mov/plate.mov")
        mock_mov_proxy.return_value = mov_path
        mock_exr_seq.return_value = (None, 1001, 1100)
        mock_get_duration.return_value = 4.125

        result = provider.discover_plate_source("/workspace/path")

        assert result is not None
        assert result.source_type == "mov"
        assert result.source_path == mov_path
        assert result.frame_start == 1001
        assert result.frame_end == 1100

    @patch("file_discovery.FileDiscovery.find_plate_mov_proxy")
    @patch("file_discovery.FileDiscovery.find_plate_exr_sequence")
    def test_discover_falls_back_to_exr(
        self,
        mock_exr_seq: MagicMock,
        mock_mov_proxy: MagicMock,
        qapp: QApplication,
    ) -> None:
        """Test discover_plate_source falls back to EXR sequence."""
        provider = PlateFrameProvider()

        exr_path = Path("/shows/test/plate/v001/exr/plate.1001.exr")
        mock_mov_proxy.return_value = None
        mock_exr_seq.return_value = (exr_path, 1001, 1100)

        result = provider.discover_plate_source("/workspace/path")

        assert result is not None
        assert result.source_type == "exr"
        assert result.source_path == exr_path

    @patch("file_discovery.FileDiscovery.find_plate_mov_proxy")
    @patch("file_discovery.FileDiscovery.find_plate_exr_sequence")
    def test_discover_caches_none_if_not_found(
        self,
        mock_exr_seq: MagicMock,
        mock_mov_proxy: MagicMock,
        qapp: QApplication,
    ) -> None:
        """Test discover_plate_source caches None if no source found."""
        provider = PlateFrameProvider()

        mock_mov_proxy.return_value = None
        mock_exr_seq.return_value = (None, None, None)

        result = provider.discover_plate_source("/workspace/path")

        assert result is None
        # Should be cached as None
        assert "/workspace/path" in provider._plate_sources
        assert provider._plate_sources["/workspace/path"] is None

        # Second call should not query filesystem
        mock_mov_proxy.reset_mock()
        result2 = provider.discover_plate_source("/workspace/path")
        assert result2 is None
        mock_mov_proxy.assert_not_called()
