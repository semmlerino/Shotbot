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
    QPoint,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
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
from runnable_tracker import FolderOpenerWorker
from shot_grid_delegate import ShotGridDelegate
from shot_item_model import ShotItemModel
from shot_model import Shot
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

    def _create_icon(self, icon_type: str, color: str, size: int = 33) -> QIcon:
        """Create a coloured shaped icon for menu items.

        Args:
            icon_type: Icon type - "pin", "folder", "film", "rocket", "target",
                      "palette", "cube", "play", "clipboard", "note"
            color: Hex colour string (e.g., "#FF6B6B")
            size: Icon size in pixels

        Returns:
            QIcon with the specified shape and colour

        """
        from PySide6.QtGui import QPen

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)

        # Scale factor for drawing
        s = size

        if icon_type == "pin":
            # Pushpin: round head + long needle
            # Head (top circle)
            painter.drawEllipse(int(s * 0.25), int(s * 0.05), int(s * 0.5), int(s * 0.35))
            # Needle body (rectangle)
            painter.drawRect(int(s * 0.42), int(s * 0.35), int(s * 0.16), int(s * 0.4))
            # Needle point (triangle)
            points = [
                QPoint(int(s * 0.42), int(s * 0.75)),
                QPoint(int(s * 0.58), int(s * 0.75)),
                QPoint(int(s * 0.5), int(s * 0.98)),
            ]
            painter.drawPolygon(points)

        elif icon_type == "folder":
            # Open folder with document
            # Back of folder
            painter.drawRoundedRect(
                int(s * 0.05), int(s * 0.2), int(s * 0.9), int(s * 0.65), 3, 3
            )
            # Folder tab
            painter.drawRoundedRect(
                int(s * 0.05), int(s * 0.12), int(s * 0.35), int(s * 0.15), 2, 2
            )
            # Document peeking out (white)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRect(int(s * 0.25), int(s * 0.08), int(s * 0.5), int(s * 0.45))
            # Document lines
            painter.setPen(QPen(QColor(color), 1))
            for i in range(3):
                y = int(s * (0.18 + i * 0.12))
                painter.drawLine(int(s * 0.32), y, int(s * 0.68), y)

        elif icon_type == "film":
            # Clapperboard with diagonal stripes
            # Main board
            painter.drawRect(int(s * 0.05), int(s * 0.25), int(s * 0.9), int(s * 0.7))
            # Clapper top (angled)
            points = [
                QPoint(int(s * 0.05), int(s * 0.25)),
                QPoint(int(s * 0.15), int(s * 0.05)),
                QPoint(int(s * 0.95), int(s * 0.05)),
                QPoint(int(s * 0.95), int(s * 0.25)),
            ]
            painter.drawPolygon(points)
            # Diagonal stripes on clapper (white)
            painter.setBrush(QColor("#FFFFFF"))
            stripe_points = [
                [
                    QPoint(int(s * 0.25), int(s * 0.05)),
                    QPoint(int(s * 0.35), int(s * 0.05)),
                    QPoint(int(s * 0.25), int(s * 0.25)),
                    QPoint(int(s * 0.15), int(s * 0.25)),
                ],
                [
                    QPoint(int(s * 0.55), int(s * 0.05)),
                    QPoint(int(s * 0.65), int(s * 0.05)),
                    QPoint(int(s * 0.55), int(s * 0.25)),
                    QPoint(int(s * 0.45), int(s * 0.25)),
                ],
                [
                    QPoint(int(s * 0.85), int(s * 0.05)),
                    QPoint(int(s * 0.95), int(s * 0.05)),
                    QPoint(int(s * 0.85), int(s * 0.25)),
                    QPoint(int(s * 0.75), int(s * 0.25)),
                ],
            ]
            for stripe in stripe_points:
                painter.drawPolygon(stripe)

        elif icon_type == "plate":
            # Film strip frame with sprocket holes (for viewing footage)
            # Main frame area
            painter.drawRect(int(s * 0.15), int(s * 0.05), int(s * 0.7), int(s * 0.9))
            # Left sprocket strip
            painter.drawRect(int(s * 0.0), int(s * 0.05), int(s * 0.15), int(s * 0.9))
            # Right sprocket strip
            painter.drawRect(int(s * 0.85), int(s * 0.05), int(s * 0.15), int(s * 0.9))
            # Sprocket holes (left side)
            painter.setBrush(QColor("#FFFFFF"))
            for i in range(4):
                y = int(s * (0.12 + i * 0.22))
                painter.drawRoundedRect(
                    int(s * 0.03), y, int(s * 0.09), int(s * 0.12), 1, 1
                )
            # Sprocket holes (right side)
            for i in range(4):
                y = int(s * (0.12 + i * 0.22))
                painter.drawRoundedRect(
                    int(s * 0.88), y, int(s * 0.09), int(s * 0.12), 1, 1
                )
            # Inner frame (image area) - slightly darker
            painter.setBrush(QColor(color).darker(120))
            painter.drawRect(int(s * 0.22), int(s * 0.15), int(s * 0.56), int(s * 0.7))

        elif icon_type == "rocket":
            # Rocket with nose cone, body, fins, and flame
            painter.setBrush(QColor(color))
            # Nose cone (triangle)
            nose = [
                QPoint(int(s * 0.5), 0),
                QPoint(int(s * 0.3), int(s * 0.25)),
                QPoint(int(s * 0.7), int(s * 0.25)),
            ]
            painter.drawPolygon(nose)
            # Body
            painter.drawRect(int(s * 0.3), int(s * 0.25), int(s * 0.4), int(s * 0.45))
            # Left fin
            fin_left = [
                QPoint(int(s * 0.3), int(s * 0.5)),
                QPoint(int(s * 0.05), int(s * 0.75)),
                QPoint(int(s * 0.3), int(s * 0.7)),
            ]
            painter.drawPolygon(fin_left)
            # Right fin
            fin_right = [
                QPoint(int(s * 0.7), int(s * 0.5)),
                QPoint(int(s * 0.95), int(s * 0.75)),
                QPoint(int(s * 0.7), int(s * 0.7)),
            ]
            painter.drawPolygon(fin_right)
            # Flame (orange/yellow gradient effect)
            painter.setBrush(QColor("#FF6600"))
            flame = [
                QPoint(int(s * 0.35), int(s * 0.7)),
                QPoint(int(s * 0.65), int(s * 0.7)),
                QPoint(int(s * 0.5), int(s * 0.98)),
            ]
            painter.drawPolygon(flame)
            painter.setBrush(QColor("#FFCC00"))
            inner_flame = [
                QPoint(int(s * 0.42), int(s * 0.7)),
                QPoint(int(s * 0.58), int(s * 0.7)),
                QPoint(int(s * 0.5), int(s * 0.88)),
            ]
            painter.drawPolygon(inner_flame)

        elif icon_type == "target":
            # Crosshair/target with lines through center
            # Outer ring
            painter.drawEllipse(int(s * 0.08), int(s * 0.08), int(s * 0.84), int(s * 0.84))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(int(s * 0.2), int(s * 0.2), int(s * 0.6), int(s * 0.6))
            painter.setBrush(QColor(color))
            painter.drawEllipse(int(s * 0.35), int(s * 0.35), int(s * 0.3), int(s * 0.3))
            # Crosshair lines
            painter.setPen(QPen(QColor(color), max(1, int(s * 0.06))))
            painter.drawLine(int(s * 0.5), 0, int(s * 0.5), int(s * 0.3))
            painter.drawLine(int(s * 0.5), int(s * 0.7), int(s * 0.5), s)
            painter.drawLine(0, int(s * 0.5), int(s * 0.3), int(s * 0.5))
            painter.drawLine(int(s * 0.7), int(s * 0.5), s, int(s * 0.5))

        elif icon_type == "palette":
            # Artist palette with thumb hole
            # Main palette shape (bean-like)
            painter.drawEllipse(int(s * 0.05), int(s * 0.15), int(s * 0.9), int(s * 0.7))
            # Thumb hole (cut out)
            painter.setBrush(QColor("#00000000"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.drawEllipse(int(s * 0.12), int(s * 0.55), int(s * 0.2), int(s * 0.22))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            # Paint blobs
            paint_colors = ["#E74C3C", "#3498DB", "#F1C40F", "#2ECC71", "#9B59B6"]
            positions = [(0.35, 0.25), (0.6, 0.22), (0.78, 0.35), (0.7, 0.55), (0.45, 0.5)]
            for c, (px, py) in zip(paint_colors, positions, strict=True):
                painter.setBrush(QColor(c))
                painter.drawEllipse(
                    int(s * px), int(s * py), int(s * 0.15), int(s * 0.15)
                )

        elif icon_type == "cube":
            # 3D cube with visible edges
            # Use lighter shade for top and right faces
            base_color = QColor(color)
            light_color = base_color.lighter(130)
            dark_color = base_color.darker(120)
            # Front face
            painter.setBrush(base_color)
            painter.drawRect(int(s * 0.1), int(s * 0.35), int(s * 0.5), int(s * 0.55))
            # Top face (lighter)
            painter.setBrush(light_color)
            top = [
                QPoint(int(s * 0.1), int(s * 0.35)),
                QPoint(int(s * 0.35), int(s * 0.1)),
                QPoint(int(s * 0.85), int(s * 0.1)),
                QPoint(int(s * 0.6), int(s * 0.35)),
            ]
            painter.drawPolygon(top)
            # Right face (darker)
            painter.setBrush(dark_color)
            right = [
                QPoint(int(s * 0.6), int(s * 0.35)),
                QPoint(int(s * 0.85), int(s * 0.1)),
                QPoint(int(s * 0.85), int(s * 0.65)),
                QPoint(int(s * 0.6), int(s * 0.9)),
            ]
            painter.drawPolygon(right)

        elif icon_type == "play":
            # Classic play button - rounded rect with bold triangle
            # Rounded rectangle background
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(
                int(s * 0.02), int(s * 0.02), int(s * 0.96), int(s * 0.96), 4, 4
            )
            # Bold play triangle (white, larger and centered)
            painter.setBrush(QColor("#FFFFFF"))
            play = [
                QPoint(int(s * 0.3), int(s * 0.15)),
                QPoint(int(s * 0.3), int(s * 0.85)),
                QPoint(int(s * 0.85), int(s * 0.5)),
            ]
            painter.drawPolygon(play)

        elif icon_type == "clipboard":
            # Clipboard with checkmark
            # Board
            painter.drawRoundedRect(
                int(s * 0.1), int(s * 0.15), int(s * 0.8), int(s * 0.8), 3, 3
            )
            # Clip at top (metallic)
            painter.setBrush(QColor("#888888"))
            painter.drawRoundedRect(
                int(s * 0.3), int(s * 0.02), int(s * 0.4), int(s * 0.2), 2, 2
            )
            # Checkmark (white)
            painter.setPen(QPen(QColor("#FFFFFF"), max(2, int(s * 0.12))))
            painter.drawLine(
                int(s * 0.25), int(s * 0.55), int(s * 0.42), int(s * 0.75)
            )
            painter.drawLine(
                int(s * 0.42), int(s * 0.75), int(s * 0.75), int(s * 0.35)
            )

        elif icon_type == "note":
            # Sticky note with folded corner
            # Note body
            painter.drawRect(int(s * 0.08), int(s * 0.08), int(s * 0.84), int(s * 0.84))
            # Folded corner (darker)
            painter.setBrush(QColor(color).darker(130))
            fold = [
                QPoint(int(s * 0.65), int(s * 0.08)),
                QPoint(int(s * 0.92), int(s * 0.08)),
                QPoint(int(s * 0.92), int(s * 0.35)),
            ]
            painter.drawPolygon(fold)
            # Lines on note
            painter.setPen(QPen(QColor("#FFFFFF").darker(110), 1))
            for i in range(3):
                y = int(s * (0.35 + i * 0.18))
                painter.drawLine(int(s * 0.18), y, int(s * 0.82), y)

        else:
            # Fallback: simple circle
            painter.drawEllipse(int(s * 0.1), int(s * 0.1), int(s * 0.8), int(s * 0.8))

        _ = painter.end()
        return QIcon(pixmap)

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
