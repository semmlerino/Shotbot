"""Unit tests for log_viewer.py"""

import pytest
from PySide6.QtWidgets import QTextEdit

from config import Config
from log_viewer import LogViewer


class TestLogViewer:
    """Test LogViewer functionality."""

    @pytest.fixture
    def log_viewer(self, qapp):
        """Create a LogViewer instance."""
        return LogViewer()

    def test_initialization(self, log_viewer):
        """Test LogViewer initialization."""
        assert log_viewer._line_count == 0
        assert isinstance(log_viewer.log_text, QTextEdit)
        assert log_viewer.log_text.isReadOnly() is True
        assert log_viewer.clear_button is not None
        assert log_viewer.clear_button.text() == "Clear Log"

    def test_add_command(self, log_viewer):
        """Test adding a command to the log."""
        timestamp = "2025-07-28 12:00:00"
        command = "ws -sg 101_ABC"

        log_viewer.add_command(timestamp, command)

        # Check that text was added
        text = log_viewer.log_text.toPlainText()
        assert timestamp in text
        assert command in text
        assert log_viewer._line_count == 1

    def test_add_error(self, log_viewer):
        """Test adding an error to the log."""
        timestamp = "2025-07-28 12:00:01"
        error = "Command failed with exit code 1"

        log_viewer.add_error(timestamp, error)

        # Check that error was added
        text = log_viewer.log_text.toPlainText()
        assert timestamp in text
        assert f"ERROR: {error}" in text
        assert log_viewer._line_count == 1

    def test_add_entry_with_color(self, log_viewer):
        """Test the internal _add_entry method."""
        timestamp = "2025-07-28 12:00:02"
        text = "Test entry"
        color = "#00ff00"

        log_viewer._add_entry(timestamp, text, color)

        # Check HTML content
        html = log_viewer.log_text.toHtml()
        assert timestamp in html
        assert text in html
        assert color in html
        assert log_viewer._line_count == 1

    def test_auto_scroll_to_bottom(self, log_viewer):
        """Test that log auto-scrolls to bottom."""
        # Add multiple entries
        for i in range(20):
            log_viewer.add_command(f"12:00:{i:02d}", f"Command {i}")

        # Check that scrollbar is at maximum
        scrollbar = log_viewer.log_text.verticalScrollBar()
        assert scrollbar.value() == scrollbar.maximum()

    def test_line_count_limit(self, log_viewer, monkeypatch):
        """Test that log trims when exceeding max lines."""
        # Set a small limit for testing
        monkeypatch.setattr(Config, "LOG_MAX_LINES", 5)

        # Add more entries than the limit
        for i in range(10):
            log_viewer.add_command(f"12:00:{i:02d}", f"Command {i}")

        # Should have exactly LOG_MAX_LINES
        assert log_viewer._line_count == 5

        # Check that trimming occurred by verifying latest entries remain
        text = log_viewer.log_text.toPlainText()
        # Should contain latest entries (after trimming)
        assert "Command 9" in text  # Latest entry should be present

    def test_trim_log(self, log_viewer, monkeypatch):
        """Test the _trim_log method."""
        # Set a small limit
        monkeypatch.setattr(Config, "LOG_MAX_LINES", 3)

        # Add entries
        log_viewer.add_command("12:00:00", "Command 1")
        log_viewer.add_command("12:00:01", "Command 2")
        log_viewer.add_command("12:00:02", "Command 3")
        log_viewer._line_count = 5  # Simulate exceeding limit

        # Trim
        log_viewer._trim_log()

        # Should have correct line count
        assert log_viewer._line_count == 3

    def test_clear_log(self, log_viewer):
        """Test clearing the log."""
        # Add some entries
        log_viewer.add_command("12:00:00", "Command 1")
        log_viewer.add_command("12:00:01", "Command 2")
        log_viewer.add_error("12:00:02", "Error 1")

        assert log_viewer._line_count == 3
        assert log_viewer.log_text.toPlainText() != ""

        # Clear the log
        log_viewer.clear_log()

        # Should be empty
        assert log_viewer._line_count == 0
        assert log_viewer.log_text.toPlainText() == ""

    def test_clear_button_connection(self, log_viewer):
        """Test that clear button is connected properly."""
        # Add some content
        log_viewer.add_command("12:00:00", "Test command")
        assert log_viewer._line_count == 1

        # Click clear button
        log_viewer.clear_button.click()

        # Should be cleared
        assert log_viewer._line_count == 0
        assert log_viewer.log_text.toPlainText() == ""

    def test_text_edit_properties(self, log_viewer):
        """Test text edit widget properties."""
        # Check font
        font = log_viewer.log_text.font()
        assert font.family() == "Consolas"
        assert font.pointSize() == 9

        # Check read-only
        assert log_viewer.log_text.isReadOnly() is True

        # Check style
        style = log_viewer.log_text.styleSheet()
        assert "background-color: #1e1e1e" in style
        assert "color: #d4d4d4" in style

    def test_html_formatting(self, log_viewer):
        """Test HTML formatting in entries."""
        timestamp = "12:00:00"
        command = "ws -sg test"

        log_viewer.add_command(timestamp, command)

        # HTML should contain the command text
        html = log_viewer.log_text.toHtml()
        assert timestamp in html
        assert "test" in html

    def test_cursor_position_after_add(self, log_viewer):
        """Test cursor position after adding entries."""
        # Add multiple entries
        for i in range(5):
            log_viewer.add_command(f"12:00:{i:02d}", f"Command {i}")

        # Cursor should be at end
        cursor = log_viewer.log_text.textCursor()
        assert cursor.position() == cursor.anchor()  # No selection

    def test_multiple_entry_types(self, log_viewer):
        """Test mixing commands and errors."""
        log_viewer.add_command("12:00:00", "Starting process")
        log_viewer.add_error("12:00:01", "Connection failed")
        log_viewer.add_command("12:00:02", "Retrying...")
        log_viewer.add_error("12:00:03", "Still failing")

        text = log_viewer.log_text.toPlainText()
        assert "Starting process" in text
        assert "ERROR: Connection failed" in text
        assert "Retrying..." in text
        assert "ERROR: Still failing" in text
        assert log_viewer._line_count == 4

    def test_long_text_entries(self, log_viewer):
        """Test handling long text entries."""
        timestamp = "12:00:00"
        long_command = "ws -sg " + " ".join([f"shot_{i:04d}" for i in range(100)])

        log_viewer.add_command(timestamp, long_command)

        # Should handle long text without issues
        text = log_viewer.log_text.toPlainText()
        assert "shot_0000" in text
        assert "shot_0099" in text

    def test_special_characters_in_entries(self, log_viewer):
        """Test special characters in log entries."""
        special_chars = "Test & < > \" ' \n \t"

        log_viewer.add_command("12:00:00", special_chars)

        # Should handle special characters
        text = log_viewer.log_text.toPlainText()
        # Note: newlines and tabs might be normalized
        assert "Test" in text
        assert "&" in text

    def test_rapid_additions(self, log_viewer):
        """Test rapid addition of many entries."""
        # Add many entries quickly
        for i in range(50):
            if i % 2 == 0:
                log_viewer.add_command(f"12:{i:02d}:00", f"Command {i}")
            else:
                log_viewer.add_error(f"12:{i:02d}:00", f"Error {i}")

        # Should handle all entries
        assert log_viewer._line_count <= Config.LOG_MAX_LINES

    def test_empty_text_handling(self, log_viewer):
        """Test handling empty text."""
        log_viewer.add_command("12:00:00", "")
        log_viewer.add_error("12:00:01", "")

        # Should still add entries even if text is empty
        assert log_viewer._line_count == 2
        text = log_viewer.log_text.toPlainText()
        assert "12:00:00" in text
        assert "12:00:01" in text
