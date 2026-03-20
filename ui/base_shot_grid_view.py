"""Intermediate base class for shot-based grid views.

Sits between BaseGridView and the two shot views (ShotGridView, PreviousShotsView),
holding all logic that is duplicated between them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtWidgets import QInputDialog, QMenu, QWidget

from typing_compat import override
from ui.base_grid_view import BaseGridView
from ui.base_item_model import BaseItemRole
from workers.runnable_tracker import FolderOpenerWorker


if TYPE_CHECKING:
    from PySide6.QtGui import QContextMenuEvent

    from managers.shot_pin_manager import ShotPinManager
    from type_definitions import Shot


class HasRefreshPinOrder(Protocol):
    """Protocol for item models that support pin-order refresh.

    Both ShotItemModel and PreviousShotsItemModel implement this method.
    Used by _refresh_with_pins() in BaseShotGridView to avoid importing
    concrete model types into the base class.
    """

    def refresh_pin_order(self) -> None:
        """Re-sort the model to reflect current pin state."""


class BaseShotGridView(BaseGridView):
    """Shared base for ShotGridView and PreviousShotsView.

    Provides:
    - Shared signals: shot_selected, shot_double_clicked
    - Common selection/click handlers
    - Visible-range update wired to model
    - Folder-open worker logic (with path validation)
    - pin_manager setter
    - Unified set_model flow via _set_model_common()
    - Context-menu implementation driven by hook methods
    """

    shot_selected: ClassVar[Signal] = Signal(object)  # Shot object
    shot_double_clicked: ClassVar[Signal] = Signal(object)  # Shot object

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected_shot: Shot | None = None

    # ------------------------------------------------------------------
    # Hook methods — override in subclasses as needed
    # ------------------------------------------------------------------

    def on_selected_shot_changed(self, shot: Shot | None) -> None:
        """Hook called when selection changes. Default no-op."""

    def _add_shot_specific_menu_actions(self, menu: QMenu, shot: Shot) -> None:
        """Hook to add view-specific context menu actions. Default no-op."""

    def _get_launch_apps(self) -> list[tuple[str, str, str, str, str]]:
        """Return launch app descriptors for the context menu.

        Each tuple: (display_label, shortcut_key, app_id, icon_type, color).
        Override to add or change entries (e.g. add Publish in ShotGridView).
        """
        return [
            ("3DEqualizer", "3", "3de", "target", "#00CED1"),
            ("Nuke", "N", "nuke", "palette", "#FF8C00"),
            ("Maya", "M", "maya", "cube", "#9B59B6"),
            ("RV", "R", "rv", "play", "#2ECC71"),
        ]

    def _connect_model_extras(self, model: QAbstractItemModel) -> None:
        """Hook for subclass-specific model signal connections. Default no-op."""

    def _get_shot_model(self) -> QAbstractItemModel | None:
        """Return the model for shot operations.

        Subclasses that store a more-specific model reference (e.g.
        _unified_model) should override this to return that reference so
        guard checks in the shared handlers work correctly.
        """
        return self._model

    # ------------------------------------------------------------------
    # Shared slot implementations
    # ------------------------------------------------------------------

    @Slot(QModelIndex)  # pyright: ignore[reportAny]
    def _on_item_clicked(self, index: QModelIndex) -> None:
        """Handle item click (no-op stub; Qt selection model handles it)."""
        _ = index

    @Slot(QModelIndex)  # pyright: ignore[reportAny]
    def _on_item_double_clicked(self, index: QModelIndex) -> None:
        """Handle item double-click — emit shot_double_clicked."""
        if not index.isValid() or not self._get_shot_model():
            return
        shot = cast("Shot | None", index.data(BaseItemRole.ObjectRole))
        if shot:
            self.shot_double_clicked.emit(shot)
            self.logger.debug(f"Shot double-clicked: {shot.full_name}")

    @Slot(QModelIndex, QModelIndex)  # pyright: ignore[reportAny]
    def _on_selection_changed(
        self, current: QModelIndex, _previous: QModelIndex
    ) -> None:
        """Handle selection change — emit shot_selected and call hook."""
        if not self._get_shot_model():
            return
        if current.isValid():
            shot = cast("Shot | None", current.data(BaseItemRole.ObjectRole))
            if shot:
                self._selected_shot = shot
                self.shot_selected.emit(shot)
                self.on_selected_shot_changed(shot)
                return
        self.on_selected_shot_changed(None)

    @override
    def _handle_visible_range_update(self, start: int, end: int) -> None:
        """Forward visible-range updates to the shot model."""
        model = self._get_shot_model()
        if model:
            model.set_visible_range(start, end)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Folder open helpers
    # ------------------------------------------------------------------

    def _open_shot_folder(self, shot: Shot) -> None:
        """Open the shot's workspace folder in system file manager (non-blocking)."""
        folder_path = shot.workspace_path
        if not folder_path:
            self.logger.error(f"No workspace path for shot: {shot.full_name}")
            return
        if not Path(folder_path).exists():
            self.logger.error(f"Workspace path does not exist: {folder_path}")
            return
        worker = FolderOpenerWorker(folder_path)
        _ = worker.signals.error.connect(
            self._on_folder_open_error,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.signals.success.connect(
            self._on_folder_open_success,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        QThreadPool.globalInstance().start(worker)
        self.logger.info(f"Opening folder: {folder_path}")

    @Slot(str)  # pyright: ignore[reportAny]
    def _on_folder_open_error(self, error_msg: str) -> None:
        """Handle folder open error."""
        self.logger.error(f"Failed to open folder: {error_msg}")

    @Slot()  # pyright: ignore[reportAny]
    def _on_folder_open_success(self) -> None:
        """Handle successful folder opening."""
        self.logger.debug("Folder opened successfully")

    # ------------------------------------------------------------------
    # Pin manager
    # ------------------------------------------------------------------

    def set_pin_manager(self, pin_manager: ShotPinManager) -> None:
        """Set the pin manager."""
        self._pin_manager = pin_manager  # pyright: ignore[reportUnannotatedClassAttribute]

    # ------------------------------------------------------------------
    # Shared set_model core flow
    # ------------------------------------------------------------------

    def _set_model_common(
        self,
        model: QAbstractItemModel,
        proxy: QSortFilterProxyModel | None = None,
    ) -> None:
        """Wire up model, list_view, and shared signals.

        Subclasses call this from their own set_model(), then do any
        extra bookkeeping (storing a typed reference, calling
        _update_status(), etc.).
        """
        self._model = model  # pyright: ignore[reportUnannotatedClassAttribute]
        self.list_view.setModel(proxy if proxy is not None else model)
        self._connect_model_visibility(model)
        selection_model = self.list_view.selectionModel()
        if selection_model:
            _ = selection_model.currentChanged.connect(
                self._on_selection_changed  # pyright: ignore[reportAny]
            )
        _ = model.shots_updated.connect(self._on_model_updated)  # type: ignore[union-attr]
        self._connect_model_extras(model)
        self.logger.debug(f"Model set with {model.rowCount()} items")

    # ------------------------------------------------------------------
    # Context menu (shared structure)
    # ------------------------------------------------------------------

    @override
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Handle right-click context menu."""
        list_view_pos = self.list_view.mapFromGlobal(event.globalPos())
        index = self.list_view.indexAt(list_view_pos)

        if not index.isValid() or not self._get_shot_model():
            return

        shot = cast("Shot | None", index.data(BaseItemRole.ObjectRole))
        if not shot:
            return

        menu = QMenu(self)
        menu.setStyleSheet(self.CONTEXT_MENU_STYLE)

        # Pin / Unpin
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

        # View-specific actions (e.g. hide/unhide in ShotGridView)
        self._add_shot_specific_menu_actions(menu, shot)

        _ = menu.addSeparator()

        self._build_launch_submenu(
            menu,
            self._get_launch_apps(),
            lambda app_id: self.app_launch_requested.emit(app_id),
        )

        _ = menu.addSeparator()

        has_note = (
            self._notes_manager.has_note(shot) if self._notes_manager else False
        )
        note_label = "Edit Note" if has_note else "Add Note"
        self._build_standard_actions(
            menu,
            [
                (
                    "Open Shot Folder",
                    "folder",
                    "#FFB347",
                    lambda: self._open_shot_folder(shot),
                ),
                (
                    "Open Main Plate in RV",
                    "play",
                    "#FF4757",
                    lambda: self._open_main_plate_in_rv(shot),
                ),
                (
                    "Copy Shot Path",
                    "clipboard",
                    "#95A5A6",
                    lambda: self._copy_path_to_clipboard(shot.workspace_path),
                ),
                (
                    note_label,
                    "note",
                    "#F1C40F",
                    lambda s=shot: self._edit_shot_note(s),  # type: ignore[misc]
                ),
            ],
        )

        _ = menu.exec(event.globalPos())
        self.logger.debug(f"Context menu shown for shot: {shot.full_name}")

    # Subclasses must still implement _on_model_updated and _create_delegate.

    # ------------------------------------------------------------------
    # Shot pin / note operations (SGV and PSV only)
    # ThreeDEGridView uses _pin_scene/_unpin_scene/_edit_scene_note instead.
    # ------------------------------------------------------------------

    @property
    def _item_model(self) -> HasRefreshPinOrder | None:
        """Return the underlying item model for pin-order refresh.

        Subclasses that support pin operations must override this property
        to return their specific model instance.

        Returns:
            Model implementing refresh_pin_order(), or None

        """
        msg = (
            f"{self.__class__.__name__} must override _item_model "
            "to support _refresh_with_pins()"
        )
        raise NotImplementedError(msg)

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
        proxy = self.list_view.model()
        if isinstance(proxy, QSortFilterProxyModel):
            proxy.invalidate()
        else:
            item_model = self._item_model
            if item_model:
                item_model.refresh_pin_order()
        self.list_view.viewport().update()

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
