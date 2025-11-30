"""Optimized grid view for shot thumbnails using Qt Model/View architecture.

This module provides a QListView-based implementation that replaces the manual
widget management approach, providing virtualization, efficient scrolling,
and proper Model/View integration.
"""

from __future__ import annotations

# Standard library imports
import shlex
import subprocess
from typing import TYPE_CHECKING, cast, final

# Third-party imports
from PySide6.QtCore import (
    QModelIndex,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QPushButton,
    QWidget,
)

# Local application imports
from base_grid_view import BaseGridView, HasAvailableShows
from base_item_model import BaseItemRole
from shot_grid_delegate import ShotGridDelegate
from shot_item_model import ShotItemModel
from shot_model import Shot
from thumbnail_widget_base import FolderOpenerWorker
from typing_compat import override


# Backward compatibility alias
ShotRole = BaseItemRole

if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtGui import QContextMenuEvent

    # Local application imports
    from base_thumbnail_delegate import BaseThumbnailDelegate
    from notes_manager import NotesManager
    from pin_manager import PinManager


@final
class ShotGridView(BaseGridView):
    """Optimized grid view for displaying shot thumbnails.

    This view provides:
    - Virtualization (only renders visible items)
    - Efficient scrolling for large datasets
    - Lazy loading of thumbnails
    - Proper Model/View integration
    - Dynamic grid layout based on window size
    - Context menu for folder operations
    """

    # Additional signals specific to ShotGridView
    shot_selected = Signal(Shot)  # Shot object
    shot_double_clicked = Signal(Shot)  # Shot object
    recover_crashes_requested = Signal()  # User clicked recover crashes button
    pin_shot_requested = Signal(Shot)  # User wants to pin a shot

    def __init__(
        self,
        model: ShotItemModel | None = None,
        pin_manager: PinManager | None = None,
        notes_manager: NotesManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the grid view.

        Args:
            model: Optional shot item model
            pin_manager: Optional pin manager for pinning shots
            notes_manager: Optional notes manager for shot notes
            parent: Optional parent widget
        """
        # Initialize widgets that will be created in template methods
        # These are set to None initially but will be assigned during super().__init__()
        self.recover_button: QPushButton

        # Initialize base class
        super().__init__(parent)

        # ShotGridView-specific attributes
        self._selected_shot: Shot | None = None
        self._pin_manager: PinManager | None = pin_manager
        self._notes_manager: NotesManager | None = notes_manager

        if model:
            self.set_model(model)

        self.logger.debug("ShotGridView initialized")

    @override
    def _create_delegate(self) -> BaseThumbnailDelegate:
        """Create the shot grid delegate.

        Returns:
            ShotGridDelegate instance
        """
        return ShotGridDelegate(self)

    @override
    def _add_toolbar_widgets(self, layout: QHBoxLayout) -> None:
        """Add recovery button to toolbar.

        Args:
            layout: The toolbar horizontal layout
        """
        # Recovery button for 3DE crash files
        self.recover_button = QPushButton("Recover Crashes...")
        self.recover_button.setToolTip(
            "Scan for and recover 3DE crash files in the current shot's workspace"
        )
        _ = self.recover_button.clicked.connect(
            lambda: self.recover_crashes_requested.emit()
        )
        layout.addWidget(self.recover_button)

        # Push button to the right
        layout.addStretch()

    @property
    def model(self) -> ShotItemModel | None:
        """Get the current data model.

        Returns:
            The shot item model or None
        """
        # Cast base class _model to more specific type
        return cast("ShotItemModel | None", self._model)

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

    def refresh_shots(self) -> None:
        """Compatibility method for refreshing shots.

        This method exists for compatibility with the old ShotGrid interface.
        It's not needed for Model/View as updates happen through the model.
        """
        # Model/View updates automatically when model data changes
        # This method is kept for interface compatibility
        model = cast("ShotItemModel | None", self._model)
        if model:
            # Force a view update
            self.list_view.viewport().update()
            self.logger.debug(
                "View refresh requested (Model/View updates automatically)"
            )

    def set_model(self, model: ShotItemModel) -> None:
        """Set the data model for the view.

        Args:
            model: Shot item model
        """
        # Store in base class attribute (base type is QAbstractItemModel)
        self._model = model
        self.list_view.setModel(model)

        # Set up selection model
        selection_model = self.list_view.selectionModel()
        if selection_model:
            _ = selection_model.currentChanged.connect(self._on_selection_changed)  # pyright: ignore[reportAny]

        # Connect to model signals
        _ = model.shots_updated.connect(self._on_model_updated)  # pyright: ignore[reportAny]

        self.logger.debug(f"Model set with {model.rowCount()} items")

    @override
    def populate_show_filter(self, shows: list[str] | HasAvailableShows) -> None:
        """Populate the show filter combo box with available shows.

        This override accepts either a list of show names or an object implementing
        HasAvailableShows protocol. When passed a protocol object, it extracts shows
        and delegates to base class.

        Args:
            shows: Either a list of show names or an object with get_available_shows() method
        """
        # Handle list case (delegate to base with type narrowing)
        if isinstance(shows, list):
            # Type narrowing: shows is list[str] after isinstance check
            super().populate_show_filter(shows)
        else:
            # Handle protocol case (extract shows using duck typing)
            # Use duck typing instead of isinstance for test compatibility
            if not hasattr(shows, "get_available_shows"):
                raise TypeError(
                    f"Expected list[str] or HasAvailableShows protocol, got {type(shows).__name__}"
                )
            show_list: list[str] = list(shows.get_available_shows())
            super().populate_show_filter(show_list)
            show_count = len(show_list)
            show_word = "show" if show_count == 1 else "shows"
            self.logger.info(f"Populated show filter with {show_count} {show_word}")

    @Slot()  # pyright: ignore[reportAny]
    def _on_model_updated(self) -> None:
        """Handle model updates."""
        # Update grid layout based on new item count
        self._update_grid_size()

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
        model = cast("ShotItemModel | None", self._model)
        if not index.isValid() or not model:
            return

        # Get shot object - index.data() returns Any from Qt API
        shot: Shot | None = cast("Shot | None", index.data(ShotRole.ObjectRole))

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
        model = cast("ShotItemModel | None", self._model)
        if not model:
            return

        # Clear previous selection in model
        if previous.isValid():
            _ = model.setData(previous, False, ShotRole.IsSelectedRole)

        # Set current selection in model
        if current.isValid():
            _ = model.setData(current, True, ShotRole.IsSelectedRole)

            # Get shot object - index.data() returns Any from Qt API
            shot: Shot | None = cast("Shot | None", current.data(ShotRole.ObjectRole))

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
        model = cast("ShotItemModel | None", self._model)
        if model:
            model.set_visible_range(start, end)  # pyright: ignore[reportAny]

    def select_shot_by_name(self, shot_name: str) -> None:
        """Select a shot by its full name.

        Args:
            shot_name: Full shot name to select
        """
        model = cast("ShotItemModel | None", self._model)
        if not model:
            return

        # Find the shot in the model
        for row in range(model.rowCount()):
            index = model.index(row, 0)

            # Get shot object - index.data() returns Any from Qt API
            shot: Shot | None = cast("Shot | None", index.data(ShotRole.ObjectRole))

            if shot and shot.full_name == shot_name:
                # Select in view
                self.list_view.setCurrentIndex(index)

                # Ensure it's visible
                self.list_view.scrollTo(
                    index,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )

                # Trigger selection
                self._on_item_clicked(index)  # pyright: ignore[reportAny]
                break

    def clear_selection(self) -> None:
        """Clear the current selection."""
        if self.list_view.selectionModel():
            self.list_view.selectionModel().clear()

        self._selected_shot = None

    def refresh_view(self) -> None:
        """Force a complete view refresh."""
        self.list_view.viewport().update()
        self._update_visible_range()

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

        model = cast("ShotItemModel | None", self._model)
        if not index.isValid() or not model:
            # No item clicked, show no menu
            return

        # Get shot object - index.data() returns Any from Qt API
        shot: Shot | None = cast("Shot | None", index.data(ShotRole.ObjectRole))

        if not shot:
            return

        # Create context menu
        menu = QMenu(self)

        # Pin/Unpin shot action (at the top for quick access)
        if self._pin_manager and self._pin_manager.is_pinned(shot):
            unpin_action = menu.addAction("Unpin Shot")
            _ = unpin_action.triggered.connect(
                lambda checked=False, s=shot: self._unpin_shot(s)  # noqa: ARG005
            )
        else:
            pin_action = menu.addAction("Pin Shot")
            _ = pin_action.triggered.connect(
                lambda checked=False, s=shot: self._pin_shot(s)  # noqa: ARG005
            )

        _ = menu.addSeparator()

        # Primary action: Open Shot Folder
        open_folder_action = menu.addAction("Open Shot Folder")
        _ = open_folder_action.triggered.connect(lambda: self._open_shot_folder(shot))

        # Open Main Plate in RV
        open_plate_action = menu.addAction("Open Main Plate in RV")
        _ = open_plate_action.triggered.connect(
            lambda: self._open_main_plate_in_rv(shot)
        )

        _ = menu.addSeparator()

        # Launch Application submenu (with keyboard shortcuts visible)
        launch_menu = menu.addMenu("Launch Application")
        launch_apps = [
            ("3DEqualizer", "3", "3de"),
            ("Nuke", "N", "nuke"),
            ("Maya", "M", "maya"),
            ("RV", "R", "rv"),
        ]
        for label, shortcut, app_id in launch_apps:
            action = launch_menu.addAction(f"{label}  ({shortcut})")
            # Use default parameter to capture app_id correctly in lambda
            _ = action.triggered.connect(
                lambda checked=False, a=app_id: self.app_launch_requested.emit(a)  # noqa: ARG005
            )

        _ = menu.addSeparator()

        # Copy Shot Path action
        copy_path_action = menu.addAction("Copy Shot Path")
        _ = copy_path_action.triggered.connect(
            lambda: self._copy_path_to_clipboard(shot.workspace_path)
        )

        _ = menu.addSeparator()

        # Edit/Add Note action
        has_note = (
            self._notes_manager.has_note(shot) if self._notes_manager else False
        )
        note_label = "Edit Note" if has_note else "Add Note"
        edit_note_action = menu.addAction(note_label)
        _ = edit_note_action.triggered.connect(
            lambda checked=False, s=shot: self._edit_shot_note(s)  # noqa: ARG005
        )

        # Show menu at cursor position
        _ = menu.exec(event.globalPos())

        self.logger.debug(f"Context menu shown for shot: {shot.full_name}")

    def _open_shot_folder(self, shot: Shot) -> None:
        """Open the shot's workspace folder in system file manager (non-blocking).

        Args:
            shot: Shot object containing workspace path
        """
        folder_path = shot.workspace_path

        # Create worker to open folder in background
        worker = FolderOpenerWorker(folder_path)

        # Connect signals with QueuedConnection for thread safety
        # Note: Slot decorators cause type checker to see methods as Any
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
        # Could show a QMessageBox here if desired

    @Slot()  # pyright: ignore[reportAny]
    def _on_folder_open_success(self) -> None:
        """Handle successful folder opening."""
        self.logger.debug("Folder opened successfully")

    def _open_main_plate_in_rv(self, shot: Shot) -> None:
        """Open the main plate in RV.

        Args:
            shot: Shot object containing workspace path
        """
        from notification_manager import error as notify_error
        from publish_plate_finder import find_main_plate

        workspace_path = shot.workspace_path
        plate_path = find_main_plate(workspace_path)

        if plate_path is None:
            self.logger.warning(f"No plate found for shot at {workspace_path}")
            notify_error("No Plate Found", f"No plate found for shot at {workspace_path}")
            return

        self.logger.info(f"Opening plate in RV: {plate_path}")
        try:
            # Use bash -ilc to inherit shell environment where Rez adds RV to PATH
            # RV settings: 12fps, auto-play, ping-pong mode (setPlayMode(2))
            safe_path = shlex.quote(plate_path)
            rv_cmd = f"rv {safe_path} -fps 12 -play -eval 'setPlayMode(2)'"
            _ = subprocess.Popen(["bash", "-ilc", rv_cmd])
        except FileNotFoundError:
            self.logger.error("RV not found. Please ensure RV is installed and in PATH.")
            notify_error("RV Not Found", "Could not launch RV. Check that RV is installed.")
        except Exception as e:
            self.logger.error(f"Failed to open RV: {e}")
            notify_error("RV Launch Failed", f"Failed to open RV: {e}")

    def _copy_path_to_clipboard(self, path: str) -> None:
        """Copy a path to the system clipboard.

        Args:
            path: The path string to copy
        """
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(path)
            self.logger.debug(f"Copied path to clipboard: {path}")

    def _edit_shot_note(self, shot: Shot) -> None:
        """Open dialog to edit note for shot.

        Args:
            shot: Shot to edit note for
        """
        if not self._notes_manager:
            return

        current_note = self._notes_manager.get_note(shot)
        new_note, ok = QInputDialog.getMultiLineText(
            self,
            f"Note for {shot.full_name}",
            "Note:",
            current_note,
        )
        if ok:
            self._notes_manager.set_note(shot, new_note)
            self.logger.debug(f"Note updated for shot: {shot.full_name}")

    def _pin_shot(self, shot: Shot) -> None:
        """Pin a shot.

        Args:
            shot: Shot to pin
        """
        if self._pin_manager:
            self._pin_manager.pin_shot(shot)
            self._refresh_with_pins()
        else:
            # Fallback: emit signal for external handling
            self.pin_shot_requested.emit(shot)

    def _unpin_shot(self, shot: Shot) -> None:
        """Unpin a shot.

        Args:
            shot: Shot to unpin
        """
        if self._pin_manager:
            self._pin_manager.unpin_shot(shot)
            self._refresh_with_pins()

    def _refresh_with_pins(self) -> None:
        """Re-sort and refresh grid to reflect pin changes."""
        model = cast("ShotItemModel | None", self._model)
        if model:
            model.refresh_pin_order()
            # Force view update
            self.list_view.viewport().update()

    def set_pin_manager(self, pin_manager: PinManager) -> None:
        """Set the pin manager.

        Args:
            pin_manager: Pin manager for pinning shots
        """
        self._pin_manager = pin_manager


# Example usage
if __name__ == "__main__":
    # Standard library imports
    import sys

    # Third-party imports
    from PySide6.QtWidgets import QApplication

    # Local application imports
    from shot_model import Shot

    app = QApplication(sys.argv)

    # Create sample data
    shots = [
        Shot("show1", "seq01", f"shot{i:04d}", f"/shows/show1/shots/seq01/shot{i:04d}")
        for i in range(100)
    ]

    # Create model and view
    from shot_item_model import ShotItemModel

    model = ShotItemModel()
    model.set_shots(shots)

    view = ShotGridView(model)
    view.resize(800, 600)
    view.show()

    # Connect signals with explicit type annotations
    def on_shot_selected(shot: Shot) -> None:
        print(f"Selected: {shot.full_name}")

    def on_shot_double_clicked(shot: Shot) -> None:
        print(f"Double-clicked: {shot.full_name}")

    _ = view.shot_selected.connect(on_shot_selected)
    _ = view.shot_double_clicked.connect(on_shot_double_clicked)

    sys.exit(app.exec())
