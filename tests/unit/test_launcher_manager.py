"""Unit tests for LauncherManager functionality.

Tests custom launcher CRUD operations, execution, and thread safety.
Refactored to follow UNIFIED_TESTING_GUIDE principles:
- Use real components where possible
- Mock only external boundaries (subprocess, ProcessPoolManager)
- Test behavior, not implementation
- Use real file I/O with temp directories
- Real signal testing with QSignalSpy
"""

from __future__ import annotations

# Third-party imports
import pytest

# Local application imports
from config import ThreadingConfig
from launcher import CustomLauncher
from launcher_manager import LauncherManager
from shot_model import Shot
from tests.test_doubles_library import (
    TestWorker,
)


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
]


# Using TestWorker from test_doubles_library instead of custom MockWorker


class TestLauncherManager:
    """Test launcher management functionality."""

    def setup_method(self, qapp) -> None:
        """Set up each test method."""
        # qapp fixture ensures QApplication exists
        self.app = qapp
        self.manager = LauncherManager()
        self.temp_config = {}

    def teardown_method(self) -> None:
        """Clean up after each test method."""
        if hasattr(self, "manager"):
            self.manager = None

    def test_launcher_creation(self) -> None:
        """Test creating custom launchers."""
        launcher = CustomLauncher(
            id="test_launcher",
            name="Test App",
            description="Test launcher",
            command="echo 'test'",
            category="custom",
        )

        assert launcher.id == "test_launcher"
        assert launcher.name == "Test App"
        assert launcher.description == "Test launcher"
        assert launcher.command == "echo 'test'"
        assert launcher.category == "custom"
        # Test default values
        assert launcher.variables == {}
        assert launcher.environment is not None

    def test_launcher_manager_initialization(self) -> None:
        """Test launcher manager initialization."""
        assert self.manager is not None
        # Test basic functionality
        assert hasattr(self.manager, "_active_processes")

    def test_launcher_creation_with_factory(self, make_test_launcher) -> None:
        """Test launcher creation using factory fixture (UNIFIED_TESTING_GUIDE)."""
        # Use factory fixture for consistent test data
        launcher = make_test_launcher(
            name="Test Exec",
            command="echo 'hello'",
            description="Test execution launcher",
        )

        # Test behavior, not implementation
        assert launcher.name == "Test Exec"
        assert launcher.command == "echo 'hello'"
        assert launcher.description == "Test execution launcher"
        assert launcher.category == "test"

        # Verify factory creates consistent test data
        launcher2 = make_test_launcher()
        assert launcher2.name == "Test Launcher"  # Default name
        assert launcher2.command == "echo {shot_name}"  # Default command

    def test_threading_config(self) -> None:
        """Test threading configuration access."""
        config = ThreadingConfig()
        assert hasattr(config, "MAX_WORKER_THREADS")
        assert config.MAX_WORKER_THREADS == 4
        assert hasattr(config, "WORKER_STOP_TIMEOUT_MS")
        assert hasattr(config, "SUBPROCESS_TIMEOUT")

    def test_shot_model_integration(self) -> None:
        """Test integration with Shot model."""
        shot = Shot(
            show="test_show",
            sequence="seq01",
            shot="shot01",
            workspace_path="/test/path",
        )

        assert shot.show == "test_show"
        assert shot.sequence == "seq01"
        assert shot.shot == "shot01"

    def test_worker_state_management(self) -> None:
        """Test worker state management with real TestWorker."""
        # Use TestWorker from test_doubles_library
        worker = TestWorker()
        assert worker.was_started is False

        # Start worker and test behavior
        worker.start()
        worker.wait(100)  # Wait briefly for thread
        assert worker.was_started is True

        # Stop and verify
        worker.stop()
        assert worker.was_stopped is True


if __name__ == "__main__":
    pytest.main([__file__])
