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

# Standard library imports
import argparse
import logging
import os
import sys
from pathlib import Path
from typing import cast


def setup_logging() -> None:
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

    # Suppress PIL/Pillow debug logging - it's too verbose
    # PIL loads all its plugins on import and logs debug messages for each one
    pil_logger = logging.getLogger("PIL")
    pil_logger.setLevel(logging.INFO)  # Only show INFO and above from PIL

    # Also suppress the Image module specifically
    pil_image_logger = logging.getLogger("PIL.Image")
    pil_image_logger.setLevel(logging.INFO)

    # Suppress PngImagePlugin debug messages
    pil_png_logger = logging.getLogger("PIL.PngImagePlugin")
    pil_png_logger.setLevel(logging.INFO)

    # Suppress all PIL plugin loggers - comprehensive list
    for plugin_name in [
        "PIL.BmpImagePlugin",
        "PIL.GifImagePlugin",
        "PIL.JpegImagePlugin",
        "PIL.PpmImagePlugin",
        "PIL.TiffImagePlugin",
        "PIL.WebPImagePlugin",
        "PIL.PcxImagePlugin",
        "PIL.SgiImagePlugin",
        "PIL.IcoImagePlugin",
        "PIL.ImImagePlugin",
        "PIL.ImtImagePlugin",
        "PIL.MspImagePlugin",
        "PIL.PcdImagePlugin",
        "PIL.TgaImagePlugin",
        "PIL.XbmImagePlugin",
        "PIL.XpmImagePlugin",
        "PIL.XVThumbImagePlugin",
        "PIL.FliImagePlugin",
        "PIL.FpxImagePlugin",
        "PIL.GbrImagePlugin",
        "PIL.CurImagePlugin",
        "PIL.DcxImagePlugin",
        "PIL.FitsImagePlugin",
        "PIL.FtexImagePlugin",
        "PIL.GdImageFile",
        "PIL.IptcImagePlugin",
        "PIL.McIdasImagePlugin",
        "PIL.MicImagePlugin",
        "PIL.MpegImagePlugin",
        "PIL.PixarImagePlugin",
        "PIL.PsdImagePlugin",
        "PIL.SunImagePlugin",
        "PIL.EpsImagePlugin",
        "PIL.IcnsImagePlugin",
        "PIL.SpiderImagePlugin",
        "PIL.PalmImagePlugin",
        "PIL.PdfImagePlugin",
        "PIL.BlpImagePlugin",
        "PIL.DdsImagePlugin",
        "PIL.Hdf5StubImagePlugin",
        "PIL.WmfImagePlugin",
        "PIL.QoiImagePlugin",
    ]:
        plugin_logger = logging.getLogger(plugin_name)
        plugin_logger.setLevel(logging.INFO)

    # Log startup (debug level - logging init is a low-level detail)
    logger = logging.getLogger(__name__)
    logger.debug(f"Logging initialized: {log_file} (console: {logging.getLevelName(console_level)})")


def main() -> None:
    """Main entry point."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="ShotBot - VFX Shot Launcher Application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  shotbot.py              # Run normally (requires ws command)
  shotbot.py --mock       # Run with mock VFX data (no ws needed)

Environment Variables:
  SHOTBOT_DEBUG=1         # Enable debug logging
  SHOTBOT_MOCK=1          # Enable mock mode via environment
""",
    )
    _ = parser.add_argument(
        "--mock",
        action="store_true",
        help="Run with mock VFX data (no ws command needed)",
    )
    _ = parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode without display (for CI/CD testing)",
    )
    _ = parser.add_argument(
        "--screenshot",
        type=int,
        metavar="SECONDS",
        help="Auto-capture screenshot after N seconds and save to C:\\temp\\shotbot_auto.png",
    )
    args = parser.parse_args()

    # Cast argparse attributes to explicit types for type checker
    headless_flag = cast("bool", args.headless)
    mock_flag = cast("bool", args.mock)
    screenshot_seconds = cast("int | None", args.screenshot)

    # Initialize logging first - BEFORE any imports that might trigger PIL
    setup_logging()

    logger = logging.getLogger(__name__)
    logger.info(f"ShotBot starting (PID: {os.getpid()})")

    # Check for headless mode
    headless_mode = headless_flag or os.environ.get("SHOTBOT_HEADLESS", "").lower() in (
        "1",
        "true",
        "yes",
    )

    # Check for mock mode from either command line or environment
    from config import is_mock_mode
    mock_mode = mock_flag or is_mock_mode()

    if headless_mode:
        logger.debug("Headless mode enabled")
        # Local application imports
        from headless_mode import HeadlessMode

        HeadlessMode.configure_qt_for_headless()

        # Headless mode usually wants mock data too
        if not mock_mode:
            logger.debug("Enabling mock mode for headless operation")
            mock_mode = True

    if mock_mode:
        logger.debug("Mock mode enabled")
        # Set environment variable so all code knows we're in mock mode
        os.environ["SHOTBOT_MOCK"] = "1"
        # MainWindow will detect SHOTBOT_MOCK and create MockWorkspacePool

    # Now import Qt and main window AFTER logging is configured
    # This ensures PIL logging is suppressed before PIL is imported
    # Third-party imports
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # Create application (headless-aware)
    if headless_mode:
        # Local application imports
        from headless_mode import HeadlessMode

        app = HeadlessMode.create_headless_application(sys.argv)
    else:
        app = QApplication(sys.argv)

    # Local application imports
    from main_window import MainWindow

    # Set application info
    app.setApplicationName("ShotBot")
    app.setOrganizationName("VFX")

    # Set dark theme
    _ = app.setStyle("Fusion")

    # Dark palette
    # Third-party imports
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
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(127, 127, 127),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(127, 127, 127),
    )

    app.setPalette(palette)

    # Create main window
    window = MainWindow()

    # Start periodic zombie thread cleanup (prevents memory leaks)
    from thread_safe_worker import ThreadSafeWorker

    ThreadSafeWorker.start_zombie_cleanup_timer()

    # In headless mode, patch the window to prevent display operations
    if headless_mode:
        # Local application imports
        from headless_mode import HeadlessMode

        HeadlessMode.patch_for_headless(window)

    # Show window (will be no-op in headless mode due to patching)
    window.show()
    logger.debug("MainWindow shown")

    # Auto-screenshot functionality
    if screenshot_seconds is not None and not headless_mode:
        from pathlib import Path

        from PySide6.QtCore import QTimer

        def take_auto_screenshot() -> None:
            """Capture window screenshot automatically."""
            try:
                # Grab the window contents
                pixmap = window.grab()

                # Save to file
                output_path = Path("/mnt/c/temp/shotbot_auto.png")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                success = pixmap.save(str(output_path))

                if success:
                    logger.info(f"Screenshot saved: {output_path}")
                else:
                    logger.error("Failed to save screenshot")
            except Exception:
                logger.exception("Auto-screenshot failed")

        # Schedule screenshot after specified delay
        delay_ms = screenshot_seconds * 1000
        logger.info(f"Auto-screenshot scheduled in {screenshot_seconds} seconds...")
        QTimer.singleShot(delay_ms, take_auto_screenshot)

    # Run application
    exit_code = app.exec()
    logger.debug(f"Qt event loop exited (code={exit_code})")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
