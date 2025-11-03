"""Type-safe conftest configuration for ShotBot test suite.

This module provides type-safe pytest fixtures and configuration that can be
imported by specific test files needing enhanced type safety.

Key principles:
- Real objects over mocks whenever possible
- Proper type annotations for all fixtures
- Protocols for necessary mock interfaces
- Clear documentation of type safety trade-offs

Usage:
    # In test files that need type safety
    from tests.conftest_type_safe import typed_cache_manager, real_shot_data
"""

from __future__ import annotations

# Standard library imports
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any


# ==============================================================================
# CRITICAL: Force Qt to use offscreen platform BEFORE any Qt imports
# ==============================================================================
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Third-party imports
import pytest
from PySide6.QtWidgets import QApplication

# Local application imports
# pyright: reportPrivateUsage=false
# Import test patterns
from tests.test_type_safe_patterns import (
    ProcessPoolProtocol,
    ShotTestData,
    create_real_cache_manager,
    create_test_shot_data,
    create_typed_process_pool_mock,
)


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Iterator
    from unittest.mock import Mock


class TestQApplication:
    """Type-safe QApplication wrapper for tests."""

    _instance: QApplication | None = None

    @classmethod
    def get_instance(cls) -> QApplication:
        """Get or create test QApplication instance with offscreen platform."""
        if cls._instance is None:
            existing = QApplication.instance()
            if existing is not None and isinstance(existing, QApplication):
                cls._instance = existing
            else:
                # Create with offscreen platform explicitly
                cls._instance = QApplication(["-platform", "offscreen"])
        return cls._instance


# ============================================================================
# TYPE-SAFE FIXTURES
# ============================================================================


@pytest.fixture(scope="session")
def qt_app() -> Iterator[QApplication]:
    """Session-scoped QApplication fixture with proper cleanup."""
    return TestQApplication.get_instance()
    # Note: Don't quit() session-scoped app as other tests may need it


@pytest.fixture
def temp_cache_dir() -> Iterator[Path]:
    """Temporary cache directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_path = Path(temp_dir) / "cache"
        cache_path.mkdir(parents=True)
        yield cache_path


@pytest.fixture
def typed_cache_manager(temp_cache_dir: Path) -> Iterator[Any]:  # CacheManager
    """Type-safe CacheManager fixture using real implementation.

    Returns:
        Real CacheManager instance with temporary storage.
    """
    cache_manager = create_real_cache_manager(temp_cache_dir)
    try:
        yield cache_manager
    finally:
        # Ensure proper cleanup
        cache_manager.clear_cache()


@pytest.fixture
def real_shot_data() -> ShotTestData:
    """Real shot test data with actual file structure."""
    return create_test_shot_data(show="TEST_SHOW", sequence="seq01", shot="0010")


@pytest.fixture
def multiple_shot_data() -> list[ShotTestData]:
    """Multiple shot test data entries."""
    return [
        create_test_shot_data("SHOW_A", "seq01", "0010"),
        create_test_shot_data("SHOW_A", "seq01", "0020"),
        create_test_shot_data("SHOW_B", "seq02", "0010"),
    ]


@pytest.fixture
def typed_process_pool_mock() -> ProcessPoolProtocol:
    """Type-safe ProcessPoolManager mock.

    Use only when real ProcessPoolManager can't work due to external dependencies.
    """
    return create_typed_process_pool_mock()


# ============================================================================
# TEST DATA FACTORIES
# ============================================================================


@pytest.fixture
def shot_data_factory() -> Any:  # Callable[[str, str, str], ShotTestData]
    """Factory for creating shot test data on demand."""

    def _create_shot_data(
        show: str = "TEST", sequence: str = "seq01", shot: str = "0010"
    ) -> ShotTestData:
        return create_test_shot_data(show, sequence, shot)

    return _create_shot_data


@pytest.fixture
def cache_test_helper(typed_cache_manager: Any) -> Any:  # CacheTestHelper
    """Helper class for cache-related test operations."""

    class CacheTestHelper:
        """Helper for type-safe cache testing operations."""

        def __init__(self, cache_manager: Any) -> None:  # CacheManager
            self.cache = cache_manager

        def populate_test_shots(self, count: int = 3) -> list[dict[str, Any]]:
            """Populate cache with test shot data.

            Args:
                count: Number of test shots to create

            Returns:
                List of shot dictionaries that were cached
            """
            shots_data = []
            for i in range(count):
                shot_data = {
                    "show": f"TEST_SHOW_{i}",
                    "sequence": "seq01",
                    "shot": f"{i + 1:04d}",
                    "workspace_path": f"/test/path/shot_{i + 1:04d}",
                }
                shots_data.append(shot_data)

            self.cache.cache_shots(shots_data)
            return shots_data

        def assert_memory_within_limits(self, max_bytes: int) -> None:
            """Assert that cache memory usage is within limits."""
            current_usage = self.cache.test_memory_usage_bytes
            assert current_usage <= max_bytes, (
                f"Memory usage {current_usage} exceeds limit {max_bytes}"
            )

        def clear_and_verify(self) -> None:
            """Clear cache and verify it's empty."""
            self.cache.clear_cache()
            assert len(self.cache.test_cached_thumbnails) == 0
            assert self.cache.test_memory_usage_bytes == 0

    return CacheTestHelper(typed_cache_manager)


