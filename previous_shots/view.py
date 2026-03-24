"""Qt Model/View implementation for previous shots grid.

This module provides an efficient QListView-based implementation for
displaying approved/completed shots, replacing the widget-heavy approach
with virtualization and proper Model/View architecture.
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING, cast

# Third-party imports
from PySide6.QtCore import (
    QAbstractItemModel,
    QSortFilterProxyModel,
    Qt,
    Slot,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from managers.progress_manager import ProgressManager
from shots.shot_grid_delegate import ShotGridDelegate
from typing_compat import override

# Local application imports
from ui.base_item_model import BaseItemRole
from ui.base_shot_grid_view import BaseShotGridView
from ui.design_system import design_system


# Backward compatibility alias
ShotRole = BaseItemRole

if TYPE_CHECKING:
    # Third-party imports
    # Local application imports
    from PySide6.QtGui import QCloseEvent

    from managers.notes_manager import NotesManager
    from managers.shot_pin_manager import ShotPinManager
    from previous_shots.item_model import PreviousShotsItemModel
    from type_definitions import Shot
    from ui.base_thumbnail_delegate import BaseThumbnailDelegate


class PreviousShotsView(BaseShotGridView):
    """Optimized view for displaying previous/approved shot thumbnails.

    This view provides:
    - Virtualization for memory efficiency
    - Lazy loading of thumbnails
    - Refresh functionality with progress tracking
    - Proper Model/View integration
    - 98% memory reduction vs widget-based approach
    """

    # Class-level type annotation for base class _model attribute
    _model: QAbstractItemModel | None

    def __init__(
        self,
        model: PreviousShotsItemModel | None = None,
        proxy: QSortFilterProxyModel | None = None,
        pin_manager: ShotPinManager | None = None,
        notes_manager: NotesManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the previous shots view.

        Args:
            model: Optional previous shots item model
            proxy: Optional proxy model for filtering/sorting
            pin_manager: Optional pin manager for pinning shots
            notes_manager: Optional notes manager for shot notes
            parent: Optional parent widget

        """
        # Initialize instance variables before super().__init__()
        # These are set in methods called during base class initialization
        self._status_label: QLabel | None = None
        self._refresh_button: QPushButton | None = None
        self._notes_manager: NotesManager | None = notes_manager

        # Initialize base class
        super().__init__(parent)

        # PreviousShotsView-specific attributes
        self._pin_manager: ShotPinManager | None = pin_manager
        # Note: Don't redefine _model - it's inherited from BaseGridView
        # We store the typed reference separately for type safety
        self._unified_model: PreviousShotsItemModel | None = model

        if model:
            self.set_model(model, proxy)

        self.logger.debug("PreviousShotsView initialized")

    @override
    def _add_top_widgets(self, layout: QVBoxLayout) -> None:
        """Add header widget with refresh button and status.

        Args:
            layout: The main vertical layout

        """
        header_widget = self._create_header()
        layout.addWidget(header_widget)

    @override
    def _create_delegate(self) -> BaseThumbnailDelegate:
        """Create the shot grid delegate.

        Returns:
            ShotGridDelegate instance

        """
        return ShotGridDelegate(self)

    def _create_header(self) -> QWidget:
        """Create header with sort buttons, refresh button and status label.

        Returns:
            Header widget

        """
        widget = QWidget()
        header_layout = QHBoxLayout(widget)
        header_layout.setContentsMargins(0, 0, 0, 5)

        # Status label
        self._status_label = QLabel("Approved Shots (Persistent Cache)")
        self._status_label.setStyleSheet(f"font-weight: bold; font-size: {design_system.typography.size_body}px;")
        header_layout.addWidget(self._status_label)

        header_layout.addStretch()

        self._create_sort_buttons(header_layout)

        # Add some spacing
        header_layout.addSpacing(10)

        # Refresh button
        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.setToolTip(
            "Scan for new approved shots and add them to persistent cache"
        )
        _ = self._refresh_button.clicked.connect(self._on_refresh_clicked)  # pyright: ignore[reportAny]
        header_layout.addWidget(self._refresh_button)

        return widget

    @property
    def model(self) -> PreviousShotsItemModel | None:
        """Get the current data model.

        Returns:
            The previous shots item model or None

        """
        return self._unified_model

    @property
    def selected_shot(self) -> Shot | None:
        """Get the currently selected shot.

        Returns:
            The selected Shot object or None

        """
        return self._selected_shot

    @property
    @override
    def thumbnail_size(self) -> int:
        """Get the current thumbnail size.

        Returns:
            Current thumbnail size in pixels

        """
        return self._thumbnail_size

    @override
    def _get_shot_model(self) -> QAbstractItemModel | None:
        """Return _unified_model as the model for shot operations."""
        return self._unified_model

    @override
    def _connect_model_extras(self, model: QAbstractItemModel) -> None:
        """Connect scan signals from the underlying model."""
        psv_model = cast("PreviousShotsItemModel", model)
        underlying_model = psv_model.get_underlying_model()
        if underlying_model:  # Type guard to satisfy basedpyright
            _ = underlying_model.scan_started.connect(
                self._on_scan_started,  # pyright: ignore[reportAny]
                Qt.ConnectionType.QueuedConnection,
            )
            _ = underlying_model.scan_finished.connect(
                self._on_scan_finished,  # pyright: ignore[reportAny]
                Qt.ConnectionType.QueuedConnection,
            )
            _ = underlying_model.scan_progress.connect(
                self._on_scan_progress,  # pyright: ignore[reportAny]
                Qt.ConnectionType.QueuedConnection,
            )

    def set_model(self, model: PreviousShotsItemModel, proxy: QSortFilterProxyModel | None = None) -> None:
        """Set the data model for the view.

        Args:
            model: Previous shots item model
            proxy: Optional proxy model for filtering/sorting

        """
        self._unified_model = model
        self._set_model_common(model, proxy)
        # Update status with shot count
        self._update_status()

    @override
    def populate_show_filter(self, shows: list[str] | object) -> None:
        """Populate the show filter combo box with available shows.

        Args:
            shows: Either a list of show names or a PreviousShotsModel to extract shows from

        """
        # Handle model object (for compatibility with base signature)
        if not isinstance(shows, list):
            # Import needed for runtime check
            from previous_shots.model import PreviousShotsModel

            if isinstance(shows, PreviousShotsModel):
                show_list = list(shows.get_available_shows())
                super().populate_show_filter(show_list)
            return

        # Handle list of strings directly (type narrowed by isinstance)
        # Cast to satisfy type checker - shows is list[str] after isinstance check
        super().populate_show_filter(cast("list[str]", shows))

    @Slot()  # pyright: ignore[reportAny]
    def _on_refresh_clicked(self) -> None:
        """Handle refresh button click."""
        self.logger.debug("Refresh button clicked")

        if self._unified_model:
            assert self._refresh_button is not None
            self._refresh_button.setEnabled(False)
            self._refresh_button.setText("Scanning...")
            self._unified_model.refresh()

    @Slot()  # pyright: ignore[reportAny]
    def _on_scan_started(self) -> None:
        """Handle scan start."""
        assert self._refresh_button is not None
        assert self._status_label is not None
        self._refresh_button.setEnabled(False)
        self._refresh_button.setText("Scanning...")
        self._status_label.setText("Scanning for new approved shots...")

        # Start progress operation
        _ = ProgressManager.start_operation("Previous Shots: Discovering archived shots")

    @Slot()  # pyright: ignore[reportAny]
    def _on_scan_finished(self) -> None:
        """Handle scan completion."""
        # Finish progress operation
        ProgressManager.finish_operation(success=True)

        # Reset UI state
        assert self._refresh_button is not None
        self._refresh_button.setEnabled(True)
        self._refresh_button.setText("Refresh")

        self._update_status()

    @Slot(int, int)  # pyright: ignore[reportAny]
    def _on_scan_progress(self, current: int, total: int) -> None:
        """Handle scan progress updates.

        Args:
            current: Current progress value
            total: Total progress value

        """
        if total > 0:
            assert self._status_label is not None
            percent = int((current / total) * 100)
            self._status_label.setText(f"Scanning... {percent}%")
            # Update progress in status bar
            ProgressManager.update(current, f"Scanning {percent}%")

    def _update_status(self) -> None:
        """Update the status label with shot count."""
        if self._unified_model:
            assert self._status_label is not None
            shot_count = self._unified_model.rowCount()
            self._status_label.setText(f"Approved Shots ({shot_count} cached)")

    @Slot()  # pyright: ignore[reportAny]
    def _on_model_updated(self) -> None:
        """Handle model updates."""
        # Update grid layout based on new item count
        self._update_grid_size()

        # Update status
        self._update_status()

        # Reset visible range tracking
        self._update_visible_range()

    def get_selected_shot(self) -> Shot | None:
        """Get the currently selected shot.

        Returns:
            Selected Shot object or None

        """
        return self._selected_shot

    def refresh(self) -> None:
        """Trigger a refresh of the grid."""
        self._on_refresh_clicked()  # pyright: ignore[reportAny]

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle widget close event to clean up resources."""
        self._visibility_timer.stop()
        super().closeEvent(event)
        self.logger.debug("PreviousShotsView cleaned up resources on close")

    # ============= Pin methods =============

    @property
    @override
    def _item_model(self) -> PreviousShotsItemModel | None:
        """Return the underlying PreviousShotsItemModel for pin-order refresh.

        Returns:
            The PreviousShotsItemModel, or None if not set

        """
        return self._unified_model
