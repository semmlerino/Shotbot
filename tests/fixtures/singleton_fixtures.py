"""Singleton registry and isolation fixtures.

Consolidated from:
- singleton_registry.py:  SingletonRegistry class, known singleton registrations
- singleton_isolation.py: reset_caches (autouse), reset_singletons, cleanup_state_heavy

Classes:
    SingletonRegistry: Central registry for all resettable singletons

Fixtures:
    reset_caches (autouse): Lightweight cleanup for ALL tests
    reset_singletons:       Heavy cleanup for Qt tests
    cleanup_state_heavy:    Alias for reset_singletons (backward compatibility)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# singleton_registry contents
# ---------------------------------------------------------------------------
import logging
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, ClassVar


if TYPE_CHECKING:
    from typing import Protocol, runtime_checkable

    @runtime_checkable
    class ResettableSingleton(Protocol):
        """Protocol for singletons that can be reset for testing."""

        @classmethod
        def reset(cls) -> None: ...


_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SingletonEntry:
    """Registry entry for a singleton class."""

    import_path: str  # e.g., "notification_manager.NotificationManager"
    cleanup_order: int  # Lower = earlier cleanup
    description: str = ""


class SingletonRegistry:
    """Central registry for all resettable singletons with ordered cleanup.

    Cleanup order rationale:
    - 10-19: Qt UI singletons (must clean up first before infrastructure)
    - 20-29: Worker/runnable tracking (cleanup before pool shutdown)
    - 30-39: Process pools (shutdown before filesystem cleanup)
    - 40-49: Infrastructure (filesystem, etc.)

    Attributes:
        _entries: List of registered singleton entries (immutable after init)

    """

    # Static registry - populated at import time
    _entries: ClassVar[list[SingletonEntry]] = []

    @classmethod
    def register(
        cls,
        import_path: str,
        cleanup_order: int = 50,
        description: str = "",
    ) -> None:
        """Register a singleton for cleanup.

        Args:
            import_path: Fully qualified path like "module.ClassName"
            cleanup_order: Lower values clean up first (default: 50)
            description: Optional description for debugging

        Raises:
            ValueError: If cleanup_order is already used (non-deterministic cleanup)
            ValueError: If import_path cannot be resolved to a valid class

        """
        # FAIL-FAST: Duplicate cleanup orders cause non-deterministic cleanup sequence
        existing_orders = {e.cleanup_order: e.import_path for e in cls._entries}
        if cleanup_order in existing_orders:
            msg = (
                f"Duplicate cleanup order {cleanup_order}: "
                f"existing={existing_orders[cleanup_order]}, new={import_path}. "
                f"Use a unique cleanup_order for deterministic cleanup sequence."
            )
            raise ValueError(msg)

        # FAIL-FAST: Validate import path resolves to a real class
        singleton_cls = cls._get_class(import_path)
        if singleton_cls is None:
            msg = f"Cannot import singleton class: {import_path}"
            raise ValueError(msg)

        entry = SingletonEntry(
            import_path=import_path,
            cleanup_order=cleanup_order,
            description=description,
        )
        cls._entries.append(entry)
        # Keep sorted by cleanup_order
        cls._entries.sort(key=lambda e: e.cleanup_order)
        _logger.debug("Registered singleton: %s (order=%d)", import_path, cleanup_order)

    @classmethod
    def _get_class(cls, import_path: str) -> type | None:
        """Import and return the class for the given import path.

        Args:
            import_path: Fully qualified path like "module.ClassName"

        Returns:
            The class, or None if import failed

        """
        try:
            module_name, class_name = import_path.rsplit(".", 1)
            module = import_module(module_name)
            return getattr(module, class_name)
        except (ImportError, AttributeError, ValueError) as e:
            _logger.debug("Failed to import %s: %s", import_path, e)
            return None

    @classmethod
    def reset_all(cls, strict: bool = False) -> list[tuple[str, Exception]]:
        """Reset all registered singletons in cleanup order.

        Args:
            strict: If True, re-raise exceptions after collecting them

        Returns:
            List of (import_path, exception) tuples for any failures

        """
        errors: list[tuple[str, Exception]] = []

        for entry in cls._entries:
            singleton_cls = cls._get_class(entry.import_path)
            if singleton_cls is None:
                continue

            try:
                singleton_cls.reset()
                _logger.debug("Reset singleton: %s", entry.import_path)
            except Exception as e:
                _logger.debug("Singleton reset failed: %s: %s", entry.import_path, e)
                errors.append((entry.import_path, e))
                if strict:
                    raise

        return errors

    @classmethod
    def verify_all_have_reset(cls) -> list[str]:
        """Verify all registered singletons have a reset() classmethod.

        Returns:
            List of import paths for singletons missing reset() method

        """
        missing: list[str] = []

        for entry in cls._entries:
            singleton_cls = cls._get_class(entry.import_path)
            if singleton_cls is None:
                # Import failed - might be expected in some test configurations
                continue

            if not hasattr(singleton_cls, "reset") or not callable(
                getattr(singleton_cls, "reset", None)
            ):
                missing.append(entry.import_path)

        return missing

    @classmethod
    def get_entries(cls) -> list[SingletonEntry]:
        """Return a copy of all registered entries (for inspection)."""
        return list(cls._entries)

    @classmethod
    def clear(cls) -> None:
        """Clear all entries (for testing the registry itself)."""
        cls._entries.clear()

    @classmethod
    def verify_all_singletons_registered(cls) -> list[str]:
        """Check that all SingletonMixin subclasses are registered.

        Auto-registers any subclass that declares _cleanup_order >= 0.
        Returns unregistered subclasses that still need manual registration.

        This catches cases where a developer creates a new SingletonMixin
        subclass but forgets to register it in the registry.

        Returns:
            List of fully qualified class names that are unregistered

        """
        from singleton_mixin import SingletonMixin

        # Get all registered class names (just the class name, not full path)
        registered_names = {e.import_path.split(".")[-1] for e in cls._entries}

        unregistered: list[str] = []
        for subclass in SingletonMixin._known_subclasses:
            # Skip abstract or test classes
            if subclass.__module__.startswith("tests."):
                continue

            class_name = subclass.__name__
            if class_name not in registered_names:
                cleanup_order = getattr(subclass, "_cleanup_order", -1)
                if cleanup_order >= 0:
                    full_path = f"{subclass.__module__}.{class_name}"
                    description = getattr(subclass, "_singleton_description", "")
                    try:
                        cls.register(full_path, cleanup_order=cleanup_order, description=description)
                        _logger.info("Auto-registered singleton: %s (order=%d)", full_path, cleanup_order)
                    except ValueError as e:
                        _logger.warning("Auto-registration failed for %s: %s", full_path, e)
                        unregistered.append(full_path)
                else:
                    full_path = f"{subclass.__module__}.{class_name}"
                    unregistered.append(full_path)

        return unregistered


# =============================================================================
# Register known singletons
# =============================================================================
# Order matters! Lower numbers clean up first.
# Qt UI components clean up before infrastructure to avoid dangling references.

# 10-19: Qt UI Singletons (must clean up first)
SingletonRegistry.register(
    "managers.notification_manager.NotificationManager",
    cleanup_order=10,
    description="Toast notifications and status bar messaging",
)
SingletonRegistry.register(
    "managers.progress_manager.ProgressManager",
    cleanup_order=15,
    description="Progress dialogs and operation tracking",
)

# 20-29: Worker/Runnable Tracking
# QRunnableTracker auto-registers via _cleanup_order=20 on the class.
SingletonRegistry.register(
    "thread_safe_worker.ThreadSafeWorker",
    cleanup_order=25,
    description="Zombie worker cleanup timer",
)

# 30-39: Process Pools
SingletonRegistry.register(
    "process_pool_manager.ProcessPoolManager",
    cleanup_order=30,
    description="Subprocess execution and caching",
)

# 40-49: Infrastructure
SingletonRegistry.register(
    "design_system.DesignSystem",
    cleanup_order=40,
    description="Design system with colors, typography, spacing, borders, shadows, and animation",
)
# FilesystemCoordinator auto-registers via _cleanup_order=41 on the class.
SingletonRegistry.register(
    "timeout_config.TimeoutConfig",
    cleanup_order=42,
    description="Timeout configuration constants",
)


# ---------------------------------------------------------------------------
# singleton_isolation contents
# ---------------------------------------------------------------------------

import gc
import os
import warnings
from pathlib import Path
from typing import TYPE_CHECKING as _TYPE_CHECKING

import pytest


if _TYPE_CHECKING:
    from collections.abc import Iterator

_isolation_logger = logging.getLogger(__name__)


def _clear_config_files() -> None:
    """Clear ALL config files for pristine test state.

    This clears ALL files in the config directory, not just known ones.
    This ensures that tests creating new config files don't leak state
    to subsequent tests within the same xdist worker.

    Known files (for documentation):
    - custom_launchers.json
    - settings.json
    - window_state.json

    Warns on unexpected artifacts to catch test isolation issues early.

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

    # Warn on unexpected artifacts to catch test isolation issues without failing
    if unexpected_files or unexpected_dirs:
        msg_parts = ["Test leaked unexpected config artifacts (isolation failure):"]
        if unexpected_files:
            msg_parts.append(f"  Files: {unexpected_files}")
        if unexpected_dirs:
            msg_parts.append(f"  Directories: {unexpected_dirs}")
        warnings.warn("\n".join(msg_parts), stacklevel=2)


