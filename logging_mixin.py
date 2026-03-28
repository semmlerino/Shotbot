"""Logging utilities for standardized logging across the codebase.

This module provides:
- ContextualLogger: Enhanced logger with structured context support
- Thread-safe context management for structured logging
- get_module_logger: Convenience function for module-level loggers
- log_context: Context manager for temporary logging context
"""

from __future__ import annotations

# Standard library imports
import logging
import threading
from collections.abc import MutableMapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

# Third-party imports
from typing_extensions import override


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Generator

# Thread-local storage for logging context
_context_storage = threading.local()


def _manage_log_context(**kwargs: str) -> Generator[None, None, None]:
    """Shared implementation for context managers.

    Handles thread-local context stack manipulation with guaranteed cleanup.

    Args:
        **kwargs: Context key-value pairs

    Yields:
        None (context manager protocol)

    """
    # Get current context or create empty dict
    current_context = getattr(_context_storage, "context", {})

    # Create new context by merging
    new_context = {**current_context, **kwargs}

    # Store old for restoration
    old_context = getattr(_context_storage, "context", None)

    try:
        _context_storage.context = new_context
        yield
    finally:
        # Restore previous context
        if old_context is not None:
            _context_storage.context = old_context
        # Remove context if there was none before
        elif hasattr(_context_storage, "context"):
            delattr(_context_storage, "context")


class ContextualLogger(logging.LoggerAdapter):  # type: ignore[type-arg]
    """Enhanced logger with structured context support."""

    def __init__(self, logger: logging.Logger) -> None:
        super().__init__(logger, {})  # pyright: ignore[reportUnknownMemberType]

    @override
    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        """Prepend thread-local context to log messages."""
        context: dict[str, object] | None = getattr(_context_storage, "context", None)
        if context:
            context_str = " | ".join(f"{k}={v}" for k, v in context.items())
            return f"[{context_str}] {msg}", kwargs
        return msg, kwargs

    @contextmanager
    def context(self, **kwargs: str) -> Generator[None, None, None]:
        """Add structured context to all log messages within this block.

        Args:
            **kwargs: Context key-value pairs (e.g., shot="shot_001", operation="scan")

        Usage:
            with self.logger.context(shot="shot_001", operation="scan"):
                self.logger.info("Processing shot")  # Will include context

        """
        yield from _manage_log_context(**kwargs)


# Convenience function for setting up module-level logging
def get_module_logger(module_name: str) -> ContextualLogger:
    """Get a contextual logger for a module.

    This is useful for module-level functions that don't belong to a class.

    Args:
        module_name: Usually pass __name__

    Returns:
        ContextualLogger instance

    Usage:
        logger = get_module_logger(__name__)
        logger.info("Module-level message")

    """
    base_logger = logging.getLogger(module_name)
    return ContextualLogger(base_logger)


# Convenience context manager for temporary logging context
@contextmanager
def log_context(**kwargs: str) -> Generator[None, None, None]:
    """Global context manager for adding structured context to log messages.

    Args:
        **kwargs: Context key-value pairs

    Usage:
        with log_context(shot="shot_001", operation="scan"):
            logger.info("Processing")  # Will include context

    """
    yield from _manage_log_context(**kwargs)
