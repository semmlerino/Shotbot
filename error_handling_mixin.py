"""Error handling utilities to eliminate code duplication for exception patterns.

This module provides standardized error handling patterns that are repeated
throughout the codebase, reducing ~1,000 lines of duplicate exception handling.

Usage:
    class MyClass(ErrorHandlingMixin):
        def my_method(self):
            # Simple error handling with default return
            result = self.safe_execute(self.risky_operation, default=[])

            # File operation with path validation
            data = self.safe_file_operation(Path.read_text, path, default="")

            # Context manager for error blocks
            with self.error_context("database update"):
                self.update_database()
"""

from __future__ import annotations

# Standard library imports
import logging
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

# Third-party imports
from typing_extensions import ParamSpec

# Local application imports
from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable, Generator

# Type variables for generic functions
P = ParamSpec("P")
T = TypeVar("T")


class ErrorHandlingMixin(LoggingMixin):
    """Mixin providing standardized error handling patterns.

    This mixin consolidates common error handling patterns found throughout
    the codebase, reducing duplicate try/except blocks and standardizing
    error logging and recovery.
    """

    def safe_execute(
        self,
        operation: Callable[..., T],
        *args: object,
        default: T | None = None,
        log_error: bool = True,
        reraise: bool = False,
        **kwargs: object,
    ) -> T | None:
        """Execute an operation with standard error handling.

        This replaces the common pattern:
        try:
            result = operation()
        except Exception as e:
            logger.error(f"Operation failed: {e}")
            return None

        Args:
            operation: Callable to execute
            *args: Positional arguments for the operation
            default: Default value to return on error
            log_error: Whether to log errors
            reraise: Whether to re-raise the exception after logging
            **kwargs: Keyword arguments for the operation

        Returns:
            Result of operation or default value on error
        """
        # Extract wrapper parameters from kwargs
        _default = cast("T | None", kwargs.pop("_default", default))
        _log_error = bool(kwargs.pop("_log_error", log_error))
        _reraise = bool(kwargs.pop("_reraise", reraise))

        try:
            return operation(*args, **kwargs)
        except Exception as e:
            if _log_error:
                # Get operation name for logging
                op_name = getattr(operation, "__name__", str(operation))
                self.logger.error(f"{op_name} failed: {e}")

                # Log traceback at debug level
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f"Traceback:\n{traceback.format_exc()}")

            if _reraise:
                raise

            return _default

    def safe_file_operation(
        self,
        path_operation: Callable[[Path], T],
        path: Path | str,
        default: T | None = None,
        log_error: bool = True,
        create_parent: bool = False,
    ) -> T | None:
        """Execute a file operation with path validation and error handling.

        This replaces patterns like:
        try:
            if not path.exists():
                logger.error(f"Path not found: {path}")
                return None
            return path.read_text()
        except Exception as e:
            logger.error(f"Failed to read {path}: {e}")
            return None

        Args:
            path_operation: Operation to perform on the path (e.g., Path.read_text)
            path: File or directory path
            default: Default value to return on error
            log_error: Whether to log errors
            create_parent: Whether to create parent directories for write operations

        Returns:
            Result of operation or default value on error
        """
        try:
            # Convert to Path if string
            path_obj = Path(path) if isinstance(path, str) else path

            # Create parent directories if requested (for write operations)
            if create_parent and not path_obj.parent.exists():
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Created parent directory: {path_obj.parent}")

            # Execute the operation
            return path_operation(path_obj)

        except FileNotFoundError as e:
            if log_error:
                self.logger.error(f"File not found: {path} - {e}")
            return default

        except PermissionError as e:
            if log_error:
                self.logger.error(f"Permission denied: {path} - {e}")
            return default

        except OSError as e:
            if log_error:
                self.logger.error(f"OS error for {path}: {e}")
            return default

        except Exception as e:
            if log_error:
                self.logger.error(f"File operation failed for {path}: {e}")
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f"Traceback:\n{traceback.format_exc()}")
            return default

    @contextmanager
    def error_context(
        self,
        operation_name: str,
        reraise: bool = False,
        log_level: int = logging.ERROR,
        default_result: object = None,
    ) -> Generator[dict[str, object], None, None]:
        """Context manager for error handling blocks.

        This replaces patterns like:
        try:
            # complex operation
            pass
        except Exception as e:
            logger.error(f"Operation failed: {e}")

        Usage:
            with self.error_context("database update") as ctx:
                self.update_database()
                ctx['result'] = "success"

        Args:
            operation_name: Name of the operation for logging
            reraise: Whether to re-raise exceptions after logging
            log_level: Logging level for errors
            default_result: Default result to set in context on error

        Yields:
            Context dictionary for storing operation results
        """
        context: dict[str, object] = {"result": default_result, "error": None}

        try:
            self.logger.debug(f"Starting {operation_name}")
            yield context
            self.logger.debug(f"Completed {operation_name}")

        except Exception as e:
            context["error"] = e
            context["result"] = default_result

            # Log based on specified level
            if log_level == logging.ERROR:
                self.logger.error(f"{operation_name} failed: {e}")
            elif log_level == logging.WARNING:
                self.logger.warning(f"{operation_name} warning: {e}")
            elif log_level == logging.INFO:
                self.logger.info(f"{operation_name} info: {e}")
            else:
                self.logger.debug(f"{operation_name} debug: {e}")

            # Include traceback for error level
            if log_level >= logging.ERROR and self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Traceback:\n{traceback.format_exc()}")

            if reraise:
                raise

    def handle_timeout(
        self,
        operation: Callable[..., T],
        _timeout_seconds: float,
        *args: object,
        default: T | None = None,
        **kwargs: object,
    ) -> T | None:
        """Execute operation with timeout handling.

        Note: This is a placeholder for timeout handling.
        Actual implementation would require threading or async support.

        Args:
            operation: Operation to execute
            timeout_seconds: Timeout in seconds
            *args: Positional arguments
            default: Default return value on timeout
            **kwargs: Keyword arguments

        Returns:
            Operation result or default on timeout
        """
        # For now, just execute normally with error handling
        # Full timeout implementation would require threading
        return self.safe_execute(
            operation, *args, default=default, log_error=True, reraise=False, **kwargs
        )

    def retry_on_error(
        self,
        operation: Callable[..., T],
        *args: object,
        max_retries: int = 3,
        delay_seconds: float = 1.0,
        backoff_factor: float = 2.0,
        **kwargs: object,
    ) -> T | None:
        """Retry an operation on failure with exponential backoff.

        Args:
            operation: Operation to execute
            *args: Positional arguments
            max_retries: Maximum number of retry attempts
            delay_seconds: Initial delay between retries
            backoff_factor: Multiplier for delay after each retry
            **kwargs: Keyword arguments

        Returns:
            Operation result or None if all retries failed
        """
        # Standard library imports
        import time

        current_delay = delay_seconds

        for attempt in range(max_retries + 1):
            try:
                result = operation(*args, **kwargs)
                if attempt > 0:
                    self.logger.info(
                        f"{operation.__name__} succeeded after {attempt} retries"
                    )
                return result

            except Exception as e:
                if attempt < max_retries:
                    self.logger.warning(
                        f"{operation.__name__} attempt {attempt + 1} failed: {e}. "
                         f"Retrying in {current_delay:.1f}s..."
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff_factor
                else:
                    self.logger.error(
                        f"{operation.__name__} failed after {max_retries + 1} attempts: {e}"
                    )

        return None

    def validate_and_execute(
        self,
        operation: Callable[..., T],
        *args: object,
        validators: list[Callable[[], bool]] | None = None,
        validation_error: str = "Validation failed",
        **kwargs: object,
    ) -> T | None:
        """Execute operation only if all validators pass.

        Args:
            operation: Operation to execute
            *args: Positional arguments
            validators: List of validation functions that return True if valid
            validation_error: Error message if validation fails
            **kwargs: Keyword arguments

        Returns:
            Operation result or None if validation failed
        """
        if validators:
            for validator in validators:
                try:
                    if not validator():
                        self.logger.error(
                            f"{validation_error}: {validator.__name__} failed"
                        )
                        return None
                except Exception as e:
                    self.logger.error(
                        f"Validator {validator.__name__} raised error: {e}"
                    )
                    return None

        return self.safe_execute(
            operation, *args, default=None, log_error=True, reraise=False, **kwargs
        )


class ErrorAggregator:
    """Collect multiple errors for batch reporting.

    Useful for operations that should continue despite errors,
    collecting all errors for reporting at the end.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        """Initialize error aggregator.

        Args:
            logger: Logger instance (uses module logger if not provided)
        """
        super().__init__()
        self.errors: list[tuple[str, Exception]] = []
        self.logger = logger or logging.getLogger(__name__)

    def add_error(self, context: str, error: Exception) -> None:
        """Add an error to the collection.

        Args:
            context: Context where error occurred
            error: The exception
        """
        self.errors.append((context, error))
        if hasattr(self.logger, "debug"):
            self.logger.debug(f"Error in {context}: {error}")

    def has_errors(self) -> bool:
        """Check if any errors were collected."""
        return len(self.errors) > 0

    def get_summary(self) -> str:
        """Get summary of all collected errors."""
        if not self.errors:
            return "No errors"

        summary_parts = [f"{len(self.errors)} errors occurred:"]
        for context, error in self.errors[:5]:  # Show first 5
            summary_parts.append(f"  - {context}: {error}")

        if len(self.errors) > 5:
            summary_parts.append(f"  ... and {len(self.errors) - 5} more")

        return "\n".join(summary_parts)

    def log_all(self, level: int = logging.ERROR) -> None:
        """Log all collected errors.

        Args:
            level: Logging level to use
        """
        if not self.errors:
            return

        for context, error in self.errors:
            if level == logging.ERROR and hasattr(self.logger, "error"):
                self.logger.error(f"{context}: {error}")
            elif level == logging.WARNING and hasattr(self.logger, "warning"):
                self.logger.warning(f"{context}: {error}")
            elif hasattr(self.logger, "info"):
                self.logger.info(f"{context}: {error}")

    def clear(self) -> None:
        """Clear all collected errors."""
        self.errors.clear()

    @contextmanager
    def collecting_errors(
        self, operation_name: str
    ) -> Generator[ErrorAggregator, None, None]:
        """Context manager for collecting errors during an operation.

        Usage:
            aggregator = ErrorAggregator(self.logger)
            with aggregator.collecting_errors("batch processing") as agg:
                for item in items:
                    try:
                        process(item)
                    except Exception as e:
                        agg.add_error(f"Item {item}", e)

        Args:
            operation_name: Name of the operation

        Yields:
            Self for adding errors
        """
        self.clear()

        try:
            yield self
        finally:
            if self.has_errors() and hasattr(self.logger, "error"):
                self.logger.error(f"{operation_name}: {self.get_summary()}")
