"""Central registry for singleton cleanup in tests.

This module provides the SingletonRegistry class that manages cleanup of all
singleton instances in the codebase. It ensures proper cleanup ordering and
provides a single source of truth for which singletons need reset.

Usage:
    from tests.fixtures.singleton_registry import SingletonRegistry

    # Reset all singletons (typically in fixture cleanup)
    errors = SingletonRegistry.reset_all()
    if errors:
        for path, exc in errors:
            logging.warning(f"Singleton reset failed: {path}: {exc}")

    # Verify all registered singletons have reset() methods
    missing = SingletonRegistry.verify_all_have_reset()
    if missing:
        warnings.warn(f"Singletons missing reset(): {missing}")
"""

from __future__ import annotations

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
            # Check if this class is registered (by class name)
            if class_name not in registered_names:
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
    "notification_manager.NotificationManager",
    cleanup_order=10,
    description="Toast notifications and status bar messaging",
)
SingletonRegistry.register(
    "progress_manager.ProgressManager",
    cleanup_order=15,
    description="Progress dialogs and operation tracking",
)

# 20-29: Worker/Runnable Tracking
SingletonRegistry.register(
    "runnable_tracker.QRunnableTracker",
    cleanup_order=20,
    description="Tracks QRunnable lifecycle for cleanup",
)
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
SingletonRegistry.register(
    "filesystem_coordinator.FilesystemCoordinator",
    cleanup_order=41,
    description="Filesystem caching and coordination",
)
SingletonRegistry.register(
    "timeout_config.TimeoutConfig",
    cleanup_order=42,
    description="Timeout configuration constants",
)
