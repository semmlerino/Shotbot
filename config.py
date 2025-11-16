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
from pathlib import Path
from typing import ClassVar


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
    DEFAULT_THUMBNAIL_SIZE: int = 350
    MIN_THUMBNAIL_SIZE: int = 250
    MAX_THUMBNAIL_SIZE: int = 600
    THUMBNAIL_SPACING: int = 20  # Increased to accommodate selection highlight
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
    USE_REZ_ENVIRONMENT: bool = True  # Enable rez environment wrapper when available
    REZ_AUTO_DETECT: bool = True  # Automatically detect rez availability via REZ_USED env var
    REZ_NUKE_PACKAGES: ClassVar[list[str]] = [
        "nuke",
        "python-3.11",
    ]  # Default rez packages for Nuke with Python 3.11 compatibility
    REZ_MAYA_PACKAGES: ClassVar[list[str]] = ["maya"]  # Default rez packages for Maya
    REZ_3DE_PACKAGES: ClassVar[list[str]] = ["3de"]  # Default rez packages for 3DE

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

    # Persistent Terminal Settings
    PERSISTENT_TERMINAL_ENABLED: bool = (
        False  # Master switch to enable/disable persistent terminal
    )
    USE_PERSISTENT_TERMINAL: bool = (
        True  # Use single terminal for all commands (when enabled)
    )
    PERSISTENT_TERMINAL_FIFO: str = "/tmp/shotbot_commands.fifo"  # FIFO path for commands
    PERSISTENT_TERMINAL_TITLE: str = "ShotBot Terminal"  # Terminal window title
    KEEP_TERMINAL_ON_EXIT: bool = False  # Keep terminal open when ShotBot closes
    CLEAR_TERMINAL_BEFORE_COMMAND: bool = False  # Clear screen before each command
    TERMINAL_DISPATCHER_SCRIPT: str = "terminal_dispatcher.sh"  # Dispatcher script name

    # Terminal Management Configuration
    FIFO_PATH: str = os.getenv("SHOTBOT_FIFO_PATH", "/tmp/shotbot_commands.fifo")
    HEARTBEAT_PATH: str = os.getenv("SHOTBOT_HEARTBEAT_PATH", "/tmp/shotbot_heartbeat.txt")
    HEARTBEAT_TIMEOUT: float = float(os.getenv("SHOTBOT_HEARTBEAT_TIMEOUT", "60.0"))
    HEARTBEAT_CHECK_INTERVAL: float = float(os.getenv("SHOTBOT_HEARTBEAT_CHECK_INTERVAL", "30.0"))
    MAX_TERMINAL_RESTART_ATTEMPTS: int = int(os.getenv("SHOTBOT_MAX_TERMINAL_RESTART_ATTEMPTS", "3"))

    # Settings file
    SETTINGS_FILE: Path = Path.home() / ".shotbot" / "settings.json"

    # UI settings
    LOG_MAX_LINES: int = 1000
    GRID_COLUMNS: int = 4  # Default columns, will be dynamic based on width

    # Threading
    MAX_THUMBNAIL_THREADS: int = 4
    CPU_COUNT: int = multiprocessing.cpu_count()  # Number of CPU cores available
    WORKER_STOP_TIMEOUT_MS: int = 5000  # Timeout for worker.wait() calls (5 seconds)

    # Thumbnail unloading settings
    THUMBNAIL_UNLOAD_DELAY_MS: int = 5000  # Delay before unloading invisible thumbnails

    # Process and command settings
    SUBPROCESS_TIMEOUT_SECONDS: int = 10  # Timeout for subprocess calls
    WS_COMMAND_TIMEOUT_SECONDS: int = 10  # Timeout for ws -sg command specifically
    WS_CACHE_TTL: int = int(os.getenv("SHOTBOT_WS_CACHE_TTL", "1800"))  # 30 minutes

    # Image and memory limits
    MAX_THUMBNAIL_DIMENSION_PX: int = 4096  # Maximum dimension for thumbnail images
    MAX_INFO_PANEL_DIMENSION_PX: int = 2048  # Maximum dimension for info panel thumbnails
    MAX_CACHE_DIMENSION_PX: int = 10000  # Maximum dimension for cached images
    MAX_THUMBNAIL_MEMORY_MB: int = 50  # Maximum memory usage for thumbnail images
    MAX_FILE_SIZE_MB: int = 100  # Maximum file size for image loading

    # Cache settings
    CACHE_EXPIRY_MINUTES: int = 1440  # Cache for 24 hours (1 day) - data persists longer
    CACHE_THUMBNAIL_SIZE: int = 512  # Size for cached thumbnails
    CACHE_REFRESH_INTERVAL_MINUTES: int = (
        60  # Background refresh check interval (once per hour)
    )
    ENABLE_BACKGROUND_REFRESH: bool = (
        True  # Can be overridden by SHOTBOT_NO_BACKGROUND_REFRESH env var
    )

    # Enhanced cache settings
    PATH_CACHE_TTL_SECONDS: int = (
        0  # Path validation (0 = no automatic expiry, manual refresh only)
    )
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

    # Memory pressure thresholds (percentage)
    MEMORY_PRESSURE_NORMAL: float = 70.0  # Below this is normal
    MEMORY_PRESSURE_MODERATE: float = 85.0  # Start considering eviction
    MEMORY_PRESSURE_HIGH: float = 95.0  # Aggressive eviction needed

    # Performance monitoring
    ENABLE_PERFORMANCE_MONITORING: bool = True
    CACHE_STATS_LOG_INTERVAL: int = 300  # Log cache stats every 5 minutes

    # Notification settings
    NOTIFICATION_TOAST_DURATION_MS: int = 4000  # Auto-dismiss time for toast notifications
    NOTIFICATION_SUCCESS_TIMEOUT_MS: int = 3000  # Success message timeout in status bar
    NOTIFICATION_ERROR_TIMEOUT_MS: int = 5000  # Error message timeout in status bar
    NOTIFICATION_MAX_TOASTS: int = 5  # Maximum simultaneous toast notifications

    # VFX pipeline settings
    DEFAULT_USERNAME: str = "gabriel-h"  # Default username for pipeline paths

    # File extensions
    # Thumbnail discovery strategy
    # Primary: Lightweight formats that can be loaded directly
    THUMBNAIL_EXTENSIONS: ClassVar[list[str]] = [".jpg", ".jpeg", ".png"]

    # Fallback: Heavy formats that require PIL resizing before use (EXR removed - not supported)
    THUMBNAIL_FALLBACK_EXTENSIONS: ClassVar[list[str]] = [".tiff", ".tif"]

    # Maximum file size (MB) for direct loading without resizing
    THUMBNAIL_MAX_DIRECT_SIZE_MB: int = 10

    # Keep IMAGE_EXTENSIONS for general image handling (includes EXR for Nuke, not for thumbnails)
    IMAGE_EXTENSIONS: ClassVar[list[str]] = [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".exr"]
    NUKE_EXTENSIONS: ClassVar[list[str]] = [".nk", ".nknc"]
    THREEDE_EXTENSIONS: ClassVar[list[str]] = [".3de"]

    # Path construction segments
    THUMBNAIL_SEGMENTS: ClassVar[list[str]] = ["publish", "editorial", "cutref", "v001", "jpg", "1920x1080"]
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

    # Legacy plate priority (for backward compatibility)
    PLATE_PRIORITY_ORDER: ClassVar[dict[str, float]] = {
        "FG01": 10,
        "fg01": 9,
        "FG02": 8,
        "PL01": 7,  # Primary turnover plate - high priority
        "PL02": 6,  # Secondary turnover plate
        "PL03": 5,  # Tertiary turnover plate
        "COMP01": 4.5,  # Composite plates - between PL and BG
        "COMP02": 4.4,
        "COMP03": 4.3,
        "BG01": 4.0,
        "bg01": 3.5,
        "BG02": 2,
    }  # Higher value = higher priority

    # Common color space patterns in plate names
    COLOR_SPACE_PATTERNS: ClassVar[list[str]] = [
        "aces",
        "lin_sgamut3cine",
        "lin_rec709",
        "rec709",
        "srgb",
        "film_lin",
    ]

    THREEDE_SCENE_SEGMENTS: ClassVar[list[str]] = ["mm", "3de", "mm-default", "scenes", "scene"]

    # Alternative 3DE scene path patterns to try if main pattern fails
    THREEDE_ALTERNATIVE_PATTERNS: ClassVar[list[list[str]]] = [
        ["mm", "3de", "scenes"],
        ["mm", "3de", "scene"],
        ["3de", "scenes"],
        ["3de", "scene"],
        ["matchmove", "3de", "scenes"],
        ["matchmove", "3de", "scene"],
        ["mm", "scenes"],
        ["mm", "scene"],
        ["scenes"],
        ["scene"],
    ]

    # Environment variables that may contain 3DE path information
    THREEDE_ENV_VARS: ClassVar[list[str]] = [
        "THREEDE_SCENE_PATH",
        "3DE_SCENE_PATH",
        "TDE_SCENE_PATH",
        "MM_SCENE_PATH",
        "MATCHMOVE_SCENE_PATH",
    ]

    # Common VFX plate name patterns for intelligent grouping
    PLATE_NAME_PATTERNS: ClassVar[list[str]] = [
        r"^[bf]g\d{2}$",  # bg01, fg01, bg02, fg02, etc.
        r"^plate_?\d+$",  # plate01, plate_01, plate02
        r"^comp_?\d+$",  # comp01, comp_01, comp02
        r"^shot_?\d+$",  # shot01, shot_01, shot010
        r"^sc\d+$",  # sc01, sc02, sc10
        r"^[\w]+_v\d{3}$",  # anything_v001, test_v002
        r"^elem_?\d+$",  # elem01, elem_01
        r"^cam_?\d+$",  # cam01, cam_01, cam1
        r"^tk\d+$",  # tk01, tk02 (take numbers)
        r"^roto_?\d+$",  # roto01, roto_01
    ]

    # Show-wide search configuration
    SHOW_SEARCH_ENABLED: bool = (
        True  # Enable searching all shots in shows (not just user's shots)
    )
    SHOW_ROOT_PATHS: ClassVar[list[str]] = [
        SHOWS_ROOT
    ]  # Root directories where shows are stored (uses configured SHOWS_ROOT)
    MAX_SHOTS_PER_SHOW: int = 1000  # Limit to prevent excessive searching in huge shows
    SKIP_SEQUENCE_PATTERNS: ClassVar[list[str]] = ["tmp", "temp", "test", "old", "archive", "_dev"]
    SKIP_SHOT_PATTERNS: ClassVar[list[str]] = ["tmp", "temp", "test", "old", "archive", "_dev"]

    # Progressive file scanning configuration
    PROGRESSIVE_SCAN_ENABLED: bool = True  # Enable progressive/batched file scanning
    PROGRESSIVE_SCAN_BATCH_SIZE: int = 20  # Number of files to process per batch
    PROGRESSIVE_SCAN_MIN_BATCH_SIZE: int = 5  # Minimum batch size for last batch
    PROGRESSIVE_SCAN_MAX_BATCH_SIZE: int = 100  # Maximum batch size limit

    # Backward compatibility constant for tests
    THREEDE_BATCH_SIZE: int = PROGRESSIVE_SCAN_BATCH_SIZE  # Alias for backward compatibility

    # Progress reporting configuration
    PROGRESS_UPDATE_INTERVAL_MS: int = 500  # Minimum time between progress updates (ms)
    PROGRESS_FILES_PER_UPDATE: int = 10  # Update progress every N files processed
    PROGRESS_ENABLE_ETA: bool = True  # Enable ETA calculation and display
    PROGRESS_ETA_SMOOTHING_WINDOW: int = 5  # Number of samples for ETA smoothing

    # Worker thread configuration
    WORKER_CANCELLATION_CHECK_INTERVAL: int = 50  # Check for cancellation every N files
    WORKER_PAUSE_CHECK_INTERVAL_MS: int = 100  # Check for pause/resume every N ms
    WORKER_THREAD_PRIORITY: int = 0  # QThread priority (0=normal, -1=low, +1=high)
    WORKER_SHUTDOWN_TIMEOUT_MS: int = 5000  # Maximum time to wait for worker shutdown

    # Performance tuning for progressive scanning
    PROGRESSIVE_IO_YIELD_INTERVAL: int = 25  # Yield to other threads every N files
    PROGRESSIVE_MEMORY_CHECK_INTERVAL: int = 100  # Check memory usage every N files
    PROGRESSIVE_MAX_MEMORY_MB: int = 512  # Maximum memory usage during scanning

    # 3DE Scene Discovery Configuration (NEW - Efficient scanning)
    THREEDE_SCAN_MODE: str = "full_show"  # Options: "full_show", "user_sequences", "smart"
    # - "full_show": Scan entire show (old behavior, can be slow)
    # - "user_sequences": Only scan sequences where user has shots
    # - "smart": Only scan shots that actually have .3de files (most efficient)

    THREEDE_MAX_SHOTS_TO_SCAN: int = 1000  # Increased: scan more shots
    THREEDE_SCAN_RELATED_SEQUENCES: bool = (
        True  # Only scan user's sequences (when in user_sequences mode)
    )
    THREEDE_FILE_FIRST_DISCOVERY: bool = True  # Use new efficient file-first discovery
    THREEDE_SCAN_TIMEOUT_SECONDS: int = 60  # Extended timeout for large/slow filesystems
    THREEDE_SCAN_MAX_DEPTH: int = (
        15  # Max directory depth for find command (increased for deeply nested files)
    )
    THREEDE_SCAN_PARALLEL_SEQUENCES: int = 4  # Number of sequences to search in parallel
    THREEDE_SCAN_MAX_FILES_PER_SHOT: int = 1  # Stop after finding ONE .3de file per shot
    THREEDE_STOP_AFTER_FIRST: bool = True  # New: stop searching shot after first .3de found
    THREEDE_CACHE_DISCOVERED_SHOTS: bool = True  # Cache which shots have .3de files
    THREEDE_INCREMENTAL_SCAN: bool = False  # Only scan for changes (future feature)


