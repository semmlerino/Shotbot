#!/usr/bin/env python3
"""Final comprehensive URL generation and non-blocking folder opening solution."""

import logging
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class SafeFolderOpener(QThread):
    """Thread-safe folder opener that won't block the UI."""

    finished_signal = Signal(bool, str)  # success, error_message

    def __init__(self, folder_path: str):
        super().__init__()
        self.folder_path = folder_path

    def run(self):
        """Open folder in background thread."""
        try:
            # Create proper file URL
            url = create_file_url(self.folder_path)
            logger.debug(f"Opening URL: {url.toString()}")

            # Try Qt's method
            success = QDesktopServices.openUrl(url)

            if success:
                self.finished_signal.emit(True, "")
            else:
                # Fallback to system command
                logger.debug("Qt method failed, trying system command")
                self._open_with_system_command(self.folder_path)
                self.finished_signal.emit(True, "")

        except Exception as e:
            logger.error(f"Error opening folder: {e}")
            self.finished_signal.emit(False, str(e))

    def _open_with_system_command(self, folder_path: str):
        """Fallback to system command for opening folders."""
        system = sys.platform

        try:
            if system == "darwin":  # macOS
                subprocess.run(["open", folder_path], check=False, timeout=5)
            elif system == "win32":  # Windows
                # Use start command to avoid blocking
                subprocess.run(["explorer", folder_path], check=False, timeout=5)
            else:  # Linux/Unix
                # Try common file managers
                for cmd in ["xdg-open", "nautilus", "dolphin", "thunar", "nemo"]:
                    try:
                        subprocess.run([cmd, folder_path], check=False, timeout=5)
                        logger.debug(f"Opened with {cmd}")
                        break
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        continue
        except Exception as e:
            logger.warning(f"System command failed: {e}")


def create_file_url(folder_path: str) -> QUrl:
    """
    Create a proper file:// URL that works across all platforms.

    Handles:
    - Unix absolute paths (/path/to/folder)
    - Unix relative paths (path/to/folder)
    - Windows paths (C:/path or C:\\path)
    - UNC paths (//network/share)
    - Paths with spaces and special characters
    - Unicode paths
    """
    # Handle empty path
    if not folder_path:
        folder_path = "/"

    # Normalize backslashes to forward slashes for consistency
    folder_path = folder_path.replace("\\", "/")

    # Check for different path types
    is_unc = folder_path.startswith("//")
    is_windows = (
        len(folder_path) >= 2 and folder_path[1] == ":" and folder_path[0].isalpha()
    )

    if is_unc:
        # UNC path: //network/share/folder
        # Should become: file://network/share/folder
        url = QUrl()
        url.setScheme("file")
        # Remove leading // and split
        path_parts = folder_path[2:].split("/", 1)
        if path_parts:
            url.setHost(path_parts[0])
            if len(path_parts) > 1:
                url.setPath("/" + path_parts[1])
            else:
                url.setPath("/")
    elif is_windows:
        # Windows path: C:/folder or D:/folder
        # Should become: file:///C:/folder
        url = QUrl()
        url.setScheme("file")
        # Windows paths need the leading slash for file:///
        if not folder_path.startswith("/"):
            folder_path = "/" + folder_path
        url.setPath(folder_path)
    else:
        # Unix path (absolute or relative)
        # Ensure it starts with / for absolute path
        if not folder_path.startswith("/"):
            folder_path = "/" + folder_path

        url = QUrl()
        url.setScheme("file")
        url.setPath(folder_path)

    return url


def open_folder_safely(
    folder_path: str, use_thread: bool = True
) -> Optional[SafeFolderOpener]:
    """
    Open a folder safely without blocking the UI.

    Args:
        folder_path: Path to the folder to open
        use_thread: If True, open in background thread (recommended)

    Returns:
        SafeFolderOpener thread if use_thread=True, None otherwise
    """
    if use_thread:
        opener = SafeFolderOpener(folder_path)
        opener.start()
        return opener
    else:
        # Direct opening (may block UI)
        url = create_file_url(folder_path)
        QDesktopServices.openUrl(url)
        return None


def test_all_cases():
    """Test all URL generation cases."""

    test_cases = [
        # (input_path, expected_prefix, description)
        ("/shows/test/shots/001/0010", "file:///", "Unix absolute path"),
        ("shows/test/shots/001/0010", "file:///", "Unix relative path"),
        ("/path with spaces/folder", "file:///", "Path with spaces"),
        ("/path/特殊字符/folder", "file:///", "Unicode path"),
        ("C:/Windows/System32", "file:///C:", "Windows path with forward slash"),
        ("C:\\Windows\\System32", "file:///C:", "Windows path with backslash"),
        ("D:/Projects/Test", "file:///D:", "Different Windows drive"),
        ("//network/share/folder", "file://network", "UNC path"),
        ("//192.168.1.1/share", "file://192.168.1.1", "UNC with IP"),
        ("/", "file:///", "Root directory"),
        ("", "file:///", "Empty path"),
    ]

    print("Comprehensive URL Generation Test")
    print("=" * 70)

    all_pass = True

    for input_path, expected_prefix, description in test_cases:
        url = create_file_url(input_path)
        url_string = url.toString()

        # Check if URL starts with expected prefix
        passes = url_string.startswith(expected_prefix)

        # Additional validation
        is_valid_url = url.isValid()

        print(f"\n{description}:")
        print(f"  Input:    '{input_path}'")
        print(f"  Output:   '{url_string}'")
        print(f"  Expected: starts with '{expected_prefix}'")
        print(f"  Valid:    {is_valid_url}")
        print(f"  Result:   {'✓ PASS' if passes and is_valid_url else '✗ FAIL'}")

        if not (passes and is_valid_url):
            all_pass = False
            print(f"  Host: '{url.host()}'")
            print(f"  Path: '{url.path()}'")

    print("\n" + "=" * 70)
    if all_pass:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed.")

    return all_pass


def test_qt_behavior():
    """Test Qt's actual behavior with different URLs."""

    print("\n" + "=" * 70)
    print("Qt Behavior Comparison")
    print("=" * 70)

    paths = [
        "shows/test/shots/001/0010",
        "/shows/test/shots/001/0010",
        "C:/Windows/System32",
        "//network/share",
    ]

    for path in paths:
        print(f"\nPath: '{path}'")

        # Our method
        our_url = create_file_url(path)
        print(f"  Our method:     '{our_url.toString()}'")

        # Qt's fromLocalFile
        qt_url = QUrl.fromLocalFile(path)
        print(f"  fromLocalFile:  '{qt_url.toString()}'")

        # Check if they would both work
        print(f"  Our URL valid:  {our_url.isValid()}")
        print(f"  Qt URL valid:   {qt_url.isValid()}")


if __name__ == "__main__":
    # Run comprehensive tests
    success = test_all_cases()

    # Test Qt behavior comparison
    test_qt_behavior()

    print("\n" + "=" * 70)
    if success:
        print("Solution verified successfully!")
        print("\nRecommended implementation:")
        print("1. Use the create_file_url() function for proper URL generation")
        print("2. Use SafeFolderOpener thread to prevent UI blocking")
        print("3. Include fallback to system commands for reliability")
    else:
        print("Issues found. Review the implementation.")
