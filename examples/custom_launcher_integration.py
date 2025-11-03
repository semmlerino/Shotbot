#!/usr/bin/env python3
"""Example integration of persistent terminal with ShotBot's command system."""

# Standard library imports
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock


# Mock PySide6 for demonstration
sys.modules["PySide6"] = Mock()
sys.modules["PySide6.QtCore"] = Mock()
sys.modules["PySide6.QtCore"].QObject = object
sys.modules["PySide6.QtCore"].Signal = Mock()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Local application imports
# Import the persistent terminal manager
from persistent_terminal_manager import PersistentTerminalManager


@dataclass
class Launcher:
    """Simple launcher configuration for example."""

    name: str
    command: str
    description: str = ""
    category: str = "custom"
    working_directory: str | None = None
    environment_vars: dict[str, str | None] = None
    terminal_title: str | None = None
    persist_terminal: bool = False
    validate_command: bool = True

    def __post_init__(self) -> None:
        if self.environment_vars is None:
            self.environment_vars = {}


class CustomLauncherManager:
    """Manages custom application launchers for ShotBot."""

    def __init__(self) -> None:
        self.persistent_terminal = PersistentTerminalManager()
        self.custom_launchers = {}
        self._load_default_launchers()

    def _load_default_launchers(self) -> None:
        """Load default custom launchers."""

        # ShotBot Debug Launcher
        self.custom_launchers["shotbot_debug"] = Launcher(
            name="ShotBot Debug Mode",
            command="rez env PySide6_Essentials pillow Jinja2 -- python3 '{shotbot_path}' --debug --shot={full_name}",
            description="Launch ShotBot with debug logging in shot context",
            category="debug",
            terminal_title="ShotBot Debug - {full_name}",
            persist_terminal=True,
            validate_command=False,  # Skip validation for rez commands
        )

        # Custom Nuke with Plugins
        self.custom_launchers["nuke_custom"] = Launcher(
            name="Nuke (Custom Build)",
            command="rez env nuke-13.2.1 my_nuke_plugins -- nuke '{nuke_script}'",
            description="Launch custom Nuke build with studio plugins",
            category="compositing",
            working_directory="{workspace_path}",
            environment_vars={
                "NUKE_PATH": "/studio/nuke/plugins",
                "OCIO": "/studio/config/aces_1.2/config.ocio",
            },
            terminal_title="Nuke Custom - {full_name}",
            persist_terminal=False,
        )

        # Plate Validator
        self.custom_launchers["plate_validator"] = Launcher(
            name="Plate Sequence Validator",
            command="python3 /studio/tools/plate_validator.py --shot='{workspace_path}' --sequence='{full_name}'",
            description="Validate plate sequences for missing frames and consistency",
            category="pipeline",
            working_directory="{workspace_path}",
            terminal_title="Plate Validation - {full_name}",
            persist_terminal=True,
        )

        # Render Submit Tool
        self.custom_launchers["render_submit"] = Launcher(
            name="Submit Render Job",
            command="/studio/tools/render_submit.py --shot={workspace_path} --frames={frame_range} --priority=50",
            description="Submit shot for farm rendering",
            category="rendering",
            environment_vars={
                "SHOT_ROOT": "{workspace_path}",
                "CURRENT_SHOT": "{full_name}",
                "RENDER_TIMESTAMP": "{timestamp}",
            },
            terminal_title="Render Submit - {full_name}",
            persist_terminal=True,
        )

        # Maya Scene Setup
        self.custom_launchers["maya_setup"] = Launcher(
            name="Maya with Scene Setup",
            command="rez env maya-2024 -- maya -script '/studio/maya/setup_shot.mel' -command 'setupShot(\"{full_name}\", \"{workspace_path}\")'",
            description="Launch Maya with automatic shot setup",
            category="modeling",
            working_directory="{workspace_path}",
            terminal_title="Maya Setup - {full_name}",
            persist_terminal=False,
        )

        # Generic Shell in Shot Context
        self.custom_launchers["shell_context"] = Launcher(
            name="Shell in Shot Context",
            command="echo 'Working in shot: {full_name}' && echo 'Path: {workspace_path}' && bash",
            description="Open shell with shot environment variables set",
            category="utility",
            working_directory="{workspace_path}",
            environment_vars={
                "SHOT_NAME": "{full_name}",
                "SHOT_PATH": "{workspace_path}",
                "SHOW": "{show}",
                "SEQUENCE": "{sequence}",
                "SHOT": "{shot}",
            },
            terminal_title="Shell - {full_name}",
            persist_terminal=True,
        )

    def get_launcher_categories(self) -> dict[str, list[tuple[str, Any]]]:
        """Get all launcher categories."""
        categories = {}
        for launcher_id, launcher in self.custom_launchers.items():
            category = launcher.category
            if category not in categories:
                categories[category] = []
            categories[category].append((launcher_id, launcher))
        return categories

    def execute_custom_launcher(
        self, launcher_id: str, shot_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a custom launcher with shot context.

        Args:
            launcher_id: ID of the launcher to execute
            shot_context: Dictionary with shot information
                - show: Show name
                - sequence: Sequence name
                - shot: Shot name
                - full_name: Full shot name (sequence_shot)
                - workspace_path: Full workspace path

        Returns:
            Dictionary with execution result
        """
        if launcher_id not in self.custom_launchers:
            return {
                "success": False,
                "error_message": f"Unknown custom launcher: {launcher_id}",
            }

        launcher = self.custom_launchers[launcher_id]

        # Build variables for substitution
        variables = shot_context.copy()

        # Add additional useful variables
        variables.update(
            {
                "user": os.environ.get("USER", "unknown"),
                "home": str(Path.home()),
                "shotbot_path": "/path/to/shotbot.py",  # Would be configured
                "nuke_script": f"{shot_context['workspace_path']}/comp/{shot_context['full_name']}_comp_v001.nk",
                "frame_range": "1001-1100",  # Would be detected from shot
            },
        )

        # Substitute variables in command
        command = self._substitute_variables(launcher.command, variables)

        # Execute using persistent terminal
        try:
            if launcher.persist_terminal or self.persistent_terminal.is_alive():
                # Use persistent terminal
                self.persistent_terminal.send_command(command)
                return {
                    "success": True,
                    "command": command,
                    "terminal": "persistent",
                }
            # Start new terminal with command
            if self.persistent_terminal.start():
                self.persistent_terminal.send_command(command)
                return {
                    "success": True,
                    "command": command,
                    "terminal": "new_persistent",
                }
            return {
                "success": False,
                "error_message": "Failed to start terminal",
            }
        except Exception as e:
            return {
                "success": False,
                "error_message": str(e),
            }

    def add_custom_launcher(self, launcher_id: str, launcher: Launcher) -> None:
        """Add a new custom launcher."""
        self.custom_launchers[launcher_id] = launcher

    def remove_custom_launcher(self, launcher_id: str) -> bool:
        """Remove a custom launcher."""
        if launcher_id in self.custom_launchers:
            del self.custom_launchers[launcher_id]
            return True
        return False

    def _substitute_variables(self, command: str, variables: dict[str, Any]) -> str:
        """Substitute variables in command string."""
        result = command
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result

    def get_available_terminals(self) -> list[str]:
        """Get available terminal emulators."""
        # Return info about persistent terminal status
        if self.persistent_terminal.is_alive():
            return ["Persistent terminal (active)"]
        return ["Persistent terminal (not started)"]


def demo_integration() -> None:
    """Demonstrate the custom launcher integration."""
    print("🎬 ShotBot Custom Launcher Integration Demo\n")

    # Create the manager
    manager = CustomLauncherManager()

    print("📋 Available Custom Launchers:")
    categories = manager.get_launcher_categories()

    for category, launchers in categories.items():
        print(f"\n  📁 {category.title()}:")
        for _launcher_id, launcher in launchers:
            print(f"    • {launcher.name}")
            print(f"      {launcher.description}")
            print(f"      Command: {launcher.command}")

    print(f"\n🖥️  Available Terminals: {manager.get_available_terminals()}")

    # Example shot context (like what ShotBot would provide)
    shot_context = {
        "show": "demo_show",
        "sequence": "seq01",
        "shot": "shot010",
        "full_name": "seq01_shot010",
        "workspace_path": "/shows/demo_show/shots/seq01/seq01_shot010",
    }

    print("\n🎯 Example Shot Context:")
    for key, value in shot_context.items():
        print(f"    {key}: {value}")

    print("\n🚀 Simulated Launcher Executions:")

    # Test each launcher (simulation only)
    for launcher_id in ["shotbot_debug", "plate_validator", "shell_context"]:
        launcher = manager.custom_launchers[launcher_id]
        print(f"\n  Testing: {launcher.name}")

        # Show what the command would look like after variable substitution
        variables = shot_context.copy()
        variables.update(
            {
                "user": "demo_user",
                "shotbot_path": "/path/to/shotbot.py",
                "timestamp": datetime.now(tz=UTC).strftime("%Y-%m-%d_%H-%M-%S"),
            },
        )

        substituted_command = manager._substitute_variables(
            launcher.command,
            variables,
        )
        print(f"    Original: {launcher.command}")
        print(f"    Substituted: {substituted_command}")

        # In real usage, you would call:
        # result = manager.execute_custom_launcher(launcher_id, shot_context)
        # if result.success:
        #     print(f"    ✅ Launched with PID: {result.process_id}")
        # else:
        #     print(f"    ❌ Failed: {result.error_message}")

    print("\n📖 Integration with CommandLauncher:")
    print("""
# In command_launcher.py, you would extend it like this:

class CommandLauncher(QObject):
    def __init__(self):
        super().__init__()
        self.current_shot = None
        self.custom_launcher_manager = CustomLauncherManager()

    def launch_custom_app(self, launcher_id):
        \"\"\"Launch a custom application.\"\"\"
        if not self.current_shot:
            self._emit_error("No shot selected")
            return False

        # Build shot context
        shot_context = {
            "show": self.current_shot.show,
            "sequence": self.current_shot.sequence,
            "shot": self.current_shot.shot,
            "full_name": self.current_shot.full_name,
            "workspace_path": self.current_shot.workspace_path
        }

        # Execute the custom launcher
        result = self.custom_launcher_manager.execute_custom_launcher(
            launcher_id, shot_context
        )

        if result.success:
            timestamp = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
            self.command_executed.emit(timestamp, result.command)
            return True
        else:
            self._emit_error(f"Custom launcher failed: {result.error_message}")
            return False
    """)

    print("\n✅ Integration demo completed!")


if __name__ == "__main__":
    # Create examples directory if it doesn't exist
    Path(__file__).resolve().parent.mkdir(parents=True, exist_ok=True)
    demo_integration()
