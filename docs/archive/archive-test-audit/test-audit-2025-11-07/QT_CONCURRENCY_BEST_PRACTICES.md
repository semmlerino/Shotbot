# Qt Concurrency Best Practices for Testing

## Critical Issues and Solutions

### 1. Event Loop Processing Anti-Patterns

#### ❌ WRONG: Using QApplication.processEvents()
```python
# This is dangerous - can cause event reordering and race conditions
QApplication.processEvents()
```

#### ✅ CORRECT: Use qtbot methods
```python
# Safe wait for event processing
qtbot.wait(50)  # Brief delay for event loop

# Wait for specific conditions
qtbot.waitUntil(lambda: widget.isVisible(), timeout=1000)

# Wait for signal emission
with qtbot.waitSignal(model.dataChanged, timeout=1000):
    model.update_data()

# Wait for window to be shown
qtbot.waitExposed(window)
```

### 2. Thread and Worker Cleanup

#### ❌ WRONG: Not cleaning up QThread workers
```python
def test_worker():
    thread = QThread()
    worker = Worker()
    worker.moveToThread(thread)
    thread.start()
    # Test ends - thread still running!
```

#### ✅ CORRECT: Proper cleanup pattern
```python
def test_worker(qtbot):
    thread = QThread()
    worker = Worker()
    worker.moveToThread(thread)

    # Connect cleanup signals BEFORE starting
    thread.started.connect(worker.process)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    # Start thread
    thread.start()

    # Wait for completion with timeout
    with qtbot.waitSignal(worker.finished, timeout=5000):
        # Trigger work
        pass

    # Ensure thread stops
    thread.quit()
    thread.wait(1000)  # Wait up to 1 second
```

### 3. Signal Connection Safety

#### ❌ WRONG: Disconnecting without checking
```python
# This can raise TypeError if not connected
signal.disconnect()
```

#### ✅ CORRECT: Safe disconnection
```python
try:
    signal.disconnect()
except (TypeError, RuntimeError):
    # Signal was not connected or already disconnected
    pass
```

### 4. Cross-Thread Signal Safety

#### ❌ WRONG: Direct connection across threads
```python
# Can cause crashes if slot modifies GUI
worker.progress.connect(ui.update_progress, Qt.DirectConnection)
```

#### ✅ CORRECT: Use proper connection types
```python
# Safe cross-thread connection (automatic with AutoConnection)
worker.progress.connect(ui.update_progress)  # Qt.AutoConnection is default

# Explicit queued connection for clarity
worker.progress.connect(ui.update_progress, Qt.QueuedConnection)

# For synchronous cross-thread (use with caution!)
worker.result.connect(handler, Qt.BlockingQueuedConnection)
```

### 5. QRunnable and Thread Pool Testing

#### ❌ WRONG: Not waiting for QRunnable completion
```python
def test_runnable():
    runnable = MyRunnable()
    QThreadPool.globalInstance().start(runnable)
    # Test ends - runnable still running!
```

#### ✅ CORRECT: Proper QRunnable testing
```python
def test_runnable(qtbot):
    completed = []

    class TestRunnable(QRunnable):
        def __init__(self):
            super().__init__()
            self.signals = WorkerSignals()

        def run(self):
            # Do work
            self.signals.finished.emit()

    runnable = TestRunnable()
    runnable.signals.finished.connect(lambda: completed.append(True))

    # Start and wait for completion
    QThreadPool.globalInstance().start(runnable)

    # Wait for signal or timeout
    qtbot.waitUntil(lambda: len(completed) > 0, timeout=2000)
```

### 6. Model/View Thread Safety

#### ❌ WRONG: Updating model from worker thread
```python
class Worker(QObject):
    def process(self):
        # Direct model update from worker thread - DANGEROUS!
        self.model.setData(index, value)
```

#### ✅ CORRECT: Use signals for model updates
```python
class Worker(QObject):
    data_ready = Signal(object, object)  # index, value

    def process(self):
        # Emit signal to main thread
        self.data_ready.emit(index, value)

# In main thread
worker.data_ready.connect(lambda idx, val: model.setData(idx, val))
```

### 7. Timer Management in Tests

#### ❌ WRONG: Not stopping timers
```python
def test_with_timer():
    timer = QTimer()
    timer.timeout.connect(callback)
    timer.start(100)
    # Test ends - timer still running!
```

