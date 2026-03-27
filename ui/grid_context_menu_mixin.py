"""Mixin providing shared context menu helpers for grid views.

This module contains methods and styling shared by all three grid view
subclasses (ShotGridView, ThreeDEGridView, PreviousShotsView) so they
can be maintained in one place without duplicating code across views.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QApplication, QMenu

from ui.icon_painter import create_icon


if TYPE_CHECKING:
    from PySide6.QtGui import QIcon

    from managers.notes_manager import NotesManager



class GridContextMenuMixin:
    """Mixin that provides shared context menu helpers for BaseGridView subclasses.

    This mixin assumes the host class also inherits from LoggingMixin so that
    ``self.logger`` is available.  It is designed to be mixed in before QWidget
    in the MRO, e.g.::

        class BaseGridView(GridContextMenuMixin, QtWidgetMixin, LoggingMixin, QWidget):
            ...

    """

    # Shared context menu CSS — identical across all three grid views
    CONTEXT_MENU_STYLE: str = """
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

    def _create_icon(self, icon_type: str, color: str, size: int = 33) -> QIcon:
        """Create a coloured shaped icon for menu items.

        Args:
            icon_type: Icon type - "pin", "folder", "film", "plate", "rocket",
                      "target", "palette", "cube", "play", "clipboard", "note"
            color: Hex colour string (e.g., "#FF6B6B")
            size: Icon size in pixels

        Returns:
            QIcon with the specified shape and colour

        """
        return create_icon(icon_type, color, size)

    def _build_launch_submenu(
        self,
        menu: QMenu,
        launch_apps: list[tuple[str, str, str, str, str]],
        callback: Callable[[str], None],
    ) -> None:
        """Build the "Launch Application" submenu with icons.

        Each entry in ``launch_apps`` is a 5-tuple:
        ``(display_label, shortcut_key, app_id, icon_type, color)``

        The ``callback`` receives the ``app_id`` string.  Callers that need to
        pass additional context (e.g. ThreeDEGridView passes the scene object)
        should wrap their signal in a lambda before calling this method::

            self._build_launch_submenu(
                menu, apps,
                lambda app_id: self.app_launch_requested.emit(app_id, scene),
            )

        Args:
            menu: The parent QMenu to attach the submenu to.
            launch_apps: Ordered list of app descriptors.
            callback: Called with ``app_id`` when an action is triggered.

        """
        launch_menu = menu.addMenu("Launch Application")
        launch_menu.setStyleSheet(self.CONTEXT_MENU_STYLE)
        launch_menu.setIcon(self._create_icon("rocket", "#95D5B2"))
        for label, shortcut, app_id, icon_type, color in launch_apps:
            action = launch_menu.addAction(f"{label}  ({shortcut})")
            action.setIcon(self._create_icon(icon_type, color))
            _ = action.triggered.connect(
                lambda checked=False, a=app_id: callback(a)  # noqa: ARG005
            )

    def _build_standard_actions(
        self,
        menu: QMenu,
        actions_config: list[tuple[str, str, str, Callable[[], None]]],
    ) -> None:
        """Add a flat list of actions to *menu* from a declarative config.

        Each entry in ``actions_config`` is a 4-tuple:
        ``(label, icon_type, color, callback)``

        Args:
            menu: The QMenu to append actions to.
            actions_config: Ordered list of action descriptors.

        """
        for label, icon_type, color, cb in actions_config:
            action = menu.addAction(label)
            action.setIcon(self._create_icon(icon_type, color))
            _ = action.triggered.connect(lambda checked=False, f=cb: f())  # noqa: ARG005  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]

    def _copy_path_to_clipboard(self, path: str) -> None:
        """Copy a path to the system clipboard.

        Args:
            path: The path string to copy

        """
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(path)
            self.logger.debug(f"Copied path to clipboard: {path}")  # type: ignore[attr-defined]

    def _open_main_plate_in_rv(self, item: object) -> None:
        """Open the main plate in RV.

        Works with any object that has a ``workspace_path`` attribute,
        including Shot and ThreeDEScene.

        Args:
            item: Object with a workspace_path attribute

        """
        from launch.rv_launcher import open_plate_in_rv

        open_plate_in_rv(item.workspace_path)  # type: ignore[union-attr]

    def _open_folder(self, path: str) -> None:
        """Open a folder in the system file manager (non-blocking).

        Validates that the path exists before launching the worker.

        Args:
            path: Absolute path to the folder to open

        """
        from PySide6.QtCore import Qt, QThreadPool

        from workers.runnable_tracker import FolderOpenerWorker

        if not path:
            self.logger.error("No folder path provided")  # type: ignore[attr-defined]
            return
        if not Path(path).exists():
            self.logger.error(f"Folder path does not exist: {path}")  # type: ignore[attr-defined]
            return
        worker = FolderOpenerWorker(path)
        _ = worker.signals.error.connect(
            self._on_folder_open_error,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        _ = worker.signals.success.connect(
            self._on_folder_open_success,  # pyright: ignore[reportAny]
            Qt.ConnectionType.QueuedConnection,
        )
        QThreadPool.globalInstance().start(worker)
        self.logger.info(f"Opening folder: {path}")  # type: ignore[attr-defined]

    def _on_folder_open_error(self, error_msg: str) -> None:
        """Handle folder open error.

        Args:
            error_msg: Error message from the worker

        """
        self.logger.error(f"Failed to open folder: {error_msg}")  # type: ignore[attr-defined]

    def _on_folder_open_success(self) -> None:
        """Handle successful folder opening."""
        self.logger.debug("Folder opened successfully")  # type: ignore[attr-defined]

    def _edit_note(self, workspace_path: str, display_name: str) -> None:
        """Open a dialog to edit a note for a shot or scene.

        Pre-populates the dialog with the existing note.  On confirmation,
        saves via the path-based notes API and invalidates the view.

        Args:
            workspace_path: Workspace path used as the notes key
            display_name: Human-readable name shown in the dialog title

        """
        from PySide6.QtWidgets import QInputDialog

        notes_manager: NotesManager | None = getattr(self, "_notes_manager", None)
        if not notes_manager:
            return

        current_note = notes_manager.get_note_by_path(workspace_path)
        new_note, ok = QInputDialog.getMultiLineText(
            self,  # type: ignore[arg-type]
            f"Note for {display_name}",
            "Note:",
            current_note,
        )
        if ok:
            notes_manager.set_note_by_path(workspace_path, new_note)
            self.logger.debug(f"Note updated for: {display_name}")  # type: ignore[attr-defined]

    def _build_shot_standard_actions(
        self,
        menu: QMenu,
        workspace_path: str,
        display_name: str,
        has_note: bool,
        item_for_rv: Any | None = None,
    ) -> None:
        """Build the 4 standard context menu actions shared across shot/3DE grids.

        Adds the following actions to *menu*:

        1. **Open Shot Folder** — opens *workspace_path* in the file manager
        2. **Open Main Plate in RV** — launches RV for *item_for_rv* (skipped when ``None``)
        3. **Copy Shot Path** — copies *workspace_path* to the clipboard
        4. **Edit Note** / **Add Note** — opens the note editor for this item

        Args:
            menu: The QMenu to append actions to.
            workspace_path: Workspace path for folder-open and clipboard actions.
            display_name: Human-readable name used in the note dialog title.
            has_note: When ``True`` the note action is labelled "Edit Note";
                      otherwise "Add Note".
            item_for_rv: Object with a ``workspace_path`` attribute passed to
                         :meth:`_open_main_plate_in_rv`.  When ``None`` the RV
                         action is omitted.

        """
        note_label = "Edit Note" if has_note else "Add Note"
        actions: list[tuple[str, str, str, Callable[[], None]]] = [
            (
                "Open Shot Folder",
                "folder",
                "#FFB347",
                lambda p=workspace_path: self._open_folder(p),  # type: ignore[misc]
            ),
        ]
        if item_for_rv is not None:
            actions.append(
                (
                    "Open Main Plate in RV",
                    "play",
                    "#FF4757",
                    lambda item=item_for_rv: self._open_main_plate_in_rv(item),  # type: ignore[misc]
                )
            )
        actions += [
            (
                "Copy Shot Path",
                "clipboard",
                "#95A5A6",
                lambda p=workspace_path: self._copy_path_to_clipboard(p),  # type: ignore[misc]
            ),
            (
                note_label,
                "note",
                "#F1C40F",
                lambda p=workspace_path, n=display_name: self._edit_note(p, n),  # type: ignore[misc]
            ),
        ]
        self._build_standard_actions(menu, actions)
