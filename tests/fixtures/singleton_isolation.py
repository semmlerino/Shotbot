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
    """Clear ALL config files for pristine test state.

    This clears ALL files in the config directory, not just known ones.
    This ensures that tests creating new config files don't leak state
    to subsequent tests within the same xdist worker.

    Known files (for documentation):
    - custom_launchers.json
    - settings.json
    - window_state.json

    FAILS on unexpected artifacts to catch test isolation issues early.

    Raises:
        RuntimeError: If unexpected config files or directories are found.
    """
    config_dir = os.environ.get("SHOTBOT_CONFIG_DIR")
    if not config_dir:
        return

    config_path = Path(config_dir)
    if not config_path.exists():
        return

    # Known config files
    known_files = {"custom_launchers.json", "settings.json", "window_state.json"}

    # Track unexpected artifacts for error reporting
    unexpected_files: list[str] = []
    unexpected_dirs: list[str] = []

    # Clear ALL files in config dir
    for item in config_path.iterdir():
        if item.is_file():
            if item.name not in known_files:
                unexpected_files.append(item.name)
            try:
                item.unlink()
            except OSError:
                pass  # Best-effort cleanup
        elif item.is_dir():
            # Clear unexpected directories recursively for complete isolation
            import shutil

            unexpected_dirs.append(item.name)
            shutil.rmtree(item, ignore_errors=True)

    # Fail on unexpected artifacts to catch test isolation issues
    if unexpected_files or unexpected_dirs:
        msg_parts = ["Test leaked unexpected config artifacts (isolation failure):"]
        if unexpected_files:
            msg_parts.append(f"  Files: {unexpected_files}")
        if unexpected_dirs:
            msg_parts.append(f"  Directories: {unexpected_dirs}")
        raise RuntimeError("\n".join(msg_parts))


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

    Known cache files:
    - shots.json
    - previous_shots.json
    - threede_scenes.json
    - migrated_shots.json

    Preserved directories (expensive to regenerate):
    - thumbnails/

    FAILS on unexpected artifacts to catch test isolation issues early.

    Note: Use clean_thumbnails fixture from tests.fixtures.caching for thumbnail isolation.

    Raises:
        RuntimeError: If unexpected cache files or directories are found.
    """
    cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")
    if not cache_dir:
        return

    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return

    # Known cache files and directories
    known_files = {
        "shots.json",
        "previous_shots.json",
        "threede_scenes.json",
        "migrated_shots.json",
    }
    known_dirs = {"production", "thumbnails"}

    # Track unexpected artifacts for error reporting
    unexpected_files: list[str] = []
    unexpected_dirs: list[str] = []

    # Clear from root cache dir and production subdirectory
    for subdir in [cache_path, cache_path / "production"]:
        if not subdir.exists():
            continue

        for item in subdir.iterdir():
            if item.is_file():
                # Clear ALL files (not just .json) for complete test isolation
                if item.name not in known_files:
                    unexpected_files.append(f"{subdir.name}/{item.name}")
                try:
                    item.unlink()
                except OSError:
                    pass  # Best-effort cleanup
            elif item.is_dir():
                # Clear unexpected directories (except known ones like thumbnails)
                if item.name not in known_dirs:
                    import shutil

                    unexpected_dirs.append(f"{subdir.name}/{item.name}")
                    shutil.rmtree(item, ignore_errors=True)

    # Fail on unexpected artifacts to catch test isolation issues
    if unexpected_files or unexpected_dirs:
        msg_parts = ["Test leaked unexpected cache artifacts (isolation failure):"]
        if unexpected_files:
            msg_parts.append(f"  Files: {unexpected_files}")
        if unexpected_dirs:
            msg_parts.append(f"  Directories: {unexpected_dirs}")
        raise RuntimeError("\n".join(msg_parts))

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
def reset_singletons(reset_caches: None) -> Iterator[None]:
    """Heavy cleanup for Qt tests - singletons, threads, Qt state.

    NOTE: This fixture is NOT autouse. It is applied conditionally via
    conftest.py's pytest_collection_modifyitems hook to tests that use qtbot
    or are marked with @pytest.mark.qt.

    IMPORTANT: Depends on reset_caches fixture to ensure caches are cleared
    before singletons are reset. This prevents singletons from loading stale
    cached data during initialization.

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
