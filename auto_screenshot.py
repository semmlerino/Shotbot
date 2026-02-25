#!/usr/bin/env python3
"""Launch ShotBot and automatically capture a screenshot after it loads."""

import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication


def capture_shotbot_window() -> Path | None:
    """Find and capture the ShotBot window.

    Returns:
        Path to the saved screenshot, or None if capture failed.

    """
    app_instance = QApplication.instance()
    if not app_instance or not isinstance(app_instance, QApplication):
        print("Error: No QApplication instance found")
        return None

    # Find all top-level windows
    windows = app_instance.topLevelWidgets()
    shotbot_window = None

    for window in windows:
        if "ShotBot" in window.windowTitle():
            shotbot_window = window
            break

    if not shotbot_window:
        print("Error: Could not find ShotBot window")
        return None

    # Grab the window contents
    pixmap = shotbot_window.grab()

    # Save to file
    output_path = Path("/mnt/c/temp/shotbot_window.png")
    success = pixmap.save(str(output_path))

    if success:
        print(f"✓ Screenshot saved to: {output_path}")
        print("  (Windows path: C:\\temp\\shotbot_window.png)")
        return output_path
    print("✗ Failed to save screenshot")
    return None


def main() -> None:
    """Launch ShotBot with auto-screenshot."""
    # Start ShotBot process
    print("Starting ShotBot...")
    shotbot_process = subprocess.Popen(
        [sys.executable, "shotbot.py", "--mock"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    # Give it time to start
    time.sleep(6)

    # Try to capture
    print("Attempting to capture window...")
    result = capture_shotbot_window()

    if result:
        print("\nScreenshot captured successfully!")
    else:
        print("\nFailed to capture. Is ShotBot running?")

    # Leave ShotBot running
    print("ShotBot remains running in background.")
    print(f"PID: {shotbot_process.pid}")


if __name__ == "__main__":
    main()
