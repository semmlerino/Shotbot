"""Configuration constants for ShotBot application."""

from pathlib import Path


class Config:
    """Application configuration."""

    # App info
    APP_NAME = "ShotBot"
    APP_VERSION = "1.0.0"

    # Window settings
    DEFAULT_WINDOW_WIDTH = 1200
    DEFAULT_WINDOW_HEIGHT = 800
    MIN_WINDOW_WIDTH = 800
    MIN_WINDOW_HEIGHT = 600

    # Thumbnail settings
    DEFAULT_THUMBNAIL_SIZE = 200
    MIN_THUMBNAIL_SIZE = 100
    MAX_THUMBNAIL_SIZE = 400
    THUMBNAIL_SPACING = 20  # Increased to accommodate selection highlight
    PLACEHOLDER_COLOR = "#444444"

    # Shot paths
    SHOWS_ROOT = "/shows"
    THUMBNAIL_PATH_PATTERN = "{shows_root}/{show}/shots/{sequence}/{shot}/publish/editorial/cutref/v001/jpg/1920x1080/"

    # Commands
    APPS = {
        "3de": "3de",
        "nuke": "nuke",
        "maya": "maya",
        "rv": "rv",
        "publish": "publish_standalone",
    }
    DEFAULT_APP = "nuke"

    # Settings file
    SETTINGS_FILE = Path.home() / ".shotbot" / "settings.json"

    # UI settings
    LOG_MAX_LINES = 1000
    GRID_COLUMNS = 4  # Default columns, will be dynamic based on width

    # Threading
    MAX_THUMBNAIL_THREADS = 4
