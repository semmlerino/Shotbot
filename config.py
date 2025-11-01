#!/usr/bin/env python3
"""
Configuration Constants for PyFFMPEG
Centralizes all magic numbers and configuration values for better maintainability
"""


# Process Management Constants
class ProcessConfig:
    """Process and threading related constants"""

    # Maximum parallel processes for different system tiers
    MAX_PARALLEL_HIGH_END = 14  # For high-end systems (RTX 4090, etc.) - Optimized for i9-14900HX + RTX 4090
    MAX_PARALLEL_DEFAULT = 4  # Default maximum parallel processes

    # GPU encoding limits
    MAX_GPU_SLOTS = (
        12  # RTX 4090 can handle up to 12 encodes (4 per NVENC engine) with 16GB VRAM
    )
    NVENC_ENGINES_PER_GPU = 3  # Number of NVENC engines per GPU

    # Thread management
    MIN_THREADS_PER_PROCESS = 2  # Minimum threads for any encoding process
    OPTIMAL_CPU_THREADS = (
        32  # Optimal thread count for CPU encoding on i9-14900HX (32 threads)
    )

    # Process timeout values (in seconds)
    SUBPROCESS_TIMEOUT = 30  # Timeout for subprocess calls
    PROCESS_START_TIMEOUT = 5  # Timeout for process startup
    PROCESS_KILL_TIMEOUT = 3  # Timeout when killing processes


# UI Update and Timer Constants
class UIConfig:
    """UI update timing and behavior constants"""

    # Timer intervals (in milliseconds)
    UI_UPDATE_DEFAULT = (
        400  # Default UI update interval - optimized for high-end system
    )
    UI_UPDATE_HIGH_ACTIVITY = (
        150  # Fast updates for high activity (4+ processes) - smoother on RTX 4090
    )
    UI_UPDATE_LOW_ACTIVITY = 1000  # Slow updates for low activity
    UI_UPDATE_FALLBACK = 1000  # Fallback timer interval for MainWindow

    # UI response delays
    WIDGET_REMOVAL_DELAY = 5000  # Delay before removing process widgets (ms)
    STOPPED_WIDGET_DELAY = 3000  # Delay for stopped process widgets (ms)

    # Activity timing
    LOW_ACTIVITY_THRESHOLD = (
        5  # Seconds of inactivity before considering "low activity"
    )
    FORCE_UPDATE_INTERVAL = 3  # Force ETA update every N seconds


# Memory and Log Management Constants
class LogConfig:
    """Log size limits and memory management"""

    # Main application log limits
    MAIN_LOG_MAX_SIZE = 20000  # Maximum characters in main log - optimized for 32GB RAM
    MAIN_LOG_TRUNCATE_LINES = 100  # Lines to keep when truncating main log

    # Process-specific log limits
    PROCESS_LOG_MAX_SIZE = (
        10000  # Maximum characters per process log - optimized for 32GB RAM
    )
    PROCESS_LOG_TRUNCATE_LINES = 50  # Lines to keep when truncating process logs

    # Log history limits for ProcessManager
    MAX_LOG_HISTORY = (
        5000  # Maximum log entries to keep in memory - optimized for 32GB RAM
    )
    TRUNCATE_LOG_HISTORY = 2500  # Truncate to this many entries

    # Memory cleanup thresholds
    MAX_PROCESS_WIDGETS = (
        16  # Maximum concurrent process widgets - matches parallel capacity
    )
    MAX_LOG_TABS = 14  # Maximum process log tabs - optimized for high-end system


# Encoding and Quality Constants
class EncodingConfig:
    """Video encoding quality and performance settings"""

    # Default quality settings
    DEFAULT_CRF_H264 = (
        16  # Default CRF for H.264 - higher quality for powerful hardware
    )
    DEFAULT_CRF_FALLBACK = 23  # Fallback CRF value

    # Bitrate settings (in kbps)
    AUDIO_BITRATE_DEFAULT = (
        256  # Default audio bitrate - higher quality for powerful hardware
    )

    # Performance presets
    PRESET_FAST = "fast"  # Fast encoding preset
    PRESET_MEDIUM = "medium"  # Medium encoding preset
    PRESET_SLOW = "slow"  # Slow encoding preset

    # Auto-balance distribution ratios
    GPU_RATIO_DEFAULT = 0.85  # 85% of files to GPU for RTX 4090 (exceptional GPU power)
    CPU_RATIO_DEFAULT = 0.15  # 15% of files to CPU by default


# Hardware Detection Constants
class HardwareConfig:
    """Hardware detection and capability constants"""

    # System capability thresholds
    HIGH_END_CPU_CORES = 24  # CPU cores to consider "high-end" - matches i9-14900HX

    # RTX GPU models that support AV1 NVENC
    RTX40_MODELS = ["RTX 40", "4090", "4080", "4070"]

    # Hardware acceleration timeout
    GPU_DETECTION_TIMEOUT = 10  # Seconds to wait for GPU detection


# File and Path Constants
class FileConfig:
    """File handling and path constants"""

    # Supported file extensions
    SUPPORTED_VIDEO_EXTENSIONS = [".ts", ".mp4", ".m4v", ".mov"]

    # Output file suffix
    OUTPUT_SUFFIX = "_RC"  # Suffix added to converted files

    # File size estimation factors (MB per minute)
    SIZE_FACTOR_H264 = 8  # H.264 estimated size
    SIZE_FACTOR_HEVC = 8  # HEVC estimated size
    SIZE_FACTOR_AV1 = 6  # AV1 estimated size
    SIZE_FACTOR_X264 = 5  # x264 estimated size
    SIZE_FACTOR_PRORES_422 = 50  # ProRes 422 estimated size
    SIZE_FACTOR_PRORES_4444 = 80  # ProRes 4444 estimated size
    SIZE_FACTOR_DEFAULT = 10  # Default fallback size factor


# Application Settings
class AppConfig:
    """Application-wide configuration"""

    # Application metadata
    APP_NAME = "PyFFMPEG Video Converter"
    APP_VERSION = "2.1"
    APP_DESCRIPTION = "RTX Advanced Hybrid Encoding"

    # Window settings
    DEFAULT_WINDOW_WIDTH = 1000
    DEFAULT_WINDOW_HEIGHT = 700

    # Settings keys for QSettings
    SETTINGS_ORG = "MyCompany"
    SETTINGS_APP = "TsConverterGuiSeq"
