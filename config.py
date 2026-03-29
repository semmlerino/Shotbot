"""Configuration constants and settings for ShotBot application.

This module provides centralized configuration management for the ShotBot VFX
application. All constants are organized within the Config class using nested
domain classes for structural grouping.

Thread Safety:
    Configuration values are read-only after import and safe for concurrent
    access. Runtime modifications should be avoided in production environments.

"""

# Standard library imports
import multiprocessing
import os
from enum import Enum, auto
from pathlib import Path
from typing import ClassVar


def is_mock_mode() -> bool:
    """Return True if SHOTBOT_MOCK environment variable is set to a truthy value."""
    return os.environ.get("SHOTBOT_MOCK", "").lower() in ("1", "true", "yes")


class RezMode(Enum):
    """Rez environment wrapping mode.

    Determines when and how rez wrapping is applied to launched commands.
    """

    DISABLED = auto()
    """Never wrap with rez. Use this when rez is not available or not wanted."""

    AUTO = auto()
    """Resolve the configured app-specific Rez packages for each DCC launch.
    This is the default because a base Rez shell is not assumed to contain the
    correct Maya/Nuke/RV context."""

    FORCE = auto()
    """Always wrap with app-specific rez packages.
    Reserved for callers that want the most explicit deterministic behavior."""


