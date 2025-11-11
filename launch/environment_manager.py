"""Environment management for application launching.

This module handles environment detection and configuration:
- Rez package manager availability
- Rez package mapping for applications
- Terminal emulator detection
"""

import logging
import os
import shutil
from typing import Final

from config import Config


logger = logging.getLogger(__name__)


class EnvironmentManager:
    """Manages launch environment configuration.

    This class provides stateless functions for detecting and configuring
    the launch environment. It handles:
    - Rez availability checking
    - Rez package mapping
    - Terminal emulator detection with caching

    All methods are instance methods to support caching, but operate
    independently without requiring shared state.
    """

    # Terminal preference order
    TERMINAL_PREFERENCE: Final[list[str]] = [
        "gnome-terminal",
        "konsole",
        "xterm",
        "x-terminal-emulator",
    ]

    def __init__(self) -> None:
        """Initialize EnvironmentManager with empty cache."""
        self._rez_available_cache: bool | None = None
        self._available_terminal_cache: str | None = None

    def is_rez_available(self, config: Config) -> bool:
        """Check if rez environment is available.

        Args:
            config: Application configuration

        Returns:
            True if rez is available and should be used

        Notes:
            - Checks config.USE_REZ_ENVIRONMENT first
            - If REZ_AUTO_DETECT enabled, checks REZ_USED environment variable
            - Otherwise checks if 'rez' command is available
            - Caches result for performance
        """
        if not config.USE_REZ_ENVIRONMENT:
            return False

        # Check for REZ_USED environment variable (indicates we're in a rez env)
        if config.REZ_AUTO_DETECT and os.environ.get("REZ_USED"):
            logger.debug("Rez detected via REZ_USED environment variable")
            return True

        # Return cached result if available
        if self._rez_available_cache is not None:
            return self._rez_available_cache

        # Check if rez command is available
        self._rez_available_cache = shutil.which("rez") is not None
        logger.debug(f"Rez availability cached: {self._rez_available_cache}")
        return self._rez_available_cache

    def get_rez_packages(self, app_name: str, config: Config) -> list[str]:
        """Get rez packages for the specified application.

        Args:
            app_name: Name of the application (nuke, maya, 3de)
            config: Application configuration

        Returns:
            List of rez packages to load for the application

        Notes:
            - Returns empty list for unknown applications
            - Packages are defined in Config.REZ_*_PACKAGES
        """
        package_map: dict[str, list[str]] = {
            "nuke": config.REZ_NUKE_PACKAGES,
            "maya": config.REZ_MAYA_PACKAGES,
            "3de": config.REZ_3DE_PACKAGES,
        }
        packages = package_map.get(app_name, [])
        logger.debug(f"Rez packages for {app_name}: {packages}")
        return packages

    def detect_terminal(self) -> str | None:
        """Detect available terminal emulator.

        Returns:
            Name of available terminal emulator, or None if none found

        Notes:
            - Checks terminals in preference order
            - Caches result for performance
            - Preference: gnome-terminal > konsole > xterm > x-terminal-emulator
        """
        # Return cached result if available
        if self._available_terminal_cache is not None:
            return self._available_terminal_cache

        # Check terminals in order of preference
        for term in self.TERMINAL_PREFERENCE:
            if shutil.which(term) is not None:
                self._available_terminal_cache = term
                logger.info(f"Detected terminal: {term}")
                return term

        # No terminal found
        logger.warning("No terminal emulator found")
        return None

    def reset_cache(self) -> None:
        """Reset cached environment detection results.

        Useful for testing or when environment changes are expected.
        """
        self._rez_available_cache = None
        self._available_terminal_cache = None
        logger.debug("EnvironmentManager cache reset")
