"""Logging utilities to eliminate code duplication and standardize logging across the codebase.

This module provides:
- LoggingMixin: A mixin class that provides standardized logging setup
- ContextualLogger: Enhanced logger with structured context support
- @log_execution: Decorator for automatic method timing and tracing
- Thread-safe context management for structured logging

Usage:
    class MyClass(LoggingMixin):
        def my_method(self):
            self.logger.info("This will use proper logger hierarchy")

    @log_execution
    def my_function():
        # Automatically logged with timing
        pass
"""

from __future__ import annotations

# Standard library imports
import functools
import logging
import threading
import time
from contextlib import contextmanager
from types import TracebackType
from typing import TYPE_CHECKING, TypeVar, cast

# Third-party imports
from typing_extensions import ParamSpec


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable, Generator, Mapping

# Type aliases matching logging module
_SysExcInfoType = (
    tuple[type[BaseException], BaseException, TracebackType | None]
    | tuple[None, None, None]
)
_ExcInfoType = None | bool | _SysExcInfoType | BaseException

# Type variables for generic decorator
P = ParamSpec("P")
T = TypeVar("T")

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


class ContextualLogger:
    """Enhanced logger wrapper that supports structured context."""

    def __init__(self, logger: logging.Logger) -> None:  # pyright: ignore[reportMissingSuperCall]
        self._logger: logging.Logger = logger

    def _format_message(self, msg: str) -> str:
        """Format message with current context if available."""
        context: dict[str, object] | None = getattr(_context_storage, "context", None)
        if context:
            context_str = " | ".join(f"{k}={v}" for k, v in context.items())
            return f"[{context_str}] {msg}"
        return msg

    def debug(
        self,
        msg: str,
        *args: object,
        exc_info: _ExcInfoType = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        """Log debug message with context."""
        self._logger.debug(
            self._format_message(msg),
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel,
            extra=extra,
        )

    def info(
        self,
        msg: str,
        *args: object,
        exc_info: _ExcInfoType = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        """Log info message with context."""
        self._logger.info(
            self._format_message(msg),
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel,
            extra=extra,
        )

    def warning(
        self,
        msg: str,
        *args: object,
        exc_info: _ExcInfoType = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        """Log warning message with context."""
        self._logger.warning(
            self._format_message(msg),
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel,
            extra=extra,
        )

    def error(
        self,
        msg: str,
        *args: object,
        exc_info: _ExcInfoType = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        """Log error message with context."""
        self._logger.error(
            self._format_message(msg),
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel,
            extra=extra,
        )

    def critical(
        self,
        msg: str,
        *args: object,
        exc_info: _ExcInfoType = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        """Log critical message with context."""
        self._logger.critical(
            self._format_message(msg),
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel,
            extra=extra,
        )

    def exception(
        self,
        msg: str,
        *args: object,
        exc_info: _ExcInfoType = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        """Log exception message with context."""
        self._logger.exception(
            self._format_message(msg),
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel,
            extra=extra,
        )

    def isEnabledFor(self, level: int) -> bool:
        """Check if the logger is enabled for the specified level.

        Args:
            level: The logging level to check (e.g., logging.DEBUG)

        Returns:
            True if the logger will process messages at this level

        """
        return self._logger.isEnabledFor(level)

    def setLevel(self, level: int) -> None:
        """Set the logging level for this logger.

        Args:
            level: The logging level to set (e.g., logging.DEBUG, logging.INFO)

        """
        self._logger.setLevel(level)

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


class LoggingMixin:
    """Mixin class providing standardized logging setup.

    This mixin eliminates the need for manual logger setup in each class.
    Instead of:
        logger = logging.getLogger(__name__)

    Simply inherit from LoggingMixin:
        class MyClass(LoggingMixin):
            def my_method(self):
                self.logger.info("Message")

    The logger will automatically use the proper hierarchy:
    module_name.ClassName
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize LoggingMixin and continue MRO chain.

        This ensures proper multiple inheritance with Qt classes.
        """
        super().__init__(*args, **kwargs)

    @property
    def logger(self) -> ContextualLogger:
        """Get the logger for this class with contextual support.

        Returns:
            ContextualLogger instance with proper naming hierarchy

        """
        # Create logger name using module + class name for proper hierarchy
        logger_name = f"{self.__class__.__module__}.{self.__class__.__name__}"
        base_logger = logging.getLogger(logger_name)

        # Cache the contextual logger on the instance to avoid recreating
        cache_attr = "_contextual_logger"
        if not hasattr(self, cache_attr):
            setattr(self, cache_attr, ContextualLogger(base_logger))

        return cast("ContextualLogger", getattr(self, cache_attr))


def log_execution(
    func: Callable[P, T] | None = None,
    *,
    include_args: bool = False,
    include_result: bool = False,
    log_level: int = logging.INFO,
) -> Callable[[Callable[P, T]], Callable[P, T]] | Callable[P, T]:
    """Decorator to automatically log method/function execution with timing.

    Args:
        func: Function to decorate (when used without parentheses)
        include_args: Whether to log function arguments (default: False for privacy)
        include_result: Whether to log return value (default: False for privacy)
        log_level: Logging level to use (default: INFO)

    Usage:
        @log_execution
        def my_method(self):
            # Automatically logged with timing
            pass

        @log_execution(include_args=True, log_level=logging.DEBUG)
        def debug_method(self, arg1, arg2):
            # Logged with arguments at DEBUG level
            pass

    """

    def decorator(inner_func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(inner_func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Get logger - try to use instance logger if available, otherwise module logger
            logger: ContextualLogger
            if args and hasattr(args[0], "logger"):
                # Type narrowing: we know args[0] has logger attribute
                instance_logger = getattr(args[0], "logger", None)
                if hasattr(instance_logger, "info"):
                    logger = cast("ContextualLogger", instance_logger)
                else:
                    logger = ContextualLogger(logging.getLogger(inner_func.__module__))
            else:
                logger = ContextualLogger(logging.getLogger(inner_func.__module__))

            # Create execution context
            func_name = f"{inner_func.__qualname__}"
            start_time = time.time()

            # Log function start
            if log_level <= logging.DEBUG and include_args:
                # Safely format args (avoid logging sensitive data)
                safe_args: list[str] = []
                for arg in args[1:] if args and hasattr(args[0], "logger") else args:
                    if isinstance(arg, str | int | float | bool):
                        safe_args.append(repr(arg))
                    else:
                        safe_args.append(f"<{type(arg).__name__}>")

                safe_kwargs = {
                    k: repr(v)
                    if isinstance(v, str | int | float | bool)
                    else f"<{type(v).__name__}>"
                    for k, v in kwargs.items()
                }

                if log_level == logging.DEBUG:
                    logger.debug(
                        f"Starting {func_name}({', '.join(safe_args)}, {safe_kwargs})"
                    )
                else:
                    logger.info(f"Starting {func_name}")
            elif log_level == logging.DEBUG:
                logger.debug(f"Starting {func_name}")
            elif log_level == logging.INFO:
                logger.info(f"Starting {func_name}")

            try:
                # Execute function
                result = inner_func(*args, **kwargs)

                # Calculate execution time
                execution_time = time.time() - start_time

                # Log success with timing
                time_str = f"completed in {execution_time:.3f}s"
                if include_result and result is not None:
                    if isinstance(result, str | int | float | bool):
                        if log_level == logging.DEBUG:
                            logger.debug(f"{func_name} {time_str} -> {result!r}")
                        else:
                            logger.info(f"{func_name} {time_str}")
                    elif log_level == logging.DEBUG:
                        logger.debug(
                            f"{func_name} {time_str} -> <{type(result).__name__}>"
                        )
                    else:
                        logger.info(f"{func_name} {time_str}")
                elif log_level == logging.DEBUG:
                    logger.debug(f"{func_name} {time_str}")
                elif log_level == logging.INFO:
                    logger.info(f"{func_name} {time_str}")

                return result

            except Exception:
                # Calculate execution time for error case
                execution_time = time.time() - start_time

                # Log error with timing
                logger.exception(f"{func_name} failed after {execution_time:.3f}s")
                raise

        return wrapper

    # Handle both @log_execution and @log_execution() cases
    if func is None:
        # Called with parentheses: @log_execution()
        return decorator
    # Called without parentheses: @log_execution
    return decorator(func)


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
