"""Enhanced launcher manager using the new thread-safe architecture.

This module integrates all the thread-safe components to provide a robust
launcher management system.
"""

import json
import logging
import os
import shlex
import string
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from config import Config
from memory_safe_cache import LRUCache, MemoryMonitor, ResourceManager
from qprocess_manager import (
    ProcessConfig,
    QProcessManager,
)
from shot_model import Shot
from thread_safe_manager import (
    AtomicCounter,
    ProcessInfo,
    ThreadSafeCollection,
    ThreadSafeProcessManager,
)

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


class EnhancedLauncherManager(QObject):
    """Enhanced launcher manager with thread-safe operations."""

    # Qt signals
    launchers_changed = Signal()
    launcher_added = Signal(str)  # launcher_id
    launcher_updated = Signal(str)  # launcher_id
    launcher_deleted = Signal(str)  # launcher_id
    validation_error = Signal(str, str)  # field, error_message
    execution_started = Signal(str)  # launcher_id
    execution_finished = Signal(str, bool)  # launcher_id, success
    process_output = Signal(str, str)  # launcher_id, output_line

    # Constants
    MAX_CONCURRENT_PROCESSES = 100
    CLEANUP_INTERVAL_MS = 30000

    def __init__(self):
        super().__init__()

        # Configuration
        self.config_dir = Path.home() / ".shotbot"
        self.config_file = self.config_dir / "custom_launchers.json"
        self._ensure_config_dir()

        # Thread-safe collections
        self._launchers = ThreadSafeCollection[CustomLauncher]("launchers")
        self._launcher_cache = LRUCache[Dict[str, Any]](
            max_size=100,
            ttl_seconds=300,  # 5 minute cache
        )

        # Process management
        self._process_manager = ThreadSafeProcessManager(
            max_processes=self.MAX_CONCURRENT_PROCESSES
        )
        self._qprocess_manager = QProcessManager(
            max_concurrent=self.MAX_CONCURRENT_PROCESSES,
            parent=self,
        )

        # Resource management
        self._resource_manager = ResourceManager(parent=self)
        self._memory_monitor = MemoryMonitor()

        # Statistics
        self._execution_counter = AtomicCounter()
        self._success_counter = AtomicCounter()
        self._failure_counter = AtomicCounter()

        # Cleanup timer
        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(self.CLEANUP_INTERVAL_MS)

        # Connect QProcess manager signals
        self._qprocess_manager.process_started.connect(self._on_process_started)
        self._qprocess_manager.process_finished.connect(self._on_process_finished)
        self._qprocess_manager.process_error.connect(self._on_process_error)

        # Load launchers
        self._load_launchers()

        logger.info("Enhanced launcher manager initialized")

    def _ensure_config_dir(self) -> None:
        """Ensure configuration directory exists."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create config directory: {e}")
            raise

    def _load_launchers(self) -> None:
        """Load launchers from configuration file."""
        if not self.config_file.exists():
            logger.debug(f"Config file {self.config_file} does not exist")
            return

        try:
            # Check cache first
            cached_data = self._launcher_cache.get("launchers_config")
            if cached_data:
                logger.debug("Loading launchers from cache")
                for launcher_id, launcher_dict in cached_data.items():
                    launcher = CustomLauncher.from_dict(launcher_dict)
                    self._launchers.add(launcher_id, launcher)
                return

            # Load from file
            with open(self.config_file, "r") as f:
                data = json.load(f)

            launchers_data = {}
            for launcher_id, launcher_data in data.get("launchers", {}).items():
                launcher_data["id"] = launcher_id
                launcher = CustomLauncher.from_dict(launcher_data)
                self._launchers.add(launcher_id, launcher)
                launchers_data[launcher_id] = launcher_data

            # Cache the loaded data
            self._launcher_cache.put("launchers_config", launchers_data)

            logger.info(f"Loaded {self._launchers.size()} launchers from config")

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to load launcher config: {e}")

    def _save_launchers(self) -> bool:
        """Save launchers to configuration file."""
        try:
            config_data = {
                "version": "2.0",
                "launchers": {},
                "metadata": {
                    "saved_at": datetime.now().isoformat(),
                    "launcher_count": self._launchers.size(),
                },
            }

            # Get all launchers safely
            with self._launchers.safe_iteration() as launchers:
                for launcher_id, launcher in launchers.items():
                    launcher_dict = launcher.to_dict()
                    launcher_dict.pop("id", None)
                    config_data["launchers"][launcher_id] = launcher_dict

            # Write atomically
            temp_file = self.config_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(config_data, f, indent=2)

            temp_file.replace(self.config_file)

            # Update cache
            self._launcher_cache.put("launchers_config", config_data["launchers"])

            logger.info(f"Saved {len(config_data['launchers'])} launchers to config")
            return True

        except (OSError, json.JSONEncodeError) as e:
            logger.error(f"Failed to save launcher config: {e}")
            return False

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
        """Create a new launcher with validation."""
        # Validate inputs
        errors = self._validate_launcher_data(name, command)
        if errors:
            for error in errors:
                self.validation_error.emit("general", error)
            return None

        # Create launcher
        launcher_id = str(uuid.uuid4())
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

        # Add to collection
        if self._launchers.add(launcher_id, launcher):
            if self._save_launchers():
                logger.info(f"Created launcher '{name}' with ID {launcher_id}")
                self.launcher_added.emit(launcher_id)
                self.launchers_changed.emit()
                return launcher_id
            else:
                self._launchers.remove(launcher_id)
                self.validation_error.emit("general", "Failed to save launcher")

        return None

    def execute_launcher(
        self,
        launcher_id: str,
        shot: Optional[Shot] = None,
        custom_vars: Optional[Dict[str, str]] = None,
        use_qprocess: bool = True,
    ) -> bool:
        """Execute a launcher using the new architecture."""
        launcher = self._launchers.get(launcher_id)
        if not launcher:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
            return False

        # Check if we can start a new process
        if not self._process_manager.can_start_process():
            self.validation_error.emit(
                "general", "Maximum concurrent processes reached"
            )
            return False

        # Check memory pressure
        if self._memory_monitor.is_under_pressure():
            logger.warning("System under memory pressure, deferring launch")
            self.validation_error.emit("general", "System under memory pressure")
            return False

        try:
            # Prepare command with variable substitution
            command = self._substitute_variables(
                launcher.command, shot, {**launcher.variables, **(custom_vars or {})}
            )

            # Prepare working directory
            working_dir = None
            if shot and shot.workspace_path:
                working_dir = shot.workspace_path

            self._execution_counter.increment()

            if use_qprocess:
                # Use QProcess manager
                return self._execute_with_qprocess(
                    launcher_id, launcher.name, command, working_dir
                )
            else:
                # Use thread-safe process manager
                return self._execute_with_process_manager(
                    launcher_id, launcher.name, command, working_dir
                )

        except Exception as e:
            logger.error(f"Failed to execute launcher '{launcher.name}': {e}")
            self._failure_counter.increment()
            self.execution_finished.emit(launcher_id, False)
            return False

    def _execute_with_qprocess(
        self,
        launcher_id: str,
        launcher_name: str,
        command: str,
        working_dir: Optional[str] = None,
    ) -> bool:
        """Execute using QProcess manager."""
        # Parse command
        parts = shlex.split(command)
        if not parts:
            return False

        config = ProcessConfig(
            command=parts[0],
            args=parts[1:] if len(parts) > 1 else [],
            working_dir=working_dir,
            timeout_seconds=300,  # 5 minute timeout
            max_output_size=5000,
        )

        process_id = f"{launcher_id}_{self._execution_counter.get()}"

        if self._qprocess_manager.add_process(process_id, config, auto_start=True):
            logger.info(f"Started launcher '{launcher_name}' with QProcess")

            # Register process with resource manager
            self._resource_manager.register_resource(
                process_id,
                {"launcher_id": launcher_id, "start_time": datetime.now()},
            )

            return True

        return False

    def _execute_with_process_manager(
        self,
        launcher_id: str,
        launcher_name: str,
        command: str,
        working_dir: Optional[str] = None,
    ) -> bool:
        """Execute using thread-safe process manager."""
        process_id = f"{launcher_id}_{self._execution_counter.get()}"

        process_info = ProcessInfo(
            process_id=process_id,
            launcher_id=launcher_id,
            launcher_name=launcher_name,
            command=command,
        )

        if self._process_manager.register_process(process_info):
            # Start the actual process (implementation depends on your needs)
            # This is where you'd integrate with subprocess or QProcess
            logger.info(f"Registered launcher '{launcher_name}' with process manager")
            self.execution_started.emit(launcher_id)
            return True

        return False

    def _substitute_variables(
        self,
        text: str,
        shot: Optional[Shot] = None,
        custom_vars: Optional[Dict[str, str]] = None,
    ) -> str:
        """Perform variable substitution in text."""
        if not text:
            return text

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

    def _validate_launcher_data(self, name: str, command: str) -> List[str]:
        """Validate launcher data."""
        errors = []

        # Validate name
        if not name or not name.strip():
            errors.append("Name cannot be empty")
        elif len(name.strip()) > 100:
            errors.append("Name cannot exceed 100 characters")

        # Validate command
        if not command or not command.strip():
            errors.append("Command cannot be empty")
        else:
            # Check for dangerous patterns
            dangerous_patterns = [
                "rm -rf",
                "sudo rm",
                "format c:",
                "del /s",
                "> /dev/sda",
            ]
            cmd_lower = command.lower()
            for pattern in dangerous_patterns:
                if pattern in cmd_lower:
                    errors.append(f"Command contains dangerous pattern: {pattern}")
                    break

        return errors

    def _on_process_started(self, process_id: str):
        """Handle process started event from QProcess manager."""
        # Extract launcher_id from process_id
        launcher_id = process_id.split("_")[0]
        self.execution_started.emit(launcher_id)

    def _on_process_finished(self, process_id: str, exit_code: int):
        """Handle process finished event from QProcess manager."""
        # Extract launcher_id from process_id
        launcher_id = process_id.split("_")[0]

        success = exit_code == 0
        if success:
            self._success_counter.increment()
        else:
            self._failure_counter.increment()

        # Clean up resources
        self._resource_manager.release_resource(process_id)

        self.execution_finished.emit(launcher_id, success)

    def _on_process_error(self, process_id: str, error_message: str):
        """Handle process error event from QProcess manager."""
        launcher_id = process_id.split("_")[0]
        logger.error(f"Process error for launcher {launcher_id}: {error_message}")
        self._failure_counter.increment()
        self.validation_error.emit("execution", error_message)

    def _periodic_cleanup(self):
        """Perform periodic cleanup tasks."""
        # Clean up finished processes
        self._process_manager.cleanup_finished_processes()

        # Clean up cache
        self._launcher_cache.cleanup_expired()

        # Log statistics
        stats = self.get_statistics()
        logger.debug(f"Launcher manager stats: {stats}")

    def get_launcher(self, launcher_id: str) -> Optional[CustomLauncher]:
        """Get a launcher by ID."""
        return self._launchers.get(launcher_id)

    def list_launchers(self) -> List[CustomLauncher]:
        """Get list of all launchers."""
        return self._launchers.values()

    def update_launcher(self, launcher_id: str, **kwargs) -> bool:
        """Update an existing launcher."""
        launcher = self._launchers.get(launcher_id)
        if not launcher:
            return False

        # Update fields
        for key, value in kwargs.items():
            if hasattr(launcher, key) and value is not None:
                setattr(launcher, key, value)

        launcher.updated_at = datetime.now().isoformat()

        # Save changes
        if self._save_launchers():
            self.launcher_updated.emit(launcher_id)
            self.launchers_changed.emit()
            return True

        return False

    def delete_launcher(self, launcher_id: str) -> bool:
        """Delete a launcher."""
        launcher = self._launchers.remove(launcher_id)
        if launcher:
            if self._save_launchers():
                self.launcher_deleted.emit(launcher_id)
                self.launchers_changed.emit()
                return True
            else:
                # Restore if save failed
                self._launchers.add(launcher_id, launcher)

        return False

    def get_statistics(self) -> Dict[str, Any]:
        """Get launcher manager statistics."""
        process_stats = self._process_manager.get_process_stats()
        qprocess_stats = self._qprocess_manager.get_process_stats()
        cache_stats = self._launcher_cache.get_stats()
        memory_info = self._memory_monitor.get_memory_info()

        return {
            "launchers": self._launchers.size(),
            "executions": self._execution_counter.get(),
            "successes": self._success_counter.get(),
            "failures": self._failure_counter.get(),
            "process_stats": process_stats,
            "qprocess_stats": qprocess_stats,
            "cache_stats": cache_stats,
            "memory_info": memory_info,
        }

    def shutdown(self):
        """Shutdown the launcher manager."""
        logger.info("Shutting down enhanced launcher manager...")

        # Stop timers
        self._cleanup_timer.stop()

        # Shutdown managers
        self._process_manager.shutdown()
        self._qprocess_manager.terminate_all()
        self._resource_manager.shutdown()

        # Clear cache
        self._launcher_cache.clear()

        logger.info("Enhanced launcher manager shutdown complete")
