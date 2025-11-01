#!/usr/bin/env python3
"""pytest configuration and fixtures for ShotBot tests.

Provides common test fixtures and utilities for unit and integration tests
specific to the ShotBot VFX asset management application.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

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
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # Don't quit app as it may be used by other tests


# ==============================================================================
# Mock Fixtures
# ==============================================================================


@pytest.fixture
def mock_settings() -> Iterator[Mock]:
    """Mock QSettings for testing settings persistence."""
    settings_data: dict[str, object] = {}

    def mock_value(key: str, default: object = None, type: type | None = None) -> object:
        value = settings_data.get(key, default)
        if type and value is not None:
            return type(value)
        return value

    def mock_set_value(key: str, value: object) -> None:
        settings_data[key] = value

    mock_instance = Mock(spec=QSettings)
    mock_instance.value = mock_value
    mock_instance.setValue = mock_set_value

    yield mock_instance


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
    from cache_manager import CacheManager

    manager = CacheManager(cache_dir=temp_cache_dir)
    yield manager
    # Cleanup
    manager.clear_cache()


@pytest.fixture
def real_cache_manager(cache_manager: object) -> Iterator[object]:
    """Alias for cache_manager fixture (for compatibility)."""
    yield cache_manager


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
