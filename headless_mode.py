#!/usr/bin/env python3
"""Headless mode support for CI/CD and testing environments.

This module provides utilities to run ShotBot without a display,
enabling automated testing in CI/CD pipelines and headless servers.
"""

from __future__ import annotations

# Standard library imports
import logging
import os
import sys
from typing import TYPE_CHECKING

# Third-party imports
from typing_extensions import ParamSpec, TypeVar

# Local application imports
from logging_mixin import get_module_logger

if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable

    # Third-party imports
    from PySide6.QtWidgets import QApplication

    # Local application imports
    from shot_model import Shot

# Module-level logger for static methods
logger = get_module_logger(__name__)

# Type variables for proper generic typing
P = ParamSpec("P")
T = TypeVar("T")


class HeadlessMode:
    """Manage headless mode configuration and detection."""

    @staticmethod
    def is_headless_environment() -> bool:
        """Detect if running in a headless environment.

        Returns:
            True if running in headless environment
        """
        # Check explicit headless flag
        if os.environ.get("SHOTBOT_HEADLESS", "").lower() in ("1", "true", "yes"):
            return True

        # Check for CI environment variables
        ci_vars = [
            "CI",
            "CONTINUOUS_INTEGRATION",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "JENKINS_URL",
            "TRAVIS",
            "CIRCLECI",
            "BITBUCKET_BUILD_NUMBER",
            "TEAMCITY_VERSION",
        ]

        for var in ci_vars:
            if os.environ.get(var):
                logger.info(f"CI environment detected: {var}={os.environ[var]}")
                return True

        # Check if display is available
        if sys.platform != "win32":
            display = os.environ.get("DISPLAY")
            if not display:
                logger.info("No DISPLAY environment variable - assuming headless")
                return True

        # Check for specific headless indicators
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return True

        # Check if running in Docker/container (common for CI)
        if os.path.exists("/.dockerenv"):
            logger.info("Docker environment detected - assuming headless")
            return True

        # Check for WSL without display
        if "microsoft-standard" in os.uname().release.lower():
            if not os.environ.get("DISPLAY"):
                logger.info("WSL without DISPLAY - assuming headless")
                return True

        return False

    @staticmethod
    def configure_qt_for_headless() -> None:
        """Configure Qt for headless operation.

        Sets environment variables needed for Qt to run without a display.
        """
        # Use offscreen platform plugin
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

        # Disable GPU acceleration for offscreen
        os.environ["QT_QUICK_BACKEND"] = "software"
        os.environ["QT_XCB_GL_INTEGRATION"] = "none"

        # Suppress warnings about missing display
        os.environ["QT_LOGGING_RULES"] = "qt.qpa.xcb.warning=false"

        # For better compatibility
        os.environ["QT_QPA_FONTDIR"] = "/usr/share/fonts"

        logger.info("Qt configured for headless operation (offscreen platform)")

    @staticmethod
    def create_headless_application(argv: list[str] | None = None) -> QApplication:
        """Create a QApplication configured for headless operation.

        Args:
            argv: Command line arguments

        Returns:
            QApplication configured for headless mode
        """
        # Third-party imports
        from PySide6.QtCore import QCoreApplication, Qt
        from PySide6.QtWidgets import QApplication

        if argv is None:
            argv = sys.argv

        # Configure Qt for headless
        HeadlessMode.configure_qt_for_headless()

        # Set application attributes before creating QApplication
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

        # Create application with offscreen platform
        app = QApplication(argv)

        # Set application info
        app.setApplicationName("ShotBot-Headless")
        app.setOrganizationName("VFX")

        logger.info("Created headless QApplication")

        return app

    @staticmethod
    def patch_for_headless(obj: object) -> None:
        """Patch an object to work in headless mode.

        This disables or mocks UI operations that would fail without a display.

        Args:
            obj: Object to patch (typically MainWindow or similar)
        """
        # Common patches for headless operation
        patches = {
            "show": lambda: None,
            "raise_": lambda: None,
            "activateWindow": lambda: None,
            "setFocus": lambda: None,
            "repaint": lambda: None,
            "update": lambda: None,
        }

        for method_name, mock_func in patches.items():
            if hasattr(obj, method_name):
                setattr(obj, method_name, mock_func)
                logger.debug(
                    f"Patched {obj.__class__.__name__}.{method_name} for headless"
                )

    @staticmethod
    def is_display_available() -> bool:
        """Check if a display is actually available for rendering.

        Returns:
            True if display is available and working
        """
        if HeadlessMode.is_headless_environment():
            return False

        # Try to import Qt and check if we can create widgets
        try:
            # Third-party imports
            from PySide6.QtCore import QCoreApplication

            # If application already exists, display is likely available
            if QCoreApplication.instance():
                return True

            # Otherwise, we can't easily test without side effects
            # Assume display is available if not in headless mode
            return True

        except Exception as e:
            logger.warning(f"Could not check display availability: {e}")
            return False

    @staticmethod
    def skip_if_headless(func: Callable[P, T]) -> Callable[P, T | None]:
        """Decorator to skip function execution in headless mode.

        Useful for UI operations that should be skipped when no display.

        Args:
            func: Function to wrap

        Returns:
            Wrapped function that skips in headless mode
        """

        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | None:
            if HeadlessMode.is_headless_environment():
                logger.debug(f"Skipping {func.__name__} in headless mode")
                return None
            return func(*args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    @staticmethod
    def require_display(func: Callable[P, T]) -> Callable[P, T]:
        """Decorator that raises an error if no display is available.

        Use for functions that absolutely require a display.

        Args:
            func: Function to wrap

        Returns:
            Wrapped function that checks for display
        """

        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if not HeadlessMode.is_display_available():
                raise RuntimeError(
                    f(("{func.__name__} requires a display but none is available. "
                    "Run with SHOTBOT_HEADLESS=1 to use headless mode."))
                )
            return func(*args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper


class HeadlessMainWindow:
    """Minimal MainWindow for headless testing.

    This provides a simplified MainWindow that can run without a display,
    useful for testing core functionality without UI.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize headless main window."""
        super().__init__()
        # Local application imports
        from cache_manager import CacheManager
        from mock_workspace_pool import create_mock_pool_from_filesystem
        from shot_model import ShotModel

        # Create mock pool for headless testing
        mock_pool = create_mock_pool_from_filesystem()

        # Create core components
        self.cache_manager = CacheManager()
        self.shot_model = ShotModel(self.cache_manager, process_pool=mock_pool)

        # Mock UI methods
        self.show: Callable[[], None] = lambda: None
        self.close: Callable[[], None] = lambda: None
        self.resize: Callable[[int, int], None] = lambda w, h: None
        self.setWindowTitle: Callable[[str], None] = lambda title: None

        logger.info("HeadlessMainWindow initialized")

    def refresh_shots(self) -> bool:
        """Refresh shot list.

        Returns:
            True if successful
        """
        success, _ = self.shot_model.refresh_shots()
        return success

    def get_shots(self) -> list[Shot]:
        """Get current shots.

        Returns:
            List of shots
        """
        # Local application imports

        return self.shot_model.shots


def run_headless_app() -> bool:
    """Run the application in headless mode for testing."""
    # Third-party imports
    from PySide6.QtCore import QTimer

    # Configure headless mode
    HeadlessMode.configure_qt_for_headless()

    # Create headless application
    app = HeadlessMode.create_headless_application()

    # Create headless main window
    window = HeadlessMainWindow()

    # Run basic operations
    logger.info("Running headless application...")

    # Refresh shots
    if window.refresh_shots():
        shots = window.get_shots()
        logger.info(f"Loaded {len(shots)} shots in headless mode")
        for shot in shots[:3]:  # Show first 3
            logger.info(f"  - {shot}")

    # Exit after a short delay
    QTimer.singleShot(100, app.quit)

    # Run event loop briefly
    return app.exec() == 0


# Example usage and testing
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Check headless detection
    if HeadlessMode.is_headless_environment():
        logger.info("🖥️  Headless environment detected")
    else:
        logger.info("🖥️  Display environment detected")

    # Try running headless
    if "--run" in sys.argv:
        sys.exit(0 if run_headless_app() else 1)
