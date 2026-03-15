"""Image processing utilities for ShotBot."""

from __future__ import annotations

# Standard library imports
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

# Local application imports
from config import Config
from logging_mixin import get_module_logger
from timeout_config import TimeoutConfig


if TYPE_CHECKING:
    from PySide6.QtCore import QSize

logger = get_module_logger(__name__)


def _make_temp_jpeg(prefix: str) -> Path:
    """Create a named temporary JPEG file and return its path.

    Opens and immediately closes the OS file descriptor so the path can be
    passed to external tools (FFmpeg, oiiotool) that need to write to it
    themselves.

    Args:
        prefix: Filename prefix for the temp file (e.g., "shotbot_thumb_")

    Returns:
        Path to the newly created (empty) temporary JPEG file

    """
    temp_fd, temp_path = tempfile.mkstemp(suffix=".jpg", prefix=prefix)
    os.close(temp_fd)
    return Path(temp_path)


class ImageUtils:
    """Utilities for image validation and processing."""

    @staticmethod
    def validate_image_dimensions(
        width: int,
        height: int,
        max_dimension: int | None = None,
        max_memory_mb: int | None = None,
    ) -> bool:
        """Validate image dimensions and estimated memory usage.

        Args:
            width: Image width in pixels
            height: Image height in pixels
            max_dimension: Maximum allowed dimension (uses Config.MAX_THUMBNAIL_DIMENSION_PX if None)
            max_memory_mb: Maximum estimated memory usage in MB (uses Config.MAX_THUMBNAIL_MEMORY_MB if None)

        Returns:
            True if dimensions are acceptable, False otherwise

        """
        if max_dimension is None:
            max_dimension = Config.MAX_THUMBNAIL_DIMENSION_PX
        if max_memory_mb is None:
            max_memory_mb = Config.MAX_THUMBNAIL_MEMORY_MB

        # Check individual dimensions
        if width > max_dimension or height > max_dimension:
            logger.warning(
                f"Image dimensions too large ({width}x{height} > {max_dimension})",
            )
            return False

        # Estimate memory usage (4 bytes per pixel for RGBA)
        estimated_memory_bytes = width * height * 4
        estimated_memory_mb = estimated_memory_bytes / (1024 * 1024)

        if estimated_memory_mb > max_memory_mb:
            logger.warning(
                f"Estimated image memory usage too high ({estimated_memory_mb:.1f}MB > {max_memory_mb}MB)",
            )
            return False

        return True

    @staticmethod
    def get_safe_dimensions_for_thumbnail(
        max_size: int | None = None,
    ) -> tuple[int, int]:
        """Get safe dimensions for thumbnail generation.

        Args:
            max_size: Maximum dimension for thumbnail (uses Config.CACHE_THUMBNAIL_SIZE if None)

        Returns:
            (width, height) tuple for safe thumbnail dimensions

        """
        if max_size is None:
            max_size = Config.CACHE_THUMBNAIL_SIZE
        return (max_size, max_size)

    @staticmethod
    def is_image_too_large_for_thumbnail(
        size: QSize,
        max_dimension: int,
    ) -> bool:
        """Check if an image is too large for thumbnail processing.

        Args:
            size: QSize object with width() and height() methods
            max_dimension: Maximum allowed dimension in pixels

        Returns:
            True if image is too large, False if it's acceptable

        """
        width = size.width()
        height = size.height()

        # Return True if image is too large (inverse of validate_image_dimensions)
        return not ImageUtils.validate_image_dimensions(
            width=width,
            height=height,
            max_dimension=max_dimension,
            max_memory_mb=Config.MAX_THUMBNAIL_MEMORY_MB,
        )

    @staticmethod
    def _run_image_tool(
        source: Path,
        cmd: list[str],
        output_path: Path,
        timeout: int,
        tool_name: str,
    ) -> Path | None:
        """Run an image extraction tool and return the output path on success.

        Handles subprocess execution, result validation, and error handling
        for FFmpeg and oiiotool commands.

        Args:
            source: Source file (used only for log messages)
            cmd: Complete command to execute
            output_path: Expected output file path
            timeout: Subprocess timeout in seconds
            tool_name: Tool name for log messages (e.g., "FFmpeg", "oiiotool")

        Returns:
            output_path on success, None on any failure

        """
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                timeout=timeout,
                text=True,
            )

            if result.returncode == 0 and output_path.exists():
                return output_path

            logger.debug(f"{tool_name} failed for {source.name}: {result.stderr}")
            return None

        except subprocess.TimeoutExpired:
            logger.warning(f"{tool_name} timeout for {source.name}")
            return None
        except FileNotFoundError:
            logger.warning(f"{tool_name} not found in PATH")
            return None
        except Exception:
            logger.exception(f"Error running {tool_name} on {source.name}")
            return None

    @staticmethod
    def extract_frame_from_mov(
        mov_path: Path,
        output_path: Path | None = None,
    ) -> Path | None:
        """Extract frame #5 from a MOV file using FFmpeg.

        Args:
            mov_path: Path to the MOV file
            output_path: Optional output path for the extracted frame.
                        If None, creates a temporary file.

        Returns:
            Path to the extracted JPEG frame, or None if extraction failed

        """
        if not mov_path.exists() or not mov_path.is_file():
            logger.debug(f"MOV file does not exist: {mov_path}")
            return None

        if output_path is None:
            output_path = _make_temp_jpeg("shotbot_thumb_")

        cmd = [
            "ffmpeg",
            "-i", str(mov_path),
            "-an",
            "-vf", "select=eq(n\\,4)",
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            str(output_path),
        ]

        result = ImageUtils._run_image_tool(mov_path, cmd, output_path, timeout=TimeoutConfig.IMAGE_TOOL_STANDARD, tool_name="FFmpeg")
        if result:
            logger.debug(f"Successfully extracted frame #5 from MOV: {mov_path.name}")
        return result

    @staticmethod
    def extract_frame_at_time(
        mov_path: Path,
        time_seconds: float,
        output_path: Path | None = None,
        width: int = 200,
    ) -> Path | None:
        """Extract a frame at a specific timestamp from a MOV file.

        Uses -ss before -i for fast seeking (crucial for performance).

        Args:
            mov_path: Path to the MOV file
            time_seconds: Timestamp in seconds to extract
            output_path: Optional output path for the extracted frame.
                        If None, creates a temporary file.
            width: Width to scale the output frame to (height auto-calculated)

        Returns:
            Path to the extracted JPEG frame, or None if extraction failed

        """
        if not mov_path.exists() or not mov_path.is_file():
            logger.debug(f"MOV file does not exist: {mov_path}")
            return None

        if output_path is None:
            output_path = _make_temp_jpeg("shotbot_scrub_")

        cmd = [
            "ffmpeg",
            "-ss", str(time_seconds),
            "-i", str(mov_path),
            "-an",
            "-vf", f"scale={width}:-1",
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            str(output_path),
        ]

        return ImageUtils._run_image_tool(mov_path, cmd, output_path, timeout=10, tool_name="FFmpeg")

    @staticmethod
    def extract_frame_from_exr(
        exr_path: Path,
        output_path: Path | None = None,
        width: int = 200,
    ) -> Path | None:
        """Extract and convert an EXR frame to JPEG using oiiotool.

        Args:
            exr_path: Path to the EXR file
            output_path: Optional output path for the converted frame.
                        If None, creates a temporary file.
            width: Width to scale the output frame to (height auto-calculated)

        Returns:
            Path to the converted JPEG frame, or None if conversion failed

        """
        if not exr_path.exists() or not exr_path.is_file():
            logger.debug(f"EXR file does not exist: {exr_path}")
            return None

        if output_path is None:
            output_path = _make_temp_jpeg("shotbot_scrub_")

        cmd = [
            "oiiotool",
            str(exr_path),
            "--resize", f"{width}x0",
            "-o", str(output_path),
        ]

        return ImageUtils._run_image_tool(exr_path, cmd, output_path, timeout=TimeoutConfig.IMAGE_TOOL_STANDARD, tool_name="oiiotool")

    @staticmethod
    def get_mov_duration(mov_path: Path) -> float | None:
        """Get the duration of a MOV file in seconds using ffprobe.

        Args:
            mov_path: Path to the MOV file

        Returns:
            Duration in seconds, or None if unable to determine

        """

        if not mov_path.exists():
            return None

        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(mov_path),
            ]

            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                timeout=10,
                text=True,
            )

            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())

            return None

        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            return None
        except Exception:
            logger.exception(f"Error getting duration for {mov_path.name}")
            return None
