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
    from typing import Any

    from PySide6.QtWidgets import QApplication

_logger = logging.getLogger(__name__)

# Strict mode fails on cleanup exceptions (useful for debugging)
# Auto-enabled in CI environments to catch thread leaks early
STRICT_CLEANUP = (
    os.environ.get("SHOTBOT_TEST_STRICT_CLEANUP", "0") == "1"
    or os.environ.get("CI") == "true"
    or os.environ.get("GITHUB_ACTIONS") == "true"
)

# Fail mode: pytest.fail() on thread leaks
# Enabled by default to catch thread leaks early in development
# STRICT_CLEANUP only logs warnings; FAIL_ON_THREAD_LEAK makes tests fail
# Opt-out with SHOTBOT_TEST_ALLOW_THREAD_LEAKS=1 for quick local runs
FAIL_ON_THREAD_LEAK = (
    os.environ.get("SHOTBOT_TEST_ALLOW_THREAD_LEAKS", "0") != "1"
    and os.environ.get("SHOTBOT_TEST_FAIL_ON_THREAD_LEAK", "1") == "1"
)

# Thread count tolerance - reduced from 2 to 1 to catch single-thread leaks
# Daemon threads and pytest internals may vary, but tolerance of 2 masked leaks
_THREAD_TOLERANCE = 1

# Thread wait timeout in ms - configurable via env var for slow CI runners
# Increased from 100ms to 500ms to handle real QThreadPool workloads
_THREAD_WAIT_TIMEOUT_MS = int(os.environ.get("SHOTBOT_TEST_THREAD_WAIT_MS", "500"))

# Thread name allowlist: Known harmless daemon threads that may persist
# These are system/library threads outside our control, not application leaks
_EXPECTED_THREAD_PREFIXES: frozenset[str] = frozenset({
    "_GC_Monitor",       # Python garbage collector monitor (some builds)
    "pytest_timeout",    # pytest-timeout watchdog thread
    "QDBusConnection",   # Qt D-Bus integration thread
    "PoolThread-",       # QThreadPool internal threads (expected to drain)
    "Thread-",           # Generic Python threads (check daemon flag separately)
    "pydevd.",           # PyCharm/debugger threads
    "Dummy-",            # Threading module dummy threads
})

# Session-level leak tracking (populated in CI/strict mode)
# Collects leak info for summary at session end instead of per-test spam
_thread_leak_summary: list[dict[str, Any]] = []


def get_thread_leak_summary() -> str | None:
    """Get formatted thread leak summary for session end.

    Returns:
        Formatted summary string if leaks were detected, None otherwise.
        Also clears the leak list after generating summary.

    """
    if not _thread_leak_summary:
        return None

    # Group by surviving thread names for actionable insights
    thread_counts: dict[str, int] = {}
    for leak in _thread_leak_summary:
        for thread in leak.get("threads", []):
            thread_counts[thread] = thread_counts.get(thread, 0) + 1

    sorted_threads = sorted(thread_counts.items(), key=lambda x: -x[1])

    lines = [
        "",
        "=" * 70,
        f"THREAD LEAK SUMMARY: {len(_thread_leak_summary)} test(s) had thread leaks",
        "=" * 70,
        "",
        "Most common surviving threads (fix these first):",
    ]
    for thread, count in sorted_threads[:10]:
        lines.append(f"  {count:3d}x  {thread}")

    if len(_thread_leak_summary) <= 5:
        lines.append("")
        lines.append("Affected tests:")
        lines.extend(f"  - {leak['test']}" for leak in _thread_leak_summary)
    else:
        lines.append("")
        lines.append(f"First 5 affected tests (of {len(_thread_leak_summary)}):")
        lines.extend(f"  - {leak['test']}" for leak in _thread_leak_summary[:5])
        lines.append("")
        lines.append("Run with SHOTBOT_TEST_FAIL_ON_THREAD_LEAK=1 to fail on leaks.")

    lines.append("=" * 70)
    lines.append("")

    # Clear for next session
    _thread_leak_summary.clear()

    return "\n".join(lines)


