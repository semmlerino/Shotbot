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

from pathlib import Path


class Config:
    """Application configuration."""

    # App info
    APP_NAME = "ShotBot"
    APP_VERSION = "1.0.0"

    # Window settings
    DEFAULT_WINDOW_WIDTH = 1200
    DEFAULT_WINDOW_HEIGHT = 800
    MIN_WINDOW_WIDTH = 800
    MIN_WINDOW_HEIGHT = 600

    # Thumbnail settings
    DEFAULT_THUMBNAIL_SIZE = 200
    MIN_THUMBNAIL_SIZE = 100
    MAX_THUMBNAIL_SIZE = 400
    THUMBNAIL_SPACING = 20  # Increased to accommodate selection highlight
    PLACEHOLDER_COLOR = "#444444"

    # Shot paths
    SHOWS_ROOT = "/shows"
    THUMBNAIL_PATH_PATTERN = "{shows_root}/{show}/shots/{sequence}/{shot}/publish/editorial/cutref/v001/jpg/1920x1080/"

    # Commands
    APPS = {
        "3de": "3de",
        "nuke": "nuke",
        "maya": "maya",
        "rv": "rv",
        "publish": "publish_standalone",
    }
    DEFAULT_APP = "nuke"

    # Settings file
    SETTINGS_FILE = Path.home() / ".shotbot" / "settings.json"

    # UI settings
    LOG_MAX_LINES = 1000
    GRID_COLUMNS = 4  # Default columns, will be dynamic based on width

    # Threading
    MAX_THUMBNAIL_THREADS = 4

    # Memory optimization (deprecated - Model/View is always used)
    # The Model/View architecture provides automatic memory optimization
    # through virtualization and delegate-based rendering
    # These are kept temporarily for backward compatibility with legacy code
    MAX_LOADED_THUMBNAILS = 50  # DEPRECATED - will be removed
    VIEWPORT_BUFFER_ROWS = 2  # DEPRECATED - will be removed
    THUMBNAIL_UNLOAD_DELAY_MS = 5000  # Delay before unloading invisible thumbnails

    # Process and command settings
    SUBPROCESS_TIMEOUT_SECONDS = 10  # Timeout for subprocess calls
    WS_COMMAND_TIMEOUT_SECONDS = 10  # Timeout for ws -sg command specifically

    # Image and memory limits
    MAX_THUMBNAIL_DIMENSION_PX = 4096  # Maximum dimension for thumbnail images
    MAX_INFO_PANEL_DIMENSION_PX = 2048  # Maximum dimension for info panel thumbnails
    MAX_CACHE_DIMENSION_PX = 10000  # Maximum dimension for cached images
    MAX_THUMBNAIL_MEMORY_MB = 50  # Maximum memory usage for thumbnail images
    MAX_FILE_SIZE_MB = 100  # Maximum file size for image loading

    # Cache settings
    CACHE_EXPIRY_MINUTES = 1440  # Cache for 24 hours (1 day) - data persists longer
    CACHE_THUMBNAIL_SIZE = 512  # Size for cached thumbnails
    CACHE_REFRESH_INTERVAL_MINUTES = 10  # Background refresh check interval

    # Enhanced cache settings
    PATH_CACHE_TTL_SECONDS = 300  # 5 minutes for path validation (10x improvement)
    DIR_CACHE_TTL_SECONDS = 60  # 1 minute for directory listings
    SCENE_CACHE_TTL_SECONDS = 1800  # 30 minutes for 3DE scenes

    # Cache size limits
    PATH_CACHE_MAX_SIZE = 5000  # Maximum path cache entries
    DIR_CACHE_MAX_SIZE = 500  # Maximum directory cache entries
    SCENE_CACHE_MAX_SIZE = 2000  # Maximum scene cache entries

    # Memory limits (MB)
    PATH_CACHE_MAX_MEMORY_MB = 1.0
    DIR_CACHE_MAX_MEMORY_MB = 5.0
    SCENE_CACHE_MAX_MEMORY_MB = 5.0
    THUMB_CACHE_MAX_MEMORY_MB = 2.0

    # Memory pressure thresholds (percentage)
    MEMORY_PRESSURE_NORMAL = 70.0  # Below this is normal
    MEMORY_PRESSURE_MODERATE = 85.0  # Start considering eviction
    MEMORY_PRESSURE_HIGH = 95.0  # Aggressive eviction needed

    # Performance monitoring
    ENABLE_PERFORMANCE_MONITORING = True
    CACHE_STATS_LOG_INTERVAL = 300  # Log cache stats every 5 minutes

    # VFX pipeline settings
    DEFAULT_USERNAME = "gabriel-h"  # Default username for pipeline paths
    UNDISTORTION_SUBPATH = "mm"  # Subdirectory for undistortion files

    # File extensions
    IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".exr"]
    NUKE_EXTENSIONS = [".nk", ".nknc"]
    THREEDE_EXTENSIONS = [".3de"]

    # Path construction segments
    THUMBNAIL_SEGMENTS = ["publish", "editorial", "cutref", "v001", "jpg", "1920x1080"]
    RAW_PLATE_SEGMENTS = [
        "publish",
        "turnover",
        "plate",
        "input_plate",
    ]  # Removed bg01 for flexible discovery

    # Plate discovery patterns and priorities
    PLATE_DISCOVERY_PATTERNS = [
        "FG01",
        "FG02",
        "BG01",
        "BG02",
        "bg01",
        "fg01",
        "plate",
    ]  # Common plate naming

    # Turnover plate preferences (lower value = higher priority)
    TURNOVER_PLATE_PRIORITY = {
        "FG": 0,  # FG plates highest priority (FG01, FG02, etc.)
        "BG": 1,  # BG plates second priority (BG01, BG02, etc.)
        "EL": 2,  # Element plates third
        "*": 3,  # All others lowest priority
    }

    # Legacy plate priority (for backward compatibility)
    PLATE_PRIORITY_ORDER = {
        "FG01": 10,
        "fg01": 9,
        "FG02": 8,
        "BG01": 7,
        "bg01": 6,
        "BG02": 5,
    }  # Higher value = higher priority

    # Common color space patterns in plate names
    COLOR_SPACE_PATTERNS = ["aces", "lin_sgamut3cine", "lin_rec709", "rec709", "srgb"]
    UNDISTORTION_BASE_SEGMENTS = [
        "user",
        "mm",
        "3de",
        "mm-default",
        "exports",
        "scene",
        "bg01",
        "nuke_lens_distortion",
    ]
    THREEDE_SCENE_SEGMENTS = ["mm", "3de", "mm-default", "scenes", "scene"]

    # Alternative 3DE scene path patterns to try if main pattern fails
    THREEDE_ALTERNATIVE_PATTERNS = [
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
    THREEDE_ENV_VARS = [
        "THREEDE_SCENE_PATH",
        "3DE_SCENE_PATH",
        "TDE_SCENE_PATH",
        "MM_SCENE_PATH",
        "MATCHMOVE_SCENE_PATH",
    ]

    # Common VFX plate name patterns for intelligent grouping
    PLATE_NAME_PATTERNS = [
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
    SHOW_SEARCH_ENABLED = (
        True  # Enable searching all shots in shows (not just user's shots)
    )
    SHOW_ROOT_PATHS = ["/shows"]  # Root directories where shows are stored
    MAX_SHOTS_PER_SHOW = 1000  # Limit to prevent excessive searching in huge shows
    SKIP_SEQUENCE_PATTERNS = ["tmp", "temp", "test", "old", "archive", "_dev"]
    SKIP_SHOT_PATTERNS = ["tmp", "temp", "test", "old", "archive", "_dev"]

    # Progressive file scanning configuration
    PROGRESSIVE_SCAN_ENABLED = True  # Enable progressive/batched file scanning
    PROGRESSIVE_SCAN_BATCH_SIZE = 20  # Number of files to process per batch
    PROGRESSIVE_SCAN_MIN_BATCH_SIZE = 5  # Minimum batch size for last batch
    PROGRESSIVE_SCAN_MAX_BATCH_SIZE = 100  # Maximum batch size limit

    # Progress reporting configuration
    PROGRESS_UPDATE_INTERVAL_MS = 500  # Minimum time between progress updates (ms)
    PROGRESS_FILES_PER_UPDATE = 10  # Update progress every N files processed
    PROGRESS_ENABLE_ETA = True  # Enable ETA calculation and display
    PROGRESS_ETA_SMOOTHING_WINDOW = 5  # Number of samples for ETA smoothing

    # Worker thread configuration
    WORKER_CANCELLATION_CHECK_INTERVAL = 50  # Check for cancellation every N files
    WORKER_PAUSE_CHECK_INTERVAL_MS = 100  # Check for pause/resume every N ms
    WORKER_THREAD_PRIORITY = 0  # QThread priority (0=normal, -1=low, +1=high)
    WORKER_SHUTDOWN_TIMEOUT_MS = 5000  # Maximum time to wait for worker shutdown

    # Performance tuning for progressive scanning
    PROGRESSIVE_IO_YIELD_INTERVAL = 25  # Yield to other threads every N files
    PROGRESSIVE_MEMORY_CHECK_INTERVAL = 100  # Check memory usage every N files
    PROGRESSIVE_MAX_MEMORY_MB = 512  # Maximum memory usage during scanning

    # 3DE Scene Discovery Configuration (NEW - Efficient scanning)
    THREEDE_SCAN_MODE = "smart"  # Options: "full_show", "user_sequences", "smart"
    # - "full_show": Scan entire show (old behavior, can be slow)
    # - "user_sequences": Only scan sequences where user has shots
    # - "smart": Only scan shots that actually have .3de files (most efficient)

    THREEDE_MAX_SHOTS_TO_SCAN = 200  # Limit number of shots to scan for performance
    THREEDE_SCAN_RELATED_SEQUENCES = (
        True  # Only scan user's sequences (when in user_sequences mode)
    )
    THREEDE_FILE_FIRST_DISCOVERY = True  # Use new efficient file-first discovery
    THREEDE_SCAN_TIMEOUT_SECONDS = 30  # Maximum time for find command
    THREEDE_CACHE_DISCOVERED_SHOTS = True  # Cache which shots have .3de files
    THREEDE_INCREMENTAL_SCAN = False  # Only scan for changes (future feature)
