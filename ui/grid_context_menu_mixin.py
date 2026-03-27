"""Mixin providing shared context menu helpers for grid views.

This module contains methods and styling shared by all three grid view
subclasses (ShotGridView, ThreeDEGridView, PreviousShotsView) so they
can be maintained in one place without duplicating code across views.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QMenu

from ui.icon_painter import create_icon


if TYPE_CHECKING:
    from PySide6.QtGui import QIcon


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
