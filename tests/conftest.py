#!/usr/bin/env python3
"""pytest configuration and fixtures for ShotBot tests.

Provides common test fixtures and utilities for unit and integration tests
specific to the ShotBot VFX asset management application.
"""

from __future__ import annotations

import os
import warnings


# ==============================================================================
# CRITICAL: Force Qt to use offscreen platform for ALL QApplication instances
# ==============================================================================
# This MUST be set before any Qt imports to prevent "real widgets" from appearing
# during tests, which causes crashes in WSL and resource exhaustion.
# See: https://doc.qt.io/qt-6/qguiapplication.html#platform
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox


if TYPE_CHECKING:
    from collections.abc import Iterator

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ==============================================================================
# Qt Application Fixtures
# ==============================================================================


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """Create QApplication instance for Qt widget testing.

    This fixture is session-scoped to avoid creating multiple QApplications
    which causes issues in PySide6.

    Uses offscreen platform to prevent widgets from actually displaying
    during test execution, which speeds up tests and prevents UI popups.

    CRITICAL: The QT_QPA_PLATFORM environment variable is set to "offscreen"
    at the top of this file to ensure ALL QApplication instances use the
    correct platform, even if created before this fixture runs.
    """
    app = QApplication.instance()
    if app is None:
        # Use offscreen platform to prevent actual widget display
        # The environment variable set at the top of this file ensures this is redundant
        # but explicit, following the principle of defense in depth
        app = QApplication(["-platform", "offscreen"])
    else:
        # QApplication already exists - validate it's using the correct platform
        # This should always be true now due to the environment variable
        platform = os.environ.get("QT_QPA_PLATFORM", "")
        if platform != "offscreen":
            warnings.warn(
                f"QApplication was created with platform '{platform}' instead of 'offscreen'. "
                f"This may cause 'real widgets' to appear during tests and crash in WSL. "
                f"The QT_QPA_PLATFORM environment variable should be set to 'offscreen' "
                f"before any Qt imports.",
                RuntimeWarning,
                stacklevel=2
            )

    return app
    # Don't quit app as it may be used by other tests


# ==============================================================================
# Mock Fixtures
# ==============================================================================


@pytest.fixture
def mock_settings() -> Iterator[Mock]:
    """Mock QSettings for testing settings persistence."""
    settings_data: dict[str, object] = {}

    def mock_value(key: str, default: object = None, value_type: type | None = None) -> object:
        value = settings_data.get(key, default)
        if value_type and value is not None:
            return value_type(value)
        return value

    def mock_set_value(key: str, value: object) -> None:
        settings_data[key] = value

    mock_instance = Mock(spec=QSettings)
    mock_instance.value = mock_value
    mock_instance.setValue = mock_set_value

    return mock_instance


# ==============================================================================
# Temporary Directory Fixtures
# ==============================================================================


@pytest.fixture
def temp_shows_root() -> Iterator[Path]:
    """Create temporary shows root directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        shows_root = Path(temp_dir)
        yield shows_root


@pytest.fixture
def temp_cache_dir() -> Iterator[Path]:
    """Create temporary cache directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = Path(temp_dir)
        yield cache_dir


@pytest.fixture
def cache_manager(temp_cache_dir: Path) -> Iterator[object]:
    """Create CacheManager instance for testing."""
    from cache_manager import (
        CacheManager,
    )

    manager = CacheManager(cache_dir=temp_cache_dir)
    yield manager
    # Cleanup
    manager.clear_cache()


@pytest.fixture
def real_cache_manager(cache_manager: object) -> Iterator[object]:
    """Alias for cache_manager fixture (for compatibility)."""
    return cache_manager


# ==============================================================================
# Qt Cleanup (Critical for Test Isolation)
# ==============================================================================


