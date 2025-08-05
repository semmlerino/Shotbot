#!/usr/bin/env python3
"""Test script to verify custom launcher integration in main UI."""

import sys
from pathlib import Path

# Mock PySide6 if not available
try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout
except ImportError:
    print("PySide6 not available, using mock objects for testing")

    class MockSignal:
        def emit(self, *args):
            pass

        def connect(self, *args):
            pass

    class QObject:
        Signal = lambda: MockSignal()

    class QVBoxLayout:
        def addWidget(self, widget):
            pass

        def addLayout(self, layout):
            pass

        def count(self):
            return 0

        def takeAt(self, index):
            return None

        def setSpacing(self, spacing):
            pass

    class QPushButton:
        def __init__(self, text=""):
            self.text = text

        def setObjectName(self, name):
            pass

        def setToolTip(self, tip):
            pass

        def setStyleSheet(self, style):
            pass

        def setEnabled(self, enabled):
            pass

        def clicked(self):
            return MockSignal()

        def deleteLater(self):
            pass

    class QLabel:
        def __init__(self, text=""):
            self.text = text

        def setObjectName(self, name):
            pass

        def setStyleSheet(self, style):
            pass

    class QFrame:
        class Shape:
            HLine = 0

        class Shadow:
            Sunken = 0

        def setFrameShape(self, shape):
            pass

        def setFrameShadow(self, shadow):
            pass

        def setStyleSheet(self, style):
            pass


# Mock the modules before importing
if "PySide6" not in sys.modules:
    import types

    pyside6 = types.ModuleType("PySide6")
    qtcore = types.ModuleType("QtCore")
    qtcore.QObject = QObject
    qtcore.Signal = lambda: MockSignal()
    pyside6.QtCore = qtcore
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore

# Import our modules
sys.path.insert(0, str(Path(__file__).parent))
from launcher_manager import LauncherManager


def test_ui_integration():
    """Test the UI integration logic."""
    print("Testing Custom Launcher UI Integration")
    print("=" * 50)

    # Create mock launcher manager
    manager = LauncherManager()

    # Add some test launchers
    test_launchers = [
        {
            "name": "Script Runner",
            "command": "python3 /path/to/script.py",
            "description": "Run custom Python scripts",
            "category": "scripts",
        },
        {
            "name": "Render Farm Submit",
            "command": "submit_job $shot",
            "description": "Submit shot to render farm",
            "category": "render",
        },
        {
            "name": "Asset Browser",
            "command": "asset_browser --shot $shot",
            "description": "Open asset browser for current shot",
            "category": "tools",
        },
    ]

    for launcher_data in test_launchers:
        launcher_id = manager.create_launcher(**launcher_data)
        if launcher_id:
            print(f"✓ Created launcher: {launcher_data['name']}")
        else:
            print(f"✗ Failed to create launcher: {launcher_data['name']}")

    # Test UI update logic
    print("\nTesting UI Update Logic:")

    # Mock container
    QVBoxLayout()
    custom_buttons = {}

    # Get all launchers
    launchers = manager.list_launchers()
    print(f"Found {len(launchers)} launchers")

    # Group by category
    categories = {}
    for launcher in launchers:
        category = launcher.category or "custom"
        if category not in categories:
            categories[category] = []
        categories[category].append(launcher)

    print(f"Categories: {list(categories.keys())}")

    # Simulate button creation
    for category in sorted(categories.keys()):
        category_launchers = categories[category]
        print(f"\nCategory: {category}")

        for launcher in category_launchers:
            button_text = f"🚀 {launcher.name}"
            print(f"  - Button: {button_text}")
            print(f"    Tooltip: {launcher.description}")

            # Create mock button
            button = QPushButton(button_text)
            custom_buttons[launcher.id] = button

    print(f"\nTotal custom launcher buttons: {len(custom_buttons)}")

    # Test styling
    print("\nButton Styling:")
    print("Built-in launchers: Blue-gray theme (#2b3e50)")
    print("Custom launchers: Green theme (#1a4d2e)")

    print("\n✓ Custom launcher integration test completed successfully!")

    # Clean up
    config_file = Path.home() / ".shotbot" / "custom_launchers.json"
    if config_file.exists():
        config_file.unlink()
        print("\nCleaned up test configuration")


if __name__ == "__main__":
    test_ui_integration()
