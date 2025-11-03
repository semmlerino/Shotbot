"""Type-safe test patterns and helpers for ShotBot test suite.

This module provides type-safe patterns, protocols, and helpers to improve
type safety across the test suite while maintaining test effectiveness.

Following test-type-safety-specialist principles:
- Prefer real objects over mocks when possible
- Use protocols for mock interfaces when mocking is necessary
- Provide proper type annotations for all test helpers
- Use specific basedpyright ignore comments when needed
- Document why type: ignore is used

Examples:
    # Prefer real objects
    cache_manager = create_real_cache_manager(tmp_path)

    # When mocking is needed, use typed protocols
    mock_launcher = create_typed_launcher_mock()

    # Type-safe fixture usage
    def test_with_real_data(real_shot_data: ShotTestData) -> None:
        assert real_shot_data.shot.show == "TEST"
"""

from __future__ import annotations

# Standard library imports
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    NamedTuple,
    Protocol,
    TypeVar,
    cast,
)
from unittest.mock import MagicMock, Mock

# Third-party imports
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

# Local application imports
from tests.helpers.synchronization import process_qt_events


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable, Iterator

    # Third-party imports
    from PySide6.QtGui import QPixmap

    # Local application imports
    from cache_manager import CacheManager
    from process_pool_manager import ProcessPoolManager
    from shot_model import Shot

# pyright: basic
# pyright: reportPrivateUsage=false

__all__ = [
    "CacheProtocol",
    "LauncherProtocol",
    "ProcessPoolProtocol",
    "ShotTestData",
    "ThreadSafeTestImage",
    "assert_signal_emitted",
    "create_real_cache_manager",
    "create_test_shot_data",
    "create_typed_launcher_mock",
    "create_typed_process_pool_mock",
    "isolated_test_env",
    "wait_for_qt_events",
]

T = TypeVar("T")


# ============================================================================
# PROTOCOLS FOR TYPE-SAFE MOCKING (Use only when real objects aren't viable)
# ============================================================================


class ProcessPoolProtocol(Protocol):
    """Protocol for ProcessPoolManager interface used in tests.

    Use this only when real ProcessPoolManager can't be used due to
    external dependencies (bash sessions, workspace commands).
    """

    def execute_workspace_command(
        self, command: str, cache_ttl: int = 300, timeout: int = 30
    ) -> str:
        """Execute workspace command with caching."""
        ...

    def get_instance(self) -> ProcessPoolManager:
        """Get singleton instance."""
        ...


class LauncherProtocol(Protocol):
    """Protocol for LauncherManager interface used in tests."""

    def launch_application(self, app_name: str, shot_name: str) -> bool:
        """Launch application with shot context."""
        ...

    def create_custom_launcher(self, launcher_data: dict[str, Any]) -> str:
        """Create custom launcher configuration."""
        ...


class CacheProtocol(Protocol):
    """Protocol for minimal CacheManager interface in tests."""

    def get_thumbnail(self, path: str) -> QPixmap | None:
        """Get cached thumbnail."""
        ...

    def cache_shots(self, shots: list[dict[str, Any]]) -> None:
        """Cache shot data."""
        ...


# ============================================================================
# TYPED TEST DATA STRUCTURES
# ============================================================================


class ShotTestData(NamedTuple):
    """Type-safe container for shot test data."""

    shot: Shot
    workspace_path: Path
    thumbnail_path: Path | None = None
    metadata: dict[str, Any] | None = None


class ThreadSafeTestImage:
    """Thread-safe test image replacement for QPixmap in tests.

    Provides a mock QPixmap interface without Qt dependencies.
    Use only in thread safety tests where real QPixmap would cause issues.
    """

    def __init__(self, width: int = 100, height: int = 100) -> None:
        self._width = width
        self._height = height
        self._lock = threading.Lock()

    def width(self) -> int:
        """Get image width."""
        with self._lock:
            return self._width

    def height(self) -> int:
        """Get image height."""
        with self._lock:
            return self._height

    def isNull(self) -> bool:
        """Check if image is null."""
        return False

    def save(self, path: str, output_format: str = "JPEG") -> bool:
        """Mock save operation."""
        with self._lock:
            return True


# ============================================================================
# REAL OBJECT FACTORIES (Preferred over mocks)
# ============================================================================


def create_real_cache_manager(cache_dir: Path) -> CacheManager:
    """Create real CacheManager for testing.

    Prefer this over mocking CacheManager as it tests actual behavior.

    Args:
        cache_dir: Temporary directory for cache storage

    Returns:
        Real CacheManager instance with temporary storage
    """
    # Local application imports
    from cache_manager import CacheManager

    return CacheManager(cache_dir=cache_dir)


