"""Singleton and cache isolation fixtures for test isolation.

This module provides the cleanup_state autouse fixture that ensures singleton
state and caches are properly reset between tests, preventing test contamination
and flaky behavior.

Fixtures:
    cleanup_state: Reset singletons and caches between tests (autouse)

Environment Variables:
    SHOTBOT_TEST_STRICT_CLEANUP: Set to "1" to fail on cleanup exceptions instead of swallowing them
"""

from __future__ import annotations

import gc
import logging
import os
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator

_logger = logging.getLogger(__name__)

# Strict mode fails on cleanup exceptions (useful for debugging)
STRICT_CLEANUP = os.environ.get("SHOTBOT_TEST_STRICT_CLEANUP", "0") == "1"


@pytest.fixture(autouse=True)
def cleanup_state_lite() -> Iterator[None]:
    """Lightweight cleanup for ALL tests - just caches and config.

    This autouse fixture provides minimal cleanup that runs for every test,
    including pure logic tests that don't touch Qt or singletons.

    Before test:
    - Clear all utility caches
    - Disable caching for predictable behavior
    - Reset Config.SHOWS_ROOT

    After test:
    - Clear caches again
    - Force garbage collection

    For heavy cleanup (Qt, singletons, threads), see cleanup_state_heavy fixture.
    """
    from utils import clear_all_caches, disable_caching

    # ===== BEFORE TEST: Lightweight setup =====
    clear_all_caches()
    disable_caching()

    # Reset Config.SHOWS_ROOT
    try:
        from config import Config

        Config.SHOWS_ROOT = os.environ.get("SHOWS_ROOT", "/shows")
    except (RuntimeError, AttributeError, ImportError) as e:
        _logger.debug("Config.SHOWS_ROOT reset before-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    # Clear OptimizedShotParser pattern cache
    try:
        import optimized_shot_parser

        optimized_shot_parser._PATTERN_CACHE.clear()
    except (RuntimeError, AttributeError, ImportError) as e:
        _logger.debug("optimized_shot_parser cache clear exception: %s", e)
        if STRICT_CLEANUP:
            raise

    yield

    # ===== AFTER TEST: Lightweight cleanup =====
    clear_all_caches()
    disable_caching()

    # Reset Config.SHOWS_ROOT
    try:
        from config import Config

        Config.SHOWS_ROOT = os.environ.get("SHOWS_ROOT", "/shows")
    except (RuntimeError, AttributeError, ImportError) as e:
        _logger.debug("Config.SHOWS_ROOT reset after-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    gc.collect()


@pytest.fixture
def cleanup_state_heavy() -> Iterator[None]:
    """Heavy cleanup for Qt tests - singletons, threads, Qt state.

    NOTE: This fixture is NOT autouse. It is applied conditionally via
    conftest.py's pytest_collection_modifyitems hook to tests that use qtbot
    or are marked with @pytest.mark.qt.

    Before test:
    - Reset NotificationManager and ProgressManager singletons
    - Reset FilesystemCoordinator

    After test:
    - Process pending Qt events
    - Reset all singletons (ProcessPoolManager, QRunnableTracker, ThreadSafeWorker)
    """
    from notification_manager import NotificationManager
    from progress_manager import ProgressManager

    # ===== BEFORE TEST: Reset singletons =====

    # Reset all singleton managers using their reset() methods
    # Order matters: NotificationManager FIRST (closes Qt widgets that ProgressManager may reference)
    try:
        NotificationManager.reset()
    except (RuntimeError, AttributeError) as e:
        _logger.debug("NotificationManager.reset() before-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    # THEN reset ProgressManager (now safe to clear widget references)
    try:
        ProgressManager.reset()
    except (RuntimeError, AttributeError) as e:
        _logger.debug("ProgressManager.reset() before-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    # Reset FilesystemCoordinator
    try:
        from filesystem_coordinator import FilesystemCoordinator

        FilesystemCoordinator.reset()
    except (RuntimeError, AttributeError, ImportError) as e:
        _logger.debug("FilesystemCoordinator.reset() before-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    yield

    # ===== AFTER TEST: Comprehensive cleanup =====

    # Qt Event Processing - Process pending events before cleanup
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app:
            app.processEvents()
    except (RuntimeError, ImportError) as e:
        _logger.debug("Qt event processing after-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    # Reset all singleton managers
    try:
        NotificationManager.reset()
    except (RuntimeError, AttributeError) as e:
        _logger.debug("NotificationManager.reset() after-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    try:
        ProgressManager.reset()
    except (RuntimeError, AttributeError) as e:
        _logger.debug("ProgressManager.reset() after-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    # QRunnableTracker Cleanup
    from runnable_tracker import QRunnableTracker

    try:
        QRunnableTracker.reset()
    except Exception as e:
        _logger.debug("QRunnableTracker.reset() exception: %s", e)
        if STRICT_CLEANUP:
            raise

    # ProcessPoolManager Cleanup
    from process_pool_manager import ProcessPoolManager

    try:
        ProcessPoolManager.reset()
    except Exception as e:
        _logger.debug("ProcessPoolManager.reset() exception: %s", e)
        if STRICT_CLEANUP:
            raise

    # FilesystemCoordinator Cleanup
    from filesystem_coordinator import FilesystemCoordinator

    try:
        FilesystemCoordinator.reset()
    except Exception as e:
        _logger.debug("FilesystemCoordinator.reset() after-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    # ThreadSafeWorker Zombie Cleanup
    from thread_safe_worker import ThreadSafeWorker

    try:
        ThreadSafeWorker.reset()
    except Exception as e:
        _logger.debug("ThreadSafeWorker.reset() exception: %s", e)
        if STRICT_CLEANUP:
            raise


# Backward compatibility alias - some tests may reference cleanup_state directly
@pytest.fixture
def cleanup_state(cleanup_state_lite: None, cleanup_state_heavy: None) -> Iterator[None]:
    """Combined cleanup fixture for backward compatibility.

    This fixture combines both lite and heavy cleanup. Use this if you explicitly
    need both, but prefer using cleanup_state_heavy directly for Qt tests.
    """
    yield