def _clear_stat_caches() -> None:
    """Clear ThumbnailCache stat cache for test isolation.

    The stat cache has a 2-second TTL which can leak between fast tests.
    ThumbnailCache is no longer a singleton, so stat caches on individual
    instances expire naturally. This function is retained as a no-op hook
    for future use if a central registry is introduced.
    """
    # ThumbnailCache stat caches are per-instance; no singleton to clear


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

    Warns on unexpected artifacts to catch test isolation issues early.

    Note: Use clean_thumbnails fixture from tests.fixtures.environment_fixtures for thumbnail isolation.

    """
    cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")
    if not cache_dir:
        return

    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return

    # Known cache files and directories (including .lock sidecar files from
    # filelock-style atomic writes used by CacheManager)
    known_files = {
        "shots.json",
        "previous_shots.json",
        "threede_scenes.json",
        "migrated_shots.json",
        "shots.json.lock",
        "previous_shots.json.lock",
        "threede_scenes.json.lock",
        "migrated_shots.json.lock",
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

    # Warn on unexpected artifacts to catch test isolation issues without failing
    if unexpected_files or unexpected_dirs:
        msg_parts = ["Test leaked unexpected cache artifacts (isolation failure):"]
        if unexpected_files:
            msg_parts.append(f"  Files: {unexpected_files}")
        if unexpected_dirs:
            msg_parts.append(f"  Directories: {unexpected_dirs}")
        warnings.warn("\n".join(msg_parts), stacklevel=2)


# Strict mode fails on cleanup exceptions (auto-enabled in CI)
STRICT_CLEANUP = (
    os.environ.get("SHOTBOT_TEST_STRICT_CLEANUP", "0") == "1"
    or os.environ.get("CI") == "true"
    or os.environ.get("GITHUB_ACTIONS") == "true"
)

# Aggressive GC mode - only run gc.collect() when explicitly requested
AGGRESSIVE_GC = os.environ.get("SHOTBOT_TEST_AGGRESSIVE_GC", "0") == "1"


@pytest.fixture(autouse=True)
def reset_caches(request: pytest.FixtureRequest) -> Iterator[None]:
    """Lightweight cleanup for ALL tests - caches and config reset before each test.

    This autouse fixture provides minimal cleanup that runs for every test,
    including pure logic tests that don't touch Qt or singletons.

    Before test:
    - Clear all utility caches (in-memory)
    - Clear disk cache files (shots.json, etc.) - unless @persistent_cache marker
    - Re-enable caching (in case previous test disabled it)
    - Reset Config.SHOWS_ROOT
    - Clear OptimizedShotParser pattern cache

    After test:
    - gc.collect() only if SHOTBOT_TEST_AGGRESSIVE_GC=1

    Note: After-test cache clearing is handled by the next test's before-test
    cleanup, eliminating redundant work in the hot path.

    For heavy cleanup (Qt, singletons, threads), see reset_singletons fixture.

    MARKERS:
        @pytest.mark.persistent_cache: Skip disk cache clearing for this test.
            Use this when testing cache loading, migration, or corruption handling.
    """
    from tests.fixtures.environment_fixtures import clear_all_caches, enable_caching

    # Check for persistent_cache marker (skip disk cache clearing)
    skip_cache_clear = "persistent_cache" in [
        m.name for m in request.node.iter_markers()
    ]

    # ===== BEFORE TEST: Lightweight setup =====
    clear_all_caches()
    enable_caching()  # Re-enable in case previous test disabled it

    # Clear disk cache files (shots.json, etc.) for pristine state
    # Skip if test has @pytest.mark.persistent_cache marker
    if not skip_cache_clear:
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
        _isolation_logger.debug("Config.SHOWS_ROOT reset before-test exception: %s", e)
        if STRICT_CLEANUP:
            raise

    # Clear OptimizedShotParser pattern cache
    try:
        from shots import shot_parser

        shot_parser._PATTERN_CACHE.clear()
    except (RuntimeError, AttributeError, ImportError) as e:
        _isolation_logger.debug("shot_parser cache clear exception: %s", e)
        if STRICT_CLEANUP:
            raise

    yield

    # ===== AFTER TEST: Minimal cleanup =====
    # Only run gc.collect() if explicitly requested (reduces overhead)
    if AGGRESSIVE_GC:
        gc.collect()


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

    # ===== BEFORE TEST: Reset all singletons =====
    errors = SingletonRegistry.reset_all(strict=STRICT_CLEANUP)
    for path, exc in errors:
        _isolation_logger.debug("Singleton reset before-test failed: %s: %s", path, exc)
        # Emit warning so it's visible in test output
        warnings.warn(
            f"Singleton reset failed (before-test): {path}: {exc}",
            UserWarning,
            stacklevel=2,
        )

    yield

    # ===== AFTER TEST: Reset singletons =====
    # Note: Qt event processing is handled by qt_cleanup fixture
    errors = SingletonRegistry.reset_all(strict=STRICT_CLEANUP)
    for path, exc in errors:
        _isolation_logger.debug("Singleton reset after-test failed: %s: %s", path, exc)
        # Emit warning so it's visible in test output
        warnings.warn(
            f"Singleton reset failed (after-test): {path}: {exc}",
            UserWarning,
            stacklevel=2,
        )


# Backward compatibility alias
cleanup_state_heavy = reset_singletons
