"""Base class for grid views with common functionality.

This module provides the BaseGridView class that contains shared UI components
and behavior for ShotGridView, ThreeDEGridView, and PreviousShotsView.
"""

from __future__ import annotations

# Standard library imports
from functools import partial
from typing import TYPE_CHECKING, ClassVar, Protocol

# Third-party imports
from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QSlider,
    QVBoxLayout,
    QWidget,
)

# Local application imports
from config import Config
from logging_mixin import LoggingMixin
from typing_compat import override
from ui.grid_context_menu_mixin import GridContextMenuMixin
from ui.qt_widget_mixin import QtWidgetMixin
from ui.scrub_bridge import ScrubPreviewBridge


class HasAvailableShows(Protocol):
    """Protocol for objects that provide available shows list.

    This protocol enables duck typing for model objects that can provide
    a list of available show names without requiring isinstance checks.
    Used for test compatibility and flexible API design.
    """

    def get_available_shows(self) -> set[str]:
        """Return list of available show names.

        Returns:
            List of show name strings

        """
        ...


# Runtime imports (not just type checking)
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence


if TYPE_CHECKING:
    # Third-party imports
    # Local application imports
    from PySide6.QtGui import QResizeEvent, QWheelEvent

    from managers.notes_manager import NotesManager
    from managers.shot_pin_manager import ShotPinManager
    from ui.base_thumbnail_delegate import BaseThumbnailDelegate
    from ui.sort_button_bar import SortButtonBar


