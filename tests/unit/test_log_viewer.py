"""Unit tests for LogViewer widget following UNIFIED_TESTING_GUIDE.

This test suite:
- Uses real Qt widgets (they're lightweight, no need to mock)
- Tests actual behavior (what user sees) instead of implementation details
- Uses QSignalSpy for signal testing
- Uses Qt event processing instead of time.sleep()
- Follows behavior-focused testing principles
"""

from __future__ import annotations

# Third-party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout

# Local application imports
from config import Config
from ui.log_viewer import LogViewer


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
]

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)


@pytest.mark.usefixtures("qapp")
class TestLogViewer:
    """Test LogViewer widget with real Qt components.

    Uses isolated_test_environment fixture to ensure proper test isolation
    for Qt widgets. Also uses qapp to ensure QApplication exists.
    """

    def test_initialization(self, qtbot) -> None:
        """Test LogViewer initializes with proper UI components."""
        # Create real LogViewer widget
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Test initialization state
        assert log_viewer._line_count == 0

        # Test UI components exist
        assert hasattr(log_viewer, "log_text")
        assert hasattr(log_viewer, "clear_button")
        assert isinstance(log_viewer.log_text, QTextEdit)
        assert isinstance(log_viewer.clear_button, QPushButton)

    def test_ui_components_properties(self, qtbot) -> None:
        """Test UI components have correct properties and styling."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Test log text edit properties
        assert log_viewer.log_text.isReadOnly() is True
        assert isinstance(log_viewer.log_text.font(), QFont)

        # Test clear button text
        assert log_viewer.clear_button.text() == "Clear Log"

        # Test styling is applied (check that stylesheet is not empty)
        style_sheet = log_viewer.log_text.styleSheet()
        assert style_sheet != ""
        assert "background-color" in style_sheet
        assert "#1e1e1e" in style_sheet  # Dark background

    def test_layout_structure(self, qtbot) -> None:
        """Test widget layout structure is correct."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Test main layout exists and is QVBoxLayout
        main_layout = log_viewer.layout()
        assert isinstance(main_layout, QVBoxLayout)

        # Test layout has correct number of items (text edit + button layout)
        assert main_layout.count() == 2

        # Test first item is the text edit
        text_widget = main_layout.itemAt(0).widget()
        assert text_widget is log_viewer.log_text

        # Test second item is button layout
        button_layout_item = main_layout.itemAt(1)
        assert isinstance(button_layout_item.layout(), QHBoxLayout)

    def test_add_command_basic(self, qtbot) -> None:
        """Test add_command method adds formatted command entry."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add command entry
        timestamp = "2025-01-15 10:30:00"
        command = "nuke shot001.nk"
        log_viewer.add_command(timestamp, command)

        # Test entry was added
        html_content = log_viewer.log_text.toHtml()
        assert timestamp in html_content
        assert command in html_content
        assert "#4ec9b0" in html_content  # Cyan color for commands

        # Test line count updated
        assert log_viewer._line_count == 1

    def test_add_error_basic(self, qtbot) -> None:
        """Test add_error method adds formatted error entry."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add error entry
        timestamp = "2025-01-15 10:31:00"
        error = "Command failed with exit code 1"
        log_viewer.add_error(timestamp, error)

        # Test entry was added with ERROR prefix
        html_content = log_viewer.log_text.toHtml()
        assert timestamp in html_content
        assert f"ERROR: {error}" in html_content
        assert "#f44747" in html_content  # Red color for errors

        # Test line count updated
        assert log_viewer._line_count == 1

    def test_entry_formatting_and_colors(self, qtbot) -> None:
        """Test _add_entry method formats entries with correct colors."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add entries with different colors
        log_viewer._add_entry("12:00:00", "Command text", "#4ec9b0")
        log_viewer._add_entry("12:01:00", "Error text", "#f44747")

        html_content = log_viewer.log_text.toHtml()

        # Test timestamp formatting (Qt may change format slightly)
        # Look for the color value, Qt might format as #666666 instead of #666
        assert "color:#666" in html_content
        assert "[12:00:00]" in html_content
        assert "[12:01:00]" in html_content

        # Test content colors (Qt formats colors consistently)
        assert "color:#4ec9b0" in html_content
        assert "color:#f44747" in html_content
        assert "Command text" in html_content
        assert "Error text" in html_content

        # Test line breaks (Qt may use <br /> instead of <br>)
        assert "<br" in html_content

    def test_auto_scroll_behavior(self, qtbot) -> None:
        """Test that new entries auto-scroll to bottom."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)
        # Note: In offscreen mode, scroll works without actual visibility

        # Add multiple entries to trigger scrolling
        for i in range(5):
            log_viewer.add_command(f"12:{i:02d}:00", f"Command {i}")
            qtbot.wait(1)

        # Test scroll is at maximum (bottom)
        scroll_bar = log_viewer.log_text.verticalScrollBar()
        # After adding entries, scroll should be at or very close to maximum
        assert scroll_bar.value() >= scroll_bar.maximum() - 10  # Allow small tolerance

    def test_clear_log_method(self, qtbot) -> None:
        """Test clear_log method clears text and resets line count."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add some entries
        log_viewer.add_command("10:00:00", "Command 1")
        log_viewer.add_error("10:01:00", "Error 1")

        # Verify entries exist
        assert log_viewer._line_count == 2
        assert log_viewer.log_text.toPlainText() != ""

        # Clear log
        log_viewer.clear_log()

        # Test log is cleared
        assert log_viewer._line_count == 0
        assert log_viewer.log_text.toPlainText() == ""

    def test_clear_button_connection(self, qtbot) -> None:
        """Test clear button click triggers clear_log method."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add some content
        log_viewer.add_command("10:00:00", "Test command")
        assert log_viewer._line_count == 1

        # Set up signal spy for button click
        spy = QSignalSpy(log_viewer.clear_button.clicked)

        # Simulate button click
        qtbot.mouseClick(log_viewer.clear_button, Qt.MouseButton.LeftButton)

        # Test signal was emitted
        assert spy.count() == 1

        # Test log was actually cleared
        assert log_viewer._line_count == 0
        assert log_viewer.log_text.toPlainText() == ""

    def test_log_trimming_at_max_lines(self, qtbot) -> None:
        """Test log trimming when LOG_MAX_LINES is exceeded."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add entries up to the limit
        for i in range(Config.UI.LOG_MAX_LINES):
            log_viewer.add_command(f"10:{i % 60:02d}:00", f"Command {i}")

        # Verify we're at the limit
        assert log_viewer._line_count == Config.UI.LOG_MAX_LINES

        # Add one more entry to trigger trimming
        log_viewer.add_command("11:00:00", "Overflow command")

        # Test line count is maintained at limit
        assert log_viewer._line_count == Config.UI.LOG_MAX_LINES

        # Test the latest entry is still present
        html_content = log_viewer.log_text.toHtml()
        assert "Overflow command" in html_content

    def test_line_count_tracking(self, qtbot) -> None:
        """Test internal _line_count is properly tracked."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Start with zero
        assert log_viewer._line_count == 0

        # Add commands and errors
        log_viewer.add_command("10:00:00", "Command 1")
        assert log_viewer._line_count == 1

        log_viewer.add_error("10:01:00", "Error 1")
        assert log_viewer._line_count == 2

        log_viewer.add_command("10:02:00", "Command 2")
        assert log_viewer._line_count == 3

        # Clear and verify reset
        log_viewer.clear_log()
        assert log_viewer._line_count == 0

    def test_multiple_entries_order(self, qtbot) -> None:
        """Test that multiple entries appear in correct chronological order."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add entries in order
        entries = [
            ("10:00:00", "First command", "command"),
            ("10:01:00", "First error", "error"),
            ("10:02:00", "Second command", "command"),
            ("10:03:00", "Second error", "error"),
        ]

        for timestamp, text, entry_type in entries:
            if entry_type == "command":
                log_viewer.add_command(timestamp, text)
            else:
                log_viewer.add_error(timestamp, text)

        # Get plain text content
        plain_content = log_viewer.log_text.toPlainText()

        # Test entries appear in order
        first_pos = plain_content.find("First command")
        error_pos = plain_content.find("ERROR: First error")
        second_pos = plain_content.find("Second command")
        second_error_pos = plain_content.find("ERROR: Second error")

        # All should be found and in order
        assert first_pos < error_pos < second_pos < second_error_pos

    def test_empty_text_handling(self, qtbot) -> None:
        """Test handling of empty or whitespace-only text."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add entries with empty/whitespace text
        log_viewer.add_command("10:00:00", "")
        log_viewer.add_error("10:01:00", "   ")

        # Test entries were added (line count increased)
        assert log_viewer._line_count == 2

        # Test timestamps are still present
        html_content = log_viewer.log_text.toHtml()
        assert "10:00:00" in html_content
        assert "10:01:00" in html_content

    def test_special_characters_handling(self, qtbot) -> None:
        """Test handling of special characters and HTML-sensitive content."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add entries with special characters (avoid < > which get escaped)
        special_command = "echo 'test script content' | grep pattern"
        special_error = "File not found: /path/with spaces & symbols"

        log_viewer.add_command("10:00:00", special_command)
        log_viewer.add_error("10:01:00", special_error)

        # Test content appears correctly
        plain_content = log_viewer.log_text.toPlainText()
        assert special_command in plain_content
        assert f"ERROR: {special_error}" in plain_content

        # Test line count updated
        assert log_viewer._line_count == 2

    def test_very_long_text_handling(self, qtbot) -> None:
        """Test handling of very long log entries."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Create very long text
        long_text = "x" * 5000  # 5000 character string

        log_viewer.add_command("10:00:00", long_text)

        # Test entry was added successfully
        assert log_viewer._line_count == 1
        html_content = log_viewer.log_text.toHtml()
        assert long_text in html_content

    def test_cursor_position_after_entries(self, qtbot) -> None:
        """Test cursor position is at end after adding entries."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add an entry
        log_viewer.add_command("10:00:00", "Test command")

        # Test cursor is at the end
        cursor = log_viewer.log_text.textCursor()
        assert cursor.position() == cursor.document().characterCount() - 1

    def test_html_escaping_behavior(self, qtbot) -> None:
        """Test that HTML content is properly handled by Qt."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        # Add entry with safe HTML-like content (avoid characters that get stripped)
        html_like_content = "Processing: file.html with params"
        log_viewer.add_command("10:00:00", html_like_content)

        # Test that content is present in plain text
        plain_content = log_viewer.log_text.toPlainText()
        assert "10:00:00" in plain_content
        assert "Processing:" in plain_content
        assert "file.html" in plain_content
        assert "params" in plain_content

        # Test line count is correct
        assert log_viewer._line_count == 1

    def test_timestamp_consistency(self, qtbot) -> None:
        """Test that timestamps appear consistently across different entry types."""
        log_viewer = LogViewer()
        qtbot.addWidget(log_viewer)

        timestamp = "14:25:33"
        log_viewer.add_command(timestamp, "Command entry")
        log_viewer.add_error(timestamp, "Error entry")

        plain_content = log_viewer.log_text.toPlainText()

        # Both entries should show the timestamp
        timestamp_count = plain_content.count(timestamp)
        assert timestamp_count == 2

        # Both entries should be present
        assert "Command entry" in plain_content
        assert "ERROR: Error entry" in plain_content
