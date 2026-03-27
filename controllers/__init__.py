"""Controllers package for MainWindow refactoring.

This package contains extracted controller classes that were previously
part of the monolithic MainWindow class. Each controller handles a specific
aspect of functionality with clear separation of concerns.

Controllers:
    - CrashRecovery: Manages crash recovery and state restoration
    - DataEventHandler: Handles data-driven events and updates
    - FilterCoordinator: Coordinates filtering operations across the application
    - LaunchCoordinator: Manages application launching and custom launchers
    - RefreshCoordinator: Coordinates shot refresh across tabs
    - SettingsController: Manages application settings and preferences
    - ShotSelectionController: Handles shot selection and navigation
    - StartupOrchestrator: Orchestrates application startup sequence
    - ThreeDEController: Manages 3DE scene discovery and handling
    - ThreeDEWorkerManager: Manages threaded operations for 3DE processing
    - ThumbnailSizeManager: Manages thumbnail sizing and display
"""

from .refresh_coordinator import RefreshCoordinator
from .settings_controller import SettingsController
from .shot_selection_controller import ShotSelectionController
from .threede_controller import ThreeDEController
from .thumbnail_size_manager import ThumbnailSizeManager


__all__ = [
    "RefreshCoordinator",
    "SettingsController",
    "ShotSelectionController",
    "ThreeDEController",
    "ThumbnailSizeManager",
]
