"""Qt cleanup fixture for test isolation.

This module provides the qt_cleanup autouse fixture that ensures Qt state
is properly cleaned between tests, preventing crashes and test contamination
in large test suites.

Fixtures:
    qt_cleanup: Clean up Qt state between tests (autouse)

Environment Variables:
    SHOTBOT_TEST_STRICT_CLEANUP: Set to "1" to fail on cleanup exceptions instead of swallowing them
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
STRICT_CLEANUP = os.environ.get("SHOTBOT_TEST_STRICT_CLEANUP", "0") == "1"


@pytest.fixture  # NOTE: No longer autouse - applied conditionally via conftest.py hook
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

    Args:
        qapp: QApplication fixture from qt_bootstrap
    """
    import threading
    import time

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
