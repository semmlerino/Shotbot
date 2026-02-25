# Pytest Timeout Best Practices for Threading Tests

## Overview

This document provides comprehensive best practices for using pytest-timeout with threading tests, particularly for Qt/PySide6 applications. These practices are essential for preventing test suite hangs, detecting deadlocks, and ensuring reliable test execution.

## Core Purpose

**pytest-timeout is designed to catch:**
- Deadlocked tests
- Hanging tests  
- Excessively long test durations
- Infinite loops in test code

**It is NOT designed for:**
- Precise timing measurements
- Performance regression testing
- Exact execution time guarantees

## Timeout Methods

### 1. Thread Method (Recommended for Portability)
**How it works:** For each test, starts a timer thread that terminates the whole process after the specified timeout.

**Advantages:**
- Most portable and reliable method
- Works on all platforms
- Provides stack traces of all threads when timeout occurs (excellent for debugging deadlocks)
- Default fallback when signal method unavailable

**Disadvantages:**
- Higher overhead per test
- Terminates entire test process (no graceful completion)
- May not work well with C extensions that release the GIL

**When to use:**
- Default choice for maximum compatibility
- Testing multi-threaded code
- When debugging deadlocks (provides thread stack traces)

### 2. Signal Method (Unix/Linux Only)
**How it works:** Schedules a SIGALRM signal when test starts, cancels when test finishes.

**Advantages:**
- Lower overhead than thread method
- Allows test suite to continue after timeout
- More precise timing
- Graceful test interruption via pytest.fail()

**Disadvantages:**
- Only works on Unix/Linux systems
- Can interfere with code that uses SIGALRM
- Not available on Windows

**When to use:**
- Unix/Linux environments only
- When test suite continuation after timeout is important
- When lower overhead is critical

## Configuration

### pytest.ini Configuration
```ini
[tool:pytest]
# Default timeout in seconds (5 minutes)
timeout = 300

# Timeout method: 'thread' or 'signal'
timeout_method = thread

# Only time the test function, exclude fixture setup/teardown
timeout_func_only = false

# Disable timeouts during debugging
timeout_disable = false
```

### Command Line Options
```bash
# Set timeout for specific test run
pytest --timeout=60 --timeout-method=thread

# Disable timeout (useful for debugging)
pytest --timeout=0

# Apply timeout to function body only
pytest --timeout=60 --timeout-func-only
```

### Per-Test Configuration
```python
import pytest

# Set timeout for specific test
@pytest.mark.timeout(30)
def test_quick_operation():
    pass

# Use different timeout method
@pytest.mark.timeout(60, method='signal')
def test_with_signal_method():
    pass

# Exclude fixture time from timeout
@pytest.mark.timeout(30, func_only=True)
def test_excluding_fixtures(slow_fixture):
    pass
```

## Qt/PySide6 Threading Test Best Practices

### 1. Use qtbot for Signal Waiting
```python
def test_thread_completion(qtbot):
    worker = MyQThreadWorker()
    
    # Wait for thread to finish with timeout
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()
    
    # Assertion after thread completes
    assert worker.result is not None
```

### 2. Test Multiple Signals
```python
def test_multiple_signals(qtbot):
    worker = MyWorker()
    
    # Wait for multiple signals
    with qtbot.waitSignals([worker.started, worker.finished], timeout=5000):
        worker.start()
```

### 3. Use QSignalSpy for Signal Introspection
```python
from PySide6.QtTest import QSignalSpy

def test_signal_emissions(qtbot):
    worker = MyWorker()
    spy = QSignalSpy(worker.progress_updated)
    
    worker.start()
    qtbot.wait(1000)  # Wait for work to progress
    
    # Check signal was emitted
    assert spy.count() > 0
    # Access signal arguments
    if spy.count() > 0:
        first_emission = spy.at(0)
        progress_value = first_emission[0]
        assert 0 <= progress_value <= 100
```

