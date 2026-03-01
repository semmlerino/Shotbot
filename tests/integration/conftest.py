"""Configuration and fixtures for integration tests."""

# Standard library imports

# Third-party imports
import pytest


# Markers are registered in pyproject.toml [tool.pytest.ini_options] markers


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Modify test collection to handle custom markers."""
    # Add integration marker to all tests in this directory
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


# NOTE: Singleton isolation is handled by reset_caches autouse fixture +
# _qt_auto_fixtures dispatcher (activates qt_cleanup and cleanup_state_heavy
# for detected Qt tests). See tests/conftest.py.