def create_test_shot_data(
    show: str = "TEST",
    sequence: str = "seq01",
    shot: str = "0010",
    workspace_path: Path | None = None,
) -> ShotTestData:
    """Create real shot test data with proper file structure.

    Args:
        show: Show name
        sequence: Sequence name
        shot: Shot name
        workspace_path: Custom workspace path (creates temp if None)

    Returns:
        ShotTestData with real Shot object and paths
    """
    # Local application imports
    from shot_model import Shot

    if workspace_path is None:
        temp_dir = Path(tempfile.mkdtemp())
        workspace_path = temp_dir / show / "shots" / sequence / f"{sequence}_{shot}"
        workspace_path.mkdir(parents=True, exist_ok=True)

    shot_obj = Shot(show, sequence, shot, str(workspace_path))

    return ShotTestData(
        shot=shot_obj,
        workspace_path=workspace_path,
        thumbnail_path=None,
        metadata={"created_for_test": True},
    )


# ============================================================================
# TYPE-SAFE MOCK FACTORIES (Use only when necessary)
# ============================================================================


def create_typed_process_pool_mock() -> ProcessPoolProtocol:
    """Create type-safe ProcessPoolManager mock.

    Use only when real ProcessPoolManager can't work due to external deps.

    Returns:
        Properly typed mock implementing ProcessPoolProtocol
    """
    mock = MagicMock(spec=ProcessPoolProtocol)

    # Configure default behaviors with proper typing
    mock.execute_workspace_command.return_value = """workspace /shows/TEST/seq01/0010
workspace /shows/TEST/seq01/0020"""

    # Type assertion to satisfy type checker
    return cast("ProcessPoolProtocol", mock)


def create_typed_launcher_mock() -> LauncherProtocol:
    """Create type-safe LauncherManager mock.

    Returns:
        Properly typed mock implementing LauncherProtocol
    """
    mock = MagicMock(spec=LauncherProtocol)
    mock.launch_application.return_value = True
    mock.create_custom_launcher.return_value = "test_launcher_id"

    return cast("LauncherProtocol", mock)


# ============================================================================
# TEST ENVIRONMENT HELPERS
# ============================================================================


@contextmanager
def isolated_test_env(cache_dir: Path | None = None) -> Iterator[dict[str, Any]]:
    """Provide isolated test environment with real components.

    Args:
        cache_dir: Custom cache directory (creates temp if None)

    Yields:
        Dictionary with initialized test components
    """
    temp_dir = tempfile.TemporaryDirectory()
    test_cache_dir = cache_dir or Path(temp_dir.name) / "cache"
    test_cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        env = {
            "cache_manager": create_real_cache_manager(test_cache_dir),
            "cache_dir": test_cache_dir,
            "temp_dir": Path(temp_dir.name),
        }
        yield env
    finally:
        # Cleanup real resources
        if "cache_manager" in env:
            # Ensure proper cleanup of Qt resources
            env["cache_manager"].clear_cache()
        temp_dir.cleanup()


def wait_for_qt_events(timeout_ms: int = 100) -> None:
    """Wait for Qt events to process.

    Args:
        timeout_ms: Maximum time to wait in milliseconds
    """
    app = QApplication.instance()
    if app is not None:
        process_qt_events(app, timeout_ms)


# ============================================================================
# TYPE-SAFE SIGNAL TESTING
# ============================================================================


def assert_signal_emitted(
    signal: Any,  # Qt Signal
    expected_count: int = 1,
    timeout_ms: int = 1000,
    expected_args: list[Any | None] | None = None,
) -> list[Any]:
    """Assert that a Qt signal was emitted with proper typing.

    Args:
        signal: Qt signal to monitor
        expected_count: Expected number of emissions
        timeout_ms: Timeout in milliseconds
        expected_args: Expected signal arguments (if any)

    Returns:
        List of signal emissions for further analysis

    Raises:
        AssertionError: If signal wasn't emitted as expected
    """
    # Third-party imports
    from PySide6.QtTest import QSignalSpy

    spy = QSignalSpy(signal)

    # Wait for signal with timeout
    start_time = time.time()
    while len(spy) < expected_count and (time.time() - start_time) * 1000 < timeout_ms:
        wait_for_qt_events(10)

    assert len(spy) == expected_count, (
        f"Expected {expected_count} signal emissions, got {len(spy)}"
    )

    if expected_args is not None and len(spy) > 0:
        actual_args = list(spy.at(0))  # First emission args
        assert actual_args == expected_args, (
            f"Expected signal args {expected_args}, got {actual_args}"
        )

    return [list(emission) for emission in spy]


# ============================================================================
# THREAD SAFETY TEST HELPERS
# ============================================================================


