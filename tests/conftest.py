#!/usr/bin/env python3
"""pytest configuration and fixtures for ShotBot tests.

Provides common test fixtures and utilities for unit and integration tests
specific to the ShotBot VFX asset management application.
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
import warnings
from pathlib import Path


# ==============================================================================
# CRITICAL: Force Qt to use offscreen platform for ALL QApplication instances
# ==============================================================================
# This MUST be set before any Qt imports to prevent "real widgets" from appearing
# during tests, which causes crashes in WSL and resource exhaustion.
# See: https://doc.qt.io/qt-6/qguiapplication.html#platform
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Create unique XDG runtime directory per worker (0700 perms to avoid Qt6 warnings/races)
# This prevents Qt6 warnings and races across xdist workers.
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
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox


if TYPE_CHECKING:
    from collections.abc import Iterator

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ==============================================================================
# Early Qt bootstrap (prevents mass-import crashes)
# ==============================================================================


def _bootstrap_qapplication() -> QApplication:
    """Create QApplication immediately so imports can safely instantiate widgets.

    Running the entire suite (unit + integration + performance) in a single
    pytest process imports roughly 2,500 modules. Several integration helpers
    lazily instantiate Qt widgets during import-time setup. Without a running
    QApplication, Qt attempts to use the host display plugin which crashes in
    headless/WSL environments ("Fatal Python error: Aborted").

    Creating the offscreen QApplication here ensures all later imports see a
    fully initialized Qt stack, enabling `pytest tests/` to run reliably.
    """
    # Import locally to avoid forcing PySide dependency when tests are not run
    from PySide6.QtCore import QStandardPaths

    # Ensure Qt writes to temporary locations before QApplication is created
    QStandardPaths.setTestModeEnabled(True)

    app = QApplication.instance()
    if app is None:
        try:
            # Force offscreen platform so no real windows are touched
            app = QApplication(["-platform", "offscreen"])
        except Exception:
            # Fallback when the offscreen plugin is unavailable (e.g., macOS dev boxes)
            os.environ["QT_QPA_PLATFORM"] = "minimal"
            app = QApplication([])
    else:
        platform = os.environ.get("QT_QPA_PLATFORM", "")
        if platform != "offscreen":
            warnings.warn(
                f"Existing QApplication is using platform '{platform}', expected 'offscreen'. "
                "This can surface real-window crashes under WSL/CI.",
                RuntimeWarning,
                stacklevel=2,
            )

    return app


_GLOBAL_QAPP = _bootstrap_qapplication()


# ==============================================================================
# Secure command executor configuration helpers
# ==============================================================================


# Secure executor removed - no longer needed for this personal project


# ==============================================================================
# Pytest Hooks
# ==============================================================================


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Group Qt-using tests and auto-enable fixtures based on markers.

    1. Groups Qt tests onto a single xdist worker for stable teardown
    2. Auto-enables fixtures based on markers (e.g., enforce_unique_connections)
    """
    for item in items:
        # Group Qt tests onto a single xdist worker
        fixtures = set(getattr(item, "fixturenames", ()) or ())
        if item.get_closest_marker("qt") or fixtures.intersection(
            {"qtbot", "cleanup_qt_state", "qt_cleanup"}
        ):
            item.add_marker(pytest.mark.xdist_group(name="qt"))

        # Auto-enable enforce_unique_connections fixture if marker is present
        if item.get_closest_marker("enforce_unique_connections"):
            item.add_marker(pytest.mark.usefixtures("enforce_unique_connections"))


# allow_real_secure_executor fixture removed - secure executor no longer exists


# ==============================================================================
# Qt Application Fixtures
# ==============================================================================


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """Return the eagerly-created QApplication instance for widget testing.

    The QApplication is created at import time (see `_bootstrap_qapplication`)
    so any module imported during collection sees a valid Qt stack. This also
    preserves the historical session scope semantics for tests.
    """
    return _GLOBAL_QAPP
    # Don't quit app as it may be used by other tests


@pytest.fixture(scope="session", autouse=True)
def _patch_qtbot_short_waits() -> Iterator[None]:
    """Intercept qtbot.wait for tiny delays to avoid pytest-qt re-entrancy crashes."""
    # Third-party imports
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
    from cache_manager import (
        CacheManager,
    )

    manager = CacheManager(cache_dir=temp_cache_dir)
    yield manager
    # Cleanup
    manager.clear_cache()


