#!/usr/bin/env python
"""
Script to run ShotBot in mock mode and capture a screenshot.
"""

# Standard library imports
import os
import sys
from pathlib import Path

# Third-party imports
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


# Set up mock environment before importing ShotBot modules
os.environ["SHOWS_ROOT"] = "/tmp/mock_vfx/shows"
os.environ["SHOTBOT_DEBUG"] = "1"
os.environ["SHOTBOT_MOCK"] = "1"

# Local application imports
# Import ShotBot modules
from main_window import MainWindow


def capture_screenshot() -> None:
    """Capture screenshot of the ShotBot main window."""
    # Standard library imports

    app = QApplication.instance()
    if not app:
        return

    # Get the main window
    windows = QApplication.topLevelWidgets()
    main_window = None
    for window in windows:
        if isinstance(window, MainWindow):
            main_window = window
            break

    if not main_window:
        print("Could not find MainWindow")
        app.quit()
        return

    # Make sure window is shown
    main_window.show()
    main_window.raise_()

    # Switch to "Other 3DE Scenes" tab to show the issue
    if hasattr(main_window, "tab_widget"):
        # Tab 0: My Shots, Tab 1: Other 3DE Scenes, Tab 2: Previous Shots
        main_window.tab_widget.setCurrentIndex(1)

    # Grab the window
    pixmap = main_window.grab()

    # Find the next available screenshot number
    existing_screenshots = [p.name for p in Path().glob("shotbot_screenshot_*.png")]
    next_num: int = 1
    if existing_screenshots:
        numbers: list[int] = []
        for filename in existing_screenshots:
            try:
                num = int(
                    filename.replace("shotbot_screenshot_", "").replace(".png", "")
                )
                numbers.append(num)
            except ValueError:
                continue
        if numbers:
            next_num = max(numbers) + 1

    # Save screenshot with incremented number
    filename = f"shotbot_screenshot_{next_num}.png"
    if pixmap.save(filename):
        print(f"Screenshot saved to {filename}")
        print(f"Window size: {main_window.width()}x{main_window.height()}")

        # ShotBot-specific debug info
        if hasattr(main_window, "tab_widget"):
            print("Tab widget present: True")
            print(f"Current tab index: {main_window.tab_widget.currentIndex()}")
            print(f"Tab count: {main_window.tab_widget.count()}")
            for i in range(main_window.tab_widget.count()):
                print(f"Tab {i}: {main_window.tab_widget.tabText(i)}")

        if hasattr(main_window, "threede_item_model"):
            scene_count = len(main_window.threede_item_model.scenes)
            print(f"3DE Item Model scenes: {scene_count}")

        if hasattr(main_window, "threede_scene_model"):
            scene_count = len(main_window.threede_scene_model.scenes)
            print(f"3DE Scene Model scenes: {scene_count}")

    else:
        print(f"Failed to save screenshot to {filename}")

    # Quit the app
    app.quit()


def main() -> None:
    """Main entry point."""
    # Set offscreen platform for headless environment
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    # Mock mode already set via SHOTBOT_MOCK environment variable above

    app = QApplication(sys.argv)

    # Create ShotBot main window
    window = MainWindow()
    window.show()

    attempts = 0  # Track attempts as a closure variable

    def check_and_capture() -> None:
        """Check if 3DE discovery is complete and capture screenshot."""
        nonlocal attempts

        # Check if 3DE discovery has completed
        if hasattr(window, "threede_item_model"):
            scene_count = len(window.threede_item_model.scenes)
            print(f"Current 3DE scenes in model: {scene_count}")

            if scene_count > 0:
                print("3DE discovery complete, capturing screenshot...")
                capture_screenshot()
                return

        # If we've been waiting too long, just capture anyway to show the current state
        attempts += 1
        if attempts >= 5:  # After 5 attempts (10 seconds total)
            print("Capturing screenshot anyway to show current state...")
            capture_screenshot()
            return

        # If not ready, check again in 2 seconds
        QTimer.singleShot(2000, check_and_capture)

    # Start checking for completion after initial setup
    QTimer.singleShot(3000, check_and_capture)

    # Run the app
    app.exec()


if __name__ == "__main__":
    main()
