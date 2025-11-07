#!/usr/bin/env python3
"""Test script for LoggingMixin functionality.

This script verifies that the LoggingMixin works correctly and demonstrates its usage.
"""

# Standard library imports
import logging
import sys
from pathlib import Path


# Add current directory to path to import logging_mixin
sys.path.insert(0, str(Path(__file__).parent))

# Local application imports
from logging_mixin import LoggingMixin, log_context, log_execution


# Configure logging to see output
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


class MockLoggingClass(LoggingMixin):
    """Test class using LoggingMixin."""

    def __init__(self, name: str) -> None:
        self.name = name

    def simple_method(self) -> None:
        """Simple method using logger."""
        self.logger.info(f"Simple method called for {self.name}")

    def context_method(self) -> None:
        """Method demonstrating context logging."""
        with self.logger.context(operation="test", user=self.name):
            self.logger.info("This message has context")
            self.logger.debug("Debug message with context")

    @log_execution
    def decorated_method(self, value: int) -> int:
        """Method with log_execution decorator."""
        # Standard library imports
        import time

        time.sleep(0.1)  # Simulate work
        return value * 2

    @log_execution(include_args=True, include_result=True, log_level=logging.DEBUG)
    def debug_decorated_method(self, x: int, y: int) -> int:
        """Method with detailed logging."""
        return x + y


@log_execution
def standalone_function(message: str) -> str:
    """Standalone function with logging decorator."""
    return f"Processed: {message}"


def test_logging_mixin() -> None:
    """Test LoggingMixin functionality."""
    print("=== Testing LoggingMixin ===")

    # Test basic logging
    test_obj = MockLoggingClass("test_user")
    test_obj.simple_method()

    # Test context logging
    test_obj.context_method()

    # Test decorated methods
    result = test_obj.decorated_method(5)
    print(f"Decorated method result: {result}")

    # Test debug decorated method
    debug_result = test_obj.debug_decorated_method(3, 7)
    print(f"Debug decorated method result: {debug_result}")

    # Test standalone function
    func_result = standalone_function("hello world")
    print(f"Standalone function result: {func_result}")

    # Test global context
    with log_context(shot="shot_001", operation="scan"):
        test_obj.logger.info("Message within global context")

    print("=== LoggingMixin test completed successfully ===")


if __name__ == "__main__":
    test_logging_mixin()
