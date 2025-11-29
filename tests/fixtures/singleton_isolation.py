"""Singleton and cache isolation fixtures for test isolation.

This module provides the cleanup_state autouse fixture that ensures singleton
state and caches are properly reset between tests, preventing test contamination
and flaky behavior.

Fixtures:
    reset_caches (autouse): Lightweight cleanup for ALL tests - caches and config
    reset_singletons: Heavy cleanup for Qt tests - singletons, threads
    cleanup_state_lite: Alias for reset_caches (backward compatibility)
    cleanup_state_heavy: Alias for reset_singletons (backward compatibility)

Environment Variables:
    SHOTBOT_TEST_STRICT_CLEANUP: Set to "1" to fail on cleanup exceptions
    SHOTBOT_TEST_AGGRESSIVE_GC: Set to "1" to run gc.collect() after each test
    CI / GITHUB_ACTIONS: Auto-enables STRICT_CLEANUP in CI environments
"""

from __future__ import annotations

import gc
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator

_logger = logging.getLogger(__name__)


def _clear_config_files() -> None:
    """Clear config files for pristine test state.

    Config files cleared:
    - custom_launchers.json
    - settings.json
    - window_state.json

    This prevents config state from one test leaking to subsequent tests
    within the same xdist worker (which shares SHOTBOT_CONFIG_DIR).
    """
    config_dir = os.environ.get("SHOTBOT_CONFIG_DIR")
    if not config_dir:
        return

    config_path = Path(config_dir)
    if not config_path.exists():
        return

    config_files = ["custom_launchers.json", "settings.json", "window_state.json"]
    for filename in config_files:
        config_file = config_path / filename
        if config_file.exists():
            try:
                config_file.unlink()
            except OSError:
                pass  # Best-effort cleanup


def _clear_stat_caches() -> None:
    """Clear CacheManager stat cache for test isolation.

    The stat cache has a 2-second TTL which can leak between fast tests.
    Clearing it ensures each test gets fresh filesystem stat results.
    """
    try:
        from cache_manager import CacheManager

        if CacheManager._instance is not None:
            CacheManager._instance._stat_cache.clear()
    except (ImportError, AttributeError):
        pass  # CacheManager not imported or no instance


def _clear_disk_cache_files() -> None:
    """Clear disk cache files for pristine test state.

    This ensures each test starts with clean disk cache state while keeping
    directory creation overhead low (directories persist, only files removed).

    Cache files cleared:
    - shots.json
    - previous_shots.json
    - threede_scenes.json
    - migrated_shots.json

    Note: Thumbnails are NOT cleared (expensive to regenerate).
    Use clean_thumbnails fixture from tests.fixtures.caching for thumbnail isolation.
    """
    cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")
    if not cache_dir:
        return

    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return

    # JSON cache files to clear (not thumbnails - expensive to recreate)
    cache_files = [
        "shots.json",
        "previous_shots.json",
        "threede_scenes.json",
        "migrated_shots.json",
    ]

    # Clear from root cache dir and production subdirectory
    for subdir in [cache_path, cache_path / "production"]:
        if not subdir.exists():
            continue
        for filename in cache_files:
            cache_file = subdir / filename
            if cache_file.exists():
                try:
                    cache_file.unlink()
                except OSError:
                    pass  # Best-effort cleanup

# Strict mode fails on cleanup exceptions (auto-enabled in CI)
STRICT_CLEANUP = (
    os.environ.get("SHOTBOT_TEST_STRICT_CLEANUP", "0") == "1"
    or os.environ.get("CI") == "true"
    or os.environ.get("GITHUB_ACTIONS") == "true"
)

# Aggressive GC mode - only run gc.collect() when explicitly requested
AGGRESSIVE_GC = os.environ.get("SHOTBOT_TEST_AGGRESSIVE_GC", "0") == "1"


@pytest.fixture(autouse=True)
def reset_caches() -> Iterator[None]:
    """Lightweight cleanup for ALL tests - caches and config reset before each test.

    This autouse fixture provides minimal cleanup that runs for every test,
    including pure logic tests that don't touch Qt or singletons.

    Before test:
    - Clear all utility caches (in-memory)
    - Clear disk cache files (shots.json, etc.)
    - Re-enable caching (in case previous test disabled it)
    - Reset Config.SHOWS_ROOT
    - Clear OptimizedShotParser pattern cache

    After test:
    - gc.collect() only if SHOTBOT_TEST_AGGRESSIVE_GC=1

    Note: After-test cache clearing is handled by the next test's before-test
    cleanup, eliminating redundant work in the hot path.

    For heavy cleanup (Qt, singletons, threads), see reset_singletons fixture.
    """
    from utils import clear_all_caches, enable_caching

    # ===== BEFORE TEST: Lightweight setup =====
    clear_all_caches()
    enable_caching()  # Re-enable in case previous test disabled it

    # Clear disk cache files (shots.json, etc.) for pristine state
    _clear_disk_cache_files()

    # Clear config files to prevent test contamination within worker
    _clear_config_files()

    # Clear CacheManager stat cache (has 2s TTL that can leak between tests)
    _clear_stat_caches()

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

    # ===== AFTER TEST: Minimal cleanup =====
    # Only run gc.collect() if explicitly requested (reduces overhead)
    if AGGRESSIVE_GC:
        gc.collect()


# Backward compatibility alias
cleanup_state_lite = reset_caches


@pytest.fixture
def reset_singletons() -> Iterator[None]:
    """Heavy cleanup for Qt tests - singletons, threads, Qt state.

    NOTE: This fixture is NOT autouse. It is applied conditionally via
    conftest.py's pytest_collection_modifyitems hook to tests that use qtbot
    or are marked with @pytest.mark.qt.

    Before test:
    - Reset all registered singletons via SingletonRegistry

    After test:
    - Process pending Qt events (handled by qt_cleanup, not here)
    - Reset all registered singletons via SingletonRegistry

    Cleanup order is managed centrally by SingletonRegistry:
    - Qt UI singletons first (NotificationManager, ProgressManager)
    - Worker tracking (QRunnableTracker, ThreadSafeWorker)
    - Process pools (ProcessPoolManager)
    - Infrastructure (FilesystemCoordinator)
    """
    from tests.fixtures.singleton_registry import SingletonRegistry

    # ===== BEFORE TEST: Reset all singletons =====
    errors = SingletonRegistry.reset_all(strict=STRICT_CLEANUP)
    for path, exc in errors:
        _logger.debug("Singleton reset before-test failed: %s: %s", path, exc)

    yield

    # ===== AFTER TEST: Reset singletons =====
    # Note: Qt event processing is handled by qt_cleanup fixture
    errors = SingletonRegistry.reset_all(strict=STRICT_CLEANUP)
    for path, exc in errors:
        _logger.debug("Singleton reset after-test failed: %s: %s", path, exc)


# Backward compatibility alias
cleanup_state_heavy = reset_singletons


@pytest.fixture
def cleanup_state(reset_caches: None, reset_singletons: None) -> Iterator[None]:
    """Combined cleanup fixture for backward compatibility.

    This fixture combines both lite and heavy cleanup. Use this if you explicitly
    need both, but prefer using reset_singletons directly for Qt tests.
    """
    return