class Config:
    """Application configuration organized by domain."""

    class App:
        """Application identity."""

        NAME: str = "ShotBot"
        VERSION: str = "1.0.2"  # Added third thumbnail fallback for EXR files

    class Window:
        """Window size defaults and constraints."""

        DEFAULT_WIDTH: int = 1200
        DEFAULT_HEIGHT: int = 800
        MIN_WIDTH: int = 800
        MIN_HEIGHT: int = 600

    class Thumbnail:
        """Thumbnail rendering defaults."""

        DEFAULT_SIZE: int = 420
        MIN_SIZE: int = 400
        MAX_SIZE: int = 1200
        ASPECT_RATIO: float = 16 / 9  # Width / Height ratio for plate images
        SPACING: int = 12  # Gap between grid cells
        PLACEHOLDER_COLOR: str = "#444444"

    class Paths:
        """Filesystem paths and patterns."""

        SHOWS_ROOT: str = os.environ.get("SHOWS_ROOT", "/shows")
        THUMBNAIL_PATH_PATTERN: str = "{shows_root}/{show}/shots/{sequence}/{shot}/publish/editorial/cutref/v001/jpg/1920x1080/"
        SCRIPTS_DIR: str = os.environ.get(
            "SHOTBOT_SCRIPTS_DIR", str(Path(__file__).resolve().parent / "scripts")
        )
        SETTINGS_FILE: Path = Path.home() / ".shotbot" / "settings.json"

    class Launch:
        """Application launch configuration."""

        APPS: ClassVar[dict[str, str]] = {
            "3de": "3de",
            "nuke": "nuke",
            "maya": "maya",
            "rv": "rv",
            "publish": "publish_standalone",
        }
        DEFAULT_APP: str = "nuke"
        REZ_MODE: RezMode = RezMode.AUTO
        REZ_NUKE_PACKAGES: ClassVar[list[str]] = [
            "nuke",
            "python-3.11",
        ]
        REZ_MAYA_PACKAGES: ClassVar[list[str]] = ["maya"]
        REZ_3DE_PACKAGES: ClassVar[list[str]] = ["3de"]
        REZ_RV_PACKAGES: ClassVar[list[str]] = ["rv"]
        REZ_PUBLISH_PACKAGES: ClassVar[list[str]] = ["publish_standalone"]
        REZ_BYPASS_APPS: ClassVar[set[str]] = set()
        LOG_MAX_SIZE_MB: int = 10  # Max log file size in MB before rotation (0 = no limit)
        LOGGING_TEE_BYPASS_APPS: ClassVar[set[str]] = set()

    class DCC:
        """DCC-specific launch flags."""

        NUKE_FIX_OCIO_CRASH: bool = False
        NUKE_SKIP_PROBLEMATIC_PLUGINS: bool = False
        NUKE_PROBLEMATIC_PLUGIN_PATHS: ClassVar[list[str]] = [
            "/software/bluebolt/rez/packages/bluebolt/nuke_tools/4.0.0rc9/python-3.11/init",
            "/software/bluebolt/rez/packages/bluebolt/nuke_tools/4.0.3/python-3.11",
        ]
        NUKE_OCIO_FALLBACK_CONFIG: str = "/usr/share/color/nuke-default/config.ocio"
        MAYA_SKIP_CONTEXT_BOOTSTRAP: ClassVar[bool] = False

    class Cache:
        """Cache TTL, size, and memory limits."""

        EXPIRY_MINUTES: int = 1440  # 24 hours
        THUMBNAIL_SIZE: int = 512
        REFRESH_INTERVAL_MINUTES: int = 60
        ENABLE_BACKGROUND_REFRESH: bool = True
        PATH_TTL_SECONDS: int = 60
        PATH_NEGATIVE_TTL_SECONDS: int = 10
        DIR_TTL_SECONDS: int = 0  # 0 = manual refresh only
        SCENE_TTL_SECONDS: int = 0  # 0 = manual refresh only
        PATH_MAX_SIZE: int = 5000
        DIR_MAX_SIZE: int = 500
        SCENE_MAX_SIZE: int = 2000
        PATH_MAX_MEMORY_MB: float = 1.0
        DIR_MAX_MEMORY_MB: float = 5.0
        SCENE_MAX_MEMORY_MB: float = 5.0
        THUMB_MAX_MEMORY_MB: float = 2.0

    class Threading:
        """Thread pool and worker configuration."""

        MAX_THUMBNAIL_THREADS: int = 4
        CPU_COUNT: int = multiprocessing.cpu_count()
        WORKER_PRIORITY: int = 0  # QThread priority (0=normal, -1=low, +1=high)

    class ImageLimits:
        """Image dimension and memory safety caps."""

        MAX_THUMBNAIL_DIMENSION_PX: int = 4096
        MAX_INFO_PANEL_DIMENSION_PX: int = 2048
        MAX_CACHE_DIMENSION_PX: int = 10000
        MAX_THUMBNAIL_MEMORY_MB: int = 50
        MAX_FILE_SIZE_MB: int = 100
        THUMBNAIL_MAX_DIRECT_SIZE_MB: int = 10

    class FileDiscovery:
        """File extension lists and plate discovery patterns."""

        THUMBNAIL_EXTENSIONS: ClassVar[list[str]] = [".jpg", ".jpeg", ".png"]
        THUMBNAIL_FALLBACK_EXTENSIONS: ClassVar[list[str]] = [".tiff", ".tif"]
        IMAGE_EXTENSIONS: ClassVar[list[str]] = [
            ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".exr",
        ]
        NUKE_EXTENSIONS: ClassVar[list[str]] = [".nk", ".nknc"]
        THREEDE_EXTENSIONS: ClassVar[list[str]] = [".3de"]
        THUMBNAIL_SEGMENTS: ClassVar[list[str]] = [
            "publish", "editorial", "cutref", "v001", "jpg", "1920x1080",
        ]
        RAW_PLATE_SEGMENTS: ClassVar[list[str]] = [
            "publish", "turnover", "plate", "input_plate",
        ]
        PLATE_DISCOVERY_PATTERNS: ClassVar[list[str]] = [
            "FG01", "FG02", "BG01", "BG02",
            "PL01", "PL02", "PL03",
            "COMP01", "COMP02", "COMP03",
            "bg01", "fg01", "plate",
        ]
        TURNOVER_PLATE_PRIORITY: ClassVar[dict[str, float]] = {
            "FG": 0, "PL": 0.5, "BG": 1, "COMP": 1.5,
            "EL": 2, "BC": 10, "*": 12,
        }

    class UI:
        """UI behavior tuning."""

        LOG_MAX_LINES: int = 1000
        GRID_COLUMNS: int = 4
        PROGRESSIVE_SCAN_BATCH_SIZE: int = 20
        PROGRESS_ETA_SMOOTHING_WINDOW: int = 5

    # Top-level (pipeline identity)
    DEFAULT_USERNAME: str = "gabriel-h"


class ThreadingConfig:
    """Threading and timeout configuration constants.

    This class centralizes all threading-related configuration to prevent
    deadlocks and ensure consistent timing across the application.
    """

    # Polling configuration
    POLL_BACKOFF_FACTOR: float = 1.5  # Exponential backoff multiplier

    # Previous shots parallel scanning
    PREVIOUS_SHOTS_PARALLEL_WORKERS: int = (
        4  # Number of parallel workers for shot scanning
    )
    PREVIOUS_SHOTS_CACHE_TTL: int = (
        0  # Cache time-to-live (0 = no automatic expiry, manual refresh only)
    )
