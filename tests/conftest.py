#!/usr/bin/env python3
"""pytest configuration and fixtures for ShotBot tests.

Provides common test fixtures and utilities for unit and integration tests
specific to the ShotBot VFX asset management application.

Fixture modules are loaded via pytest_plugins for better organization.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


# ==============================================================================
# CRITICAL: Qt Environment Setup (MUST be before PySide6 imports)
# ==============================================================================
# This MUST be set before any Qt imports to prevent "real widgets" from appearing
# during tests, which causes crashes in WSL and resource exhaustion.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Create unique XDG runtime directory per worker (0700 perms to avoid Qt6 warnings/races)
run_id = os.environ.get("PYTEST_XDIST_TESTRUNUID", "solo")
worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
base_tmp = Path(tempfile.gettempdir())
xdg_path = base_tmp / f"xdg-{run_id}-{worker}"
xdg_path.mkdir(mode=0o700, parents=True, exist_ok=True)
os.environ.setdefault("XDG_RUNTIME_DIR", str(xdg_path))

# Direct custom launcher persistence into a writable, per-test directory
config_dir = Path(tempfile.mkdtemp(prefix=f"shotbot-config-{run_id}-{worker}-"))
os.environ.setdefault("SHOTBOT_CONFIG_DIR", str(config_dir))
os.environ.setdefault("SHOTBOT_SECURE_EXECUTOR_MODE", "mock")

# Per-worker cache isolation (eliminates race conditions on shared ~/.shotbot/cache_test)
cache_dir = base_tmp / f"shotbot_test_cache_{worker}"
cache_dir.mkdir(parents=True, exist_ok=True)
os.environ["SHOTBOT_TEST_CACHE_DIR"] = str(cache_dir)

# ==============================================================================
# NOW safe to import PySide6
# ==============================================================================
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QApplication


if TYPE_CHECKING:
    from collections.abc import Iterator

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ==============================================================================
# CRITICAL: Early Qt bootstrap (prevents mass-import crashes)
# ==============================================================================
# Must happen BEFORE pytest_plugins loads other modules that may use Qt
QStandardPaths.setTestModeEnabled(True)

_existing_app = QApplication.instance()
if _existing_app is None:
    try:
        _GLOBAL_QAPP = QApplication(["-platform", "offscreen"])
    except Exception:
        os.environ["QT_QPA_PLATFORM"] = "minimal"
        _GLOBAL_QAPP = QApplication([])
else:
    _GLOBAL_QAPP = _existing_app


# ==============================================================================
# Qt Application Fixtures (MUST be in conftest.py, not plugin modules)
# ==============================================================================


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """Return the eagerly-created QApplication instance for widget testing.

    The QApplication is created at import time (see above) so any module
    imported during collection sees a valid Qt stack. This fixture preserves
    the historical session scope semantics for tests.

    IMPORTANT: This fixture MUST be in conftest.py (not a pytest_plugins module)
    because it references the module-level _GLOBAL_QAPP created above.
    """
    return _GLOBAL_QAPP
    # Don't quit app as it may be used by other tests


@pytest.fixture(scope="session", autouse=True)
def _patch_qtbot_short_waits() -> Iterator[None]:
    """Intercept qtbot.wait for tiny delays to avoid pytest-qt re-entrancy crashes.

    IMPORTANT: This fixture MUST be in conftest.py (not a pytest_plugins module)
    to ensure it's registered at the same time as qapp and runs at session scope.

    Set SHOTBOT_TEST_NO_WAIT_PATCH=1 to disable this patch for timing diagnostics.
    """
    # Allow opt-out for timing diagnostics
    if os.environ.get("SHOTBOT_TEST_NO_WAIT_PATCH", "0") == "1":
        yield
        return

    from pytestqt.qtbot import QtBot

    original_wait = QtBot.wait

    def _safe_wait(self, timeout: int = 0) -> None:
        from tests.test_helpers import process_qt_events

        if timeout <= 5:
            process_qt_events()
            return None
        return original_wait(self, timeout)

    QtBot.wait = _safe_wait  # type: ignore[assignment]
    try:
        yield
    finally:
        QtBot.wait = original_wait  # type: ignore[assignment]


# ==============================================================================
# Fixture Module Loading
# ==============================================================================
pytest_plugins = [
    # NOTE: Qt fixtures (qapp, _patch_qtbot_short_waits) are now in conftest.py
    # above, not in qt_bootstrap.py - this ensures they have access to _GLOBAL_QAPP
    "tests.fixtures.determinism",
    "tests.fixtures.temp_directories",
    "tests.fixtures.test_doubles",
    "tests.fixtures.subprocess_mocking",
    "tests.fixtures.qt_safety",
    "tests.fixtures.qt_cleanup",
    "tests.fixtures.singleton_isolation",
    "tests.fixtures.data_factories",
]


# ==============================================================================
# Pytest Hooks
# ==============================================================================


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Group Qt-using tests and auto-enable fixtures based on markers.

    1. Groups Qt tests onto a single xdist worker for stable teardown
    2. Auto-applies heavy cleanup fixtures (qt_cleanup, cleanup_state_heavy) to Qt tests
    3. Auto-enables fixtures based on markers (e.g., enforce_unique_connections)
    """
    for item in items:
        # Determine if this is a Qt test
        fixtures = set(getattr(item, "fixturenames", ()) or ())
        is_qt_test = item.get_closest_marker("qt") or fixtures.intersection(
            {"qtbot", "cleanup_qt_state", "qt_cleanup"}
        )

        if is_qt_test:
            # Group Qt tests onto a single xdist worker for stable teardown
            item.add_marker(pytest.mark.xdist_group(name="qt"))
            # Auto-apply heavy cleanup fixtures to Qt tests
            # (qt_cleanup handles Qt state, cleanup_state_heavy handles singletons)
            item.add_marker(pytest.mark.usefixtures("qt_cleanup", "cleanup_state_heavy"))

        # Auto-enable enforce_unique_connections fixture if marker is present
        if item.get_closest_marker("enforce_unique_connections"):
            item.add_marker(pytest.mark.usefixtures("enforce_unique_connections"))


