# Qt Concurrency Architectural Review
## Terminal/Launcher System - Qt Threading Analysis

**Analysis Date**: 2025-11-11
**Scope**: PersistentTerminalManager, CommandLauncher, LauncherController
**Focus**: Qt-specific threading, concurrency, and architecture patterns

---

## Executive Summary

The terminal/launcher system has **several critical Qt architecture violations** that block the GUI thread for up to 8 seconds during terminal health checks and recovery operations. While the code is functionally correct for single-threaded execution, it violates Qt best practices for responsive GUI applications.

**Severity Levels**:
- 🔴 **CRITICAL**: Blocks GUI thread for 5-8 seconds (user-visible freezing)
- 🟡 **WARNING**: Architecture violations that don't currently cause issues but are non-idiomatic
- 🟢 **INFO**: Opportunities for improvement

**Current Architecture**: All operations run synchronously on the GUI thread. No worker threads, no async operations, no event loop integration.

---

## 1. Qt Thread Safety Analysis

### 1.1 Threading Context ✅ SAFE (But Wrong Architecture)

**Current Implementation**:
```
User Action (GUI Thread)
    ↓
LauncherPanel.app_launch_requested signal (GUI Thread)
    ↓
LauncherController.launch_app() (GUI Thread)
    ↓
CommandLauncher.launch_app() (GUI Thread)
    ↓
PersistentTerminalManager.send_command() (GUI Thread)
    ↓
Signal Emission (GUI Thread)
```

**Finding**: All operations execute synchronously on the GUI thread.

**Assessment**:
- ✅ No cross-thread signal emission issues
- ✅ No race conditions between threads
- ❌ Blocking operations freeze the GUI for seconds
- ❌ No responsiveness during long operations

---

## 2. Critical Issues: GUI Thread Blocking

### 🔴 CRITICAL Issue #1: Health Check Blocking (5 seconds)

**Location**: `persistent_terminal_manager.py:569-631`

```python
def _ensure_dispatcher_healthy(self) -> bool:
    # ... health check fails ...

    # BLOCKS GUI THREAD FOR UP TO 5 SECONDS
    timeout = 5.0
    poll_interval = 0.2
    elapsed = 0.0

    while elapsed < timeout:
        if self._is_dispatcher_healthy():
            return True
        time.sleep(poll_interval)  # ← BLOCKS GUI THREAD 200ms per iteration
        elapsed += poll_interval

    return False
```

**Impact**:
- GUI freezes for up to 5 seconds when dispatcher needs recovery
- User cannot interact with application during health check
- No progress indication to user
- Called from `send_command()` which is called on user button clicks

**Frequency**: Every time dispatcher health check fails (restart scenarios)

---

### 🔴 CRITICAL Issue #2: Terminal Launch Blocking (3.5 seconds)

**Location**: `persistent_terminal_manager.py:360-462`

```python
def _launch_terminal(self) -> bool:
    # subprocess.Popen is fine (non-blocking)
    self.terminal_process = subprocess.Popen(cmd, start_new_session=True)

    # BLOCKS GUI THREAD FOR 500ms
    time.sleep(0.5)

    # BLOCKS GUI THREAD FOR UP TO 3 SECONDS
    timeout = 3.0
    poll_interval = 0.2
    elapsed = 0.0

    while elapsed < timeout:
        self.dispatcher_pid = self._find_dispatcher_pid()
        if self.dispatcher_pid is not None:
            break
        time.sleep(poll_interval)  # ← BLOCKS GUI THREAD 200ms per iteration
        elapsed += poll_interval

    return True
```

**Impact**:
- GUI freezes for 0.5-3.5 seconds during terminal launch
- User sees application "hang" with no feedback
- Called during first command send or after recovery

**Total Blocking Time**: Up to **8.5 seconds** (health check + launch + additional waits)

---

### 🔴 CRITICAL Issue #3: Additional Blocking Operations

**Location**: Multiple locations

```python
# Line 601: Kill operation blocking
time.sleep(0.5)  # ← BLOCKS GUI 500ms

# Line 425: Launch verification blocking
time.sleep(0.5)  # ← BLOCKS GUI 500ms

# Lines 522-565: FIFO write operations
# Uses os.open() with O_NONBLOCK but can still block briefly
fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
```

