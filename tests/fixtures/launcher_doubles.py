"""Launcher test doubles.

Classes:
    TestLauncherEnvironment: Test double for launcher environment
    TestLauncherTerminal: Test double for launcher terminal settings
    TestLauncher: Test double for launcher configuration
    LauncherManagerDouble: Test double for LauncherManager with real Qt signals

Functions:
    make_test_launcher: Fixture factory for creating CustomLauncher instances
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal


class TestLauncherEnvironment:
    """Test double for launcher environment."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(
        self,
        env_type: str = "none",
        packages: list[str] | None = None,
        command_prefix: str = "",
    ) -> None:
        self.type = env_type
        self.packages = packages or []
        self.command_prefix = command_prefix


class TestLauncherTerminal:
    """Test double for launcher terminal settings."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self, persist: bool = False, background: bool = False) -> None:
        self.persist = persist
        self.background = background


class TestLauncher:
    """Test double for launcher configuration."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(
        self,
        launcher_id: str | None = None,
        name: str = "Test Launcher",
        command: str = "echo {shot_name}",
        description: str = "Test launcher",
        category: str = "test",
        enabled: bool = True,
        environment: TestLauncherEnvironment | None = None,
        terminal: TestLauncherTerminal | None = None,
        launcher_id_compat: str | None = None,  # Backwards compatibility alias
    ) -> None:
        """Initialize test launcher."""
        # Support both launcher_id and launcher_id_compat parameter names
        self.id = (
            launcher_id_compat
            if launcher_id_compat is not None
            else (launcher_id if launcher_id is not None else "test_launcher")
        )
        self.name = name
        self.command = command
        self.description = description
        self.category = category
        self.enabled = enabled
        self.environment = environment or TestLauncherEnvironment()
        self.terminal = terminal or TestLauncherTerminal()
        self.execution_count = 0
        self.last_execution_args: dict[str, str | None] | None = None

    def execute(self, **kwargs: str) -> bool:
        """Simulate launcher execution."""
        self.execution_count += 1
        self.last_execution_args = kwargs  # type: ignore[assignment]
        return True