# ==============================================================================
# Signal Connection Safety Fixtures
# ==============================================================================


@pytest.fixture(scope="session")
def _signal_instance_type():
    """Discover the type used by PySide6 for signal instances.

    This fixture robustly discovers the concrete type that PySide6 uses
    for signal objects, which we need for monkey-patching connect().
    """
    from PySide6.QtCore import QObject, Signal

    class _Dummy(QObject):
        sig = Signal()

    return type(_Dummy().sig)


@pytest.fixture
def enforce_unique_connections(request, monkeypatch, _signal_instance_type):
    """Force all signal.connect() calls to use UniqueConnection during tests.

    This fixture prevents duplicate signal connections by automatically using
    Qt.UniqueConnection for all connect() calls. If a signal is connected to
    the same slot twice, Qt will ignore the second connection silently.

    Scope: Currently only applies to tests marked with @pytest.mark.enforce_unique_connections

    Why this helps:
    - Catches duplicate signal connections at connection time (not emission time)
    - Makes "double-emission on click" bugs impossible
    - Provides immediate feedback in the test that creates the duplicate

    Usage:
        @pytest.mark.enforce_unique_connections
        def test_my_widget(qtbot, enforce_unique_connections):
            widget = MyWidget()
            # Any duplicate connections will be prevented

    Expand to all tests:
        Change this to autouse=True once validated on launcher tests.
    """
    from PySide6.QtCore import Qt

    # Get original connect method
    original_connect = _signal_instance_type.connect

    def _connect_unique(self, slot, connection_type=Qt.ConnectionType.AutoConnection):
        """Override connect() to enforce UniqueConnection while preserving caller's semantics."""
        # Preserve caller's choice (Queued, Blocked, etc.), just OR the UniqueConnection flag
        return original_connect(self, slot, connection_type | Qt.ConnectionType.UniqueConnection)

    # Patch connect() method
    monkeypatch.setattr(_signal_instance_type, "connect", _connect_unique, raising=True)


    # Cleanup is automatic via monkeypatch


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
    config.addinivalue_line(
        "markers",
        "enforce_unique_connections: enforce UniqueConnection for signal.connect() in this test",
    )
    config.addinivalue_line(
        "markers",
        "real_subprocess: execute test with real subprocess (bypasses autouse mocks)",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip tests marked with skip_if_parallel when running with xdist."""
    # Check if test has skip_if_parallel marker
    if item.get_closest_marker("skip_if_parallel"):
        # Check if running with xdist (parallel execution)
        if hasattr(item.config, "workerinput"):  # xdist worker
            pytest.skip("Test skipped in parallel execution due to Qt state pollution")
