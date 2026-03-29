"""Configuration constants and settings for ShotBot application.

This module provides centralized configuration management for the ShotBot VFX
application. All constants are organized within the Config class to eliminate
magic numbers and provide a single source of truth for application settings.

Configuration Categories:
    - Application Info: Version, name, and metadata
    - Window Settings: Default dimensions, minimum sizes, and layout preferences
    - Thumbnail Settings: Size constraints, spacing, colors, and visual properties
    - File System Paths: Show directories, thumbnail paths, and workspace patterns
    - Application Commands: Executable names and launcher configurations
    - Performance Tuning: Thread counts, memory limits, and optimization flags
    - Cache Management: TTL values, size limits, and cleanup thresholds
    - UI Behavior: Update intervals, timeouts, and responsive design parameters

Path Pattern System:
    The configuration uses Python string formatting for flexible path construction:
        THUMBNAIL_PATH_PATTERN = "{shows_root}/{show}/shots/{sequence}/{shot}/..."

    This allows for easy customization of VFX pipeline directory structures
    without modifying core application logic.

Threading Configuration:
    Thread limits are carefully tuned for the target hardware:
        - MAX_THUMBNAIL_THREADS: Balances I/O throughput with memory usage
        - Background workers use separate thread pools for non-blocking operations
        - Qt thread safety considerations built into concurrent access patterns

Examples:
    Accessing configuration values:
        >>> from config import Config
        >>> thumbnail_size = Config.DEFAULT_THUMBNAIL_SIZE
        >>> shows_path = Config.SHOWS_ROOT
        >>> app_commands = Config.APPS

    Customizing for different pipelines:
        >>> # For custom show directory structure
        >>> Config.SHOWS_ROOT = "/mnt/projects"
        >>> Config.THUMBNAIL_PATH_PATTERN = "{shows_root}/{show}/shots/{sequence}..."

    Runtime configuration validation:
        >>> from pathlib import Path
        >>> assert Path(Config.SHOWS_ROOT).exists(), "Shows root not accessible"
        >>> assert Config.MIN_THUMBNAIL_SIZE <= Config.DEFAULT_THUMBNAIL_SIZE

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
    """Application configuration."""

    # App info
    APP_NAME: str = "ShotBot"
    APP_VERSION: str = "1.0.2"  # Added third thumbnail fallback for EXR files

    # Window settings
    DEFAULT_WINDOW_WIDTH: int = 1200
    DEFAULT_WINDOW_HEIGHT: int = 800
    MIN_WINDOW_WIDTH: int = 800
    MIN_WINDOW_HEIGHT: int = 600

    # Thumbnail settings
    DEFAULT_THUMBNAIL_SIZE: int = 420
    MIN_THUMBNAIL_SIZE: int = 400
    MAX_THUMBNAIL_SIZE: int = 1200
    THUMBNAIL_ASPECT_RATIO: float = 16 / 9  # Width / Height ratio for plate images
    THUMBNAIL_SPACING: int = 12  # Gap between grid cells
    PLACEHOLDER_COLOR: str = "#444444"

    # Shot paths (configurable via SHOWS_ROOT environment variable)
    SHOWS_ROOT: str = os.environ.get("SHOWS_ROOT", "/shows")
    THUMBNAIL_PATH_PATTERN: str = "{shows_root}/{show}/shots/{sequence}/{shot}/publish/editorial/cutref/v001/jpg/1920x1080/"

    # Commands
    APPS: ClassVar[dict[str, str]] = {
        "3de": "3de",
        "nuke": "nuke",
        "maya": "maya",
        "rv": "rv",
        "publish": "publish_standalone",
    }
    DEFAULT_APP: str = "nuke"

    # Rez Environment Configuration
    # - DISABLED: Never launch through Rez
    # - AUTO: Resolve the configured app packages for each DCC launch
    # - FORCE: Reserved for callers that want explicit deterministic wrapping
    REZ_MODE: RezMode = RezMode.AUTO

    REZ_NUKE_PACKAGES: ClassVar[list[str]] = [
        "nuke",
        "python-3.11",
    ]  # Default rez packages for Nuke with Python 3.11 compatibility
    REZ_MAYA_PACKAGES: ClassVar[list[str]] = ["maya"]  # Default rez packages for Maya
    REZ_3DE_PACKAGES: ClassVar[list[str]] = ["3de"]  # Default rez packages for 3DE
    REZ_RV_PACKAGES: ClassVar[list[str]] = ["rv"]  # Default rez packages for RV
    REZ_PUBLISH_PACKAGES: ClassVar[list[str]] = [
        "publish_standalone"
    ]  # Rez packages for publish tool

    NUKE_FIX_OCIO_CRASH: bool = (
        False  # Whether to apply environment fixes to prevent OCIO plugin crashes
    )
    NUKE_SKIP_PROBLEMATIC_PLUGINS: bool = (
        False  # Whether to skip known problematic plugins that cause crashes
    )
    NUKE_PROBLEMATIC_PLUGIN_PATHS: ClassVar[list[str]] = [
        "/software/bluebolt/rez/packages/bluebolt/nuke_tools/4.0.0rc9/python-3.11/init",
        "/software/bluebolt/rez/packages/bluebolt/nuke_tools/4.0.3/python-3.11",  # Disable ShotGrid bootstrap errors
        # Add other problematic plugin paths here
    ]
    NUKE_OCIO_FALLBACK_CONFIG: str = "/usr/share/color/nuke-default/config.ocio"  # Fallback OCIO config if system one fails

    # Maya launch optimization
    MAYA_SKIP_CONTEXT_BOOTSTRAP: ClassVar[bool] = False

    # Per-app Rez bypass — apps in this set skip rez wrapping even when REZ_MODE is AUTO/FORCE
    REZ_BYPASS_APPS: ClassVar[set[str]] = set()

    # Launch logging
    LAUNCH_LOG_MAX_SIZE_MB: int = (
        10  # Max log file size in MB before rotation (0 = no limit)
    )
    LAUNCH_LOGGING_TEE_BYPASS_APPS: ClassVar[set[str]] = set()

    # Settings file
    SETTINGS_FILE: Path = Path.home() / ".shotbot" / "settings.json"

    # UI settings
    LOG_MAX_LINES: int = 1000
    GRID_COLUMNS: int = 4  # Default columns, will be dynamic based on width

    # Threading
    MAX_THUMBNAIL_THREADS: int = 4
    CPU_COUNT: int = multiprocessing.cpu_count()  # Number of CPU cores available

    # Image and memory limits
    MAX_THUMBNAIL_DIMENSION_PX: int = 4096  # Maximum dimension for thumbnail images
    MAX_INFO_PANEL_DIMENSION_PX: int = (
        2048  # Maximum dimension for info panel thumbnails
    )
    MAX_CACHE_DIMENSION_PX: int = 10000  # Maximum dimension for cached images
    MAX_THUMBNAIL_MEMORY_MB: int = 50  # Maximum memory usage for thumbnail images
    MAX_FILE_SIZE_MB: int = 100  # Maximum file size for image loading

    # Cache settings
    CACHE_EXPIRY_MINUTES: int = (
        1440  # Cache for 24 hours (1 day) - data persists longer
    )
    CACHE_THUMBNAIL_SIZE: int = 512  # Size for cached thumbnails
    CACHE_REFRESH_INTERVAL_MINUTES: int = (
        60  # Background refresh check interval (once per hour)
    )
    ENABLE_BACKGROUND_REFRESH: bool = True

    # Enhanced cache settings
    PATH_CACHE_TTL_SECONDS: int = 60  # Positive path validation TTL (seconds)
    PATH_CACHE_NEGATIVE_TTL_SECONDS: int = 10  # Missing-path TTL (seconds)
    DIR_CACHE_TTL_SECONDS: int = (
        0  # Directory listings (0 = no automatic expiry, manual refresh only)
    )
    SCENE_CACHE_TTL_SECONDS: int = (
        0  # 3DE scenes (0 = no automatic expiry, manual refresh only)
    )

    # Cache size limits
    PATH_CACHE_MAX_SIZE: int = 5000  # Maximum path cache entries
    DIR_CACHE_MAX_SIZE: int = 500  # Maximum directory cache entries
    SCENE_CACHE_MAX_SIZE: int = 2000  # Maximum scene cache entries

    # Memory limits (MB)
    PATH_CACHE_MAX_MEMORY_MB: float = 1.0
    DIR_CACHE_MAX_MEMORY_MB: float = 5.0
    SCENE_CACHE_MAX_MEMORY_MB: float = 5.0
    THUMB_CACHE_MAX_MEMORY_MB: float = 2.0

    # (Notification timeouts moved to TimeoutConfig.NOTIFICATION_SUCCESS_MS / NOTIFICATION_ERROR_MS)

    # VFX pipeline settings
    DEFAULT_USERNAME: str = "gabriel-h"  # Default username for pipeline paths
    # Production scripts directory — used for PYTHON_CUSTOM_SCRIPTS_3DE4 and NUKE_PATH exports
    # Override with SHOTBOT_SCRIPTS_DIR env var; defaults to repo-relative scripts/
    SCRIPTS_DIR: str = os.environ.get(
        "SHOTBOT_SCRIPTS_DIR", str(Path(__file__).resolve().parent / "scripts")
    )

    # File extensions
    # Thumbnail discovery strategy
    # Primary: Lightweight formats that can be loaded directly
    THUMBNAIL_EXTENSIONS: ClassVar[list[str]] = [".jpg", ".jpeg", ".png"]

    # Fallback: Heavy formats that require PIL resizing before use (EXR removed - not supported)
    THUMBNAIL_FALLBACK_EXTENSIONS: ClassVar[list[str]] = [".tiff", ".tif"]

    # Maximum file size (MB) for direct loading without resizing
    THUMBNAIL_MAX_DIRECT_SIZE_MB: int = 10

    # Keep IMAGE_EXTENSIONS for general image handling (includes EXR for Nuke, not for thumbnails)
    IMAGE_EXTENSIONS: ClassVar[list[str]] = [
        ".jpg",
        ".jpeg",
        ".png",
        ".tiff",
        ".tif",
        ".exr",
    ]
    NUKE_EXTENSIONS: ClassVar[list[str]] = [".nk", ".nknc"]
    THREEDE_EXTENSIONS: ClassVar[list[str]] = [".3de"]

    # Path construction segments
    THUMBNAIL_SEGMENTS: ClassVar[list[str]] = [
        "publish",
        "editorial",
        "cutref",
        "v001",
        "jpg",
        "1920x1080",
    ]
    RAW_PLATE_SEGMENTS: ClassVar[list[str]] = [
        "publish",
        "turnover",
        "plate",
        "input_plate",
    ]  # Removed bg01 for flexible discovery

    # Plate discovery patterns and priorities
    PLATE_DISCOVERY_PATTERNS: ClassVar[list[str]] = [
        "FG01",
        "FG02",
        "BG01",
        "BG02",
        "PL01",  # Primary turnover plate
        "PL02",  # Secondary turnover plate
        "PL03",  # Tertiary turnover plate
        "COMP01",  # Composite plate 01
        "COMP02",  # Composite plate 02
        "COMP03",  # Composite plate 03
        "bg01",
        "fg01",
        "plate",
    ]  # Common plate naming including PL## turnover patterns

    # Turnover plate preferences (lower value = higher priority)
    # For primary workflow: use FG (foreground), PL (turnover), and BG (background) plates
    TURNOVER_PLATE_PRIORITY: ClassVar[dict[str, float]] = {
        "FG": 0,  # Primary foreground plates (FG01, FG02) - USE THESE
        "PL": 0.5,  # Primary turnover plates (PL01, PL02) - USE THESE
        "BG": 1,  # Primary background plates (BG01, BG02) - USE THESE
        "COMP": 1.5,  # Composite plates - USE IF NEEDED
        "EL": 2,  # Element plates - USE IF NEEDED
        "BC": 10,  # Background clean plates (BC01) - SKIP (reference only)
        "*": 12,  # All others lowest priority
    }

    # Progressive file scanning configuration
    PROGRESSIVE_SCAN_BATCH_SIZE: int = 20  # Number of files to process per batch

    # Progress reporting configuration
    PROGRESS_ETA_SMOOTHING_WINDOW: int = 5  # Number of samples for ETA smoothing

    # Worker thread configuration
    WORKER_THREAD_PRIORITY: int = 0  # QThread priority (0=normal, -1=low, +1=high)


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
