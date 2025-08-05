#!/usr/bin/env python3
"""Example usage of LauncherManager for ShotBot custom launchers.

This script demonstrates how to integrate the LauncherManager
into the ShotBot application.
"""

import logging
import sys
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(level=logging.INFO)

# Mock PySide6 if not available for demonstration
try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    print("PySide6 not available - using mock for demonstration")

    class Signal:
        def __init__(self, *args):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, *args):
            for callback in self.callbacks:
                callback(*args)

    class QObject:
        pass

    # Mock the PySide6 module for imports
    from types import ModuleType

    # Create mock modules
    pyside6 = ModuleType("PySide6")
    qtcore = ModuleType("PySide6.QtCore")
    qtcore.QObject = QObject
    qtcore.Signal = Signal
    pyside6.QtCore = qtcore

    # Install in sys.modules
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore


# Mock Shot class for demonstration
class Shot:
    def __init__(self, show, sequence, shot, workspace_path):
        self.show = show
        self.sequence = sequence
        self.shot = shot
        self.workspace_path = workspace_path

    @property
    def full_name(self):
        return f"{self.sequence}_{self.shot}"


# Mock utilities for demonstration
class PathUtils:
    @staticmethod
    def validate_path_exists(path, description=""):
        return False  # Mock as not existing for demo


class ValidationUtils:
    pass


# Mock config
class Config:
    APP_VERSION = "1.0.0"


# Mock modules for launcher_manager imports
sys.modules["utils"] = type(sys)("utils")
sys.modules["utils"].PathUtils = PathUtils
sys.modules["utils"].ValidationUtils = ValidationUtils
sys.modules["config"] = type(sys)("config")
sys.modules["config"].Config = Config
sys.modules["shot_model"] = type(sys)("shot_model")
sys.modules["shot_model"].Shot = Shot

from launcher_manager import LauncherEnvironment, LauncherManager, LauncherTerminal


def main():
    """Demonstrate LauncherManager usage."""
    print("=== ShotBot LauncherManager Example ===\n")

    # Create manager instance
    manager = LauncherManager()

    # Connect to signals for demonstration
    manager.launcher_added.connect(
        lambda launcher_id: print(f"✓ Launcher added: {launcher_id}")
    )
    manager.launcher_updated.connect(
        lambda launcher_id: print(f"✓ Launcher updated: {launcher_id}")
    )
    manager.launcher_deleted.connect(
        lambda launcher_id: print(f"✓ Launcher deleted: {launcher_id}")
    )
    manager.validation_error.connect(
        lambda field, error: print(f"✗ Validation error in {field}: {error}")
    )
    manager.execution_started.connect(
        lambda launcher_id: print(f"🚀 Execution started: {launcher_id}")
    )
    manager.execution_finished.connect(
        lambda launcher_id, success: print(
            f"{'✓' if success else '✗'} Execution {'completed' if success else 'failed'}: {launcher_id}"
        )
    )

    print("1. Creating custom launchers...")

    # Create a simple launcher
    simple_id = manager.create_launcher(
        name="Simple Echo",
        command="echo 'Hello from {show} shot {full_name}'",
        description="Simple echo command with shot variables",
    )

    # Create a more complex launcher with environment
    complex_id = manager.create_launcher(
        name="Nuke with Custom Script",
        command="nuke --nc {workspace_path}/nuke/{shot}_custom_v001.nk",
        description="Launch Nuke with custom script template",
        category="compositing",
        variables={"script_template": "/studio/templates/nuke/shot_template.nk"},
        environment=LauncherEnvironment(type="rez", packages=["nuke", "studio_tools"]),
        terminal=LauncherTerminal(required=False, title="Nuke - {show} {full_name}"),
    )

    # Create a debug launcher
    debug_id = manager.create_launcher(
        name="Debug Shot",
        command="python3 /studio/tools/debug_shot.py --shot={workspace_path} --verbose",
        description="Debug tools for shot analysis",
        category="debug",
    )

    print(f"\n2. Created {len(manager.list_launchers())} launchers")

    # List all launchers
    print("\n3. Listing all launchers:")
    for launcher in manager.list_launchers():
        print(f"   - {launcher.name} ({launcher.category}): {launcher.command}")

    # List by category
    print(f"\n4. Categories: {', '.join(manager.get_categories())}")

    # Create a test shot for execution
    test_shot = Shot(
        show="demo_show",
        sequence="seq001",
        shot="sh010",
        workspace_path="/shows/demo_show/shots/seq001/sh010",
    )

    print(f"\n5. Test shot context: {test_shot.full_name}")

    # Execute simple launcher in shot context (dry run)
    if simple_id:
        print("\n6. Executing simple launcher (dry run):")
        success = manager.execute_in_shot_context(simple_id, test_shot, dry_run=True)
        print(f"   Dry run success: {success}")

    # Validate paths for complex launcher
    if complex_id:
        print("\n7. Validating complex launcher paths:")
        errors = manager.validate_launcher_paths(complex_id, test_shot)
        if errors:
            print("   Validation errors:")
            for error in errors:
                print(f"   - {error}")
        else:
            print("   ✓ All paths valid")

    # Update a launcher
    if debug_id:
        print("\n8. Updating debug launcher:")
        success = manager.update_launcher(
            debug_id, description="Enhanced debug tools for shot analysis with logging"
        )
        print(f"   Update success: {success}")

    # Test variable substitution
    print("\n9. Testing variable substitution:")
    test_command = "process_shot --input={workspace_path} --output={workspace_path}/output --shot={full_name}"
    substituted = manager._substitute_variables(test_command, test_shot)
    print(f"   Original: {test_command}")
    print(f"   Substituted: {substituted}")

    # Demonstrate error handling
    print("\n10. Testing error handling:")

    # Try to create launcher with empty name
    invalid_id = manager.create_launcher(name="", command="echo test")
    print(f"   Invalid launcher created: {invalid_id is not None}")

    # Try to create launcher with dangerous command
    dangerous_id = manager.create_launcher(name="Dangerous", command="rm -rf /")
    print(f"   Dangerous launcher created: {dangerous_id is not None}")

    # Final summary
    final_count = len(manager.list_launchers())
    print("\n=== Summary ===")
    print(f"Total launchers: {final_count}")
    print(f"Categories: {', '.join(manager.get_categories())}")

    print("\n✓ LauncherManager demonstration complete!")


if __name__ == "__main__":
    main()
