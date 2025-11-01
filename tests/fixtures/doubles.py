"""Test doubles for system boundaries.

Following UNIFIED_TESTING_GUIDE principle: "Use test doubles instead of mocks."

Test doubles are preferred over unittest.mock because they:
- Provide real behavior testing
- Are easier to understand and maintain
- Catch interface changes at compile time
- Enable better type checking
"""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture
def test_process_pool_simple() -> Generator[object, None, None]:
    """Simple test double for ProcessPoolManager.

    Provides a lightweight alternative to mocking for tests that just need
    basic command execution simulation.

    Example:
        def test_with_pool(test_process_pool_simple):
            # Use pool in tests
            result = test_process_pool_simple.execute_command("echo test")
            assert "test" in result
    """
    from tests.test_doubles_library import TestProcessPool

    pool = TestProcessPool()
    pool.set_outputs("workspace /shows/test/shots/010/0010")

    yield pool

    # Cleanup if needed
    if hasattr(pool, "cleanup"):
        pool.cleanup()


# Note: More test double fixtures can be added here following the same pattern.
# Each fixture should:
# 1. Use a test double from test_doubles_library
# 2. Provide sensible default configuration
# 3. Yield the configured double
# 4. Clean up resources in finally/teardown