**Cumulative Impact**: Terminal operations can block GUI for 5-10 seconds total.

---

## 3. QObject Lifecycle Issues

### 🟡 WARNING Issue #4: Missing Parent-Child Relationship

**Location**: `main_window.py:323-329`

```python
# PROBLEM: No parent parameter passed
self.persistent_terminal = PersistentTerminalManager(
    fifo_path=Config.PERSISTENT_TERMINAL_FIFO
)  # ← Should pass parent=self

self.command_launcher = CommandLauncher(
    persistent_terminal=self.persistent_terminal
)  # ← Should pass parent=self
```

**Constructor Signatures** (Don't Accept Parent):
```python
# persistent_terminal_manager.py:39-41
def __init__(
    self, fifo_path: str | None = None, dispatcher_path: str | None = None
) -> None:  # ← Missing parent: QObject | None = None parameter
    super().__init__()  # ← Should be super().__init__(parent)

# command_launcher.py:66-73
def __init__(
    self,
    raw_plate_finder: type[RawPlateFinderType] | None = None,
    # ... other params ...
    persistent_terminal: PersistentTerminalManager | None = None,
) -> None:  # ← Missing parent: QObject | None = None parameter
    super().__init__()  # ← Should be super().__init__(parent)
```

**Consequences**:
1. **No Automatic Cleanup**: Qt won't auto-delete these objects when MainWindow is destroyed
2. **Broken Object Hierarchy**: Qt's parent-child ownership chain is incomplete
3. **Memory Leak Risk**: Objects may persist after window closure
4. **Signal Cleanup Issues**: Signals remain connected after parent destruction

**Current Workaround**: `CleanupManager` manually calls `persistent_terminal.cleanup()`, but this is fragile and non-idiomatic Qt.

---

### 🟡 WARNING Issue #5: __del__ in QObject

**Location**: `persistent_terminal_manager.py:774-781`

```python
def __del__(self) -> None:
    """Cleanup on deletion."""
    try:
        # Only cleanup FIFO, leave terminal running
        if hasattr(self, "fifo_path") and Path(self.fifo_path).exists():
            Path(self.fifo_path).unlink()
    except Exception:
        pass
```

**Problems**:
1. **Non-Deterministic**: `__del__` can be called at any time, from any thread
2. **No Qt Guarantee**: May be called after Qt has shut down
3. **Thread Safety**: Could be called from wrong thread
4. **Not Qt Idiomatic**: Should use `deleteLater()` or explicit cleanup

**Qt Best Practice**: Use `closeEvent()` or explicit `cleanup()` method, not `__del__`.

---

## 4. Signal/Slot Architecture

### ✅ Signal Definitions (Correct)

Both classes properly inherit from QObject and define signals:

```python
# persistent_terminal_manager.py:31-37
class PersistentTerminalManager(LoggingMixin, QObject):
    terminal_started = Signal(int)  # PID of terminal
    terminal_closed = Signal()
    command_sent = Signal(str)

# command_launcher.py:55-64
class CommandLauncher(LoggingMixin, QObject):
    command_executed = Signal(str, str)  # timestamp, command
    command_error = Signal(str, str)  # timestamp, error
```

**Assessment**: ✅ Correct Qt signal definitions

---

### ✅ Signal Connections (Safe, But Missing Connection Types)

**Location**: `controllers/launcher_controller.py:106-140`

```python
def _setup_signals(self) -> None:
    # All use default AutoConnection
    self.window.launcher_panel.app_launch_requested.connect(self.launch_app)
    self.window.command_launcher.command_executed.connect(
        self.window.log_viewer.add_command
    )
    self.window.command_launcher.command_error.connect(
        self.window.log_viewer.add_error
    )
    # ... more connections ...
```

**Current Behavior**:
- Uses default `Qt.ConnectionType.AutoConnection`
- Since all objects are on GUI thread, this becomes `Qt.ConnectionType.DirectConnection`
- Signals execute slots synchronously in same thread

**Assessment**:
- ✅ Safe for current single-threaded architecture
- 🟡 Should explicitly specify connection types for clarity
- 🟡 Will need changes if moving to worker threads

**Recommendation**: Explicitly specify connection types:
```python
# For same-thread (explicit)
signal.connect(slot, type=Qt.ConnectionType.DirectConnection)

# For cross-thread (future-proofing)
signal.connect(slot, type=Qt.ConnectionType.QueuedConnection)
```

---

### ✅ Signal Emission (All From GUI Thread)

**Examples**:
```python
# persistent_terminal_manager.py:451
self.terminal_started.emit(self.terminal_pid)  # ← GUI thread

# persistent_terminal_manager.py:534
self.command_sent.emit(command)  # ← GUI thread

# command_launcher.py:316
self.command_executed.emit(timestamp, msg)  # ← GUI thread
```

**Assessment**: ✅ All signals emitted from GUI thread (safe)

---

## 5. Lock Usage Analysis

### 🟡 WARNING Issue #6: threading.Lock Instead of QMutex

**Location**: `persistent_terminal_manager.py:79-80`

```python
# Thread safety: Lock for serializing FIFO writes
self._write_lock = threading.Lock()
```

**Usage**:
```python
# Line 517-535
with self._write_lock:
    # Send command to FIFO using non-blocking I/O
    fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
    # ... FIFO write operations ...
```

**Assessment**:
- ✅ Functionally correct (prevents concurrent FIFO writes)
- 🟡 Not Qt-idiomatic (should use `QMutex` or `QMutexLocker`)
- ℹ️ Not a problem in current single-threaded architecture
- 🟡 Will need changes if moving to worker threads

**Qt Best Practice**:
```python
from PySide6.QtCore import QMutex, QMutexLocker

self._write_lock = QMutex()

# Usage
with QMutexLocker(self._write_lock):
    # Critical section
    pass
```

---

## 6. Event Loop Integration

### ✅ QTimer Usage (Correct Pattern)

**Location**: `command_launcher.py:500, 699, 925`

```python
# Schedule verification callback on event loop
QTimer.singleShot(100, partial(self._verify_spawn, process, app_name))
```

**Assessment**: ✅ Correct Qt pattern for deferred execution

---

### ❌ Missing processEvents() or Async Operations

**Problem**: Long-running operations don't yield to event loop

Current blocking pattern:
```python
# BLOCKS EVENT LOOP FOR 5 SECONDS
while elapsed < timeout:
    if self._is_dispatcher_healthy():
        return True
    time.sleep(poll_interval)  # ← Event loop not processing
    elapsed += poll_interval
```

**Should Be** (if staying synchronous):
```python
from PySide6.QtCore import QElapsedTimer
from PySide6.QtWidgets import QApplication

timer = QElapsedTimer()
timer.start()

while timer.elapsed() < timeout_ms:
    if self._is_dispatcher_healthy():
        return True
    QApplication.processEvents()  # ← Allow GUI to remain responsive
    QThread.msleep(poll_interval_ms)
```

**Better Solution**: Move to worker thread (see recommendations).

---

## 7. Qt-Specific Race Conditions

### ✅ No Cross-Thread Widget Access

**Assessment**: No GUI widgets accessed from non-GUI threads (because everything runs on GUI thread).

---

### ✅ No Premature Object Deletion Issues

**Assessment**: Objects remain alive during operations due to strong references from MainWindow.

---

### 🟡 Potential Signal Emission Timing Issues

**Scenario**: If moved to worker thread in future

```python
# In worker thread (future scenario)
self.terminal_started.emit(self.terminal_pid)  # ← Must use QueuedConnection
```

**Current Status**: Not an issue (single-threaded), but needs consideration for future threading.

---

## 8. Architecture Pattern Analysis

### Current Pattern: Synchronous Single-Threaded

```
[GUI Thread]
  ↓
User Button Click
  ↓
LauncherController.launch_app()
  ↓
CommandLauncher.launch_app()
  ↓
PersistentTerminalManager.send_command()
  ↓
Blocking Operations (time.sleep, polling)
  ↓
Signal Emission
  ↓
[GUI Frozen During This Time]
```

**Problems**:
- GUI blocks for 5-10 seconds during terminal operations
- No progress indication possible
- Poor user experience
- Violates Qt responsiveness guidelines

---

### Recommended Pattern: Worker Thread with Signals

```
[GUI Thread]                    [Worker Thread]
  ↓
User Button Click
  ↓
Start Worker Thread
  ↓ (QueuedConnection)
Show Progress Dialog  ────────> Terminal Operations
  ↓                            (Blocking OK Here)
Process Other Events            ↓
  ↓                            Health Checks
Remain Responsive               ↓
  ↓                            Recovery
Update Progress <────────────── Progress Signals
  ↓                            ↓
Hide Progress Dialog <────────── Finished Signal
```

**Benefits**:
- GUI remains responsive during terminal operations
- Can show progress indication
- Can cancel operations
- Better user experience
- Follows Qt best practices

---

## 9. Detailed Recommendations

### 🔴 CRITICAL Priority: Fix GUI Blocking

**Option 1: Move Terminal Operations to Worker Thread (Recommended)**

**Implementation Pattern**:

```python
from PySide6.QtCore import QObject, QThread, Signal, Slot

class TerminalWorker(QObject):
    """Worker for terminal operations."""

    # Signals for communication
    progress = Signal(str)  # Progress message
    finished = Signal(bool)  # Success/failure
    error = Signal(str)  # Error message

    def __init__(self, terminal_manager: PersistentTerminalManager):
        super().__init__()
        self.terminal_manager = terminal_manager

    @Slot()
    def send_command(self, command: str) -> None:
        """Send command in worker thread."""
        try:
            self.progress.emit("Checking terminal health...")

            # Blocking operations OK in worker thread
            success = self.terminal_manager.send_command(command)

            self.finished.emit(success)
        except Exception as e:
            self.error.emit(str(e))

class PersistentTerminalManager(LoggingMixin, QObject):
    # Existing signals...

    def __init__(
        self,
        fifo_path: str | None = None,
        dispatcher_path: str | None = None,
        parent: QObject | None = None  # ← ADD THIS
    ) -> None:
        super().__init__(parent)  # ← Pass parent
        # ... existing init ...

    def send_command_async(self, command: str) -> None:
        """Non-blocking command send using worker thread."""
        self.worker_thread = QThread()
        self.worker = TerminalWorker(self)

        # Move worker to thread
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(lambda: self.worker.send_command(command))
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        # Connect to UI updates
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)

        # Start thread
        self.worker_thread.start()
```

**Option 2: Use QThreadPool with QRunnable (Alternative)**

```python
from PySide6.QtCore import QRunnable, QThreadPool, Signal, Slot

class TerminalTask(QRunnable):
    """Task for terminal operations in thread pool."""

    class Signals(QObject):
        finished = Signal(bool)
        error = Signal(str)

    def __init__(self, command: str, manager):
        super().__init__()
        self.command = command
        self.manager = manager
        self.signals = self.Signals()

    def run(self):
        try:
            success = self.manager.send_command(command)
            self.signals.finished.emit(success)
        except Exception as e:
            self.signals.error.emit(str(e))

# Usage
pool = QThreadPool.globalInstance()
task = TerminalTask(command, self)
task.signals.finished.connect(self._on_finished)
pool.start(task)
```

---

### 🟡 HIGH Priority: Fix QObject Lifecycle

**1. Add Parent Parameter to Constructors**

```python
# persistent_terminal_manager.py
def __init__(
    self,
    fifo_path: str | None = None,
    dispatcher_path: str | None = None,
    parent: QObject | None = None  # ← ADD THIS
) -> None:
    super().__init__(parent)  # ← Pass parent
    # ... rest of init ...

# command_launcher.py
def __init__(
    self,
    raw_plate_finder: type[RawPlateFinderType] | None = None,
    nuke_script_generator: type[NukeScriptGeneratorType] | None = None,
    threede_latest_finder: type[ThreeDELatestFinderType] | None = None,
    maya_latest_finder: type[MayaLatestFinderType] | None = None,
    persistent_terminal: PersistentTerminalManager | None = None,
    parent: QObject | None = None  # ← ADD THIS
) -> None:
    super().__init__(parent)  # ← Pass parent
    # ... rest of init ...
```

**2. Update MainWindow Instantiation**

```python
# main_window.py
self.persistent_terminal = PersistentTerminalManager(
    fifo_path=Config.PERSISTENT_TERMINAL_FIFO,
    parent=self  # ← ADD THIS
)

self.command_launcher = CommandLauncher(
    persistent_terminal=self.persistent_terminal,
    parent=self  # ← ADD THIS
)
```

**Benefits**:
- Qt automatically deletes child objects when parent is destroyed
- Proper cleanup without manual CleanupManager calls
- Follows Qt object ownership model
- Signals automatically disconnected on parent destruction

---

**3. Remove __del__ Method**

```python
# persistent_terminal_manager.py
# DELETE THIS:
def __del__(self) -> None:
    """Cleanup on deletion."""
    try:
        if hasattr(self, "fifo_path") and Path(self.fifo_path).exists():
            Path(self.fifo_path).unlink()
    except Exception:
        pass

# REPLACE WITH:
# Cleanup is already handled in cleanup() method
# Qt will call this via CleanupManager or parent destruction
```

---

### 🟡 MEDIUM Priority: Improve Signal Architecture

**1. Explicit Connection Types**

```python
# controllers/launcher_controller.py
def _setup_signals(self) -> None:
    # Explicit same-thread connections
    self.window.launcher_panel.app_launch_requested.connect(
        self.launch_app,
        type=Qt.ConnectionType.DirectConnection  # ← Explicit
    )

    # If using worker threads, use QueuedConnection
    self.worker.progress.connect(
        self.update_progress,
        type=Qt.ConnectionType.QueuedConnection  # ← Cross-thread
    )
```

**2. Add @Slot Decorators**

```python
# persistent_terminal_manager.py
@Slot()
def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    """Send a command to the persistent terminal."""
    # ... implementation ...

# command_launcher.py
@Slot(str, bool, bool, bool, bool, bool, str)
def launch_app(
    self,
    app_name: str,
    include_raw_plate: bool = False,
    # ... other params ...
) -> bool:
    """Launch an application."""
    # ... implementation ...
```

**Benefits**:
- Explicit slot declaration
- Better error messages from Qt
- Performance optimization hints for Qt's meta-object system

---

### 🟢 LOW Priority: Qt-Idiomatic Lock Usage

**Replace threading.Lock with QMutex**

```python
# persistent_terminal_manager.py
from PySide6.QtCore import QMutex, QMutexLocker

def __init__(self, ...):
    super().__init__(parent)

    # Replace threading.Lock with QMutex
    self._write_lock = QMutex()  # ← Qt-idiomatic

    # ... rest of init ...

def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    # Use QMutexLocker for RAII
    with QMutexLocker(self._write_lock):  # ← Qt-idiomatic
        # Critical section
        fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        # ... FIFO operations ...
```

**Benefits**:
- Integrates with Qt's threading model
- Better debugging with Qt tools
- Consistent with other Qt code

---

## 10. Testing Considerations

### Current Test Challenges

1. **GUI Blocking Not Testable**: Tests don't experience GUI freezing
2. **No Async Test Patterns**: Tests assume synchronous execution
3. **Mock Subprocess Required**: Terminal operations spawn real processes

### Recommended Test Updates (After Worker Thread Implementation)

```python
# tests/unit/test_persistent_terminal_manager.py
import pytest
from PySide6.QtCore import QSignalSpy

@pytest.fixture
def terminal_manager(qtbot):
    """Create terminal manager with Qt event loop."""
    manager = PersistentTerminalManager()
    qtbot.addWidget(manager)  # Ensures proper cleanup
    return manager

def test_async_command_send(qtbot, terminal_manager):
    """Test asynchronous command sending."""
    # Setup signal spy
    spy = QSignalSpy(terminal_manager.command_sent)

    # Send command asynchronously
    terminal_manager.send_command_async("test command")

    # Wait for signal with timeout
    assert spy.wait(timeout=5000), "Command signal not emitted within 5s"
    assert len(spy) == 1
    assert spy[0][0] == "test command"

def test_progress_updates(qtbot, terminal_manager):
    """Test progress signal emission during long operations."""
    progress_messages = []

    def capture_progress(msg):
        progress_messages.append(msg)

    terminal_manager.worker.progress.connect(capture_progress)
    terminal_manager.send_command_async("test command")

    # Wait for completion
    qtbot.waitUntil(lambda: len(progress_messages) > 0, timeout=5000)

    assert "Checking terminal health" in progress_messages
```

---

## 11. Migration Path

### Phase 1: Fix QObject Lifecycle (Low Risk)
1. Add parent parameters to constructors
2. Update MainWindow instantiation
3. Remove __del__ method
4. Test existing functionality

**Estimated Effort**: 2-4 hours
**Risk**: Low
**Benefit**: Proper cleanup, memory leak prevention

---

### Phase 2: Add Async API (Medium Risk)
1. Create `send_command_async()` method with worker thread
2. Keep existing `send_command()` for backward compatibility
3. Update GUI code to use async version
4. Add progress signals and UI feedback

**Estimated Effort**: 1-2 days
**Risk**: Medium
**Benefit**: Responsive GUI, better UX

---

### Phase 3: Deprecate Synchronous API (Low Risk)
1. Mark `send_command()` as deprecated
2. Update all call sites to async version
3. Remove synchronous version in future release

**Estimated Effort**: 4-8 hours
**Risk**: Low (after Phase 2 testing)
**Benefit**: Cleaner API, enforced responsiveness

---

## 12. Summary of Findings

### Critical Issues (Fix Immediately)
1. 🔴 **GUI thread blocking for 5-10 seconds** during terminal operations
2. 🔴 **No progress indication** during long operations
3. 🔴 **Poor user experience** due to application freezing

### Warning Issues (Fix Soon)
4. 🟡 **Missing parent-child QObject relationships** (memory leak risk)
5. 🟡 **__del__ method in QObject** (non-deterministic cleanup)
6. 🟡 **threading.Lock instead of QMutex** (non-idiomatic)

### Informational (Future Improvements)
7. 🟢 **No explicit connection types** (implicit AutoConnection)
8. 🟢 **No @Slot decorators** (missing Qt metadata)
9. 🟢 **No async API** (synchronous only)

---

## 13. Conclusion

The terminal/launcher system is **functionally correct but architecturally problematic** from a Qt perspective. The most critical issue is GUI thread blocking during terminal health checks and recovery, which can freeze the application for up to 10 seconds.

**Immediate Actions Required**:
1. Move blocking terminal operations to worker thread
2. Add parent-child QObject relationships
3. Remove __del__ method

**Long-Term Improvements**:
4. Use Qt-idiomatic patterns (QMutex, explicit connection types, @Slot decorators)
5. Add comprehensive async API
6. Improve test coverage for async operations

The recommended worker thread pattern is standard Qt practice and will significantly improve application responsiveness while maintaining correctness.

---

## Appendix A: Qt Threading Best Practices Reference

### Do's ✅
- Inherit from QObject for signal/slot support
- Pass parent parameter to all QObject constructors
- Use QThread/QThreadPool for long-running operations
- Use QueuedConnection for cross-thread signals
- Use QMutex/QReadWriteLock for thread-safe data access
- Call deleteLater() for object cleanup
- Use @Slot decorators for clarity

### Don'ts ❌
- Don't block GUI thread with time.sleep() or polling loops
- Don't implement __del__ in QObject subclasses
- Don't access GUI widgets from non-GUI threads
- Don't use Python threading.Lock in Qt code (use QMutex)
- Don't subclass QThread unless necessary (use moveToThread pattern)
- Don't call processEvents() frequently (indicates wrong architecture)

### Connection Types
- **AutoConnection** (default): Qt chooses Direct or Queued based on thread
- **DirectConnection**: Synchronous, same-thread execution
- **QueuedConnection**: Asynchronous, cross-thread safe
- **BlockingQueuedConnection**: Synchronous cross-thread (deadlock risk!)
- **UniqueConnection**: Prevents duplicate connections

---

**End of Report**