# ============================================================================
# MOCK CONFIGURATION HELPERS
# ============================================================================


class MockConfigurationHelper:
    """Helper for configuring mocks with proper typing."""

    @staticmethod
    def configure_process_pool_mock(
        mock: ProcessPoolProtocol,
        workspace_output: str | None = None,
    ) -> None:
        """Configure ProcessPoolManager mock with standard responses.

        Args:
            mock: Mock to configure
            workspace_output: Custom workspace command output
        """
        default_output = (
            workspace_output
            or """workspace /shows/TEST/seq01/0010
workspace /shows/TEST/seq01/0020
workspace /shows/TEST/seq02/0010"""
        )

        # Configure with proper typing awareness
        mock.execute_workspace_command.return_value = default_output

    @staticmethod
    def configure_launcher_mock(mock: Mock) -> None:
        """Configure LauncherManager mock with standard responses."""
        mock.launch_application.return_value = True
        mock.get_custom_launchers.return_value = []


@pytest.fixture
def mock_config_helper() -> MockConfigurationHelper:
    """Helper for configuring mocks consistently."""
    return MockConfigurationHelper()


# ============================================================================
# ASSERTION HELPERS
# ============================================================================


def assert_shot_data_valid(shot_data: ShotTestData) -> None:
    """Assert that shot test data is valid and well-formed.

    Args:
        shot_data: Shot data to validate

    Raises:
        AssertionError: If shot data is invalid
    """
    assert shot_data.shot is not None, "Shot object is None"
    assert shot_data.workspace_path.exists(), (
        f"Workspace path {shot_data.workspace_path} doesn't exist"
    )
    assert shot_data.shot.show, "Show name is empty"
    assert shot_data.shot.sequence, "Sequence name is empty"
    assert shot_data.shot.shot, "Shot name is empty"


def assert_cache_state_clean(cache_manager: Any) -> None:  # CacheManager
    """Assert that cache manager is in clean state.

    Args:
        cache_manager: Cache manager to check
    """
    assert len(cache_manager.test_cached_thumbnails) == 0, "Cache has thumbnails"
    assert cache_manager.test_memory_usage_bytes == 0, "Memory usage not zero"


# ============================================================================
# PARAMETRIZED TEST DATA
# ============================================================================


# Type-safe parametrized data for common test scenarios
SHOT_TEST_CASES = [
    ("SHOW_A", "seq01", "0010"),
    ("SHOW_B", "seq02", "0020"),
    ("COMPLEX_SHOW", "101_ABC", "0030"),
]

MEMORY_TEST_CASES = [
    (1024, 1),  # 1KB, 1 item
    (10240, 10),  # 10KB, 10 items
    (102400, 100),  # 100KB, 100 items
]

ERROR_TEST_CASES = [
    ("", "Empty show name"),
    ("VALID_SHOW", ""),  # Empty sequence
    ("VALID_SHOW", "seq01", ""),  # Empty shot
]


@pytest.fixture(params=SHOT_TEST_CASES)
def parametrized_shot_data(request: pytest.FixtureRequest) -> ShotTestData:
    """Parametrized shot data for multiple test scenarios."""
    show, sequence, shot = request.param
    return create_test_shot_data(show, sequence, shot)


@pytest.fixture(params=MEMORY_TEST_CASES)
def memory_test_params(request: pytest.FixtureRequest) -> tuple[int, int]:
    """Parametrized memory test parameters (size, count)."""
    return request.param


# ============================================================================
# INTEGRATION TEST HELPERS
# ============================================================================


class IntegrationTestEnvironment:
    """Type-safe integration test environment."""

    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.cache_dir = temp_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize real components
        self.cache_manager = create_real_cache_manager(self.cache_dir)
        self.app = TestQApplication.get_instance()

    def cleanup(self) -> None:
        """Clean up test environment."""
        self.cache_manager.clear_cache()


@pytest.fixture
def integration_env() -> Iterator[IntegrationTestEnvironment]:
    """Integration test environment with real components."""
    with tempfile.TemporaryDirectory() as temp_dir:
        env = IntegrationTestEnvironment(Path(temp_dir))
        try:
            yield env
        finally:
            env.cleanup()


# ============================================================================
# TYPE CHECKING HELPERS
# ============================================================================


def verify_type_safety() -> None:
    """Verify that type-safe patterns are working correctly.

    This function can be called in tests to ensure type safety is maintained.
    """
    # Create instances to verify typing works
    shot_data = create_test_shot_data()
    assert_shot_data_valid(shot_data)

    # Verify mock protocols work
    mock_pool = create_typed_process_pool_mock()
    result = mock_pool.execute_workspace_command("test")
    assert isinstance(result, str)


if __name__ == "__main__":
    # Verify configuration on import
    verify_type_safety()
    print("✓ Type-safe conftest configuration validated")
