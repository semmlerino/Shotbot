"""3DEqualizer UI and discovery components.

This package contains focused components for 3DE scene browsing and crash recovery:
- ThreeDEGridDelegate: Thumbnail delegate for 3DE scene grid
- ThreeDEGridView: Grid view widget for 3DE scenes
- ThreeDEItemModel: Qt item model for 3DE scenes
- ThreeDELatestFinder: Finder for latest 3DE scene files
- ThreeDERecoveryManager: Manager for 3DE crash file recovery
- CrashFileInfo: Data class for crash file information
- ThreeDERecoveryDialog: Dialog for presenting crash recovery options
- ThreeDERecoveryResultDialog: Dialog for showing recovery results
- ThreeDESceneModel: Domain model holding discovered 3DE scenes
- ThreeDESceneWorker: Background worker for 3DE scene discovery
- FilesystemScanner: Filesystem scanner for .3de files
- SceneDiscoveryCoordinator: Coordinator for scene discovery
- SceneParser: Parser for 3DE scene file paths
"""

from threede.filesystem_scanner import FileSystemScanner
from threede.grid_delegate import ThreeDEGridDelegate
from threede.grid_view import ThreeDEGridView
from threede.item_model import ThreeDEItemModel
from threede.latest_finder import ThreeDELatestFinder
from threede.recovery import CrashFileInfo, ThreeDERecoveryManager
from threede.recovery_dialog import ThreeDERecoveryDialog, ThreeDERecoveryResultDialog
from threede.scene_discovery_coordinator import SceneDiscoveryCoordinator
from threede.scene_model import ThreeDESceneModel
from threede.scene_parser import SceneParser
from threede.scene_worker import ThreeDESceneWorker


__all__ = [
    "CrashFileInfo",
    "FileSystemScanner",
    "SceneDiscoveryCoordinator",
    "SceneParser",
    "ThreeDEGridDelegate",
    "ThreeDEGridView",
    "ThreeDEItemModel",
    "ThreeDELatestFinder",
    "ThreeDERecoveryDialog",
    "ThreeDERecoveryManager",
    "ThreeDERecoveryResultDialog",
    "ThreeDESceneModel",
    "ThreeDESceneWorker",
]
