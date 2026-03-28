"""Centralized timeout configuration for ShotBot.

This module provides production-ready timeout values optimized for VFX workflows
dealing with network file systems, large data sets, and heavy applications.
"""

# Standard library imports
import logging
import os
from typing import ClassVar, cast


_logger = logging.getLogger(__name__)


class TimeoutConfig:
    """Timeout configuration for various operations in seconds."""

    _cleanup_order: ClassVar[int] = 42
    _singleton_description: ClassVar[str] = "Timeout configuration constants"

    # Store original values for reset (populated after class definition)
    initial_defaults: ClassVar[dict[str, int | float]] = {}

    # Command execution timeouts
    WORKSPACE_COMMAND_DEFAULT: int = 120  # 2 minutes for workspace commands
    WORKSPACE_COMMAND_HEAVY: int = 300  # 5 minutes for heavy operations
    APPLICATION_LAUNCH: int = 300  # 5 minutes for app launches
    SIMPLE_COMMAND: int = 30  # 30 seconds for simple commands

    # Process management timeouts
    PROCESS_GRACEFUL_TERMINATE: int = 10  # 10 seconds for graceful termination
    PROCESS_FORCE_KILL: int = 5  # 5 seconds after terminate before force kill
    PROCESS_STARTUP_VALIDATION: int = 30  # 30 seconds for app startup validation
    PROCESS_POLL_INTERVAL: float = 1.0  # 1 second between process checks

    # File system operation timeouts
    FILE_SEARCH_QUICK: int = 15  # 15 seconds for quick file checks
    FILE_SEARCH_STANDARD: int = 120  # 2 minutes for standard searches
    FILE_SEARCH_DEEP: int = 300  # 5 minutes for deep recursive searches
    FILE_NETWORK_OPERATION: int = 60  # 1 minute for network file operations

    # Session management timeouts
    SESSION_RECOVERY_MAX_WAIT: int = 30  # 30 seconds max for session recovery
    SESSION_COMMAND_DEFAULT: int = 120  # 2 minutes default for session commands
    SESSION_HEALTHCHECK: int = 5  # 5 seconds for health check commands

    # Cache and background operation timeouts
    CACHE_OPERATION: float = 5  # 5 seconds for cache operations
    BACKGROUND_TASK: int = 60  # 1 minute for background tasks
    CLEANUP_OPERATION: int = 10  # 10 seconds for cleanup operations

    # Shot model operation timeouts
    SHOT_WORKSPACE_COMMAND: int = 30  # 30 seconds for shot workspace commands
    SHOT_CACHE_OPERATION: int = 5  # 5 seconds for shot cache reads

    # Image processing timeouts
    IMAGE_TOOL_STANDARD: int = 30  # 30 seconds for ffmpeg/oiiotool operations

    # Filesystem coordination
    FILESYSTEM_CACHE_TTL: int = 300  # 5 minutes TTL for cached directory listings

    # Concurrent operation timeouts
    FUTURE_RESULT_QUICK: int = 5  # 5 seconds for quick future.result() calls

    # Worker lifecycle (milliseconds unless noted)
    WORKER_COORDINATION_STOP_MS: int = (
        5000  # Outer coordination wait (threede_worker_manager)
    )
    WORKER_GRACEFUL_STOP_MS: int = 2000  # Inner safe_stop / ThreadingConfig equivalent
    WORKER_TERMINATE_MS: int = 1000  # Time before force termination
    WORKER_SHUTDOWN_MS: int = 5000  # Maximum time to wait for worker shutdown
    WORKER_PAUSE_CHECK_MS: int = 100  # Check for pause/resume every N ms
    WORKER_POLL_INTERVAL_SEC: float = 0.1  # Polling interval for worker state checks

    # Launch / verification
    LAUNCH_VERIFICATION_SEC: float = 60.0  # How long to wait for app to start
    LAUNCH_VERIFICATION_POLL_SEC: float = 0.5  # How often to scan for process

    # Subprocess / session
    SUBPROCESS_SEC: float = 30.0  # General subprocess timeout
    SESSION_INIT_SEC: float = 2.0  # Timeout for session initialization
    BASH_WARMUP_SEC: int = 15  # First bash session initialization

    # Scanning
    THREEDE_SCAN_SEC: int = 60  # Timeout per directory scan (seconds)
    PREVIOUS_SHOTS_SCAN_SEC: int = 30  # Timeout per show scan (seconds)

    # UI notifications (milliseconds)
    NOTIFICATION_SUCCESS_MS: int = 3000  # Success message timeout in status bar
    NOTIFICATION_ERROR_MS: int = 5000  # Error message timeout in status bar
    NOTIFICATION_SETTINGS_MS: int = 2500  # Settings-saved notification timeout
    THUMBNAIL_UNLOAD_DELAY_MS: int = 5000  # Delay before unloading invisible thumbnails
    PROGRESS_UPDATE_INTERVAL_MS: int = 500  # Minimum time between progress updates (ms)

    # Polling
    POLL_INITIAL_SEC: float = 0.01  # 10ms - Initial polling interval
    POLL_MAX_SEC: float = 0.5  # 500ms - Maximum polling interval
    THREAD_POOL_SHUTDOWN_SEC: float = 5.0  # Thread pool operation timeout

    # File search stop
    FILE_SEARCH_STOP_MS: int = 1000  # Stop timeout for file search worker

    # Session warmer
    SESSION_WARMER_STOP_MS: int = 2000  # Stop timeout for session warmer thread

    # UI and interaction timeouts (in milliseconds)
    UI_OPERATION_MS: int = 5000  # 5 seconds for UI operations
    UI_ANIMATION_MS: int = 1000  # 1 second for animations
    UI_RESPONSE_MS: int = 500  # 500ms for UI responsiveness

    @classmethod
    def scale_timeouts(cls, factor: float) -> None:
        """Scale all timeouts by a factor for slower/faster environments.

        Args:
            factor: Scaling factor (e.g., 2.0 for double timeouts, 0.5 for half)

        """
        # Scale all class attributes that are timeout values
        for attr_name in dir(cls):
            # Use cast to provide explicit type hint for getattr result
            attr_value: object = cast("object", getattr(cls, attr_name))
            if (
                not attr_name.startswith("_")
                and not callable(attr_value)
                and attr_name.isupper()
                and isinstance(attr_value, int | float)
            ):
                # Don't scale millisecond values directly, they have _MS suffix
                if attr_name.endswith("_MS"):
                    setattr(cls, attr_name, int(attr_value * factor))
                else:
                    setattr(cls, attr_name, int(attr_value * factor))

    @classmethod
    def optimize_for_network_latency(cls, latency_ms: int) -> None:
        """Adjust timeouts based on network latency.

        Args:
            latency_ms: Network latency in milliseconds

        """
        if latency_ms > 100:  # High latency network
            # Increase file and network operation timeouts
            factor = 1 + (latency_ms / 100) * 0.5  # Scale factor based on latency
            cls.FILE_SEARCH_QUICK = int(cls.FILE_SEARCH_QUICK * factor)
            cls.FILE_SEARCH_STANDARD = int(cls.FILE_SEARCH_STANDARD * factor)
            cls.FILE_SEARCH_DEEP = int(cls.FILE_SEARCH_DEEP * factor)
            cls.FILE_NETWORK_OPERATION = int(cls.FILE_NETWORK_OPERATION * factor)
            cls.WORKSPACE_COMMAND_DEFAULT = int(cls.WORKSPACE_COMMAND_DEFAULT * factor)

    @classmethod
    def reset(cls) -> None:
        """Reset all timeout values to defaults. Used in test isolation."""
        for attr_name, default_value in cls.initial_defaults.items():
            setattr(cls, attr_name, default_value)


def _capture_timeout_defaults(cls: type[TimeoutConfig]) -> None:
    """Capture current TimeoutConfig class attribute values as reset defaults."""
    cls.initial_defaults = {
        attr: getattr(cls, attr)
        for attr in dir(cls)
        if not attr.startswith("_")
        and attr.isupper()
        and isinstance(getattr(cls, attr), (int, float))
    }


# Capture defaults after class definition
_capture_timeout_defaults(TimeoutConfig)

# Environment-based configuration
# Allow environment override for critical timeouts
if os.environ.get("SHOTBOT_TIMEOUT_SCALE"):
    try:
        scale = float(os.environ["SHOTBOT_TIMEOUT_SCALE"])
        TimeoutConfig.scale_timeouts(scale)
        _logger.info(f"Scaled all timeouts by factor of {scale}")
    except ValueError:
        pass

# Adjust for known slow network environments
if os.environ.get("SHOTBOT_NETWORK_LATENCY_MS"):
    try:
        latency = int(os.environ["SHOTBOT_NETWORK_LATENCY_MS"])
        TimeoutConfig.optimize_for_network_latency(latency)
        _logger.info(f"Optimized timeouts for {latency}ms network latency")
    except ValueError:
        pass
