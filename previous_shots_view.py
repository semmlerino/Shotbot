"""Qt Model/View implementation for previous shots grid.

This module provides an efficient QListView-based implementation for
displaying approved/completed shots, replacing the widget-heavy approach
with virtualization and proper Model/View architecture.
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING, ClassVar, cast

# Third-party imports
from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from base_grid_view import BaseGridView
from base_item_model import BaseItemRole
from progress_manager import ProgressManager
from shot_grid_delegate import ShotGridDelegate
from thumbnail_widget_base import FolderOpenerWorker
from typing_compat import override


# Backward compatibility alias
ShotRole = BaseItemRole

if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtGui import QCloseEvent, QContextMenuEvent

    # Local application imports
    from base_thumbnail_delegate import BaseThumbnailDelegate
    from previous_shots_item_model import PreviousShotsItemModel
    from shot_model import Shot


class PreviousShotsView(BaseGridView):
    """Optimized view for displaying previous/approved shot thumbnails.

    This view provides:
    - Virtualization for memory efficiency
    - Lazy loading of thumbnails
    - Refresh functionality with progress tracking
    - Proper Model/View integration
    - 98% memory reduction vs widget-based approach
    """

    # Additional signals specific to PreviousShotsView
    shot_selected: ClassVar[Signal] = Signal(object)  # Shot object
    shot_double_clicked: ClassVar[Signal] = Signal(object)  # Shot object

    # Class-level type annotation for base class _model attribute
    _model: QAbstractItemModel | None

    def __init__(
        self,
        model: PreviousShotsItemModel | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the previous shots view.

        Args:
            model: Optional previous shots item model
            parent: Optional parent widget
        """
        # Initialize instance variables before super().__init__()
        # These are set in methods called during base class initialization
        self._update_timer: QTimer | None = None
        self._status_label: QLabel | None = None
        self._refresh_button: QPushButton | None = None

        # Initialize base class
        super().__init__(parent)

        # PreviousShotsView-specific attributes
        self._selected_shot: Shot | None = None
        # Note: Don't redefine _model - it's inherited from BaseGridView
        # We store the typed reference separately for type safety
        self._unified_model: PreviousShotsItemModel | None = model

        if model:
            self.set_model(model)

        self.logger.info("PreviousShotsView initialized with Model/View architecture")

    @override
    def _setup_visibility_tracking(self) -> None:
        """Override to use scroll-based updates instead of timer."""
        # Setup scroll-based visibility updates (replaces timer)
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        _ = self._update_timer.timeout.connect(self._update_visible_range)

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
        """Create header with refresh button and status label.

        Returns:
            Header widget
        """
        widget = QWidget()
        header_layout = QHBoxLayout(widget)
        header_layout.setContentsMargins(0, 0, 0, 5)

        # Status label
        self._status_label = QLabel("Approved Shots (Persistent Cache)")
        self._status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        header_layout.addWidget(self._status_label)

        header_layout.addStretch()

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

    def set_model(self, model: PreviousShotsItemModel) -> None:
        """Set the data model for the view.

        Args:
            model: Previous shots item model
        """
        self._unified_model = model
        self._model = model  # type: ignore[assignment]
        self.list_view.setModel(model)

        # Set up selection model
        selection_model = self.list_view.selectionModel()
        if selection_model:
            _ = selection_model.currentChanged.connect(self._on_selection_changed)  # pyright: ignore[reportAny]

        # Connect to model signals
        _ = model.shots_updated.connect(self._on_model_updated)  # pyright: ignore[reportAny]

        # Connect to underlying model's scan signals using accessor method
        underlying_model = model.get_underlying_model()
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

        # Connect scroll events for debounced visibility updates
        _ = self.list_view.verticalScrollBar().valueChanged.connect(
            self._schedule_visible_range_update  # pyright: ignore[reportAny]
        )

        # Update status with shot count
        self._update_status()

        self.logger.debug(f"Model set with {model.rowCount()} items")

    @override
    def populate_show_filter(self, shows: list[str] | object) -> None:
        """Populate the show filter combo box with available shows.

        Args:
            shows: Either a list of show names or a PreviousShotsModel to extract shows from
        """
        # Handle model object (for compatibility with base signature)
        if not isinstance(shows, list):
            # Import needed for runtime check
            from previous_shots_model import PreviousShotsModel

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

    @Slot(QModelIndex)  # pyright: ignore[reportAny]
    def _on_item_clicked(self, index: QModelIndex) -> None:
        """Handle item click.

        This is a stub implementation. Qt's selection model will trigger
        _on_selection_changed automatically, which handles all selection logic.
        This avoids duplicate signal emissions.

        Args:
            index: Clicked model index
        """
        # Qt's selection model automatically handles the click
        # _on_selection_changed will be triggered with the full selection logic

    @Slot(QModelIndex)  # pyright: ignore[reportAny]
    def _on_item_double_clicked(self, index: QModelIndex) -> None:
        """Handle item double-click.

        Args:
            index: Double-clicked model index
        """
        if not index.isValid() or not self._unified_model:
            return

        # Cast needed because QModelIndex.data() returns Any
        shot = cast("Shot | None", index.data(ShotRole.ObjectRole))
        if shot:
            self.shot_double_clicked.emit(shot)
            self.logger.debug(f"Shot double-clicked: {shot.full_name}")

    @Slot(QModelIndex, QModelIndex)  # pyright: ignore[reportAny]
    def _on_selection_changed(
        self,
        current: QModelIndex,
        previous: QModelIndex,
    ) -> None:
        """Handle selection change.

        Args:
            current: Current selection index
            previous: Previous selection index
        """
        if not self._unified_model:
            return

        # Clear previous selection in model
        if previous.isValid():
            _ = self._unified_model.setData(previous, False, ShotRole.IsSelectedRole)

        # Set current selection in model
        if current.isValid():
            _ = self._unified_model.setData(current, True, ShotRole.IsSelectedRole)

            # Cast needed because QModelIndex.data() returns Any
            shot = cast("Shot | None", current.data(ShotRole.ObjectRole))
            if shot:
                self._selected_shot = shot
                self.shot_selected.emit(shot)

    @override
    def _handle_visible_range_update(self, start: int, end: int) -> None:
        """Handle the visible range update for lazy loading.

        Args:
            start: Start row index
            end: End row index (exclusive)
        """
        if self._unified_model:
            self._unified_model.set_visible_range(start, end)  # pyright: ignore[reportAny]

    @override
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Handle right-click context menu.

        Args:
            event: Context menu event
        """
        # Convert global position to list view coordinates
        list_view_pos = self.list_view.mapFromGlobal(event.globalPos())

        # Get the index at the clicked position
        index = self.list_view.indexAt(list_view_pos)

        if not index.isValid() or not self._unified_model:
            return

        # Cast needed because QModelIndex.data() returns Any
        shot = cast("Shot | None", index.data(ShotRole.ObjectRole))
        if not shot:
            return

        # Create context menu
        menu = QMenu(self)

        # Add "Open Shot Folder" action
        open_folder_action = menu.addAction("Open Shot Folder")
        _ = open_folder_action.triggered.connect(lambda: self._open_shot_folder(shot))

        # Show menu at cursor position
        _ = menu.exec(event.globalPos())

        self.logger.debug(f"Context menu shown for shot: {shot.full_name}")

    def _open_shot_folder(self, shot: Shot) -> None:
        """Open the shot's workspace folder in system file manager.

        Args:
            shot: Shot object containing workspace path
        """
        folder_path = shot.workspace_path

        # Validate folder path
        if not folder_path:
            self.logger.error(f"No workspace path for shot: {shot.full_name}")
            return

        # Standard library imports
        from pathlib import Path

        if not Path(folder_path).exists():
            self.logger.error(f"Workspace path does not exist: {folder_path}")
            return

        # Create worker to open folder in background
        worker = FolderOpenerWorker(folder_path)

        # Connect signals
        _ = worker.signals.error.connect(
            self._on_folder_open_error,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.signals.success.connect(
            self._on_folder_open_success,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )

        # Start the worker
        QThreadPool.globalInstance().start(worker)

        self.logger.info(f"Opening folder: {folder_path}")

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_folder_open_error(self, error_msg: str) -> None:
        """Handle folder open error.

        Args:
            error_msg: Error message from worker
        """
        self.logger.error(f"Failed to open folder: {error_msg}")

    @Slot()  # pyright: ignore[reportAny]
    def _on_folder_open_success(self) -> None:
        """Handle successful folder opening."""
        self.logger.debug("Folder opened successfully")

    def get_selected_shot(self) -> Shot | None:
        """Get the currently selected shot.

        Returns:
            Selected Shot object or None
        """
        return self._selected_shot

    def refresh(self) -> None:
        """Trigger a refresh of the grid."""
        self._on_refresh_clicked()  # pyright: ignore[reportAny]

    @Slot()  # pyright: ignore[reportAny]
    def _schedule_visible_range_update(self) -> None:
        """Schedule a debounced visible range update.

        This is called on scroll events and uses a timer to debounce
        the updates for better performance.
        """
        # Cancel any pending update
        assert self._update_timer is not None
        self._update_timer.stop()
        # Schedule update after 50ms of no scrolling
        self._update_timer.start(50)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle widget close event to clean up resources.

        Args:
            event: Close event
        """
        # Stop the update timer to prevent memory leaks
        if self._update_timer is not None:
            self._update_timer.stop()

        # Call parent implementation
        super().closeEvent(event)

        self.logger.debug("PreviousShotsView cleaned up resources on close")
