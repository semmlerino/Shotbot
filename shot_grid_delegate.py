"""Delegate for shot thumbnail rendering using base class.

This module provides ShotGridDelegate that inherits common
functionality from BaseThumbnailDelegate.
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING

# Third-party imports
from PySide6.QtGui import QColor

from base_item_model import BaseItemRole

# Local application imports
from base_thumbnail_delegate import (
    BaseThumbnailDelegate,
    DelegateTheme,
    ThumbnailItemData,
)
from logging_mixin import get_module_logger
from typing_compat import override


# Backward compatibility alias
ShotRole = BaseItemRole

if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtCore import QModelIndex, QPersistentModelIndex
    from PySide6.QtWidgets import QWidget

# Module-level logger
logger = get_module_logger(__name__)


class ShotGridDelegate(BaseThumbnailDelegate):
    """Delegate for rendering shot thumbnails in a grid.

    Inherits common painting logic from BaseThumbnailDelegate and
    provides shot-specific data extraction and theming.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the shot grid delegate.

        Args:
            parent: Optional parent widget

        """
        super().__init__(parent)
        logger.debug("ShotGridDelegate initialized")

    @override
    def get_theme(self) -> DelegateTheme:
        """Get the shot grid theme configuration.

        Returns:
            Theme configuration for shot grid

        """
        return DelegateTheme(
            # Shot grid specific colors
            bg_color=QColor("#2b2b2b"),
            bg_hover_color=QColor("#3a3a3a"),
            bg_selected_color=QColor("#0d7377"),
            border_color=QColor("#444"),
            border_hover_color=QColor("#888"),
            border_selected_color=QColor("#14ffec"),
            text_color=QColor("#ffffff"),
            text_selected_color=QColor("#14ffec"),
            # Dimensions
            text_height=50,
            padding=8,
            border_radius=8,
            # Font sizes
            name_font_size=13,
            info_font_size=11,
        )

    @override
    def get_item_data(
        self, index: QModelIndex | QPersistentModelIndex
    ) -> ThumbnailItemData:
        """Extract shot data from model index.

        Args:
            index: Model index

        Returns:
            Dictionary with shot data

        """
        if not index.isValid():
            return {}

        return {
            "name": index.data(ShotRole.FullNameRole) or "Unknown",
            "show": index.data(ShotRole.ShowRole),
            "sequence": index.data(ShotRole.SequenceRole),
            "thumbnail": index.data(ShotRole.ThumbnailPixmapRole),
            "loading_state": index.data(ShotRole.LoadingStateRole),
            "is_selected": index.data(ShotRole.IsSelectedRole) or False,
            "is_pinned": index.data(ShotRole.IsPinnedRole) or False,
            "is_hidden": index.data(ShotRole.IsHiddenRole) or False,
            "has_note": index.data(ShotRole.HasNoteRole) or False,
            "frame_range": index.data(ShotRole.FrameRangeRole) or "No plate",
        }
