# Qt Resource Cleanup Fixes

This document provides code fixes for the violations found in the Qt Resource Cleanup Audit.

## Fix 1: tests/test_subprocess_no_deadlock.py (Line 148)

### Current Code (VIOLATION)

```python
def test_launcher_worker_no_deadlock() -> bool:
    """Test that the actual LauncherWorker doesn't deadlock with verbose apps."""

    # Third-party imports
    from PySide6.QtCore import (
        QCoreApplication,
    )

    # Local application imports
    from launcher.worker import (
        LauncherWorker,
    )
    from tests.helpers.synchronization import (
        process_qt_events,
    )

    app = QCoreApplication.instance() or QCoreApplication([])

    # Create a command that generates lots of output
    if sys.platform == "win32":
        command = "dir /s C:\\Windows\\System32"
    else:
        command = "find /usr -type f 2>&1 | head -10000"

    worker = LauncherWorker(
        launcher_id="test_verbose", command=command, working_dir=None
    )

    finished = False

    def on_finished(launcher_id, success, return_code) -> None:
        nonlocal finished
        finished = True
        print(f"LauncherWorker finished: success={success}, code={return_code}")

    worker.command_finished.connect(on_finished)

    # Start worker  <-- VIOLATION: NO TRY/FINALLY
    worker.start()

    # Wait up to 10 seconds
    start = time.time()
    timeout_sec = 10
    while not finished and time.time() - start < timeout_sec:
        process_qt_events(app, 10)
        # Use wait_for_condition instead of sleep to avoid blocking
        wait_for_condition(lambda: finished, timeout_ms=100, poll_interval_ms=50)

    # Check result
    if finished:
        print(f"✓ LauncherWorker completed in {time.time() - start:.2f}s")
        return True
    print("✗ LauncherWorker deadlocked or timed out!")
    worker.request_stop()
    worker.wait(1000)
    return False
```

### Fixed Code

```python
def test_launcher_worker_no_deadlock() -> bool:
    """Test that the actual LauncherWorker doesn't deadlock with verbose apps."""

    # Third-party imports
    from PySide6.QtCore import (
        QCoreApplication,
    )

    # Local application imports
    from launcher.worker import (
        LauncherWorker,
    )
    from tests.helpers.synchronization import (
        process_qt_events,
    )

    app = QCoreApplication.instance() or QCoreApplication([])

    # Create a command that generates lots of output
    if sys.platform == "win32":
        command = "dir /s C:\\Windows\\System32"
    else:
        command = "find /usr -type f 2>&1 | head -10000"

    worker = LauncherWorker(
        launcher_id="test_verbose", command=command, working_dir=None
    )

    finished = False

    def on_finished(launcher_id, success, return_code) -> None:
        nonlocal finished
        finished = True
        print(f"LauncherWorker finished: success={success}, code={return_code}")

    worker.command_finished.connect(on_finished)

    # FIXED: Wrapped in try/finally for guaranteed cleanup
    try:
        # Start worker
        worker.start()

        # Wait up to 10 seconds
        start = time.time()
        timeout_sec = 10
        while not finished and time.time() - start < timeout_sec:
            process_qt_events(app, 10)
            # Use wait_for_condition instead of sleep to avoid blocking
            wait_for_condition(lambda: finished, timeout_ms=100, poll_interval_ms=50)

        # Check result
        if finished:
            print(f"✓ LauncherWorker completed in {time.time() - start:.2f}s")
            return True
        print("✗ LauncherWorker deadlocked or timed out!")
        return False
    finally:
        # GUARANTEED cleanup (regardless of success/timeout/exception)
        if worker.isRunning():
            worker.request_stop()
        worker.wait(1000)
```

### Changes
1. Wrapped entire worker lifecycle in try/finally
2. Moved cleanup to finally block (guaranteed execution)
3. Cleanup always runs, regardless of success/timeout/exception
4. Return statements properly positioned before finally block

---

## Fix 2: tests/test_utils/qt_thread_test_helpers.py (Line 188)

### Current Code (VIOLATION)

```python
def measure_worker_lifecycle(
    self,
    worker_factory,
    work_duration=0.01,
    expected_final_state=None,
    connect_signals=True,
) -> dict:
    """Measure worker lifecycle with expected duration."""
    results = {
        "success": False,
        "started": False,
        "finished": False,
        "final_state": None,
        "error_messages": [],
    }

    # ... signal setup ...

    # Start worker  <-- VIOLATION: BEFORE try block
    worker.start()

    # Wait for complete lifecycle
    timeout_ms = max(5000, int(work_duration * 1000 * 10))

    try:
        # Wait for thread to finish
        with self.qtbot.waitSignal(worker.finished, timeout=timeout_ms):
            pass

        # ... rest of method ...
    finally:
        # Cleanup is minimal/missing
        pass
```

### Fixed Code

```python
def measure_worker_lifecycle(
    self,
    worker_factory,
    work_duration=0.01,
    expected_final_state=None,
    connect_signals=True,
) -> dict:
    """Measure worker lifecycle with expected duration."""
    results = {
        "success": False,
        "started": False,
        "finished": False,
        "final_state": None,
        "error_messages": [],
    }

    # ... signal setup ...

    # FIXED: worker.start() moved INSIDE try block
    timeout_ms = max(5000, int(work_duration * 1000 * 10))

    try:
        # Start worker (now inside try)
        worker.start()

        # Wait for thread to finish
        with self.qtbot.waitSignal(worker.finished, timeout=timeout_ms):
            pass

        # Allow time for final state transitions
        self.qtbot.wait(200)

        # ... rest of method ...

    finally:
        # GUARANTEED cleanup: disconnect signals, stop thread, cleanup
        # Disconnect all signals to prevent late firing
        if hasattr(worker, "worker_started") and connect_signals:
            try:
                worker.worker_started.disconnect()
            except (RuntimeError, TypeError):
                pass

        if hasattr(worker, "worker_finished") and connect_signals:
            try:
                worker.worker_finished.disconnect()
            except (RuntimeError, TypeError):
                pass

        if hasattr(worker, "worker_error") and connect_signals:
            try:
                worker.worker_error.disconnect()
            except (RuntimeError, TypeError):
                pass

        # Stop the worker if it's still running
        if worker.isRunning():
            worker.stop()
            worker.wait(5000)
```

