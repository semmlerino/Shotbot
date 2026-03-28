"""Thread-safe singleton mixin to eliminate boilerplate singleton code.

This module provides a reusable SingletonMixin that implements a thread-safe
singleton pattern with proper test isolation support via reset().

Usage:
    from typing_compat import override

    class MyService(SingletonMixin):
        def __init__(self) -> None:
            if self._is_initialized():
                return
            super().__init__()
            # ... actual initialization ...
            self._mark_initialized()

        @classmethod
        @override  # Mark as override for type checker
        def _cleanup_instance(cls) -> None:
            if cls._instance is not None:
                cls._instance.shutdown()  # Your cleanup logic
"""

from __future__ import annotations

import threading
from typing import ClassVar, Self


class SingletonMixin:
    """Thread-safe singleton mixin with single-checked locking.

    Provides:
    - Thread-safe singleton creation via __new__
    - Initialization guard helpers (_is_initialized, _mark_initialized)
    - Test isolation via reset() classmethod
    - Customizable cleanup via _cleanup_instance() override
    - Automatic subclass tracking for test registry verification

    Thread Safety:
    Uses single-checked locking (check only inside lock) rather than
    double-checked locking pattern (DCLP). The outer check in DCLP is
    unsafe in Python because attribute access isn't atomic - another
    thread could see a partially-constructed object. The performance
    cost of always acquiring the lock is negligible since uncontended
    lock acquisition is cheap.

    Note: Subclasses must call _is_initialized() at the start of __init__
    and _mark_initialized() at the end to prevent re-initialization.
    """

    _instance: ClassVar[Self | None] = None  # type: ignore[misc]
    _lock: ClassVar[threading.RLock] = threading.RLock()  # RLock for reentrant cleanup
    _initialized: ClassVar[bool] = False

    # Track all subclasses for registry verification
    _known_subclasses: ClassVar[set[type]] = set()

    # Subclasses set these to enable auto-registration in SingletonRegistry.
    # -1 means "not configured, must register manually".
    _cleanup_order: ClassVar[int] = -1
    _singleton_description: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Track subclass for singleton registry verification.

        This hook is called when a class inherits from SingletonMixin,
        allowing the test infrastructure to verify all singletons are
        properly registered in SingletonRegistry.
        """
        super().__init_subclass__(**kwargs)
        SingletonMixin._known_subclasses.add(cls)

    def __new__(cls) -> Self:
        """Create singleton instance with thread-safe locking.

        Uses single-checked locking pattern for correctness. See class
        docstring for rationale on why DCLP is avoided.
        """
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                cls._instance = instance
            return cls._instance

    @classmethod
    def _is_initialized(cls) -> bool:
        """Check if singleton has been initialized.

        Use at the start of __init__ to guard against re-initialization:
            if self._is_initialized():
                return
        """
        return cls._initialized

    @classmethod
    def _mark_initialized(cls) -> None:
        """Mark singleton as initialized.

        Use at the end of __init__:
            self._mark_initialized()
        """
        cls._initialized = True

    @classmethod
    def _cleanup_instance(cls) -> None:
        """Override in subclass to provide cleanup logic.

        Called by reset() before clearing the singleton instance.
        Subclasses should override this to call their cleanup methods:
            @classmethod
            def _cleanup_instance(cls) -> None:
                if cls._instance is not None:
                    cls._instance.shutdown()
        """

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing. INTERNAL USE ONLY.

        This method clears all state and resets the singleton instance.
        It should only be used in test cleanup to ensure test isolation.
        """
        with cls._lock:
            try:
                if cls._instance is not None:
                    cls._cleanup_instance()
            finally:
                cls._instance = None
                cls._initialized = False
