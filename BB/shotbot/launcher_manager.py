"""Business logic layer for ShotBot's custom launcher feature."""

import json
import logging
import os
import shlex
import string
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from config import Config
from shot_model import Shot
from utils import PathUtils

# Set up logger for this module
logger = logging.getLogger(__name__)


@dataclass
class LauncherValidation:
    """Validation settings for a launcher."""

    check_executable: bool = True
    required_files: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(
        default_factory=lambda: [
            r";\s*rm\s",
            r";\s*sudo\s",
            r";\s*su\s",
            r"&&\s*rm\s",
            r"\|\s*rm\s",
            r"`rm\s",
            r"\$\(rm\s",
        ]
    )


@dataclass
class LauncherTerminal:
    """Terminal settings for a launcher."""

    required: bool = False
    persist: bool = False
    title: Optional[str] = None


@dataclass
class LauncherEnvironment:
    """Environment settings for a launcher."""

    type: str = "bash"  # "bash", "rez", "conda"
    packages: List[str] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    command_prefix: Optional[str] = None


@dataclass
class CustomLauncher:
    """Represents a custom application launcher."""

    id: str
    name: str
    description: str
    command: str
    category: str = "custom"
    variables: Dict[str, str] = field(default_factory=dict)
    environment: LauncherEnvironment = field(default_factory=LauncherEnvironment)
    terminal: LauncherTerminal = field(default_factory=LauncherTerminal)
    validation: LauncherValidation = field(default_factory=LauncherValidation)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert launcher to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomLauncher":
        """Create launcher from dictionary data."""
        # Handle nested objects
        if "environment" in data and isinstance(data["environment"], dict):
            data["environment"] = LauncherEnvironment(**data["environment"])
        if "terminal" in data and isinstance(data["terminal"], dict):
            data["terminal"] = LauncherTerminal(**data["terminal"])
        if "validation" in data and isinstance(data["validation"], dict):
            data["validation"] = LauncherValidation(**data["validation"])

        return cls(**data)


