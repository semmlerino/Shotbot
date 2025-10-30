"""Command launcher for executing applications in shot context."""

from __future__ import annotations

# Standard library imports
import os
import shutil
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

# Third-party imports
from PySide6.QtCore import QObject, Signal

# Local application imports
from config import Config
from logging_mixin import LoggingMixin
from nuke_launch_router import NukeLaunchRouter

if TYPE_CHECKING:
    # Local application imports
    from maya_latest_finder import MayaLatestFinder as MayaLatestFinderType
    from nuke_script_generator import NukeScriptGenerator as NukeScriptGeneratorType
    from persistent_terminal_manager import PersistentTerminalManager
    from raw_plate_finder import RawPlateFinder as RawPlateFinderType
    from shot_model import Shot
    from threede_latest_finder import ThreeDELatestFinder as ThreeDELatestFinderType
    from threede_scene_model import ThreeDEScene
    from undistortion_finder import UndistortionFinder as UndistortionFinderType
else:
    # Import at runtime to avoid circular imports
    # Local application imports
    pass


class CommandLauncher(LoggingMixin, QObject):
    """Handles launching applications in shot context.

    This class uses dependency injection for better testability and following SOLID principles.
    Dependencies are passed as constructor parameters rather than imported directly.
    """

    # Signals
    command_executed = Signal(str, str)  # timestamp, command
    command_error = Signal(str, str)  # timestamp, error

    def __init__(
        self,
        raw_plate_finder: type[RawPlateFinderType] | None = None,
        undistortion_finder: type[UndistortionFinderType] | None = None,
        nuke_script_generator: type[NukeScriptGeneratorType] | None = None,
        threede_latest_finder: type[ThreeDELatestFinderType] | None = None,
        maya_latest_finder: type[MayaLatestFinderType] | None = None,
        persistent_terminal: PersistentTerminalManager | None = None,
    ) -> None:
        """Initialize CommandLauncher with optional dependencies.

        Args:
            raw_plate_finder: Class for finding raw plates (defaults to RawPlateFinder)
            undistortion_finder: Class for finding undistortion files (defaults to UndistortionFinder)
            nuke_script_generator: Class for generating Nuke scripts (defaults to NukeScriptGenerator)
            threede_latest_finder: Class for finding latest 3DE scenes (defaults to ThreeDELatestFinder)
            maya_latest_finder: Class for finding latest Maya scenes (defaults to MayaLatestFinder)
            persistent_terminal: Optional persistent terminal manager for single terminal mode
        """
        super().__init__()
        self.current_shot: Shot | None = None
        self.persistent_terminal = persistent_terminal

        # Cache fields for expensive operations
        self._rez_available: bool | None = None
        self._available_terminal: str | None = None

        # Initialize the Nuke launch handler
        self.nuke_handler = NukeLaunchRouter()

        # Use injected dependencies or fall back to defaults
        # Note: These are now deprecated and will be removed in the next phase
        # They're kept for backward compatibility with other methods
        if raw_plate_finder is None:
            # Local application imports
            from raw_plate_finder import RawPlateFinder

            self._raw_plate_finder = RawPlateFinder
        else:
            self._raw_plate_finder = raw_plate_finder

        if undistortion_finder is None:
            # Local application imports
            from undistortion_finder import UndistortionFinder

            self._undistortion_finder = UndistortionFinder
        else:
            self._undistortion_finder = undistortion_finder

        if nuke_script_generator is None:
            # Local application imports
            from nuke_script_generator import NukeScriptGenerator

            self._nuke_script_generator = NukeScriptGenerator
        else:
            self._nuke_script_generator = nuke_script_generator

        if threede_latest_finder is None:
            # Local application imports
            from threede_latest_finder import ThreeDELatestFinder

            self._threede_latest_finder = ThreeDELatestFinder()
        else:
            self._threede_latest_finder = threede_latest_finder()

        if maya_latest_finder is None:
            # Local application imports
            from maya_latest_finder import MayaLatestFinder

            self._maya_latest_finder = MayaLatestFinder()
        else:
            self._maya_latest_finder = maya_latest_finder()

    def set_current_shot(self, shot: Shot | None) -> None:
        """Set the current shot context."""
        self.current_shot = shot

    def _is_rez_available(self) -> bool:
        """Check if rez environment is available.

        Returns:
            True if rez is available and should be used
        """
        if not Config.USE_REZ_ENVIRONMENT:
            return False

        # Check for REZ_USED environment variable (indicates we're in a rez env)
        if Config.REZ_AUTO_DETECT and os.environ.get("REZ_USED"):
            return True

        # Return cached result if available
        if self._rez_available is not None:
            return self._rez_available

        # Check if rez command is available
        self._rez_available = shutil.which("rez") is not None
        self.logger.debug(f"Rez availability cached: {self._rez_available}")
        return self._rez_available

    def _clear_rez_cache(self) -> None:
        """Clear the rez availability cache (for testing)."""
        self._rez_available = None

    def _clear_terminal_cache(self) -> None:
        """Clear the terminal detection cache (for testing and error recovery)."""
        self._available_terminal = None

    def _get_rez_packages_for_app(self, app_name: str) -> list[str]:
        """Get rez packages for the specified application.

        Args:
            app_name: Name of the application

        Returns:
            List of rez packages to load
        """
        package_map = {
            "nuke": Config.REZ_NUKE_PACKAGES,
            "maya": Config.REZ_MAYA_PACKAGES,
            "3de": Config.REZ_3DE_PACKAGES,
        }
        return package_map.get(app_name, [])

    def _detect_available_terminal(self) -> str | None:
        """Detect available terminal emulator.

        Returns:
            Name of available terminal emulator, or None if none found
        """
        # Return cached result if available
        if self._available_terminal is not None:
            return self._available_terminal

        # Check terminals in order of preference
        terminals = ["gnome-terminal", "konsole", "xterm", "x-terminal-emulator"]
        for term in terminals:
            if shutil.which(term) is not None:
                self._available_terminal = term
                self.logger.info(f"Detected terminal: {term}")
                return term

        # No terminal found
        self.logger.warning("No terminal emulator found")
        return None

    def _validate_path_for_shell(self, path: str) -> str:
        """Validate and escape a path for safe use in shell commands.

        Args:
            path: Path to validate and escape

        Returns:
            Safely escaped path string

        Raises:
            ValueError: If path contains dangerous characters that cannot be escaped
        """
        # Standard library imports
        import shlex

        # Check for command injection attempts
        dangerous_chars = [
            ";",
            "&&",
            "||",
            "|",  # Command separators
            ">",
            "<",
            ">>",
            ">&",  # Redirections
            "`",
            "$(",  # Command substitution
            "\n",
            "\r",  # Newlines that could break out
            "${",
            "$((",  # Variable/arithmetic expansion
        ]

        for char in dangerous_chars:
            if char in path:
                raise ValueError(
                    f"Path contains dangerous character '{char}' that could allow command injection: {path[:100]}"
                )

        # Additional validation for known dangerous patterns
        dangerous_patterns = [
            "../",  # Path traversal
            "/..",  # Path traversal variant
            "~/.",  # Hidden file access attempts
        ]

        for pattern in dangerous_patterns:
            if pattern in path:
                raise ValueError(
                    f"Path contains dangerous pattern '{pattern}': {path[:100]}"
                )

        # Use shlex.quote for safe shell escaping
        # This adds single quotes around the string and escapes any single quotes within
        return shlex.quote(path)

    # Method removed - now using NukeLaunchHandler.get_environment_fixes()

    def launch_app(
        self,
        app_name: str,
        include_undistortion: bool = False,
        include_raw_plate: bool = False,
        open_latest_threede: bool = False,
        open_latest_maya: bool = False,
        open_latest_scene: bool = False,
        create_new_file: bool = False,
        selected_plate: str | None = None,
    ) -> bool:
        """Launch an application in the current shot context.

        Args:
            app_name: Name of the application to launch
            include_undistortion: Whether to include undistortion nodes (Nuke only)
            include_raw_plate: Whether to include raw plate Read node (Nuke only)
            open_latest_threede: Whether to open the latest 3DE scene file (3DE only)
            open_latest_maya: Whether to open the latest Maya scene file (Maya only)
            open_latest_scene: Whether to open the latest Nuke script (Nuke only)
            create_new_file: Whether to create a new version (Nuke only)
            selected_plate: Selected plate space for Nuke workspace scripts (e.g., "FG01", "BG01")

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

        # Handle Nuke-specific launching logic
        if app_name == "nuke":
            # Use the unified Nuke handler for all Nuke-specific logic
            options = {
                "open_latest_scene": open_latest_scene,
                "create_new_file": create_new_file,
                "include_raw_plate": include_raw_plate,
                "include_undistortion": include_undistortion,
            }

            command, log_messages = self.nuke_handler.prepare_nuke_command(
                self.current_shot, command, options, selected_plate=selected_plate
            )

            # Emit log messages
            timestamp = datetime.now().strftime("%H:%M:%S")
            for msg in log_messages:
                self.command_executed.emit(timestamp, msg)

        # Old Nuke handling code has been removed - see NukeLaunchHandler

        # Handle 3DE with latest scene file
        if app_name == "3de" and open_latest_threede:
            latest_scene = self._threede_latest_finder.find_latest_threede_scene(
                self.current_shot.workspace_path,
                self.current_shot.full_name,
            )
            if latest_scene:
                # Add the scene file to the command
                try:
                    safe_scene_path = self._validate_path_for_shell(str(latest_scene))
                    command = f"{command} -open {safe_scene_path}"
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self.command_executed.emit(
                        timestamp,
                        f"Opening latest 3DE scene: {latest_scene.name}",
                    )
                except ValueError as e:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self.command_executed.emit(
                        timestamp,
                        f"Warning: Invalid 3DE scene path: {e!s}",
                    )
            else:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.command_executed.emit(
                    timestamp,
                    "Info: No 3DE scene files found in workspace",
                )

        # Handle Maya with latest scene file
        if app_name == "maya" and open_latest_maya:
            latest_scene = self._maya_latest_finder.find_latest_maya_scene(
                self.current_shot.workspace_path,
                self.current_shot.full_name,
            )
            if latest_scene:
                # Add the scene file to the command
                try:
                    safe_scene_path = self._validate_path_for_shell(str(latest_scene))
                    command = f"{command} -file {safe_scene_path}"
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self.command_executed.emit(
                        timestamp,
                        f"Opening latest Maya scene: {latest_scene.name}",
                    )
                except ValueError as e:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self.command_executed.emit(
                        timestamp,
                        f"Warning: Invalid Maya scene path: {e!s}",
                    )
            else:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.command_executed.emit(
                    timestamp,
                    "Info: No Maya scene files found in workspace",
                )

        # Build full command with ws (workspace setup)
        # Validate and escape workspace path to prevent injection
        try:
            safe_workspace_path = self._validate_path_for_shell(
                self.current_shot.workspace_path
            )

            # Apply Nuke environment fixes if needed
            env_fixes = ""
            if app_name == "nuke":
                env_fixes = self.nuke_handler.get_environment_fixes()
                if env_fixes:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    fix_details: list[str] = []
                    if Config.NUKE_SKIP_PROBLEMATIC_PLUGINS:
                        fix_details.append("runtime NUKE_PATH filtering")
                    if Config.NUKE_OCIO_FALLBACK_CONFIG:
                        fix_details.append("OCIO fallback")
                    fix_details.append("crash reporting disabled")

                    self.command_executed.emit(
                        timestamp,
                        f"Applied environment fixes to prevent Nuke crashes: {', '.join(fix_details)}",
                    )

            # Build base command WITHOUT background operator
            # We'll add & only when actually sending to persistent terminal
            ws_command = f"ws {safe_workspace_path} && {env_fixes}{command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        # Wrap with rez environment if available
        if self._is_rez_available():
            rez_packages = self._get_rez_packages_for_app(app_name)
            if rez_packages:
                packages_str = " ".join(rez_packages)
                # Use bash -ilc for interactive login shell to ensure shell functions like ws are loaded
                # The -i flag is crucial for loading shell functions from configuration files
                full_command = f'rez env {packages_str} -- bash -ilc "{ws_command}"'
                self.logger.debug(
                    f"Constructed rez command with bash -ilc: {full_command}"
                )
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.command_executed.emit(
                    timestamp, f"Using rez environment with packages: {packages_str}"
                )
            else:
                full_command = ws_command
        else:
            full_command = ws_command

        # Log the command to UI
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_executed.emit(timestamp, full_command)

        # Enhanced debug logging for command integrity verification
        self.logger.debug(
            f"Constructed command for {app_name}:\n"
            f"  Command: {full_command!r}\n"
            f"  Length: {len(full_command)} chars\n"
            f"  Workspace: {self.current_shot.workspace_path if self.current_shot else 'None'}\n"
            f"  Shot: {self.current_shot.full_name if self.current_shot else 'None'}"
        )

        # Use persistent terminal if available and enabled
        if (
            self.persistent_terminal
            and Config.PERSISTENT_TERMINAL_ENABLED
            and Config.USE_PERSISTENT_TERMINAL
        ):
            # Add & for GUI apps when using persistent terminal
            command_to_send = full_command
            if Config.AUTO_BACKGROUND_GUI_APPS and self._is_gui_app(app_name):
                # For rez commands, add & inside the quoted bash command
                if "bash -ilc" in full_command:
                    # Command is like: rez env nuke -- bash -ilc "ws /path && nuke"
                    # We need to add & inside the quotes
                    command_to_send = full_command.rstrip('"') + ' &"'
                else:
                    command_to_send = full_command + " &"
                self.logger.debug(
                    f"Added & for GUI app {app_name} in persistent terminal"
                )

            self.logger.info(
                f"Sending command to persistent terminal: {command_to_send}"
            )
            self.logger.debug(
                f"Command details:\n"
                f"  Original: {full_command!r}\n"
                f"  To send: {command_to_send!r}\n"
                f"  Is GUI app: {self._is_gui_app(app_name)}\n"
                f"  Auto-background: {Config.AUTO_BACKGROUND_GUI_APPS}"
            )

            success = self.persistent_terminal.send_command(command_to_send)
            if success:
                self.logger.debug("Command successfully sent to persistent terminal")
                return True
            self.logger.warning(
                "Failed to send command to persistent terminal, falling back to new terminal"
            )
            # Emit user-friendly message about fallback
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.command_executed.emit(
                timestamp,
                "⚠ Persistent terminal not available, launching in new terminal...",
            )
            # Fall through to launch new terminal - WITHOUT the & operator

        # Launch in new terminal (original behavior)
        # Pre-check for available terminal
        terminal = self._detect_available_terminal()
        if terminal is None:
            self._emit_error(
                "No terminal emulator found (checked: gnome-terminal, konsole, xterm, x-terminal-emulator)"
            )
            return False

        try:
            # Build command for the detected terminal
            if terminal == "gnome-terminal":
                term_cmd = ["gnome-terminal", "--", "bash", "-i", "-c", full_command]
            elif terminal == "konsole":
                term_cmd = ["konsole", "-e", "bash", "-i", "-c", full_command]
            elif terminal in ["xterm", "x-terminal-emulator"]:
                term_cmd = [terminal, "-e", "bash", "-i", "-c", full_command]
            else:
                # Fallback to direct execution
                term_cmd = ["/bin/bash", "-i", "-c", full_command]

            subprocess.Popen(term_cmd)
            return True

        except Exception as e:
            # Clear cache on failure - terminal may have been uninstalled
            self._available_terminal = None
            self._emit_error(f"Failed to launch {app_name}: {e!s}")
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
        # Validate and escape scene path to prevent injection
        try:
            safe_scene_path = self._validate_path_for_shell(str(scene.scene_path))
            # Add app-specific command-line flags for scene file
            if app_name == "3de":
                command = f"{command} -open {safe_scene_path}"
            elif app_name == "maya":
                command = f"{command} -file {safe_scene_path}"
            else:
                # Nuke and others accept scene file without flag
                command = f"{command} {safe_scene_path}"
        except ValueError as e:
            self._emit_error(f"Invalid scene path: {e!s}")
            return False

        # Build full command with ws (workspace setup)
        # Validate and escape workspace path to prevent injection
        try:
            safe_workspace_path = self._validate_path_for_shell(scene.workspace_path)

            # Apply Nuke environment fixes if needed (same as regular launch)
            env_fixes = ""
            if app_name == "nuke":
                env_fixes = self.nuke_handler.get_environment_fixes()
                if env_fixes:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    fix_details: list[str] = []
                    if Config.NUKE_SKIP_PROBLEMATIC_PLUGINS:
                        fix_details.append("runtime NUKE_PATH filtering")
                    if Config.NUKE_OCIO_FALLBACK_CONFIG:
                        fix_details.append("OCIO fallback")
                    fix_details.append("crash reporting disabled")

                    self.command_executed.emit(
                        timestamp,
                        f"Applied environment fixes for Nuke scene launch: {', '.join(fix_details)}",
                    )

            # Build base command WITHOUT background operator
            # We'll add & only when actually sending to persistent terminal
            ws_command = f"ws {safe_workspace_path} && {env_fixes}{command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        # Wrap with rez environment if available
        if self._is_rez_available():
            rez_packages = self._get_rez_packages_for_app(app_name)
            if rez_packages:
                packages_str = " ".join(rez_packages)
                # Use bash -ilc for interactive login shell to ensure shell functions are loaded
                full_command = f'rez env {packages_str} -- bash -ilc "{ws_command}"'
                self.logger.debug(
                    f"Constructed rez scene command with bash -ilc: {full_command}"
                )
            else:
                full_command = ws_command
        else:
            full_command = ws_command

        # Log the command
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_executed.emit(
            timestamp,
            f"{full_command} (Scene by: {scene.user}, Plate: {scene.plate})",
        )

        # Use persistent terminal if available and enabled
        if (
            self.persistent_terminal
            and Config.PERSISTENT_TERMINAL_ENABLED
            and Config.USE_PERSISTENT_TERMINAL
        ):
            # Add & for GUI apps when using persistent terminal
            command_to_send = full_command
            if Config.AUTO_BACKGROUND_GUI_APPS and self._is_gui_app(app_name):
                # For rez commands, add & inside the quoted bash command
                if "bash -ilc" in full_command:
                    # Command is like: rez env 3de -- bash -ilc "ws /path && 3de /file"
                    # We need to add & inside the quotes
                    command_to_send = full_command.rstrip('"') + ' &"'
                else:
                    command_to_send = full_command + " &"
                self.logger.debug(
                    f"Added & for GUI app {app_name} in persistent terminal"
                )

            self.logger.info(
                f"Sending scene command to persistent terminal: {command_to_send}"
            )
            self.logger.debug(
                f"Is GUI app: {self._is_gui_app(app_name)}, Auto-background: {Config.AUTO_BACKGROUND_GUI_APPS}"
            )

            success = self.persistent_terminal.send_command(command_to_send)
            if success:
                self.logger.debug(
                    "Scene command successfully sent to persistent terminal"
                )
                return True
            self.logger.warning(
                "Failed to send command to persistent terminal, falling back to new terminal"
            )
            # Emit user-friendly message about fallback
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.command_executed.emit(
                timestamp,
                "⚠ Persistent terminal not available, launching in new terminal...",
            )
            # Fall through to launch new terminal - WITHOUT the & operator

        # Launch in new terminal (original behavior)
        # Pre-check for available terminal
        terminal = self._detect_available_terminal()
        if terminal is None:
            self._emit_error(
                "No terminal emulator found (checked: gnome-terminal, konsole, xterm, x-terminal-emulator)"
            )
            return False

        try:
            # Build command for the detected terminal
            if terminal == "gnome-terminal":
                term_cmd = ["gnome-terminal", "--", "bash", "-i", "-c", full_command]
            elif terminal == "konsole":
                term_cmd = ["konsole", "-e", "bash", "-i", "-c", full_command]
            elif terminal in ["xterm", "x-terminal-emulator"]:
                term_cmd = [terminal, "-e", "bash", "-i", "-c", full_command]
            else:
                # Fallback to direct execution
                term_cmd = ["/bin/bash", "-i", "-c", full_command]

            subprocess.Popen(term_cmd)
            return True

        except Exception as e:
            # Clear cache on failure - terminal may have been uninstalled
            self._available_terminal = None
            self._emit_error(f"Failed to launch {app_name} with scene: {e!s}")
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
            raw_plate_path = self._raw_plate_finder.find_latest_raw_plate(
                scene.workspace_path,
                scene.full_name,
            )

            if raw_plate_path:
                # Verify at least one frame exists
                if self._raw_plate_finder.verify_plate_exists(raw_plate_path):
                    # Create a Nuke script with the plate loaded
                    script_path = self._nuke_script_generator.create_plate_script(
                        raw_plate_path,
                        scene.full_name,
                    )

                    if script_path:
                        # Launch Nuke with the generated script
                        command = f"{command} {script_path}"
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        version = self._raw_plate_finder.get_version_from_path(
                            raw_plate_path
                        )
                        self.command_executed.emit(
                            timestamp,
                            f"Created Nuke script with plate: {version}/{raw_plate_path.split('/')[-1]}",
                        )
                    else:
                        # Fallback to just passing the path (safely escaped)
                        safe_plate_path = self._validate_path_for_shell(raw_plate_path)
                        command = f"{command} {safe_plate_path}"
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        version = self._raw_plate_finder.get_version_from_path(
                            raw_plate_path
                        )
                        self.command_executed.emit(
                            timestamp,
                            f"Found raw plate: {version}/{raw_plate_path.split('/')[-1]}",
                        )
                else:
                    # Log warning if plate path found but no frames exist
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self.command_executed.emit(
                        timestamp,
                        "Warning: Raw plate path found but no frames exist",
                    )
            else:
                # Log warning if raw plate requested but not found
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.command_executed.emit(
                    timestamp,
                    "Warning: Raw plate not found for this shot",
                )

        # Handle undistortion for Nuke
        if app_name == "nuke" and include_undistortion:
            undistortion_path = self._undistortion_finder.find_latest_undistortion(
                scene.workspace_path,
                scene.full_name,
            )

            if undistortion_path:
                # Include the undistortion file in the Nuke command (safely escaped)
                safe_undistortion_path = self._validate_path_for_shell(
                    str(undistortion_path)
                )
                command = f"{command} {safe_undistortion_path}"
                timestamp = datetime.now().strftime("%H:%M:%S")
                version = self._undistortion_finder.get_version_from_path(
                    undistortion_path
                )
                self.command_executed.emit(
                    timestamp,
                    f"Found undistortion file: {version}/{undistortion_path.name}",
                )
            else:
                # Log warning if undistortion requested but not found
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.command_executed.emit(
                    timestamp,
                    "Warning: Undistortion file not found for this shot",
                )

        # Build full command with ws (workspace setup)
        # Validate and escape workspace path to prevent injection
        try:
            safe_workspace_path = self._validate_path_for_shell(scene.workspace_path)
            full_command = f"ws {safe_workspace_path} && {command}"
        except ValueError as e:
            self._emit_error(f"Invalid workspace path: {e!s}")
            return False

        # Log the command
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_executed.emit(
            timestamp,
            f"{full_command} (Context: {scene.user}'s {scene.plate})",
        )

        # Pre-check for available terminal
        terminal = self._detect_available_terminal()
        if terminal is None:
            self._emit_error(
                "No terminal emulator found (checked: gnome-terminal, konsole, xterm, x-terminal-emulator)"
            )
            return False

        try:
            # Build command for the detected terminal
            if terminal == "gnome-terminal":
                term_cmd = ["gnome-terminal", "--", "bash", "-i", "-c", full_command]
            elif terminal == "konsole":
                term_cmd = ["konsole", "-e", "bash", "-i", "-c", full_command]
            elif terminal in ["xterm", "x-terminal-emulator"]:
                term_cmd = [terminal, "-e", "bash", "-i", "-c", full_command]
            else:
                # Fallback to direct execution
                term_cmd = ["/bin/bash", "-i", "-c", full_command]

            subprocess.Popen(term_cmd)
            return True

        except Exception as e:
            # Clear cache on failure - terminal may have been uninstalled
            self._available_terminal = None
            self._emit_error(f"Failed to launch {app_name} in scene context: {e!s}")
            return False

    def _is_gui_app(self, app_name: str) -> bool:
        """Check if an application is a GUI application.

        Args:
            app_name: Name of the application

        Returns:
            True if the app is a GUI application, False otherwise
        """
        # List of known GUI applications that should run in background
        gui_apps = {
            "3de",
            "nuke",
            "maya",
            "rv",
            "houdini",
            "mari",
            "katana",
            "clarisse",
        }
        return app_name.lower() in gui_apps

    def _emit_error(self, error: str) -> None:
        """Emit error with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_error.emit(timestamp, error)