### 4. Process Events for Thread Synchronization
```python
from PySide6.QtWidgets import QApplication

def test_thread_with_events(qtbot):
    worker = MyWorker()
    worker.start()
    
    # Process events to ensure signal delivery
    QApplication.processEvents()
    qtbot.wait(100)
    
    # Now check state
    assert worker.get_state() == WorkerState.RUNNING
```

## Deadlock Prevention Strategies

### 1. Lock Ordering
Always acquire locks in a consistent order across all code:
```python
# CORRECT: Always acquire locks in same order
with lock_a:
    with lock_b:
        # Do work

# WRONG: Inconsistent lock ordering causes deadlocks
# Thread 1:
with lock_a:
    with lock_b:
        pass
        
# Thread 2:
with lock_b:  # Different order!
    with lock_a:
        pass
```

### 2. Use Timeout-Based Locking
```python
import threading

lock = threading.Lock()

# Use timeout to prevent indefinite blocking
if lock.acquire(timeout=5):
    try:
        # Do work
        pass
    finally:
        lock.release()
else:
    # Handle timeout
    raise TimeoutError("Could not acquire lock")
```

### 3. Use Context Managers
```python
from contextlib import contextmanager
import threading

@contextmanager
def acquire_locks(*locks):
    """Acquire multiple locks safely."""
    acquired = []
    try:
        for lock in locks:
            if not lock.acquire(timeout=5):
                raise TimeoutError(f"Could not acquire lock {lock}")
            acquired.append(lock)
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()
```

### 4. Use Reentrant Locks
```python
import threading

# Reentrant lock allows same thread to acquire multiple times
lock = threading.RLock()

def outer_function():
    with lock:
        inner_function()  # Safe even though inner also acquires lock

def inner_function():
    with lock:
        # Do work
        pass
```

## Common Issues and Solutions

### Issue 1: Test Hangs During Thread Cleanup
**Symptom:** Test timeout during worker thread cleanup

**Solution:**
```python
def test_worker_cleanup(qtbot):
    worker = MyWorker()
    worker.start()
    
    # Request stop and wait with timeout
    worker.request_stop()
    assert worker.wait(5000), "Worker did not stop in time"
    
    # Ensure cleanup
    worker.deleteLater()
    qtbot.wait(100)  # Allow deletion to process
```

### Issue 2: Timeout During Fixture Setup
**Symptom:** Test times out before actual test code runs

**Solution:**
```python
# Use func_only to exclude fixture time
@pytest.mark.timeout(30, func_only=True)
def test_with_slow_fixture(slow_database_fixture):
    # Only this code is timed, not fixture setup
    assert slow_database_fixture.query("SELECT 1")
```

### Issue 3: Cascading Timer Issues
**Symptom:** Multiple timers creating cascade effect

**Solution:**
```python
class Manager:
    def __init__(self):
        self._cleanup_scheduled = False
        self._cleanup_timer = QTimer()
        self._cleanup_timer.setSingleShot(True)
        
    def schedule_cleanup(self):
        # Prevent multiple timers
        if self._cleanup_scheduled:
            return
            
        self._cleanup_scheduled = True
        self._cleanup_timer.timeout.connect(self._do_cleanup)
        self._cleanup_timer.start(1000)
        
    def _do_cleanup(self):
        self._cleanup_scheduled = False
        # Perform cleanup
```

### Issue 4: Signal Not Emitted in Time
**Symptom:** qtbot.waitSignal times out even though operation completes

**Solution:**
```python
def test_delayed_signal(qtbot):
    worker = MyWorker()
    
    # Increase timeout for slow operations
    with qtbot.waitSignal(worker.finished, timeout=10000) as blocker:
        worker.start()
        # Process events to help signal delivery
        QApplication.processEvents()
```

## Performance Optimization

### 1. Set Appropriate Timeout Values
```python
# Short timeout for fast operations
@pytest.mark.timeout(5)
def test_quick_calculation():
    assert 2 + 2 == 4

# Longer timeout for I/O operations
@pytest.mark.timeout(60)
def test_network_request():
    response = fetch_from_api()
    assert response.status_code == 200

# Very long timeout for integration tests
@pytest.mark.timeout(300)
def test_full_workflow():
    run_complex_integration_test()
```

