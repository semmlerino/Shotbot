#!/usr/bin/env python3
"""pytest configuration and fixtures for ShotBot tests.

Provides common test fixtures and utilities for unit and integration tests
specific to the ShotBot VFX asset management application.

Fixture modules are loaded via pytest_plugins for better organization.

ARCHITECTURE OVERVIEW
=====================
This module implements sophisticated test infrastructure for a PySide6/Qt application
with ~2,700 tests across serial default runs and optional pytest-xdist isolation checks.
The design addresses several Qt-specific challenges that cause hard-to-diagnose crashes.

KEY DESIGN DECISIONS
--------------------

1. EARLY QT BOOTSTRAP (lines 94-107)
   WHY: PySide6 crashes if QApplication is created after certain imports or if
   multiple QApplication instances exist. By creating the QApplication at module
   import time (before pytest_plugins loads), we ensure a stable Qt environment.
   HOW: Create global _GLOBAL_QAPP at import time with offscreen platform.
   FALLBACK: If offscreen fails, falls back to "minimal" platform.

2. XDIST GROUPING STRATEGY
   WHY: Qt tests sharing QApplication must run on the same worker to prevent
   crashes from Qt state contamination.
   HOW: Module-based grouping via xdist_group markers. Tests in the same module
   share a worker; different modules can run in parallel.
   HEAVY TESTS: @pytest.mark.qt_heavy → dedicated "qt_heavy" worker group.

4. SINGLETON REGISTRY VALIDATION
   WHY: Singleton state leaks between tests cause flaky failures. All singletons
   must implement reset() and be registered for proper cleanup.
   HOW: pytest_configure validates that all SingletonMixin subclasses are
   registered and have reset() methods. Fails fast if not.

FIXTURE EXECUTION ORDER
-----------------------
For Qt tests, fixtures execute in this order (Qt fixtures activated by
_qt_auto_fixtures autouse dispatcher via request.getfixturevalue()):

  BEFORE TEST:
    1. reset_caches      (autouse)  → Clear in-memory and disk caches
    2. reset_singletons  (Qt tests) → Reset all registered singletons
    3. qt_cleanup        (Qt tests) → Clean Qt threads, pixmaps, events

  TEST RUNS

  AFTER TEST:
    4. qt_cleanup        (Qt tests) → Detect thread leaks, clean Qt state
    5. reset_singletons  (Qt tests) → Reset singletons again (safety)
    6. reset_caches      (autouse)  → gc.collect() if SHOTBOT_TEST_AGGRESSIVE_GC=1

IMPORTANT MARKERS
-----------------
- @pytest.mark.qt                    Force Qt cleanup fixtures
- @pytest.mark.qt_heavy              Isolate on single dedicated worker
- @pytest.mark.skip_if_parallel      Skip test in parallel execution
- @pytest.mark.real_subprocess       Opt Qt tests out of subprocess mocks; groups real-subprocess tests for xdist

GLOBAL STATE
------------
- _GLOBAL_QAPP: Session-scoped QApplication created at import time.

ENVIRONMENT VARIABLES
---------------------
- QT_QPA_PLATFORM=offscreen          Prevent real widgets appearing (auto-set)
- SHOTBOT_TEST_AGGRESSIVE_GC=1       Force gc.collect() after each test
- SHOTBOT_SKIP_SMOKE=1               Skip smoke tests that need external deps

DEBUGGING TIPS
--------------
1. Test hangs? Check for blocking Qt event loops (use PYTHONFAULTHANDLER=1)
2. Thread leaks? Run with -v and check qt_cleanup warnings
3. Flaky failures? Check singleton state - use reset_singletons fixture
4. Qt crashes? Verify --dist=loadgroup is used with pytest-xdist

See also: UNIFIED_TESTING_V2.md for comprehensive testing guidance.
"""

from __future__ import annotations


# Not a test module despite the test_ prefix — exclude from collection.
collect_ignore = ["test_helpers.py"]

# Test inclusion is controlled by marker policy in pyproject.toml (`-m ...`).
# Keep collection broad here so excluded suites can still be run explicitly.
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path


