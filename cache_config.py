"""Cache configuration and directory management.

This module provides centralized cache directory configuration
that separates mock/test cache from production cache, and integrates
with SettingsManager for user-configurable cache settings.
"""

from __future__ import annotations

# Standard library imports
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, final

# Third-party imports
from PySide6.QtCore import QObject, Signal

# Local application imports
from logging_mixin import LoggingMixin, get_module_logger


# Module-level logger for static methods
logger = get_module_logger(__name__)

if TYPE_CHECKING:
    # Local application imports
    from settings_manager import SettingsManager


@final
class CacheConfig(LoggingMixin):
    """Manage cache directory configuration based on mode."""

    # Default cache directories
    PRODUCTION_CACHE_DIR = Path.home() / ".shotbot" / "cache"
    MOCK_CACHE_DIR = Path.home() / ".shotbot" / "cache_mock"
    TEST_CACHE_DIR = Path.home() / ".shotbot" / "cache_test"

    @staticmethod
    def get_cache_directory() -> Path:
        """Get the appropriate cache directory based on current mode.

        Returns:
            Path to cache directory (production, mock, or test)

        """
        # Check if we're in test mode (pytest or unittest running)
        if CacheConfig.is_test_mode():
            cache_dir = CacheConfig.TEST_CACHE_DIR
            logger.debug(f"Using TEST cache directory: {cache_dir}")
            return cache_dir

        # Check if we're in mock mode
        if CacheConfig.is_mock_mode():
            cache_dir = CacheConfig.MOCK_CACHE_DIR
            logger.debug(f"Using MOCK cache directory: {cache_dir}")
            return cache_dir

        # Default to production cache
        cache_dir = CacheConfig.PRODUCTION_CACHE_DIR
        logger.debug(f"Using PRODUCTION cache directory: {cache_dir}")
        return cache_dir

    @staticmethod
    def is_test_mode() -> bool:
        """Check if running in test mode.

        Returns:
            True if pytest or unittest is running

        """
        # Check for pytest
        if "pytest" in sys.modules:
            return True

        # Check for unittest
        if "unittest" in sys.modules and hasattr(sys, "_called_from_test"):
            return True

        # Check environment variable
        if os.environ.get("SHOTBOT_TEST_MODE", "").lower() in ("1", "true", "yes"):
            return True

        # Check if running from tests directory
        # Standard library imports
        import inspect

        frame = inspect.currentframe()
        while frame:
            code = frame.f_code
            if "/tests/" in code.co_filename or "\\tests\\" in code.co_filename:
                return True
            frame = frame.f_back

        return False

    @staticmethod
    def is_mock_mode() -> bool:
        """Check if running in mock mode.

        Returns:
            True if mock mode is enabled

        """
        # Check environment variable
        return os.environ.get("SHOTBOT_MOCK", "").lower() in ("1", "true", "yes")

    @staticmethod
    def is_headless_mode() -> bool:
        """Check if running in headless mode.

        Returns:
            True if headless mode is enabled

        """
        if os.environ.get("SHOTBOT_HEADLESS", "").lower() in ("1", "true", "yes"):
            return True

        # Check for CI environment
        ci_vars = ["CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "GITLAB_CI"]
        return any(os.environ.get(var) for var in ci_vars)

    @staticmethod
    def clear_test_cache() -> None:
        """Clear the test cache directory.

        Useful for ensuring clean state in tests.
        """
        # Standard library imports
        import shutil

        if CacheConfig.TEST_CACHE_DIR.exists():
            shutil.rmtree(CacheConfig.TEST_CACHE_DIR)
            logger.info(f"Cleared test cache: {CacheConfig.TEST_CACHE_DIR}")

    @staticmethod
    def clear_mock_cache() -> None:
        """Clear the mock cache directory.

        Useful for ensuring clean state in mock mode.
        """
        # Standard library imports
        import shutil

        if CacheConfig.MOCK_CACHE_DIR.exists():
            shutil.rmtree(CacheConfig.MOCK_CACHE_DIR)
            logger.info(f"Cleared mock cache: {CacheConfig.MOCK_CACHE_DIR}")

    @staticmethod
    def get_cache_info() -> dict[str, object]:
        """Get information about current cache configuration.

        Returns:
            Dictionary with cache configuration details

        """
        cache_dir = CacheConfig.get_cache_directory()

        info: dict[str, object] = {
            "cache_directory": str(cache_dir),
            "exists": cache_dir.exists(),
            "is_test_mode": CacheConfig.is_test_mode(),
            "is_mock_mode": CacheConfig.is_mock_mode(),
            "is_headless_mode": CacheConfig.is_headless_mode(),
        }

        if cache_dir.exists():
            # Calculate size
            total_size = 0
            file_count = 0
            for path in cache_dir.rglob("*"):
                if path.is_file():
                    total_size += path.stat().st_size
                    file_count += 1

            info["size_mb"] = round(total_size / (1024 * 1024), 2)
            info["file_count"] = file_count

        return info

    @staticmethod
    def migrate_cache(from_dir: Path, to_dir: Path) -> bool:
        """Migrate cache from one directory to another.

        Args:
            from_dir: Source cache directory
            to_dir: Destination cache directory

        Returns:
            True if successful

        """
        # Standard library imports
        import shutil

        if not from_dir.exists():
            logger.warning(f"Source cache directory does not exist: {from_dir}")
            return False

        try:
            # Ensure parent directory exists
            to_dir.parent.mkdir(parents=True, exist_ok=True)

            # Copy entire directory tree
            if to_dir.exists():
                shutil.rmtree(to_dir)

            _ = shutil.copytree(from_dir, to_dir)
            logger.info(f"Migrated cache from {from_dir} to {to_dir}")
            return True

        except Exception as e:
            logger.error(f"Failed to migrate cache: {e}")
            return False


@final
class UnifiedCacheConfig(LoggingMixin, QObject):
    """Unified cache configuration that integrates with SettingsManager.

    This class provides a single point of configuration for all cache components,
    ensuring they use consistent user-configurable settings instead of hardcoded values.

    Signals:
        memory_limit_changed: Emitted when memory limit changes (int: new_limit_mb)
        expiry_time_changed: Emitted when expiry time changes (int: new_expiry_minutes)
        config_updated: Emitted when any cache configuration changes
    """

    # Signals for configuration changes
    memory_limit_changed = Signal(int)  # new_limit_mb
    expiry_time_changed = Signal(int)  # new_expiry_minutes
    config_updated = Signal()

    def __init__(self, settings_manager: SettingsManager) -> None:
        """Initialize unified cache config with settings manager.

        Args:
            settings_manager: The application's settings manager

        """
        super().__init__()
        self._settings_manager = settings_manager

        # Connect to settings changes
        _ = self._settings_manager.settings_changed.connect(self._on_settings_changed)

        self.logger.debug("UnifiedCacheConfig initialized")

    @property
    def memory_limit_mb(self) -> int:
        """Get current memory limit in MB from user settings."""
        return self._settings_manager.get_max_cache_memory_mb()

    @property
    def memory_limit_bytes(self) -> int:
        """Get current memory limit in bytes from user settings."""
        return self.memory_limit_mb * 1024 * 1024

    @property
    def expiry_minutes(self) -> int:
        """Get current cache expiry time in minutes from user settings."""
        return self._settings_manager.get_cache_expiry_minutes()

    @property
    def expiry_seconds(self) -> int:
        """Get current cache expiry time in seconds from user settings."""
        return self.expiry_minutes * 60

    def get_memory_limit_mb(self) -> int:
        """Get memory limit in MB (method for backward compatibility)."""
        return self.memory_limit_mb

    def get_expiry_minutes(self) -> int:
        """Get expiry time in minutes (method for backward compatibility)."""
        return self.expiry_minutes

    def get_cache_config(self) -> dict[str, int]:
        """Get complete cache configuration dictionary.

        Returns:
            Dictionary with all cache configuration values

        """
        return {
            "memory_limit_mb": self.memory_limit_mb,
            "memory_limit_bytes": self.memory_limit_bytes,
            "expiry_minutes": self.expiry_minutes,
            "expiry_seconds": self.expiry_seconds,
        }

    def _on_settings_changed(self, setting_key: str, new_value: object) -> None:
        """Handle settings changes and emit appropriate signals.

        Args:
            setting_key: The settings key that changed
            new_value: The new value for the setting

        """
        if setting_key == "performance/max_cache_memory_mb" and isinstance(new_value, int | float | str):
            # Type narrowing for numeric values from QSettings
            self.logger.info(f"Cache memory limit changed to {new_value}MB")
            self.memory_limit_changed.emit(int(new_value))
            self.config_updated.emit()
        elif setting_key == "performance/cache_expiry_minutes" and isinstance(new_value, int | float | str):
            # Type narrowing for numeric values from QSettings
            self.logger.info(f"Cache expiry time changed to {new_value} minutes")
            self.expiry_time_changed.emit(int(new_value))
            self.config_updated.emit()

    # NOTE: ThumbnailManager methods removed after cache simplification
    # These were part of the old over-engineered cache system


# Global instance for easy access (initialized by CacheManager)
_unified_config: UnifiedCacheConfig | None = None


def get_unified_cache_config() -> UnifiedCacheConfig | None:
    """Get the global unified cache config instance.

    Returns:
        Global UnifiedCacheConfig instance or None if not initialized

    """
    return _unified_config


def set_unified_cache_config(config: UnifiedCacheConfig) -> None:
    """Set the global unified cache config instance.

    Args:
        config: UnifiedCacheConfig instance to set as global

    """
    global _unified_config  # noqa: PLW0603
    _unified_config = config
    logger.debug("Global unified cache config set")


def create_unified_cache_config(
    settings_manager: SettingsManager,
) -> UnifiedCacheConfig:
    """Create and set the global unified cache config.

    Args:
        settings_manager: Settings manager to use for configuration

    Returns:
        Created UnifiedCacheConfig instance

    """
    config = UnifiedCacheConfig(settings_manager)
    set_unified_cache_config(config)
    return config


# sys is now imported at the top of the file

# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Test cache directory detection
    print("Cache Configuration Test")
    print("=" * 50)

    # Normal mode
    cache_dir = CacheConfig.get_cache_directory()
    print(f"Normal mode cache: {cache_dir}")

    # Mock mode
    os.environ["SHOTBOT_MOCK"] = "1"
    cache_dir = CacheConfig.get_cache_directory()
    print(f"Mock mode cache: {cache_dir}")

    # Test mode
    os.environ["SHOTBOT_TEST_MODE"] = "1"
    cache_dir = CacheConfig.get_cache_directory()
    print(f"Test mode cache: {cache_dir}")

    # Get cache info
    print("\nCache Info:")
    info = CacheConfig.get_cache_info()
    for key, value in info.items():
        print(f"  {key}: {value}")
