"""Improved thumbnail_widget_base.py with non-blocking folder opening."""

import logging
import subprocess
import sys

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices

# Set up logger for this module
logger = logging.getLogger(__name__)


class FolderOpenerThread(QThread):
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
            logger.debug(f"Opening folder with URL: {url.toString()}")

            # Try Qt's method first
            success = QDesktopServices.openUrl(url)

            if success:
                logger.debug(f"Successfully opened folder: {self.folder_path}")
                self.finished_signal.emit(True, "")
            else:
                # Fallback to system command
                logger.debug("QDesktopServices failed, trying system command")
                self._open_with_system_command()

        except Exception as e:
            error_msg = f"Error opening folder: {e}"
            logger.error(error_msg)
            self.finished_signal.emit(False, str(e))

    def _create_file_url(self, folder_path: str) -> QUrl:
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
            logger.warning("Empty folder path provided, using root")

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
            logger.debug(f"Handling UNC path: {folder_path}")
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
            logger.debug(f"Handling Windows path: {folder_path}")
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
                logger.debug(f"Converting relative path to absolute: {folder_path}")
                folder_path = "/" + folder_path

            url = QUrl()
            url.setScheme("file")
            url.setPath(folder_path)

        return url

    def _open_with_system_command(self):
        """Fallback to system command for opening folders."""
        system = sys.platform

        try:
            if system == "darwin":  # macOS
                result = subprocess.run(
                    ["open", self.folder_path],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    logger.debug("Opened with macOS 'open' command")
                    self.finished_signal.emit(True, "")
                else:
                    self.finished_signal.emit(
                        False, f"open command failed: {result.stderr}"
                    )

            elif system == "win32":  # Windows
                result = subprocess.run(
                    ["explorer", self.folder_path],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    logger.debug("Opened with Windows Explorer")
                    self.finished_signal.emit(True, "")
                else:
                    self.finished_signal.emit(
                        False, f"explorer failed: {result.stderr}"
                    )

            else:  # Linux/Unix
                # Try common file managers
                success = False
                last_error = ""
                for cmd in [
                    "xdg-open",
                    "nautilus",
                    "dolphin",
                    "thunar",
                    "nemo",
                    "pcmanfm",
                ]:
                    try:
                        result = subprocess.run(
                            [cmd, self.folder_path],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        if result.returncode == 0:
                            logger.debug(f"Opened with {cmd}")
                            self.finished_signal.emit(True, "")
                            success = True
                            break
                        else:
                            last_error = f"{cmd}: {result.stderr}"
                    except FileNotFoundError:
                        last_error = f"{cmd} not found"
                        continue
                    except subprocess.TimeoutExpired:
                        last_error = f"{cmd} timed out"
                        continue

                if not success:
                    self.finished_signal.emit(
                        False, f"No file manager worked: {last_error}"
                    )

        except Exception as e:
            error_msg = f"System command failed: {e}"
            logger.warning(error_msg)
            self.finished_signal.emit(False, error_msg)


# Example of how to integrate into thumbnail_widget_base.py:
"""
def _open_shot_folder(self):
    '''Open the shot's workspace folder in system file manager (non-blocking).'''
    folder_path = self.data.workspace_path
    
    # Create and start the folder opener thread
    self.folder_opener = FolderOpenerThread(folder_path)
    self.folder_opener.finished_signal.connect(self._on_folder_opened)
    self.folder_opener.start()
    
    logger.info(f"Opening folder: {folder_path}")

def _on_folder_opened(self, success: bool, error: str):
    '''Handle the result of folder opening attempt.'''
    if success:
        logger.debug("Folder opened successfully")
    else:
        logger.warning(f"Failed to open folder: {error}")
        # Optionally show user notification here
    
    # Clean up the thread
    if hasattr(self, 'folder_opener'):
        self.folder_opener.quit()
        self.folder_opener.wait()
        self.folder_opener.deleteLater()
        self.folder_opener = None
"""
