#!/usr/bin/env python3
"""pytest configuration and fixtures for ShotBot tests.

Provides common test fixtures and utilities for unit and integration tests
specific to the ShotBot VFX asset management application.

Fixture modules are loaded via pytest_plugins for better organization.
"""

from __future__ import annotations


# ==============================================================================
# DEPRECATED TEST MODULE EXCLUSION
# ==============================================================================
# These test modules are deprecated and should not be collected.
# MainWindow now uses RightPanelWidget instead of LauncherPanel.
collect_ignore = [
    "integration/test_launcher_panel_integration.py",
]

import atexit
import os
import shutil
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


def _cleanup_test_dirs() -> None:
    """Cleanup temporary test directories at session end.

    Best-effort cleanup - failures are silently ignored since the OS
    will eventually clean /tmp anyway.
    """
    for d in (config_dir, cache_dir, xdg_path):
        if d.exists():
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass  # Best-effort cleanup


atexit.register(_cleanup_test_dirs)

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

    DESIGN PHILOSOPHY:
    This is a SAFETY mechanism that prevents pytest-qt from entering nested
    event loops when qtbot.wait() is called with very short timeouts (≤5ms).
    These short waits typically indicate the intent to process pending events,
    not to actually wait for time to pass.

    BEHAVIOR:
    - qtbot.wait(0) through qtbot.wait(5): Replaced with process_qt_events()
    - qtbot.wait(6+): Original wait behavior preserved

    RECOMMENDED PATTERN:
    Use process_qt_events() directly instead of qtbot.wait(1) for clarity:
        from tests.test_helpers import process_qt_events
        process_qt_events()  # Clear and explicit intent

    OPT-OUT:
    Set SHOTBOT_TEST_NO_WAIT_PATCH=1 to disable this patch entirely.
    This is useful for:
    - Timing diagnostics where real millisecond delays matter
    - Debugging tests that behave differently with/without the patch

    DIAGNOSTICS:
    Set SHOTBOT_TEST_WAIT_DIAG=1 to log when short waits are intercepted.

    IMPORTANT: This fixture MUST be in conftest.py (not a pytest_plugins module)
    to ensure it's registered at the same time as qapp and runs at session scope.
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
            # Optional diagnostic logging for debugging timing issues
            if os.environ.get("SHOTBOT_TEST_WAIT_DIAG", "0") == "1":
                import logging
                import traceback

                logging.getLogger(__name__).debug(
                    "qtbot.wait(%d) bypassed at:\n%s",
                    timeout,
                    "".join(traceback.format_stack()[-4:-1]),
                )
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
    "tests.fixtures.caching",
    "tests.fixtures.data_factories",
]


# ==============================================================================
# Pytest Hooks
# ==============================================================================


