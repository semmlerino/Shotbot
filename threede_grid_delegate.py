"""Delegate for 3DE scene thumbnail rendering using base class.

This module provides ThreeDEGridDelegate that inherits common
functionality from BaseThumbnailDelegate.
"""

from __future__ import annotations

# Standard library imports
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

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
ThreeDERole = BaseItemRole

if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtCore import QModelIndex, QPersistentModelIndex
    from PySide6.QtWidgets import QWidget

# Module-level logger
logger = get_module_logger(__name__)


class ThreeDEGridDelegate(BaseThumbnailDelegate):
    """Delegate for rendering 3DE scene thumbnails in a grid.

    Inherits common painting logic from BaseThumbnailDelegate and
    provides 3DE-specific data extraction and theming.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the 3DE grid delegate.

        Args:
            parent: Optional parent widget
        """
        super().__init__(parent)
        logger.debug("ThreeDEGridDelegate initialized")

    @override
    def get_theme(self) -> DelegateTheme:
        """Get the 3DE grid theme configuration.

        Returns:
            Theme configuration for 3DE grid
        """
        return DelegateTheme(
            # 3DE specific colors with blue tint
            bg_color=QColor("#2b2b3b"),  # Slightly blue tint
            bg_hover_color=QColor("#3a3a4a"),
            bg_selected_color=QColor("#0a5f73"),  # Different from shot grid
            border_color=QColor("#445"),
            border_hover_color=QColor("#889"),
            border_selected_color=QColor("#00c9ff"),  # 3DE blue
            text_color=QColor("#ffffff"),
            text_selected_color=QColor("#00c9ff"),
            user_color=QColor("#a0a0a0"),  # Gray for user text
            # Dimensions
            text_height=50,  # Slightly taller for extra info
            padding=8,
            border_radius=8,
            # Font sizes
            name_font_size=9,
            info_font_size=7,  # Smaller for user/timestamp
        )

    @override
    def get_item_data(
        self, index: QModelIndex | QPersistentModelIndex
    ) -> ThumbnailItemData:
        """Extract 3DE scene data from model index.

        Args:
            index: Model index

        Returns:
            Dictionary with 3DE scene data
        """
        if not index.isValid():
            return {}

        # Get timestamp and format it if available
        # ModifiedTimeRole returns float (Unix timestamp) or 0.0
        timestamp_str = ""
        # Qt's index.data() returns Any - cast to expected type and validate at runtime
        timestamp_data = cast(
            "float | int | None",
            index.data(ThreeDERole.ModifiedTimeRole),
        )
        if timestamp_data is not None and timestamp_data != 0:
            try:
                # Convert Unix timestamp to datetime
                timestamp = datetime.fromtimestamp(float(timestamp_data), tz=UTC)
                # Format timestamp for display
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError):
                # Handle invalid timestamps gracefully
                timestamp_str = ""

        return {
            "name": index.data(ThreeDERole.DisplayRole) or "Unknown",
            "show": index.data(ThreeDERole.ShowRole),
            "sequence": index.data(ThreeDERole.SequenceRole),
            "shot": index.data(ThreeDERole.ItemSpecificRole1),  # Maps to shot
            "thumbnail": index.data(ThreeDERole.ThumbnailPixmapRole),
            "loading_state": index.data(ThreeDERole.LoadingStateRole),
            "is_selected": index.data(ThreeDERole.IsSelectedRole) or False,
            "user": index.data(
                ThreeDERole.ItemSpecificRole2
            ),  # Maps to user for THREEDE
            "timestamp": timestamp_str,
        }
