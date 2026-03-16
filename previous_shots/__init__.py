"""Previous shots components for displaying approved/archived shots.

This package provides components for finding, managing, and displaying
shots the user has previously worked on (approved/completed):
- PreviousShotsFinder: Filesystem scanner for previous shots
- ParallelShotsFinder: Parallel implementation of PreviousShotsFinder
- PreviousShotsItemModel: Qt item model for previous shots
- PreviousShotsModel: Data model managing previous shots state
- PreviousShotsView: Qt view for displaying previous shots grid
- PreviousShotsWorker: Background worker for scanning shots
"""

from previous_shots.finder import ParallelShotsFinder, PreviousShotsFinder
from previous_shots.item_model import PreviousShotsItemModel
from previous_shots.model import PreviousShotsModel
from previous_shots.view import PreviousShotsView
from previous_shots.worker import PreviousShotsWorker


__all__ = [
    "ParallelShotsFinder",
    "PreviousShotsFinder",
    "PreviousShotsItemModel",
    "PreviousShotsModel",
    "PreviousShotsView",
    "PreviousShotsWorker",
]
