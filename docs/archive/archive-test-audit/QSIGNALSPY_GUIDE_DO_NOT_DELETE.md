# QSignalSpy Guide for PySide6 Testing - DO NOT DELETE

*Critical reference for using QSignalSpy correctly in PySide6 tests*

## Overview

QSignalSpy is a class in PySide6.QtTest that enables introspection of signal emissions during testing. It captures signals and their arguments for verification.

## Import

```python
from PySide6.QtTest import QSignalSpy
```

## Key API Differences from PyQt

### ❌ INCORRECT (PyQt style that doesn't work in PySide6)
```python
spy = QSignalSpy(widget.signal)
assert len(spy) == 1  # TypeError: object of type 'PySide6.QtTest.QSignalSpy' has no len()
data = spy[0][0]  # TypeError: 'PySide6.QtTest.QSignalSpy' object is not subscriptable
```

### ✅ CORRECT (PySide6 style)
```python
spy = QSignalSpy(widget.signal)
assert spy.count() == 1  # Use count() method
data = spy.at(0)[0]  # Use at() method to access signal data
```

## Core Methods

### Constructor
```python
# Basic construction - pass the signal directly
spy = QSignalSpy(widget.signal_name)

# Alternative - pass object and signal
spy = QSignalSpy(obj, signal)
```

### Checking Signal Count
```python
# Get number of times signal was emitted
count = spy.count()
assert spy.count() == 1

# size() is an alias for count()
assert spy.size() == 1
```

### Accessing Signal Arguments
```python
# Get arguments of the Nth signal emission (0-indexed)
args = spy.at(0)  # Returns list of QVariant

# Access specific argument
first_signal_args = spy.at(0)
first_argument = first_signal_args[0]
```

### Waiting for Signals
```python
# Wait up to timeout (milliseconds) for signal
success = spy.wait(1000)  # Returns True if signal emitted within timeout
assert success

# Default timeout is 5000ms
spy.wait()
```

### Other Methods
```python
# Check if spy is valid (successfully connected to signal)
assert spy.isValid()

# Get the signal being spied
signal = spy.signal()

# Take and remove first signal (modifies the spy)
args = spy.takeFirst()
```

## Common Testing Patterns

### Basic Signal Verification
```python
def test_signal_emission(qtbot):
    widget = MyWidget()
    spy = QSignalSpy(widget.data_changed)
    
    # Trigger the signal
    widget.update_data("test")
    
    # Verify emission
    assert spy.count() == 1
    assert spy.at(0)[0] == "test"
```

### Multiple Signal Emissions
```python
def test_multiple_signals(qtbot):
    model = DataModel()
    spy = QSignalSpy(model.item_added)
    
    # Add multiple items
    model.add_item("A")
    model.add_item("B")
    model.add_item("C")
    
    # Verify all emissions
    assert spy.count() == 3
    assert spy.at(0)[0] == "A"
    assert spy.at(1)[0] == "B"
    assert spy.at(2)[0] == "C"
```

### Waiting for Async Signals
```python
def test_async_operation(qtbot):
    worker = AsyncWorker()
    spy = QSignalSpy(worker.finished)
    
    worker.start()
    
    # Wait for completion
    assert spy.wait(5000)  # Wait up to 5 seconds
    assert spy.count() == 1
    
    # Check result
    result = spy.at(0)[0]
    assert result == "success"
```

### Testing No Signal Emission
```python
def test_no_emission(qtbot):
    widget = MyWidget()
    spy = QSignalSpy(widget.error_occurred)
    
    # Perform valid operation
    widget.do_valid_operation()
    
    # Verify no error signal
    assert spy.count() == 0
```

### Complex Signal Arguments
```python
def test_complex_signal(qtbot):
    manager = DataManager()
    spy = QSignalSpy(manager.status_changed)
    
    manager.update_status(42, "active", 3.14)
    
    assert spy.count() == 1
    args = spy.at(0)
    assert args[0] == 42        # int
    assert args[1] == "active"  # str
    assert args[2] == 3.14      # float
```

