"""Optimized grid view for shot thumbnails using Qt Model/View architecture.

This module provides a QListView-based implementation that replaces the manual
widget management approach, providing virtualization, efficient scrolling,
and proper Model/View integration.
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING, cast, final

# Third-party imports
from PySide6.QtCore import (
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QWidget,
)

# Local application imports
from base_grid_view import BaseGridView, HasAvailableShows
from base_item_model import BaseItemRole
from runnable_tracker import FolderOpenerWorker
from shot_grid_delegate import ShotGridDelegate
from shot_item_model import ShotItemModel
from type_definitions import Shot
from typing_compat import override


# Backward compatibility alias
ShotRole = BaseItemRole

if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtGui import QContextMenuEvent

    # Local application imports
    from base_thumbnail_delegate import BaseThumbnailDelegate
    from hide_manager import HideManager
    from notes_manager import NotesManager
    from shot_pin_manager import ShotPinManager


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
    shot_visibility_changed = Signal()  # Shot was hidden or unhidden
    show_hidden_changed = Signal(bool)  # Show Hidden checkbox toggled

    def __init__(
        self,
        model: ShotItemModel | None = None,
        proxy: QSortFilterProxyModel | None = None,
        pin_manager: ShotPinManager | None = None,
        notes_manager: NotesManager | None = None,
        hide_manager: HideManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the grid view.

        Args:
            model: Optional shot item model
            proxy: Optional proxy model for filtering/sorting
            pin_manager: Optional pin manager for pinning shots
            notes_manager: Optional notes manager for shot notes
            hide_manager: Optional hide manager for hiding shots
            parent: Optional parent widget

        """
        # Initialize widgets that will be created in template methods
        # These are set to None initially but will be assigned during super().__init__()
        self.recover_button: QPushButton

        # Initialize base class
        super().__init__(parent)

        # ShotGridView-specific attributes
        self._selected_shot: Shot | None = None
        self._pin_manager: ShotPinManager | None = pin_manager
        self._notes_manager: NotesManager | None = notes_manager
        self._hide_manager: HideManager | None = hide_manager

        if model:
            self.set_model(model, proxy)

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

        self.publish_button = QPushButton("Publish  (P)")
        self.publish_button.setToolTip("Launch publish_standalone for the selected shot")
        self.publish_button.setEnabled(False)
        _ = self.publish_button.clicked.connect(
            lambda: self.app_launch_requested.emit("publish")
        )
        layout.addWidget(self.publish_button)

        self.show_hidden_checkbox = QCheckBox("Show Hidden")
        self.show_hidden_checkbox.setToolTip("Show hidden shots (dimmed)")
        _ = self.show_hidden_checkbox.toggled.connect(self._on_show_hidden_toggled)
        layout.addWidget(self.show_hidden_checkbox)

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


    def set_model(self, model: ShotItemModel, proxy: QSortFilterProxyModel | None = None) -> None:
        """Set the data model for the view.

        Args:
            model: Shot item model
            proxy: Optional proxy model for filtering/sorting

        """

        # Store in base class attribute (base type is QAbstractItemModel)
        self._model = model
        self.list_view.setModel(proxy if proxy is not None else model)
        self._connect_model_visibility(model)

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
                msg = f"Expected list[str] or HasAvailableShows protocol, got {type(shows).__name__}"
                raise TypeError(
                    msg
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
        _ = index

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
        _previous: QModelIndex,
    ) -> None:
        """Handle selection change.

        Args:
            current: Current selection index
            previous: Previous selection index

        """
        model = cast("ShotItemModel | None", self._model)
        if not model:
            return

        if current.isValid():
            # Get shot object - index.data() returns Any from Qt API
            shot: Shot | None = cast("Shot | None", current.data(ShotRole.ObjectRole))

            if shot:
                self._selected_shot = shot
                self.shot_selected.emit(shot)
                self.publish_button.setEnabled(True)
                return

        self.publish_button.setEnabled(False)

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

        # Create context menu with enlarged styling (50% larger)
        menu = QMenu(self)
        menu_style = """
            QMenu {
                font-size: 18px;
                padding: 8px;
            }
            QMenu::item {
                padding: 12px 24px 12px 12px;
                min-width: 200px;
            }
            QMenu::item:selected {
                background-color: #3daee9;
            }
            QMenu::separator {
                height: 2px;
                margin: 6px 12px;
            }
        """
        menu.setStyleSheet(menu_style)

        # Pin/Unpin shot action (at the top for quick access)
        if self._pin_manager and self._pin_manager.is_pinned(shot):
            unpin_action = menu.addAction("Unpin Shot")
            unpin_action.setIcon(self._create_icon("pin", "#FF6B6B"))
            _ = unpin_action.triggered.connect(
                lambda checked=False, s=shot: self._unpin_shot(s)  # noqa: ARG005
            )
        else:
            pin_action = menu.addAction("Pin Shot")
            pin_action.setIcon(self._create_icon("pin", "#FF6B6B"))
            _ = pin_action.triggered.connect(
                lambda checked=False, s=shot: self._pin_shot(s)  # noqa: ARG005
            )

        # Hide/Unhide shot action
        if self._hide_manager and self._hide_manager.is_hidden(shot):
            unhide_action = menu.addAction("Unhide Shot")
            unhide_action.setIcon(self._create_icon("note", "#888888"))
            _ = unhide_action.triggered.connect(
                lambda checked=False, s=shot: self._unhide_shot(s)  # noqa: ARG005
            )
        else:
            hide_action = menu.addAction("Hide Shot")
            hide_action.setIcon(self._create_icon("note", "#888888"))
            _ = hide_action.triggered.connect(
                lambda checked=False, s=shot: self._hide_shot(s)  # noqa: ARG005
            )

        _ = menu.addSeparator()

        # Primary action: Open Shot Folder
        open_folder_action = menu.addAction("Open Shot Folder")
        open_folder_action.setIcon(self._create_icon("folder", "#FFB347"))
        _ = open_folder_action.triggered.connect(lambda: self._open_shot_folder(shot))

        # Open Main Plate in RV
        open_plate_action = menu.addAction("Open Main Plate in RV")
        open_plate_action.setIcon(self._create_icon("play", "#FF4757"))
        _ = open_plate_action.triggered.connect(
            lambda: self._open_main_plate_in_rv(shot)
        )

        _ = menu.addSeparator()

        # Launch Application submenu (with keyboard shortcuts visible)
        launch_menu = menu.addMenu("Launch Application")
        launch_menu.setStyleSheet(menu_style)
        launch_menu.setIcon(self._create_icon("rocket", "#95D5B2"))
        launch_apps = [
            ("3DEqualizer", "3", "3de", "target", "#00CED1"),
            ("Nuke", "N", "nuke", "palette", "#FF8C00"),
            ("Maya", "M", "maya", "cube", "#9B59B6"),
            ("RV", "R", "rv", "play", "#2ECC71"),
            ("Publish", "P", "publish", "clipboard", "#5D8A5E"),
        ]
        for label, shortcut, app_id, icon_type, color in launch_apps:
            action = launch_menu.addAction(f"{label}  ({shortcut})")
            action.setIcon(self._create_icon(icon_type, color))
            # Use default parameter to capture app_id correctly in lambda
            _ = action.triggered.connect(
                lambda checked=False, a=app_id: self.app_launch_requested.emit(a)  # noqa: ARG005
            )

        _ = menu.addSeparator()

        # Copy Shot Path action
        copy_path_action = menu.addAction("Copy Shot Path")
        copy_path_action.setIcon(self._create_icon("clipboard", "#95A5A6"))
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
        edit_note_action.setIcon(self._create_icon("note", "#F1C40F"))
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

    @property
    @override
    def _item_model(self) -> ShotItemModel | None:
        """Return the underlying ShotItemModel for pin-order refresh.

        Returns:
            The ShotItemModel, or None if not set

        """
        return cast("ShotItemModel | None", self._model)

    def set_pin_manager(self, pin_manager: ShotPinManager) -> None:
        """Set the pin manager.

        Args:
            pin_manager: Pin manager for pinning shots

        """
        self._pin_manager = pin_manager

    def set_hide_manager(self, hide_manager: HideManager) -> None:
        """Set the hide manager.

        Args:
            hide_manager: Hide manager for hiding shots

        """
        self._hide_manager = hide_manager

    def _hide_shot(self, shot: Shot) -> None:
        """Hide a shot.

        Args:
            shot: Shot to hide

        """
        if self._hide_manager:
            self._hide_manager.hide_shot(shot)
            self.shot_visibility_changed.emit()

    def _unhide_shot(self, shot: Shot) -> None:
        """Unhide a shot.

        Args:
            shot: Shot to unhide

        """
        if self._hide_manager:
            self._hide_manager.unhide_shot(shot)
            self.shot_visibility_changed.emit()

    def _on_show_hidden_toggled(self, checked: bool) -> None:
        """Handle Show Hidden checkbox toggle.

        Args:
            checked: Whether the checkbox is checked

        """
        self.show_hidden_changed.emit(checked)


# Example usage
if __name__ == "__main__":
    # Standard library imports
    import sys

    # Third-party imports
    from PySide6.QtWidgets import QApplication

    # Local application imports
    from type_definitions import Shot

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
