#!/usr/bin/env python3
"""pytest configuration and fixtures for ShotBot tests.

Provides common test fixtures and utilities for unit and integration tests
specific to the ShotBot VFX asset management application.

Fixture modules are loaded via pytest_plugins for better organization.

ARCHITECTURE OVERVIEW
=====================
This module implements sophisticated test infrastructure for a PySide6/Qt application
with 3,500+ tests running in parallel via pytest-xdist. The design addresses several
Qt-specific challenges that cause hard-to-diagnose crashes.

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

3. AST-BASED QT DETECTION (lines 302-419)
   WHY: Tests that import PySide6 directly (without qtbot fixture) still need
   proper cleanup. Without detection, they leak Qt state.
   HOW: Parse test module source with AST, detect PySide6 imports (excluding
   TYPE_CHECKING blocks), and auto-apply cleanup fixtures.

4. XDIST GROUPING STRATEGY (lines 494-510)
   WHY: Qt tests sharing QApplication must run on the same worker to prevent
   crashes from Qt state contamination.
   HOW: Module-based grouping via xdist_group markers. Tests in the same module
   share a worker; different modules can run in parallel.
   HEAVY TESTS: @pytest.mark.qt_heavy → dedicated "qt_heavy" worker group.

5. SINGLETON REGISTRY VALIDATION (lines 675-710)
   WHY: Singleton state leaks between tests cause flaky failures. All singletons
   must implement reset() and be registered for proper cleanup.
   HOW: pytest_configure validates that all SingletonMixin subclasses are
   registered and have reset() methods. Fails fast if not.

FIXTURE EXECUTION ORDER
-----------------------
For Qt tests, fixtures execute in this order:

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
- @pytest.mark.enforce_unique_connections  Prevent duplicate signal connections
- @pytest.mark.real_subprocess       Execute with real subprocess (bypass mocks)

GLOBAL STATE
------------
- _current_test_item: Set by pytest_runtest_setup, used by wait() patch to
  check @pytest.mark.real_timing. Cleared by pytest_runtest_teardown.
- _qt_detection_cache: Module name → bool cache for AST detection performance.
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
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Create unique XDG runtime directory per worker
# IMPORTANT: 0o700 permissions are REQUIRED by Qt6 - it warns/fails if XDG_RUNTIME_DIR
# has permissive permissions (security requirement from XDG Base Directory spec).
# Per-worker isolation also prevents race conditions when running with pytest-xdist.
run_id = os.environ.get("PYTEST_XDIST_TESTRUNUID", "solo")
worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
base_tmp = Path(tempfile.gettempdir())
xdg_path = base_tmp / f"xdg-{run_id}-{worker}"
xdg_path.mkdir(mode=0o700, parents=True, exist_ok=True)  # 0o700 required by Qt6
os.environ.setdefault("XDG_RUNTIME_DIR", str(xdg_path))

# Direct custom launcher persistence into a writable, per-test directory
config_dir = Path(tempfile.mkdtemp(prefix=f"shotbot-config-{run_id}-{worker}-"))
os.environ.setdefault("SHOTBOT_CONFIG_DIR", str(config_dir))
os.environ.setdefault("SHOTBOT_SECURE_EXECUTOR_MODE", "mock")

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

# Logger for Qt detection messages
import logging


_conftest_logger = logging.getLogger(__name__)


def _fixture_uses_pyside6(item: pytest.Item, fixture_name: str) -> bool:
    """Check if a fixture or its dependencies use PySide6.

    This function inspects the fixture dependency graph to detect indirect
    Qt usage through fixtures. This catches cases where a test doesn't import
    PySide6 directly but uses fixtures that do.

    Args:
        item: The pytest item (test function)
        fixture_name: Name of the fixture to check

    Returns:
        True if the fixture imports PySide6, False otherwise

    """
    try:
        # Get fixture manager from session
        fm = item.session._fixturemanager
        fixture_defs = fm.getfixturedefs(fixture_name, item.nodeid)

        if not fixture_defs:
            return False

        for fixture_def in fixture_defs:
            # Check fixture function's module
            func = fixture_def.func
            func_module = getattr(func, "__module__", "")
            if isinstance(func_module, str) and func_module.startswith("PySide6"):
                return True

            # Check fixture function's source for PySide6 imports
            try:
                import ast
                import inspect

                source = inspect.getsource(func)
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith("PySide6"):
                                return True
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.module.startswith("PySide6"):
                            return True
            except (TypeError, OSError, SyntaxError):
                pass

    except (AttributeError, KeyError):
        pass

    return False


# Cache for Qt detection results (module name -> bool)
# This avoids redundant AST parsing for tests in the same module
_qt_detection_cache: dict[str, bool] = {}


def _module_imports_pyside6(module) -> bool:
    """Check if a test module imports PySide6 at any level.

    This function detects tests that use Qt directly without requesting
    Qt fixtures (qtbot, qapp, etc.) so they can be auto-grouped and
    have cleanup fixtures applied.

    Detection methods:
    1. Runtime check: Module-level PySide6 objects in vars(module)
    2. AST check: Import statements anywhere in source (catches function-local imports)

    NOTE: TYPE_CHECKING blocks are intentionally skipped in AST detection to avoid
    false positives from type-hint-only imports that never execute at runtime.

    Args:
        module: The test module to check

    Returns:
        True if the module imports from PySide6, False otherwise

    """
    if module is None:
        return False

    # Check cache first
    module_name = getattr(module, "__name__", None)
    if module_name and module_name in _qt_detection_cache:
        return _qt_detection_cache[module_name]

    result = False

    # Method 1: Runtime module-level object check
    try:
        module_dict = vars(module)
    except TypeError:
        module_dict = {}

    for obj in module_dict.values():
        # Check object's module
        obj_module = getattr(obj, "__module__", "")
        if isinstance(obj_module, str) and obj_module.startswith("PySide6"):
            result = True
            break

        # Check base classes for types (catches Qt widget subclasses)
        if isinstance(obj, type):
            for base in getattr(obj, "__mro__", ()):
                base_module = getattr(base, "__module__", "")
                if isinstance(base_module, str) and base_module.startswith("PySide6"):
                    result = True
                    break
            if result:
                break

    # Method 2: AST-based detection for function-level imports (if not already found)
    # This catches imports inside test functions that runtime check misses
    # Note: TYPE_CHECKING blocks are skipped to avoid false positives from type hints
    if not result:
        try:
            import ast
            import inspect

            source = inspect.getsource(module)
            tree = ast.parse(source)

            # Build line ranges to skip (TYPE_CHECKING blocks)
            # These are type-hint-only imports that don't execute at runtime
            skip_ranges: list[tuple[int, int]] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    test = node.test
                    # Match both `if TYPE_CHECKING:` and `if typing.TYPE_CHECKING:`
                    is_type_checking = (
                        isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
                    ) or (
                        isinstance(test, ast.Attribute)
                        and test.attr == "TYPE_CHECKING"
                    )
                    if is_type_checking and node.body:
                        # Get line range of this if-block's body
                        start_line = node.body[0].lineno
                        end_line = (
                            node.body[-1].end_lineno
                            if hasattr(node.body[-1], "end_lineno")
                            and node.body[-1].end_lineno
                            else node.body[-1].lineno
                        )
                        skip_ranges.append((start_line, end_line))

            # Check imports, skipping those in TYPE_CHECKING blocks
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    # Skip if inside TYPE_CHECKING block
                    if any(start <= node.lineno <= end for start, end in skip_ranges):
                        continue
                    for alias in node.names:
                        if alias.name.startswith("PySide6"):
                            result = True
                            break
                elif isinstance(node, ast.ImportFrom):
                    # Skip if inside TYPE_CHECKING block
                    if any(start <= node.lineno <= end for start, end in skip_ranges):
                        continue
                    if node.module and node.module.startswith("PySide6"):
                        result = True
                        break
                if result:
                    break
        except (TypeError, OSError, SyntaxError):
            # Can't get source or parse it - fall back to runtime check only
            pass

    # Cache result
    if module_name:
        _qt_detection_cache[module_name] = result

    return result


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
    # Track modules we've already logged auto-detection for (avoid spam)
    auto_detected_modules: set[str] = set()

    for item in items:
        # Determine if this is a Qt test via fixtures or marker
        fixtures = set(getattr(item, "fixturenames", ()) or ())
        is_qt_test = item.get_closest_marker("qt") or fixtures.intersection(_QT_FIXTURES)

        # Auto-detect PySide6 imports if not already detected as Qt test
        if not is_qt_test:
            # Method 1: Check module-level and function-level imports
            if item.module and _module_imports_pyside6(item.module):
                is_qt_test = True
                # Log once per module (not per test)
                module_name = item.module.__name__ if item.module else "unknown"
                if module_name not in auto_detected_modules:
                    auto_detected_modules.add(module_name)
                    # DEBUG level to reduce console noise - auto-detection is normal behavior
                    _conftest_logger.debug(
                        "Auto-detected PySide6 import in %s (no fixture/marker). "
                        "Applying Qt cleanup automatically.",
                        module_name,
                    )

            # Method 2: Check fixture dependency graph for indirect Qt usage
            if not is_qt_test:
                for fixture_name in fixtures - _QT_FIXTURES:  # Skip known Qt fixtures
                    if _fixture_uses_pyside6(item, fixture_name):
                        is_qt_test = True
                        module_name = item.module.__name__ if item.module else "unknown"
                        if module_name not in auto_detected_modules:
                            auto_detected_modules.add(module_name)
                            _conftest_logger.debug(
                                "Auto-detected PySide6 in fixture dependency for %s. "
                                "Applying Qt cleanup automatically.",
                                module_name,
                            )
                        break

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
    config.addinivalue_line(
        "markers",
        "performance_like: timing-sensitive checks excluded from default runs",
    )
    config.addinivalue_line("markers", "critical: mark test as critical/high priority")
    config.addinivalue_line("markers", "gui_mainwindow: mark test as requiring main window GUI")
    config.addinivalue_line("markers", "qt_heavy: mark test as Qt-intensive")
    config.addinivalue_line("markers", "integration_unsafe: mark test as potentially unsafe integration test")
    config.addinivalue_line("markers", "integration_safe: mark test as safe integration test")
    config.addinivalue_line(
        "markers",
        "permissive_process_pool: allow TestProcessPool without set_outputs() (use sparingly)",
    )
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
        "real_timing: bypass short-wait patch for timing-sensitive tests "
        "(NOTE: patch only intercepts waits ≤1ms; waits ≥2ms always use real timing)",
    )
    config.addinivalue_line(
        "markers",
        "smoke: smoke tests for real subprocess/external dependencies "
        "(skip locally with SHOTBOT_SKIP_SMOKE=1)",
    )
    config.addinivalue_line(
        "markers",
        "legacy: lower-signal or duplicate historical tests excluded from default runs",
    )
    config.addinivalue_line(
        "markers",
        "tutorial: educational/reference tests excluded from default runs",
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

    # FAIL-FAST: Verify all SingletonMixin subclasses are registered
    # This catches cases where a developer creates a new singleton but forgets to register it
    unregistered = SingletonRegistry.verify_all_singletons_registered()
    if unregistered:
        pytest.fail(
            f"SINGLETON REGISTRATION FAILURE: The following SingletonMixin subclasses "
            f"are NOT registered in SingletonRegistry: {unregistered}\n\n"
            f"Every SingletonMixin subclass MUST be registered for proper test isolation.\n"
            f"See CLAUDE.md 'Singleton Pattern & Test Isolation' section.\n\n"
            f"To fix: Add a registration in tests/fixtures/singleton_registry.py:\n"
            f"    SingletonRegistry.register(\n"
            f'        "module_name.ClassName",\n'
            f"        cleanup_order=XX,  # Lower = earlier cleanup (10-19: UI, 20-29: Workers, 30-39: Pools)\n"
            f'        description="Description of the singleton",\n'
            f"    )",
            pytrace=False,
        )

    # FAIL-FAST: Verify singleton dependency order is correct
    # This catches cases where cleanup order doesn't match declared dependencies
    dep_violations = SingletonRegistry.validate_dependency_order()
    if dep_violations:
        pytest.fail(
            "SINGLETON DEPENDENCY ORDER VIOLATION:\n"
            + "\n".join(f"  - {v}" for v in dep_violations)
            + "\n\nFix: Adjust cleanup_order values so dependencies clean up AFTER dependents.",
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
    # Final best-effort Qt drain before interpreter shutdown.
    # This mitigates late segfaults from lingering QRunnable/QThreadPool work.
    try:
        from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
        from PySide6.QtWidgets import QApplication

        from runnable_tracker import get_tracker

        tracker = get_tracker()
        tracker.wait_for_all(timeout_ms=3000)
        tracker.cleanup_all()
        QThreadPool.globalInstance().waitForDone(3000)

        app = QApplication.instance()
        if app is not None:
            for _ in range(3):
                app.processEvents()
            try:
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            except (RuntimeError, SystemError):
                pass
            app.processEvents()
    except Exception:
        # Never fail session teardown due to best-effort stability cleanup.
        pass

    from tests.fixtures.qt_cleanup import get_thread_leak_summary

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

    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            try:
                app.quit()
            except (RuntimeError, SystemError):
                pass
            for _ in range(3):
                try:
                    app.processEvents()
                except (RuntimeError, SystemError):
                    break
            try:
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            except (RuntimeError, SystemError):
                pass
            try:
                app.processEvents()
            except (RuntimeError, SystemError):
                pass

            # Force C++ QApplication deletion before Python interpreter finalization.
            try:
                from shiboken6 import Shiboken

                Shiboken.delete(app)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        _GLOBAL_QAPP = None


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    """Clear current test item tracking AFTER fixture teardown.

    Uses trylast=True to ensure this runs after all fixture teardown is complete.
    This allows fixture cleanup code to still access markers like @pytest.mark.real_timing.
    """
    global _current_test_item  # noqa: PLW0603
    _current_test_item = None
