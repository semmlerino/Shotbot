"""Tests for ErrorHandlingMixin and ErrorAggregator.

Tests cover:
- safe_execute(): Error handling with default values, logging, reraise
- safe_file_operation(): File operations with error handling
- error_context(): Context manager for error blocks
- ErrorAggregator: Collection and reporting of multiple errors
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from error_handling_mixin import ErrorAggregator, ErrorHandlingMixin


# ==============================================================================
# Test Fixtures
# ==============================================================================


class ConcreteErrorHandler(ErrorHandlingMixin):
    """Concrete implementation of ErrorHandlingMixin for testing."""



@pytest.fixture
def handler() -> ConcreteErrorHandler:
    """Create a fresh error handler instance."""
    return ConcreteErrorHandler()


@pytest.fixture
def aggregator() -> ErrorAggregator:
    """Create a fresh error aggregator instance."""
    return ErrorAggregator()


# ==============================================================================
# safe_execute() Tests
# ==============================================================================


class TestSafeExecute:
    """Tests for safe_execute() wrapper."""

    def test_returns_result_on_success(self, handler: ConcreteErrorHandler) -> None:
        """Successful operation returns result."""

        def success_op() -> int:
            return 42

        result = handler.safe_execute(success_op)
        assert result == 42

    def test_returns_default_on_error(self, handler: ConcreteErrorHandler) -> None:
        """Failed operation returns default value."""

        def failing_op() -> str:
            raise ValueError("Test error")

        result = handler.safe_execute(failing_op, default="fallback")
        assert result == "fallback"

    def test_returns_none_when_no_default(self, handler: ConcreteErrorHandler) -> None:
        """Failed operation returns None when no default specified."""

        def failing_op() -> str:
            raise ValueError("Test error")

        result = handler.safe_execute(failing_op)
        assert result is None

    def test_passes_args_to_operation(self, handler: ConcreteErrorHandler) -> None:
        """Arguments are passed to the operation."""

        def add(a: int, b: int) -> int:
            return a + b

        result = handler.safe_execute(add, 3, 4)
        assert result == 7

    def test_passes_kwargs_to_operation(self, handler: ConcreteErrorHandler) -> None:
        """Keyword arguments are passed to the operation."""

        def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting}, {name}!"

        result = handler.safe_execute(greet, name="World", greeting="Hi")
        assert result == "Hi, World!"

    def test_logs_error_by_default(
        self,
        handler: ConcreteErrorHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Errors are logged by default."""

        def failing_op() -> None:
            raise ValueError("Test error message")

        with caplog.at_level(logging.ERROR):
            handler.safe_execute(failing_op)

        assert "failed" in caplog.text.lower()
        assert "Test error message" in caplog.text

    def test_log_error_false_suppresses_logging(
        self,
        handler: ConcreteErrorHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_error=False suppresses error logging."""

        def failing_op() -> None:
            raise ValueError("Should not be logged")

        with caplog.at_level(logging.ERROR):
            handler.safe_execute(failing_op, log_error=False)

        assert "Should not be logged" not in caplog.text

    def test_reraise_propagates_exception(
        self,
        handler: ConcreteErrorHandler,
    ) -> None:
        """reraise=True re-raises exception after logging."""

        def failing_op() -> None:
            raise ValueError("Reraise me")

        with pytest.raises(ValueError, match="Reraise me"):
            handler.safe_execute(failing_op, reraise=True)


# ==============================================================================
# safe_file_operation() Tests
# ==============================================================================


class TestSafeFileOperation:
    """Tests for safe_file_operation() wrapper."""

    def test_reads_file_successfully(
        self,
        handler: ConcreteErrorHandler,
        tmp_path: Path,
    ) -> None:
        """Successful file read returns content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        result = handler.safe_file_operation(Path.read_text, test_file)
        assert result == "Hello, World!"

    def test_returns_default_file_not_found(
        self,
        handler: ConcreteErrorHandler,
        tmp_path: Path,
    ) -> None:
        """FileNotFoundError returns default value."""
        nonexistent = tmp_path / "nonexistent.txt"

        result = handler.safe_file_operation(
            Path.read_text,
            nonexistent,
            default="default_content",
        )
        assert result == "default_content"

    def test_logs_file_not_found_error(
        self,
        handler: ConcreteErrorHandler,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """FileNotFoundError is logged."""
        nonexistent = tmp_path / "nonexistent.txt"

        with caplog.at_level(logging.ERROR):
            handler.safe_file_operation(Path.read_text, nonexistent)

        assert "not found" in caplog.text.lower()

    def test_accepts_string_path(
        self,
        handler: ConcreteErrorHandler,
        tmp_path: Path,
    ) -> None:
        """String paths are converted to Path objects."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Content")

        result = handler.safe_file_operation(Path.read_text, str(test_file))
        assert result == "Content"

    def test_create_parent_creates_directories(
        self,
        handler: ConcreteErrorHandler,
        tmp_path: Path,
    ) -> None:
        """create_parent=True creates parent directories."""
        nested_file = tmp_path / "a" / "b" / "c" / "test.txt"

        def write_op(path: Path) -> bool:
            path.write_text("Created!")
            return True

        result = handler.safe_file_operation(write_op, nested_file, create_parent=True)

        assert result is True
        assert nested_file.exists()
        assert nested_file.read_text() == "Created!"

    def test_log_error_false_suppresses_file_errors(
        self,
        handler: ConcreteErrorHandler,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_error=False suppresses file error logging."""
        nonexistent = tmp_path / "nonexistent.txt"

        with caplog.at_level(logging.ERROR):
            handler.safe_file_operation(
                Path.read_text,
                nonexistent,
                log_error=False,
            )

        assert "not found" not in caplog.text.lower()


# ==============================================================================
# error_context() Tests
# ==============================================================================


class TestErrorContext:
    """Tests for error_context() context manager."""

    def test_context_yields_dict_with_result_key(
        self,
        handler: ConcreteErrorHandler,
    ) -> None:
        """Context yields dictionary with result key."""
        with handler.error_context("test op") as ctx:
            assert "result" in ctx
            ctx["result"] = "success"

        assert ctx["result"] == "success"

    def test_context_captures_error(
        self,
        handler: ConcreteErrorHandler,
    ) -> None:
        """Exceptions are captured in context['error']."""
        with handler.error_context("failing op") as ctx:
            raise ValueError("Test error")

        assert ctx["error"] is not None
        assert isinstance(ctx["error"], ValueError)
        assert str(ctx["error"]) == "Test error"

    def test_context_sets_default_result_on_error(
        self,
        handler: ConcreteErrorHandler,
    ) -> None:
        """Context result is set to default_result on error."""
        with handler.error_context("op", default_result="fallback") as ctx:
            ctx["result"] = "should be overwritten"
            raise RuntimeError("Error!")

        assert ctx["result"] == "fallback"

    def test_context_reraise_propagates(
        self,
        handler: ConcreteErrorHandler,
    ) -> None:
        """reraise=True propagates exception."""
        with pytest.raises(ValueError, match="Reraise me"), handler.error_context(
            "op", reraise=True
        ):
            raise ValueError("Reraise me")

    def test_context_logs_at_specified_level(
        self,
        handler: ConcreteErrorHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Errors are logged at specified level."""
        with caplog.at_level(logging.WARNING), handler.error_context(
            "op", log_level=logging.WARNING
        ):
            raise ValueError("Warning level error")

        assert "warning" in caplog.text.lower()

    def test_context_no_error_key_on_success(
        self,
        handler: ConcreteErrorHandler,
    ) -> None:
        """Successful context has error=None."""
        with handler.error_context("success op") as ctx:
            pass  # No exception

        assert ctx["error"] is None


# ==============================================================================
# ErrorAggregator Tests
# ==============================================================================


class TestErrorAggregator:
    """Tests for ErrorAggregator class."""

    def test_add_error_collects_errors(self, aggregator: ErrorAggregator) -> None:
        """add_error() collects errors."""
        aggregator.add_error("context1", ValueError("Error 1"))
        aggregator.add_error("context2", RuntimeError("Error 2"))

        assert len(aggregator.errors) == 2

    def test_has_errors_returns_true_when_errors_exist(
        self,
        aggregator: ErrorAggregator,
    ) -> None:
        """has_errors() returns True when errors collected."""
        assert not aggregator.has_errors()

        aggregator.add_error("context", ValueError("Error"))

        assert aggregator.has_errors()

    def test_get_summary_formats_correctly(
        self,
        aggregator: ErrorAggregator,
    ) -> None:
        """get_summary() formats error list correctly."""
        aggregator.add_error("context1", ValueError("Error 1"))
        aggregator.add_error("context2", RuntimeError("Error 2"))

        summary = aggregator.get_summary()

        assert "2 errors occurred" in summary
        assert "context1" in summary
        assert "Error 1" in summary
        assert "context2" in summary
        assert "Error 2" in summary

    def test_get_summary_truncates_long_lists(
        self,
        aggregator: ErrorAggregator,
    ) -> None:
        """get_summary() truncates lists > 5 errors."""
        for i in range(10):
            aggregator.add_error(f"context{i}", ValueError(f"Error {i}"))

        summary = aggregator.get_summary()

        assert "10 errors occurred" in summary
        assert "... and 5 more" in summary

    def test_get_summary_no_errors(self, aggregator: ErrorAggregator) -> None:
        """get_summary() returns message when no errors."""
        summary = aggregator.get_summary()
        assert summary == "No errors"

    def test_log_all_logs_each_error(
        self,
        aggregator: ErrorAggregator,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_all() logs each error."""
        aggregator.add_error("context1", ValueError("Error 1"))
        aggregator.add_error("context2", RuntimeError("Error 2"))

        with caplog.at_level(logging.ERROR):
            aggregator.log_all(level=logging.ERROR)

        assert "context1" in caplog.text
        assert "Error 1" in caplog.text
        assert "context2" in caplog.text
        assert "Error 2" in caplog.text

    def test_clear_removes_all_errors(self, aggregator: ErrorAggregator) -> None:
        """clear() removes all collected errors."""
        aggregator.add_error("context", ValueError("Error"))
        assert aggregator.has_errors()

        aggregator.clear()

        assert not aggregator.has_errors()
        assert len(aggregator.errors) == 0

    def test_collecting_errors_context_manager(
        self,
        aggregator: ErrorAggregator,
    ) -> None:
        """collecting_errors() context manager works correctly."""
        with aggregator.collecting_errors("batch operation") as agg:
            agg.add_error("item1", ValueError("Failed"))
            agg.add_error("item2", RuntimeError("Also failed"))

        assert aggregator.has_errors()
        assert len(aggregator.errors) == 2

    def test_collecting_errors_clears_previous(
        self,
        aggregator: ErrorAggregator,
    ) -> None:
        """collecting_errors() clears previous errors at start."""
        aggregator.add_error("old", ValueError("Old error"))
        assert len(aggregator.errors) == 1

        with aggregator.collecting_errors("new operation") as agg:
            agg.add_error("new", ValueError("New error"))

        assert len(aggregator.errors) == 1
        assert aggregator.errors[0][0] == "new"

    def test_collecting_errors_logs_summary_on_exit(
        self,
        aggregator: ErrorAggregator,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """collecting_errors() logs summary on context exit."""
        with caplog.at_level(logging.ERROR), aggregator.collecting_errors(
            "batch processing"
        ) as agg:
            agg.add_error("item", ValueError("Error"))

        assert "batch processing" in caplog.text
        assert "1 errors occurred" in caplog.text