class BaseGridView(GridContextMenuMixin, QtWidgetMixin, LoggingMixin, QWidget):
    """Base class for grid views with common functionality.

    This base class provides:
    - Thumbnail size control (slider and label)
    - Show filter combo box
    - QListView configuration for grid display
    - Common properties and methods
    - Template methods for customization

    Subclasses must implement abstract methods to provide
    specific behavior for their data types.
    """

    # Common signals that all views share
    app_launch_requested: ClassVar[Signal] = Signal(str)  # app_name
    show_filter_requested: ClassVar[Signal] = Signal(
        str
    )  # show name or empty string for all
    text_filter_requested: ClassVar[Signal] = Signal(
        str
    )  # filter text for real-time search
    pin_shot_requested: ClassVar[Signal] = Signal(
        object
    )  # fallback when no pin_manager
    sort_order_changed: ClassVar[Signal] = Signal(str)  # "name" or "date"

    # Manager attribute declarations — subclasses initialize these.
    # Declared here so shared handler methods (_pin_shot, etc.) type-check correctly.
    _pin_manager: ShotPinManager | None
    _notes_manager: NotesManager | None

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the base grid view.

        Args:
            parent: Optional parent widget

        """
        super().__init__(parent)

        # Common properties
        self._thumbnail_size: int = Config.DEFAULT_THUMBNAIL_SIZE
        self._model: QAbstractItemModel | None = None

        # Scrub preview bridge
        self._scrub_bridge: ScrubPreviewBridge = ScrubPreviewBridge(self)

        # Sort bar — created by subclasses via SortButtonBar
        self._sort_bar: SortButtonBar | None = None

        # Create the UI
        self._setup_base_ui()

        # Set focus policy
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Setup visibility/update mechanism
        self._setup_visibility_tracking()

        self.logger.debug(f"{self.__class__.__name__} initialized")

    def _setup_base_ui(self) -> None:
        """Set up the base user interface components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Allow subclasses to add top widgets (like loading indicators)
        self._add_top_widgets(layout)

        # === COMPACT UNIFIED TOOLBAR ===
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(5, 5, 5, 5)
        toolbar_layout.setSpacing(8)

        # Size slider (compact, no label)
        self.size_slider: QSlider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setMinimum(Config.MIN_THUMBNAIL_SIZE)
        self.size_slider.setMaximum(Config.MAX_THUMBNAIL_SIZE)
        self.size_slider.setValue(self._thumbnail_size)
        self.size_slider.setFixedWidth(120)
        self.size_slider.setToolTip("Thumbnail size")
        _ = self.size_slider.valueChanged.connect(self._on_size_changed)
        toolbar_layout.addWidget(self.size_slider)

        # Compact size label (just "Npx")
        self.size_label: QLabel = QLabel(f"{self._thumbnail_size}px")
        self.size_label.setFixedWidth(45)
        self.size_label.setStyleSheet("color: #888;")
        toolbar_layout.addWidget(self.size_label)

        # Vertical separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("color: #444;")
        toolbar_layout.addWidget(separator)

        # Show filter (compact)
        self.show_combo: QComboBox = QComboBox()
        self.show_combo.addItem("All Shows")
        self.show_combo.setFixedWidth(120)
        self.show_combo.setToolTip("Filter by show")
        _ = self.show_combo.currentTextChanged.connect(self._on_show_filter_changed)
        toolbar_layout.addWidget(self.show_combo)

        # Text filter (compact with placeholder)
        self.text_filter_input: QLineEdit = QLineEdit()
        self.text_filter_input.setPlaceholderText("Filter...")
        self.text_filter_input.setClearButtonEnabled(True)
        self.text_filter_input.setFixedWidth(150)
        self.text_filter_input.setToolTip("Filter by name")
        _ = self.text_filter_input.textChanged.connect(self._on_text_filter_changed)
        toolbar_layout.addWidget(self.text_filter_input)

        # Allow subclasses to add additional toolbar widgets (buttons, count labels, etc.)
        # Subclasses should add stretch themselves if they need items pushed to the right
        self._add_toolbar_widgets(toolbar_layout)

        layout.addLayout(toolbar_layout)

        # Create QListView with grid mode
        self.list_view: QListView = QListView()
        self._configure_list_view()

        # Create and set delegate (subclasses must provide)
        self._delegate: BaseThumbnailDelegate = self._create_delegate()
        self.list_view.setItemDelegate(self._delegate)

        # Connect list view signals
        _ = self.list_view.clicked.connect(self._on_item_clicked)
        _ = self.list_view.doubleClicked.connect(self._on_item_double_clicked)

        layout.addWidget(self.list_view)

        # Set focus on list view too
        self.list_view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Setup scrub preview system
        self._setup_scrub_preview()

        # Setup QAction-based keyboard shortcuts for app launching
        self._setup_launch_shortcuts()

    def _configure_list_view(self) -> None:
        """Configure the QListView with common settings."""
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setLayoutMode(QListView.LayoutMode.Batched)
        self.list_view.setBatchSize(20)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setSpacing(Config.THUMBNAIL_SPACING)

        # Set selection behavior
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )

        # Enable smooth scrolling
        self.list_view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.list_view.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )

    def _setup_visibility_tracking(self) -> None:
        """Set up event-driven visibility tracking for lazy loading.

        Uses a debounced single-shot timer triggered by scroll and resize
        events instead of polling. Subclasses connect model signals via
        _connect_model_visibility() in their set_model() methods.
        """
        self._visibility_timer: QTimer = QTimer()
        self._visibility_timer.setSingleShot(True)
        _ = self._visibility_timer.timeout.connect(self._update_visible_range)

        # Scrollbar exists from _setup_base_ui() even before a model is set
        _ = self.list_view.verticalScrollBar().valueChanged.connect(
            self._schedule_visible_range_update
        )

    def _schedule_visible_range_update(self) -> None:
        """Schedule a debounced visible range update.

        Called on scroll/resize events. Stops any pending timer and
        restarts with 50ms delay for batching rapid events.
        """
        self._visibility_timer.stop()
        self._visibility_timer.start(50)

    def _connect_model_visibility(self, model: QAbstractItemModel) -> None:
        """Connect model signals for visibility tracking.

        Subclasses should call this from their set_model() methods
        after setting the model on list_view.

        Args:
            model: The item model being set

        """
        _ = model.modelReset.connect(self._schedule_visible_range_update)
        self._schedule_visible_range_update()

    def _setup_scrub_preview(self) -> None:
        """Initialize the scrub preview system via ScrubPreviewBridge.

        Delegates all wiring to the bridge so this class stays free of
        direct ScrubEventFilter / ScrubPreviewManager dependencies.
        """
        self._scrub_bridge.setup(
            self.list_view,
            self._delegate,
            self._on_scrub_repaint_requested,
            on_scrub_started=self._on_scrub_started,
            on_scrub_ended=self._on_scrub_ended,
        )
        self.logger.debug("Scrub preview system initialized")

    def _setup_launch_shortcuts(self) -> None:
        """Set up QAction-based keyboard shortcuts for app launching.

        Actions are scoped to list_view so they fire when list_view or its
        viewport has focus, but NOT when the search field or combo has focus.
        """
        key_map = {
            Qt.Key.Key_3: "3de",
            Qt.Key.Key_N: "nuke",
            Qt.Key.Key_M: "maya",
            Qt.Key.Key_R: "rv",
            Qt.Key.Key_P: "publish",
        }
        for key, app_name in key_map.items():
            action = QAction(self.list_view)
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            _ = action.triggered.connect(partial(self._on_shortcut_launch, app_name))
            self.list_view.addAction(action)

    def _on_shortcut_launch(self, app_name: str) -> None:
        """Handle shortcut-triggered app launch.

        Args:
            app_name: Name of the app to launch

        """
        self.app_launch_requested.emit(app_name)

    def _on_scrub_repaint_requested(self, index: QModelIndex) -> None:
        """Handle request to repaint an item during scrub.

        Args:
            index: Model index to repaint

        """
        if index.isValid():
            # Request repaint of this specific item
            self.list_view.update(index)

    def _on_scrub_started(self, index: QModelIndex) -> None:
        """Handle scrub preview started.

        Args:
            index: Model index where scrub started

        """
        self.logger.debug(f"Scrub started on row {index.row()}")

    def _on_scrub_ended(self, index: QModelIndex) -> None:
        """Handle scrub preview ended.

        Args:
            index: Model index where scrub ended

        """
        self.logger.debug(f"Scrub ended on row {index.row()}")
        # Ensure item is repainted to show normal thumbnail
        if index.isValid():
            self.list_view.update(index)

    # Template methods for subclasses to override

    def _add_top_widgets(self, layout: QVBoxLayout) -> None:
        """Add widgets at the top of the layout.

        Override in subclasses to add headers, loading bars, etc.

        Args:
            layout: The main vertical layout

        """

    def _add_toolbar_widgets(self, layout: QHBoxLayout) -> None:
        """Add additional widgets to the toolbar.

        Override in subclasses to add buttons, labels, etc.

        Args:
            layout: The toolbar horizontal layout

        """

    def _create_delegate(self) -> BaseThumbnailDelegate:
        """Create the appropriate delegate for this view.

        Must be implemented by subclasses.

        Returns:
            The delegate instance

        """
        raise NotImplementedError

    def _on_item_clicked(self, _index: QModelIndex) -> None:
        """Handle item click.

        Must be implemented by subclasses to handle specific data types.

        Args:
            index: The clicked model index

        """
        raise NotImplementedError

    def _on_item_double_clicked(self, _index: QModelIndex) -> None:
        """Handle item double-click.

        Must be implemented by subclasses to handle specific data types.

        Args:
            index: The double-clicked model index

        """
        raise NotImplementedError

    # Common slot implementations

    def _on_size_changed(self, size: int) -> None:
        """Handle thumbnail size change.

        Args:
            size: New thumbnail size

        """
        self._thumbnail_size = size
        self.size_label.setText(f"{size}px")

        # Update delegate size
        if hasattr(self._delegate, "set_thumbnail_size"):
            self._delegate.set_thumbnail_size(size)

        # Update grid size
        self._update_grid_size()

        # Force view update
        self.list_view.viewport().update()

        self.logger.debug(f"Thumbnail size changed to {size}px")

    def _on_show_filter_changed(self, show_text: str) -> None:
        """Handle show filter change.

        Args:
            show_text: Selected show name or "All Shows"

        """
        # Convert "All Shows" to empty string for the signal
        show_filter = "" if show_text == "All Shows" else show_text
        self.show_filter_requested.emit(show_filter)
        self.logger.info(f"Show filter requested: {show_text}")

    def _on_text_filter_changed(self, text: str) -> None:
        """Handle text filter change for real-time search.

        Args:
            text: Filter text from QLineEdit

        """
        self.text_filter_requested.emit(text)
        self.logger.debug(f"Text filter changed: '{text}'")

    def _update_grid_size(self) -> None:
        """Update the grid size based on thumbnail size."""
        # Calculate item size including padding and text height
        padding = 8
        text_height = 50
        item_width = self._thumbnail_size + 2 * padding
        # Calculate height based on 16:9 aspect ratio for plate images
        thumbnail_height = int(self._thumbnail_size / Config.THUMBNAIL_ASPECT_RATIO)
        item_height = thumbnail_height + text_height + 2 * padding

        # Set grid size on the view
        self.list_view.setGridSize(QSize(item_width, item_height))

        # Ensure uniform item sizes
        self.list_view.setUniformItemSizes(True)

    def _update_visible_range(self) -> None:
        """Update the visible item range for lazy loading.

        This base implementation can be overridden by subclasses.
        """
        if not self._model:
            return

        viewport = self.list_view.viewport()
        visible_rect = viewport.rect()

        first_index = self.list_view.indexAt(visible_rect.topLeft())
        last_index = self.list_view.indexAt(visible_rect.bottomRight())

        # self._model is already verified non-None above; use it for fallback index building
        if not first_index.isValid():
            first_index = self._model.index(0, 0)

        if not last_index.isValid():
            last_index = self._model.index(self._model.rowCount() - 1, 0)

        if first_index.isValid() and last_index.isValid():
            # Map through proxy if the list view has a proxy model installed
            from PySide6.QtCore import QSortFilterProxyModel

            proxy = self.list_view.model()
            if isinstance(proxy, QSortFilterProxyModel):
                source_rows: list[int] = []
                for row in range(first_index.row(), last_index.row() + 1):
                    proxy_idx = proxy.index(row, 0)
                    source_idx = proxy.mapToSource(proxy_idx)
                    if source_idx.isValid():
                        source_rows.append(source_idx.row())
                if source_rows:
                    self._handle_visible_range_update(
                        min(source_rows), max(source_rows) + 1
                    )
            else:
                self._handle_visible_range_update(
                    first_index.row(), last_index.row() + 1
                )

    def _handle_visible_range_update(self, start: int, end: int) -> None:
        """Handle the visible range update.

        Override in subclasses to update their specific models.

        Args:
            start: Start row index
            end: End row index (exclusive)

        """
        # Default implementation - subclasses should override
        # to call their model's set_visible_range or similar

    def set_sort_order(self, order: str) -> None:
        """Set the sort order and update button states.

        Called by MainWindow when restoring settings or syncing with model.

        Args:
            order: Sort order ("name" or "date")

        """
        if self._sort_bar is not None:
            self._sort_bar.set_order(order)

    # Common properties

    @property
    def thumbnail_size(self) -> int:
        """Get the current thumbnail size.

        Returns:
            Current thumbnail size in pixels

        """
        return self._thumbnail_size

    def populate_show_filter(self, shows: list[str] | HasAvailableShows) -> None:
        """Populate the show filter combo box.

        Accepts either a list of show names or an object implementing
        HasAvailableShows protocol. When passed a protocol object,
        subclasses should extract shows and call super().

        Args:
            shows: Either list of show names or object with get_available_shows() method

        """
        # Handle case where subclass passes a protocol object
        if not isinstance(shows, list):
            return  # Subclass will extract shows and call super()

        # Type narrowing: shows is list[str] after isinstance check
        try:
            # Block signals to prevent triggering filter change
            _ = self.show_combo.blockSignals(True)

            # Clear existing items except "All Shows"
            while self.show_combo.count() > 1:
                self.show_combo.removeItem(1)

            # Add shows to combo box
            for show in sorted(shows):
                self.show_combo.addItem(show)

            show_count = len(shows)
            show_word = "show" if show_count == 1 else "shows"
            self.logger.debug(f"Populated show filter with {show_count} {show_word}")
        finally:
            # Re-enable signals
            _ = self.show_combo.blockSignals(False)

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle wheel event for thumbnail size adjustment with Ctrl.

        This is a common implementation that subclasses can inherit or override.

        Args:
            event: Wheel event

        """
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                new_size = min(self._thumbnail_size + 10, Config.MAX_THUMBNAIL_SIZE)
            else:
                new_size = max(self._thumbnail_size - 10, Config.MIN_THUMBNAIL_SIZE)

            self.size_slider.setValue(new_size)
            event.accept()
        else:
            super().wheelEvent(event)

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Handle resize to update visible thumbnails.

        Args:
            event: Resize event

        """
        super().resizeEvent(event)
        self._schedule_visible_range_update()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Forward unhandled key events to list_view for navigation.

        App launch shortcuts are handled by QActions on list_view.

        Args:
            event: Key event

        """
        # Let QListView handle navigation (arrow keys, etc.)
        self.list_view.keyPressEvent(event)
