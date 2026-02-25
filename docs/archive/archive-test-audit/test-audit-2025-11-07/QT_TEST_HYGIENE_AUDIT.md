# Qt Test Hygiene Audit Report

## Executive Summary

The segfaults in `test_threede_worker_workflow.py` when run serially are NOT caused by "deep Qt C++ corruption" as documented. They are caused by **test hygiene issues** - specifically missing object cleanup that causes Qt C++ objects to accumulate across tests.

## Root Causes Identified

### 1. Missing deleteLater() + Event Processing (CRITICAL)

**Problem**: All `cleanup_worker()` functions disconnect signals and call `quit()`/`wait()`, but **never call `deleteLater()`** on the worker object or process events to flush the deletion queue.

**Impact**: Qt C++ objects accumulate across tests, eventually causing segfaults in `qtbot.waitSignal()`.

**Found in**:
- `test_worker_concurrent_signal_handling` (line 581-609)
- `test_worker_memory_and_resource_cleanup`
- `test_worker_full_production_workflow`
- All other worker tests

**Example of missing cleanup**:
```python
def cleanup_worker() -> None:
    # Disconnect signals
    worker.started.disconnect(started_wrapper)
    # ... other disconnects ...

    # Stop thread
    if worker.isRunning():
        worker.requestInterruption()
        worker.quit()
        worker.wait(5000)

    # ❌ MISSING: deleteLater() + event processing
```

**Required fix**:
```python
def cleanup_worker() -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    # Disconnect signals first
    try:
        worker.started.disconnect(started_wrapper)
    except (TypeError, RuntimeError):
        pass
    # ... other disconnects ...

    # Stop thread
    if worker.isRunning():
        worker.requestInterruption()
        worker.quit()
        worker.wait(5000)

    # ✅ CRITICAL: Delete the Qt C++ object
    worker.deleteLater()

    # ✅ CRITICAL: Process events to flush deletion queue
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()  # Second pass for cascading cleanups
```

### 2. Missing QApplication.exit() Monkeypatch

**Problem**: No autouse fixture prevents tests from accidentally calling `QApplication.exit()` or `qapp.exit()`, which poisons the event loop for subsequent tests.

**Impact**: If any test calls `exit()`, all subsequent tests fail with event loop corruption.

**Fix**: Add to `tests/conftest.py`:
```python
@pytest.fixture(autouse=True)
def prevent_qapp_exit(monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> None:
    """Prevent tests from calling QApplication.exit() which poisons event loops.

    pytest-qt explicitly warns that calling exit() breaks subsequent tests.
    This monkeypatch ensures tests can't accidentally poison the event loop.

    See: https://pytest-qt.readthedocs.io/en/latest/note_dialogs.html#warning-about-qapplication-exit
    """
    def _noop_exit(retcode: int = 0) -> None:
        pass  # Do nothing - tests shouldn't exit the app

    monkeypatch.setattr(qapp, "exit", _noop_exit)
    monkeypatch.setattr(QApplication, "exit", _noop_exit)
```

### 3. No Worker Parenting

**Problem**: Workers are created without a parent object:
```python
worker = ThreeDESceneWorker(
    shots=test_shots,
    excluded_users=set(),
    enable_progressive=True,
)
```

**Impact**: Qt's automatic parent-child cleanup doesn't apply. Worker must be manually deleted.

**Fix**: Either parent the worker to a test-owned widget, or ensure manual `deleteLater()` (see fix #1).

## What's Working Correctly

1. **`qt_cleanup` autouse fixture** - Excellent! Flushes deferred deletes, clears caches, waits for threads
2. **Signal disconnection** - All cleanup functions properly disconnect signals before stopping threads
3. **Thread stopping** - Proper `requestInterruption()` → `quit()` → `wait()` sequence
4. **QT_QPA_PLATFORM=offscreen** - Correctly set before imports
5. **No QApplication.exit() calls** - No tests call exit() currently (but protection needed)

## Incorrect Documentation to Fix

**File**: `tests/integration/test_threede_worker_workflow.py` lines 13-35

**Current (WRONG)**:
> "Root cause: Multiple sequential ThreeDESceneWorker executions leave Qt's event queue
> and signal mechanism in a corrupted state. Standard cleanup (signal disconnection,
> event processing, garbage collection) cannot prevent this deep Qt C++ issue."

**Corrected understanding**:
The segfaults are caused by **missing cleanup** (no `deleteLater()` + event processing), not by Qt corruption. Standard cleanup CAN and DOES prevent these issues when implemented correctly.

## Recommended Solutions

### Immediate Fixes (Required)

1. **Add `deleteLater()` + event processing to all `cleanup_worker()` functions**
2. **Add `prevent_qapp_exit` autouse fixture to conftest.py**
3. **Rewrite documentation to remove "deep Qt corruption" narrative**

### Additional Hardening (Recommended)

1. **pytest-forked for true isolation**:
   ```bash
   pip install pytest-forked
   pytest tests/integration/test_threede_worker_workflow.py --forked
   ```
   Or mark specific tests:
   ```python
   @pytest.mark.forked
   def test_worker_concurrent_signal_handling(self, qtbot): ...
   ```

2. **Worker restart in CI** (pyproject.toml):
   ```toml
   [tool.pytest.ini_options]
   addopts = [
       "--max-worker-restart=4",  # Restart workers periodically to prevent accumulation
   ]
   ```

3. **Parent workers to test widget**:
   ```python
   @pytest.fixture
   def parent_widget(qtbot):
       from PySide6.QtWidgets import QWidget
       widget = QWidget()
       qtbot.addWidget(widget)
       return widget

   def test_worker(qtbot, parent_widget):
       worker = ThreeDESceneWorker(parent=parent_widget, ...)
       # Qt will auto-cleanup when parent_widget is destroyed
   ```

## Test Execution Strategy

**Development** (fast feedback):
```bash
pytest tests/integration/test_threede_worker_workflow.py -n 2
```

**CI/Pre-merge** (catch accumulation):
```bash
pytest tests/integration/test_threede_worker_workflow.py -n 0 --forked
```

**For flaky tests** (true isolation):
```bash
pytest tests/integration/test_threede_worker_workflow.py --forked -n auto
```

## References

- [pytest-qt: Don't call QApplication.exit()](https://pytest-qt.readthedocs.io/en/latest/note_dialogs.html#warning-about-qapplication-exit)
- [Qt Object Trees & Ownership](https://doc.qt.io/qt-6/objecttrees.html)
- [pytest-forked for process isolation](https://github.com/pytest-dev/pytest-forked)
- [pytest-xdist --max-worker-restart](https://pytest-xdist.readthedocs.io/en/latest/how-to.html#dealing-with-tests-that-leak-resources)
