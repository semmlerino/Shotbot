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
    QSortFilterProxyModel,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from shots.shot_grid_delegate import ShotGridDelegate
from shots.shot_item_model import ShotItemModel
from type_definitions import Shot
from typing_compat import override

# Local application imports
from ui.base_item_model import BaseItemRole
from ui.base_shot_grid_view import BaseShotGridView


if TYPE_CHECKING:
    # Third-party imports
    # Local application imports
    from PySide6.QtWidgets import QMenu

    from managers.hide_manager import HideManager
    from managers.notes_manager import NotesManager
    from managers.shot_pin_manager import ShotPinManager
    from ui.base_grid_view import HasAvailableShows
    from ui.base_thumbnail_delegate import BaseThumbnailDelegate


@final
class ShotGridView(BaseShotGridView):
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
        self.publish_button.setToolTip(
            "Launch publish_standalone for the selected shot"
        )
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

    def set_model(
        self, model: ShotItemModel, proxy: QSortFilterProxyModel | None = None
    ) -> None:
        """Set the data model for the view.

        Args:
            model: Shot item model
            proxy: Optional proxy model for filtering/sorting

        """
        self._set_model_common(model, proxy)

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
                raise TypeError(msg)
            show_list: list[str] = list(shows.get_available_shows())
            super().populate_show_filter(show_list)
            show_count = len(show_list)
            show_word = "show" if show_count == 1 else "shows"
            self.logger.info(f"Populated show filter with {show_count} {show_word}")

    @Slot()  # pyright: ignore[reportAny]
    def _on_model_updated(self) -> None:  # pyright: ignore[reportUnusedFunction]
        """Handle model updates."""
        # Update grid layout based on new item count
        self._update_grid_size()

        # Reset visible range tracking
        self._update_visible_range()

    @override
    def on_selected_shot_changed(self, shot: Shot | None) -> None:
        """Update publish button enabled state when selection changes."""
        self.publish_button.setEnabled(shot is not None)

    @override
    def _get_launch_apps(self) -> list[tuple[str, str, str, str, str]]:
        """Return launch apps including Publish."""
        return [
            ("3DEqualizer", "3", "3de", "target", "#00CED1"),
            ("Nuke", "N", "nuke", "palette", "#FF8C00"),
            ("Maya", "M", "maya", "cube", "#9B59B6"),
            ("RV", "R", "rv", "play", "#2ECC71"),
            ("Publish", "P", "publish", "clipboard", "#5D8A5E"),
        ]

    @override
    def _add_shot_specific_menu_actions(self, menu: QMenu, shot: Shot) -> None:
        """Add hide/unhide action to context menu."""
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
            shot: Shot | None = cast("Shot | None", index.data(BaseItemRole.ObjectRole))

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

    @property
    @override
    def _item_model(self) -> ShotItemModel | None:
        """Return the underlying ShotItemModel for pin-order refresh.

        Returns:
            The ShotItemModel, or None if not set

        """
        return cast("ShotItemModel | None", self._model)

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
    from shots.shot_item_model import ShotItemModel

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
