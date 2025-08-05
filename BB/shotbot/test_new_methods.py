#!/usr/bin/env python3
"""Simple test for the new LauncherManager methods without PySide6 dependency."""

import sys
import tempfile
from pathlib import Path


# Mock the required modules to avoid PySide6 dependency
class MockQObject:
    def __init__(self):
        pass


class MockSignal:
    def __init__(self, *args):
        pass

    def emit(self, *args):
        pass


sys.modules["PySide6"] = type(sys)("PySide6")
sys.modules["PySide6.QtCore"] = type(sys)("PySide6.QtCore")
sys.modules["PySide6.QtCore"].QObject = MockQObject
sys.modules["PySide6.QtCore"].Signal = MockSignal


# Mock other dependencies
class MockConfig:
    APP_VERSION = "1.0.0"


class MockShot:
    def __init__(self, show, sequence, shot):
        self.show = show
        self.sequence = sequence
        self.shot = shot
        self.full_name = f"{show}_{sequence}_{shot}"
        self.workspace_path = f"/workspace/{show}/{sequence}/{shot}"


class MockPathUtils:
    @staticmethod
    def validate_path_exists(path, description):
        return True


class MockValidationUtils:
    pass


sys.modules["config"] = type(sys)("config")
sys.modules["config"].Config = MockConfig
sys.modules["shot_model"] = type(sys)("shot_model")
sys.modules["shot_model"].Shot = MockShot
sys.modules["utils"] = type(sys)("utils")
sys.modules["utils"].PathUtils = MockPathUtils
sys.modules["utils"].ValidationUtils = MockValidationUtils

# Now import the actual module
from launcher_manager import LauncherManager


def test_get_launcher_by_name():
    """Test get_launcher_by_name method."""
    print("Testing get_launcher_by_name...")

    # Create a manager with temp config
    with tempfile.TemporaryDirectory() as temp_dir:
        # Override the config directory
        manager = LauncherManager()
        manager.config.config_dir = Path(temp_dir)
        manager.config.config_file = Path(temp_dir) / "test_launchers.json"

        # Add some test launchers
        launcher1_id = manager.create_launcher("Test Launcher 1", "echo test1")
        manager.create_launcher("Test Launcher 2", "echo test2")

        # Test finding existing launcher
        result = manager.get_launcher_by_name("Test Launcher 1")
        assert result is not None, "Should find existing launcher"
        assert result.name == "Test Launcher 1", "Should return correct launcher"
        assert result.id == launcher1_id, "Should return launcher with correct ID"

        # Test finding non-existent launcher
        result = manager.get_launcher_by_name("Non-existent")
        assert result is None, "Should return None for non-existent launcher"

        # Test with empty name
        result = manager.get_launcher_by_name("")
        assert result is None, "Should return None for empty name"

        # Test with None
        result = manager.get_launcher_by_name(None)
        assert result is None, "Should return None for None name"

        # Test with whitespace name
        result = manager.get_launcher_by_name("  Test Launcher 1  ")
        assert result is not None, "Should find launcher with trimmed name"

        print("✓ get_launcher_by_name tests passed")


def test_validate_command_syntax():
    """Test validate_command_syntax method."""
    print("Testing validate_command_syntax...")

    manager = LauncherManager()

    # Test valid commands
    valid_commands = [
        "echo hello",
        "nuke $show/$sequence/$shot/scene.nk",
        "cd ${workspace_path} && ls",
        "echo $USER is working on $full_name",
        "python script.py --show=${show} --seq=${sequence}",
    ]

    for cmd in valid_commands:
        is_valid, error = manager.validate_command_syntax(cmd)
        assert is_valid, f"Command '{cmd}' should be valid but got error: {error}"

    # Test invalid commands
    invalid_commands = [
        "",  # Empty command
        "echo $invalid_var",  # Invalid variable
        "echo ${unknown_placeholder}",  # Unknown placeholder
        "echo $show ${invalid}",  # Mixed valid and invalid
    ]

    for cmd in invalid_commands:
        is_valid, error = manager.validate_command_syntax(cmd)
        assert not is_valid, (
            f"Command '{cmd}' should be invalid but was marked as valid"
        )
        assert error is not None, f"Command '{cmd}' should have error message"

    # Test malformed syntax
    malformed_commands = [
        "echo ${unclosed",  # Unclosed brace
        "echo ${}",  # Empty variable name
    ]

    for cmd in malformed_commands:
        is_valid, error = manager.validate_command_syntax(cmd)
        assert not is_valid, f"Malformed command '{cmd}' should be invalid"
        assert error is not None, f"Malformed command '{cmd}' should have error message"

    print("✓ validate_command_syntax tests passed")


def main():
    """Run all tests."""
    print("Running tests for new LauncherManager methods...")

    try:
        test_get_launcher_by_name()
        test_validate_command_syntax()
        print("\n✅ All tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
