"""Test quality improvement patterns for ShotBot.

This module provides test data factories, builders, and patterns
for better test isolation, maintainability, and clarity.
"""

import random
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar
from unittest.mock import MagicMock, Mock, patch

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

T = TypeVar("T")


# ============================================================================
# Test Data Factories
# ============================================================================


class Factory:
    """Base factory class for generating test data."""

    _sequence = 0

    @classmethod
    def next_sequence(cls) -> int:
        """Get next sequence number."""
        cls._sequence += 1
        return cls._sequence

    @classmethod
    def reset_sequence(cls):
        """Reset sequence counter."""
        cls._sequence = 0


class ShotFactory(Factory):
    """Factory for creating test shot data."""

    @classmethod
    def create(
        cls,
        name: Optional[str] = None,
        sequence: Optional[str] = None,
        scene: Optional[str] = None,
        number: Optional[int] = None,
        workspace_path: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Create a test shot.

        Args:
            name: Shot name (auto-generated if None)
            sequence: Sequence number
            scene: Scene code
            number: Shot number
            workspace_path: Workspace path
            **kwargs: Additional shot attributes

        Returns:
            Dictionary representing a shot
        """
        seq_num = cls.next_sequence()

        if not name:
            sequence = sequence or "108"
            scene = scene or "CHV"
            number = number or seq_num
            name = f"{sequence}_{scene}_{number:04d}"

        if not workspace_path:
            workspace_path = f"/shows/ygsk/shots/{name}"

        return {
            "name": name,
            "workspace_path": workspace_path,
            "status": kwargs.get("status", "pending"),
            "thumbnail": kwargs.get("thumbnail"),
            "created": kwargs.get("created", datetime.now()),
            **kwargs,
        }

    @classmethod
    def create_batch(cls, count: int, **kwargs) -> List[Dict[str, Any]]:
        """Create multiple shots.

        Args:
            count: Number of shots to create
            **kwargs: Attributes to apply to all shots

        Returns:
            List of shot dictionaries
        """
        return [cls.create(**kwargs) for _ in range(count)]


class ThreeDESceneFactory(Factory):
    """Factory for creating test 3DE scene data."""

    @classmethod
    def create(
        cls,
        path: Optional[str] = None,
        user: Optional[str] = None,
        shot_name: Optional[str] = None,
        plate_name: Optional[str] = None,
        file_size: Optional[int] = None,
        modified_time: Optional[float] = None,
        **kwargs,
    ) -> "ThreeDEScene":
        """Create a test 3DE scene.

        Returns:
            ThreeDEScene instance
        """
        from threede_scene_model import ThreeDEScene

        seq_num = cls.next_sequence()

        if not shot_name:
            shot_name = f"TEST_{seq_num:04d}"

        if not user:
            user = f"user{seq_num}"

        if not path:
            path = (
                f"/shows/ygsk/shots/{shot_name}/user/{user}/3de/project/{shot_name}.3de"
            )

        if not plate_name:
            plate_name = f"plate_{seq_num}"

        if file_size is None:
            file_size = random.randint(1000, 1000000)

        if modified_time is None:
            modified_time = time.time() - random.randint(0, 86400 * 30)

        return ThreeDEScene(
            path=path,
            user=user,
            shot_name=shot_name,
            plate_name=plate_name,
            file_size=file_size,
            modified_time=modified_time,
            **kwargs,
        )


class LauncherFactory(Factory):
    """Factory for creating test launcher configurations."""

    @classmethod
    def create(
        cls,
        id: Optional[str] = None,
        name: Optional[str] = None,
        command: Optional[str] = None,
        icon: Optional[str] = None,
        **kwargs,
    ) -> "CustomLauncher":
        """Create a test launcher configuration.

        Returns:
            CustomLauncher instance
        """
        from launcher_manager import CustomLauncher

        seq_num = cls.next_sequence()

        if not id:
            id = f"launcher_{seq_num}"

        if not name:
            name = f"Test Launcher {seq_num}"

        if not command:
            command = f"test_command --arg{seq_num}"

        return CustomLauncher(id=id, name=name, command=command, icon=icon, **kwargs)


class PathFactory(Factory):
    """Factory for creating test paths."""

    @classmethod
    def create_shot_workspace(cls, shot_name: Optional[str] = None) -> str:
        """Create a shot workspace path."""
        if not shot_name:
            shot_name = ShotFactory.create()["name"]
        return f"/shows/ygsk/shots/{shot_name}"

    @classmethod
    def create_plate_path(
        cls,
        shot_name: Optional[str] = None,
        plate_name: Optional[str] = None,
        version: Optional[str] = None,
    ) -> str:
        """Create a plate file path."""
        shot_name = shot_name or f"TEST_{cls.next_sequence():04d}"
        plate_name = plate_name or "FG01"
        version = version or "v001"

        return (
            f"/shows/ygsk/shots/{shot_name}/plate/{plate_name}/{version}/"
            f"exr/4312x2304/{shot_name}_turnover-plate_{plate_name}_acescg_{version}.####.exr"
        )

    @classmethod
    def create_temp_directory(cls) -> Path:
        """Create a temporary directory for testing."""
        return Path(tempfile.mkdtemp(prefix="shotbot_test_"))


# ============================================================================
# Test Data Builders
# ============================================================================


class Builder:
    """Base builder class for complex test objects."""

    def build(self) -> Any:
        """Build the final object."""
        raise NotImplementedError


class ShotModelBuilder(Builder):
    """Builder for creating configured ShotModel instances."""

    def __init__(self):
        """Initialize the builder."""
        self._shots = []
        self._cache_enabled = True
        self._refresh_interval = 300
        self._mock_ws_output = None

    def with_shots(self, shots: List[Dict[str, Any]]) -> "ShotModelBuilder":
        """Add shots to the model.

        Args:
            shots: List of shot dictionaries

        Returns:
            Self for chaining
        """
        self._shots = shots
        return self

    def with_cache_disabled(self) -> "ShotModelBuilder":
        """Disable caching in the model.

        Returns:
            Self for chaining
        """
        self._cache_enabled = False
        return self

    def with_mock_ws_output(self, output: str) -> "ShotModelBuilder":
        """Set mock workspace command output.

        Args:
            output: Mock output string

        Returns:
            Self for chaining
        """
        self._mock_ws_output = output
        return self

    def build(self) -> "ShotModel":
        """Build the configured ShotModel.

        Returns:
            Configured ShotModel instance
        """
        from shot_model import ShotModel

        model = ShotModel()

        # Configure model
        if not self._cache_enabled:
            model._cache_enabled = False

        # Add shots
        for shot in self._shots:
            model._shots.append(shot["name"])

        # Mock ws command if specified
        if self._mock_ws_output:
            with patch.object(
                model, "_run_ws_command", return_value=self._mock_ws_output
            ):
                model.refresh_shots()

        return model


class CacheBuilder(Builder):
    """Builder for creating pre-populated cache instances."""

    def __init__(self):
        """Initialize the builder."""
        self._entries = {}
        self._default_ttl = 300

    def with_entry(
        self, key: str, value: Any, ttl: Optional[float] = None
    ) -> "CacheBuilder":
        """Add an entry to the cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live

        Returns:
            Self for chaining
        """
        self._entries[key] = (value, ttl or self._default_ttl)
        return self

    def with_expired_entry(self, key: str, value: Any) -> "CacheBuilder":
        """Add an already-expired entry.

        Args:
            key: Cache key
            value: Value to cache

        Returns:
            Self for chaining
        """
        self._entries[key] = (value, 0.001)
        return self

    def build(self) -> "CacheManager":
        """Build the configured cache.

        Returns:
            Configured CacheManager instance
        """
        import time

        from cache_manager import CacheManager

        cache = CacheManager()

        # Add entries
        for key, (value, ttl) in self._entries.items():
            cache.set(key, value, ttl)

            # If entry should be expired, wait
            if ttl <= 0.001:
                time.sleep(0.002)

        return cache


# ============================================================================
# Test Isolation Patterns
# ============================================================================


class IsolatedTest:
    """Base class for isolated test scenarios."""

    @contextmanager
    def isolated_filesystem(self):
        """Create an isolated filesystem for testing.

        Yields:
            Path to temporary directory
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @contextmanager
    def isolated_qt_app(self, qtbot):
        """Create an isolated Qt application context.

        Args:
            qtbot: pytest-qt fixture

        Yields:
            QApplication instance
        """
        from PySide6.QtCore import QCoreApplication

        # Save current app settings
        org = QCoreApplication.organizationName()
        app = QCoreApplication.applicationName()

        # Set test-specific settings
        QCoreApplication.setOrganizationName("TestOrg")
        QCoreApplication.setApplicationName("TestApp")

        try:
            yield QCoreApplication.instance()
        finally:
            # Restore original settings
            QCoreApplication.setOrganizationName(org)
            QCoreApplication.setApplicationName(app)

    @contextmanager
    def isolated_environment(self, **env_vars):
        """Create an isolated environment with custom variables.

        Args:
            **env_vars: Environment variables to set

        Yields:
            None
        """
        import os

        # Save original environment
        original = {}
        for key in env_vars:
            original[key] = os.environ.get(key)

        # Set test environment
        for key, value in env_vars.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)

        try:
            yield
        finally:
            # Restore original environment
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class MockBuilder:
    """Builder for creating complex mock objects."""

    @staticmethod
    def create_mock_process(
        returncode: int = 0, stdout: str = "", stderr: str = ""
    ) -> Mock:
        """Create a mock subprocess result.

        Args:
            returncode: Process return code
            stdout: Standard output
            stderr: Standard error

        Returns:
            Mock CompletedProcess
        """
        mock = Mock()
        mock.returncode = returncode
        mock.stdout = stdout
        mock.stderr = stderr
        return mock

    @staticmethod
    def create_mock_qthread(signals: Optional[Dict[str, Signal]] = None) -> Mock:
        """Create a mock QThread with signals.

        Args:
            signals: Dictionary of signal names to Signal objects

        Returns:
            Mock QThread
        """
        mock = MagicMock(spec=QObject)

        # Add standard thread methods
        mock.start = MagicMock()
        mock.quit = MagicMock()
        mock.wait = MagicMock(return_value=True)
        mock.isRunning = MagicMock(return_value=False)

        # Add signals
        if signals:
            for name, signal in signals.items():
                setattr(mock, name, signal)

        return mock

    @staticmethod
    def create_mock_widget(widget_type: Type[QWidget], **properties) -> Mock:
        """Create a mock Qt widget.

        Args:
            widget_type: Type of widget to mock
            **properties: Widget properties

        Returns:
            Mock widget
        """
        mock = MagicMock(spec=widget_type)

        # Set properties
        for prop, value in properties.items():
            setattr(mock, prop, value)

        # Add common widget methods
        mock.show = MagicMock()
        mock.hide = MagicMock()
        mock.update = MagicMock()
        mock.setEnabled = MagicMock()

        return mock


