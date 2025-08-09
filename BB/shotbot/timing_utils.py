"""Simple timing utilities for performance testing."""

import functools
import logging
import time

logger = logging.getLogger(__name__)


def timed_operation(operation_name: str, log_threshold_ms: int = 100):
    """Decorator to time function execution.

    Args:
        operation_name: Name of the operation for logging
        log_threshold_ms: Only log if execution time exceeds this threshold
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                end_time = time.perf_counter()
                duration_ms = (end_time - start_time) * 1000
                if duration_ms > log_threshold_ms:
                    logger.debug(f"{operation_name} took {duration_ms:.1f}ms")

        return wrapper

    return decorator
