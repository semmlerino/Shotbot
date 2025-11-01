#!/usr/bin/env python3
"""ShotBot - VFX Shot Launcher Application Entry Point.

This module serves as the main entry point for the ShotBot VFX shot browsing
and application launcher. ShotBot provides a graphical interface for VFX artists
to browse shots, view thumbnails, discover 3DE scenes, and launch applications
in the correct shot workspace context.

Application Overview:
    ShotBot integrates with VFX pipeline tools using the `ws` (workspace) command
    to list and navigate shots. It provides visual thumbnail grids, background
    scene discovery, and a flexible custom launcher system for workflow automation.

Key Components Initialized:
    - Qt Application: PySide6 QApplication with proper platform settings
    - Logging System: File and console logging with environment-based levels
    - Main Window: Tabbed interface with shot grids and launcher management
    - Cache Manager: Thread-safe caching for thumbnails and data persistence
    - Background Workers: Non-blocking threads for scene discovery and data refresh

Environment Variables:
    SHOTBOT_DEBUG: Set to enable debug-level console logging
        Example: SHOTBOT_DEBUG=1 python shotbot.py

    QT_QPA_PLATFORM: Qt platform abstraction (auto-detected)
    DISPLAY: X11 display for Linux environments (WSL compatibility)

Usage:
    Command line execution:
        $ python shotbot.py                    # Standard execution
        $ SHOTBOT_DEBUG=1 python shotbot.py    # Debug mode
        $ rez env PySide6_Essentials -- python3 shotbot.py  # Rez environment

    Programmatic usage:
        >>> import sys
        >>> from PySide6.QtWidgets import QApplication
        >>> from main_window import MainWindow
        >>> app = QApplication(sys.argv)
        >>> window = MainWindow()
        >>> window.show()
        >>> sys.exit(app.exec())

Dependencies:
    - PySide6: Qt for Python GUI framework
    - Python 3.8+: Modern Python with type annotation support
    - ws command: VFX workspace tool (must be available in shell)
    - Standard library: pathlib, logging, subprocess, threading

Error Handling:
    The application includes comprehensive error handling for:
    - Missing workspace commands (graceful degradation)
    - File system permission issues (user notification)
    - Qt platform initialization failures (fallback strategies)
    - Network and I/O timeouts (configurable limits)

Thread Safety:
    All background operations use Qt's thread-safe signal/slot mechanism.
    The main UI thread remains responsive during intensive operations like
    thumbnail loading and scene discovery.
"""

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from main_window import MainWindow


def setup_logging():
    """Configure logging for the application."""
    # Create logs directory
    log_dir = Path.home() / ".shotbot" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Configure logging
    log_file = log_dir / "shotbot.log"

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Set to DEBUG to allow all messages through

    # File handler for all logs
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console handler - check for debug environment variable
    console_handler = logging.StreamHandler()
    console_level = (
        logging.DEBUG if os.environ.get("SHOTBOT_DEBUG") else logging.WARNING
    )
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Log startup
    logger = logging.getLogger(__name__)
    logger.info("ShotBot logging initialized")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Console log level: {logging.getLevelName(console_level)}")
    if console_level == logging.DEBUG:
        logger.debug("Debug logging is enabled in console")


def main():
    """Main entry point."""
    # Initialize logging first
    setup_logging()

    # Create application
    app = QApplication(sys.argv)

    # Set application info
    app.setApplicationName("ShotBot")
    app.setOrganizationName("VFX")

    # Set dark theme
    app.setStyle("Fusion")

    # Dark palette
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()

    # Window colors
    palette.setColor(QPalette.ColorRole.Window, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)

    # Base colors (for input widgets)
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 35))

    # Text colors
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)

    # Button colors
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)

    # Highlight colors
    palette.setColor(QPalette.ColorRole.Highlight, QColor(13, 115, 119))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)

    # Disabled colors
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(127, 127, 127),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(127, 127, 127)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(127, 127, 127),
    )

    app.setPalette(palette)

    # Create and show main window
    window = MainWindow()
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