# ==============================================================================
# CRITICAL: Qt Environment Setup (MUST be before PySide6 imports)
# ==============================================================================
# This MUST be set before any Qt imports to prevent real widgets from appearing
# during tests, which causes resource exhaustion and potential crashes.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Create unique XDG runtime directory per worker
# IMPORTANT: 0o700 permissions are REQUIRED by Qt6 - it warns/fails if XDG_RUNTIME_DIR
# has permissive permissions (security requirement from XDG Base Directory spec).
# Per-worker isolation also prevents race conditions when running with pytest-xdist.
run_id = os.environ.get("PYTEST_XDIST_TESTRUNUID", "solo")
worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
base_tmp = Path(tempfile.gettempdir())
xdg_path = base_tmp / f"xdg-{run_id}-{worker}"
xdg_path.mkdir(mode=0o700, parents=True, exist_ok=True)  # 0o700 required by Qt6
os.environ["XDG_RUNTIME_DIR"] = str(xdg_path)

# Direct custom launcher persistence into a writable, per-test directory
config_dir = Path(tempfile.mkdtemp(prefix=f"shotbot-config-{run_id}-{worker}-"))
os.environ["SHOTBOT_CONFIG_DIR"] = str(config_dir)
os.environ["SHOTBOT_SECURE_EXECUTOR_MODE"] = "mock"

# Enable test mode for threading - allows terminate() on zombie threads to prevent CI hangs
os.environ["SHOTBOT_TEST_MODE"] = "1"

# Per-worker cache isolation (eliminates race conditions on shared ~/.shotbot/cache_test)
cache_dir = base_tmp / f"shotbot_test_cache_{run_id}_{worker}"
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
            except Exception:  # noqa: BLE001
                pass  # Best-effort cleanup


atexit.register(_cleanup_test_dirs)

# ==============================================================================
# NOW safe to import PySide6
# ==============================================================================
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QStandardPaths
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
    except Exception:  # noqa: BLE001
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


# ==============================================================================
# Fixture Module Loading
# ==============================================================================
pytest_plugins = [
    # NOTE: Qt fixtures (qapp) are in conftest.py above to access _GLOBAL_QAPP
    "tests.fixtures.qt_fixtures",
    "tests.fixtures.process_fixtures",
    "tests.fixtures.singleton_fixtures",
    "tests.fixtures.environment_fixtures",
]


# ==============================================================================
# Pytest Hooks
# ==============================================================================


# Fixtures that indicate a test uses Qt and needs grouping/cleanup
_QT_FIXTURES = frozenset(
    {
        "qtbot",
        "cleanup_qt_state",
        "qt_cleanup",
        "qapp",
        "prevent_qapp_exit",
    }
)

# Logger for Qt detection messages
import logging