### 2. Use Thread Pools Efficiently
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def test_concurrent_operations():
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        
        for i in range(10):
            future = executor.submit(worker_function, i)
            futures.append(future)
        
        # Wait with timeout
        for future in as_completed(futures, timeout=30):
            result = future.result()
            assert result is not None
```

### 3. Batch Test Operations
```python
def test_batch_operations(qtbot):
    """Test multiple operations efficiently."""
    workers = [MyWorker(i) for i in range(5)]
    
    # Start all workers
    for worker in workers:
        worker.start()
    
    # Wait for all to complete
    for worker in workers:
        with qtbot.waitSignal(worker.finished, timeout=5000):
            pass
    
    # Check all results
    for worker in workers:
        assert worker.result is not None
```

## Debugging Timeout Issues

### 1. Enable Debug Output
```bash
# Run with verbose output to see what's happening
pytest -vv --timeout=30 --timeout-method=thread

# Disable timeout for debugging
pytest --timeout=0 --pdb
```

### 2. Add Diagnostic Logging
```python
import logging
import time

def test_with_diagnostics():
    start_time = time.time()
    logging.info(f"Test started at {start_time}")
    
    # Your test code
    result = long_running_operation()
    
    elapsed = time.time() - start_time
    logging.info(f"Test took {elapsed:.2f} seconds")
    
    assert result is not None
```

### 3. Use Thread Dump on Timeout
When using thread method, pytest-timeout automatically dumps all thread stacks on timeout. This is invaluable for debugging deadlocks:

```
===== pytest-timeout thread dump =====
Thread 0x00007f8b8c8b8700 (most recent call first):
  File "test_file.py", line 45, in worker_function
    lock_b.acquire()  # Waiting for lock_b
  File "test_file.py", line 40, in test_deadlock
    with lock_a:  # Holding lock_a
```

## Platform-Specific Considerations

### Windows
- Signal method not available; always uses thread method
- May need longer timeouts due to process creation overhead
- Consider using `pytest-xdist` for parallel execution

### Linux/macOS
- Both signal and thread methods available
- Signal method generally preferred for lower overhead
- Can use `SIGALRM` for more precise timeout control

### CI/CD Environments
- Set longer timeouts than local development (2-3x)
- Consider system load and resource constraints
- Use thread method for maximum compatibility

## Best Practices Summary

1. **Always set a default timeout** in pytest.ini (300-600 seconds)
2. **Use thread method** for maximum compatibility
3. **Set specific timeouts** for tests with known duration
4. **Use qtbot.waitSignal** for Qt thread synchronization
5. **Implement proper cleanup** in teardown/finally blocks
6. **Use context managers** for lock acquisition
7. **Add diagnostic logging** for timeout debugging
8. **Process Qt events** when testing signals
9. **Use func_only** when fixtures are slow
10. **Disable timeouts** when debugging with --pdb

## Common Anti-Patterns to Avoid

1. **Don't use sleep() for synchronization** - Use proper signal waiting
2. **Don't use infinite loops** without exit conditions
3. **Don't acquire locks in inconsistent order**
4. **Don't ignore cleanup** in test teardown
5. **Don't set timeouts too short** - Allow for system variability
6. **Don't forget to process events** in Qt tests
7. **Don't use blocking waits** without timeouts
8. **Don't create cascading timers** without checks

## References

- [pytest-timeout Documentation](https://github.com/pytest-dev/pytest-timeout)
- [pytest-qt Documentation](https://pytest-qt.readthedocs.io/)
- [Qt Threading Documentation](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html)
- [Python Threading Best Practices](https://docs.python.org/3/library/threading.html)

## Conclusion

Proper timeout configuration and threading test practices are essential for maintaining a reliable test suite. By following these guidelines, you can prevent test hangs, detect deadlocks early, and ensure your threading tests run efficiently and reliably across all platforms.