"""Process Pool Manager for optimized subprocess handling.

This module provides centralized process management with:
- Parallel execution via ThreadPoolExecutor (the "pool" in the name)
- Command caching to avoid redundant subprocess calls
- Centralized workspace command execution

Note: Each command spawns a fresh bash subprocess. The "pool" refers to
the thread pool for parallel execution, not session reuse. Caching provides
the primary performance benefit by avoiding repeated shell invocations.
"""

# See: docs/THREADING_ARCHITECTURE.md

from __future__ import annotations

# Standard library imports
import concurrent.futures
import gc
import selectors
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Literal, final

from PySide6.QtCore import (
    QCoreApplication,
    QMutex,
    QMutexLocker,
    QObject,
    QThread,
)

# Third-party imports
from cachetools import TTLCache

# Local application imports
from logging_mixin import LoggingMixin, get_module_logger
from timeout_config import TimeoutConfig


# Module-level logger
logger = get_module_logger(__name__)


@dataclass
class CancellableResult:
    """Result from cancellable subprocess execution.

    Attributes:
        returncode: Process return code (None if cancelled/timeout)
        stdout: Captured standard output
        stderr: Captured standard error
        status: "ok", "cancelled", or "timeout"

    """

    returncode: int | None
    stdout: str
    stderr: str
    status: Literal["ok", "cancelled", "timeout"]


