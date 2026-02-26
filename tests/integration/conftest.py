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


# NOTE: Singleton isolation is now handled by the root conftest.py via
# tests/fixtures/singleton_isolation.py (cleanup_state fixture, autouse=True)
# The redundant integration_test_isolation fixture was removed.