class LauncherManagerDouble(QObject):
    """Test double for LauncherManager with real signals."""

    launcher_added = Signal(str)
    launcher_removed = Signal(str)
    launcher_executed = Signal(str)
    execution_started = Signal(str)
    execution_finished = Signal(str, bool)
    launchers_changed = Signal()

    def __init__(self) -> None:
        """Initialize test launcher manager."""
        super().__init__()
        self._launchers: dict[str, TestLauncher] = {}
        self._execution_history: list[dict[str, Any]] = []
        self._validation_results: dict[str, tuple[bool, str | None]] = {}
        self._test_command: str | None = None  # For temporary test launchers

    def validate_command_syntax(self, command: str) -> tuple[bool, str | None]:
        """Validate command syntax with real behavior."""
        if not command or not command.strip():
            return (False, "Command cannot be empty")

        # Check for basic syntax issues
        if command.startswith("{") and not command.endswith("}"):
            return (False, "Unclosed variable substitution")

        # Allow override for testing specific scenarios
        if command in self._validation_results:
            return self._validation_results[command]

        return (True, None)

    def set_validation_result(
        self, command: str, is_valid: bool, error: str | None = None
    ) -> None:
        """Set custom validation result for testing."""
        self._validation_results[command] = (is_valid, error)

    def set_test_command(self, command: str) -> None:
        """Set command for temporary test launcher."""
        self._test_command = command

    def get_launcher_by_name(self, name: str) -> TestLauncher | None:
        """Find launcher by name with real search behavior."""
        for launcher in self._launchers.values():
            if launcher.name == name:
                return launcher
        return None

    def create_launcher(
        self,
        name: str,
        command: str,
        description: str = "",
        category: str = "custom",
        environment: TestLauncherEnvironment | None = None,
        terminal: TestLauncherTerminal | None = None,
    ) -> str | None:
        """Create a test launcher with real behavior."""
        # Check for duplicate names
        if self.get_launcher_by_name(name):
            return None  # Simulate creation failure

        launcher_id = f"launcher_{len(self._launchers)}"
        launcher = TestLauncher(launcher_id, name, command, description, category)
        self._launchers[launcher_id] = launcher
        self.launcher_added.emit(launcher_id)
        self.launchers_changed.emit()
        return launcher_id

    def update_launcher(
        self,
        launcher_id: str,
        name: str | None = None,
        command: str | None = None,
        description: str | None = None,
        category: str | None = None,
        environment: TestLauncherEnvironment | None = None,
        terminal: TestLauncherTerminal | None = None,
    ) -> bool:
        """Update existing launcher with real behavior."""
        if launcher_id not in self._launchers:
            return False

        launcher = self._launchers[launcher_id]

        # Check for name conflicts (excluding self)
        if name and name != launcher.name:
            existing = self.get_launcher_by_name(name)
            if existing and existing.id != launcher_id:
                return False

        # Apply updates
        if name is not None:
            launcher.name = name
        if command is not None:
            launcher.command = command
        if description is not None:
            launcher.description = description
        if category is not None:
            launcher.category = category

        self.launchers_changed.emit()
        return True

    def delete_launcher(self, launcher_id: str) -> bool:
        """Delete launcher with real behavior."""
        if launcher_id not in self._launchers:
            return False

        del self._launchers[launcher_id]
        self.launcher_removed.emit(launcher_id)
        self.launchers_changed.emit()
        return True

    def execute_launcher(
        self,
        launcher_id_or_launcher: str | TestLauncher,
        custom_vars: dict[str, str | None] | None = None,
        dry_run: bool = False,
    ) -> bool:
        """Execute a launcher with real behavior."""
        # Handle both launcher_id string and launcher object
        if hasattr(launcher_id_or_launcher, "id"):
            # It's a launcher object
            launcher_obj = launcher_id_or_launcher
            launcher_id = launcher_obj.id  # type: ignore[union-attr]
            if launcher_id not in self._launchers:
                # For test launcher objects, add temporarily
                self._launchers[launcher_id] = launcher_obj  # type: ignore[assignment]
        elif isinstance(launcher_id_or_launcher, str):
            # It's a launcher_id string
            launcher_id = launcher_id_or_launcher
        else:
            # Unsupported type
            raise ValueError(
                f"Expected launcher object or launcher_id string, got {type(launcher_id_or_launcher)}"
            )

        if launcher_id not in self._launchers:
            # For test scenarios, create a temporary launcher if it doesn't exist
            if launcher_id == "test":
                command = self._test_command or "echo test"
                temp_launcher = TestLauncher(
                    launcher_id=launcher_id, name="Temporary Test Launcher", command=command
                )
                self._launchers[launcher_id] = temp_launcher
            else:
                return False

        launcher = self._launchers[launcher_id]

        if not dry_run:
            self.execution_started.emit(launcher_id)

        # Record execution
        self._execution_history.append(
            {
                "launcher_id": launcher_id,
                "custom_vars": custom_vars,
                "dry_run": dry_run,
                "timestamp": time.time(),
            }
        )

        # Simulate execution (always succeeds unless command has issues)
        success = not launcher.command.startswith("bad")  # Simple failure simulation

        if not success:
            # Simulate execution failure with an exception
            raise RuntimeError(f"Command execution failed: {launcher.command}")

        if not dry_run:
            self.launcher_executed.emit(launcher_id)
            self.execution_finished.emit(launcher_id, success)

        return success

    def list_launchers(self) -> list[TestLauncher]:
        """List all launchers."""
        return list(self._launchers.values())

    def get_launcher(self, launcher_id: str) -> TestLauncher | None:
        """Get specific launcher."""
        return self._launchers.get(launcher_id)

    def was_dry_run_executed(self) -> bool:
        """Check if any dry run was executed (for testing)."""
        return any(entry.get("dry_run", False) for entry in self._execution_history)

    def get_created_launcher_count(self) -> int:
        """Get number of launchers created (for testing)."""
        return len(self._launchers)

    def get_last_created_launcher(self) -> TestLauncher | None:
        """Get the most recently created launcher (for testing)."""
        if not self._launchers:
            return None
        # Return the launcher with highest ID number (most recent)
        return max(
            self._launchers.values(),
            key=lambda launcher: int(launcher.id.split("_")[-1]),
        )


# =============================================================================
# PYTEST FIXTURES
# =============================================================================


@pytest.fixture
def make_test_launcher():
    """Factory fixture for creating CustomLauncher instances for testing.

    Returns a callable that creates CustomLauncher instances with sensible
    defaults for testing. All parameters are optional.

    Example usage:
        def test_launcher(make_test_launcher):
            launcher = make_test_launcher(name="Test", command="echo test")
            assert launcher.name == "Test"
    """
    from launcher import CustomLauncher

    def _make_launcher(
        name: str = "Test Launcher",
        command: str = "echo {shot_name}",
        description: str = "Test launcher",
        category: str = "test",
        launcher_id: str | None = None,
    ):
        """Create a CustomLauncher instance for testing.

        Args:
            name: Launcher name (default: "Test Launcher")
            command: Command to execute (default: "echo {shot_name}")
            description: Launcher description (default: "Test launcher")
            category: Launcher category (default: "test")
            launcher_id: Launcher ID (default: auto-generated UUID)

        Returns:
            CustomLauncher instance

        """
        if launcher_id is None:
            launcher_id = str(uuid.uuid4())

        return CustomLauncher(
            id=launcher_id,
            name=name,
            command=command,
            description=description,
            category=category,
        )

    return _make_launcher
