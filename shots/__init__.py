"""Shot tab UI components.

This package contains the shot grid view, delegate, models, and info panels:
- ShotGridView: Grid view widget for shot thumbnails
- ShotGridDelegate: Thumbnail delegate for shot grid
- ShotItemModel: Qt item model for shots
- ShotModel: Domain model with async loading
- AsyncShotLoader: Background worker for shot data
- ShotInfoPanel: Panel showing current shot details
- ShotFilesPanel: Panel showing files for a shot
- FileListItem: Individual file entry widget
- FileTypeSection: Grouped file type section
"""

from shots.shot_files_panel import FileListItem, FileTypeSection, ShotFilesPanel
from shots.shot_grid_delegate import ShotGridDelegate
from shots.shot_grid_view import ShotGridView
from shots.shot_info_panel import ShotInfoPanel
from shots.shot_item_model import ShotItemModel
from shots.shot_model import AsyncShotLoader, ShotModel


__all__ = [
    "AsyncShotLoader",
    "FileListItem",
    "FileTypeSection",
    "ShotFilesPanel",
    "ShotGridDelegate",
    "ShotGridView",
    "ShotInfoPanel",
    "ShotItemModel",
    "ShotModel",
]
