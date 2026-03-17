"""Manager components for ShotBot application.

This package contains focused manager classes for UI and application state:
- HideManager: Manages shot row visibility and filtering
- NotesManager: Manages per-shot notes storage and retrieval
- ShotPinManager: Manages pinned shots persistence
- FilePinManager: Manages pinned file paths persistence
- NotificationManager: Manages user-facing status bar notifications
- ProgressManager: Manages status-bar progress indicators for long-running operations
- SettingsManager: Manages application settings persistence via QSettings
- get_stored_height: Helper to retrieve stored integer height from QSettings
"""

from managers.file_pin_manager import FilePinManager
from managers.hide_manager import HideManager
from managers.notes_manager import NotesManager
from managers.notification_manager import NotificationManager
from managers.progress_manager import ProgressManager
from managers.settings_manager import SettingsManager, get_stored_height
from managers.shot_pin_manager import ShotPinManager


__all__ = [
    "FilePinManager",
    "HideManager",
    "NotesManager",
    "NotificationManager",
    "ProgressManager",
    "SettingsManager",
    "ShotPinManager",
    "get_stored_height",
]
