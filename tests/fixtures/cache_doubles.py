"""Cache and progress test doubles.

Classes:
    TestProgressOperation: Minimal test double for progress operations
    TestProgressManager: Test double for progress manager

Fixtures:
    test_process_pool: TestProcessPool instance for mocking ProcessPoolManager
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, ClassVar

import pytest

from tests.fixtures.process_doubles import TestProcessPool


@dataclass
class TestProgressOperation:
    """Minimal test double for progress operations (internal to TestProgressManager)."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    title: str
    cancelable: bool = False
    progress: int = 0
    finished: bool = False


class TestProgressManager:
    """Test double for progress manager."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    _current_operation: ClassVar[TestProgressOperation | None] = None
    _operations_started: ClassVar[list[TestProgressOperation]] = []
    _operations_finished: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def start_operation(cls, config: Any) -> TestProgressOperation:
        """Start a new progress operation."""
        if isinstance(config, str):
            operation = TestProgressOperation(title=config)
        else:
            # Handle config object
            title = getattr(config, "title", "Test Operation")
            cancelable = getattr(config, "cancelable", False)
            operation = TestProgressOperation(title=title, cancelable=cancelable)

        cls._current_operation = operation
        cls._operations_started.append(operation)
        return operation

    @classmethod
    def finish_operation(cls, success: bool = True, error_message: str = "") -> None:
        """Finish the current progress operation."""
        if cls._current_operation:
            cls._operations_finished.append(
                {
                    "operation": cls._current_operation,
                    "success": success,
                    "error_message": error_message,
                    "timestamp": time.time(),
                }
            )
            cls._current_operation = None

    @classmethod
    def get_current_operation(cls) -> TestProgressOperation | None:
        """Get the current progress operation."""
        return cls._current_operation

    @classmethod
    def clear_all_operations(cls) -> None:
        """Clear all operations for testing."""
        cls._current_operation = None
        cls._operations_started.clear()
        cls._operations_finished.clear()

    @classmethod
    def get_operations_started_count(cls) -> int:
        """Get number of operations started (for testing)."""
        return len(cls._operations_started)

    @classmethod
    def get_operations_finished_count(cls) -> int:
        """Get number of operations finished (for testing)."""
        return len(cls._operations_finished)


# =============================================================================
# PYTEST FIXTURES
# =============================================================================


@pytest.fixture
def test_process_pool(request: pytest.FixtureRequest) -> TestProcessPool:
    """Provide a TestProcessPool instance for mocking ProcessPoolManager.

    Args:
        request: Pytest request for marker checking

    Returns:
        TestProcessPool instance that can be configured to return
        specific outputs or simulate errors.

    NOTE: Tests that define their own local `test_process_pool` fixture
    will shadow this global one - the local fixture takes precedence.

    MARKERS:
        @pytest.mark.permissive_process_pool: Disable strict mode
        @pytest.mark.enforce_thread_guard: Enable main-thread rejection (contract testing)
        @pytest.mark.allow_main_thread: Allow calls from main/UI thread (opt-out from guard)

    """
    # Check for markers
    is_permissive = "permissive_process_pool" in [
        m.name for m in request.node.iter_markers()
    ]
    enforce_guard = "enforce_thread_guard" in [
        m.name for m in request.node.iter_markers()
    ]
    allow_main = "allow_main_thread" in [
        m.name for m in request.node.iter_markers()
    ]
    return TestProcessPool(
        strict=not is_permissive,
        enforce_thread_guard=enforce_guard,
        allow_main_thread=allow_main,
    )