@pytest.fixture
def real_cache_manager(cache_manager: object) -> Iterator[object]:
    """Alias for cache_manager fixture (for compatibility)."""
    return cache_manager


# ==============================================================================
# Qt Cleanup (Critical for Test Isolation)
# ==============================================================================


@pytest.fixture(autouse=True)
def qt_cleanup(qapp: QApplication) -> Iterator[None]:
    """Ensure Qt state is clean between tests.

    This autouse fixture implements proper Qt test hygiene to prevent
    test-hygiene issues that cause crashes in large test suites:

    1. Flushes deferred deletes (deleteLater()) to prevent dangling signals/slots
    2. Clears Qt caches (QPixmapCache) to prevent memory accumulation
    3. Waits for background threads to prevent use-after-free
    4. Processes events multiple times to ensure complete cleanup

    Qt's object model is robust - it doesn't "accumulate leaks" from creating
    thousands of widgets. Crashes in large suites are from test-hygiene issues,
    not Qt corruption. This fixture ensures proper cleanup between tests.

    See Qt Test best practices: doc.qt.io/qt-6/qttest-index.html
    """
    # Third-party imports
    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    from PySide6.QtGui import QPixmapCache

    # BEFORE TEST: Wait for background threads from previous test FIRST
    # This prevents crashes from processing events while threads are still running
    # Only wait if there are actually active threads (performance optimization)
    pool = QThreadPool.globalInstance()
    if pool.activeThreadCount() > 0:
        pool.waitForDone(500)

    # Wrap event processing in try-except to prevent crashes from leaked objects
    try:
        # Now clean up state from previous test
        # Multiple rounds ensure complete event processing
        for _ in range(2):
            QCoreApplication.processEvents()
            # Flush deferred deletes explicitly (deleteLater() calls)
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        # Clear Qt caches to prevent memory accumulation
        QPixmapCache.clear()
    except (RuntimeError, SystemError):
        # Ignore errors from deleted C++ objects or system state during cleanup
        pass

    yield

    # AFTER TEST: Wait for background threads FIRST before processing events
    # This prevents crashes from processing events while threads are still running
    # Only wait if there are actually active threads (performance optimization)
    pool = QThreadPool.globalInstance()
    if pool.activeThreadCount() > 0:
        # Cancel pending runnables from queue (if supported - some Qt builds may lack clear())
        if hasattr(pool, "clear"):
            pool.clear()
        pool.waitForDone(100)  # Reduced from 2000ms → 100ms for performance

    # Also wait for any Python threading.Thread instances to complete
    # Some tests use threading.Thread in addition to QThreadPool
    # Process Qt events while waiting to avoid deadlocks
    import threading
    import time
    if threading.active_count() > 1:
        start_time = time.time()
        timeout = 0.5
        while threading.active_count() > 1 and (time.time() - start_time) < timeout:
            # Process Qt events instead of sleeping to prevent deadlocks
            QCoreApplication.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    # Wrap event processing in try-except to prevent crashes from leaked objects
    try:
        # Now that threads are done, clean up Qt resources
        # Multiple rounds to catch cascading cleanups
        for _ in range(3):
            QCoreApplication.processEvents()
            # Flush deferred deletes - prevents dangling signals/slots
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        # Clear Qt caches again after test
        QPixmapCache.clear()

        # Final event processing after thread cleanup
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    except (RuntimeError, SystemError):
        # Ignore errors from deleted C++ objects or system state during cleanup
        # This can happen if a QObject was deleted in C++ but Python still has a reference
        pass


