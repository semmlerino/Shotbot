"""QProcess-based implementation of LauncherManager for improved process management.

This module provides a QProcess-based version of LauncherManager that offers
better integration with Qt's event loop, improved resource management, and
more robust process lifecycle tracking.
"""

import logging
import os
import shlex
import string
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from config import Config
from launcher_manager import (
    CustomLauncher,
    LauncherConfig,
    LauncherEnvironment,
    LauncherTerminal,
    LauncherValidation,
)
from qprocess_manager import ProcessState, QProcessManager
from shot_model import Shot
from utils import PathUtils

logger = logging.getLogger(__name__)


class LauncherExecutionWorker(QThread):
    """Worker thread for launcher execution using QProcess."""

    # Signals
    execution_started = Signal(str, str)  # launcher_id, command
    execution_progress = Signal(str, str)  # launcher_id, message
    execution_finished = Signal(str, bool, int)  # launcher_id, success, return_code
    execution_error = Signal(str, str)  # launcher_id, error_message

    def __init__(
        self,
        process_manager: QProcessManager,
        launcher_id: str,
        launcher_name: str,
        command: str,
        working_directory: Optional[str] = None,
        terminal: bool = False,
        terminal_persist: bool = False,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.process_manager = process_manager
        self.launcher_id = launcher_id
        self.launcher_name = launcher_name
        self.command = command
        self.working_directory = working_directory
        self.terminal = terminal
        self.terminal_persist = terminal_persist
        self._process_id: Optional[str] = None

    def run(self):
        """Execute the launcher command."""
        try:
            # Emit start signal
            self.execution_started.emit(self.launcher_id, self.command)
            logger.info(
                f"Worker starting launcher '{self.launcher_name}': {self.command}"
            )

            # Execute command
            if self.terminal:
                # Launch in terminal window
                self._process_id = self.process_manager.execute(
                    command=self.command,
                    working_directory=self.working_directory,
                    terminal=True,
                    terminal_persist=self.terminal_persist,
                    capture_output=False,
                    timeout_ms=0,  # No timeout for GUI apps
                    process_id=f"launcher_{self.launcher_id}_{int(time.time() * 1000)}",
                )
            else:
                # Launch directly with output capture
                self._process_id = self.process_manager.execute_shell(
                    command=self.command,
                    working_directory=self.working_directory,
                    capture_output=False,  # GUI apps don't need output capture
                    timeout_ms=0,  # No timeout for GUI apps
                    process_id=f"launcher_{self.launcher_id}_{int(time.time() * 1000)}",
                )

            if not self._process_id:
                error_msg = f"Failed to start launcher '{self.launcher_name}'"
                logger.error(error_msg)
                self.execution_error.emit(self.launcher_id, error_msg)
                self.execution_finished.emit(self.launcher_id, False, -1)
                return

            logger.info(
                f"Started process {self._process_id} for launcher '{self.launcher_name}'"
            )

            # For terminal processes, we consider them successful if launched
            if self.terminal:
                self.execution_finished.emit(self.launcher_id, True, 0)
            else:
                # For non-terminal, wait briefly to check if it started
                time.sleep(0.5)
                process_info = self.process_manager.get_process_info(self._process_id)

                if process_info and process_info.state in [
                    ProcessState.RUNNING,
                    ProcessState.FINISHED,
                ]:
                    success = process_info.state != ProcessState.FAILED
                    return_code = process_info.exit_code or 0
                    self.execution_finished.emit(self.launcher_id, success, return_code)
                else:
                    self.execution_error.emit(
                        self.launcher_id, "Process failed to start"
                    )
                    self.execution_finished.emit(self.launcher_id, False, -1)

        except Exception as e:
            error_msg = (
                f"Worker exception for launcher '{self.launcher_name}': {str(e)}"
            )
            logger.error(error_msg)
            self.execution_error.emit(self.launcher_id, error_msg)
            self.execution_finished.emit(self.launcher_id, False, -1)

    def stop(self):
        """Stop the launcher execution."""
        if self._process_id:
            self.process_manager.terminate_process(self._process_id)
        self.quit()
        self.wait()


class LauncherManagerQProcess(QObject):
    """QProcess-based launcher manager with improved process management.

    Drop-in replacement for LauncherManager that uses QProcess for better
    integration with Qt's event loop and more robust process management.
    """

    # Qt signals (backward compatible)
    launchers_changed = Signal()
    launcher_added = Signal(str)  # launcher_id
    launcher_updated = Signal(str)  # launcher_id
    launcher_deleted = Signal(str)  # launcher_id
    validation_error = Signal(str, str)  # field, error_message
    execution_started = Signal(str)  # launcher_id
    execution_finished = Signal(str, bool)  # launcher_id, success

    # New signals for enhanced functionality
    execution_progress = Signal(str, str)  # launcher_id, message
    process_count_changed = Signal(int, int)  # active, total

    # Process management constants
    MAX_CONCURRENT_PROCESSES = 100
    CLEANUP_INTERVAL_MS = 30000  # 30 seconds

    def __init__(self, process_manager: Optional[QProcessManager] = None):
        super().__init__()
        self.config = LauncherConfig()
        self.process_manager = process_manager or QProcessManager()
        self._launchers: Dict[str, CustomLauncher] = {}

        # Thread-safe process tracking
        self._active_workers: Dict[str, LauncherExecutionWorker] = {}
        self._process_lock = threading.RLock()

        # Periodic cleanup timer
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(self.CLEANUP_INTERVAL_MS)

        # Connect process manager signals
        self.process_manager.process_state_changed.connect(
            self._on_process_state_changed
        )

        # Load launchers
        self._load_launchers()

        logger.info("LauncherManagerQProcess initialized")

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
                ":(){ :|:& };:",  # Fork bomb
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
            "systemctl",
            "service",
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
        """Create a new launcher (backward compatible API)."""
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
        """Update an existing launcher (backward compatible API)."""
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
        """Delete a launcher (backward compatible API)."""
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
        """Get a launcher by ID."""
        return self._launchers.get(launcher_id)

    def get_launcher_by_name(self, name: str) -> Optional[CustomLauncher]:
        """Get a launcher by name."""
        if not name:
            return None

        name = name.strip()
        for launcher in self._launchers.values():
            if launcher.name == name:
                return launcher
        return None

    def list_launchers(self, category: Optional[str] = None) -> List[CustomLauncher]:
        """Get list of all launchers, optionally filtered by category."""
        launchers = list(self._launchers.values())

        if category:
            launchers = [l for l in launchers if l.category == category]

        # Sort by name
        launchers.sort(key=lambda x: x.name.lower())
        return launchers

    def get_categories(self) -> List[str]:
        """Get list of all categories in use."""
        categories = set(launcher.category for launcher in self._launchers.values())
        return sorted(categories)

    def execute_launcher(
        self,
        launcher_id: str,
        custom_vars: Optional[Dict[str, str]] = None,
        dry_run: bool = False,
        use_worker: bool = True,
    ) -> bool:
        """Execute a launcher with optional custom variables."""
        if launcher_id not in self._launchers:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
            return False

        launcher = self._launchers[launcher_id]

        try:
            # Check process limits
            active, total = self.process_manager.get_process_count()
            if active >= self.MAX_CONCURRENT_PROCESSES:
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

            # Use worker for execution
            if use_worker:
                return self._execute_with_worker(
                    launcher_id, launcher.name, command, launcher.terminal
                )
            else:
                # Direct execution (blocking)
                return self._execute_direct(
                    launcher_id, launcher.name, command, launcher.terminal
                )

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
        """Execute a launcher with shot context variables."""
        if launcher_id not in self._launchers:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
            return False

        launcher = self._launchers[launcher_id]

        try:
            # Check process limits
            active, total = self.process_manager.get_process_count()
            if active >= self.MAX_CONCURRENT_PROCESSES:
                error_msg = f"Maximum concurrent processes ({self.MAX_CONCURRENT_PROCESSES}) reached"
                logger.warning(error_msg)
                self.validation_error.emit("general", error_msg)
                return False

            # Substitute variables with shot context
            merged_vars = {**launcher.variables, **(custom_vars or {})}
            command = self._substitute_variables(launcher.command, shot, merged_vars)

            # Build full command with ws
            full_command = f"ws {shot.workspace_path} && {command}"

            if dry_run:
                logger.info(
                    f"DRY RUN - Would execute in shot {shot.full_name}: {full_command}"
                )
                return True

            # Use worker for execution
            if use_worker:
                return self._execute_with_worker(
                    launcher_id,
                    launcher.name,
                    full_command,
                    launcher.terminal,
                    shot.workspace_path,
                )
            else:
                # Direct execution (blocking)
                return self._execute_direct(
                    launcher_id,
                    launcher.name,
                    full_command,
                    launcher.terminal,
                    shot.workspace_path,
                )

        except Exception as e:
            logger.error(
                f"Failed to execute launcher '{launcher.name}' in shot context: {e}"
            )
            self.execution_finished.emit(launcher_id, False)
            return False

    def _execute_with_worker(
        self,
        launcher_id: str,
        launcher_name: str,
        command: str,
        terminal: LauncherTerminal,
        working_dir: Optional[str] = None,
    ) -> bool:
        """Execute command using a worker thread."""
        try:
            # Clean up finished workers first
            self._cleanup_finished_workers()

            # Create worker
            worker = LauncherExecutionWorker(
                self.process_manager,
                launcher_id,
                launcher_name,
                command,
                working_directory=working_dir,
                terminal=terminal.required,
                terminal_persist=terminal.persist,
                parent=self,
            )

            # Connect worker signals
            worker.execution_started.connect(
                lambda lid, cmd: self.execution_started.emit(lid)
            )
            worker.execution_progress.connect(self.execution_progress.emit)
            worker.execution_finished.connect(self._on_worker_finished)
            worker.execution_error.connect(
                lambda lid, error: logger.error(f"Worker error [{lid}]: {error}")
            )

            # Store worker reference
            with self._process_lock:
                self._active_workers[launcher_id] = worker

            # Start worker
            worker.start()

            logger.info(f"Started worker thread for launcher '{launcher_name}'")
            return True

        except Exception as e:
            logger.error(f"Failed to start worker thread: {e}")
            self.execution_finished.emit(launcher_id, False)
            return False

    def _execute_direct(
        self,
        launcher_id: str,
        launcher_name: str,
        command: str,
        terminal: LauncherTerminal,
        working_dir: Optional[str] = None,
    ) -> bool:
        """Execute command directly (blocking)."""
        try:
            self.execution_started.emit(launcher_id)

            # Execute using process manager
            if terminal.required:
                process_id = self.process_manager.execute(
                    command=command,
                    working_directory=working_dir,
                    terminal=True,
                    terminal_persist=terminal.persist,
                    capture_output=False,
                    timeout_ms=0,
                )
            else:
                process_id = self.process_manager.execute_shell(
                    command=command,
                    working_directory=working_dir,
                    capture_output=False,
                    timeout_ms=0,
                )

            success = process_id is not None
            self.execution_finished.emit(launcher_id, success)
            return success

        except Exception as e:
            logger.error(f"Failed to execute launcher '{launcher_name}': {e}")
            self.execution_finished.emit(launcher_id, False)
            return False

    @Slot(str, bool, int)
    def _on_worker_finished(self, launcher_id: str, success: bool, return_code: int):
        """Handle worker thread completion."""
        launcher = self._launchers.get(launcher_id)
        launcher_name = launcher.name if launcher else launcher_id

        if success:
            logger.info(f"Launcher '{launcher_name}' completed successfully")
        else:
            logger.warning(f"Launcher '{launcher_name}' failed with code {return_code}")

        # Emit the finished signal
        self.execution_finished.emit(launcher_id, success)

        # Schedule cleanup
        QTimer.singleShot(1000, self._cleanup_finished_workers)

    @Slot(str, ProcessState)
    def _on_process_state_changed(self, process_id: str, state: ProcessState):
        """Handle process state changes from QProcessManager."""
        # Update process count
        active, total = self.process_manager.get_process_count()
        self.process_count_changed.emit(active, total)

    def _cleanup_finished_workers(self):
        """Clean up finished worker threads."""
        with self._process_lock:
            finished = []
            for launcher_id, worker in self._active_workers.items():
                if worker.isFinished():
                    finished.append(launcher_id)
                    worker.deleteLater()

            for launcher_id in finished:
                del self._active_workers[launcher_id]

            if finished:
                logger.debug(f"Cleaned up {len(finished)} finished workers")

    @Slot()
    def _periodic_cleanup(self):
        """Periodic cleanup of resources."""
        self._cleanup_finished_workers()

        # Update process count
        active, total = self.process_manager.get_process_count()
        if active > 0:
            logger.debug(
                f"Active launcher processes: {active}/{self.MAX_CONCURRENT_PROCESSES}"
            )

    def get_active_process_count(self) -> int:
        """Get the number of currently active launcher processes."""
        self._cleanup_finished_workers()
        active, _ = self.process_manager.get_process_count()
        return active

    def get_active_process_info(self) -> List[Dict[str, Any]]:
        """Get information about all active processes."""
        return [
            {
                "process_id": info.process_id,
                "state": info.state.value,
                "duration": info.duration,
                "command": info.config.command[:100],
            }
            for info in self.process_manager.get_active_processes()
        ]

    def terminate_all_processes(self):
        """Terminate all active processes."""
        # Stop all workers
        with self._process_lock:
            for worker in self._active_workers.values():
                if worker.isRunning():
                    worker.stop()
            self._active_workers.clear()

        logger.info("Terminated all launcher processes")

    def shutdown(self):
        """Gracefully shutdown the launcher manager."""
        logger.info("LauncherManagerQProcess shutting down...")

        # Stop cleanup timer
        self._cleanup_timer.stop()

        # Terminate all processes
        self.terminate_all_processes()

        # Shutdown process manager
        if self.process_manager:
            self.process_manager.shutdown()

        logger.info("LauncherManagerQProcess shutdown complete")

    def reload_config(self) -> bool:
        """Reload launcher configuration from file."""
        try:
            self._load_launchers()
            logger.info("Reloaded launcher configuration")
            self.launchers_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to reload launcher configuration: {e}")
            return False

    def validate_command_syntax(self, command: str) -> tuple[bool, Optional[str]]:
        """Validate command syntax for variable substitutions (backward compatible)."""
        if not command:
            return False, "Command cannot be empty"

        # Define valid placeholder variables
        valid_variables = {
            "show",
            "sequence",
            "shot",
            "full_name",
            "workspace_path",
            "HOME",
            "USER",
            "SHOTBOT_VERSION",
        }

        try:
            template = string.Template(command)

            # Extract placeholders
            import re

            placeholders = set()
            for match in re.finditer(r"\$(?:(\w+)|\{(\w+)\})", command):
                placeholder = match.group(1) or match.group(2)
                if placeholder:
                    placeholders.add(placeholder)

            # Check for invalid variables
            invalid_vars = placeholders - valid_variables
            if invalid_vars:
                return False, f"Invalid variables: {', '.join(sorted(invalid_vars))}"

            # Try safe substitution
            template.safe_substitute({})
            return True, None

        except Exception as e:
            return False, f"Command validation failed: {e}"

    def validate_launcher_paths(
        self, launcher_id: str, shot: Optional[Shot] = None
    ) -> List[str]:
        """Validate that required files exist for a launcher (backward compatible)."""
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

        return errors