_conftest_logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def _qt_auto_fixtures(request: pytest.FixtureRequest) -> None:
    """Conditionally activate Qt cleanup fixtures for detected Qt tests.

    Uses request.getfixturevalue() at runtime — the correct mechanism for
    conditional fixture injection. Replaces the broken add_marker(usefixtures(...))
    approach in pytest_collection_modifyitems which runs too late for fixture resolution.
    """
    fixtures = set(getattr(request.node, "fixturenames", ()) or ())
    is_qt_test = request.node.get_closest_marker("qt") is not None or bool(
        fixtures.intersection(_QT_FIXTURES)
    )

    if is_qt_test:
        request.getfixturevalue("qt_cleanup")
        request.getfixturevalue("reset_singletons")
        request.getfixturevalue("prevent_qapp_exit")
        # Skip subprocess mocking for tests that need real subprocess behavior.
        # @pytest.mark.real_subprocess opts out of both subprocess fixtures.
        needs_real_subprocess = (
            request.node.get_closest_marker("real_subprocess") is not None
        )
        if not needs_real_subprocess:
            request.getfixturevalue("mock_process_pool_manager")
            request.getfixturevalue("mock_subprocess_popen")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Group Qt-using tests and auto-enable fixtures based on markers.

    GROUPING STRATEGY:
    - Qt tests are grouped by module (e.g., qt_test_shot_model, qt_test_launcher)
    - Tests in the same module share a worker for stable module-level Qt state
    - Different modules can run in parallel on different workers
    - This balances stability (module isolation) with parallelism (multiple workers)

    AUTO-FIXTURES:
    Qt cleanup fixtures (qt_cleanup, cleanup_state_heavy) are now activated
    by the _qt_auto_fixtures autouse dispatcher, not by this hook.

    MARKERS:
    - @pytest.mark.qt_heavy: Forces test onto single "qt_heavy" worker group
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
        # Determine if this is a Qt test via fixtures or marker
        fixtures = set(getattr(item, "fixturenames", ()) or ())
        is_qt_test = item.get_closest_marker("qt") or fixtures.intersection(
            _QT_FIXTURES
        )

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

    # Markers are registered in pyproject.toml [tool.pytest.ini_options] markers

    # FAIL-FAST: Verify all registered singletons have reset() methods
    # This catches cases where new singletons are added without proper reset support
    # Hard failure ensures tests cannot run with improper singleton isolation
    from tests.fixtures.singleton_fixtures import SingletonRegistry

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

    # FAIL-FAST: Verify all SingletonMixin subclasses are registered
    # This catches cases where a developer creates a new singleton but forgets to register it
    unregistered = SingletonRegistry.verify_all_singletons_registered()
    if unregistered:
        pytest.fail(
            f"SINGLETON REGISTRATION FAILURE: The following SingletonMixin subclasses "
            f"are NOT registered in SingletonRegistry: {unregistered}\n\n"
            f"Every SingletonMixin subclass MUST be registered for proper test isolation.\n"
            f"See CLAUDE.md 'Singleton Pattern & Test Isolation' section.\n\n"
            f"To fix: Add a registration in tests/fixtures/singleton_fixtures.py:\n"
            f"    SingletonRegistry.register(\n"
            f'        "module_name.ClassName",\n'
            f"        cleanup_order=XX,  # Lower = earlier cleanup (10-19: UI, 20-29: Workers, 30-39: Pools)\n"
            f'        description="Description of the singleton",\n'
            f"    )",
            pytrace=False,
        )

    # FAIL-FAST: Verify no circular dependencies in singleton cleanup graph
    try:
        SingletonRegistry.verify_no_dependency_cycles()
    except Exception as e:  # noqa: BLE001
        pytest.fail(
            f"SINGLETON DEPENDENCY CYCLE: {e}\n\n"
            f"Singleton _cleanup_depends_on declarations form a cycle.\n"
            f"Fix: Remove one dependency from the cycle to break it.",
            pytrace=False,
        )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Setup hook: handle skip conditions for parallel execution."""
    # Check if test has skip_if_parallel marker
    if item.get_closest_marker("skip_if_parallel"):
        # Check if running with xdist (parallel execution)
        if hasattr(item.config, "workerinput"):  # xdist worker
            pytest.skip("Test skipped in parallel execution due to Qt state pollution")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Print thread leak summary at end of session (if any leaks detected).

    This hook prints a consolidated summary instead of per-test warnings,
    reducing console noise while still providing actionable information.

    Only active when STRICT_CLEANUP or FAIL_ON_THREAD_LEAK is enabled
    (CI environments, GitHub Actions, or explicit env vars).
    """
    from tests.fixtures.qt_fixtures import get_thread_leak_summary

    summary = get_thread_leak_summary()
    if summary:
        # Get terminal reporter for proper output formatting
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.write_line(summary, yellow=True)
        else:
            # Fallback to print if reporter not available
            print(summary)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Final Qt teardown hook to avoid PySide shutdown-time segfaults."""
    global _GLOBAL_QAPP  # noqa: PLW0603

    # Ensure any remaining thread pool runnables are cancelled or finished
    try:
        from PySide6.QtCore import QThreadPool

        pool = QThreadPool.globalInstance()
        pool.clear()
        pool.waitForDone(2000)
    except Exception:  # noqa: BLE001
        pass

    # Keep this hook minimal. Per-test cleanup already drains Qt state; extra
    # Qt API calls here can crash during interpreter teardown once C++ objects
    # are partially finalized.
    _GLOBAL_QAPP = None


