"""Controllers package for MainWindow refactoring.

This package contains extracted controller classes that were previously
part of the monolithic MainWindow class. Each controller handles a specific
aspect of functionality with clear separation of concerns.

Controllers:
    - SettingsController: Manages application settings and preferences
    - UISetupController: Handles UI initialization and layout setup
    - ThreeDEController: Manages 3DE scene discovery and handling
    - ShotController: Handles shot management and model operations
    - LauncherCoordinator: Manages application launching and custom launchers
    - RefreshCoordinator: Coordinates shot refresh across tabs

This refactoring follows the established plan in MAINWINDOW_SAFE_REFACTORING_PLAN_DO_NOT_DELETE.md
"""

from .refresh_coordinator import RefreshCoordinator
from .settings_controller import SettingsController, SettingsTarget
from .shot_selection_controller import ShotSelectionController, ShotSelectionTarget
from .threede_controller import ThreeDEController
from .thumbnail_size_manager import ThumbnailSizeManager


__all__ = [
    "RefreshCoordinator",
    "SettingsController",
    "SettingsTarget",
    "ShotSelectionController",
    "ShotSelectionTarget",
    "ThreeDEController",
    "ThumbnailSizeManager",
]
