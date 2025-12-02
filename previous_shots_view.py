"""Qt Model/View implementation for previous shots grid.

This module provides an efficient QListView-based implementation for
displaying approved/completed shots, replacing the widget-heavy approach
with virtualization and proper Model/View architecture.
"""

from __future__ import annotations

# Standard library imports
import shlex
import subprocess
from typing import TYPE_CHECKING, ClassVar, cast

# Third-party imports
from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QPoint,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from base_grid_view import BaseGridView
from base_item_model import BaseItemRole
from design_system import design_system
from progress_manager import ProgressManager, update_progress
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
    from notes_manager import NotesManager
    from pin_manager import PinManager
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
    sort_order_changed: ClassVar[Signal] = Signal(str)  # "name" or "date"
    pin_shot_requested: ClassVar[Signal] = Signal(object)  # User wants to pin a shot

    # Class-level type annotation for base class _model attribute
    _model: QAbstractItemModel | None

    def __init__(
        self,
        model: PreviousShotsItemModel | None = None,
        pin_manager: PinManager | None = None,
        notes_manager: NotesManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the previous shots view.

        Args:
            model: Optional previous shots item model
            pin_manager: Optional pin manager for pinning shots
            notes_manager: Optional notes manager for shot notes
            parent: Optional parent widget
        """
        # Initialize instance variables before super().__init__()
        # These are set in methods called during base class initialization
        self._update_timer: QTimer | None = None
        self._status_label: QLabel | None = None
        self._refresh_button: QPushButton | None = None
        self._sort_name_btn: QPushButton | None = None
        self._sort_date_btn: QPushButton | None = None
        self._sort_button_group: QButtonGroup | None = None
        self._notes_manager: NotesManager | None = notes_manager

        # Initialize base class
        super().__init__(parent)

        # PreviousShotsView-specific attributes
        self._selected_shot: Shot | None = None
        self._pin_manager: PinManager | None = pin_manager
        # Note: Don't redefine _model - it's inherited from BaseGridView
        # We store the typed reference separately for type safety
        self._unified_model: PreviousShotsItemModel | None = model

        if model:
            self.set_model(model)

        self.logger.debug("PreviousShotsView initialized")

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

        # Sort toggle buttons
        sort_label = QLabel("Sort:")
        header_layout.addWidget(sort_label)

        self._sort_name_btn = QPushButton("Name")
        self._sort_name_btn.setCheckable(True)
        self._sort_name_btn.setToolTip("Sort by shot name alphabetically")
        self._sort_name_btn.setFixedWidth(50)
        header_layout.addWidget(self._sort_name_btn)

        self._sort_date_btn = QPushButton("Date")
        self._sort_date_btn.setCheckable(True)
        self._sort_date_btn.setChecked(True)  # Default: date (newest first)
        self._sort_date_btn.setToolTip("Sort by discovery date (newest first)")
        self._sort_date_btn.setFixedWidth(50)
        header_layout.addWidget(self._sort_date_btn)

        # Button group for exclusive selection
        self._sort_button_group = QButtonGroup(self)
        self._sort_button_group.addButton(self._sort_name_btn, 0)
        self._sort_button_group.addButton(self._sort_date_btn, 1)
        _ = self._sort_button_group.idClicked.connect(self._on_sort_button_clicked)

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
            # Update progress in status bar
            update_progress(current, f"Scanning {percent}%")

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

    def _create_icon(self, icon_type: str, color: str, size: int = 33) -> QIcon:
        """Create a coloured shaped icon for menu items.

        Args:
            icon_type: Icon type - "pin", "folder", "rocket", "target",
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
            painter.drawEllipse(int(s * 0.25), int(s * 0.05), int(s * 0.5), int(s * 0.35))
            painter.drawRect(int(s * 0.42), int(s * 0.35), int(s * 0.16), int(s * 0.4))
            points = [
                QPoint(int(s * 0.42), int(s * 0.75)),
                QPoint(int(s * 0.58), int(s * 0.75)),
                QPoint(int(s * 0.5), int(s * 0.98)),
            ]
            painter.drawPolygon(points)

        elif icon_type == "folder":
            # Open folder with document
            painter.drawRoundedRect(
                int(s * 0.05), int(s * 0.2), int(s * 0.9), int(s * 0.65), 3, 3
            )
            painter.drawRoundedRect(
                int(s * 0.05), int(s * 0.12), int(s * 0.35), int(s * 0.15), 2, 2
            )
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRect(int(s * 0.25), int(s * 0.08), int(s * 0.5), int(s * 0.45))
            painter.setPen(QPen(QColor(color), 1))
            for i in range(3):
                y = int(s * (0.18 + i * 0.12))
                painter.drawLine(int(s * 0.32), y, int(s * 0.68), y)

        elif icon_type == "rocket":
            # Rocket with nose cone, body, fins, and flame
            painter.setBrush(QColor(color))
            nose = [
                QPoint(int(s * 0.5), 0),
                QPoint(int(s * 0.3), int(s * 0.25)),
                QPoint(int(s * 0.7), int(s * 0.25)),
            ]
            painter.drawPolygon(nose)
            painter.drawRect(int(s * 0.3), int(s * 0.25), int(s * 0.4), int(s * 0.45))
            fin_left = [
                QPoint(int(s * 0.3), int(s * 0.5)),
                QPoint(int(s * 0.05), int(s * 0.75)),
                QPoint(int(s * 0.3), int(s * 0.7)),
            ]
            painter.drawPolygon(fin_left)
            fin_right = [
                QPoint(int(s * 0.7), int(s * 0.5)),
                QPoint(int(s * 0.95), int(s * 0.75)),
                QPoint(int(s * 0.7), int(s * 0.7)),
            ]
            painter.drawPolygon(fin_right)
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
            painter.drawEllipse(int(s * 0.08), int(s * 0.08), int(s * 0.84), int(s * 0.84))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(int(s * 0.2), int(s * 0.2), int(s * 0.6), int(s * 0.6))
            painter.setBrush(QColor(color))
            painter.drawEllipse(int(s * 0.35), int(s * 0.35), int(s * 0.3), int(s * 0.3))
            painter.setPen(QPen(QColor(color), max(1, int(s * 0.06))))
            painter.drawLine(int(s * 0.5), 0, int(s * 0.5), int(s * 0.3))
            painter.drawLine(int(s * 0.5), int(s * 0.7), int(s * 0.5), s)
            painter.drawLine(0, int(s * 0.5), int(s * 0.3), int(s * 0.5))
            painter.drawLine(int(s * 0.7), int(s * 0.5), s, int(s * 0.5))

        elif icon_type == "palette":
            # Artist palette with thumb hole
            painter.drawEllipse(int(s * 0.05), int(s * 0.15), int(s * 0.9), int(s * 0.7))
            painter.setBrush(QColor("#00000000"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.drawEllipse(int(s * 0.12), int(s * 0.55), int(s * 0.2), int(s * 0.22))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            paint_colors = ["#E74C3C", "#3498DB", "#F1C40F", "#2ECC71", "#9B59B6"]
            positions = [(0.35, 0.25), (0.6, 0.22), (0.78, 0.35), (0.7, 0.55), (0.45, 0.5)]
            for c, (px, py) in zip(paint_colors, positions, strict=True):
                painter.setBrush(QColor(c))
                painter.drawEllipse(
                    int(s * px), int(s * py), int(s * 0.15), int(s * 0.15)
                )

        elif icon_type == "cube":
            # 3D cube with visible edges
            base_color = QColor(color)
            light_color = base_color.lighter(130)
            dark_color = base_color.darker(120)
            painter.setBrush(base_color)
            painter.drawRect(int(s * 0.1), int(s * 0.35), int(s * 0.5), int(s * 0.55))
            painter.setBrush(light_color)
            top = [
                QPoint(int(s * 0.1), int(s * 0.35)),
                QPoint(int(s * 0.35), int(s * 0.1)),
                QPoint(int(s * 0.85), int(s * 0.1)),
                QPoint(int(s * 0.6), int(s * 0.35)),
            ]
            painter.drawPolygon(top)
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
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(
                int(s * 0.02), int(s * 0.02), int(s * 0.96), int(s * 0.96), 4, 4
            )
            painter.setBrush(QColor("#FFFFFF"))
            play = [
                QPoint(int(s * 0.3), int(s * 0.15)),
                QPoint(int(s * 0.3), int(s * 0.85)),
                QPoint(int(s * 0.85), int(s * 0.5)),
            ]
            painter.drawPolygon(play)

        elif icon_type == "clipboard":
            # Clipboard with checkmark
            painter.drawRoundedRect(
                int(s * 0.1), int(s * 0.15), int(s * 0.8), int(s * 0.8), 3, 3
            )
            painter.setBrush(QColor("#888888"))
            painter.drawRoundedRect(
                int(s * 0.3), int(s * 0.02), int(s * 0.4), int(s * 0.2), 2, 2
            )
            painter.setPen(QPen(QColor("#FFFFFF"), max(2, int(s * 0.12))))
            painter.drawLine(
                int(s * 0.25), int(s * 0.55), int(s * 0.42), int(s * 0.75)
            )
            painter.drawLine(
                int(s * 0.42), int(s * 0.75), int(s * 0.75), int(s * 0.35)
            )

        elif icon_type == "note":
            # Sticky note with folded corner
            painter.drawRect(int(s * 0.08), int(s * 0.08), int(s * 0.84), int(s * 0.84))
            painter.setBrush(QColor(color).darker(130))
            fold = [
                QPoint(int(s * 0.65), int(s * 0.08)),
                QPoint(int(s * 0.92), int(s * 0.08)),
                QPoint(int(s * 0.92), int(s * 0.35)),
            ]
            painter.drawPolygon(fold)
            painter.setPen(QPen(QColor("#FFFFFF").darker(110), 1))
            for i in range(3):
                y = int(s * (0.35 + i * 0.18))
                painter.drawLine(int(s * 0.18), y, int(s * 0.82), y)

        else:
            # Fallback: simple circle
            painter.drawEllipse(int(s * 0.1), int(s * 0.1), int(s * 0.8), int(s * 0.8))

        _ = painter.end()
        return QIcon(pixmap)

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

    # ============= Sort order methods =============

    def _on_sort_button_clicked(self, button_id: int) -> None:
        """Handle sort button click.

        Args:
            button_id: ID of clicked button (0=name, 1=date)
        """
        order = "name" if button_id == 0 else "date"
        self.sort_order_changed.emit(order)
        self.logger.info(f"Sort order changed to: {order}")

    def set_sort_order(self, order: str) -> None:
        """Set the sort order and update button states.

        Called by MainWindow when restoring settings or syncing with model.

        Args:
            order: Sort order ("name" or "date")
        """
        if order not in ("name", "date"):
            return

        # Update button states without emitting signal
        assert self._sort_button_group is not None
        assert self._sort_name_btn is not None
        assert self._sort_date_btn is not None
        _ = self._sort_button_group.blockSignals(True)
        if order == "name":
            self._sort_name_btn.setChecked(True)
        else:
            self._sort_date_btn.setChecked(True)
        _ = self._sort_button_group.blockSignals(False)

    # ============= Pin methods =============

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
        if self._unified_model:
            self._unified_model.refresh_pin_order()
            # Force view update
            self.list_view.viewport().update()

    def set_pin_manager(self, pin_manager: PinManager) -> None:
        """Set the pin manager.

        Args:
            pin_manager: Pin manager for pinning shots
        """
        self._pin_manager = pin_manager
