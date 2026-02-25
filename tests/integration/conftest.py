"""Configuration and fixtures for integration tests."""

# Standard library imports

# Third-party imports
import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers",
        "performance: mark test as a performance benchmark",
    )
    config.addinivalue_line("markers", "stress: mark test as a stress test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")


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
