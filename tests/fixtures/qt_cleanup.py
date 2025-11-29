"""Qt cleanup fixture for test isolation.

This module provides the qt_cleanup autouse fixture that ensures Qt state
is properly cleaned between tests, preventing crashes and test contamination
in large test suites.

Fixtures:
    qt_cleanup: Clean up Qt state between tests (autouse)

Environment Variables:
    SHOTBOT_TEST_STRICT_CLEANUP: Set to "1" to fail on cleanup exceptions instead of swallowing them
    SHOTBOT_TEST_FAIL_ON_THREAD_LEAK: Set to "1" to fail tests when thread leaks are detected
    CI: Auto-enables strict cleanup in CI environments
    GITHUB_ACTIONS: Auto-enables strict cleanup in GitHub Actions
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator

    from PySide6.QtWidgets import QApplication

_logger = logging.getLogger(__name__)

# Strict mode fails on cleanup exceptions (useful for debugging)
# Auto-enabled in CI environments to catch thread leaks early
STRICT_CLEANUP = (
    os.environ.get("SHOTBOT_TEST_STRICT_CLEANUP", "0") == "1"
    or os.environ.get("CI") == "true"
    or os.environ.get("GITHUB_ACTIONS") == "true"
)

# Fail mode: pytest.fail() on thread leaks (opt-in, stricter than STRICT_CLEANUP)
# STRICT_CLEANUP only logs warnings; FAIL_ON_THREAD_LEAK makes tests fail
FAIL_ON_THREAD_LEAK = os.environ.get("SHOTBOT_TEST_FAIL_ON_THREAD_LEAK", "0") == "1"

# Thread count tolerance - daemon threads and pytest internals can vary slightly
_THREAD_TOLERANCE = 2


@pytest.fixture  # NOTE: No longer autouse - applied conditionally via conftest.py hook
def qt_cleanup(qapp: QApplication) -> Iterator[None]:
    """Ensure Qt state is clean between tests.

    This autouse fixture implements proper Qt test hygiene to prevent
    test-hygiene issues that cause crashes in large test suites:

    1. Flushes deferred deletes (deleteLater()) to prevent dangling signals/slots
    2. Clears Qt caches (QPixmapCache) to prevent memory accumulation
    3. Waits for background threads to prevent use-after-free
    4. Processes events multiple times to ensure complete cleanup
    5. (STRICT MODE) Detects thread leaks by comparing baseline counts

    Qt's object model is robust - it doesn't "accumulate leaks" from creating
    thousands of widgets. Crashes in large suites are from test-hygiene issues,
    not Qt corruption. This fixture ensures proper cleanup between tests.

    In CI environments (or with SHOTBOT_TEST_STRICT_CLEANUP=1), thread leaks
    are logged with surviving thread names to help identify the source.

    See Qt Test best practices: doc.qt.io/qt-6/qttest-index.html

    Args:
        qapp: QApplication fixture from qt_bootstrap
    """
    import threading
    import time

    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    from PySide6.QtGui import QPixmapCache

    # Capture baseline thread counts BEFORE test
    # Used for leak detection after cleanup
    baseline_python_threads = threading.active_count()
    baseline_pool_threads = QThreadPool.globalInstance().activeThreadCount()

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
    except (RuntimeError, SystemError) as e:
        _logger.debug("Qt cleanup before-test exception (swallowed): %s", e)
        if STRICT_CLEANUP:
            raise

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
    if threading.active_count() > 1:
        start_time = time.time()
        timeout = 0.5
        while threading.active_count() > 1 and (time.time() - start_time) < timeout:
            # Process Qt events instead of sleeping to prevent deadlocks
            # Wrap in try-except to prevent crashes from deleted Qt objects
            try:
                QCoreApplication.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            except (RuntimeError, SystemError) as e:
                _logger.debug("Qt cleanup thread-wait exception (swallowed): %s", e)
                if STRICT_CLEANUP:
                    raise
                break

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
    except (RuntimeError, SystemError) as e:
        _logger.debug("Qt cleanup after-test exception (swallowed): %s", e)
        if STRICT_CLEANUP:
            raise

    # THREAD LEAK DETECTION: Compare current thread counts to baseline
    # Only log warnings in strict mode to avoid noise during normal development
    if STRICT_CLEANUP or FAIL_ON_THREAD_LEAK:
        final_pool_threads = QThreadPool.globalInstance().activeThreadCount()
        final_python_threads = threading.active_count()

        # Track if any leaks detected (for FAIL_ON_THREAD_LEAK)
        pool_leaked = final_pool_threads > baseline_pool_threads
        python_leaked = final_python_threads > baseline_python_threads + _THREAD_TOLERANCE

        # Check QThreadPool for leaked runnables
        if pool_leaked:
            leaked_count = final_pool_threads - baseline_pool_threads
            _logger.warning(
                "THREAD LEAK: QThreadPool has %d more active runnable(s) than before test. "
                "Baseline: %d, Final: %d. "
                "This can cause xdist flakes when runnables mutate shared state.",
                leaked_count,
                baseline_pool_threads,
                final_pool_threads,
            )

        # Check Python threads (with tolerance for daemon threads)
        surviving_threads: list[str] = []
        if python_leaked:
            leaked_count = final_python_threads - baseline_python_threads
            surviving_threads = [
                f"{t.name} (daemon={t.daemon})"
                for t in threading.enumerate()
                if t.name != "MainThread"
            ]
            _logger.warning(
                "THREAD LEAK: %d more Python thread(s) than before test. "
                "Baseline: %d, Final: %d. "
                "Surviving threads: %s. "
                "This can cause xdist flakes and use-after-free crashes.",
                leaked_count,
                baseline_python_threads,
                final_python_threads,
                surviving_threads,
            )

        # FAIL_ON_THREAD_LEAK: Make tests fail on thread leaks (opt-in strict mode)
        if FAIL_ON_THREAD_LEAK and (pool_leaked or python_leaked):
            pytest.fail(
                f"THREAD LEAK DETECTED (SHOTBOT_TEST_FAIL_ON_THREAD_LEAK=1)\n"
                f"QThreadPool: {baseline_pool_threads} -> {final_pool_threads} "
                f"(+{final_pool_threads - baseline_pool_threads})\n"
                f"Python threads: {baseline_python_threads} -> {final_python_threads} "
                f"(+{final_python_threads - baseline_python_threads})\n"
                f"Surviving: {surviving_threads or 'N/A'}",
                pytrace=False,
            )