@pytest.fixture(autouse=True)
def qt_cleanup(qapp: QApplication) -> Iterator[None]:
    """Ensure Qt state is clean between tests.

    This autouse fixture processes Qt events before and after each test
    to ensure widgets are fully cleaned up and Qt is in a stable state.

    Also waits for QThread background threads to finish to prevent crashes
    from AsyncShotLoader or other background operations.

    Critical for preventing Qt state pollution that causes crashes when
    running the full test suite (tests pass individually but crash together).

    See TESTING.md section "Test Isolation and Parallel Execution" for details.
    """
    # Third-party imports
    from PySide6.QtCore import QThreadPool

    # Process any pending events before test
    qapp.processEvents()
    # Process all pending deleteLater() calls from previous tests
    qapp.sendPostedEvents(None, 0)  # QEvent::DeferredDelete = 0

    yield

    # Process events after test to ensure all deleteLater() calls are executed
    qapp.processEvents()
    qapp.sendPostedEvents(None, 0)  # Process DeferredDelete events

    # Wait for any background QThreads to finish (max 2000ms)
    # This prevents AsyncShotLoader or other background threads from
    # interfering with subsequent tests.
    # Increased from 500ms to 2000ms to allow MainWindow async operations
    # (shot model initialization, cache loading) to complete fully.
    QThreadPool.globalInstance().waitForDone(2000)


@pytest.fixture(autouse=True)
def clear_module_caches() -> Iterator[None]:
    """Clear all module-level caches before each test.

    This autouse fixture ensures that cached values from previous tests
    don't contaminate the current test. Module-level caches are a common
    source of test isolation failures in parallel execution.

    Clearing happens FIRST (before test execution) to prevent
    contamination from previous tests on any worker.

    See TESTING.md section "Common Root Causes of Isolation Failures" for details.
    """
    # Local application imports - import here to avoid circular dependencies
    from utils import clear_all_caches

    # Clear ALL caches FIRST, before any test operations
    clear_all_caches()

    yield

    # Optional: Clear caches after test as well (defense in depth)
    clear_all_caches()


@pytest.fixture(autouse=True)
def mock_message_boxes_unless_overridden() -> Iterator[None]:
    """Mock QMessageBox dialogs with low-priority defaults.

    This autouse fixture provides default mocks for QMessageBox to prevent
    real dialogs from appearing. Individual tests can override these mocks
    with their own patch.object() calls - test-specific patches take priority.

    Critical for:
    - Preventing real widgets from appearing ("getting real widgets" issue)
    - Avoiding timeouts from modal dialogs waiting for user input
    - Preventing resource exhaustion under high parallel load

    Note:
        These are DEFAULT mocks only. Tests that patch QMessageBox methods
        in their own fixtures or test bodies will override these defaults.
        This is intentional - test-specific mocks should take precedence.
    """
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
         patch.object(QMessageBox, "warning"), \
         patch.object(QMessageBox, "critical"), \
         patch.object(QMessageBox, "information"):
        yield


@pytest.fixture(autouse=True)
def cleanup_threading_state(qtbot: QtBot) -> Iterator[None]:
    """Clean up all threading and singleton state between tests.

    This autouse fixture ensures clean state for each test by:
    - Resetting ProcessPoolManager singleton
    - Clearing ThreadSafeWorker zombie threads
    - Processing pending Qt events

    Args:
        qtbot: pytest-qt's QtBot fixture for Qt event processing

    Note:
        This is an autouse fixture that runs automatically for every test.
        It executes cleanup after the test completes (yield).
    """
    yield

    # Qt Event Processing FIRST - before any cleanup that might delete Qt objects
    # This ensures Qt is in a stable state before we start tearing things down
    try:
        qtbot.wait(10)  # Reduced from 50ms - just enough to process pending events
    except RuntimeError:
        # Qt objects may already be deleted, ignore
        pass

    # NotificationManager Cleanup (must happen early to avoid Qt object access after deletion)
    from notification_manager import NotificationManager
    NotificationManager.cleanup()

    # ProcessPoolManager Cleanup
    from process_pool_manager import ProcessPoolManager

    if ProcessPoolManager._instance is not None:
        try:
            ProcessPoolManager._instance.shutdown(timeout=1.0)
        except Exception as e:
            import warnings

            warnings.warn(f"ProcessPoolManager shutdown failed: {e}", RuntimeWarning)

    ProcessPoolManager._instance = None
    ProcessPoolManager._initialized = False

    # ThreadSafeWorker Zombie Cleanup
    from PySide6.QtCore import QMutexLocker

    from thread_safe_worker import ThreadSafeWorker

    with QMutexLocker(ThreadSafeWorker._zombie_mutex):
        zombie_count = len(ThreadSafeWorker._zombie_threads)
        if zombie_count > 0:
            cleaned = ThreadSafeWorker.cleanup_old_zombies()
            ThreadSafeWorker._zombie_threads.clear()
            ThreadSafeWorker._zombie_timestamps.clear()