class LauncherConfig:
    """Manages persistence of custom launcher configurations."""

    def __init__(self):
        self.config_dir = Path.home() / ".shotbot"
        self.config_file = self.config_dir / "custom_launchers.json"
        self._ensure_config_dir()

    def _ensure_config_dir(self) -> None:
        """Ensure configuration directory exists."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create config directory {self.config_dir}: {e}")
            raise

    def load_launchers(self) -> Dict[str, CustomLauncher]:
        """Load launchers from configuration file."""
        if not self.config_file.exists():
            logger.debug(f"Config file {self.config_file} does not exist")
            return {}

        try:
            with open(self.config_file, "r") as f:
                data = json.load(f)

            launchers = {}
            for launcher_id, launcher_data in data.get("launchers", {}).items():
                launcher_data["id"] = launcher_id
                launchers[launcher_id] = CustomLauncher.from_dict(launcher_data)

            logger.info(f"Loaded {len(launchers)} launchers from config")
            return launchers

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to load launcher config: {e}")
            return {}

    def save_launchers(self, launchers: Dict[str, CustomLauncher]) -> bool:
        """Save launchers to configuration file."""
        try:
            config_data = {
                "version": "1.0",
                "launchers": {},
                "terminal_preferences": ["gnome-terminal", "konsole", "xterm"],
            }

            for launcher_id, launcher in launchers.items():
                launcher_dict = launcher.to_dict()
                # Remove ID from nested dict as it's the key
                launcher_dict.pop("id", None)
                config_data["launchers"][launcher_id] = launcher_dict

            with open(self.config_file, "w") as f:
                json.dump(config_data, f, indent=2)

            logger.info(f"Saved {len(launchers)} launchers to config")
            return True

        except (OSError, json.JSONEncodeError) as e:
            logger.error(f"Failed to save launcher config: {e}")
            return False


class LauncherManager(QObject):
    """Manages CRUD operations and execution for custom launchers."""

    # Qt signals
    launchers_changed = Signal()
    launcher_added = Signal(str)  # launcher_id
    launcher_updated = Signal(str)  # launcher_id
    launcher_deleted = Signal(str)  # launcher_id
    validation_error = Signal(str, str)  # field, error_message
    execution_started = Signal(str)  # launcher_id
    execution_finished = Signal(str, bool)  # launcher_id, success

    def __init__(self):
        super().__init__()
        self.config = LauncherConfig()
        self._launchers: Dict[str, CustomLauncher] = {}
        self._active_processes: Dict[
            str, subprocess.Popen
        ] = {}  # Track active processes
        self._load_launchers()

    def _load_launchers(self) -> None:
        """Load launchers from configuration."""
        self._launchers = self.config.load_launchers()

    def _save_launchers(self) -> bool:
        """Save current launchers to configuration."""
        return self.config.save_launchers(self._launchers)

    def _generate_id(self) -> str:
        """Generate unique ID for new launcher."""
        return str(uuid.uuid4())

    def _validate_launcher_data(
        self, name: str, command: str, exclude_id: Optional[str] = None
    ) -> List[str]:
        """Validate launcher data and return list of errors."""
        errors = []

        # Validate name
        if not name or not name.strip():
            errors.append("Name cannot be empty")
        elif len(name.strip()) > 100:
            errors.append("Name cannot exceed 100 characters")
        else:
            # Check name uniqueness
            for launcher_id, launcher in self._launchers.items():
                if launcher_id != exclude_id and launcher.name == name.strip():
                    errors.append(f"Name '{name.strip()}' already exists")
                    break

        # Validate command
        if not command or not command.strip():
            errors.append("Command cannot be empty")
        else:
            # Check for security patterns
            cmd_lower = command.lower()
            security_patterns = [
                "rm -rf",
                "sudo rm",
                "rm /",
                "format c:",
                "del /s",
                "> /dev/sda",
                "dd if=",
                "mkfs.",
                "fdisk",
            ]
            for pattern in security_patterns:
                if pattern in cmd_lower:
                    errors.append(
                        f"Command contains potentially dangerous pattern: {pattern}"
                    )
                    break

        return errors

    def _substitute_variables(
        self,
        text: str,
        shot: Optional[Shot] = None,
        custom_vars: Optional[Dict[str, str]] = None,
    ) -> str:
        """Perform variable substitution in text."""
        if not text:
            return text

        # Build substitution context
        context = {}

        # Add shot context variables
        if shot:
            context.update(
                {
                    "show": shot.show,
                    "sequence": shot.sequence,
                    "shot": shot.shot,
                    "full_name": shot.full_name,
                    "workspace_path": shot.workspace_path,
                }
            )

        # Add custom variables
        if custom_vars:
            context.update(custom_vars)

        # Add environment variables
        context.update(
            {
                "HOME": os.environ.get("HOME", ""),
                "USER": os.environ.get("USER", ""),
                "SHOTBOT_VERSION": Config.APP_VERSION,
            }
        )

        # Use string.Template for safe substitution
        try:
            template = string.Template(text)
            return template.safe_substitute(context)
        except (ValueError, KeyError) as e:
            logger.warning(f"Variable substitution failed: {e}")
            return text

    def _validate_security(self, command: str) -> List[str]:
        """Validate command for security issues."""
        errors = []

        # Parse command safely
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            errors.append(f"Invalid command syntax: {e}")
            return errors

        if not tokens:
            errors.append("Empty command after parsing")
            return errors

        # Check for dangerous commands
        dangerous_commands = {
            "rm",
            "rmdir",
            "del",
            "format",
            "fdisk",
            "mkfs",
            "dd",
            "shutdown",
            "reboot",
            "halt",
            "init",
        }

        base_command = Path(tokens[0]).name.lower()
        if base_command in dangerous_commands:
            errors.append(f"Potentially dangerous command: {base_command}")

        return errors

    def create_launcher(
        self,
        name: str,
        command: str,
        description: str = "",
        category: str = "custom",
        variables: Optional[Dict[str, str]] = None,
        environment: Optional[LauncherEnvironment] = None,
        terminal: Optional[LauncherTerminal] = None,
        validation: Optional[LauncherValidation] = None,
    ) -> Optional[str]:
        """Create a new launcher.

        Args:
            name: Display name for the launcher
            command: Command to execute
            description: Optional description
            category: Category for organization
            variables: Custom variables for substitution
            environment: Environment configuration
            terminal: Terminal configuration
            validation: Validation configuration

        Returns:
            Launcher ID if successful, None otherwise
        """
        # Validate required fields
        errors = self._validate_launcher_data(name, command)
        if errors:
            for error in errors:
                self.validation_error.emit("general", error)
            return None

        # Security validation
        security_errors = self._validate_security(command)
        if security_errors:
            for error in security_errors:
                self.validation_error.emit("command", error)
            return None

        # Generate ID and create launcher
        launcher_id = self._generate_id()
        launcher = CustomLauncher(
            id=launcher_id,
            name=name.strip(),
            description=description,
            command=command.strip(),
            category=category,
            variables=variables or {},
            environment=environment or LauncherEnvironment(),
            terminal=terminal or LauncherTerminal(),
            validation=validation or LauncherValidation(),
        )

        # Store launcher
        self._launchers[launcher_id] = launcher

        # Save to config
        if self._save_launchers():
            logger.info(f"Created launcher '{name}' with ID {launcher_id}")
            self.launcher_added.emit(launcher_id)
            self.launchers_changed.emit()
            return launcher_id
        else:
            # Remove from memory if save failed
            del self._launchers[launcher_id]
            self.validation_error.emit(
                "general", "Failed to save launcher configuration"
            )
            return None

    def update_launcher(
        self,
        launcher_id: str,
        name: Optional[str] = None,
        command: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        variables: Optional[Dict[str, str]] = None,
        environment: Optional[LauncherEnvironment] = None,
        terminal: Optional[LauncherTerminal] = None,
        validation: Optional[LauncherValidation] = None,
    ) -> bool:
        """Update an existing launcher.

        Args:
            launcher_id: ID of launcher to update
            name: New name (if provided)
            command: New command (if provided)
            description: New description (if provided)
            category: New category (if provided)
            variables: New variables (if provided)
            environment: New environment config (if provided)
            terminal: New terminal config (if provided)
            validation: New validation config (if provided)

        Returns:
            True if successful, False otherwise
        """
        if launcher_id not in self._launchers:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
            return False

        launcher = self._launchers[launcher_id]

        # Validate changes if name or command are being updated
        update_name = name if name is not None else launcher.name
        update_command = command if command is not None else launcher.command

        errors = self._validate_launcher_data(update_name, update_command, launcher_id)
        if errors:
            for error in errors:
                self.validation_error.emit("general", error)
            return False

        # Security validation for command changes
        if command is not None:
            security_errors = self._validate_security(command)
            if security_errors:
                for error in security_errors:
                    self.validation_error.emit("command", error)
                return False

        # Apply updates
        if name is not None:
            launcher.name = name.strip()
        if command is not None:
            launcher.command = command.strip()
        if description is not None:
            launcher.description = description
        if category is not None:
            launcher.category = category
        if variables is not None:
            launcher.variables = variables
        if environment is not None:
            launcher.environment = environment
        if terminal is not None:
            launcher.terminal = terminal
        if validation is not None:
            launcher.validation = validation

        launcher.updated_at = datetime.now().isoformat()

        # Save to config
        if self._save_launchers():
            logger.info(f"Updated launcher '{launcher.name}' (ID: {launcher_id})")
            self.launcher_updated.emit(launcher_id)
            self.launchers_changed.emit()
            return True
        else:
            self.validation_error.emit(
                "general", "Failed to save launcher configuration"
            )
            return False

    def delete_launcher(self, launcher_id: str) -> bool:
        """Delete a launcher.

        Args:
            launcher_id: ID of launcher to delete

        Returns:
            True if successful, False otherwise
        """
        if launcher_id not in self._launchers:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
            return False

        launcher_name = self._launchers[launcher_id].name
        del self._launchers[launcher_id]

        # Save to config
        if self._save_launchers():
            logger.info(f"Deleted launcher '{launcher_name}' (ID: {launcher_id})")
            self.launcher_deleted.emit(launcher_id)
            self.launchers_changed.emit()
            return True
        else:
            self.validation_error.emit(
                "general", "Failed to save launcher configuration"
            )
            return False

    def get_launcher(self, launcher_id: str) -> Optional[CustomLauncher]:
        """Get a launcher by ID.

        Args:
            launcher_id: ID of launcher to retrieve

        Returns:
            CustomLauncher if found, None otherwise
        """
        return self._launchers.get(launcher_id)

    def get_launcher_by_name(self, name: str) -> Optional[CustomLauncher]:
        """Get a launcher by name.

        Args:
            name: Name of launcher to retrieve

        Returns:
            CustomLauncher if found, None otherwise
        """
        if not name:
            return None

        name = name.strip()
        for launcher in self._launchers.values():
            if launcher.name == name:
                return launcher
        return None

    def validate_command_syntax(self, command: str) -> tuple[bool, Optional[str]]:
        """Validate command syntax for variable substitutions.

        Args:
            command: Command string to validate

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.
        """
        if not command:
            return False, "Command cannot be empty"

        # Define valid placeholder variables
        valid_variables = {
            # Shot context variables
            "show",
            "sequence",
            "shot",
            "full_name",
            "workspace_path",
            # Environment variables
            "HOME",
            "USER",
            "SHOTBOT_VERSION",
        }

        try:
            # Use string.Template to validate syntax
            template = string.Template(command)

            # Extract all placeholders from the command
            placeholders = set()
            import re

            # Find all $identifier and ${identifier} patterns
            for match in re.finditer(r"\$(?:(\w+)|\{(\w+)\})", command):
                placeholder = match.group(1) or match.group(2)
                if placeholder:
                    placeholders.add(placeholder)

            # Check for invalid variable names
            invalid_vars = placeholders - valid_variables
            if invalid_vars:
                invalid_list = ", ".join(sorted(invalid_vars))
                valid_list = ", ".join(sorted(valid_variables))
                return (
                    False,
                    f"Invalid variables: {invalid_list}. Valid variables are: {valid_list}",
                )

            # Try to perform a safe substitution to catch syntax errors
            # Use empty context to catch any malformed patterns
            try:
                template.safe_substitute({})
            except ValueError as e:
                return False, f"Invalid template syntax: {e}"

            return True, None

        except Exception as e:
            return False, f"Command validation failed: {e}"

    def list_launchers(self, category: Optional[str] = None) -> List[CustomLauncher]:
        """Get list of all launchers, optionally filtered by category.

        Args:
            category: Optional category filter

        Returns:
            List of CustomLauncher objects
        """
        launchers = list(self._launchers.values())

        if category:
            launchers = [
                launcher for launcher in launchers if launcher.category == category
            ]

        # Sort by name
        launchers.sort(key=lambda x: x.name.lower())
        return launchers

    def get_categories(self) -> List[str]:
        """Get list of all categories in use.

        Returns:
            Sorted list of category names
        """
        categories = set(launcher.category for launcher in self._launchers.values())
        return sorted(categories)

    def execute_launcher(
        self,
        launcher_id: str,
        custom_vars: Optional[Dict[str, str]] = None,
        dry_run: bool = False,
    ) -> bool:
        """Execute a launcher with optional custom variables.

        Args:
            launcher_id: ID of launcher to execute
            custom_vars: Optional custom variables for substitution
            dry_run: If True, only validate and log the command without executing

        Returns:
            True if execution started successfully, False otherwise
        """
        if launcher_id not in self._launchers:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
            return False

        launcher = self._launchers[launcher_id]

        try:
            # Substitute variables in command
            merged_vars = {**launcher.variables, **(custom_vars or {})}
            command = self._substitute_variables(launcher.command, None, merged_vars)

            if dry_run:
                logger.info(f"DRY RUN - Would execute: {command}")
                return True

            # Execute command
            self.execution_started.emit(launcher_id)
            logger.info(f"Executing launcher '{launcher.name}': {command}")

            # Use shell execution for complex commands
            # Use DEVNULL to prevent pipe buffer deadlocks when apps close
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )

            # Don't wait for completion to avoid blocking UI
            # Store process reference for tracking
            process_key = f"{launcher_id}_{process.pid}"
            self._active_processes[process_key] = process

            logger.info(
                f"Started process for launcher '{launcher.name}' (PID: {process.pid})"
            )
            self.execution_finished.emit(launcher_id, True)

            # Clean up any finished processes
            self._cleanup_finished_processes()
            return True

        except Exception as e:
            logger.error(f"Failed to execute launcher '{launcher.name}': {e}")
            self.execution_finished.emit(launcher_id, False)
            return False

    def execute_in_shot_context(
        self,
        launcher_id: str,
        shot: Shot,
        custom_vars: Optional[Dict[str, str]] = None,
        dry_run: bool = False,
    ) -> bool:
        """Execute a launcher with shot context variables.

        Args:
            launcher_id: ID of launcher to execute
            shot: Shot object providing context
            custom_vars: Optional additional custom variables
            dry_run: If True, only validate and log the command without executing

        Returns:
            True if execution started successfully, False otherwise
        """
        if launcher_id not in self._launchers:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
            return False

        launcher = self._launchers[launcher_id]

        try:
            # Substitute variables in command with shot context
            merged_vars = {**launcher.variables, **(custom_vars or {})}
            command = self._substitute_variables(launcher.command, shot, merged_vars)

            if dry_run:
                logger.info(
                    f"DRY RUN - Would execute in shot context {shot.full_name}: {command}"
                )
                return True

            # Change to shot workspace directory
            original_cwd = os.getcwd()
            workspace_exists = PathUtils.validate_path_exists(
                shot.workspace_path, "Shot workspace"
            )

            if workspace_exists:
                os.chdir(shot.workspace_path)
                logger.info(f"Changed to workspace directory: {shot.workspace_path}")

            try:
                # Execute command
                self.execution_started.emit(launcher_id)
                logger.info(
                    f"Executing launcher '{launcher.name}' in shot {shot.full_name}: {command}"
                )

                # For shot context, use ws command if available
                full_command = f"bash -i -c 'ws {shot.workspace_path} && {command}'"

                # Use DEVNULL to prevent pipe buffer deadlocks when apps close
                process = subprocess.Popen(
                    full_command,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )

                # Store process reference for tracking
                process_key = f"{launcher_id}_{process.pid}"
                self._active_processes[process_key] = process

                logger.info(
                    f"Started process for launcher '{launcher.name}' in shot context (PID: {process.pid})"
                )
                self.execution_finished.emit(launcher_id, True)

                # Clean up any finished processes
                self._cleanup_finished_processes()
                return True

            finally:
                # Restore original working directory
                os.chdir(original_cwd)

        except Exception as e:
            logger.error(
                f"Failed to execute launcher '{launcher.name}' in shot context: {e}"
            )
            self.execution_finished.emit(launcher_id, False)
            return False

    def validate_launcher_paths(
        self, launcher_id: str, shot: Optional[Shot] = None
    ) -> List[str]:
        """Validate that required files exist for a launcher.

        Args:
            launcher_id: ID of launcher to validate
            shot: Optional shot context for variable substitution

        Returns:
            List of validation error messages
        """
        if launcher_id not in self._launchers:
            return [f"Launcher {launcher_id} not found"]

        launcher = self._launchers[launcher_id]
        errors = []

        # Check required files
        for file_path in launcher.validation.required_files:
            resolved_path = self._substitute_variables(
                file_path, shot, launcher.variables
            )

            if not PathUtils.validate_path_exists(
                resolved_path, f"Required file {file_path}"
            ):
                errors.append(f"Required file not found: {resolved_path}")

        # Check executable if enabled
        if launcher.validation.check_executable:
            try:
                command_parts = shlex.split(launcher.command)
                if command_parts:
                    executable = command_parts[0]
                    # Substitute variables in executable path
                    resolved_executable = self._substitute_variables(
                        executable, shot, launcher.variables
                    )

                    # Check if it's an absolute path
                    if os.path.isabs(resolved_executable):
                        if not PathUtils.validate_path_exists(
                            resolved_executable, "Executable"
                        ):
                            errors.append(
                                f"Executable not found: {resolved_executable}"
                            )
                    else:
                        # Check if it's in PATH
                        import shutil

                        if not shutil.which(resolved_executable):
                            errors.append(
                                f"Executable not found in PATH: {resolved_executable}"
                            )

            except ValueError as e:
                errors.append(f"Failed to parse command: {e}")

        return errors

    def _cleanup_finished_processes(self) -> None:
        """Clean up finished processes from tracking."""
        finished_keys = []
        for process_key, process in self._active_processes.items():
            # Check if process has finished
            if process.poll() is not None:
                finished_keys.append(process_key)

        # Remove finished processes
        for key in finished_keys:
            del self._active_processes[key]

        if finished_keys:
            logger.debug(f"Cleaned up {len(finished_keys)} finished processes")

    def get_active_process_count(self) -> int:
        """Get the number of currently active launcher processes.

        Returns:
            Number of active processes
        """
        self._cleanup_finished_processes()
        return len(self._active_processes)

    def reload_config(self) -> bool:
        """Reload launcher configuration from file.

        Returns:
            True if reload was successful, False otherwise
        """
        try:
            self._load_launchers()
            logger.info("Reloaded launcher configuration")
            self.launchers_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to reload launcher configuration: {e}")
            return False
