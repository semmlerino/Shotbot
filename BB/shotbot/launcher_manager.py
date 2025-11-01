"""Business logic layer for ShotBot's custom launcher feature."""

import json
import logging
import os
import shlex
import string
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from config import Config
from shot_model import Shot
from thread_safe_worker import ThreadSafeWorker
from utils import PathUtils

# Set up logger for this module
logger = logging.getLogger(__name__)


class LauncherWorker(ThreadSafeWorker):
    """Thread-safe worker for executing launcher commands.

    This worker inherits thread-safe lifecycle management from ThreadSafeWorker
    and adds launcher-specific functionality.
    """

    # Launcher-specific signals
    command_started = Signal(str, str)  # launcher_id, command
    command_finished = Signal(str, bool, int)  # launcher_id, success, return_code
    command_error = Signal(str, str)  # launcher_id, error_message

    def __init__(
        self, launcher_id: str, command: str, working_dir: Optional[str] = None
    ):
        """Initialize launcher worker.

        Args:
            launcher_id: Unique identifier for this launcher
            command: Command to execute
            working_dir: Optional working directory for the command
        """
        super().__init__()
        self.launcher_id = launcher_id
        self.command = command
        self.working_dir = working_dir
        self._process: Optional[subprocess.Popen[Any]] = None

    def do_work(self):
        """Execute the launcher command with proper lifecycle management.

        This method is called by the base class run() method and includes
        proper state management and error handling.
        """
        try:
            # Emit start signal
            self.command_started.emit(self.launcher_id, self.command)
            logger.info(
                f"Worker {id(self)} starting launcher '{self.launcher_id}': {self.command}"
            )

            # Parse command properly to avoid shell injection
            # Use shlex to split if it's a string command
            if isinstance(self.command, str):
                # For safety, we should avoid shell=True
                # But some commands may require it, so we'll sanitize first
                import shlex

                try:
                    # Try to parse as shell command
                    cmd_list = shlex.split(self.command)
                    use_shell = False
                except ValueError:
                    # Complex shell command, use shell=True but log warning
                    logger.warning(
                        f"Using shell=True for complex command: {self.command[:100]}"
                    )
                    cmd_list = self.command
                    use_shell = True
            else:
                cmd_list = self.command
                use_shell = False

            # Start the process
            self._process = subprocess.Popen(
                cmd_list,
                shell=use_shell,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=self.working_dir,
                start_new_session=True,  # Isolate process group
            )

            # Monitor process with periodic checks for stop requests
            while not self.is_stop_requested():
                try:
                    # Check if process finished with timeout
                    return_code = self._process.wait(timeout=0.5)
                    # Process finished normally
                    success = return_code == 0
                    logger.info(
                        f"Worker {id(self)} finished launcher '{self.launcher_id}' with code {return_code}"
                    )
                    self.command_finished.emit(self.launcher_id, success, return_code)
                    return
                except subprocess.TimeoutExpired:
                    # Process still running, check for stop request
                    continue

            # Stop was requested - terminate the process
            if self._process and self._process.poll() is None:
                logger.info(
                    f"Worker {id(self)} stopping launcher '{self.launcher_id}' due to stop request"
                )
                self._terminate_process()
                self.command_finished.emit(self.launcher_id, False, -2)

        except Exception as e:
            error_msg = f"Worker exception for launcher '{self.launcher_id}': {str(e)}"
            logger.exception(error_msg)
            self.command_error.emit(self.launcher_id, error_msg)
            self.command_finished.emit(self.launcher_id, False, -1)
        finally:
            # Ensure process is cleaned up
            self._cleanup_process()

    def _terminate_process(self):
        """Safely terminate the subprocess."""
        if not self._process:
            return

        try:
            # Try graceful termination first
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Force kill if necessary
                logger.warning(
                    f"Force killing launcher '{self.launcher_id}' after timeout"
                )
                self._process.kill()
                self._process.wait(timeout=1)
        except Exception as e:
            logger.error(f"Error terminating process for '{self.launcher_id}': {e}")

    def _cleanup_process(self):
        """Clean up process resources."""
        if self._process:
            # Ensure process is terminated
            if self._process.poll() is None:
                self._terminate_process()
            self._process = None

    def request_stop(self) -> bool:
        """Override to handle process termination."""
        # Call parent implementation first
        if super().request_stop():
            # Also terminate the subprocess if running
            if self._process and self._process.poll() is None:
                self._terminate_process()
            return True
        return False


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

        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Failed to save launcher config: {e}")
            return False