@final
class CancellableSubprocess:
    """Wrapper for subprocess.Popen with cancellation support.

    This class provides a cancellable alternative to subprocess.run() by using
    Popen with a polling loop and optional cancel_flag callback.

    Based on the proven pattern from filesystem_scanner._run_subprocess_with_streaming_read()
    """

    def __init__(
        self,
        cmd: list[str],
        *,
        shell: bool = False,
        text: bool = True,
    ) -> None:
        """Initialize cancellable subprocess.

        Args:
            cmd: Command to execute as list of arguments
            shell: If True, run through shell (not recommended)
            text: If True, use text mode for stdout/stderr

        """
        self._cmd = cmd
        self._shell = shell
        self._text = text
        self._process: subprocess.Popen[str] | None = None
        self._cancel_requested = threading.Event()

    def run(
        self,
        timeout: float = 120.0,
        poll_interval: float = 0.1,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> CancellableResult:
        """Run subprocess with cancellation support.

        Args:
            timeout: Maximum time to wait for command (seconds)
            poll_interval: How often to check for cancellation/timeout (seconds)
            cancel_flag: Optional callback that returns True if execution should be cancelled

        Returns:
            CancellableResult with returncode, stdout, stderr, and status

        """
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        self._process = subprocess.Popen(
            self._cmd,
            shell=self._shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=self._text,
        )

        # Register stdout and stderr for non-blocking reads
        sel = selectors.DefaultSelector()
        try:
            if self._process.stdout:
                _ = sel.register(self._process.stdout, selectors.EVENT_READ, "stdout")
            if self._process.stderr:
                _ = sel.register(self._process.stderr, selectors.EVENT_READ, "stderr")

            start_time = time.monotonic()

            while self._process.poll() is None:
                # Check cancellation (both internal flag and external callback)
                if self._cancel_requested.is_set() or (cancel_flag and cancel_flag()):
                    logger.info("Subprocess cancelled")
                    self._process.kill()
                    _ = self._process.wait()
                    return CancellableResult(None, "", "", "cancelled")

                # Check timeout using wall clock to avoid drift from processing overhead
                if time.monotonic() - start_time >= timeout:
                    logger.error(f"Subprocess timed out after {timeout} seconds")
                    self._process.kill()
                    _ = self._process.wait()
                    return CancellableResult(None, "", "", "timeout")

                # Read available data (selector handles timeout for responsiveness)
                ready = sel.select(timeout=poll_interval)
                for key, _ in ready:
                    # Read available data in chunks to avoid blocking
                    data = key.fileobj.read(8192)  # type: ignore[union-attr]
                    if isinstance(data, str) and data:
                        if key.data == "stdout":  # pyright: ignore[reportAny]
                            stdout_chunks.append(data)
                        else:
                            stderr_chunks.append(data)

            # Process exited - drain any remaining buffered data
            for key, _ in sel.select(timeout=0):
                remaining = key.fileobj.read()  # type: ignore[union-attr]
                if isinstance(remaining, str) and remaining:
                    if key.data == "stdout":  # pyright: ignore[reportAny]
                        stdout_chunks.append(remaining)
                    else:
                        stderr_chunks.append(remaining)

            return CancellableResult(
                self._process.returncode,
                "".join(stdout_chunks),
                "".join(stderr_chunks),
                "ok",
            )

        finally:
            sel.close()

    def cancel(self) -> None:
        """Request cancellation of the running subprocess.

        If the subprocess is running, this will trigger a kill on the next poll cycle.
        """
        self._cancel_requested.set()
        if self._process and self._process.poll() is None:
            self._process.kill()


@final
class ProcessPoolManager(LoggingMixin, QObject):
    """Centralized process management with thread pooling and caching.

    This singleton class manages all subprocess operations for the application,
    providing:
    - Parallel execution via ThreadPoolExecutor
    - Command caching to avoid redundant subprocess calls
    - Centralized workspace command handling

    The "pool" in ProcessPoolManager refers to the thread pool for parallelism,
    not bash session pooling. Each command spawns a fresh subprocess, with
    caching providing the primary performance optimization.

    Singleton Pattern Notes:
        This class uses a custom singleton pattern instead of SingletonMixin because:
        1. It inherits from QObject for Qt signals (LoggingMixin + QObject MRO)
        2. Uses threading.Lock (not RLock) - simpler for this use case
        3. Calls __init__ manually inside __new__ under lock to prevent race
           conditions where another thread gets an uninitialized instance

        CAUTION: The Lock (not RLock) prevents re-entrant access. If cleanup code
        needs to access ProcessPoolManager.get_instance() while already holding
        the lock, it could deadlock. Current code avoids this pattern.

        The reset() method is called by SingletonRegistry during test cleanup
        to ensure proper test isolation.
    """

    _cleanup_order: ClassVar[int] = 30
    _singleton_description: ClassVar[str] = "Subprocess execution and caching"

    # Singleton instance
    _instance: ClassVar[ProcessPoolManager | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()  # Use Python's threading.Lock for singleton access
    _initialized: ClassVar[bool] = False  # Class-level flag to track singleton initialization

    def __new__(cls, max_workers: int = 4) -> ProcessPoolManager:
        """Ensure singleton pattern with proper thread safety.

        CRITICAL: Holds lock across both __new__ and __init__ to prevent race where
        another thread gets uninitialized instance between __new__ and __init__.

        Note: Parameters are intentionally unused in __new__ (singleton returns existing
        instance) but must match __init__ signature for type checker consistency.
        """
        # Fast path - no lock if already initialized
        if cls._instance is None:
            with cls._lock:
                # Double-check inside lock to prevent race condition
                if cls._instance is None:
                    # Create instance but DON'T set cls._instance yet
                    instance = super().__new__(cls)
                    # Initialize BEFORE making visible (call __init__ manually)
                    instance.__init__(max_workers)
                    # Now safe to expose - fully initialized
                    cls._instance = instance
                    # Set flag so __init__ doesn't run again
                    cls._initialized = True
        return cls._instance

    def __init__(self, max_workers: int = 4) -> None:
        """Initialize process pool manager.

        Args:
            max_workers: Maximum concurrent workers

        Note: __new__ calls this manually under lock, so we don't need lock here.
        If called directly (e.g., by Python after __new__), check if already initialized.

        """
        # Check if already initialized (called by __new__ or Python)
        if hasattr(self, "_init_done") and self._init_done:
            return

        super().__init__()

        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
        )
        self._cache: TTLCache[str, str] = TTLCache(maxsize=500, ttl=30)  # pyright: ignore[reportInvalidTypeArguments] - vendored cachetools lacks type stubs
        self._cache_lock = QMutex()
        # Instance-level mutex and shutdown flag for thread-safe shutdown
        self._mutex = QMutex()
        self._shutdown_requested = False

        # Mark initialization as complete
        self._init_done = True

        self.logger.debug(f"ProcessPoolManager initialized ({max_workers} workers)")

    @classmethod
    def get_instance(cls) -> ProcessPoolManager:
        """Get singleton instance.

        Thread safety is handled by __new__ method.

        Returns:
            ProcessPoolManager singleton

        """
        # Standard singleton pattern
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _check_not_shutdown(self) -> None:
        """Raise RuntimeError if shutdown has been requested."""
        with QMutexLocker(self._mutex):
            if self._shutdown_requested:
                msg = "ProcessPoolManager has been shut down"
                raise RuntimeError(msg)

    def execute_workspace_command(
        self,
        command: str,
        cache_ttl: int = 30,
        timeout: int | None = None,
        use_login_shell: bool = False,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> str:
        """Execute workspace command with caching and cancellation support.

        Args:
            command: Command to execute
            cache_ttl: Cache time-to-live in seconds
            timeout: Command execution timeout in seconds (default: TimeoutConfig.SUBPROCESS_SEC)
            use_login_shell: If True, use bash -l (login) instead of bash -i (interactive)
                           Login shell sources workspace functions without blocking on terminal
            cancel_flag: Optional callback that returns True if execution should be cancelled.
                        The subprocess will be killed on the next poll cycle if this returns True.

        Returns:
            Command output

        Raises:
            RuntimeError: If called from the main thread (UI thread), after shutdown, or if cancelled
            subprocess.CalledProcessError: If command returns non-zero exit code
            subprocess.TimeoutExpired: If command exceeds timeout

        """
        # Check shutdown flag before executing
        # Without this check, commands submitted after shutdown() cause RuntimeError
        self._check_not_shutdown()

        # CRITICAL: Prevent UI freezes - this method blocks for up to 120 seconds
        # Must only be called from background threads
        current_thread = QThread.currentThread()
        app_instance = QCoreApplication.instance()
        if app_instance and current_thread == app_instance.thread():
            msg = (
                "execute_workspace_command() cannot be called on the main (UI) thread!\n"
                f"This method blocks for up to {TimeoutConfig.SUBPROCESS_SEC}s "
                "and will freeze the UI.\n"
                "Use AsyncShotLoader or background workers instead.\n"
                f"Command attempted: {command[:100]}..."
            )
            raise RuntimeError(
                msg
            )

        if timeout is None:
            timeout = int(TimeoutConfig.SUBPROCESS_SEC)

        # Check cache first
        with QMutexLocker(self._cache_lock):
            _raw = self._cache.get(command)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] - vendored cachetools
        if isinstance(_raw, str):
            return _raw

        # Execute command using subprocess
        try:
            # Shell mode selection for ws command execution:
            #
            # -i (interactive, default): Required because 'ws' is a shell function defined
            #    in .bashrc, which is only sourced in interactive shells. Interactive mode
            #    may emit banner/MOTD noise, but the parser in base_shot_model.py handles
            #    this by skipping non-matching lines (logged at DEBUG level).
            #
            # -l (login): Used for cache warming (use_login_shell=True). Avoids terminal
            #    blocking during shell init. Works if .bash_profile sources .bashrc.
            #
            # Note: Production launcher uses -ilc (combined) for reliability. Here we use
            # separate flags because the parser tolerates banner noise, and -l is faster
            # for cache warming where terminal interaction isn't needed.
            shell_flag = "-l" if use_login_shell else "-i"
            cmd = ["/bin/bash", shell_flag, "-c", command]

            # Use CancellableSubprocess for cancellation support
            cancellable = CancellableSubprocess(cmd)
            proc_result = cancellable.run(
                timeout=float(timeout),
                cancel_flag=cancel_flag,
            )

            # Handle cancellation
            if proc_result.status == "cancelled":
                msg = f"Command cancelled: {command[:50]}..."
                raise RuntimeError(msg)

            # Handle timeout
            if proc_result.status == "timeout":
                raise subprocess.TimeoutExpired(cmd, timeout)

            # Handle non-zero exit code
            if proc_result.returncode != 0:
                raise subprocess.CalledProcessError(
                    proc_result.returncode or 1,
                    cmd,
                    proc_result.stdout,
                    proc_result.stderr,
                )

            result = proc_result.stdout

            # Cache result
            with QMutexLocker(self._cache_lock):
                self._cache[command] = result

            return result

        except Exception:
            self.logger.exception(f"Command execution failed ({command[:80]!r})")
            raise


    def invalidate_cache(self, pattern: str | None = None) -> None:
        """Invalidate command cache.

        Args:
            pattern: pattern to match (invalidates all if None)

        """
        with QMutexLocker(self._cache_lock):
            if pattern is None:
                self._cache.clear()
                logger.info("Cleared entire command cache")
            else:
                keys: list[str] = [k for k in self._cache if pattern in k]  # pyright: ignore[reportUnknownVariableType] - vendored cachetools
                for k in keys:
                    del self._cache[k]
                logger.info(
                    f"Invalidated {len(keys)} cache entries matching '{pattern}'",
                )

    def shutdown(self, timeout: float = 5.0) -> None:
        """Shutdown the process pool manager with enhanced error handling.

        Args:
            timeout: Maximum time to wait for executor shutdown in seconds

        Note:
            Uses a timeout wrapper around executor.shutdown() to prevent
            indefinite blocking if tasks are stuck. If the graceful shutdown
            takes longer than timeout, a forced shutdown is triggered.

        """
        with QMutexLocker(self._mutex):
            if self._shutdown_requested:
                self.logger.debug(
                    "ProcessPoolManager shutdown already requested, skipping"
                )
                return
            self._shutdown_requested = True

        self.logger.debug(f"Starting ProcessPoolManager shutdown (timeout={timeout}s)")

        # Stage 1: Graceful executor shutdown with timeout wrapper
        # ThreadPoolExecutor.shutdown() doesn't support timeout parameter,
        # so we wrap it in a background thread with our own timeout
        shutdown_successful = False
        shutdown_complete = threading.Event()

        def _do_shutdown() -> None:
            """Perform executor shutdown in background thread."""
            try:
                # Python 3.11+ guaranteed to support cancel_futures parameter
                self._executor.shutdown(wait=True, cancel_futures=True)
            except Exception as e:  # noqa: BLE001
                self.logger.debug(f"Executor shutdown exception in thread: {e}")
            finally:
                shutdown_complete.set()

        try:
            self.logger.debug("Initiating ThreadPoolExecutor shutdown")
            shutdown_thread = threading.Thread(
                target=_do_shutdown, daemon=True, name="ExecutorShutdown"
            )
            shutdown_thread.start()

            # Wait for shutdown with timeout
            if shutdown_complete.wait(timeout=timeout):
                shutdown_successful = True
                self.logger.debug("ThreadPoolExecutor shutdown completed within timeout")
            else:
                # Timeout reached - force shutdown
                # Note: Python threads cannot be forcibly terminated. shutdown(wait=False)
                # abandons running threads but they will continue until completion.
                # cancel_futures=True cancels pending (not-yet-started) tasks.
                self.logger.warning(
                    f"Executor shutdown timed out after {timeout}s, forcing non-blocking shutdown"
                )
                try:
                    self._executor.shutdown(wait=False, cancel_futures=True)

                    # Log any threads still running after timeout (helps diagnose leaks)
                    if hasattr(self._executor, "_threads"):
                        alive_threads = [
                            t for t in self._executor._threads if t.is_alive()
                        ]
                        if alive_threads:
                            thread_names = [t.name for t in alive_threads]
                            self.logger.warning(
                                f"Abandoned {len(alive_threads)} threads after timeout: {thread_names}"
                            )
                except Exception as e:  # noqa: BLE001
                    self.logger.debug(f"Force shutdown exception: {e}")

        except Exception:
            self.logger.exception("Error during ProcessPoolManager executor shutdown")

        # Stage 2: Clean up any remaining resources
        try:
            cache_size = len(self._cache)
            self._cache.clear()
            if cache_size > 0:
                self.logger.debug(f"Cleared {cache_size} command cache entries")

        except Exception:  # noqa: BLE001
            self.logger.warning("Error during resource cleanup", exc_info=True)

        # Stage 3: Force garbage collection to clean up circular references
        try:
            _ = gc.collect()
        except Exception as e:  # noqa: BLE001
            self.logger.debug(f"Error during garbage collection: {e}")

        status = "successful" if shutdown_successful else "with timeout"
        self.logger.info(f"ProcessPoolManager shutdown complete ({status})")

    def __del__(self) -> None:
        """Ensure cleanup on destruction.

        CRITICAL BUG FIX #36: Ensure ThreadPoolExecutor is shut down even if
        shutdown() not called explicitly. ThreadPoolExecutor has threads that
        need explicit shutdown - Python's garbage collector won't clean them up.

        This provides defensive cleanup but explicit shutdown() is preferred.
        """
        try:
            if getattr(self, "_init_done", False) and not self._shutdown_requested:
                self.logger.debug("ProcessPoolManager.__del__ called - triggering shutdown")
                self.shutdown(timeout=2.0)
        except Exception:  # noqa: BLE001
            # Ignore errors in destructor - we're being destroyed anyway
            pass

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing. INTERNAL USE ONLY.

        This method shuts down the process pool and resets the singleton instance.
        It should only be used in test cleanup to ensure test isolation.

        IMPORTANT: Calls deleteLater() on the QObject to ensure proper Qt cleanup.
        Without this, Qt event processing may access stale QObject references,
        causing segfaults in pytestqt's _process_events.
        """
        instance = cls._instance
        if instance is not None:
            try:
                instance.shutdown(timeout=2.0)
            except Exception:  # noqa: BLE001
                logger.warning("Error during reset shutdown", exc_info=True)

            # Schedule Qt object deletion - CRITICAL for preventing segfaults
            # in pytestqt event processing after test teardown.
            # Check for deleteLater to handle mock objects in tests that don't
            # inherit from QObject.
            if hasattr(instance, "deleteLater") and callable(instance.deleteLater):
                try:
                    instance.deleteLater()
                except (RuntimeError, AttributeError):
                    # Already deleted or in invalid state
                    pass

        # Reset singleton state
        with cls._lock:
            cls._instance = None
            cls._initialized = False

        logger.debug("ProcessPoolManager reset for testing")
