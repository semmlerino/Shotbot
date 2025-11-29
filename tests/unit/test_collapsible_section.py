"""Tests for CollapsibleSection widget."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from collapsible_section import CollapsibleSection
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


class TestCollapsibleSectionInit:
    """Tests for CollapsibleSection initialization."""

    def test_default_state_collapsed(self, qtbot: QtBot) -> None:
        """Section is collapsed by default."""
        section = CollapsibleSection("Test Section")
        qtbot.addWidget(section)

        assert not section.is_expanded()

    def test_initial_expanded_state(self, qtbot: QtBot) -> None:
        """Section can be created expanded."""
        section = CollapsibleSection("Test Section", expanded=True)
        qtbot.addWidget(section)

        assert section.is_expanded()

    def test_title_displayed(self, qtbot: QtBot) -> None:
        """Title is displayed in header."""
        section = CollapsibleSection("My Section")
        qtbot.addWidget(section)

        # Header button should contain title
        header_text = section._header_button.text()
        assert "My Section" in header_text


class TestCollapsibleSectionExpansion:
    """Tests for expand/collapse functionality."""

    def test_toggle_expansion(self, qtbot: QtBot) -> None:
        """Clicking header toggles expansion."""
        section = CollapsibleSection("Test", expanded=False)
        qtbot.addWidget(section)

        # Initially collapsed
        assert not section.is_expanded()

        # Click to expand
        qtbot.mouseClick(section._header_button, Qt.MouseButton.LeftButton)
        process_qt_events()
        assert section.is_expanded()

        # Click to collapse
        qtbot.mouseClick(section._header_button, Qt.MouseButton.LeftButton)
        process_qt_events()
        assert not section.is_expanded()

    def test_set_expanded_programmatically(self, qtbot: QtBot) -> None:
        """Can set expansion state programmatically."""
        section = CollapsibleSection("Test", expanded=False)
        qtbot.addWidget(section)

        section.set_expanded(True)
        assert section.is_expanded()

        section.set_expanded(False)
        assert not section.is_expanded()

    def test_expanded_changed_signal_emitted(self, qtbot: QtBot) -> None:
        """Signal emitted when expansion state changes."""
        section = CollapsibleSection("Test", expanded=False)
        qtbot.addWidget(section)

        with qtbot.waitSignal(section.expanded_changed, timeout=1000) as blocker:
            section.set_expanded(True)

        assert blocker.args == [True]

    def test_no_signal_when_state_unchanged(self, qtbot: QtBot) -> None:
        """No signal emitted when setting same state."""
        section = CollapsibleSection("Test", expanded=True)
        qtbot.addWidget(section)

        signals_received = []
        section.expanded_changed.connect(signals_received.append)

        # Set same state
        section.set_expanded(True)
        process_qt_events()

        assert len(signals_received) == 0

    def test_content_visibility_matches_expansion(self, qtbot: QtBot) -> None:
        """Content widget visibility matches expansion state."""
        section = CollapsibleSection("Test", expanded=False)
        content = QLabel("Content")
        section.set_content(content)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        # Collapsed - content hidden
        assert not section._content_container.isVisible()

        # Expanded - content visible
        section.set_expanded(True)
        process_qt_events()
        assert section._content_container.isVisible()


class TestCollapsibleSectionContent:
    """Tests for content management."""

    def test_set_content(self, qtbot: QtBot) -> None:
        """Can set content widget."""
        section = CollapsibleSection("Test")
        content = QLabel("Test Content")
        section.set_content(content)
        qtbot.addWidget(section)

        assert section.get_content() is content

    def test_replace_content(self, qtbot: QtBot) -> None:
        """Setting new content replaces old content."""
        section = CollapsibleSection("Test")
        old_content = QLabel("Old")
        new_content = QLabel("New")

        section.set_content(old_content)
        section.set_content(new_content)
        qtbot.addWidget(section)

        assert section.get_content() is new_content
        # Old content should have no parent
        assert old_content.parent() is None


class TestCollapsibleSectionTitleAndCount:
    """Tests for title and count display."""

    def test_set_title(self, qtbot: QtBot) -> None:
        """Can change title after creation."""
        section = CollapsibleSection("Original")
        qtbot.addWidget(section)

        section.set_title("Changed")
        assert "Changed" in section._header_button.text()

    def test_set_count(self, qtbot: QtBot) -> None:
        """Count is displayed in header."""
        section = CollapsibleSection("Files")
        qtbot.addWidget(section)

        section.set_count(5)
        header_text = section._header_button.text()
        assert "(5)" in header_text

    def test_clear_count(self, qtbot: QtBot) -> None:
        """Count can be cleared."""
        section = CollapsibleSection("Files")
        qtbot.addWidget(section)

        section.set_count(5)
        section.set_count(None)

        header_text = section._header_button.text()
        # Should not contain parentheses for count
        assert "(5)" not in header_text

    def test_header_indicator_changes(self, qtbot: QtBot) -> None:
        """Header indicator changes based on expansion state."""
        section = CollapsibleSection("Test", expanded=False)
        qtbot.addWidget(section)

        # Collapsed shows right arrow
        collapsed_text = section._header_button.text()
        assert "▶" in collapsed_text

        section.set_expanded(True)
        expanded_text = section._header_button.text()
        assert "▼" in expanded_text


class TestCollapsibleSectionStyling:
    """Tests for custom styling."""

    def test_set_header_style(self, qtbot: QtBot) -> None:
        """Can customize header appearance."""
        section = CollapsibleSection("Test")
        qtbot.addWidget(section)

        section.set_header_style(
            color="#ff0000",
            hover_color="#00ff00",
            hover_bg="#0000ff",
        )

        # Widget should still be functional after style change
        assert section.is_expanded() is False
        section.set_expanded(True)
        assert section.is_expanded() is True
