#!/usr/bin/env python3
"""Headless mode support for CI/CD and testing environments.

This module provides utilities to run ShotBot without a display,
enabling automated testing in CI/CD pipelines and headless servers.
"""

from __future__ import annotations

# Standard library imports
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Third-party imports
from typing_extensions import TypeVar

# Local application imports
from logging_mixin import get_module_logger


if TYPE_CHECKING:
    # Standard library imports

    # Third-party imports
    from PySide6.QtWidgets import QApplication

# Module-level logger for static methods
logger = get_module_logger(__name__)

# Type variables for proper generic typing
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
        if Path("/.dockerenv").exists():
            logger.info("Docker environment detected - assuming headless")
            return True

        # Check for WSL without display
        if "microsoft-standard" in os.uname().release.lower() and not os.environ.get(
            "DISPLAY"
        ):
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