# ============================================================================
# Test Fixtures and Utilities
# ============================================================================


@pytest.fixture
def shot_factory():
    """Pytest fixture for shot factory."""
    ShotFactory.reset_sequence()
    return ShotFactory


@pytest.fixture
def scene_factory():
    """Pytest fixture for 3DE scene factory."""
    ThreeDESceneFactory.reset_sequence()
    return ThreeDESceneFactory


@pytest.fixture
def isolated_test():
    """Pytest fixture for isolated test helper."""
    return IsolatedTest()


@pytest.fixture
def mock_builder():
    """Pytest fixture for mock builder."""
    return MockBuilder


# ============================================================================
# Example Test Patterns
# ============================================================================


@pytest.mark.quality
class TestWithFactories:
    """Example tests using factories and builders."""

    def test_shot_model_with_factory(self, shot_factory):
        """Test shot model using factory-generated data."""
        # Create test shots
        shots = shot_factory.create_batch(10, status="pending")

        # Build model with shots
        model = ShotModelBuilder().with_shots(shots).with_cache_disabled().build()

        # Verify
        assert len(model._shots) == 10
        assert all(s["status"] == "pending" for s in shots)

    def test_cache_with_builder(self):
        """Test cache using builder pattern."""
        # Build cache with specific state
        cache = (
            CacheBuilder()
            .with_entry("key1", "value1", ttl=300)
            .with_entry("key2", "value2", ttl=600)
            .with_expired_entry("expired", "old_value")
            .build()
        )

        # Verify state
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("expired") is None


