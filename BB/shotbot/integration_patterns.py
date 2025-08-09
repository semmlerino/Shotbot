"""Integration patterns for seamless migration and backward compatibility.

This module provides patterns and utilities for integrating new architectural
improvements with existing code, ensuring backward compatibility and smooth migration.
"""

import functools
import logging
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from PySide6.QtCore import QObject, Signal

from progressive_file_scanner import AsyncProgressiveScanner, BatchResult
from qprocess_pool import QProcessPool
from qprocess_wrapper import ProcessConfig, QProcessWrapper
from type_system import CommandExecutor, ProcessResult, Result

# Set up logger for this module
logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================
# Backward Compatible Adapters
# ============================================================================


class SubprocessToQProcessAdapter(CommandExecutor):
    """Adapter to migrate from subprocess to QProcess seamlessly.

    This adapter provides a subprocess-like interface while using QProcess
    internally, allowing gradual migration of existing code.

    Example:
        >>> # Old code using subprocess
        >>> result = subprocess.run(["ls", "-la"], capture_output=True)
        >>> # New code with adapter
        >>> adapter = SubprocessToQProcessAdapter()
        >>> result = adapter.run(["ls", "-la"], capture_output=True)
        >>> # Same interface, but using QProcess internally
    """

    def __init__(self, use_pool: bool = False, max_processes: int = 4):
        """Initialize adapter.

        Args:
            use_pool: Use process pool for concurrent execution
            max_processes: Maximum concurrent processes if using pool
        """
        self.use_pool = use_pool
        self.pool = QProcessPool(max_processes) if use_pool else None

    def run(
        self,
        args: List[str],
        capture_output: bool = False,
        text: bool = True,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> ProcessResult:
        """Run command with subprocess.run-like interface.

        Args:
            args: Command and arguments
            capture_output: Capture stdout/stderr
            text: Return text instead of bytes
            timeout: Timeout in seconds
            cwd: Working directory
            env: Environment variables
            **kwargs: Additional arguments (ignored for compatibility)

        Returns:
            ProcessResult mimicking subprocess.CompletedProcess
        """
        if not args:
            raise ValueError("args must not be empty")

        command = args[0]
        arguments = args[1:] if len(args) > 1 else []

        # Create process configuration
        config = ProcessConfig(
            command=command,
            arguments=arguments,
            working_directory=cwd,
            environment=env or {},
            timeout_ms=int(timeout * 1000) if timeout else None,
        )

        # Execute using QProcess
        if self.use_pool and self.pool:
            return self._run_with_pool(config)
        else:
            return self._run_direct(config)

    def _run_direct(self, config: ProcessConfig) -> ProcessResult:
        """Run directly with QProcess wrapper."""
        wrapper = QProcessWrapper()

        # Collect output
        stdout_lines = []
        stderr_lines = []

        def collect_stdout(text: str, is_error: bool):
            if not is_error:
                stdout_lines.append(text)
            else:
                stderr_lines.append(text)

        wrapper.output_received.connect(collect_stdout)

        # Start process
        success = wrapper.start_process(config)
        if not success:
            return ProcessResult(
                command=config["command"],
                exit_code=-1,
                stdout="",
                stderr="Failed to start process",
                duration_ms=0.0,
                timed_out=False,
                error="Failed to start",
            )

        # Wait for completion
        timeout_ms = config.get("timeout_ms", 30000)
        if not wrapper.terminate(timeout_ms):
            return ProcessResult(
                command=config["command"],
                exit_code=-1,
                stdout="".join(stdout_lines),
                stderr="".join(stderr_lines),
                duration_ms=float(timeout_ms),
                timed_out=True,
                error="Process timed out",
            )

        # Get results
        output = wrapper.get_output()
        return ProcessResult(
            command=config["command"],
            exit_code=output["exit_code"],
            stdout=output["stdout"],
            stderr=output["stderr"],
            duration_ms=output["duration_ms"],
            timed_out=output["timed_out"],
            error=None,
        )

    def _run_with_pool(self, config: ProcessConfig) -> ProcessResult:
        """Run using process pool."""
        result_container = {"result": None}

        def handle_completion(info):
            result_container["result"] = ProcessResult(
                command=config["command"],
                exit_code=info.exit_code or -1,
                stdout="\n".join(info.stdout_lines),
                stderr="\n".join(info.stderr_lines),
                duration_ms=(info.end_time - info.start_time) * 1000
                if info.end_time
                else 0,
                timed_out=info.timed_out,
                error=str(info.error) if info.error else None,
            )

        # Submit to pool
        task_id = self.pool.submit(config, callback=handle_completion)
        if not task_id:
            return ProcessResult(
                command=config["command"],
                exit_code=-1,
                stdout="",
                stderr="Pool queue full",
                duration_ms=0.0,
                timed_out=False,
                error="Pool queue full",
            )

        # Wait for completion
        timeout_ms = config.get("timeout_ms", 30000)
        self.pool.wait_all(timeout_ms)

        return result_container["result"] or ProcessResult(
            command=config["command"],
            exit_code=-1,
            stdout="",
            stderr="No result received",
            duration_ms=0.0,
            timed_out=False,
            error="No result",
        )

    def execute(
        self, command: str, arguments: List[str], timeout: Optional[int] = None
    ) -> ProcessResult:
        """CommandExecutor protocol implementation."""
        return self.run([command] + arguments, capture_output=True, timeout=timeout)

    def execute_async(
        self,
        command: str,
        arguments: List[str],
        callback: Callable[[ProcessResult], None],
    ) -> None:
        """CommandExecutor protocol async implementation."""
        if not self.pool:
            raise RuntimeError("Async execution requires pool mode")

        config = ProcessConfig(command=command, arguments=arguments)

        def handle_completion(info):
            result = ProcessResult(
                command=command,
                exit_code=info.exit_code or -1,
                stdout="\n".join(info.stdout_lines),
                stderr="\n".join(info.stderr_lines),
                duration_ms=(info.end_time - info.start_time) * 1000
                if info.end_time
                else 0,
                timed_out=info.timed_out,
                error=str(info.error) if info.error else None,
            )
            callback(result)

        self.pool.submit(config, callback=handle_completion)


# ============================================================================
# Progressive Loading Integration
# ============================================================================


class LegacyScannerAdapter(QObject):
    """Adapter to use progressive scanner with legacy callback-based code.

    This adapter allows using the new progressive scanner with existing code
    that expects callback-based file discovery.

    Example:
        >>> # Old callback-based code
        >>> def on_file_found(path):
        ...     print(f"Found: {path}")
        >>> # Use adapter with new scanner
        >>> adapter = LegacyScannerAdapter()
        >>> adapter.file_found.connect(on_file_found)
        >>> adapter.scan_directory("/shows", extensions=[".3de"])
    """

    # Signals for compatibility
    file_found = Signal(str)  # path
    scan_progress = Signal(int, int)  # current, total
    scan_completed = Signal()
    scan_error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        """Initialize adapter."""
        super().__init__(parent)
        self._scanner: Optional[AsyncProgressiveScanner] = None
        self._total_found = 0

    def scan_directory(
        self,
        path: str,
        extensions: Optional[List[str]] = None,
        recursive: bool = True,
        exclude_patterns: Optional[List[str]] = None,
    ) -> None:
        """Start directory scan with legacy interface.

        Args:
            path: Directory to scan
            extensions: File extensions to find
            recursive: Scan recursively
            exclude_patterns: Patterns to exclude
        """
        from progressive_file_scanner import ExtensionFilter, PatternFilter

        # Create appropriate filter
        filter = None
        if extensions:
            filter = ExtensionFilter(extensions)
        elif exclude_patterns:
            filter = PatternFilter(["*"], exclude_patterns)

        # Create and configure scanner
        self._scanner = AsyncProgressiveScanner(
            root_path=path,
            filter=filter,
            batch_size=50,
            parent=self,
        )

        # Connect signals
        self._scanner.batch_ready.connect(self._handle_batch)
        self._scanner.scan_completed.connect(self._handle_completion)
        self._scanner.scan_error.connect(self._handle_error)
        self._scanner.progress_updated.connect(self._handle_progress)

        # Start scanning
        self._total_found = 0
        self._scanner.start()

    def _handle_batch(self, batch: BatchResult) -> None:
        """Handle batch of results."""
        for result in batch.results:
            if not result.error:
                self.file_found.emit(str(result.path))
                self._total_found += 1

    def _handle_progress(self, progress) -> None:
        """Handle progress update."""
        self.scan_progress.emit(progress.total_scanned, progress.total_found)

    def _handle_completion(self, total: int) -> None:
        """Handle scan completion."""
        self.scan_completed.emit()

    def _handle_error(self, error: str) -> None:
        """Handle scan error."""
        self.scan_error.emit(error)

    def cancel(self) -> None:
        """Cancel current scan."""
        if self._scanner:
            self._scanner.stop()


# ============================================================================
# Migration Decorators
# ============================================================================


def deprecated(reason: str, alternative: Optional[str] = None):
    """Decorator to mark deprecated functions.

    Args:
        reason: Deprecation reason
        alternative: Suggested alternative

    Example:
        >>> @deprecated("Use new_function instead", "new_function")
        >>> def old_function():
        ...     pass
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            msg = f"{func.__name__} is deprecated: {reason}"
            if alternative:
                msg += f". Use {alternative} instead."
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def compatibility_wrapper(
    old_interface: Type, new_implementation: Type
) -> Callable[[Type], Type]:
    """Decorator to create compatibility wrapper for classes.

    Args:
        old_interface: Old interface to support
        new_implementation: New implementation to use

    Example:
        >>> @compatibility_wrapper(OldScanner, ProgressiveScanner)
        >>> class Scanner:
        ...     pass
    """

    def decorator(cls: Type) -> Type:
        # Add methods from old interface
        for name, method in old_interface.__dict__.items():
            if not name.startswith("_") and callable(method):
                if not hasattr(cls, name):
                    # Create adapter method
                    def make_adapter(method_name):
                        def adapter(self, *args, **kwargs):
                            warnings.warn(
                                f"Using legacy method {method_name}",
                                DeprecationWarning,
                                stacklevel=2,
                            )
                            # Try to map to new implementation
                            if hasattr(self._new_impl, method_name):
                                return getattr(self._new_impl, method_name)(
                                    *args, **kwargs
                                )
                            else:
                                raise NotImplementedError(
                                    f"Legacy method {method_name} not implemented"
                                )

                        return adapter

                    setattr(cls, name, make_adapter(name))

        # Store new implementation reference
        original_init = cls.__init__

        def new_init(self, *args, **kwargs):
            self._new_impl = new_implementation(*args, **kwargs)
            original_init(self, *args, **kwargs)

        cls.__init__ = new_init

        return cls

    return decorator


# ============================================================================
# Performance Monitoring Integration
# ============================================================================


@dataclass
class PerformanceMetrics:
    """Performance metrics for operations."""

    operation: str
    duration_ms: float
    memory_before_mb: float
    memory_after_mb: float
    cpu_percent: float
    success: bool
    metadata: Dict[str, Any]


class PerformanceMonitor:
    """Monitor and log performance of operations.

    Example:
        >>> monitor = PerformanceMonitor()
        >>> with monitor.measure("file_scan"):
        ...     scan_files()
        >>> metrics = monitor.get_metrics("file_scan")
        >>> print(f"Scan took {metrics.duration_ms}ms")
    """

    def __init__(self):
        """Initialize monitor."""
        self._metrics: Dict[str, List[PerformanceMetrics]] = {}
        self._active_measurements: Dict[str, Any] = {}

    def measure(self, operation: str):
        """Context manager for measuring performance.

        Args:
            operation: Operation name

        Returns:
            Context manager
        """
        return self._MeasurementContext(self, operation)

    class _MeasurementContext:
        """Context manager for performance measurement."""

        def __init__(self, monitor: "PerformanceMonitor", operation: str):
            self.monitor = monitor
            self.operation = operation
            self.start_time = None
            self.start_memory = None

        def __enter__(self):
            import time

            import psutil

            self.start_time = time.time()
            process = psutil.Process()
            self.start_memory = process.memory_info().rss / (1024 * 1024)
            self.monitor._active_measurements[self.operation] = {
                "start_time": self.start_time,
                "start_memory": self.start_memory,
            }
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            import time

            import psutil

            end_time = time.time()
            process = psutil.Process()
            end_memory = process.memory_info().rss / (1024 * 1024)

            metrics = PerformanceMetrics(
                operation=self.operation,
                duration_ms=(end_time - self.start_time) * 1000,
                memory_before_mb=self.start_memory,
                memory_after_mb=end_memory,
                cpu_percent=process.cpu_percent(),
                success=exc_type is None,
                metadata={},
            )

            if self.operation not in self.monitor._metrics:
                self.monitor._metrics[self.operation] = []
            self.monitor._metrics[self.operation].append(metrics)

            del self.monitor._active_measurements[self.operation]

            # Log if performance is poor
            if metrics.duration_ms > 1000:
                logger.warning(
                    f"Slow operation {self.operation}: {metrics.duration_ms:.1f}ms"
                )
            if end_memory - self.start_memory > 100:
                logger.warning(
                    f"High memory usage in {self.operation}: "
                    f"+{end_memory - self.start_memory:.1f}MB"
                )

    def get_metrics(self, operation: str) -> Optional[PerformanceMetrics]:
        """Get latest metrics for operation.

        Args:
            operation: Operation name

        Returns:
            Latest metrics or None
        """
        if operation in self._metrics and self._metrics[operation]:
            return self._metrics[operation][-1]
        return None

    def get_average_metrics(self, operation: str) -> Optional[PerformanceMetrics]:
        """Get average metrics for operation.

        Args:
            operation: Operation name

        Returns:
            Average metrics or None
        """
        if operation not in self._metrics or not self._metrics[operation]:
            return None

        metrics_list = self._metrics[operation]
        avg_duration = sum(m.duration_ms for m in metrics_list) / len(metrics_list)
        avg_memory = sum(m.memory_after_mb for m in metrics_list) / len(metrics_list)
        avg_cpu = sum(m.cpu_percent for m in metrics_list) / len(metrics_list)

        return PerformanceMetrics(
            operation=operation,
            duration_ms=avg_duration,
            memory_before_mb=0,
            memory_after_mb=avg_memory,
            cpu_percent=avg_cpu,
            success=True,
            metadata={"sample_count": len(metrics_list)},
        )


# ============================================================================
# Error Handling Patterns
# ============================================================================


class ErrorHandler(ABC):
    """Abstract base class for error handlers."""

    @abstractmethod
    def handle(self, error: Exception, context: Dict[str, Any]) -> bool:
        """Handle an error.

        Args:
            error: The exception
            context: Error context

        Returns:
            True if error was handled
        """
        pass


class LoggingErrorHandler(ErrorHandler):
    """Error handler that logs errors."""

    def handle(self, error: Exception, context: Dict[str, Any]) -> bool:
        """Log the error."""
        logger.error(
            f"Error in {context.get('operation', 'unknown')}: {error}",
            exc_info=True,
            extra=context,
        )
        return True


class RetryErrorHandler(ErrorHandler):
    """Error handler that retries operations."""

    def __init__(self, max_retries: int = 3, backoff_factor: float = 2.0):
        """Initialize retry handler.

        Args:
            max_retries: Maximum retry attempts
            backoff_factor: Exponential backoff factor
        """
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def handle(self, error: Exception, context: Dict[str, Any]) -> bool:
        """Retry the operation."""
        import time

        retry_count = context.get("retry_count", 0)
        if retry_count >= self.max_retries:
            return False

        # Calculate backoff
        delay = self.backoff_factor**retry_count
        logger.info(f"Retrying after {delay}s (attempt {retry_count + 1})")
        time.sleep(delay)

        # Update context
        context["retry_count"] = retry_count + 1

        # Re-execute operation if provided
        if operation := context.get("operation_func"):
            try:
                result = operation()
                context["result"] = result
                return True
            except Exception as e:
                # Recursive retry
                return self.handle(e, context)

        return False


class ErrorHandlerChain:
    """Chain of error handlers."""

    def __init__(self):
        """Initialize handler chain."""
        self._handlers: List[ErrorHandler] = []

    def add_handler(self, handler: ErrorHandler) -> "ErrorHandlerChain":
        """Add handler to chain.

        Args:
            handler: Error handler

        Returns:
            Self for chaining
        """
        self._handlers.append(handler)
        return self

    def handle(
        self, error: Exception, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Handle error through chain.

        Args:
            error: The exception
            context: Error context

        Returns:
            True if any handler handled the error
        """
        context = context or {}

        for handler in self._handlers:
            try:
                if handler.handle(error, context):
                    return True
            except Exception as e:
                logger.error(f"Error in error handler: {e}")

        return False


# Global error handler instance
global_error_handler = ErrorHandlerChain()
global_error_handler.add_handler(LoggingErrorHandler())


def with_error_handling(
    operation_name: str, handlers: Optional[ErrorHandlerChain] = None
):
    """Decorator for automatic error handling.

    Args:
        operation_name: Name of the operation
        handlers: Custom error handler chain

    Example:
        >>> @with_error_handling("file_scan")
        >>> def scan_files():
        ...     # Code that might raise exceptions
        ...     pass
    """
    handlers = handlers or global_error_handler

    def decorator(func: Callable[..., T]) -> Callable[..., Result[T]]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Result[T]:
            context = {
                "operation": operation_name,
                "function": func.__name__,
                "args": args,
                "kwargs": kwargs,
            }

            try:
                result = func(*args, **kwargs)
                return Result.success(result)
            except Exception as e:
                if handlers.handle(e, context):
                    # Check if handler provided a result
                    if "result" in context:
                        return Result.success(context["result"])
                    else:
                        return Result.error(f"Handled error: {e}")
                else:
                    return Result.error(f"Unhandled error: {e}")

        return wrapper

    return decorator