class ProcessInfo:
    """Information about an active process."""

    def __init__(
        self,
        process: subprocess.Popen[Any],
        launcher_id: str,
        launcher_name: str,
        command: str,
        timestamp: float,
    ):
        self.process = process
        self.launcher_id = launcher_id
        self.launcher_name = launcher_name
        self.command = command
        self.timestamp = timestamp
        self.validated = False  # Whether process startup was validated


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

    # Process management constants
    MAX_CONCURRENT_PROCESSES = 100
    CLEANUP_INTERVAL_MS = 30000  # 30 seconds
    PROCESS_STARTUP_TIMEOUT_MS = 5000  # 5 seconds for process validation

    def __init__(self):
        super().__init__()
        self.config = LauncherConfig()
        self._launchers: Dict[str, CustomLauncher] = {}

        # Thread-safe process tracking with detailed information
        self._active_processes: Dict[str, ProcessInfo] = {}
        self._active_workers: Dict[str, LauncherWorker] = {}  # Track worker threads
        self._process_lock = threading.RLock()
        self._cleanup_lock = threading.Lock()  # Separate lock for cleanup coordination
        self._cleanup_in_progress = False  # Track cleanup state with lock protection

        # Periodic cleanup timer
        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(self.CLEANUP_INTERVAL_MS)

        # Shutdown flag for graceful cleanup
        self._shutting_down = False

        self._load_launchers()

        logger.info(
            f"LauncherManager initialized with cleanup interval {self.CLEANUP_INTERVAL_MS}ms"
        )

    def _load_launchers(self) -> None:
        """Load launchers from configuration."""
        self._launchers = self.config.load_launchers()

    def _save_launchers(self) -> bool:
        """Save current launchers to configuration."""
        return self.config.save_launchers(self._launchers)

    def _generate_id(self) -> str:
        """Generate unique ID for new launcher."""
        return str(uuid.uuid4())

    def _generate_process_key(self, launcher_id: str, process_pid: int) -> str:
        """Generate unique process key with timestamp and UUID components.

        Args:
            launcher_id: ID of the launcher
            process_pid: Process ID

        Returns:
            Unique process key string
        """
        timestamp = int(time.time() * 1000)  # Millisecond precision
        unique_suffix = str(uuid.uuid4())[:8]  # Short UUID suffix
        return f"{launcher_id}_{process_pid}_{timestamp}_{unique_suffix}"

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

    def validate_command_syntax(self, command: str) -> "tuple[bool, Optional[str]]":
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
        use_worker: bool = True,
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
            # Check process limits before execution
            with self._process_lock:
                if len(self._active_processes) >= self.MAX_CONCURRENT_PROCESSES:
                    error_msg = f"Maximum concurrent processes ({self.MAX_CONCURRENT_PROCESSES}) reached"
                    logger.warning(error_msg)
                    self.validation_error.emit("general", error_msg)
                    return False

            # Substitute variables in command
            merged_vars = {**launcher.variables, **(custom_vars or {})}
            command = self._substitute_variables(launcher.command, None, merged_vars)

            if dry_run:
                logger.info(f"DRY RUN - Would execute: {command}")
                return True

            # Execute command
            self.execution_started.emit(launcher_id)
            logger.info(f"Executing launcher '{launcher.name}': {command}")

            # Treat all apps as GUI apps - always launch in terminal window
            if launcher.terminal.required:
                # Try to launch in a terminal (like command_launcher.py does)
                # Properly escape command for shell safety
                import shlex

                escaped_command = shlex.quote(command)
                bash_command = f"bash -i -c {escaped_command}"

                terminal_commands = [
                    # Try gnome-terminal first
                    ["gnome-terminal", "--", "bash", "-i", "-c", command],
                    # Try xterm as fallback
                    ["xterm", "-e", bash_command],
                    # Try konsole
                    ["konsole", "-e", "bash", "-i", "-c", command],
                ]

                launched = False
                process = None
                for term_cmd in terminal_commands:
                    try:
                        process = subprocess.Popen(
                            term_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
                        launched = True
                        logger.info(f"Launched in terminal: {term_cmd[0]}")
                        break
                    except (FileNotFoundError, OSError):
                        continue

                if not launched or process is None:
                    # If no terminal worked, use worker thread as fallback
                    logger.warning(
                        "No terminal emulator found, falling back to worker thread"
                    )
                    return self._execute_with_worker(
                        launcher_id, launcher.name, command
                    )

                # Validate process started successfully
                # At this point, process is guaranteed to be not None
                assert process is not None
                success = self._validate_process_startup(process)
                if not success:
                    try:
                        process.terminate()
                        process.wait(timeout=3)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                    error_msg = "Process failed to start properly"
                    logger.error(
                        f"Failed to start launcher '{launcher.name}': {error_msg}"
                    )
                    self.execution_finished.emit(launcher_id, False)
                    return False

                # Generate unique process key and store process info
                process_key = self._generate_process_key(launcher_id, process.pid)
                process_info = ProcessInfo(
                    process=process,
                    launcher_id=launcher_id,
                    launcher_name=launcher.name,
                    command=command,
                    timestamp=time.time(),
                )
                process_info.validated = True

                with self._process_lock:
                    self._active_processes[process_key] = process_info

                logger.info(
                    f"Started process for launcher '{launcher.name}' (PID: {process.pid}, Key: {process_key})"
                )
                self.execution_finished.emit(launcher_id, True)

                # Clean up any finished processes
                self._cleanup_finished_processes()
                return True
            else:
                # Use worker thread for non-terminal apps (still with full isolation)
                return self._execute_with_worker(launcher_id, launcher.name, command)

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
        use_worker: bool = True,
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
            # Check process limits before execution
            with self._process_lock:
                if len(self._active_processes) >= self.MAX_CONCURRENT_PROCESSES:
                    error_msg = f"Maximum concurrent processes ({self.MAX_CONCURRENT_PROCESSES}) reached"
                    logger.warning(error_msg)
                    self.validation_error.emit("general", error_msg)
                    return False

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
                # Properly escape workspace path and command for shell safety
                import shlex

                escaped_workspace = shlex.quote(shot.workspace_path)
                # Build the inner command that will be passed to bash -c
                inner_command = f"ws {escaped_workspace} && {command}"
                full_command = f"bash -i -c {shlex.quote(inner_command)}"

                # Treat all apps as GUI apps - always launch in terminal window
                if launcher.terminal.required:
                    # Try to launch in a terminal (like command_launcher.py does)
                    terminal_commands = [
                        # Try gnome-terminal first
                        ["gnome-terminal", "--", "bash", "-i", "-c", full_command],
                        # Try xterm as fallback
                        ["xterm", "-e", full_command],
                        # Try konsole
                        ["konsole", "-e", "bash", "-i", "-c", full_command],
                    ]

                    launched = False
                    process = None
                    for term_cmd in terminal_commands:
                        try:
                            process = subprocess.Popen(
                                term_cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True,
                            )
                            launched = True
                            logger.info(f"Launched in terminal: {term_cmd[0]}")
                            break
                        except (FileNotFoundError, OSError):
                            continue

                    if not launched or process is None:
                        # If no terminal worked, use worker thread as fallback
                        logger.warning(
                            "No terminal emulator found, falling back to worker thread"
                        )
                        return self._execute_with_worker(
                            launcher_id,
                            launcher.name,
                            full_command,
                            shot.workspace_path,
                        )
                    # Validate process started successfully
                    # At this point, process is guaranteed to be not None
                    assert process is not None
                    success = self._validate_process_startup(process)
                    if not success:
                        try:
                            process.terminate()
                            process.wait(timeout=3)
                        except (subprocess.TimeoutExpired, OSError):
                            pass
                        error_msg = "Process failed to start properly in shot context"
                        logger.error(
                            f"Failed to start launcher '{launcher.name}': {error_msg}"
                        )
                        self.execution_finished.emit(launcher_id, False)
                        return False

                    # Generate unique process key and store process info
                    process_key = self._generate_process_key(launcher_id, process.pid)
                    process_info = ProcessInfo(
                        process=process,
                        launcher_id=launcher_id,
                        launcher_name=launcher.name,
                        command=full_command,
                        timestamp=time.time(),
                    )
                    process_info.validated = True

                    with self._process_lock:
                        self._active_processes[process_key] = process_info

                    logger.info(
                        f"Started process for launcher '{launcher.name}' in shot context (PID: {process.pid}, Key: {process_key})"
                    )
                    self.execution_finished.emit(launcher_id, True)

                    # Clean up any finished processes
                    self._cleanup_finished_processes()
                    return True
                else:
                    # Use worker thread for non-terminal apps (still with full isolation)
                    return self._execute_with_worker(
                        launcher_id, launcher.name, full_command, shot.workspace_path
                    )

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

    def _validate_process_startup(self, process: subprocess.Popen[Any]) -> bool:
        """Validate that a process started successfully.

        Args:
            process: The subprocess.Popen object to validate

        Returns:
            True if process started successfully, False otherwise
        """
        if self._shutting_down:
            return False

        try:
            # Wait a short time to see if process fails immediately
            time.sleep(0.1)

            # Check if process is still running
            return_code = process.poll()
            if return_code is not None:
                logger.warning(f"Process exited immediately with code {return_code}")
                return False

            # Process appears to be running successfully
            return True

        except Exception as e:
            logger.error(f"Error validating process startup: {e}")
            return False

    def _cleanup_finished_processes(self) -> None:
        """Clean up finished processes from tracking (thread-safe)."""
        if self._shutting_down:
            return

        finished_keys = []

        with self._process_lock:
            # Create a snapshot to avoid iteration issues
            processes_snapshot = list(self._active_processes.items())

        # Check processes outside lock to prevent blocking
        for process_key, process_info in processes_snapshot:
            try:
                # Check if process has finished
                if process_info.process.poll() is not None:
                    finished_keys.append(process_key)
            except (OSError, AttributeError) as e:
                # Process may have been cleaned up already
                logger.debug(f"Error checking process {process_key}: {e}")
                finished_keys.append(process_key)

        # Remove finished processes with lock held
        if finished_keys:
            with self._process_lock:
                for key in finished_keys:
                    if key in self._active_processes:
                        process_info = self._active_processes[key]
                        logger.debug(
                            f"Cleaning up finished process: {process_info.launcher_name} "
                            + f"(PID: {process_info.process.pid}, Key: {key})"
                        )
                        del self._active_processes[key]
                logger.debug(f"Cleaned up {len(finished_keys)} finished processes")

    def _periodic_cleanup(self) -> None:
        """Periodic cleanup of finished processes and old entries."""
        if self._shutting_down:
            return

        try:
            current_time = time.time()
            old_threshold = current_time - 3600  # 1 hour ago

            # Clean up processes and workers (they have their own locking)
            self._cleanup_finished_processes()
            self._cleanup_finished_workers()

            # Get snapshot for checking old entries
            with self._process_lock:
                processes_snapshot = list(self._active_processes.items())

            # Check for old entries outside the lock
            old_keys = []
            for process_key, process_info in processes_snapshot:
                if process_info.timestamp < old_threshold:
                    try:
                        # Check if process is still running
                        if process_info.process.poll() is not None:
                            old_keys.append(process_key)
                        else:
                            # Process is old but still running, log it
                            logger.info(
                                f"Long-running process: {process_info.launcher_name} "
                                + f"(PID: {process_info.process.pid}, Age: {current_time - process_info.timestamp:.0f}s)"
                            )
                    except (OSError, AttributeError):
                        old_keys.append(process_key)

            # Remove old entries with lock held
            if old_keys:
                with self._process_lock:
                    for key in old_keys:
                        if key in self._active_processes:
                            logger.debug(f"Removing old process entry: {key}")
                            del self._active_processes[key]

            # Log current process count
            with self._process_lock:
                active_count = len(self._active_processes)
                if active_count > 0:
                    logger.debug(
                        f"Active processes: {active_count}/{self.MAX_CONCURRENT_PROCESSES}"
                    )

        except Exception as e:
            logger.error(f"Error during periodic cleanup: {e}")

    def get_active_process_count(self) -> int:
        """Get the number of currently active launcher processes.

        Returns:
            Number of active processes
        """
        # Trigger cleanup but don't wait for it
        self._cleanup_finished_processes()
        self._cleanup_finished_workers()

        # Return current count
        with self._process_lock:
            return len(self._active_processes) + len(self._active_workers)

    def get_active_process_info(self) -> List[Dict[str, Any]]:
        """Get information about all active processes.

        Returns:
            List of dictionaries containing process information
        """
        # Trigger cleanup but don't wait for it
        self._cleanup_finished_processes()

        process_info = []
        with self._process_lock:
            for process_key, info in self._active_processes.items():
                try:
                    process_info.append(
                        {
                            "key": process_key,
                            "launcher_id": info.launcher_id,
                            "launcher_name": info.launcher_name,
                            "pid": info.process.pid,
                            "command": info.command,
                            "timestamp": info.timestamp,
                            "age_seconds": time.time() - info.timestamp,
                            "validated": info.validated,
                            "running": info.process.poll() is None,
                        }
                    )
                except (OSError, AttributeError) as e:
                    logger.debug(f"Error getting info for process {process_key}: {e}")

        return process_info

    def terminate_process(self, process_key: str, force: bool = False) -> bool:
        """Terminate a specific process.

        Args:
            process_key: Unique key identifying the process
            force: If True, use SIGKILL instead of SIGTERM

        Returns:
            True if process was terminated, False otherwise
        """
        with self._process_lock:
            if process_key not in self._active_processes:
                logger.warning(f"Process key {process_key} not found")
                return False

            process_info = self._active_processes[process_key]
            process = process_info.process

            try:
                if process.poll() is not None:
                    logger.debug(f"Process {process_key} already terminated")
                    del self._active_processes[process_key]
                    return True

                if force:
                    process.kill()
                    logger.info(
                        f"Forcefully killed process {process_info.launcher_name} (PID: {process.pid})"
                    )
                else:
                    process.terminate()
                    logger.info(
                        f"Terminated process {process_info.launcher_name} (PID: {process.pid})"
                    )

                # Wait a short time for process to exit
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if not force:
                        # Try force kill if terminate didn't work
                        process.kill()
                        process.wait(timeout=3)

                del self._active_processes[process_key]
                return True

            except (OSError, subprocess.TimeoutExpired) as e:
                logger.error(f"Error terminating process {process_key}: {e}")
                return False

    def shutdown(self) -> None:
        """Gracefully shutdown the launcher manager and clean up resources."""
        logger.info("LauncherManager shutting down...")
        self._shutting_down = True

        # Stop the cleanup timer
        if self._cleanup_timer:
            self._cleanup_timer.stop()

        # Stop all worker threads first
        self.stop_all_workers()

        # Terminate all active processes
        with self._process_lock:
            active_processes = list(self._active_processes.keys())

        for process_key in active_processes:
            try:
                self.terminate_process(process_key, force=False)
            except Exception as e:
                logger.error(
                    f"Error terminating process {process_key} during shutdown: {e}"
                )

        # Final cleanup
        with self._process_lock:
            remaining_count = len(self._active_processes)
            if remaining_count > 0:
                logger.warning(
                    f"Shutdown completed with {remaining_count} processes still tracked"
                )
            else:
                logger.info("All processes cleaned up successfully")

        logger.info("LauncherManager shutdown complete")

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

    def _execute_with_worker(
        self,
        launcher_id: str,
        launcher_name: str,
        command: str,
        working_dir: Optional[str] = None,
    ) -> bool:
        """Execute command using a worker thread.

        Args:
            launcher_id: ID of the launcher
            launcher_name: Name of the launcher
            command: Command to execute
            working_dir: Optional working directory

        Returns:
            True if worker started successfully, False otherwise
        """
        try:
            # Create worker
            worker = LauncherWorker(launcher_id, command, working_dir)

            # Connect worker signals with explicit connection types for thread safety
            # Use safe_connect from ThreadSafeWorker for proper tracking
            worker.safe_connect(
                worker.command_started,
                lambda lid, cmd: logger.debug(f"Worker started: {lid} - {cmd}"),
                Qt.ConnectionType.QueuedConnection,  # Cross-thread signal
            )
            worker.safe_connect(
                worker.command_finished,
                self._on_worker_finished,
                Qt.ConnectionType.QueuedConnection,  # Cross-thread signal
            )
            worker.safe_connect(
                worker.command_error,
                lambda lid, error: logger.error(f"Worker error [{lid}]: {error}"),
                Qt.ConnectionType.QueuedConnection,  # Cross-thread signal
            )

            # Store worker reference
            worker_key = f"{launcher_id}_{int(time.time() * 1000)}"
            with self._process_lock:
                self._active_workers[worker_key] = worker

            # Start worker
            worker.start()

            logger.info(f"Started worker thread for launcher '{launcher_name}'")
            return True

        except Exception as e:
            logger.error(f"Failed to start worker thread: {e}")
            self.execution_finished.emit(launcher_id, False)
            return False

    def _on_worker_finished(self, launcher_id: str, success: bool, return_code: int):
        """Handle worker thread completion.

        Args:
            launcher_id: ID of the launcher that finished
            success: Whether execution was successful
            return_code: Process return code
        """
        launcher = self._launchers.get(launcher_id)
        launcher_name = launcher.name if launcher else launcher_id

        if success:
            logger.info(f"Launcher '{launcher_name}' completed successfully")
        else:
            logger.warning(f"Launcher '{launcher_name}' failed with code {return_code}")

        # Emit the finished signal
        self.execution_finished.emit(launcher_id, success)

        # Schedule cleanup of finished workers
        QTimer.singleShot(1000, self._cleanup_finished_workers)

    def _cleanup_finished_workers(self):
        """Thread-safe cleanup of finished worker threads.

        This method uses proper locking and the ThreadSafeWorker state
        management to safely clean up finished workers.
        """
        # Try to acquire cleanup lock without blocking
        if not self._cleanup_lock.acquire(blocking=False):
            logger.debug("Worker cleanup already in progress, scheduling retry")
            # Schedule retry to ensure cleanup happens eventually
            QTimer.singleShot(500, self._cleanup_finished_workers)
            return

        try:
            # Get snapshot of workers to check
            with self._process_lock:
                workers_to_check = list(self._active_workers.items())

            finished_workers = []

            for worker_key, worker in workers_to_check:
                try:
                    # Use ThreadSafeWorker state management
                    state = worker.get_state()

                    if state in ["STOPPED", "DELETED"]:
                        # Worker finished normally
                        finished_workers.append(worker_key)

                        # Disconnect signals using thread-safe method
                        worker.disconnect_all()

                        # Schedule for deletion
                        worker.deleteLater()
                        logger.debug(
                            f"Cleaned up finished worker {worker_key} (state: {state})"
                        )

                    elif state == "CREATED" and not worker.isRunning():
                        # Worker never started - clean it up
                        finished_workers.append(worker_key)
                        worker.deleteLater()
                        logger.debug(f"Cleaned up unstarted worker {worker_key}")

                    elif state == "RUNNING" and not worker.isRunning():
                        # Worker is stuck - request stop
                        logger.warning(
                            f"Worker {worker_key} stuck in RUNNING but thread not running"
                        )
                        if worker.request_stop():
                            if not worker.safe_wait(1000):
                                worker.safe_terminate()
                        finished_workers.append(worker_key)
                        worker.deleteLater()

                    elif state == "STOPPING":
                        # Worker is stopping - give it more time
                        if not worker.safe_wait(500):
                            # Still not stopped - force terminate
                            logger.warning(
                                f"Force terminating stuck worker {worker_key}"
                            )
                            worker.safe_terminate()
                            finished_workers.append(worker_key)
                            worker.deleteLater()

                except Exception as e:
                    logger.error(f"Error checking worker {worker_key}: {e}")
                    # Mark for cleanup anyway to prevent accumulation
                    finished_workers.append(worker_key)
                    try:
                        worker.safe_terminate()
                        worker.deleteLater()
                    except Exception:
                        pass  # Best effort cleanup

            # Remove finished workers atomically
            if finished_workers:
                with self._process_lock:
                    for key in finished_workers:
                        self._active_workers.pop(key, None)

                logger.debug(f"Cleaned up {len(finished_workers)} finished workers")

        finally:
            self._cleanup_lock.release()

    def stop_all_workers(self) -> None:
        """Stop all active worker threads using thread-safe methods."""
        # Get snapshot of workers to stop
        with self._process_lock:
            workers_to_stop = dict(self._active_workers)

        # Stop workers outside the lock to avoid blocking
        for worker_key, worker in workers_to_stop.items():
            try:
                state = worker.get_state()
                if state not in ["STOPPED", "DELETED"]:
                    logger.debug(f"Stopping worker {worker_key} (state: {state})")
                    if worker.request_stop():
                        if not worker.safe_wait(1000):
                            logger.warning(
                                f"Worker {worker_key} didn't stop gracefully, terminating"
                            )
                            worker.safe_terminate()
            except Exception as e:
                logger.error(f"Error stopping worker {worker_key}: {e}")

        # Clear the dictionary with lock held
        with self._process_lock:
            self._active_workers.clear()
            logger.info("Stopped all worker threads")