@pytest.fixture
def mock_subprocess_workspace() -> Iterator[None]:
    """Mock subprocess.run for tests that call VFX workspace commands.

    Use this fixture explicitly in tests that need subprocess mocking.
    Most tests don't need subprocess mocking at all.

    Provides:
    - Mock responses for 'ws' (workspace) commands
    - Prevents "ws: command not found" errors
    - Returns realistic workspace command output

    Usage:
        def test_workspace_parsing(mock_subprocess_workspace):
            # Test code that calls subprocess.run with workspace commands
            pass
    """
    def mock_run_side_effect(*args, **kwargs):
        """Mock subprocess.run with realistic workspace command responses."""
        # Extract the command being run
        cmd = args[0] if args else kwargs.get("args", [])

        # Handle different command patterns
        if (
            isinstance(cmd, list)
            and len(cmd) >= 2
            and ("ws -sg" in " ".join(cmd) or "ws" in cmd[-1])
        ):
            # Return realistic workspace command output
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "workspace /shows/test_show/shots/seq01/seq01_0010"
            mock_result.stderr = ""
            return mock_result

        # Default: return empty but successful result
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        return mock_result

    with patch("subprocess.run", side_effect=mock_run_side_effect):
        yield


# ==============================================================================
# Mock Environment Setup
# ==============================================================================


@pytest.fixture
def mock_environment() -> Iterator[dict[str, str]]:
    """Set up mock environment variables for testing."""
    original_env = os.environ.copy()

    # Set test environment
    os.environ["SHOTBOT_MODE"] = "test"
    os.environ["USER"] = "test_user"

    test_env = {
        "SHOTBOT_MODE": "test",
        "USER": "test_user",
    }

    yield test_env

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def isolated_test_environment(qapp: QApplication) -> Iterator[None]:
    """Provide isolated test environment with cache clearing for Qt widgets.

    This fixture ensures complete test isolation by:
    1. Clearing all utility caches (VersionUtils, path cache, etc.)
    2. Processing Qt events to ensure clean state
    3. Providing proper cleanup after test execution

    Critical for parallel test execution with pytest-xdist to prevent
    cache pollution between tests running in different workers.

    See TESTING.md section "Test Isolation and Parallel Execution".
    """
    # Import here to avoid circular imports
    from utils import (
        clear_all_caches,
    )

    # Clear all utility caches before test
    clear_all_caches()

    # Process Qt events for clean state
    qapp.processEvents()
    qapp.sendPostedEvents(None, 0)  # QEvent::DeferredDelete

    yield

    # Clear caches after test for next test's isolation
    clear_all_caches()

    # Final Qt cleanup
    qapp.processEvents()
    qapp.sendPostedEvents(None, 0)


# ==============================================================================
# Test Data Fixtures
# ==============================================================================


@pytest.fixture
def sample_shot_data() -> dict[str, object]:
    """Sample shot data for testing."""
    return {
        "show": "TestShow",
        "sequence": "SEQ001",
        "shot": "0010",
        "workspace_path": "/shows/TestShow/shots/SEQ001/SEQ001_0010",
    }


@pytest.fixture
def sample_threede_scene_data() -> dict[str, object]:
    """Sample 3DE scene data for testing."""
    return {
        "filepath": "/shows/TestShow/shots/SEQ001/SEQ001_0010/user/test_user/3de/SEQ001_0010_v001.3de",
        "show": "TestShow",
        "sequence": "SEQ001",
        "shot": "0010",
        "user": "test_user",
        "filename": "SEQ001_0010_v001.3de",
        "modified_time": 1234567890.0,
        "workspace_path": "/shows/TestShow/shots/SEQ001/SEQ001_0010",
    }