@pytest.mark.quality
class TestWithIsolation(IsolatedTest):
    """Example tests using isolation patterns."""

    def test_with_isolated_filesystem(self):
        """Test with isolated filesystem."""
        with self.isolated_filesystem() as tmpdir:
            # Create test files
            test_file = tmpdir / "test.txt"
            test_file.write_text("test content")

            # Test operations
            assert test_file.exists()
            assert test_file.read_text() == "test content"

        # Filesystem is automatically cleaned up

    def test_with_isolated_environment(self):
        """Test with isolated environment variables."""
        import os

        with self.isolated_environment(TEST_VAR="test_value", SHOTBOT_DEBUG="1"):
            # Test with custom environment
            assert os.environ["TEST_VAR"] == "test_value"
            assert os.environ["SHOTBOT_DEBUG"] == "1"

        # Environment is automatically restored
        assert "TEST_VAR" not in os.environ


@pytest.mark.quality
class TestWithMocks:
    """Example tests using mock builder."""

    def test_with_mock_process(self, mock_builder):
        """Test with mock subprocess."""
        # Create mock process
        mock_proc = mock_builder.create_mock_process(
            returncode=0, stdout="Shot list:\nSHOT_001\nSHOT_002"
        )

        # Use in test
        with patch("subprocess.run", return_value=mock_proc):
            # Test code that uses subprocess
            pass

    def test_with_mock_widget(self, mock_builder, qtbot):
        """Test with mock Qt widget."""
        from PySide6.QtWidgets import QPushButton

        # Create mock widget
        mock_button = mock_builder.create_mock_widget(
            QPushButton, text="Test Button", enabled=True
        )

        # Use in test
        assert mock_button.text == "Test Button"
        assert mock_button.enabled == True

        # Verify interactions
        mock_button.click()
        mock_button.click.assert_called_once()


