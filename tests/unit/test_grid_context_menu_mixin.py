"""Unit tests for grid_context_menu_mixin.py - GridContextMenuMixin class.

Tests the shared context menu helpers provided by GridContextMenuMixin:
- Icon creation with custom sizes and colors
- Clipboard operations
- Menu building (launch submenu and standard actions)
- Context menu styling

Following project conventions:
- Use pytest style with qtbot fixture from pytest-qt
- Mark all tests with @pytest.mark.qt
- Use real Qt components with minimal mocking
- Test both the return values and side effects
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu

from tests.test_helpers import process_qt_events
from ui.grid_context_menu_mixin import GridContextMenuMixin


pytestmark = [pytest.mark.unit, pytest.mark.qt]


# ============================================================================
# Test Doubles
# ============================================================================


class _MixinConsumer(GridContextMenuMixin):
    """Minimal test consumer that inherits from GridContextMenuMixin.

    Provides the required self.logger attribute that the mixin expects.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger("test")


# ============================================================================
# Tests
# ============================================================================


class TestContextMenuStyling:
    """Tests for the CONTEXT_MENU_STYLE constant."""

    def test_context_menu_style_is_string(self) -> None:
        """CONTEXT_MENU_STYLE is a non-empty string containing QMenu."""
        assert isinstance(GridContextMenuMixin.CONTEXT_MENU_STYLE, str)
        assert len(GridContextMenuMixin.CONTEXT_MENU_STYLE) > 0
        assert "QMenu" in GridContextMenuMixin.CONTEXT_MENU_STYLE

    def test_context_menu_style_contains_expected_selectors(self) -> None:
        """CONTEXT_MENU_STYLE includes common CSS selectors."""
        style = GridContextMenuMixin.CONTEXT_MENU_STYLE
        # These are the key CSS selectors for styling
        assert "QMenu::item" in style
        assert "QMenu::item:selected" in style
        assert "QMenu::separator" in style


class TestCreateIcon:
    """Tests for _create_icon method."""

    def test_create_icon_returns_qicon(self) -> None:
        """_create_icon returns a QIcon object."""
        consumer = _MixinConsumer()
        icon = consumer._create_icon("pin", "#FF0000")
        assert isinstance(icon, QIcon)
        assert not icon.isNull()

    def test_create_icon_with_custom_size(self) -> None:
        """_create_icon accepts custom size parameter."""
        consumer = _MixinConsumer()
        icon = consumer._create_icon("folder", "#00FF00", size=64)
        assert isinstance(icon, QIcon)
        assert not icon.isNull()

    def test_create_icon_with_different_types(self) -> None:
        """_create_icon works with various icon types."""
        consumer = _MixinConsumer()
        icon_types = ["pin", "folder", "film", "plate", "rocket", "target", "palette"]

        for icon_type in icon_types:
            icon = consumer._create_icon(icon_type, "#FF6B6B")
            assert isinstance(icon, QIcon), f"Failed for icon_type: {icon_type}"
            assert not icon.isNull(), f"Icon is null for type: {icon_type}"

    def test_create_icon_with_different_colors(self) -> None:
        """_create_icon works with different hex colors."""
        consumer = _MixinConsumer()
        colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFFFF", "#000000"]

        for color in colors:
            icon = consumer._create_icon("pin", color)
            assert isinstance(icon, QIcon)
            assert not icon.isNull()

    def test_create_icon_default_size(self) -> None:
        """_create_icon uses default size of 33 when not specified."""
        consumer = _MixinConsumer()
        icon1 = consumer._create_icon("pin", "#FF0000")
        icon2 = consumer._create_icon("pin", "#FF0000", size=33)
        # Both should produce valid icons; we can't directly compare sizes,
        # but both should be valid
        assert isinstance(icon1, QIcon)
        assert isinstance(icon2, QIcon)