@pytest.fixture(autouse=True)
def cleanup_state() -> Iterator[None]:
    """Clean up all module-level caches and singleton state before and after each test.

    This autouse fixture consolidates cache clearing, singleton resets, and threading cleanup
    to prevent test contamination. Runs both before and after each test for complete isolation.

    Before test:
    - Clear all utility caches and disable caching
    - Clear shared cache directory
    - Reset NotificationManager and ProgressManager singletons

    After test (defense in depth):
    - Process pending Qt events
    - Clean up Qt widgets (NotificationManager, ProgressManager)
    - Reset all singletons (ProcessPoolManager, QRunnableTracker, ThreadSafeWorker)
    - Clear caches again
    - Force garbage collection

    See UNIFIED_TESTING_V2.MD section "Common Root Causes of Isolation Failures" for details.
    """
    # Local application imports - import here to avoid circular dependencies
    import gc
    import shutil
    from pathlib import Path

    from notification_manager import NotificationManager
    from progress_manager import ProgressManager
    from utils import clear_all_caches, disable_caching

    # ===== BEFORE TEST: Setup clean state =====

    # Clear ALL caches FIRST, before any test operations
    clear_all_caches()

    # CRITICAL: Clear shared cache directory to prevent contamination
    # Tests using CacheManager() without cache_dir parameter use ~/.shotbot/cache_test
    # This shared directory accumulates data across test runs, causing contamination
    shared_cache_dir = Path.home() / ".shotbot" / "cache_test"
    if shared_cache_dir.exists():
        try:
            shutil.rmtree(shared_cache_dir)
        except FileNotFoundError:
            # Race condition in pytest-xdist: another worker may have deleted it
            pass

    # CRITICAL: Reset _cache_disabled flag to ensure consistent test behavior
    # Some tests call enable_caching() to test caching behavior.
    # Always disable caching at the start of each test for predictable behavior.
    disable_caching()

    # Reset all singleton managers using their reset() methods
    # Order matters: NotificationManager FIRST (closes Qt widgets that ProgressManager may reference)
    try:
        NotificationManager.reset()
    except (RuntimeError, AttributeError):
        # Qt objects may already be deleted
        pass

    # THEN reset ProgressManager (now safe to clear widget references)
    try:
        ProgressManager.reset()
    except (RuntimeError, AttributeError):
        # Qt objects may already be deleted
        pass

    # Reset ProcessPoolManager
    try:
        from process_pool_manager import ProcessPoolManager
        ProcessPoolManager.reset()
    except (RuntimeError, AttributeError, ImportError):
        pass

    # Reset FilesystemCoordinator
    try:
        from filesystem_coordinator import FilesystemCoordinator
        FilesystemCoordinator.reset()
    except (RuntimeError, AttributeError, ImportError):
        pass

    yield

    # ===== AFTER TEST: Comprehensive cleanup (defense in depth) =====

    # Qt Event Processing - Process pending events before cleanup
    # This ensures Qt is in a stable state before we start tearing things down
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.processEvents()
    except (RuntimeError, ImportError):
        # Qt not available or objects already deleted, ignore
        pass

    # Reset all singleton managers using their reset() methods
    # NotificationManager first (must happen early to avoid Qt object access after deletion)
    try:
        NotificationManager.reset()
    except (RuntimeError, AttributeError):
        pass

    # ProgressManager cleanup
    try:
        ProgressManager.reset()
    except (RuntimeError, AttributeError):
        pass

    # Clear utils caches
    clear_all_caches()

    # CRITICAL: Clear shared cache directory after test
    if shared_cache_dir.exists():
        try:
            shutil.rmtree(shared_cache_dir)
        except FileNotFoundError:
            pass

    # CRITICAL: Reset _cache_disabled flag after test
    disable_caching()

    # QRunnableTracker Cleanup
    from runnable_tracker import QRunnableTracker
    try:
        QRunnableTracker.reset()
    except Exception as e:
        import warnings
        warnings.warn(f"QRunnableTracker reset failed: {e}", RuntimeWarning, stacklevel=2)

    # ProcessPoolManager Cleanup
    from process_pool_manager import ProcessPoolManager
    try:
        ProcessPoolManager.reset()
    except Exception as e:
        import warnings
        warnings.warn(f"ProcessPoolManager reset failed: {e}", RuntimeWarning, stacklevel=2)

    # FilesystemCoordinator Cleanup
    from filesystem_coordinator import FilesystemCoordinator
    try:
        FilesystemCoordinator.reset()
    except Exception as e:
        import warnings
        warnings.warn(f"FilesystemCoordinator reset failed: {e}", RuntimeWarning, stacklevel=2)

    # ThreadSafeWorker Zombie Cleanup
    from PySide6.QtCore import QMutexLocker

    from thread_safe_worker import ThreadSafeWorker

    with QMutexLocker(ThreadSafeWorker._zombie_mutex):
        zombie_count = len(ThreadSafeWorker._zombie_threads)
        if zombie_count > 0:
            ThreadSafeWorker.cleanup_old_zombies()
            ThreadSafeWorker._zombie_threads.clear()
            ThreadSafeWorker._zombie_timestamps.clear()

    # Force garbage collection to clean up any instances that cached state
    # (e.g., TargetedShotsFinder instances with cached Config.SHOWS_ROOT regex patterns)
    gc.collect()


