#!/usr/bin/env python3
"""Test screenshot with pyautogui."""

from pathlib import Path

import pyautogui  # type: ignore[reportMissingModuleSource]


try:
    print("Attempting to take screenshot with pyautogui...")
    screenshot = pyautogui.screenshot()
    output_path = Path("/tmp/shotbot_screenshot.png")
    screenshot.save(str(output_path))
    print(f"✓ Screenshot saved to: {output_path}")
except Exception as e:
    print(f"✗ Screenshot failed: {e}")
    print("\nPyAutoGUI on Linux requires 'scrot' to be installed.")
    print("Please run: sudo apt-get install scrot")
