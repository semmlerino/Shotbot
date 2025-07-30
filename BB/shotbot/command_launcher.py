"""Command launcher for executing applications in shot context."""

import subprocess
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal

from config import Config
from raw_plate_finder import RawPlateFinder
from shot_model import Shot
from undistortion_finder import UndistortionFinder


class CommandLauncher(QObject):
    """Handles launching applications in shot context."""

    # Signals
    command_executed = Signal(str, str)  # timestamp, command
    command_error = Signal(str, str)  # timestamp, error

    def __init__(self):
        super().__init__()
        self.current_shot: Optional[Shot] = None

    def set_current_shot(self, shot: Optional[Shot]):
        """Set the current shot context."""
        self.current_shot = shot

    def launch_app(
        self,
        app_name: str,
        include_undistortion: bool = False,
        include_raw_plate: bool = False,
    ) -> bool:
        """Launch an application in the current shot context.

        Args:
            app_name: Name of the application to launch
            include_undistortion: Whether to include undistortion nodes (Nuke only)
            include_raw_plate: Whether to include raw plate Read node (Nuke only)

        Returns:
            True if launch was successful, False otherwise
        """
        if not self.current_shot:
            self._emit_error("No shot selected")
            return False

        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Handle raw plate for Nuke
        if app_name == "nuke" and include_raw_plate:
            raw_plate_path = RawPlateFinder.find_latest_raw_plate(
                self.current_shot.workspace_path, self.current_shot.full_name
            )

            if raw_plate_path:
                # Verify at least one frame exists
                if RawPlateFinder.verify_plate_exists(raw_plate_path):
                    # Include the raw plate in the Nuke command
                    command = f"{command} {raw_plate_path}"
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    version = RawPlateFinder.get_version_from_path(raw_plate_path)
                    self.command_executed.emit(
                        timestamp,
                        f"Found raw plate: {version}/{raw_plate_path.split('/')[-1]}",
                    )
                else:
                    # Log warning if plate path found but no frames exist
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self.command_executed.emit(
                        timestamp, "Warning: Raw plate path found but no frames exist"
                    )
            else:
                # Log warning if raw plate requested but not found
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.command_executed.emit(
                    timestamp, "Warning: Raw plate not found for this shot"
                )

        # Handle undistortion for Nuke
        if app_name == "nuke" and include_undistortion:
            undistortion_path = UndistortionFinder.find_latest_undistortion(
                self.current_shot.workspace_path, self.current_shot.full_name
            )

            if undistortion_path:
                # Include the undistortion file in the Nuke command
                command = f"{command} {undistortion_path}"
                timestamp = datetime.now().strftime("%H:%M:%S")
                version = UndistortionFinder.get_version_from_path(undistortion_path)
                self.command_executed.emit(
                    timestamp,
                    f"Found undistortion file: {version}/{undistortion_path.name}",
                )
            else:
                # Log warning if undistortion requested but not found
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.command_executed.emit(
                    timestamp, "Warning: Undistortion file not found for this shot"
                )

        # Build full command with ws (workspace setup)
        full_command = f"ws {self.current_shot.workspace_path} && {command}"

        # Log the command
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_executed.emit(timestamp, full_command)

        try:
            # Execute in a new terminal
            # This will work on Linux with common terminal emulators
            terminal_commands = [
                # Try gnome-terminal first with interactive bash
                ["gnome-terminal", "--", "bash", "-i", "-c", full_command],
                # Try xterm as fallback with interactive bash
                [
                    "xterm",
                    "-e",
                    f"bash -i -c '{full_command}; read -p \"Press Enter to close...\"'",
                ],
                # Try konsole with interactive bash
                ["konsole", "-e", "bash", "-i", "-c", full_command],
            ]

            for term_cmd in terminal_commands:
                try:
                    subprocess.Popen(term_cmd)
                    return True
                except FileNotFoundError:
                    continue

            # If no terminal worked, try direct execution with interactive bash
            subprocess.Popen(["/bin/bash", "-i", "-c", full_command])
            return True

        except Exception as e:
            self._emit_error(f"Failed to launch {app_name}: {str(e)}")
            return False

    def _emit_error(self, error: str):
        """Emit error with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_error.emit(timestamp, error)