# ============================================================================
# Test Organization Patterns
# ============================================================================


class TestSuite:
    """Base class for organizing related tests."""

    @classmethod
    def setup_class(cls):
        """Set up test suite."""
        cls.shared_resources = {}

    @classmethod
    def teardown_class(cls):
        """Tear down test suite."""
        cls.shared_resources.clear()


@pytest.mark.quality
class TestShotWorkflow(TestSuite):
    """Complete workflow tests for shot operations."""

    def test_complete_shot_workflow(self, shot_factory, scene_factory, isolated_test):
        """Test complete shot workflow from discovery to launch."""
        with isolated_test.isolated_filesystem() as tmpdir:
            # Create test data
            shot = shot_factory.create()
            scenes = scene_factory.create_batch(5)

            # Test workflow steps
            self._test_shot_discovery(shot)
            self._test_scene_finding(scenes)
            self._test_launch_application(shot)

    def _test_shot_discovery(self, shot):
        """Test shot discovery step."""
        assert shot["name"]
        assert shot["workspace_path"]

    def _test_scene_finding(self, scenes):
        """Test scene finding step."""
        assert len(scenes) == 5
        assert all(s.user for s in scenes)

    def _test_launch_application(self, shot):
        """Test application launch step."""
        # Mock launch
        pass


if __name__ == "__main__":
    # Example usage
    print("Test Quality Patterns Examples")
    print("=" * 50)

    # Create test data
    shot = ShotFactory.create()
    print(f"Created shot: {shot}")

    # Build complex object
    model = (
        ShotModelBuilder()
        .with_shots(ShotFactory.create_batch(3))
        .with_cache_disabled()
        .build()
    )
    print(f"Built model with {len(model._shots)} shots")

    # Create isolated test
    test = IsolatedTest()
    with test.isolated_filesystem() as tmpdir:
        print(f"Created isolated filesystem at: {tmpdir}")