# Fixtures that indicate a test uses Qt and needs grouping/cleanup
_QT_FIXTURES = frozenset({"qtbot", "cleanup_qt_state", "qt_cleanup", "qapp"})


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Group Qt-using tests and auto-enable fixtures based on markers.

    GROUPING STRATEGY:
    - Qt tests are grouped by module (e.g., qt_test_shot_model, qt_test_launcher)
    - Tests in the same module share a worker for stable module-level Qt state
    - Different modules can run in parallel on different workers
    - This balances stability (module isolation) with parallelism (multiple workers)

    AUTO-FIXTURES (automatically applied to Qt tests):
    - qt_cleanup: Handles Qt widget/state cleanup between tests
    - cleanup_state_heavy: Handles singleton reset between tests

    MARKERS:
    - @pytest.mark.qt_heavy: Forces test onto single "qt_heavy" worker group
    - @pytest.mark.enforce_unique_connections: Enforces UniqueConnection for signals
    - @pytest.mark.qt: Marks test as Qt-using (triggers cleanup fixtures)

    Qt TEST DETECTION:
    Tests are detected as Qt tests if they either:
    1. Use any of these fixtures: qtbot, cleanup_qt_state, qt_cleanup, qapp
    2. Have @pytest.mark.qt marker

    IMPORTANT: Tests that import PySide6 directly WITHOUT using the above fixtures
    should add @pytest.mark.qt to ensure proper cleanup:

        @pytest.mark.qt
        def test_my_qt_model():
            from PySide6.QtCore import QObject
            obj = QObject()
            # ... test code ...

    Without the marker, such tests may skip Qt cleanup and leak state.
    """
    for item in items:
        # Determine if this is a Qt test
        fixtures = set(getattr(item, "fixturenames", ()) or ())
        is_qt_test = item.get_closest_marker("qt") or fixtures.intersection(_QT_FIXTURES)

        if is_qt_test:
            # Check for qt_heavy marker - these tests need extra isolation
            if item.get_closest_marker("qt_heavy"):
                # Heavy Qt tests go to dedicated worker for stability
                item.add_marker(pytest.mark.xdist_group(name="qt_heavy"))
            else:
                # Module-based grouping: tests in same module share a worker
                # This allows parallelism across modules while keeping
                # module-level Qt state stable
                module_name = item.module.__name__ if item.module else "unknown"
                # Extract just the test file name for the group
                group_name = f"qt_{module_name.split('.')[-1]}"
                item.add_marker(pytest.mark.xdist_group(name=group_name))

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
    # FAIL-FAST: Qt tests use xdist_group markers which REQUIRE --dist=loadgroup
    # Running with wrong dist mode causes Qt crashes that are hard to diagnose
    dist_mode = config.getoption("dist", default=None)
    if dist_mode and dist_mode not in ("loadgroup", "no"):
        raise pytest.UsageError(
            f"Invalid --dist={dist_mode} for Qt tests.\n\n"
            f"Qt tests use xdist_group markers which REQUIRE --dist=loadgroup.\n"
            f"Other dist modes (worksteal, loadscope, etc.) ignore grouping and crash Qt.\n\n"
            f"Fix: Use one of:\n"
            f"  pytest -n auto --dist=loadgroup   (parallel with Qt safety)\n"
            f"  pytest                            (serial, no -n flag)\n"
        )

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
    config.addinivalue_line(
        "markers",
        "permissive_subprocess: allow subprocess calls without subprocess_mock (DEPRECATED)",
    )
    config.addinivalue_line(
        "markers",
        "allow_dialogs: allow dialogs without explicit expect_dialog/expect_no_dialogs fixture",
    )
    config.addinivalue_line(
        "markers",
        "real_timing: documents test requires actual timing delays "
        "(NOTE: short-wait patch only affects waits ≤5ms; waits >5ms use real timing automatically)",
    )

    # FAIL-FAST: Verify all registered singletons have reset() methods
    # This catches cases where new singletons are added without proper reset support
    # Hard failure ensures tests cannot run with improper singleton isolation
    from tests.fixtures.singleton_registry import SingletonRegistry

    missing = SingletonRegistry.verify_all_have_reset()
    if missing:
        pytest.fail(
            f"SINGLETON ISOLATION FAILURE: The following singletons are registered "
            f"in SingletonRegistry but missing reset() classmethod: {missing}\n\n"
            f"Every singleton MUST implement reset() for proper test isolation.\n"
            f"See CLAUDE.md 'Singleton Pattern & Test Isolation' section.\n\n"
            f"To fix: Add a reset() classmethod to each singleton class that:\n"
            f"  1. Cleans up any resources (shutdown, cleanup, etc.)\n"
            f"  2. Resets cls._instance = None\n"
            f"  3. Resets any class-level mutable state",
            pytrace=False,
        )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip tests marked with skip_if_parallel when running with xdist."""
    # Check if test has skip_if_parallel marker
    if item.get_closest_marker("skip_if_parallel"):
        # Check if running with xdist (parallel execution)
        if hasattr(item.config, "workerinput"):  # xdist worker
            pytest.skip("Test skipped in parallel execution due to Qt state pollution")
