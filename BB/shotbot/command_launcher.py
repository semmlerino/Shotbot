"""Command launcher for executing applications in shot context."""

import subprocess
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal

from config import Config
from raw_plate_finder import RawPlateFinder
from shot_model import Shot
from threede_scene_model import ThreeDEScene
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

        # Handle raw plate and undistortion for Nuke (integrated approach)
        if app_name == "nuke" and (include_raw_plate or include_undistortion):
            raw_plate_path = None
            undistortion_path = None

            # Get raw plate if requested
            if include_raw_plate:
                raw_plate_path = RawPlateFinder.find_latest_raw_plate(
                    self.current_shot.workspace_path, self.current_shot.full_name
                )
                # Verify plate exists
                if raw_plate_path and not RawPlateFinder.verify_plate_exists(
                    raw_plate_path
                ):
                    raw_plate_path = None

            # Get undistortion if requested
            if include_undistortion:
                undistortion_path = UndistortionFinder.find_latest_undistortion(
                    self.current_shot.workspace_path, self.current_shot.full_name
                )

            # Generate integrated Nuke script if we have plate or undistortion
            if raw_plate_path or undistortion_path:
                from nuke_script_generator import NukeScriptGenerator

                if raw_plate_path and undistortion_path:
                    # Both plate and undistortion
                    script_path = (
                        NukeScriptGenerator.create_plate_script_with_undistortion(
                            raw_plate_path,
                            str(undistortion_path),
                            self.current_shot.full_name,
                        )
                    )
                    if script_path:
                        command = f"{command} {script_path}"
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        plate_version = RawPlateFinder.get_version_from_path(
                            raw_plate_path
                        )
                        undist_version = UndistortionFinder.get_version_from_path(
                            undistortion_path
                        )
                        self.command_executed.emit(
                            timestamp,
                            f"Generated Nuke script with plate ({plate_version}) and undistortion ({undist_version})",
                        )
                    else:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        self.command_executed.emit(
                            timestamp,
                            "Error: Failed to generate integrated Nuke script",
                        )
                elif raw_plate_path:
                    # Plate only
                    script_path = NukeScriptGenerator.create_plate_script(
                        raw_plate_path, self.current_shot.full_name
                    )
                    if script_path:
                        command = f"{command} {script_path}"
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        version = RawPlateFinder.get_version_from_path(raw_plate_path)
                        self.command_executed.emit(
                            timestamp, f"Generated Nuke script with plate: {version}"
                        )
                    else:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        self.command_executed.emit(
                            timestamp, "Error: Failed to generate plate script"
                        )
                elif undistortion_path:
                    # Undistortion only (no plate available)
                    script_path = (
                        NukeScriptGenerator.create_plate_script_with_undistortion(
                            "",
                            str(undistortion_path),
                            self.current_shot.full_name,  # Empty plate path
                        )
                    )
                    if script_path:
                        command = f"{command} {script_path}"
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        version = UndistortionFinder.get_version_from_path(
                            undistortion_path
                        )
                        self.command_executed.emit(
                            timestamp,
                            f"Generated Nuke script with undistortion: {version}",
                        )
                    else:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        self.command_executed.emit(
                            timestamp, "Error: Failed to generate undistortion script"
                        )
            else:
                # Log warnings for missing files
                timestamp = datetime.now().strftime("%H:%M:%S")
                if include_raw_plate:
                    self.command_executed.emit(
                        timestamp,
                        "Warning: Raw plate not found or no frames exist for this shot",
                    )
                if include_undistortion:
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

    def launch_app_with_scene(self, app_name: str, scene: ThreeDEScene) -> bool:
        """Launch an application with a specific 3DE scene file.

        Args:
            app_name: Name of the application to launch
            scene: The 3DE scene to open

        Returns:
            True if launch was successful, False otherwise
        """
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Include the scene file in the command
        command = f"{command} {scene.scene_path}"

        # Build full command with ws (workspace setup)
        full_command = f"ws {scene.workspace_path} && {command}"

        # Log the command
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_executed.emit(
            timestamp, f"{full_command} (Scene by: {scene.user}, Plate: {scene.plate})"
        )

        try:
            # Execute in a new terminal
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
            self._emit_error(f"Failed to launch {app_name} with scene: {str(e)}")
            return False

    def launch_app_with_scene_context(
        self,
        app_name: str,
        scene: ThreeDEScene,
        include_undistortion: bool = False,
        include_raw_plate: bool = False,
    ) -> bool:
        """Launch an application in the context of a 3DE scene (shot context only, no scene file).

        Args:
            app_name: Name of the application to launch
            scene: The 3DE scene providing shot context
            include_undistortion: Whether to include undistortion nodes (Nuke only)
            include_raw_plate: Whether to include raw plate Read node (Nuke only)

        Returns:
            True if launch was successful, False otherwise
        """
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Get the command
        command = Config.APPS[app_name]

        # Handle raw plate for Nuke
        if app_name == "nuke" and include_raw_plate:
            raw_plate_path = RawPlateFinder.find_latest_raw_plate(
                scene.workspace_path, scene.full_name
            )

            if raw_plate_path:
                # Verify at least one frame exists
                if RawPlateFinder.verify_plate_exists(raw_plate_path):
                    # Create a Nuke script with the plate loaded
                    from nuke_script_generator import NukeScriptGenerator

                    script_path = NukeScriptGenerator.create_plate_script(
                        raw_plate_path, scene.full_name
                    )

                    if script_path:
                        # Launch Nuke with the generated script
                        command = f"{command} {script_path}"
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        version = RawPlateFinder.get_version_from_path(raw_plate_path)
                        self.command_executed.emit(
                            timestamp,
                            f"Created Nuke script with plate: {version}/{raw_plate_path.split('/')[-1]}",
                        )
                    else:
                        # Fallback to just passing the path
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
                scene.workspace_path, scene.full_name
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
        full_command = f"ws {scene.workspace_path} && {command}"

        # Log the command
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_executed.emit(
            timestamp, f"{full_command} (Context: {scene.user}'s {scene.plate})"
        )

        try:
            # Execute in a new terminal
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
            self._emit_error(f"Failed to launch {app_name} in scene context: {str(e)}")
            return False

    def _emit_error(self, error: str):
        """Emit error with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_error.emit(timestamp, error)
