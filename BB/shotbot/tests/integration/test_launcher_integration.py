#!/usr/bin/env python3
"""Test script for custom launcher integration in ShotBot."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication

from launcher_dialog import LauncherManagerDialog
from launcher_manager import LauncherManager


def test_launcher_integration():
    """Test the launcher integration."""
    app = QApplication(sys.argv)

    # Create launcher manager
    manager = LauncherManager()

    # Create some test launchers if none exist
    if not manager.list_launchers():
        print("Creating test launchers...")

        # ShotBot Debug launcher
        launcher1_id = manager.create_launcher(
            name="ShotBot Debug Mode",
            command="rez env PySide6_Essentials pillow Jinja2 -- python3 '{workspace_path}/shotbot.py' --debug",
            description="Launch ShotBot in debug mode with rez environment",
            category="Debug",
            persist_terminal=True,
        )
        print(f"Created launcher 1: {launcher1_id}")

        # Nuke launcher
        launcher2_id = manager.create_launcher(
            name="Nuke Shot",
            command="nuke --nc '{workspace_path}/nuke/{shot}_v001.nk'",
            description="Launch Nuke with shot file",
            category="Applications",
        )
        print(f"Created launcher 2: {launcher2_id}")

        # Script launcher
        launcher3_id = manager.create_launcher(
            name="Check Plate",
            command="python3 /tools/check_plate.py --shot {full_name} --show {show}",
            description="Run plate validation script",
            category="Scripts",
        )
        print(f"Created launcher 3: {launcher3_id}")

    # Show the launcher dialog
    dialog = LauncherManagerDialog(manager)
    dialog.show()

    print("\nLauncher Manager Dialog opened successfully!")
    print("Features to test:")
    print("- Add new launcher (click 'Add New Launcher')")
    print("- Edit existing launcher (select and press F2 or click Edit)")
    print("- Delete launcher (select and press Delete)")
    print("- Search launchers (type in search field)")
    print("- Launch command (double-click or press Enter)")
    print(
        "- Keyboard shortcuts: Ctrl+N (new), Ctrl+F (search), Ctrl+L (from main window)"
    )

    # Run the application
    sys.exit(app.exec())


if __name__ == "__main__":
    test_launcher_integration()
