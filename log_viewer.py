"""Log viewer widget for displaying command history."""

# Third-party imports
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget

# Local application imports
from config import Config
from logging_mixin import LoggingMixin
from qt_widget_mixin import QtWidgetMixin


class LogViewer(QtWidgetMixin, LoggingMixin, QWidget):
    """Widget for displaying command execution logs."""

    def __init__(self) -> None:
        super().__init__()
        self._setup_ui()
        self._line_count = 0

    def _setup_ui(self) -> None:
        """Set up the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Text edit for logs
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))

        # Style the log
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 5px;
            }
        """)

        layout.addWidget(self.log_text)

        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Clear button
        self.clear_button = QPushButton("Clear Log")
        _ = self.clear_button.clicked.connect(clear_log)
        _ = self.clear_button.clicked.connect(self.clear_log)
        button_layout.addWidget(self.clear_button)

        layout.addLayout(button_layout)

    def add_command(self, timestamp: str, command: str) -> None:
        """Add a command to the log."""
        self._add_entry(timestamp, command, "#4ec9b0")  # Cyan color for commands

    def add_error(self, timestamp: str, error: str) -> None:
        """Add an error to the log."""
        self._add_entry(timestamp, f"ERROR: {error}", "#f44747")  # Red color for errors

    def _add_entry(self, timestamp: str, text: str, color: str) -> None:
        """Add an entry to the log with color."""
        # Format the entry
        entry = f'<span style="color: #666">[{timestamp}]</span> <span style="color: {color}">{text}</span>'

        # Add to log
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(entry + "<br>")

        # Auto-scroll to bottom
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum(),
        )

        # Limit lines
        self._line_count += 1
        if self._line_count > Config.LOG_MAX_LINES:
            self._trim_log()

    def _trim_log(self) -> None:
        """Trim log to maximum lines."""
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(
            QTextCursor.MoveOperation.Down,
            QTextCursor.MoveMode.KeepAnchor,
            self._line_count - Config.LOG_MAX_LINES,
        )
        cursor.removeSelectedText()
        self._line_count = Config.LOG_MAX_LINES

    def clear_log(self) -> None:
        """Clear the log."""
        self.log_text.clear()
        self._line_count = 0
