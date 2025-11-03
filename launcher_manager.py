"""Business logic layer for ShotBot's custom launcher feature.

This module provides a thin orchestration layer that coordinates between
specialized components for launcher management, validation, and execution.
"""

from __future__ import annotations

# Standard library imports
import contextlib
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

# Third-party imports
from PySide6.QtCore import QObject, QRecursiveMutex, QTimer, Signal

# Local application imports
from config import ThreadingConfig
from launcher.config_manager import LauncherConfigManager
from launcher.models import (
    CustomLauncher,
    LauncherEnvironment,
    LauncherTerminal,
    LauncherValidation,
    ProcessInfoDict,
)
from launcher.process_manager import LauncherProcessManager
from launcher.repository import LauncherRepository
from launcher.validator import LauncherValidator
from logging_mixin import LoggingMixin
from process_pool_manager import ProcessPoolManager


if TYPE_CHECKING:
    # Standard library imports
    from pathlib import Path

    # Local application imports
    from launcher.models import ProcessInfo
    from launcher.worker import LauncherWorker
    from protocols import ProcessPoolInterface
    from shot_model import Shot

# Set up logger for this module


class LauncherManager(LoggingMixin, QObject):
    """Orchestrates launcher operations through specialized components.

    This class serves as a facade that coordinates between:
    - LauncherRepository: CRUD operations and persistence
    - LauncherValidator: Command and configuration validation
    - LauncherProcessManager: Process lifecycle management
    - LauncherConfigManager: Configuration persistence
    """

    # Qt signals
    launchers_changed = Signal()
    launcher_added = Signal(str)  # launcher_id
    launcher_updated = Signal(str)  # launcher_id
    launcher_deleted = Signal(str)  # launcher_id
    validation_error = Signal(str, str)  # field, error_message
    execution_started = Signal(str)  # launcher_id
    execution_finished = Signal(str, bool)  # launcher_id, success

    # Process management signals (forwarded from process manager)
    command_started = Signal(str, str)  # launcher_id, command
    command_finished = Signal(str, bool, int)  # launcher_id, success, return_code
    command_error = Signal(str, str)  # launcher_id, error_message
    command_output = Signal(str, str)  # launcher_id, output_line

    # Process limits
    MAX_CONCURRENT_PROCESSES = ThreadingConfig.MAX_WORKER_THREADS * 25

    def __init__(
        self,
        config_dir: str | Path | None = None,
        process_pool: ProcessPoolInterface | None = None,
    ) -> None:
        """Initialize the launcher manager with all components.

        Args:
            config_dir: Optional configuration directory path
            process_pool: Optional process pool instance (defaults to singleton)
        """
        super().__init__()

        # Initialize components
        self._config_manager = LauncherConfigManager(config_dir)
        self._repository = LauncherRepository(self._config_manager)
        self._validator = LauncherValidator()
        self._process_manager = LauncherProcessManager()
        self._signals_connected = False  # Track signal connection state

        # Initialize process pool - use provided instance or default singleton
        self._process_pool = process_pool or ProcessPoolManager.get_instance()

        self._use_process_pool = (
            os.environ.get("SHOTBOT_USE_PROCESS_POOL", "true").lower() == "true"
        )

        # Connect process manager signals
        try:
            _ = self._process_manager.process_started.connect(self.command_started)
            _ = self._process_manager.process_finished.connect(self.command_finished)
            _ = self._process_manager.process_error.connect(self.command_error)
            self._signals_connected = True
        except (AttributeError, RuntimeError) as e:
            # Signals may not be available in test environment
            self.logger.debug(f"Could not connect process manager signals: {e}")
            self._signals_connected = False

        self.logger.info(
            f"LauncherManager initialized with {self._repository.count()} launchers"
        )

    # ==================== Backward Compatibility Properties ====================

    @property
    def _active_processes(self) -> dict[str, ProcessInfo]:
        """Backward compatibility property for accessing active processes.

        This exposes the _active_processes from the process manager to maintain
        compatibility with existing tests and code that expect this attribute
        directly on LauncherManager.

        Returns:
            Dictionary of active processes from the process manager
        """
        return self._process_manager.get_active_processes_dict()

    @property
    def _active_workers(self) -> dict[str, LauncherWorker]:
        """Backward compatibility property for accessing active workers.

        Returns:
            Dictionary of active workers from the process manager
        """
        return self._process_manager.get_active_workers_dict()

    @_active_workers.setter
    def _active_workers(self, value: dict[str, LauncherWorker]) -> None:
        """Setter for active workers (backward compatibility for tests).

        Args:
            value: Dictionary of active workers to set
        """
        # TODO: Add a public setter method in ProcessManager or refactor tests
        self._process_manager._active_workers = value  # pyright: ignore[reportPrivateUsage]

    @property
    def _process_lock(self) -> QRecursiveMutex:
        """Backward compatibility property for accessing process lock.

        Returns:
            Process lock from the process manager
        """
        return self._process_manager._process_lock  # pyright: ignore[reportPrivateUsage]

    @property
    def _cleanup_retry_timer(self) -> QTimer:
        """Backward compatibility property for accessing cleanup retry timer.

        Returns:
            Cleanup retry timer from the process manager
        """
        return self._process_manager._cleanup_retry_timer  # pyright: ignore[reportPrivateUsage]

    @property
    def _cleanup_scheduled(self) -> bool:
        """Backward compatibility property for accessing cleanup scheduled flag.

        Returns:
            Cleanup scheduled flag from the process manager
        """
        return self._process_manager._cleanup_scheduled  # pyright: ignore[reportPrivateUsage]

    def _cleanup_finished_workers(self) -> None:
        """Backward compatibility method for cleaning up finished workers.

        Delegates to the process manager's cleanup method.
        """
        return self._process_manager._cleanup_finished_workers()  # pyright: ignore[reportPrivateUsage]

    # ==================== CRUD Operations ====================

    def create_launcher(
        self,
        name: str,
        command: str,
        description: str = "",
        category: str = "custom",
        variables: dict[str, str | None] | None = None,
        environment: LauncherEnvironment | None = None,
        terminal: LauncherTerminal | None = None,
        validation: LauncherValidation | None = None,
    ) -> str | None:
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
        # Create launcher object
        launcher = CustomLauncher(
            id="",  # Will be generated by repository
            name=name.strip(),
            description=description,
            command=command.strip(),
            category=category,
            variables={k: v for k, v in (variables or {}).items() if v is not None},
            environment=environment or LauncherEnvironment(),
            terminal=terminal or LauncherTerminal(),
            validation=validation or LauncherValidation(),
        )

        # Validate configuration
        launchers_dict = {
            launcher.id: launcher for launcher in self._repository.list_all()
        }
        valid, errors = self._validator.validate_launcher_config(
            launcher, launchers_dict
        )
        if not valid:
            for error in errors:
                self.validation_error.emit("general", error)
            return None

        # Create through repository
        if self._repository.create(launcher):
            self.logger.info(f"Created launcher '{name}' with ID {launcher.id}")
            self.launcher_added.emit(launcher.id)
            self.launchers_changed.emit()
            return launcher.id

        self.validation_error.emit("general", "Failed to save launcher configuration")
        return None

    def create_launcher_from_object(self, launcher: CustomLauncher) -> bool:
        """Create a launcher from a CustomLauncher object (backward compatibility).

        Args:
            launcher: CustomLauncher object to create

        Returns:
            True if successful, False otherwise
        """
        # Validate configuration
        launchers_dict = {
            existing.id: existing for existing in self._repository.list_all()
        }
        valid, errors = self._validator.validate_launcher_config(
            launcher, launchers_dict
        )
        if not valid:
            for error in errors:
                self.validation_error.emit("general", error)
            return False

        # Create through repository, preserving the launcher's ID
        if self._repository.create(launcher):
            self.logger.info(
                f"Created launcher '{launcher.name}' with ID {launcher.id}"
            )
            self.launcher_added.emit(launcher.id)
            self.launchers_changed.emit()
            return True

        self.validation_error.emit("general", "Failed to save launcher configuration")
        return False

    def update_launcher(
        self,
        launcher_id: str,
        name: str | None = None,
        command: str | None = None,
        description: str | None = None,
        category: str | None = None,
        variables: dict[str, str | None] | None = None,
        environment: LauncherEnvironment | None = None,
        terminal: LauncherTerminal | None = None,
        validation: LauncherValidation | None = None,
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
        # Get existing launcher
        launcher = self._repository.get(launcher_id)
        if not launcher:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
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
            launcher.variables = {k: v for k, v in variables.items() if v is not None}
        if environment is not None:
            launcher.environment = environment
        if terminal is not None:
            launcher.terminal = terminal
        if validation is not None:
            launcher.validation = validation

        launcher.updated_at = datetime.now(tz=UTC).isoformat()

        # Validate updated configuration
        launchers_dict = {
            launcher.id: launcher for launcher in self._repository.list_all()
        }
        valid, errors = self._validator.validate_launcher_config(
            launcher, launchers_dict
        )
        if not valid:
            for error in errors:
                self.validation_error.emit("general", error)
            return False

        # Update through repository
        if self._repository.update(launcher):
            self.logger.info(f"Updated launcher '{launcher.name}' (ID: {launcher_id})")
            self.launcher_updated.emit(launcher_id)
            self.launchers_changed.emit()
            return True

        self.validation_error.emit("general", "Failed to save launcher configuration")
        return False

    def delete_launcher(self, launcher_id: str) -> bool:
        """Delete a launcher.

        Args:
            launcher_id: ID of launcher to delete

        Returns:
            True if successful, False otherwise
        """
        # Delete through repository (it handles the name logging)
        if self._repository.delete(launcher_id):
            self.launcher_deleted.emit(launcher_id)
            self.launchers_changed.emit()
            return True

        self.validation_error.emit("general", f"Launcher {launcher_id} not found")
        return False

    def get_launcher(self, launcher_id: str) -> CustomLauncher | None:
        """Get a launcher by ID.

        Args:
            launcher_id: ID of launcher to retrieve

        Returns:
            CustomLauncher if found, None otherwise
        """
        return self._repository.get(launcher_id)

    def get_launcher_by_name(self, name: str) -> CustomLauncher | None:
        """Get a launcher by name.

        Args:
            name: Name of launcher to retrieve

        Returns:
            CustomLauncher if found, None otherwise
        """
        if not name:
            return None
        return self._repository.get_by_name(name.strip())

    def list_launchers(self, category: str | None = None) -> list[CustomLauncher]:
        """Get list of all launchers, optionally filtered by category.

        Args:
            category: Optional category filter

        Returns:
            List of CustomLauncher objects
        """
        return self._repository.list_all(category)

    def get_categories(self) -> list[str]:
        """Get list of all categories in use.

        Returns:
            Sorted list of category names
        """
        return self._repository.get_categories()

    # ==================== Validation ====================

    def validate_command_syntax(self, command: str) -> tuple[bool, str | None]:
        """Validate command syntax for variable substitutions.

        Args:
            command: Command string to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        return self._validator.validate_command_syntax(command)

    def validate_launcher_config(
        self,
        launcher: CustomLauncher,
        exclude_id: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Validate a launcher configuration.

        Args:
            launcher: Launcher to validate
            exclude_id: Optional ID to exclude from duplicate checks

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        launchers_dict = {
            launcher.id: launcher for launcher in self._repository.list_all()
        }
        if exclude_id and exclude_id in launchers_dict:
            del launchers_dict[exclude_id]
        return self._validator.validate_launcher_config(launcher, launchers_dict)

    # ==================== Execution ====================

    def execute_launcher(
        self,
        launcher_id: str,
        custom_vars: dict[str, str | None] | dict[str, str] | None = None,
        dry_run: bool = False,
        use_worker: bool = True,
    ) -> bool:
        """Execute a launcher with optional custom variables.

        Args:
            launcher_id: ID of launcher to execute
            custom_vars: Optional custom variables for substitution
            dry_run: If True, only validate and log the command
            use_worker: If True, use worker thread for execution

        Returns:
            True if execution started successfully, False otherwise
        """
        # Get launcher
        launcher = self._repository.get(launcher_id)
        if not launcher:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
            return False

        # Check process limit
        if (
            self._process_manager.get_active_process_count()
            >= self.MAX_CONCURRENT_PROCESSES
        ):
            error_msg = f"Maximum concurrent processes ({self.MAX_CONCURRENT_PROCESSES}) reached"
            self.logger.warning(error_msg)
            self.validation_error.emit("general", error_msg)
            return False

        # Substitute variables
        merged_vars = {**launcher.variables, **(custom_vars or {})}
        command = self._validator.substitute_variables(
            launcher.command, None, merged_vars
        )

        if dry_run:
            self.logger.info(f"DRY RUN - Would execute: {command}")
            return True

        # Execute command
        self.execution_started.emit(launcher_id)
        self.logger.info(f"Executing launcher '{launcher.name}': {command}")

        # Determine working directory
        working_dir = None
        if launcher.validation and launcher.validation.working_directory:
            working_dir = launcher.validation.working_directory

        # Execute based on configuration
        if use_worker and not launcher.terminal.required:
            # Use worker thread for non-terminal commands
            success = self._process_manager.execute_with_worker(
                launcher_id,
                launcher.name,
                command,
                working_dir,
            )
        else:
            # Use subprocess for terminal commands
            # Standard library imports
            import shlex

            cmd_list = shlex.split(command)
            process_key = self._process_manager.execute_with_subprocess(
                launcher_id,
                launcher.name,
                cmd_list,
                working_dir,
            )
            success = process_key is not None

        if success:
            self.command_started.emit(launcher_id, command)
        else:
            self.execution_finished.emit(launcher_id, False)

        return success

    def execute_in_shot_context(
        self,
        launcher_id: str,
        shot: Shot | None = None,
        custom_vars: dict[str, str | None] | dict[str, str] | None = None,
    ) -> bool:
        """Execute a launcher in the context of a specific shot.

        Args:
            launcher_id: ID of launcher to execute
            shot: Shot object providing context
            custom_vars: Additional variables for substitution

        Returns:
            True if execution started successfully, False otherwise
        """
        # Get launcher
        launcher = self._repository.get(launcher_id)
        if not launcher:
            self.validation_error.emit("general", f"Launcher {launcher_id} not found")
            return False

        # Build shot variables if shot provided
        shot_vars: dict[str, str] = {}
        if shot:
            shot_vars.update(
                {
                    "shot_name": shot.full_name,
                    "shot_path": shot.workspace_path,
                    "user": os.getenv("USER", "unknown"),
                }
            )

            # Add path components if resolve_paths is enabled
            # Note: PathUtils.get_shot_path_variables would need to be implemented
            # if path component extraction is needed

        # Merge all variables
        all_vars: dict[str, str] = {
            **launcher.variables,
            **shot_vars,
            **{k: v for k, v in (custom_vars or {}).items() if v is not None},
        }

        # Execute with merged variables
        return self.execute_launcher(launcher_id, all_vars)

    # ==================== Process Management ====================

    def get_active_process_count(self) -> int:
        """Get count of currently active processes.

        Returns:
            Number of active processes
        """
        return self._process_manager.get_active_process_count()

    def get_active_process_info(self) -> list[ProcessInfoDict]:
        """Get information about all active processes.

        Returns:
            List of process information dictionaries
        """
        return self._process_manager.get_active_process_info()

    def terminate_process(self, process_key: str, force: bool = False) -> bool:
        """Terminate a specific process.

        Args:
            process_key: Key of the process to terminate
            force: If True, force kill the process

        Returns:
            True if process was terminated, False otherwise
        """
        return self._process_manager.terminate_process(process_key, force)

    def stop_all_workers(self) -> None:
        """Stop all active workers and processes gracefully."""
        self._process_manager.stop_all_workers()

    def shutdown(self) -> None:
        """Shutdown the launcher manager and clean up resources."""
        self.logger.info("Shutting down LauncherManager")

        # Only disconnect signals if they were successfully connected
        if self._signals_connected:
            try:
                # Use disconnect() without arguments to disconnect all slots
                # This avoids warnings about disconnecting specific slots that may not exist
                if hasattr(self._process_manager, "process_started"):
                    with contextlib.suppress(RuntimeError, TypeError):
                        _ = self._process_manager.process_started.disconnect()

                if hasattr(self._process_manager, "process_finished"):
                    with contextlib.suppress(RuntimeError, TypeError):
                        _ = self._process_manager.process_finished.disconnect()

                if hasattr(self._process_manager, "process_error"):
                    with contextlib.suppress(RuntimeError, TypeError):
                        _ = self._process_manager.process_error.disconnect()

                self._signals_connected = False
            except Exception as e:
                # Log but don't fail on cleanup errors
                self.logger.debug(f"Error disconnecting signals: {e}")

        self._process_manager.shutdown()
        self.logger.info("LauncherManager shutdown complete")

    def reload_config(self) -> bool:
        """Reload launcher configuration from disk.

        Returns:
            True if reload successful, False otherwise
        """
        try:
            self._repository.reload()
            self.launchers_changed.emit()
            self.logger.info("Configuration reloaded successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to reload configuration: {e}")
            return False
