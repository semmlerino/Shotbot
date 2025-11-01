#!/usr/bin/env python3
"""Automated integration test for custom launcher integration in ShotBot."""

from PySide6.QtCore import QTimer

from launcher_dialog import LauncherManagerDialog
from launcher_manager import LauncherManager, LauncherTerminal


def test_launcher_integration(qtbot):
    """Test the launcher integration without user interaction."""
    # Create launcher manager
    manager = LauncherManager()

    # Clear any existing launchers for test isolation
    for launcher in manager.list_launchers():
        manager.delete_launcher(launcher.id)

    # Test creating launchers with different configurations

    # ShotBot Debug launcher (terminal required)
    launcher1_id = manager.create_launcher(
        name="ShotBot Debug Mode",
        command="echo 'Debug mode: $workspace_path'",  # Safe test command
        description="Launch ShotBot in debug mode with rez environment",
        category="Debug",
        terminal=LauncherTerminal(required=True, persist=True),
    )
    assert launcher1_id is not None
    assert manager.get_launcher(launcher1_id).terminal.required is True
    assert manager.get_launcher(launcher1_id).terminal.persist is True

    # Nuke launcher (default worker thread)
    launcher2_id = manager.create_launcher(
        name="Nuke Shot",
        command="echo 'Nuke: $workspace_path/$shot'",  # Safe test command
        description="Launch Nuke with shot file",
        category="Applications",
    )
    assert launcher2_id is not None
    assert manager.get_launcher(launcher2_id).terminal.required is False

    # Script launcher with variables
    launcher3_id = manager.create_launcher(
        name="Check Plate",
        command="echo 'Checking $full_name in $show'",  # Safe test command
        description="Run plate validation script",
        category="Scripts",
        variables={"extra_arg": "test_value"},
    )
    assert launcher3_id is not None
    assert "extra_arg" in manager.get_launcher(launcher3_id).variables

    # Verify all launchers were created
    launchers = manager.list_launchers()
    assert len(launchers) == 3

    # Test categories
    categories = manager.get_categories()
    assert "Debug" in categories
    assert "Applications" in categories
    assert "Scripts" in categories

    # Test launcher dialog creation and basic functionality
    dialog = LauncherManagerDialog(manager)
    qtbot.addWidget(dialog)

    # Verify dialog initializes properly
    assert dialog.launcher_manager == manager
    assert dialog.launcher_list is not None

    # Test dialog shows and can be closed
    dialog.show()
    qtbot.waitExposed(dialog)

    # Use QTimer to close dialog after a short delay
    def close_dialog():
        dialog.close()

    QTimer.singleShot(100, close_dialog)
    qtbot.waitUntil(lambda: not dialog.isVisible(), timeout=1000)

    # Clean up test launchers
    for launcher in manager.list_launchers():
        manager.delete_launcher(launcher.id)

    assert len(manager.list_launchers()) == 0

    # Ensure proper cleanup
    manager.shutdown()


# Interactive script for manual testing
def manual_launcher_integration():
    """Interactive version for manual testing."""
    import sys

    from PySide6.QtWidgets import QApplication

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
            terminal=LauncherTerminal(required=True, persist=True),
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
    manual_launcher_integration()