### Changes
1. Moved worker.start() inside try block (line 188 → after try:)
2. Added comprehensive cleanup in finally block
3. Disconnects all signal handlers to prevent late signal delivery
4. Ensures worker.stop() and worker.wait() always execute
5. Graceful error handling for signal disconnection

---

## Fix 3: tests/helpers/synchronization.py (Line 151)

### Current Code (DOCUMENTATION ISSUE)

```python
@staticmethod
@contextlib.contextmanager
def wait_for_threads_to_start(max_wait_ms: int = 5000):
    """Context manager to ensure threads have started.

    Example:
        # Instead of: thread.start(); time.sleep(0.1)
        # Use:
        with wait_for_threads_to_start():
            thread.start()
    """
    initial_count = threading.active_count()

    yield

    # Wait for thread count to increase
    SynchronizationHelpers.wait_for_condition(
        lambda: threading.active_count() > initial_count,
        timeout_ms=max_wait_ms,
    )
```

### Fixed Code (Option A: Clarify that cleanup is caller's responsibility)

```python
@staticmethod
@contextlib.contextmanager
def wait_for_threads_to_start(max_wait_ms: int = 5000):
    """Context manager to ensure threads have started.

    IMPORTANT: This helper only waits for threads to start.
    Cleanup (join(), stop(), etc.) is the caller's responsibility.

    Example - Correct usage with cleanup:
        # Wrap both start AND cleanup
        thread = threading.Thread(target=worker_func)
        try:
            with wait_for_threads_to_start():
                thread.start()
            # Test code...
        finally:
            thread.join(timeout=5.0)  # Cleanup is caller's responsibility

    Example - For Qt workers:
        from launcher.worker import LauncherWorker
        worker = LauncherWorker(...)
        try:
            with wait_for_threads_to_start():
                worker.start()
            # Test code...
        finally:
            if worker.isRunning():
                worker.stop()
                worker.wait(5000)
    """
    initial_count = threading.active_count()

    yield

    # Wait for thread count to increase
    SynchronizationHelpers.wait_for_condition(
        lambda: threading.active_count() > initial_count,
        timeout_ms=max_wait_ms,
    )
```

### Alternative Fix (Option B: Create a context manager that handles cleanup)

```python
@staticmethod
@contextlib.contextmanager
def wait_for_and_cleanup_threads(
    thread_object=None,
    max_wait_ms: int = 5000,
    cleanup_timeout_ms: int = 5000,
):
    """Context manager that waits for thread start AND handles cleanup.

    This ensures proper thread lifecycle: start → run → cleanup.

    Args:
        thread_object: Qt worker or threading.Thread to manage
        max_wait_ms: Timeout for thread to start
        cleanup_timeout_ms: Timeout for thread cleanup

    Example - Qt worker:
        worker = LauncherWorker(...)
        with wait_for_and_cleanup_threads(worker):
            worker.start()  # Will auto-cleanup in finally

    Example - Regular thread:
        thread = threading.Thread(target=my_func)
        with wait_for_and_cleanup_threads(thread):
            thread.start()  # Will auto-join in finally
    """
    initial_count = threading.active_count()

    try:
        # Wait for thread to start
        SynchronizationHelpers.wait_for_condition(
            lambda: threading.active_count() > initial_count,
            timeout_ms=max_wait_ms,
        )
        yield
    finally:
        # GUARANTEED cleanup
        if thread_object is not None:
            if hasattr(thread_object, "isRunning"):
                # Qt worker
                if thread_object.isRunning():
                    thread_object.stop()
                thread_object.wait(cleanup_timeout_ms)
            elif hasattr(thread_object, "is_alive"):
                # threading.Thread
                if thread_object.is_alive():
                    thread_object.join(timeout=cleanup_timeout_ms / 1000.0)
```

### Changes
1. Option A: Clarify documentation that cleanup is caller's responsibility
2. Option B: Create new helper that handles cleanup automatically
3. Both options prevent users from following incorrect cleanup pattern

---

## Implementation Priority

### Priority 1 (Critical)
- [ ] Fix: tests/test_subprocess_no_deadlock.py:148
- [ ] Test: Verify with `pytest tests/test_subprocess_no_deadlock.py -v`

### Priority 2 (High)
- [ ] Fix: tests/test_utils/qt_thread_test_helpers.py:188
- [ ] Test: Verify all tests that use measure_worker_lifecycle() still pass

### Priority 3 (Low)
- [ ] Fix: tests/helpers/synchronization.py:151
- [ ] Update documentation/docstring

---

## Verification Steps

After applying fixes:

```bash
# Run affected tests
pytest tests/test_subprocess_no_deadlock.py -v
pytest tests/test_utils/qt_thread_test_helpers.py -v

# Run full suite serially
pytest tests/ --tb=short

# Run full suite with parallelism
pytest tests/ -n 2 --tb=short
```

---

## Testing with Parallel Execution

Verify fixes work correctly with parallel test workers:

```bash
# Recommended: 2 workers
pytest tests/ -n 2 --tb=short -v

# Full parallelism
pytest tests/ -n auto --tb=short -v
```

These violations are most likely to appear during parallel test execution.