@pytest.fixture
def make_test_shot(tmp_path: Path):
    """Factory fixture for creating test Shot instances.

    Implements TestShotFactory protocol from test_protocols.py.
    """
    # Local application imports
    from shot_model import (
        Shot,
    )

    def _make_shot(
        show: str = "test",
        sequence: str = "seq01",
        shot: str = "0010",
        with_thumbnail: bool = True,
    ) -> Shot:
        """Create a test Shot instance with optional thumbnail."""
        workspace_path = str(tmp_path / "shows" / show / "shots" / sequence / f"{sequence}_{shot}")

        # Create workspace directory
        Path(workspace_path).mkdir(parents=True, exist_ok=True)

        # Create thumbnail if requested
        if with_thumbnail:
            thumbnail_dir = Path(workspace_path) / "editorial" / "thumbnails"
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            thumbnail_file = thumbnail_dir / f"{sequence}_{shot}.jpg"
            thumbnail_file.write_bytes(b"fake image data")

        return Shot(
            show=show,
            sequence=sequence,
            shot=shot,
            workspace_path=workspace_path,
        )

    return _make_shot



@pytest.fixture
def make_test_filesystem(tmp_path: Path):
    """Factory fixture for creating TestFileSystem instances.

    Returns a callable that creates TestFileSystem instances for
    testing file operations with VFX directory structures.

    Example usage:
        def test_scene_discovery(make_test_filesystem):
            fs = make_test_filesystem()
            shot_path = fs.create_vfx_structure("show1", "seq01", "0010")
            fs.create_file(shot_path / "user/artist/scene.3de", "content")
    """
    # Import here to avoid circular imports
    from tests.test_doubles_extended import (
        TestFileSystem,
    )

    def _make_filesystem() -> TestFileSystem:
        """Create a TestFileSystem instance with tmp_path as base."""
        return TestFileSystem(base_path=tmp_path)

    return _make_filesystem



@pytest.fixture
def make_real_3de_file(tmp_path: Path):
    """Factory fixture for creating real 3DE files in VFX directory structure.

    Returns a callable that creates a complete VFX directory structure with
    a real 3DE file for testing ThreeDEScene functionality.

    Example usage:
        def test_scene(make_real_3de_file):
            scene_path = make_real_3de_file("show1", "seq01", "0010", "artist1")
            # scene_path points to the .3de file
            # scene_path.parent.parent.parent.parent is the workspace_path
    """

    def _make_3de_file(
        show: str,
        seq: str,
        shot: str,
        user: str,
        plate: str = "BG01",
        filename: str = "scene.3de",
    ) -> Path:
        """Create a real 3DE file in VFX directory structure.

        Args:
            show: Show name
            seq: Sequence name
            shot: Shot name
            user: User/artist name
            plate: Plate name (default: "BG01")
            filename: 3DE filename (default: "scene.3de")

        Returns:
            Path to the created 3DE file
        """
        # Create VFX directory structure
        # Structure: shows/{show}/shots/{seq}/{seq}_{shot}/user/{user}/3de/
        workspace_path = tmp_path / "shows" / show / "shots" / seq / f"{seq}_{shot}"
        threede_dir = workspace_path / "user" / user / "3de"
        threede_dir.mkdir(parents=True, exist_ok=True)

        # Create the 3DE file with minimal valid content
        scene_file = threede_dir / filename
        scene_file.write_text(f"# 3DE Scene File\n# Show: {show}\n# Seq: {seq}\n# Shot: {shot}\n# User: {user}\n# Plate: {plate}\n")

        return scene_file

    return _make_3de_file