#### ✅ CORRECT: Proper timer cleanup
```python
def test_with_timer(qtbot):
    timer = QTimer()
    timer.timeout.connect(callback)
    timer.start(100)

    try:
        # Do test
        qtbot.wait(500)
    finally:
        timer.stop()
        timer.deleteLater()
```

### 8. QSignalSpy Best Practices

#### ✅ CORRECT: Using QSignalSpy effectively
```python
def test_signal_emission(qtbot):
    model = MyModel()

    # Create spy before triggering action
    spy = QSignalSpy(model.dataChanged)

    # Trigger action
    model.update_data()

    # Wait for signal with timeout
    assert spy.wait(1000)  # Returns True if signal emitted

    # Check signal parameters
    assert len(spy) == 1  # One emission
    args = spy.at(0)  # Get first emission arguments
    assert args[0] == expected_value
```

### 9. Avoiding Race Conditions in Tests

#### ❌ WRONG: Arbitrary waits
```python
# Hope 100ms is enough!
qtbot.wait(100)
assert widget.property == expected
```

#### ✅ CORRECT: Deterministic waiting
```python
# Wait for specific condition
qtbot.waitUntil(lambda: widget.property == expected, timeout=1000)

# Or use signals
with qtbot.waitSignal(widget.propertyChanged):
    widget.setProperty(value)
assert widget.property == expected
```

### 10. Thread Affinity Rules

#### Key Rules:
1. **Parent and child QObjects MUST live in the same thread**
2. **Create QObjects AFTER moveToThread(), not in __init__**
3. **Use QObject.thread() to check thread affinity**
4. **Cannot move object with parent to another thread**

#### ✅ CORRECT: Worker with proper thread affinity
```python
class Worker(QObject):
    def __init__(self):
        super().__init__()
        # DON'T create child QObjects here
        self.timer = None

    @Slot()
    def initialize(self):
        """Called AFTER moveToThread."""
        # NOW create QObjects - correct thread affinity
        self.timer = QTimer()
        self.timer.timeout.connect(self.process)
        self.timer.start(1000)

    @Slot()
    def process(self):
        # Work in correct thread
        pass

# Usage
worker = Worker()
thread = QThread()
worker.moveToThread(thread)
thread.started.connect(worker.initialize)  # Initialize after move
thread.start()
```

## Test-Specific Patterns

### Integration Test Setup
```python
@pytest.fixture
def main_window_safe(qapp, qtbot):
    """Create main window with proper cleanup."""
    # Ensure QApplication exists
    assert qapp is not None

    # Create window
    window = MainWindow()
    qtbot.addWidget(window)

    # Show and wait for exposure
    window.show()
    qtbot.waitExposed(window)

    yield window

    # Cleanup
    window.close()
```

### Mock Worker for Testing
```python
class MockWorker(QObject):
    """Thread-safe mock worker for testing."""

    finished = Signal()
    progress = Signal(int)

    def __init__(self):
        super().__init__()
        self._mutex = QMutex()
        self._is_running = False

    @Slot()
    def start(self):
        with QMutexLocker(self._mutex):
            if self._is_running:
                return
            self._is_running = True

        # Simulate work
        for i in range(100):
            if not self._is_running:
                break
            self.progress.emit(i)
            QThread.msleep(10)

        self.finished.emit()

    @Slot()
    def stop(self):
        with QMutexLocker(self._mutex):
            self._is_running = False
```

## Common Flaky Test Causes

1. **Race conditions from processEvents()**
   - Solution: Use qtbot.wait() or waitUntil()

2. **Threads/workers not cleaned up**
   - Solution: Always connect cleanup signals and wait for completion

3. **Arbitrary wait times**
   - Solution: Use deterministic waiting with waitUntil() or waitSignal()

4. **GUI updates from worker threads**
   - Solution: Always use signals to update GUI from main thread

5. **Timer-based tests without proper cleanup**
   - Solution: Stop and delete timers in finally blocks

6. **Signal spy created after action**
   - Solution: Create spy before triggering action

7. **Not waiting for window exposure**
   - Solution: Use qtbot.waitExposed() after show()

8. **Direct model updates from threads**
   - Solution: Use queued signal connections

## Debugging Flaky Tests

```python
# Add debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check thread affinity
print(f"Object thread: {obj.thread()}")
print(f"Current thread: {QThread.currentThread()}")

# Verify signal connections
try:
    # Qt 5.15+ / PySide6
    print(f"Receivers: {signal.isSignalConnected()}")
except:
    pass

# Use longer timeouts during debugging
qtbot.waitUntil(condition, timeout=10000)  # 10 seconds
```