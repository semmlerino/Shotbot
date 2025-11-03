#!/usr/bin/env python3
"""Take a screenshot using Qt's built-in screen capture."""

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QPixmap, QScreen
from PySide6.QtWidgets import QApplication


def capture_screenshot() -> Path | None:
    """Capture screenshot of the primary screen."""
    # Get existing QApplication instance or create one
    app_instance = QApplication.instance()
    if not app_instance or not isinstance(app_instance, QApplication):
        app_instance = QApplication(sys.argv)

    # Get the primary screen - QGuiApplication has primaryScreen()
    # QApplication inherits from QGuiApplication, so this is safe
    screen: QScreen | None = QGuiApplication.primaryScreen()
    if not screen:
        print("Error: No screen found")
        return None

    # Capture the screen
    pixmap: QPixmap = screen.grabWindow(0)

    # Save to file
    output_path = Path("/tmp/shotbot_screenshot.png")
    success: bool = pixmap.save(str(output_path))

    if success:
        print(f"✓ Screenshot saved to: {output_path}")
        return output_path
    print("✗ Failed to save screenshot")
    return None


if __name__ == "__main__":
    # Create app if running standalone
    app_instance = QApplication.instance()
    if not app_instance or not isinstance(app_instance, QApplication):
        app_instance = QApplication(sys.argv)

    # Store app reference for closure
    app: QApplication = app_instance

    # Capture after a brief delay to ensure everything is rendered
    def delayed_capture() -> None:
        _ = capture_screenshot()
        app.quit()

    QTimer.singleShot(100, delayed_capture)
    sys.exit(app.exec())