@pytest.fixture
def test_process_pool():
    """Test double for ProcessPoolManager implementing ProcessPoolProtocol.

    Provides a configurable test double that tracks calls and allows
    setting custom outputs and errors.
    """

    class TestProcessPool:
        """Test double for process pool operations."""

        def __init__(self) -> None:
            self.should_fail = False
            self.fail_with_timeout = False
            self.call_count = 0
            self.commands: list[str] = []
            self._outputs_queue: list[str] = []
            self._errors: str = ""
            self._repeat_output: bool = True  # By default, repeat the same output

        def set_outputs(self, *outputs: str, repeat: bool = True) -> None:
            """Set multiple outputs to return from execute_workspace_command.

            Args:
                *outputs: Variable number of output strings
                repeat: If True (default), returns the last output repeatedly for all calls.
                       If False, pops outputs sequentially and returns empty when exhausted.

            Default behavior (repeat=True) handles race conditions with background threads
            that may call execute_workspace_command() multiple times unpredictably.
            Use repeat=False for tests that need specific sequential outputs.
            """
            self._outputs_queue = list(outputs)
            self._repeat_output = repeat

        def set_errors(self, error: str) -> None:
            """Set errors to raise from execute_workspace_command."""
            self._errors = error

        def execute_workspace_command(
            self,
            command: str,
            cache_ttl: int | None = None,
            timeout: int | None = None,
        ) -> str:
            """Execute a workspace command (test double)."""
            self.call_count += 1
            self.commands.append(command)

            if self.fail_with_timeout:
                raise TimeoutError("Simulated timeout")

            if self.should_fail or self._errors:
                raise RuntimeError(self._errors or "Test error")

            # Return output based on mode
            if self._outputs_queue:
                if self._repeat_output:
                    # Return the last output repeatedly (handles background threads)
                    return self._outputs_queue[-1]
                # Pop sequentially (for tests needing specific order)
                return self._outputs_queue.pop(0)
            return ""

        def invalidate_cache(self, command: str) -> None:
            """Invalidate the cache for a specific command (test double)."""
            # Track that cache invalidation was called
            self.commands.append(f"invalidate:{command}")

        def reset(self) -> None:
            """Reset the test double state."""
            self.should_fail = False
            self.fail_with_timeout = False
            self.call_count = 0
            self.commands = []
            self._outputs_queue = []
            self._errors = ""
            self._repeat_output = True

    return TestProcessPool()


@pytest.fixture(autouse=True)
def mock_process_pool_manager(monkeypatch, test_process_pool):
    """Globally patch ProcessPoolManager to use test double.

    This autouse fixture ensures that ALL code (including AsyncShotLoader,
    MainWindow initialization, etc.) uses the test double instead of trying
    to execute real subprocess commands.

    Critical for preventing worker crashes from background threads calling
    non-existent commands like 'ws -sg' during test execution.
    """
    # Patch ProcessPoolManager.get_instance() to return our test double
    monkeypatch.setattr(
        "process_pool_manager.ProcessPoolManager.get_instance",
        lambda: test_process_pool,
    )


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
    from launcher import (
        CustomLauncher,
    )

    def _make_launcher(
        name: str = "Test Launcher",
        command: str = "echo {shot_name}",
        description: str = "Test launcher",
        category: str = "test",
        launcher_id: str | None = None,
    ) -> CustomLauncher:
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


@pytest.fixture
def real_shot_model(tmp_path: Path, test_process_pool, cache_manager):
    """Factory fixture for creating real ShotModel instances with test data.

    Returns a ShotModel instance configured with a temporary shows root,
    a test process pool, and a shared cache manager.
    """
    # Local application imports
    from shot_model import (
        ShotModel,
    )

    # Create shows root
    shows_root = tmp_path / "shows"
    shows_root.mkdir(exist_ok=True)

    # Create ShotModel instance with test process pool and shared cache manager
    return ShotModel(cache_manager=cache_manager, process_pool=test_process_pool)



# ==============================================================================
# Pytest Configuration
# ==============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "fast: mark test as fast running")
    config.addinivalue_line("markers", "qt: mark test as requiring Qt")
    config.addinivalue_line(
        "markers",
        "concurrent: mark test as testing concurrent/threading behavior",
    )
    config.addinivalue_line("markers", "thread_safety: mark test as testing thread safety")
    config.addinivalue_line("markers", "performance: mark test as testing performance")
    config.addinivalue_line("markers", "critical: mark test as critical/high priority")
    config.addinivalue_line("markers", "gui_mainwindow: mark test as requiring main window GUI")
    config.addinivalue_line("markers", "qt_heavy: mark test as Qt-intensive")
    config.addinivalue_line("markers", "integration_unsafe: mark test as potentially unsafe integration test")
    config.addinivalue_line("markers", "integration_safe: mark test as safe integration test")
    config.addinivalue_line(
        "markers",
        "skip_if_parallel: skip test when running in parallel mode due to Qt state pollution",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip tests marked with skip_if_parallel when running with xdist."""
    # Check if test has skip_if_parallel marker
    if item.get_closest_marker("skip_if_parallel"):
        # Check if running with xdist (parallel execution)
        if hasattr(item.config, "workerinput"):  # xdist worker
            pytest.skip("Test skipped in parallel execution due to Qt state pollution")
