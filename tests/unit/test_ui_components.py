"""Tests for UI components.

This test suite validates the ui_components.py module following
UNIFIED_TESTING_GUIDE.md principles.
"""

from __future__ import annotations

import pytest

# Third-party imports
from PySide6.QtWidgets import QWidget


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

# Local application imports
from ui_components import (
    EmptyStateWidget,
    ModernButton,
    ProgressOverlay,
    ThumbnailPlaceholder,
)


class TestModernButton:
    """Test ModernButton widget with parent parameter handling."""

    def test_initialization_default_variant(self, qtbot):
        """Test button creation with default variant."""
        button = ModernButton("Test Button")
        qtbot.addWidget(button)

        assert button.text() == "Test Button"
        assert button.variant == "default"

    def test_initialization_with_parent(self, qtbot):
        """Test button creation with explicit parent (Qt crash prevention)."""
        parent = QWidget()
        qtbot.addWidget(parent)

        button = ModernButton("Test", parent=parent)
        qtbot.addWidget(button)

        assert button.parent() == parent
        assert button.text() == "Test"

    def test_initialization_danger_variant(self, qtbot):
        """Test button creation with danger variant."""
        button = ModernButton("Delete", variant="danger")
        qtbot.addWidget(button)

        assert button.text() == "Delete"
        assert button.variant == "danger"

    def test_initialization_primary_variant(self, qtbot):
        """Test button creation with primary variant."""
        button = ModernButton("Save", variant="primary")
        qtbot.addWidget(button)

        assert button.text() == "Save"
        assert button.variant == "primary"

    def test_clicked_signal(self, qtbot):
        """Test button click signal emission."""
        button = ModernButton("Click Me")
        qtbot.addWidget(button)

        with qtbot.waitSignal(button.clicked, timeout=1000):
            button.click()


class TestProgressOverlay:
    """Test ProgressOverlay widget."""

    def test_initialization(self, qtbot):
        """Test progress overlay creation."""
        parent = QWidget()
        qtbot.addWidget(parent)

        overlay = ProgressOverlay(parent)
        qtbot.addWidget(overlay)

        # Verify cancel button has proper parent (it's parented to the card frame, not overlay directly)
        assert overlay.cancel_button.parent() is not None
        # Button is ultimately owned by the overlay widget tree
        assert overlay.isAncestorOf(overlay.cancel_button)


class TestEmptyStateWidget:
    """Test EmptyStateWidget."""

    def test_initialization_with_action(self, qtbot):
        """Test empty state widget with action button."""
        widget = EmptyStateWidget(
            title="No Data",
            description="Add some data",
            action_text="Add",
        )
        qtbot.addWidget(widget)

        # Should have created action button with proper parent
        # Button is created dynamically, check it exists
        action_buttons = [
            child
            for child in widget.findChildren(ModernButton)
            if child.text() == "Add"
        ]
        assert len(action_buttons) == 1
        assert action_buttons[0].parent() is not None


class TestThumbnailPlaceholder:
    """Test ThumbnailPlaceholder widget."""

    def test_initialization_default_size(self, qtbot):
        """Test placeholder creation with default size."""
        placeholder = ThumbnailPlaceholder()
        qtbot.addWidget(placeholder)

        assert placeholder.width() == 200
        assert placeholder.height() == 200

    def test_initialization_custom_size(self, qtbot):
        """Test placeholder creation with custom size."""
        placeholder = ThumbnailPlaceholder(size=150)
        qtbot.addWidget(placeholder)

        assert placeholder.width() == 150
        assert placeholder.height() == 150