class TypedThreadTestHelper:
    """Helper for type-safe thread testing patterns."""

    def __init__(self, thread_count: int = 10) -> None:
        self.thread_count = thread_count
        self.results: list[Any] = []
        self.errors: list[Exception] = []
        self._lock = threading.Lock()

    def run_concurrent_operations(
        self,
        operation: Callable[[], T],
        operation_count: int | None = None,
    ) -> list[T]:
        """Run operations concurrently with proper error handling.

        Args:
            operation: Operation to run concurrently
            operation_count: Number of operations (defaults to thread_count)

        Returns:
            List of successful operation results
        """
        # Standard library imports
        import concurrent.futures

        count = operation_count or self.thread_count

        def safe_operation() -> T | None:
            try:
                return operation()
            except Exception as e:
                with self._lock:
                    self.errors.append(e)
                return None

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.thread_count
        ) as executor:
            futures = [executor.submit(safe_operation) for _ in range(count)]
            results = [f.result() for f in futures]

        # Filter out None results from errors
        return [r for r in results if r is not None]


    def assert_no_errors(self) -> None:
        """Assert that no errors occurred during concurrent operations."""
        if self.errors:
            error_msgs = [str(e) for e in self.errors]
            raise AssertionError(f"Concurrent operations had errors: {error_msgs}")


# ============================================================================
# BASEDPYRIGHT-SPECIFIC HELPERS
# ============================================================================


def suppress_mock_member_access(mock_obj: Mock, attr_name: str) -> Any:
    """Helper to suppress basedpyright warnings for mock attribute access.

    Use this when you need to access dynamic mock attributes but want to
    document the type safety issue explicitly.

    Args:
        mock_obj: Mock object
        attr_name: Attribute name to access

    Returns:
        Mock attribute value
    """
    # Using getattr to make the dynamic access explicit
    return getattr(mock_obj, attr_name)  # pyright: ignore[reportUnknownMemberType]


def typed_mock_assert_called_with(
    mock_method: Any,  # Mock method
    *expected_args: Any,
    **expected_kwargs: Any,
) -> None:
    """Type-safe wrapper for mock.assert_called_with().

    Args:
        mock_method: Mock method to check
        *expected_args: Expected positional arguments
        **expected_kwargs: Expected keyword arguments
    """
    # Explicit ignore for mock method access
    mock_method.assert_called_with(*expected_args, **expected_kwargs)  # pyright: ignore[reportUnknownMemberType]


# ============================================================================
# INTEGRATION TEST PATTERNS
# ============================================================================


@pytest.fixture
def real_test_environment() -> Iterator[dict[str, Any]]:
    """Pytest fixture providing real test environment.

    Yields:
        Dictionary with real components for integration testing
    """
    with isolated_test_env() as env:
        # Add QApplication if needed
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
            env["app"] = app
            env["created_app"] = True
        else:
            env["app"] = app
            env["created_app"] = False

        yield env


@pytest.fixture
def typed_shot_factory() -> Callable[[str, str, str], ShotTestData]:
    """Factory fixture for creating typed shot test data."""
    return create_test_shot_data


# ============================================================================
# USAGE EXAMPLES AND DOCUMENTATION
# ============================================================================


def example_real_object_test() -> None:
    """Example of testing with real objects (preferred approach).

    This demonstrates the preferred pattern of using real components
    with temporary storage instead of mocking.
    """
    with isolated_test_env() as env:
        cache_manager = env["cache_manager"]

        # Test real behavior
        shots_data = [
            {
                "show": "TEST",
                "sequence": "seq01",
                "shot": "0010",
                "workspace_path": "/test/path",
            }
        ]

        # Real method call, real behavior
        cache_manager.cache_shots(shots_data)

        # Verify real state
        cached_shots = cache_manager.get_cached_shots()
        assert len(cached_shots) == 1
        assert cached_shots[0]["show"] == "TEST"


def example_typed_mock_test() -> None:
    """Example of type-safe mocking when real objects can't be used.

    Use this pattern only when external dependencies make real objects
    unsuitable (network, filesystem, external processes).
    """
    # Create typed mock for external dependency
    mock_pool = create_typed_process_pool_mock()

    # Configure specific behavior
    mock_pool.execute_workspace_command.return_value = "workspace /test/path"  # pyright: ignore[reportUnknownMemberType]

    # Use in test with proper typing
    result = mock_pool.execute_workspace_command("ws -sg")
    assert "workspace" in result


def example_signal_testing() -> None:
    """Example of type-safe Qt signal testing."""

    class TestSignalEmitter(QObject):
        test_signal = Signal(str)

    emitter = TestSignalEmitter()

    # Type-safe signal assertion
    def emit_test_signal() -> None:
        emitter.test_signal.emit("test_data")

    # This will properly wait for and verify the signal
    emit_test_signal()
    emissions = assert_signal_emitted(
        emitter.test_signal, expected_count=1, expected_args=["test_data"]
    )

    assert len(emissions) == 1
    assert emissions[0] == ["test_data"]


if __name__ == "__main__":
    # Run examples to verify patterns work
    example_real_object_test()
    example_typed_mock_test()
    print("✓ All type-safe test patterns validated")