## Common Pitfalls and Solutions

### 1. Using len() instead of count()
```python
# ❌ WRONG
if len(spy) > 0:
    pass

# ✅ CORRECT
if spy.count() > 0:
    pass
```

### 2. Direct indexing instead of at()
```python
# ❌ WRONG
first_signal = spy[0]

# ✅ CORRECT
first_signal = spy.at(0)
```

### 3. Not checking isValid()
```python
# ✅ GOOD PRACTICE
spy = QSignalSpy(widget.some_signal)
assert spy.isValid(), "Failed to connect to signal"
```

### 4. Forgetting QThread signals need special handling
```python
# For QThread-based workers, signals work differently
def test_thread_worker(qtbot):
    worker = ThreadWorker()
    spy = QSignalSpy(worker.progress)
    
    # Note: Don't use qtbot.addWidget() with QThread
    # QThread is not a QWidget
    
    worker.start()
    # ... test continues
```

## Integration with pytest-qt

### Using with qtbot
```python
def test_with_qtbot(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)  # Register widget for cleanup
    
    spy = QSignalSpy(widget.destroyed)
    
    widget.deleteLater()
    qtbot.wait(100)  # Process events
    
    assert spy.count() == 1
```

### Alternative: qtbot.waitSignal()
```python
# Instead of QSignalSpy + wait()
def test_with_wait_signal(qtbot):
    widget = MyWidget()
    
    with qtbot.waitSignal(widget.data_ready, timeout=1000) as blocker:
        widget.load_data()
    
    assert blocker.signal_triggered
    # Access args via blocker.args
```

## Real-World Example

```python
class TestThreeDESceneWorker:
    def test_pause_and_resume(self, qtbot, sample_shots):
        """Test pause and resume functionality with signals."""
        worker = ThreeDESceneWorker(shots=sample_shots)
        
        # Set up signal spies
        pause_spy = QSignalSpy(worker.paused)
        resume_spy = QSignalSpy(worker.resumed)
        
        # Initially not paused
        assert not worker.is_paused()
        
        # Pause the worker
        worker.pause()
        assert worker.is_paused()
        assert pause_spy.count() == 1
        
        # Pause again (should not emit signal)
        worker.pause()
        assert worker.is_paused()
        assert pause_spy.count() == 1  # Still only 1
        
        # Resume the worker
        worker.resume()
        assert not worker.is_paused()
        assert resume_spy.count() == 1
        
        # Resume again (should not emit signal)
        worker.resume()
        assert not worker.is_paused()
        assert resume_spy.count() == 1  # Still only 1
```

## Type Annotations

```python
from typing import List, Any
from PySide6.QtTest import QSignalSpy
from PySide6.QtCore import QObject, Signal

class MyClass(QObject):
    data_ready = Signal(str, int)
    
def test_typed(qtbot) -> None:
    obj = MyClass()
    spy: QSignalSpy = QSignalSpy(obj.data_ready)
    
    obj.data_ready.emit("test", 42)
    
    count: int = spy.count()
    args: List[Any] = spy.at(0)
    
    assert count == 1
    assert args[0] == "test"
    assert args[1] == 42
```

## Debugging Tips

1. **Print signal emissions for debugging:**
```python
for i in range(spy.count()):
    print(f"Signal {i}: {spy.at(i)}")
```

2. **Verify spy is connected:**
```python
spy = QSignalSpy(widget.signal)
if not spy.isValid():
    print("Failed to connect spy to signal!")
```

3. **Check what signal is being spied:**
```python
print(f"Spying on signal: {spy.signal()}")
```

## Summary

- **Always use `count()` not `len()`** to get number of signal emissions
- **Always use `at(index)` not `[index]`** to access signal data
- **Check `isValid()`** after construction to ensure connection
- **Use `wait(timeout)`** for async operations
- **Remember QThread is not a QWidget** - don't use qtbot.addWidget()
- **Consider qtbot.waitSignal()** as an alternative for simple cases

---
*Last Updated: 2025-08-16 | Critical Reference - DO NOT DELETE*