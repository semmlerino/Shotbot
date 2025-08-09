#!/usr/bin/env python3
"""Test if QDesktopServices.openUrl() is blocking and potential solutions."""

import sys
import time

from PySide6.QtCore import QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget


class UrlOpenerThread(QThread):
    """Thread to open URL without blocking UI."""

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        """Open URL in thread."""
        QDesktopServices.openUrl(self.url)


class TestWindow(QWidget):
    """Test window to check UI blocking."""

    def __init__(self):
        super().__init__()
        self.counter = 0
        self.setup_ui()

        # Timer to update counter every 100ms
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_counter)
        self.timer.start(100)

    def setup_ui(self):
        """Set up the UI."""
        layout = QVBoxLayout(self)

        # Counter label to show UI responsiveness
        self.counter_label = QLabel("Counter: 0")
        layout.addWidget(self.counter_label)

        # Button to test direct openUrl (potentially blocking)
        btn_direct = QPushButton("Test Direct openUrl (may block)")
        btn_direct.clicked.connect(self.test_direct_open)
        layout.addWidget(btn_direct)

        # Button to test threaded openUrl
        btn_threaded = QPushButton("Test Threaded openUrl")
        btn_threaded.clicked.connect(self.test_threaded_open)
        layout.addWidget(btn_threaded)

        # Button to test with non-existent path
        btn_nonexistent = QPushButton("Test Non-existent Path")
        btn_nonexistent.clicked.connect(self.test_nonexistent_path)
        layout.addWidget(btn_nonexistent)

        # Status label
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        self.setWindowTitle("URL Opening Test")
        self.resize(300, 200)

    def update_counter(self):
        """Update counter to show UI is responsive."""
        self.counter += 1
        self.counter_label.setText(f"Counter: {self.counter}")

    def test_direct_open(self):
        """Test opening URL directly (potentially blocking)."""
        self.status_label.setText("Opening URL directly...")

        # Create test URL
        folder_path = "/tmp"
        url = QUrl()
        url.setScheme("file")
        url.setPath(folder_path)

        print(f"Direct opening: {url.toString()}")
        start_time = time.time()

        # This might block the UI
        result = QDesktopServices.openUrl(url)

        elapsed = time.time() - start_time
        self.status_label.setText(f"Direct open: {result}, took {elapsed:.3f}s")
        print(f"Direct open result: {result}, took {elapsed:.3f}s")

    def test_threaded_open(self):
        """Test opening URL in thread (non-blocking)."""
        self.status_label.setText("Opening URL in thread...")

        # Create test URL
        folder_path = "/tmp"
        url = QUrl()
        url.setScheme("file")
        url.setPath(folder_path)

        print(f"Threaded opening: {url.toString()}")

        # Open in thread
        self.opener_thread = UrlOpenerThread(url)
        self.opener_thread.finished.connect(
            lambda: self.status_label.setText("Threaded open completed")
        )
        self.opener_thread.start()

    def test_nonexistent_path(self):
        """Test with non-existent path to see if it blocks."""
        self.status_label.setText("Testing non-existent path...")

        # Create URL for non-existent path
        folder_path = "/nonexistent/path/that/does/not/exist"
        url = QUrl()
        url.setScheme("file")
        url.setPath(folder_path)

        print(f"Testing non-existent: {url.toString()}")
        start_time = time.time()

        result = QDesktopServices.openUrl(url)

        elapsed = time.time() - start_time
        self.status_label.setText(f"Non-existent: {result}, took {elapsed:.3f}s")
        print(f"Non-existent path result: {result}, took {elapsed:.3f}s")


def main():
    """Run the test application."""
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()

    print("Test window opened. Watch the counter to see if UI freezes.")
    print("Click buttons to test different URL opening approaches.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
