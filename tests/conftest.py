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

2. QTBOT.WAIT() MONKEYPATCH (lines 131-207)
   WHY: pytest-qt's wait() can cause re-entrant event loop crashes when called
   with very short timeouts during fixture cleanup.
   HOW: Intercept wait(0) and wait(1), replace with process_qt_events().
   Waits of 2ms+ use original timing.
   OPT-OUT: @pytest.mark.real_timing or SHOTBOT_TEST_NO_WAIT_PATCH=1

3. XDIST GROUPING STRATEGY
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
- @pytest.mark.real_timing           Bypass wait() patch (timing-sensitive tests)
- @pytest.mark.skip_if_parallel      Skip test in parallel execution
- @pytest.mark.real_subprocess       Execute with real subprocess (bypass mocks)

GLOBAL STATE
------------
- _current_test_item: Set by pytest_runtest_setup, used by wait() patch to
  check @pytest.mark.real_timing. Cleared by pytest_runtest_teardown.
- _GLOBAL_QAPP: Session-scoped QApplication created at import time.

ENVIRONMENT VARIABLES
---------------------
- QT_QPA_PLATFORM=offscreen          Prevent real widgets appearing (auto-set)
- SHOTBOT_TEST_NO_WAIT_PATCH=1       Disable qtbot.wait() interception
- SHOTBOT_TEST_WAIT_DIAG=1           Log when short waits are intercepted
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
# This MUST be set before any Qt imports to prevent "real widgets" from appearing
# during tests, which causes crashes in WSL and resource exhaustion.
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

# Track current test item for runtime marker checks (e.g., @pytest.mark.real_timing)
# Set by pytest_runtest_call hook, cleared by pytest_runtest_teardown
_current_test_item: pytest.Item | None = None


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


@pytest.fixture(scope="session", autouse=True)
def _patch_qtbot_short_waits() -> Iterator[None]:
    """Intercept qtbot.wait for tiny delays to avoid pytest-qt re-entrancy crashes.

    DESIGN PHILOSOPHY:
    This is a SAFETY mechanism that prevents pytest-qt from entering nested
    event loops when qtbot.wait() is called with very short timeouts (≤1ms).
    These minimal waits typically indicate the intent to process pending events,
    not to actually wait for time to pass.

    BEHAVIOR:
    - qtbot.wait(0) through qtbot.wait(1): Replaced with process_qt_events()
    - qtbot.wait(2+): Original wait behavior preserved (real timing)

    This conservative threshold (1ms vs previous 5ms) ensures that legitimate
    short delays (2-5ms) use real timing, which is important for:
    - Debounce/timeout testing
    - Event ordering verification
    - Real-world timing simulation

    RECOMMENDED PATTERN:
    Use process_qt_events() directly instead of qtbot.wait(1) for clarity:
        from tests.test_helpers import process_qt_events
        process_qt_events()  # Clear and explicit intent

    OPT-OUT:
    - Set SHOTBOT_TEST_NO_WAIT_PATCH=1 to disable this patch entirely
    - Use @pytest.mark.real_timing to bypass the patch for specific tests

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
    original_wait_until = QtBot.waitUntil

    # Auto-enable diagnostics in CI environments
    is_ci = (
        os.environ.get("CI", "").lower() in ("true", "1", "yes")
        or os.environ.get("GITHUB_ACTIONS") == "true"
    )
    log_intercepted = os.environ.get("SHOTBOT_TEST_WAIT_DIAG", "0") == "1" or is_ci

    def _safe_wait(self, timeout: int = 0) -> None:
        from tests.test_helpers import process_qt_events

        # Honor @pytest.mark.real_timing - bypass patch entirely for timing-sensitive tests
        if _current_test_item is not None:
            if _current_test_item.get_closest_marker("real_timing"):
                return original_wait(self, timeout)

        if timeout <= 1:
            # Intercept wait(0) and wait(1) - these indicate "process events" intent
            # Diagnostic logging - auto-enabled in CI, opt-in locally
            if log_intercepted:
                import logging

                test_name = _current_test_item.name if _current_test_item else "unknown"
                logging.getLogger(__name__).info(
                    "qtbot.wait(%d) intercepted in '%s'", timeout, test_name
                )
            process_qt_events()
            return None
        return original_wait(self, timeout)

    def _safe_wait_until(
        self,
        callback: object,
        timeout: int = 5000,
    ) -> None:
        import time

        from tests.test_helpers import process_qt_events

        if not callable(callback):
            return original_wait_until(self, callback, timeout=timeout)

        # Honor @pytest.mark.real_timing - bypass patch entirely for timing-sensitive tests
        if _current_test_item is not None:
            if _current_test_item.get_closest_marker("real_timing"):
                return original_wait_until(self, callback, timeout=timeout)

        deadline = time.perf_counter() + max(timeout, 0) / 1000.0
        last_assertion: AssertionError | None = None

        while True:
            try:
                result = callback()
            except AssertionError as exc:
                last_assertion = exc
            else:
                if result is None or bool(result):
                    # Preserve pytest-qt's practical behavior: once the condition
                    # becomes true, flush one more round of queued Qt callbacks
                    # before returning so signal-driven state has a chance to land.
                    process_qt_events()
                    return None

            if time.perf_counter() >= deadline:
                if last_assertion is not None:
                    raise last_assertion
                raise TimeoutError(f"waitUntil timed out in {timeout} milliseconds")

            # Pump Qt events without entering pytest-qt's nested event loop.
            process_qt_events()
            time.sleep(0.01)

    QtBot.wait = _safe_wait  # type: ignore[assignment]
    QtBot.waitUntil = _safe_wait_until  # type: ignore[assignment]
    try:
        yield
    finally:
        QtBot.wait = original_wait  # type: ignore[assignment]
        QtBot.waitUntil = original_wait_until  # type: ignore[assignment]


# ==============================================================================
# Fixture Module Loading
# ==============================================================================
pytest_plugins = [
    # NOTE: Qt fixtures (qapp, _patch_qtbot_short_waits) are now in conftest.py
    # above, not in qt_bootstrap.py - this ensures they have access to _GLOBAL_QAPP
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
        "suppress_qmessagebox",
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
        request.getfixturevalue("suppress_qmessagebox")
        request.getfixturevalue("prevent_qapp_exit")


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


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Setup hook: track current test item and handle skip conditions.

    Sets _current_test_item EARLY so that fixture setup/teardown can access
    markers like @pytest.mark.real_timing. This is important because the
    qtbot.wait() patch needs to check this marker during fixture cleanup.
    """
    import logging

    global _current_test_item  # noqa: PLW0603

    # SAFETY CHECK: Previous test item should have been cleared in teardown
    # If not, it indicates a hook failure - log prominently but recover
    if _current_test_item is not None:
        logging.getLogger(__name__).warning(
            "INFRASTRUCTURE BUG: _current_test_item not cleared from previous test!\n"
            "  Previous: %s\n"
            "  Current: %s\n"
            "This indicates pytest_runtest_teardown failed to run. Check fixture cleanup.",
            _current_test_item.nodeid if _current_test_item else "unknown",
            item.nodeid,
        )
        # Recover by clearing it - don't cascade failures
        _current_test_item = None

    _current_test_item = item

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


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    """Clear current test item tracking AFTER fixture teardown.

    Uses trylast=True to ensure this runs after all fixture teardown is complete.
    This allows fixture cleanup code to still access markers like @pytest.mark.real_timing.
    """
    global _current_test_item  # noqa: PLW0603
    _current_test_item = None
