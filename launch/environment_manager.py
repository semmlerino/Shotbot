"""Environment management for application launching.

This module handles environment detection and configuration:
- Rez package manager availability
- Rez package mapping for applications
- Terminal emulator detection
"""

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
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

    # Terminal preference order (common VFX facility terminals)
    TERMINAL_PREFERENCE: Final[list[str]] = [
        "gnome-terminal",
        "konsole",
        "xfce4-terminal",
        "mate-terminal",
        "alacritty",
        "kitty",
        "terminology",
        "xterm",
        "x-terminal-emulator",
    ]

    # X11-based terminals that require DISPLAY environment variable
    # These will fail on headless/WSL systems without X11 forwarding
    X11_TERMINALS: Final[set[str]] = {
        "gnome-terminal",
        "konsole",
        "xfce4-terminal",
        "mate-terminal",
        "terminology",
        "xterm",
        "x-terminal-emulator",
    }

    # Cache TTL for terminal detection (5 minutes)
    TERMINAL_CACHE_TTL_SEC: Final[float] = 300.0

    # Brief wait for cache warming to complete (avoids 2s subprocess block on fast launch)
    _CACHE_WARM_WAIT_SEC: float = 0.15

    # Timeout for ws availability check (reduced from 5.0s to improve UI responsiveness)
    # VFX facility shells may take longer due to NFS mounts, AD/LDAP auth, rez init
    # 2s is sufficient for most environments; if it times out, we use optimistic fallback
    WS_AVAILABILITY_TIMEOUT_SEC: float = 2.0

    def __init__(self) -> None:
        """Initialize EnvironmentManager with empty cache."""
        self._rez_available_cache: bool | None = None
        self._ws_available_cache: bool | None = None
        self._available_terminal_cache: str | None = None
        self._terminal_cache_time: float = 0.0
        self._cache_warm_event: threading.Event = threading.Event()

    def is_rez_available(self, config: "type[Config]") -> bool:
        """Check if rez wrapping should be applied to commands.

        This is a compatibility wrapper around should_wrap_with_rez() which
        uses the modern RezMode enum configuration.

        Args:
            config: Application configuration

        Returns:
            True if rez wrapping should be applied, False to skip wrapping

        """
        return self.should_wrap_with_rez(config)

    def should_wrap_with_rez(self, config: "type[Config]") -> bool:
        """Determine if commands should be wrapped with rez environment.

        Uses the new RezMode enum for cleaner configuration:
            - DISABLED: Never wrap with rez
            - AUTO: Resolve configured app packages for each DCC launch
            - FORCE: Always wrap with app-specific packages

        Args:
            config: Application configuration

        Returns:
            True if rez wrapping should be applied, False to skip wrapping

        """
        from config import RezMode

        # DISABLED mode: never wrap
        if config.REZ_MODE == RezMode.DISABLED:
            logger.debug("Rez wrapping DISABLED via RezMode.DISABLED")
            return False

        if config.REZ_MODE == RezMode.AUTO and os.environ.get("REZ_USED"):
            logger.debug(
                "REZ_USED is set, but launcher will still resolve explicit app packages"
            )

        # AUTO/FORCE mode: require the rez command to be available
        if self._rez_available_cache is None:
            self._rez_available_cache = shutil.which("rez") is not None

        if not self._rez_available_cache:
            logger.warning("Rez wrapping unavailable: 'rez' command not found in PATH")
            return False

        logger.debug("Rez wrapping ENABLED")
        return True

    def is_ws_available(self) -> bool:
        """Check if ws (workspace) command is available.

        Returns:
            True if ws command is available (shell function, alias, or binary)

        The ws command is a BlueBolt VFX facility shell function that:
            - Is an alias to 'workspace' function defined in interactive shell
            - Takes a workspace path as argument (e.g., ws /shows/show/shots/seq/shot)
            - Generates and sources a temporary file that sets:
              SHOW, SEQUENCE, SHOT, WORKSPACE_PATH variables
            - Sources hierarchical env.sh files for show/sequence/shot config
            - Does NOT handle Rez (Rez is set up by shell init before ws runs)

        Detection uses bash -lc because ws is a shell function defined
        in the interactive shell profile (.bashrc), not a binary on PATH.
        shutil.which() only finds binaries, so we need bash to detect the function.

        """
        if self._ws_available_cache is not None:
            return self._ws_available_cache

        # If cache warming is in progress, wait briefly for it to complete
        # This avoids a 2-second subprocess block if user launches immediately after startup
        if not self._cache_warm_event.is_set():
            _ = self._cache_warm_event.wait(timeout=self._CACHE_WARM_WAIT_SEC)
            # Check again after waiting - warming thread may have populated cache
            if self._ws_available_cache is not None:
                return self._ws_available_cache

        # Use bash interactive login shell to check for ws - handles binaries, functions, and aliases
        # shutil.which() only finds binaries, but ws is often a shell function in VFX studios
        # CRITICAL: Use -ilc (interactive login) to match actual launch behavior.
        # The ws function is defined in .bashrc which is only sourced in interactive shells.
        # Using -lc (non-interactive login) can false-negative if .bash_profile doesn't source .bashrc.
        try:
            result = subprocess.run(
                ["bash", "-ilc", "command -v ws"],
                check=False, capture_output=True,
                text=True,
                timeout=self.WS_AVAILABILITY_TIMEOUT_SEC,
            )
            self._ws_available_cache = result.returncode == 0
        except subprocess.TimeoutExpired:
            # Optimistic fallback: assume ws is available
            # If it doesn't exist, the actual launch will fail with a clear error
            logger.warning(
                "ws availability check timed out after %.1fs. "
                "Assuming ws is available (will fail with clear error if not).",
                self.WS_AVAILABILITY_TIMEOUT_SEC,
            )
            self._ws_available_cache = True
        except OSError:
            logger.warning("Failed to check ws availability", exc_info=True)
            # Fall back to shutil.which (better than nothing)
            self._ws_available_cache = shutil.which("ws") is not None

        logger.debug(f"ws availability cached: {self._ws_available_cache}")
        return self._ws_available_cache

    def get_rez_packages(self, app_name: str, config: "type[Config]") -> list[str]:
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
            "rv": config.REZ_RV_PACKAGES,
            "publish": config.REZ_PUBLISH_PACKAGES,
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
            - Caches result for performance with 5-minute TTL
            - Preference: gnome-terminal > konsole > xterm > x-terminal-emulator
            - Skips X11 terminals when DISPLAY is not set (headless/WSL)

        """
        # Return cached result if not expired (cache_time > 0 means detection was performed)
        current_time = time.monotonic()
        if (
            self._terminal_cache_time > 0
            and current_time - self._terminal_cache_time < self.TERMINAL_CACHE_TTL_SEC
        ):
            return self._available_terminal_cache

        # Check if X11 display is available
        display = os.environ.get("DISPLAY")
        has_display = bool(display)

        if not has_display:
            logger.debug("No DISPLAY set - X11 terminals will be skipped")

        # Check terminals in order of preference
        for term in self.TERMINAL_PREFERENCE:
            if shutil.which(term) is not None:
                # Skip X11 terminals if no DISPLAY (prevents infinite failure loop)
                if term in self.X11_TERMINALS and not has_display:
                    logger.debug(f"Skipping {term}: requires DISPLAY (not set)")
                    continue

                self._available_terminal_cache = term
                self._terminal_cache_time = current_time
                logger.info(f"Detected terminal: {term}")
                return term

        # No terminal found - cache the None result too
        self._available_terminal_cache = None
        self._terminal_cache_time = current_time
        logger.warning("No terminal emulator found")
        return None

    def reset_cache(self) -> None:
        """Reset cached environment detection results.

        Useful for testing or when environment changes are expected.
        """
        self._rez_available_cache = None
        self._ws_available_cache = None
        self._available_terminal_cache = None
        self._terminal_cache_time = 0.0
        self._cache_warm_event.clear()
        logger.debug("EnvironmentManager cache reset")

    def warm_cache_async(self) -> None:
        """Pre-warm environment caches in background thread.

        Call this at startup to avoid blocking the main thread on first
        environment checks. The caches will be populated in the background
        and subsequent calls to is_rez_available(), is_ws_available(), and
        detect_terminal() will return immediately from cache.

        Sets _cache_warm_event when complete so is_ws_available() can avoid
        blocking if called during warmup.
        """
        def _warm() -> None:
            try:
                # These calls will populate the caches
                _ = self.is_ws_available()
                _ = self.detect_terminal()
                logger.debug("Environment caches pre-warmed successfully")
            except Exception:  # noqa: BLE001
                logger.warning("Error during cache pre-warming", exc_info=True)
            finally:
                # Always signal completion so waiters don't block forever
                self._cache_warm_event.set()

        thread = threading.Thread(target=_warm, daemon=True, name="EnvironmentCacheWarm")
        thread.start()