def _is_expected_thread(thread_name: str) -> bool:
    """Check if a thread name matches known harmless patterns.

    Args:
        thread_name: The thread name to check (e.g., "Thread-1", "pytest_timeout")

    Returns:
        True if the thread is expected/harmless, False if it's a potential leak

    """
    return any(thread_name.startswith(prefix) for prefix in _EXPECTED_THREAD_PREFIXES)


@pytest.fixture  # NOTE: No longer autouse - applied conditionally via conftest.py hook
def qt_cleanup(qapp: QApplication, request: pytest.FixtureRequest) -> Iterator[None]:
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
        _logger.warning("Qt cleanup before-test exception (check for orphaned Qt objects): %s", e)
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
        pool.waitForDone(_THREAD_WAIT_TIMEOUT_MS)  # Configurable via SHOTBOT_TEST_THREAD_WAIT_MS

        # Backoff loop if still active - handles slow thread shutdowns
        if pool.activeThreadCount() > 0:
            for backoff_ms in [100, 200, 500]:
                pool.waitForDone(backoff_ms)
                if pool.activeThreadCount() == 0:
                    break

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
                _logger.warning("Qt cleanup thread-wait exception (check for deleted Qt objects): %s", e)
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
        _logger.warning("Qt cleanup after-test exception (check for orphaned Qt objects): %s", e)
        if STRICT_CLEANUP:
            raise

    # THREAD LEAK DETECTION: Compare current thread counts to baseline
    # Collects to session summary instead of per-test logging (reduces noise)
    if STRICT_CLEANUP or FAIL_ON_THREAD_LEAK:
        final_pool_threads = QThreadPool.globalInstance().activeThreadCount()
        final_python_threads = threading.active_count()

        # Track if any leaks detected
        pool_leaked = final_pool_threads > baseline_pool_threads
        python_leaked = final_python_threads > baseline_python_threads + _THREAD_TOLERANCE

        # Collect surviving thread info for analysis
        all_surviving: list[str] = []
        unexpected_threads: list[str] = []
        if pool_leaked or python_leaked:
            for t in threading.enumerate():
                if t.name == "MainThread":
                    continue
                thread_info = f"{t.name} (daemon={t.daemon})"
                all_surviving.append(thread_info)
                # Only flag unexpected threads as leaks
                if not _is_expected_thread(t.name):
                    unexpected_threads.append(thread_info)

            # Only report leak if there are UNEXPECTED threads
            # Expected daemon threads (pytest_timeout, etc.) are not leaks
            if unexpected_threads:
                # Collect leak info for session-end summary (no per-test spam)
                _thread_leak_summary.append({
                    "test": request.node.nodeid,
                    "pool": (baseline_pool_threads, final_pool_threads),
                    "python": (baseline_python_threads, final_python_threads),
                    "threads": unexpected_threads,
                    "all_threads": all_surviving,  # Full list for debugging
                })

        # FAIL_ON_THREAD_LEAK: Make tests fail immediately (enabled by default)
        # Only fail if there are UNEXPECTED threads (not just daemon count increase)
        # Skip failure for tests marked with @pytest.mark.thread_leak_ok
        has_leak_ok_marker = "thread_leak_ok" in [
            m.name for m in request.node.iter_markers()
        ]
        if FAIL_ON_THREAD_LEAK and unexpected_threads and not has_leak_ok_marker:
            pytest.fail(
                f"THREAD LEAK DETECTED (FAIL_ON_THREAD_LEAK is enabled by default)\n"
                f"QThreadPool: {baseline_pool_threads} -> {final_pool_threads} "
                f"(+{final_pool_threads - baseline_pool_threads})\n"
                f"Python threads: {baseline_python_threads} -> {final_python_threads} "
                f"(+{final_python_threads - baseline_python_threads})\n"
                f"Unexpected threads: {unexpected_threads}\n"
                f"(Expected threads filtered: {_EXPECTED_THREAD_PREFIXES})\n"
                f"To opt-out, add @pytest.mark.thread_leak_ok or set "
                f"SHOTBOT_TEST_ALLOW_THREAD_LEAKS=1",
                pytrace=False,
            )