@pytest.fixture(autouse=True)
def clear_parser_cache() -> Iterator[None]:
    """Clear OptimizedShotParser pattern cache to prevent pollution.

    The cache is keyed by Config.SHOWS_ROOT. When tests monkeypatch this value,
    the cache accumulates entries that can cause parser regex mismatches.
    """
    yield
    # Import here to avoid circular imports at module level
    try:
        from optimized_shot_parser import _PATTERN_CACHE
        _PATTERN_CACHE.clear()
    except (ImportError, AttributeError):
        pass  # Parser module may not exist or cache may be renamed


@pytest.fixture(autouse=True)
def suppress_qmessagebox(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-dismiss modal dialogs to prevent blocking tests.

    This autouse fixture provides default mocks for QMessageBox to prevent
    real dialogs from appearing. Individual tests can override these mocks
    with their own monkeypatch calls - test-specific patches take priority.

    Critical for:
    - Preventing real widgets from appearing ("getting real widgets" issue)
    - Avoiding timeouts from modal dialogs waiting for user input
    - Preventing resource exhaustion under high parallel load

    Pattern from UNIFIED_TESTING_V2.MD section "Essential Autouse Fixtures".
    """
    def _ok(*args, **kwargs):
        return QMessageBox.StandardButton.Ok

    def _yes(*args, **kwargs):
        return QMessageBox.StandardButton.Yes

    # Static method patches
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, _ok, raising=True)
    monkeypatch.setattr(QMessageBox, "question", _yes, raising=True)

    # Instance-style dialog patches (catch .exec() and .open() usage)
    monkeypatch.setattr(QMessageBox, "exec", _ok, raising=True)
    monkeypatch.setattr(QMessageBox, "open", lambda *args, **kwargs: None, raising=True)


@pytest.fixture(autouse=True)
def stable_random_seed() -> None:
    """Fix random seeds for reproducible tests (pairs well with pytest-randomly).

    This fixture makes each test's random values deterministic while pytest-randomly
    still shuffles test ORDER to surface hidden test coupling.

    Pattern from UNIFIED_TESTING_V2.MD section "Essential Autouse Fixtures".
    """
    import random

    random.seed(12345)

    try:
        import numpy as np
        np.random.seed(12345)
    except ImportError:
        pass  # numpy not installed


@pytest.fixture(autouse=True)
def clear_module_caches() -> Iterator[None]:
    """Clear common in-memory caches before/after each test.

    This fixture prevents module-level @lru_cache and @functools.cache
    decorators from accumulating stale data across tests, which is especially
    critical for parallel execution where tests run on different workers.

    Pattern from UNIFIED_TESTING_V2.MD section 3 "Module-Level Caches".
    """
    import inspect

    modules_to_clear = []

    # Import modules that have cached functions
    try:
        import utils
        modules_to_clear.append(utils)
    except (ModuleNotFoundError, ImportError):
        pass

    # Clear LRU caches and other cached functions BEFORE test
    for mod in modules_to_clear:
        for name, obj in inspect.getmembers(mod):
            if hasattr(obj, "cache_clear"):
                obj.cache_clear()

    yield

    # Clear again after test (defense in depth)
    for mod in modules_to_clear:
        for name, obj in inspect.getmembers(mod):
            if hasattr(obj, "cache_clear"):
                obj.cache_clear()


@pytest.fixture(autouse=True)
def cleanup_launcher_manager_state() -> Iterator[None]:
    """Clean up LauncherManager state between tests.

    Prevents pollution from tests that create LauncherManager instances
    with stale state from previous tests.
    """
    yield

    # Import here to avoid circular dependencies
    try:
        # Clear any class-level state if it exists
        # LauncherManager instances should be cleaned up by Qt, but we ensure
        # any dangling references are released
        import gc

        from launcher_manager import LauncherManager  # noqa: F401
        gc.collect()  # Force garbage collection to clean up Qt objects
    except ImportError:
        # LauncherManager not available in this test
        pass


@pytest.fixture(autouse=True)
def prevent_qapp_exit(monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> None:
    """Prevent tests from calling QApplication.exit() or quit() which poisons event loops.

    pytest-qt explicitly warns that calling QApplication.exit() in one test
    breaks subsequent tests because it corrupts the event loop state.
    This monkeypatch ensures tests can't accidentally poison the event loop.

    This is critical for large test suites where one bad test can cascade
    failures to all subsequent tests in the same process.

    See: https://pytest-qt.readthedocs.io/en/latest/note_dialogs.html#warning-about-qapplication-exit
    """

    def _noop(*args, **kwargs) -> None:
        """No-op exit/quit - tests shouldn't exit the application."""

    from PySide6.QtCore import QCoreApplication

    # Patch both exit and quit (instance + class methods)
    # Code often calls Q(Core)Application.quit() in addition to exit()
    monkeypatch.setattr(qapp, "exit", _noop)
    monkeypatch.setattr(QApplication, "exit", _noop)
    monkeypatch.setattr(qapp, "quit", _noop)
    monkeypatch.setattr(QApplication, "quit", _noop)
    # Also patch QCoreApplication (some code paths use this)
    monkeypatch.setattr(QCoreApplication, "exit", _noop)
    monkeypatch.setattr(QCoreApplication, "quit", _noop)


@pytest.fixture
def mock_subprocess_workspace() -> Iterator[None]:
    """Mock subprocess.run for tests that call VFX workspace commands.

    Use this fixture explicitly in tests that need subprocess mocking.
    Most tests don't need subprocess mocking at all.

    Provides:
    - Mock responses for 'ws' (workspace) commands
    - Prevents "ws: command not found" errors
    - Returns realistic workspace command output

    Usage:
        def test_workspace_parsing(mock_subprocess_workspace):
            # Test code that calls subprocess.run with workspace commands
            pass
    """
    def mock_run_side_effect(*args, **kwargs):
        """Mock subprocess.run with realistic workspace command responses."""
        # Extract the command being run
        cmd = args[0] if args else kwargs.get("args", [])

        # Normalize to string for matching (handle both list and string forms)
        text = " ".join(cmd) if isinstance(cmd, list) else (cmd or "")

        # Handle workspace commands (ws)
        if " ws " in f" {text} " or text.strip().startswith("ws"):
            # Return realistic workspace command output
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "workspace /shows/test_show/shots/seq01/seq01_0010"
            mock_result.stderr = ""
            return mock_result

        # Default: return empty but successful result
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        return mock_result

    with patch("subprocess.run", side_effect=mock_run_side_effect):
        yield


# ==============================================================================
# Mock Environment Setup
# ==============================================================================


@pytest.fixture
def mock_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Set up mock environment variables for testing.

    Uses monkeypatch.setenv for safer environment manipulation that
    doesn't clear the entire environment mapping (which can surprise
    other threads).
    """
    # Set test environment using monkeypatch (safer than clearing os.environ)
    monkeypatch.setenv("SHOTBOT_MODE", "test")
    monkeypatch.setenv("USER", "test_user")

    # Cleanup is automatic via monkeypatch
    return {
        "SHOTBOT_MODE": "test",
        "USER": "test_user",
    }


@pytest.fixture
def isolated_test_environment(qapp: QApplication) -> Iterator[None]:
    """Provide isolated test environment with cache clearing for Qt widgets.

    This fixture ensures complete test isolation by:
    1. Clearing all utility caches (VersionUtils, path cache, etc.)
    2. Processing Qt events to ensure clean state
    3. Providing proper cleanup after test execution

    Critical for parallel test execution with pytest-xdist to prevent
    cache pollution between tests running in different workers.

    See UNIFIED_TESTING_V2.MD section "Test Isolation and Parallel Execution".
    """
    # Import here to avoid circular imports
    from utils import (
        clear_all_caches,
    )

    # Clear all utility caches before test
    clear_all_caches()

    # Process Qt events for clean state
    from PySide6.QtCore import QCoreApplication, QEvent
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    yield

    # Clear caches after test for next test's isolation
    clear_all_caches()

    # Final Qt cleanup
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


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


@pytest.fixture
def make_test_shot(tmp_path: Path):
    """Factory fixture for creating test Shot instances.

    Implements TestShotFactory protocol from test_protocols.py.
    """
    # Local application imports
    from shot_model import (
        Shot,
    )

    def _make_shot(
        show: str = "test",
        sequence: str = "seq01",
        shot: str = "0010",
        with_thumbnail: bool = True,
    ) -> Shot:
        """Create a test Shot instance with optional thumbnail."""
        workspace_path = str(tmp_path / "shows" / show / "shots" / sequence / f"{sequence}_{shot}")

        # Create workspace directory
        Path(workspace_path).mkdir(parents=True, exist_ok=True)

        # Create thumbnail if requested
        if with_thumbnail:
            thumbnail_dir = Path(workspace_path) / "editorial" / "thumbnails"
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            thumbnail_file = thumbnail_dir / f"{sequence}_{shot}.jpg"
            thumbnail_file.write_bytes(b"fake image data")

        return Shot(
            show=show,
            sequence=sequence,
            shot=shot,
            workspace_path=workspace_path,
        )

    return _make_shot



@pytest.fixture
def make_test_filesystem(tmp_path: Path):
    """Factory fixture for creating TestFileSystem instances.

    Returns a callable that creates TestFileSystem instances for
    testing file operations with VFX directory structures.

    Example usage:
        def test_scene_discovery(make_test_filesystem):
            fs = make_test_filesystem()
            shot_path = fs.create_vfx_structure("show1", "seq01", "0010")
            fs.create_file(shot_path / "user/artist/scene.3de", "content")
    """
    # Import here to avoid circular imports
    from tests.test_doubles_extended import (
        TestFileSystem,
    )

    def _make_filesystem() -> TestFileSystem:
        """Create a TestFileSystem instance with tmp_path as base."""
        return TestFileSystem(base_path=tmp_path)

    return _make_filesystem



@pytest.fixture
def make_real_3de_file(tmp_path: Path):
    """Factory fixture for creating real 3DE files in VFX directory structure.

    Returns a callable that creates a complete VFX directory structure with
    a real 3DE file for testing ThreeDEScene functionality.

    Example usage:
        def test_scene(make_real_3de_file):
            scene_path = make_real_3de_file("show1", "seq01", "0010", "artist1")
            # scene_path points to the .3de file
            # scene_path.parent.parent.parent.parent is the workspace_path
    """

    def _make_3de_file(
        show: str,
        seq: str,
        shot: str,
        user: str,
        plate: str = "BG01",
        filename: str = "scene.3de",
    ) -> Path:
        """Create a real 3DE file in VFX directory structure.

        Args:
            show: Show name
            seq: Sequence name
            shot: Shot name
            user: User/artist name
            plate: Plate name (default: "BG01")
            filename: 3DE filename (default: "scene.3de")

        Returns:
            Path to the created 3DE file
        """
        # Create VFX directory structure
        # Structure: shows/{show}/shots/{seq}/{seq}_{shot}/user/{user}/3de/
        workspace_path = tmp_path / "shows" / show / "shots" / seq / f"{seq}_{shot}"
        threede_dir = workspace_path / "user" / user / "3de"
        threede_dir.mkdir(parents=True, exist_ok=True)

        # Create the 3DE file with minimal valid content
        scene_file = threede_dir / filename
        scene_file.write_text(f"# 3DE Scene File\n# Show: {show}\n# Seq: {seq}\n# Shot: {shot}\n# User: {user}\n# Plate: {plate}\n")

        return scene_file

    return _make_3de_file


@pytest.fixture
def test_process_pool():
    """Test double for ProcessPoolManager implementing ProcessPoolProtocol.

    Provides a configurable test double that tracks calls and allows
    setting custom outputs and errors.
    """

    class TestProcessPool:
        """Test double for process pool operations."""

        def __init__(self) -> None:
            self.should_fail = False
            self.fail_with_timeout = False
            self.call_count = 0
            self.commands: list[str] = []
            self._outputs_queue: list[str] = []
            self._errors: str = ""
            self._repeat_output: bool = True  # By default, repeat the same output

        def set_outputs(self, *outputs: str, repeat: bool = True) -> None:
            """Set multiple outputs to return from execute_workspace_command.

            Args:
                *outputs: Variable number of output strings
                repeat: If True (default), returns the last output repeatedly for all calls.
                       If False, pops outputs sequentially and returns empty when exhausted.

            Default behavior (repeat=True) handles race conditions with background threads
            that may call execute_workspace_command() multiple times unpredictably.
            Use repeat=False for tests that need specific sequential outputs.
            """
            self._outputs_queue = list(outputs)
            self._repeat_output = repeat

        def set_errors(self, error: str) -> None:
            """Set errors to raise from execute_workspace_command."""
            self._errors = error

        def execute_workspace_command(
            self,
            command: str,
            cache_ttl: int | None = None,
            timeout: int | None = None,
        ) -> str:
            """Execute a workspace command (test double)."""
            self.call_count += 1
            self.commands.append(command)

            if self.fail_with_timeout:
                raise TimeoutError("Simulated timeout")

            if self.should_fail or self._errors:
                raise RuntimeError(self._errors or "Test error")

            # Return output based on mode
            if self._outputs_queue:
                if self._repeat_output:
                    # Return the last output repeatedly (handles background threads)
                    return self._outputs_queue[-1]
                # Pop sequentially (for tests needing specific order)
                return self._outputs_queue.pop(0)
            return ""

        def invalidate_cache(self, command: str) -> None:
            """Invalidate the cache for a specific command (test double)."""
            # Track that cache invalidation was called
            self.commands.append(f"invalidate:{command}")

        def reset(self) -> None:
            """Reset the test double state."""
            self.should_fail = False
            self.fail_with_timeout = False
            self.call_count = 0
            self.commands = []
            self._outputs_queue = []
            self._errors = ""
            self._repeat_output = True

    return TestProcessPool()


@pytest.fixture
def mock_process_pool_manager(monkeypatch, test_process_pool):
    """Patch ProcessPoolManager to use test double.

    This fixture patches ProcessPoolManager for tests that need subprocess mocking.
    Use this fixture explicitly in tests that need it (not autouse).

    Per UNIFIED_TESTING_V2.MD:
    - Autouse appropriate ONLY for: Qt cleanup, cache clearing, QMessageBox mocking, random seed
    - NOT for: subprocess, filesystem, database mocking (use explicit fixtures)

    Usage:
        def test_something(mock_process_pool_manager):
            # Test code that uses ProcessPoolManager
            pass
    """
    # Patch ProcessPoolManager.get_instance() to return our test double
    monkeypatch.setattr(
        "process_pool_manager.ProcessPoolManager.get_instance",
        lambda: test_process_pool,
    )


@pytest.fixture
def make_test_launcher():
    """Factory fixture for creating CustomLauncher instances for testing.

    Returns a callable that creates CustomLauncher instances with sensible
    defaults for testing. All parameters are optional.

    Example usage:
        def test_launcher(make_test_launcher):
            launcher = make_test_launcher(name="Test", command="echo test")
            assert launcher.name == "Test"
    """
    from launcher import (
        CustomLauncher,
    )

    def _make_launcher(
        name: str = "Test Launcher",
        command: str = "echo {shot_name}",
        description: str = "Test launcher",
        category: str = "test",
        launcher_id: str | None = None,
    ) -> CustomLauncher:
        """Create a CustomLauncher instance for testing.

        Args:
            name: Launcher name (default: "Test Launcher")
            command: Command to execute (default: "echo {shot_name}")
            description: Launcher description (default: "Test launcher")
            category: Launcher category (default: "test")
            launcher_id: Launcher ID (default: auto-generated UUID)

        Returns:
            CustomLauncher instance
        """
        if launcher_id is None:
            launcher_id = str(uuid.uuid4())

        return CustomLauncher(
            id=launcher_id,
            name=name,
            command=command,
            description=description,
            category=category,
        )

    return _make_launcher


@pytest.fixture
def real_shot_model(tmp_path: Path, test_process_pool, cache_manager):
    """Factory fixture for creating real ShotModel instances with test data.

    Returns a ShotModel instance configured with a temporary shows root,
    a test process pool, and a shared cache manager.
    """
    # Local application imports
    from shot_model import (
        ShotModel,
    )

    # Create shows root
    shows_root = tmp_path / "shows"
    shows_root.mkdir(exist_ok=True)

    # Create ShotModel instance with test process pool and shared cache manager
    return ShotModel(cache_manager=cache_manager, process_pool=test_process_pool)



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


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip tests marked with skip_if_parallel when running with xdist."""
    # Check if test has skip_if_parallel marker
    if item.get_closest_marker("skip_if_parallel"):
        # Check if running with xdist (parallel execution)
        if hasattr(item.config, "workerinput"):  # xdist worker
            pytest.skip("Test skipped in parallel execution due to Qt state pollution")
