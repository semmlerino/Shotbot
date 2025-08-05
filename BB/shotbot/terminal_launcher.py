"""Terminal launcher for executing commands in new terminal windows."""

import logging
import os
import platform
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal

# Set up logger for this module
logger = logging.getLogger(__name__)


@dataclass
class LaunchResult:
    """Result of a launcher execution."""

    success: bool
    command: str = ""
    process_id: Optional[int] = None
    error_message: str = ""
    terminal_type: str = ""


@dataclass
class Launcher:
    """Represents a custom launcher configuration."""

    name: str
    command: str
    description: str = ""
    category: str = "custom"
    working_directory: Optional[str] = None
    environment_vars: Optional[Dict[str, str]] = None
    terminal_title: Optional[str] = None
    terminal_geometry: Optional[str] = None
    persist_terminal: bool = False
    timeout_seconds: int = 30
    validate_command: bool = True


class TerminalLauncher(QObject):
    """Handles launching commands in new terminal windows across platforms."""

    # Signals
    launcher_executed = Signal(str, str, str)  # launcher_name, command, timestamp
    launcher_failed = Signal(str, str, str)  # launcher_name, error, timestamp
    terminal_detected = Signal(str)  # terminal_type

    # Terminal configurations by platform
    LINUX_TERMINALS = [
        "gnome-terminal",
        "konsole",
        "xterm",
        "x-terminal-emulator",
        "alacritty",
        "terminator",
    ]

    MACOS_TERMINALS = [
        "Terminal",
        "iTerm",
    ]

    WINDOWS_TERMINALS = [
        "cmd.exe",
        "powershell.exe",
        "wt.exe",  # Windows Terminal
    ]

    def __init__(self):
        super().__init__()
        self._detected_terminals: List[str] = []
        self._preferred_terminal: Optional[str] = None
        self._platform = platform.system().lower()
        self._detect_available_terminals()

    def _detect_available_terminals(self) -> None:
        """Detect available terminal emulators on the current platform."""
        terminals_to_check = []

        if self._platform == "linux":
            terminals_to_check = self.LINUX_TERMINALS
        elif self._platform == "darwin":
            terminals_to_check = self.MACOS_TERMINALS
        elif self._platform == "windows":
            terminals_to_check = self.WINDOWS_TERMINALS
        else:
            logger.warning(f"Unsupported platform: {self._platform}")
            return

        for terminal in terminals_to_check:
            if self._is_terminal_available(terminal):
                self._detected_terminals.append(terminal)
                logger.debug(f"Detected terminal: {terminal}")

        if self._detected_terminals:
            self._preferred_terminal = self._detected_terminals[0]
            logger.info(f"Using preferred terminal: {self._preferred_terminal}")
            self.terminal_detected.emit(self._preferred_terminal)
        else:
            logger.error(f"No terminal emulators found on {self._platform}")

    def _is_terminal_available(self, terminal: str) -> bool:
        """Check if a terminal emulator is available."""
        try:
            if self._platform == "darwin" and terminal in ["Terminal", "iTerm"]:
                # macOS applications - check if they exist
                app_paths = [
                    f"/Applications/{terminal}.app",
                    f"/System/Applications/{terminal}.app",
                ]
                return any(os.path.exists(path) for path in app_paths)
            else:
                # Unix/Linux/Windows - check if executable is in PATH
                return shutil.which(terminal) is not None
        except Exception as e:
            logger.debug(f"Error checking terminal {terminal}: {e}")
            return False

    def get_available_terminals(self) -> List[str]:
        """Get list of available terminal emulators."""
        return self._detected_terminals.copy()

    def set_preferred_terminal(self, terminal: str) -> bool:
        """Set preferred terminal emulator."""
        if terminal in self._detected_terminals:
            self._preferred_terminal = terminal
            logger.info(f"Set preferred terminal: {terminal}")
            return True
        else:
            logger.error(f"Terminal not available: {terminal}")
            return False

    def execute_launcher(
        self, launcher: Launcher, variables: Optional[Dict[str, str]] = None
    ) -> LaunchResult:
        """Execute a launcher with variable substitution."""
        try:
            # Substitute variables in command
            final_command = self._substitute_variables(
                launcher.command, variables or {}
            )

            # Validate command if requested
            if launcher.validate_command:
                validation_error = self._validate_command(final_command)
                if validation_error:
                    return LaunchResult(
                        success=False,
                        command=final_command,
                        error_message=validation_error,
                    )

            # Build environment variables
            env = os.environ.copy()
            if launcher.environment_vars:
                for key, value in launcher.environment_vars.items():
                    env[key] = self._substitute_variables(value, variables or {})

            # Execute in terminal
            result = self._execute_in_terminal(
                command=final_command,
                working_directory=launcher.working_directory,
                environment=env,
                terminal_title=launcher.terminal_title,
                terminal_geometry=launcher.terminal_geometry,
                persist=launcher.persist_terminal,
                timeout=launcher.timeout_seconds,
            )

            if result.success:
                timestamp = self._get_timestamp()
                self.launcher_executed.emit(launcher.name, final_command, timestamp)
                logger.info(
                    f"Successfully executed launcher '{launcher.name}': {final_command}"
                )
            else:
                timestamp = self._get_timestamp()
                self.launcher_failed.emit(
                    launcher.name, result.error_message, timestamp
                )
                logger.error(
                    f"Failed to execute launcher '{launcher.name}': {result.error_message}"
                )

            return result

        except Exception as e:
            error_msg = f"Exception executing launcher: {str(e)}"
            logger.exception(error_msg)
            timestamp = self._get_timestamp()
            self.launcher_failed.emit(launcher.name, error_msg, timestamp)
            return LaunchResult(
                success=False, command=launcher.command, error_message=error_msg
            )

    def _substitute_variables(self, text: str, variables: Dict[str, str]) -> str:
        """Substitute variables in text using {variable_name} syntax."""
        try:
            # Built-in variables
            builtin_vars = {
                "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
                "home": str(Path.home()),
                "timestamp": self._get_timestamp(),
                "date": self._get_timestamp().split("_")[0],
                "time": self._get_timestamp().split("_")[1].replace("-", ":"),
            }

            # Merge variables (user variables override built-ins)
            all_vars = {**builtin_vars, **variables}

            # Perform substitution
            result = text
            for key, value in all_vars.items():
                result = result.replace(f"{{{key}}}", str(value))

            return result

        except Exception as e:
            logger.error(f"Error substituting variables in '{text}': {e}")
            return text

    def _validate_command(self, command: str) -> Optional[str]:
        """Validate a command for basic security and availability."""
        try:
            # Split command to get the executable
            parts = shlex.split(command)
            if not parts:
                return "Empty command"

            executable = parts[0]

            # Skip validation for shell built-ins and complex commands
            shell_builtins = ["cd", "echo", "export", "source", ".", "bash", "sh"]
            if executable in shell_builtins or "|" in command or "&&" in command:
                return None

            # Check if executable exists
            if not shutil.which(executable) and not os.path.isfile(executable):
                return f"Executable not found: {executable}"

            # Basic command injection protection
            dangerous_chars = [";", "`", "$()"]
            for char in dangerous_chars:
                if char in command:
                    logger.warning(f"Potentially dangerous command: {command}")
                    break

            return None

        except Exception as e:
            logger.error(f"Error validating command '{command}': {e}")
            return f"Command validation error: {str(e)}"

    def _execute_in_terminal(
        self,
        command: str,
        working_directory: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        terminal_title: Optional[str] = None,
        terminal_geometry: Optional[str] = None,
        persist: bool = False,
        timeout: int = 30,
    ) -> LaunchResult:
        """Execute command in a new terminal window."""
        if not self._preferred_terminal:
            return LaunchResult(
                success=False,
                command=command,
                error_message="No terminal emulator available",
            )

        try:
            # Build terminal command
            terminal_cmd = self._build_terminal_command(
                terminal_type=self._preferred_terminal,
                command=command,
                working_directory=working_directory,
                terminal_title=terminal_title,
                terminal_geometry=terminal_geometry,
                persist=persist,
            )

            if not terminal_cmd:
                return LaunchResult(
                    success=False,
                    command=command,
                    error_message=f"Failed to build command for terminal: {self._preferred_terminal}",
                )

            logger.debug(f"Executing terminal command: {' '.join(terminal_cmd)}")

            # Execute the terminal command
            # Use DEVNULL to prevent pipe buffer deadlocks when apps close
            process = subprocess.Popen(
                terminal_cmd,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=working_directory,
            )

            return LaunchResult(
                success=True,
                command=command,
                process_id=process.pid,
                terminal_type=self._preferred_terminal,
            )

        except Exception as e:
            error_msg = f"Failed to execute in terminal: {str(e)}"
            logger.error(error_msg)
            return LaunchResult(
                success=False,
                command=command,
                error_message=error_msg,
                terminal_type=self._preferred_terminal,
            )

    def _build_terminal_command(
        self,
        terminal_type: str,
        command: str,
        working_directory: Optional[str] = None,
        terminal_title: Optional[str] = None,
        terminal_geometry: Optional[str] = None,
        persist: bool = False,
    ) -> Optional[List[str]]:
        """Build terminal-specific command."""
        try:
            # Prepare command with persistence if requested
            final_command = command
            if persist:
                final_command += "; read -p 'Press Enter to close...'"

            # Build command based on terminal type
            if terminal_type == "gnome-terminal":
                return self._build_gnome_terminal_command(
                    final_command, working_directory, terminal_title, terminal_geometry
                )
            elif terminal_type == "konsole":
                return self._build_konsole_command(
                    final_command, working_directory, terminal_title, terminal_geometry
                )
            elif terminal_type == "xterm":
                return self._build_xterm_command(
                    final_command, working_directory, terminal_title, terminal_geometry
                )
            elif terminal_type == "x-terminal-emulator":
                return self._build_generic_terminal_command(
                    terminal_type, final_command, working_directory
                )
            elif terminal_type == "alacritty":
                return self._build_alacritty_command(
                    final_command, working_directory, terminal_title
                )
            elif terminal_type == "terminator":
                return self._build_terminator_command(
                    final_command, working_directory, terminal_title
                )
            elif terminal_type == "Terminal" and self._platform == "darwin":
                return self._build_macos_terminal_command(
                    final_command, working_directory, terminal_title
                )
            elif terminal_type == "iTerm" and self._platform == "darwin":
                return self._build_iterm_command(
                    final_command, working_directory, terminal_title
                )
            elif terminal_type in ["cmd.exe", "powershell.exe", "wt.exe"]:
                return self._build_windows_terminal_command(
                    terminal_type, final_command, working_directory, terminal_title
                )
            else:
                logger.warning(f"Unsupported terminal type: {terminal_type}")
                return None

        except Exception as e:
            logger.error(f"Error building terminal command: {e}")
            return None

    def _build_gnome_terminal_command(
        self,
        command: str,
        working_directory: Optional[str],
        title: Optional[str],
        geometry: Optional[str],
    ) -> List[str]:
        """Build gnome-terminal command."""
        cmd = ["gnome-terminal"]

        if title:
            cmd.extend(["--title", title])

        if geometry:
            cmd.extend(["--geometry", geometry])

        if working_directory:
            cmd.extend(["--working-directory", working_directory])

        cmd.extend(["--", "bash", "-i", "-c", command])
        return cmd

    def _build_konsole_command(
        self,
        command: str,
        working_directory: Optional[str],
        title: Optional[str],
        geometry: Optional[str],
    ) -> List[str]:
        """Build konsole command."""
        cmd = ["konsole"]

        if working_directory:
            cmd.extend(["--workdir", working_directory])

        if title:
            cmd.extend(["--title", title])

        cmd.extend(["-e", "bash", "-i", "-c", command])
        return cmd

    def _build_xterm_command(
        self,
        command: str,
        working_directory: Optional[str],
        title: Optional[str],
        geometry: Optional[str],
    ) -> List[str]:
        """Build xterm command."""
        cmd = ["xterm"]

        if title:
            cmd.extend(["-title", title])

        if geometry:
            cmd.extend(["-geometry", geometry])

        # xterm doesn't have built-in working directory support
        full_command = command
        if working_directory:
            full_command = f"cd '{working_directory}' && {command}"

        cmd.extend(["-e", "bash", "-i", "-c", full_command])
        return cmd

    def _build_generic_terminal_command(
        self, terminal_type: str, command: str, working_directory: Optional[str]
    ) -> List[str]:
        """Build generic terminal command."""
        cmd = [terminal_type]

        full_command = command
        if working_directory:
            full_command = f"cd '{working_directory}' && {command}"

        cmd.extend(["-e", "bash", "-i", "-c", full_command])
        return cmd

    def _build_alacritty_command(
        self, command: str, working_directory: Optional[str], title: Optional[str]
    ) -> List[str]:
        """Build alacritty command."""
        cmd = ["alacritty"]

        if working_directory:
            cmd.extend(["--working-directory", working_directory])

        if title:
            cmd.extend(["--title", title])

        cmd.extend(["-e", "bash", "-i", "-c", command])
        return cmd

    def _build_terminator_command(
        self, command: str, working_directory: Optional[str], title: Optional[str]
    ) -> List[str]:
        """Build terminator command."""
        cmd = ["terminator"]

        if working_directory:
            cmd.extend(["--working-directory", working_directory])

        if title:
            cmd.extend(["--title", title])

        cmd.extend(["-x", "bash", "-i", "-c", command])
        return cmd

    def _build_macos_terminal_command(
        self, command: str, working_directory: Optional[str], title: Optional[str]
    ) -> List[str]:
        """Build macOS Terminal.app command using osascript."""
        script_parts = []

        if working_directory:
            script_parts.append(
                f'tell application "Terminal" to do script "cd \\"{working_directory}\\" && {command}"'
            )
        else:
            script_parts.append(f'tell application "Terminal" to do script "{command}"')

        return ["osascript", "-e", " ".join(script_parts)]

    def _build_iterm_command(
        self, command: str, working_directory: Optional[str], title: Optional[str]
    ) -> List[str]:
        """Build iTerm2 command using osascript."""

        full_command = command
        if working_directory:
            full_command = f'cd "{working_directory}" && {command}'

        script = f'''
        tell application "iTerm"
            create window with default profile
            tell current session of current window
                write text "{full_command}"
            end tell
        end tell
        '''

        return ["osascript", "-e", script]

    def _build_windows_terminal_command(
        self,
        terminal_type: str,
        command: str,
        working_directory: Optional[str],
        title: Optional[str],
    ) -> List[str]:
        """Build Windows terminal command."""
        if terminal_type == "wt.exe":
            # Windows Terminal
            cmd = ["wt"]

            if working_directory:
                cmd.extend(["-d", working_directory])

            if title:
                cmd.extend(["--title", title])

            cmd.extend(["--", "cmd", "/k", command])
            return cmd

        elif terminal_type == "powershell.exe":
            cmd = ["powershell", "-NoExit"]

            if working_directory:
                command = f"Set-Location '{working_directory}'; {command}"

            cmd.extend(["-Command", command])
            return cmd

        else:  # cmd.exe
            cmd = ["cmd", "/k"]

            if working_directory:
                command = f'cd /d "{working_directory}" && {command}'

            cmd.append(command)
            return cmd

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    @staticmethod
    def create_launcher(
        name: str, command: str, description: str = "", **kwargs
    ) -> Launcher:
        """Create a launcher with sensible defaults."""
        return Launcher(name=name, command=command, description=description, **kwargs)

    @staticmethod
    def create_shotbot_debug_launcher(shotbot_path: str) -> Launcher:
        """Create a launcher for debugging ShotBot."""
        return Launcher(
            name="ShotBot Debug",
            command=f"rez env PySide6_Essentials pillow Jinja2 -- python3 '{shotbot_path}' --debug",
            description="Launch ShotBot with debug logging",
            category="debug",
            terminal_title="ShotBot Debug - {timestamp}",
            persist_terminal=True,
            validate_command=False,  # Skip validation for complex rez commands
        )
