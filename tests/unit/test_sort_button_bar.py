"""Unit tests for sort_button_bar.py - SortButtonBar widget.

Tests the SortButtonBar class which provides toggle buttons for
name/date sorting in grid views.

Test Coverage:
- Initialization and button setup
- Layout integration (add_to_layout)
- Default sort order
- Button click callbacks
- Programmatic set_order updates (no callback fire)
- Invalid order handling
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ui.sort_button_bar import SortButtonBar


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


pytestmark = [pytest.mark.unit, pytest.mark.qt]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def container(qtbot: QtBot) -> QWidget:
    """Create a parent widget container for the SortButtonBar."""
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def callback() -> MagicMock:
    """Create a mock callback for sort order changes."""
    return MagicMock()


@pytest.fixture
def sort_bar(container: QWidget, callback: MagicMock) -> SortButtonBar:
    """Create a SortButtonBar with mock callback."""
    return SortButtonBar(callback, container)


# ============================================================================
# Test Layout Integration
# ============================================================================


class TestLayoutIntegration:
    """Test SortButtonBar integration with layouts."""

    def test_add_to_layout_adds_three_widgets(
        self, sort_bar: SortButtonBar, container: QWidget
    ) -> None:
        """Test that add_to_layout adds label and two buttons to layout."""
        layout = QHBoxLayout()
        sort_bar.add_to_layout(layout)

        assert layout.count() == 3
        # Verify widget types: label, name button, date button
        assert layout.itemAt(0) is not None
        assert layout.itemAt(1) is not None
        assert layout.itemAt(2) is not None


# ============================================================================
# Test Initialization and Default State
# ============================================================================


class TestInitialization:
    """Test SortButtonBar initialization."""

    def test_default_order_is_date(self, sort_bar: SortButtonBar) -> None:
        """Test that Date button is checked by default and Name is not."""
        assert sort_bar._date_btn.isChecked() is True
        assert sort_bar._name_btn.isChecked() is False

    def test_label_created(self, sort_bar: SortButtonBar) -> None:
        """Test that sort label is created with correct text."""
        assert sort_bar._label.text() == "Sort:"

    def test_name_button_properties(self, sort_bar: SortButtonBar) -> None:
        """Test Name button is configured correctly."""
        assert sort_bar._name_btn.text() == "Name"
        assert sort_bar._name_btn.isCheckable() is True
        assert sort_bar._name_btn.toolTip() == "Sort by shot name alphabetically"

    def test_date_button_properties(self, sort_bar: SortButtonBar) -> None:
        """Test Date button is configured correctly."""
        assert sort_bar._date_btn.text() == "Date"
        assert sort_bar._date_btn.isCheckable() is True
        assert sort_bar._date_btn.toolTip() == "Sort by date (newest first)"

    def test_button_group_created(self, sort_bar: SortButtonBar) -> None:
        """Test that QButtonGroup is created and buttons registered."""
        assert sort_bar._button_group is not None
        # Button group should have 2 buttons
        assert len(sort_bar._button_group.buttons()) == 2


# ============================================================================
# Test User Click Callbacks
# ============================================================================


class TestClickCallbacks:
    """Test that button clicks fire the callback."""

    def test_click_name_fires_callback(
        self, qtbot: QtBot, sort_bar: SortButtonBar, callback: MagicMock
    ) -> None:
        """Test clicking Name button fires callback with 'name'."""
        sort_bar._name_btn.click()

        callback.assert_called_once_with("name")

    def test_click_date_fires_callback(
        self, qtbot: QtBot, sort_bar: SortButtonBar, callback: MagicMock
    ) -> None:
        """Test clicking Date button fires callback with 'date'."""
        # First click Name to ensure we're testing Date callback
        sort_bar._name_btn.click()
        callback.reset_mock()

        # Now click Date
        sort_bar._date_btn.click()

        callback.assert_called_once_with("date")

    def test_callback_receives_correct_order_after_toggle(
        self, qtbot: QtBot, sort_bar: SortButtonBar, callback: MagicMock
    ) -> None:
        """Test toggling between buttons fires callback with correct order."""
        # Start with Date (default)
        assert sort_bar._date_btn.isChecked() is True

        # Click Name
        sort_bar._name_btn.click()
        assert callback.call_args_list[-1][0][0] == "name"
        assert sort_bar._name_btn.isChecked() is True

        # Click Date
        sort_bar._date_btn.click()
        assert callback.call_args_list[-1][0][0] == "date"
        assert sort_bar._date_btn.isChecked() is True


# ============================================================================
# Test Programmatic set_order (no callback)
# ============================================================================


class TestSetOrderNoCallback:
    """Test set_order method does not fire callback."""

    def test_set_order_name_does_not_fire_callback(
        self, sort_bar: SortButtonBar, callback: MagicMock
    ) -> None:
        """Test that set_order('name') does not fire the callback."""
        sort_bar.set_order("name")

        callback.assert_not_called()

    def test_set_order_date_does_not_fire_callback(
        self, sort_bar: SortButtonBar, callback: MagicMock
    ) -> None:
        """Test that set_order('date') does not fire the callback."""
        # Start with Name to ensure we're testing
        sort_bar.set_order("name")
        callback.reset_mock()

        # Now set to Date
        sort_bar.set_order("date")

        callback.assert_not_called()

    def test_set_order_does_not_fire_even_after_user_click(
        self, qtbot: QtBot, sort_bar: SortButtonBar, callback: MagicMock
    ) -> None:
        """Test that set_order does not fire callback even after user click."""
        # User clicks Name (fires callback)
        sort_bar._name_btn.click()
        assert callback.call_count == 1

        # Programmatic set_order should not fire callback
        sort_bar.set_order("date")
        assert callback.call_count == 1  # Still 1, not incremented


# ============================================================================
# Test set_order Updates Button State
# ============================================================================


class TestSetOrderButtonState:
    """Test that set_order correctly updates button checked state."""

    def test_set_order_updates_button_state(self, sort_bar: SortButtonBar) -> None:
        """Test set_order updates checked state of buttons."""
        # Default is Date
        assert sort_bar._date_btn.isChecked() is True
        assert sort_bar._name_btn.isChecked() is False

        # Set to Name
        sort_bar.set_order("name")
        assert sort_bar._name_btn.isChecked() is True
        assert sort_bar._date_btn.isChecked() is False

        # Set back to Date
        sort_bar.set_order("date")
        assert sort_bar._date_btn.isChecked() is True
        assert sort_bar._name_btn.isChecked() is False

    def test_set_order_name_checks_only_name(self, sort_bar: SortButtonBar) -> None:
        """Test set_order('name') checks Name and unchecks Date."""
        sort_bar.set_order("name")

        assert sort_bar._name_btn.isChecked() is True
        assert sort_bar._date_btn.isChecked() is False

    def test_set_order_date_checks_only_date(self, sort_bar: SortButtonBar) -> None:
        """Test set_order('date') checks Date and unchecks Name."""
        # Start with Name
        sort_bar.set_order("name")
        assert sort_bar._name_btn.isChecked() is True

        # Set to Date
        sort_bar.set_order("date")
        assert sort_bar._date_btn.isChecked() is True
        assert sort_bar._name_btn.isChecked() is False


# ============================================================================
# Test Invalid Order Handling
# ============================================================================


class TestInvalidOrderHandling:
    """Test handling of invalid order values."""

    def test_set_order_invalid_ignored(
        self, sort_bar: SortButtonBar, callback: MagicMock
    ) -> None:
        """Test that set_order with invalid value is silently ignored."""
        # Start with known state
        sort_bar.set_order("date")
        assert sort_bar._date_btn.isChecked() is True

        # Try invalid order
        sort_bar.set_order("invalid")

        # State should be unchanged
        assert sort_bar._date_btn.isChecked() is True
        assert sort_bar._name_btn.isChecked() is False

        # No callback should be fired
        callback.assert_not_called()

    def test_set_order_empty_string_ignored(self, sort_bar: SortButtonBar) -> None:
        """Test that set_order with empty string is ignored."""
        sort_bar.set_order("date")
        initial_checked = sort_bar._date_btn.isChecked()

        sort_bar.set_order("")

        assert sort_bar._date_btn.isChecked() == initial_checked

    def test_set_order_case_sensitive(self, sort_bar: SortButtonBar) -> None:
        """Test that set_order is case-sensitive (uppercase ignored)."""
        sort_bar.set_order("date")
        assert sort_bar._date_btn.isChecked() is True

        # Try uppercase
        sort_bar.set_order("NAME")

        # Should be ignored
        assert sort_bar._date_btn.isChecked() is True
        assert sort_bar._name_btn.isChecked() is False

    def test_set_order_with_whitespace_ignored(self, sort_bar: SortButtonBar) -> None:
        """Test that set_order with whitespace is ignored."""
        sort_bar.set_order("date")

        sort_bar.set_order(" name ")

        # Should be ignored
        assert sort_bar._date_btn.isChecked() is True
        assert sort_bar._name_btn.isChecked() is False