class TestCopyPathToClipboard:
    """Tests for _copy_path_to_clipboard method."""

    def test_copy_path_to_clipboard(self, qapp: QApplication) -> None:
        """_copy_path_to_clipboard copies path to system clipboard."""
        consumer = _MixinConsumer()
        test_path = "/some/test/path"

        consumer._copy_path_to_clipboard(test_path)
        process_qt_events()

        clipboard = QApplication.clipboard()
        assert clipboard is not None
        assert clipboard.text() == test_path

    def test_copy_path_to_clipboard_multiple_times(self, qapp: QApplication) -> None:
        """_copy_path_to_clipboard updates clipboard on multiple calls."""
        consumer = _MixinConsumer()

        consumer._copy_path_to_clipboard("/path/one")
        process_qt_events()
        clipboard = QApplication.clipboard()
        assert clipboard.text() == "/path/one"

        consumer._copy_path_to_clipboard("/path/two")
        process_qt_events()
        assert clipboard.text() == "/path/two"

    def test_copy_path_to_clipboard_logs_debug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_copy_path_to_clipboard logs debug message."""
        import ui.grid_context_menu_mixin as gcm

        mock_debug = MagicMock()
        monkeypatch.setattr(gcm.logger, "debug", mock_debug)

        consumer = _MixinConsumer()
        consumer._copy_path_to_clipboard("/test/path")

        mock_debug.assert_called_once()
        call_args = mock_debug.call_args[0][0]
        assert "Copied path to clipboard" in call_args
        assert "/test/path" in call_args


class TestBuildLaunchSubmenu:
    """Tests for _build_launch_submenu method."""

    def test_build_launch_submenu_creates_actions(self) -> None:
        """_build_launch_submenu adds actions to menu."""
        consumer = _MixinConsumer()
        menu = QMenu()
        callback = MagicMock()

        launch_apps = [
            ("Maya", "M", "maya", "rocket", "#FF6B6B"),
            ("Nuke", "N", "nuke", "rocket", "#4ECDC4"),
        ]

        consumer._build_launch_submenu(menu, launch_apps, callback)
        process_qt_events()

        # Menu should have a submenu
        assert len(menu.actions()) > 0
        # Get the submenu action
        submenu_action = menu.actions()[0]
        submenu = submenu_action.menu()
        assert submenu is not None

        # Submenu should have the correct number of actions (one per app)
        assert len(submenu.actions()) == len(launch_apps)

    def test_build_launch_submenu_action_labels(self) -> None:
        """_build_launch_submenu creates actions with correct labels."""
        consumer = _MixinConsumer()
        menu = QMenu()
        callback = MagicMock()

        launch_apps = [
            ("Maya", "M", "maya", "rocket", "#FF6B6B"),
            ("Nuke", "N", "nuke", "rocket", "#4ECDC4"),
        ]

        consumer._build_launch_submenu(menu, launch_apps, callback)
        process_qt_events()

        # Get actions before accessing submenu
        menu_actions = menu.actions()
        assert len(menu_actions) > 0
        submenu = menu_actions[0].menu()
        assert submenu is not None

        # Get submenu actions and verify count
        submenu_actions = submenu.actions()
        assert len(submenu_actions) == 2

        # Check action labels include the shortcut
        assert "Maya" in submenu_actions[0].text()
        assert "(M)" in submenu_actions[0].text()
        assert "Nuke" in submenu_actions[1].text()
        assert "(N)" in submenu_actions[1].text()

    def test_build_launch_submenu_action_icons(self) -> None:
        """_build_launch_submenu adds icons to actions."""
        consumer = _MixinConsumer()
        menu = QMenu()
        callback = MagicMock()

        launch_apps = [
            ("Maya", "M", "maya", "rocket", "#FF6B6B"),
        ]

        consumer._build_launch_submenu(menu, launch_apps, callback)
        process_qt_events()

        menu_actions = menu.actions()
        submenu = menu_actions[0].menu()
        assert submenu is not None
        submenu_actions = submenu.actions()
        assert len(submenu_actions) > 0
        action = submenu_actions[0]
        assert not action.icon().isNull()

    def test_build_launch_submenu_callbacks_triggered(self) -> None:
        """_build_launch_submenu callbacks are called with correct app_id."""
        consumer = _MixinConsumer()
        menu = QMenu()
        callback = MagicMock()

        launch_apps = [
            ("Maya", "M", "maya", "rocket", "#FF6B6B"),
            ("Nuke", "N", "nuke", "rocket", "#4ECDC4"),
        ]

        consumer._build_launch_submenu(menu, launch_apps, callback)
        process_qt_events()

        menu_actions = menu.actions()
        assert len(menu_actions) > 0
        submenu = menu_actions[0].menu()
        assert submenu is not None

        # Get submenu actions and trigger the first action (Maya)
        submenu_actions = submenu.actions()
        assert len(submenu_actions) > 0
        action = submenu_actions[0]
        action.trigger()
        process_qt_events()

        # Callback should be called with app_id "maya"
        callback.assert_called()
        assert callback.call_args[0][0] == "maya"

    def test_build_launch_submenu_has_icon(self) -> None:
        """_build_launch_submenu adds icon to the submenu itself."""
        consumer = _MixinConsumer()
        menu = QMenu()
        callback = MagicMock()

        launch_apps = [
            ("Maya", "M", "maya", "rocket", "#FF6B6B"),
        ]

        consumer._build_launch_submenu(menu, launch_apps, callback)
        process_qt_events()

        menu_actions = menu.actions()
        submenu = menu_actions[0].menu()
        assert submenu is not None
        assert not submenu.icon().isNull()

    def test_build_launch_submenu_has_style(self) -> None:
        """_build_launch_submenu sets stylesheet on submenu."""
        consumer = _MixinConsumer()
        menu = QMenu()
        callback = MagicMock()

        launch_apps = [
            ("Maya", "M", "maya", "rocket", "#FF6B6B"),
        ]

        consumer._build_launch_submenu(menu, launch_apps, callback)
        process_qt_events()

        menu_actions = menu.actions()
        submenu = menu_actions[0].menu()
        assert submenu is not None
        # The stylesheet should be set to CONTEXT_MENU_STYLE
        assert "QMenu" in submenu.styleSheet()

    def test_build_launch_submenu_empty_list(self) -> None:
        """_build_launch_submenu handles empty app list gracefully."""
        consumer = _MixinConsumer()
        menu = QMenu()
        callback = MagicMock()

        consumer._build_launch_submenu(menu, [], callback)
        process_qt_events()

        # Submenu should still be added (even if empty)
        menu_actions = menu.actions()
        assert len(menu_actions) > 0
        submenu = menu_actions[0].menu()
        assert submenu is not None
        submenu_actions = submenu.actions()
        assert len(submenu_actions) == 0


class TestBuildStandardActions:
    """Tests for _build_standard_actions method."""

    def test_build_standard_actions_adds_actions(self) -> None:
        """_build_standard_actions adds actions to menu."""
        consumer = _MixinConsumer()
        menu = QMenu()

        actions_config = [
            ("Open Folder", "folder", "#FF6B6B", MagicMock()),
            ("Copy Path", "clipboard", "#4ECDC4", MagicMock()),
        ]

        consumer._build_standard_actions(menu, actions_config)
        process_qt_events()

        # Menu should have the correct number of actions
        assert len(menu.actions()) == len(actions_config)

    def test_build_standard_actions_labels(self) -> None:
        """_build_standard_actions creates actions with correct labels."""
        consumer = _MixinConsumer()
        menu = QMenu()

        callback1 = MagicMock()
        callback2 = MagicMock()

        actions_config = [
            ("Open Folder", "folder", "#FF6B6B", callback1),
            ("Copy Path", "clipboard", "#4ECDC4", callback2),
        ]

        consumer._build_standard_actions(menu, actions_config)
        process_qt_events()

        assert menu.actions()[0].text() == "Open Folder"
        assert menu.actions()[1].text() == "Copy Path"

    def test_build_standard_actions_icons(self) -> None:
        """_build_standard_actions adds icons to actions."""
        consumer = _MixinConsumer()
        menu = QMenu()

        actions_config = [
            ("Open Folder", "folder", "#FF6B6B", MagicMock()),
        ]

        consumer._build_standard_actions(menu, actions_config)
        process_qt_events()

        action = menu.actions()[0]
        assert not action.icon().isNull()

    def test_build_standard_actions_callbacks_triggered(self) -> None:
        """_build_standard_actions callbacks are called when triggered."""
        consumer = _MixinConsumer()
        menu = QMenu()

        callback1 = MagicMock()
        callback2 = MagicMock()

        actions_config = [
            ("Action 1", "folder", "#FF6B6B", callback1),
            ("Action 2", "clipboard", "#4ECDC4", callback2),
        ]

        consumer._build_standard_actions(menu, actions_config)
        process_qt_events()

        # Trigger first action
        menu.actions()[0].trigger()
        process_qt_events()

        callback1.assert_called_once()
        callback2.assert_not_called()

        # Trigger second action
        menu.actions()[1].trigger()
        process_qt_events()

        callback2.assert_called_once()

    def test_build_standard_actions_multiple_callbacks(self) -> None:
        """_build_standard_actions handles multiple callbacks independently."""
        consumer = _MixinConsumer()
        menu = QMenu()

        callbacks = [MagicMock() for _ in range(3)]

        actions_config = [
            ("Action 1", "folder", "#FF6B6B", callbacks[0]),
            ("Action 2", "clipboard", "#4ECDC4", callbacks[1]),
            ("Action 3", "pin", "#95D5B2", callbacks[2]),
        ]

        consumer._build_standard_actions(menu, actions_config)
        process_qt_events()

        # Trigger each action and verify only its callback is called
        for i, action in enumerate(menu.actions()):
            # Clear all mocks
            for cb in callbacks:
                cb.reset_mock()

            # Trigger this action
            action.trigger()
            process_qt_events()

            # Verify only this callback was called
            callbacks[i].assert_called_once()
            for j, cb in enumerate(callbacks):
                if i != j:
                    cb.assert_not_called()

    def test_build_standard_actions_empty_list(self) -> None:
        """_build_standard_actions handles empty config gracefully."""
        consumer = _MixinConsumer()
        menu = QMenu()

        consumer._build_standard_actions(menu, [])
        process_qt_events()

        # Menu should be empty
        assert len(menu.actions()) == 0