class ThreadingConfig:
    """Threading and timeout configuration constants.

    This class centralizes all threading-related configuration to prevent
    deadlocks and ensure consistent timing across the application.
    """

    # Worker timeouts
    WORKER_STOP_TIMEOUT_MS: int = 2000  # Time to wait for graceful worker stop
    WORKER_TERMINATE_TIMEOUT_MS: int = 1000  # Time to wait before force termination
    WORKER_POLL_INTERVAL: float = 0.1  # Polling interval for worker state checks

    # Cleanup timings
    CLEANUP_RETRY_DELAY_MS: int = 500  # Delay between cleanup retry attempts
    CLEANUP_INITIAL_DELAY_MS: int = 1000  # Initial delay before cleanup starts

    # Process pool configuration
    SESSION_INIT_TIMEOUT: float = 2.0  # Timeout for session initialization
    SESSION_MAX_RETRIES: int = 5  # Maximum retry attempts for session operations
    SUBPROCESS_TIMEOUT: float = 30.0  # General subprocess timeout

    # Polling configuration
    INITIAL_POLL_INTERVAL: float = 0.01  # 10ms - Initial polling interval
    MAX_POLL_INTERVAL: float = 0.5  # 500ms - Maximum polling interval
    POLL_BACKOFF_FACTOR: float = 1.5  # Exponential backoff multiplier

    # Cache configuration
    CACHE_MAX_MEMORY_MB: int = 100  # Maximum memory for caching
    CACHE_CLEANUP_INTERVAL: int = 30  # Cache cleanup interval in minutes

    # Thread pool settings
    MAX_WORKER_THREADS: int = 4  # Maximum number of worker threads
    THREAD_POOL_TIMEOUT: float = 5.0  # Thread pool operation timeout

    # Previous shots parallel scanning
    PREVIOUS_SHOTS_PARALLEL_WORKERS: int = 4  # Number of parallel workers for shot scanning
    PREVIOUS_SHOTS_SCAN_TIMEOUT: int = 30  # Timeout per show (seconds)
    PREVIOUS_SHOTS_CACHE_TTL: int = (
        0  # Cache time-to-live (0 = no automatic expiry, manual refresh only)
    )

    # 3DE scene discovery parallel scanning
    THREEDE_PARALLEL_WORKERS: int = 4  # Number of parallel workers for 3DE file discovery
    THREEDE_PROGRESS_INTERVAL: int = 10  # Number of files between progress updates
    THREEDE_SCAN_CHUNK_SIZE: int = 100  # Files per batch for processing
    THREEDE_SCAN_TIMEOUT: int = 60  # Timeout per directory scan (seconds)
