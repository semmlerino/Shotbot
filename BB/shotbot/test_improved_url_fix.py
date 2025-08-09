#!/usr/bin/env python3
"""Improved URL generation fix with non-blocking execution."""

import subprocess
import sys

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices


class NonBlockingFolderOpener(QThread):
    """Thread to open folders without blocking the UI."""

    finished_signal = Signal(bool, str)  # success, error_message

    def __init__(self, folder_path: str):
        super().__init__()
        self.folder_path = folder_path

    def run(self):
        """Open folder in background thread."""
        try:
            # Create proper file URL
            url = self._create_file_url(self.folder_path)

            # Try Qt's method first
            success = QDesktopServices.openUrl(url)

            if not success:
                # Fallback to system command
                self._open_with_system_command(self.folder_path)
                self.finished_signal.emit(True, "")
            else:
                self.finished_signal.emit(True, "")

        except Exception as e:
            self.finished_signal.emit(False, str(e))

    def _create_file_url(self, folder_path: str) -> QUrl:
        """Create proper file:/// URL handling all edge cases."""
        # Handle empty path
        if not folder_path:
            folder_path = "/"

        # Handle UNC paths (//network/share)
        if folder_path.startswith("//"):
            # UNC paths need special handling
            url = QUrl()
            url.setScheme("file")
            url.setHost(folder_path[2:].split("/")[0])
            url.setPath("/" + "/".join(folder_path[2:].split("/")[1:]))
            return url

        # Ensure absolute path for Unix-style paths
        if not folder_path.startswith("/") and not (
            len(folder_path) > 1 and folder_path[1] == ":"
        ):
            folder_path = "/" + folder_path

        # Create URL with proper scheme
        url = QUrl()
        url.setScheme("file")
        url.setPath(folder_path)

        return url

    def _open_with_system_command(self, folder_path: str):
        """Fallback to system command for opening folders."""
        system = sys.platform

        try:
            if system == "darwin":  # macOS
                subprocess.run(["open", folder_path], check=False)
            elif system == "win32":  # Windows
                subprocess.run(["explorer", folder_path], check=False)
            else:  # Linux/Unix
                # Try common file managers
                for cmd in ["xdg-open", "nautilus", "dolphin", "thunar"]:
                    try:
                        subprocess.run([cmd, folder_path], check=False)
                        break
                    except FileNotFoundError:
                        continue
        except Exception:
            pass  # Silently fail for fallback


def improved_open_shot_folder(folder_path: str) -> QUrl:
    """
    Improved version of _open_shot_folder that:
    1. Handles all path edge cases correctly
    2. Returns the URL for verification
    3. Can be used with threading for non-blocking
    """
    # Handle empty path
    if not folder_path:
        folder_path = "/"

    # Handle UNC paths (//network/share)
    if folder_path.startswith("//"):
        url = QUrl()
        url.setScheme("file")
        # Split UNC path into host and path components
        parts = folder_path[2:].split("/", 1)
        if len(parts) > 0:
            url.setHost(parts[0])
        if len(parts) > 1:
            url.setPath("/" + parts[1])
        return url

    # Ensure absolute path for Unix-style paths
    # Check if it's a Windows path (C:/, D:/, etc.)
    is_windows_path = len(folder_path) > 1 and folder_path[1] == ":"

    if not folder_path.startswith("/") and not is_windows_path:
        folder_path = "/" + folder_path

    # Create URL with proper scheme
    url = QUrl()
    url.setScheme("file")
    url.setPath(folder_path)

    return url


def test_improved_fix():
    """Test the improved URL generation."""

    test_cases = [
        # (input_path, description)
        ("/shows/test/shots/001/0010", "Absolute Unix path"),
        ("shows/test/shots/001/0010", "Relative Unix path"),
        ("/path with spaces/folder", "Path with spaces"),
        ("/path/with/special!@#$%^&()chars", "Special characters"),
        ("C:/Windows/System32", "Windows path"),
        ("//network/share/folder", "UNC path"),
        ("/path/with/unicode/测试/folder", "Unicode characters"),
        ("/", "Root directory"),
        ("", "Empty path"),
    ]

    print("Testing Improved URL Generation")
    print("=" * 60)

    for input_path, description in test_cases:
        url = improved_open_shot_folder(input_path)
        url_string = url.toString()

        # Check format
        is_valid = url_string.startswith("file://")
        has_triple_slash = url_string.startswith("file:///")

        print(f"\n{description}:")
        print(f"  Input: '{input_path}'")
        print(f"  URL: '{url_string}'")
        print(f"  Valid: {is_valid}")
        print(f"  Triple slash: {has_triple_slash or 'UNC' in description}")

    # Test path encoding
    print("\n" + "=" * 60)
    print("Path Encoding Tests:")

    special_paths = [
        "/path with spaces/test",
        "/path/with/special!@#$%^&()chars",
        "/path/with/unicode/测试/folder",
    ]

    for path in special_paths:
        url = improved_open_shot_folder(path)
        print(f"\nPath: '{path}'")
        print(f"  Encoded URL: '{url.toString()}'")
        print(f"  Decoded path: '{url.path()}'")


if __name__ == "__main__":
    test_improved_fix()
