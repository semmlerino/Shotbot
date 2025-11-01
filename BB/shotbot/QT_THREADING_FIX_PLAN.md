# Qt Threading Race Condition Fix Plan

## Executive Summary
This document outlines the plan to fix critical Qt threading race conditions in the ShotBot application that can cause crashes, memory leaks, and undefined behavior.

## Issues Identified

### 1. Signal Disconnection Race Condition (HIGH RISK)
**Location:** `launcher_manager.py:1468-1475`
**Problem:** Signals are disconnected while the worker thread may still be emitting them, causing:
- RuntimeError: "wrapped C/C++ object has been deleted"
- Potential segmentation faults
- Memory corruption

### 2. Thread-Unsafe Cleanup Events (HIGH RISK)
**Location:** `launcher_manager.py:1441-1503`
**Problem:** `_cleanup_in_progress` Event accessed without proper locking:
- Multiple threads can enter cleanup simultaneously
- Dictionary modified during iteration
- Race conditions in process tracking

### 3. QThread Double Termination (MEDIUM RISK)
**Location:** `main_window.py:442-451`, `main_window.py:1227-1244`
**Problem:** Same worker thread can be terminated twice:
- Once in `_refresh_threede_scenes()` 
- Again in `closeEvent()`
- Can cause segmentation faults and undefined behavior

### 4. Missing Explicit Connection Types (MEDIUM RISK)
**Location:** Multiple signal connections throughout codebase
**Problem:** Cross-thread signals without explicit Qt.QueuedConnection
- Slots may execute in wrong thread
- Race conditions in slot execution

## Solution Architecture

### Core Principle: Thread-Safe Lifecycle Management
```
CREATED → STARTING → RUNNING → STOPPING → STOPPED → DELETED
```

Each transition must be atomic and thread-safe.

## Implementation Plan

### Phase 1: Create Thread-Safe Worker Base Class

```python
# thread_safe_worker.py
from PySide6.QtCore import QThread, QMutex, QMutexLocker, Signal, Qt
from typing import Optional
import weakref

class ThreadSafeWorker(QThread):
    """Base class for thread-safe workers with proper lifecycle management."""
    
    # Lifecycle signals
    worker_started = Signal()
    worker_stopping = Signal()
    worker_stopped = Signal()
    worker_error = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state_mutex = QMutex()
        self._state = "CREATED"
        self._stop_requested = False
        self._connections = []  # Track signal connections
        
    def get_state(self) -> str:
        """Thread-safe state getter."""
        with QMutexLocker(self._state_mutex):
            return self._state
    
    def set_state(self, new_state: str) -> bool:
        """Thread-safe state setter with validation."""
        valid_transitions = {
            "CREATED": ["STARTING"],
            "STARTING": ["RUNNING", "STOPPED"],
            "RUNNING": ["STOPPING"],
            "STOPPING": ["STOPPED"],
            "STOPPED": ["DELETED"]
        }
        
        with QMutexLocker(self._state_mutex):
            current = self._state
            if new_state in valid_transitions.get(current, []):
                self._state = new_state
                return True
            return False
    
    def request_stop(self) -> bool:
        """Thread-safe stop request."""
        if self.set_state("STOPPING"):
            self._stop_requested = True
            self.worker_stopping.emit()
            return True
        return False
    
    def safe_connect(self, signal, slot, connection_type=Qt.QueuedConnection):
        """Track signal connections for safe cleanup."""
        connection = (weakref.ref(signal), weakref.ref(slot))
        self._connections.append(connection)
        signal.connect(slot, connection_type)
    
    def disconnect_all(self):
        """Safely disconnect all tracked signals."""
        for signal_ref, slot_ref in self._connections:
            signal = signal_ref()
            slot = slot_ref()
            if signal and slot:
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass  # Already disconnected
        self._connections.clear()
    
    def run(self):
        """Override in subclass with actual work."""
        if not self.set_state("STARTING"):
            return
            
        self.worker_started.emit()
        
        if not self.set_state("RUNNING"):
            return
        
        try:
            self.do_work()
        except Exception as e:
            self.worker_error.emit(str(e))
        finally:
            self.set_state("STOPPED")
            self.worker_stopped.emit()
    
    def do_work(self):
        """Override this method with actual work implementation."""
        raise NotImplementedError
```

### Phase 2: Fix LauncherWorker Signal Disconnection

```python
# launcher_manager.py - Updated LauncherWorker
class LauncherWorker(ThreadSafeWorker):
    """Thread-safe worker for executing launcher commands."""
    
    command_started = Signal(str, str)
    command_finished = Signal(str, bool, int)
    command_error = Signal(str, str)
    
    def __init__(self, launcher_id: str, command: str, working_dir: Optional[str] = None):
        super().__init__()
        self.launcher_id = launcher_id
        self.command = command
        self.working_dir = working_dir
        self._process: Optional[subprocess.Popen[Any]] = None
        
    def do_work(self):
        """Execute the command with proper lifecycle management."""
        try:
            self.command_started.emit(self.launcher_id, self.command)
            
            self._process = subprocess.Popen(
                self.command,
                shell=False,  # SECURITY: Never use shell=True
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=self.working_dir,
                start_new_session=True,
            )
            
            # Poll with timeout to check for stop requests
            while not self._stop_requested:
                try:
                    return_code = self._process.wait(timeout=0.5)
                    # Process finished normally
                    success = return_code == 0
                    self.command_finished.emit(self.launcher_id, success, return_code)
                    return
                except subprocess.TimeoutExpired:
                    continue  # Check stop flag again
            
            # Stop was requested - terminate process
            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
                    
        except Exception as e:
            self.command_error.emit(self.launcher_id, str(e))
            self.command_finished.emit(self.launcher_id, False, -1)
```

### Phase 3: Fix Cleanup Thread Safety

```python
# launcher_manager.py - Thread-safe cleanup
class LauncherManager:
    def __init__(self):
        # Use RLock for recursive locking support
        self._process_lock = threading.RLock()
        self._cleanup_lock = threading.Lock()
        self._cleanup_in_progress = False
        self._active_workers: Dict[str, LauncherWorker] = {}
        
    def _cleanup_finished_workers(self):
        """Thread-safe worker cleanup with proper lifecycle management."""
        # Try to acquire cleanup lock without blocking
        if not self._cleanup_lock.acquire(blocking=False):
            logger.debug("Cleanup already in progress, skipping")
            return
            
        try:
            # Get snapshot of workers to check
            with self._process_lock:
                workers_to_check = list(self._active_workers.items())
            
            finished_workers = []
            
            for worker_key, worker in workers_to_check:
                state = worker.get_state()
                
                if state == "STOPPED":
                    # Worker finished normally
                    finished_workers.append(worker_key)
                    
                    # Disconnect signals BEFORE cleanup
                    worker.disconnect_all()
                    
                    # Schedule for deletion
                    worker.deleteLater()
                    
                elif state == "RUNNING" and not worker.isRunning():
                    # Worker stuck - request stop
                    if worker.request_stop():
                        if not worker.wait(1000):
                            worker.terminate()
                            worker.wait(500)
                    finished_workers.append(worker_key)
                    worker.deleteLater()
                    
            # Remove finished workers atomically
            if finished_workers:
                with self._process_lock:
                    for key in finished_workers:
                        self._active_workers.pop(key, None)
                        
        finally:
            self._cleanup_lock.release()
```

### Phase 4: Fix QThread Double Termination

```python
# main_window.py - Safe worker management
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._threede_worker: Optional[ThreeDESceneWorker] = None
        self._worker_mutex = QMutex()
        self._closing = False
        
    def _refresh_threede_scenes(self):
        """Thread-safe 3DE scene refresh."""
        with QMutexLocker(self._worker_mutex):
            if self._closing:
                return  # Don't start new work during shutdown
                
            # Check existing worker state
            if self._threede_worker:
                state = self._threede_worker.get_state()
                
                if state in ["RUNNING", "STARTING"]:
                    # Worker is active - request stop and wait
                    if self._threede_worker.request_stop():
                        self._threede_worker.wait(1000)
                    return
                    
                elif state == "STOPPED":
                    # Clean up old worker
                    self._threede_worker.deleteLater()
                    self._threede_worker = None
            
            # Create new worker
            self._threede_worker = ThreeDESceneWorker(
                shots=self.shot_model.shots,
                enable_progressive=True
            )
            
            # Use safe connections with explicit types
            self._threede_worker.safe_connect(
                self._threede_worker.started,
                self._on_threede_discovery_started,
                Qt.QueuedConnection
            )
            self._threede_worker.safe_connect(
                self._threede_worker.finished,
                self._on_threede_discovery_finished,
                Qt.QueuedConnection
            )
            
            self._threede_worker.start()
    
    def closeEvent(self, event: QCloseEvent):
        """Thread-safe shutdown."""
        with QMutexLocker(self._worker_mutex):
            self._closing = True
            
            if self._threede_worker:
                state = self._threede_worker.get_state()
                
                # Only stop if not already stopped
                if state not in ["STOPPED", "DELETED"]:
                    if self._threede_worker.request_stop():
                        if not self._threede_worker.wait(3000):
                            self._threede_worker.terminate()
                            self._threede_worker.wait()
                
                self._threede_worker = None
        
        super().closeEvent(event)
```

### Phase 5: Add Explicit Connection Types

```python
# Global fix for all signal connections
def setup_signal_connections(self):
    """Setup all signal connections with explicit types."""
    # Worker signals (cross-thread) - always use QueuedConnection
    worker.command_started.connect(
        self.on_command_started,
        Qt.QueuedConnection  # Explicit for cross-thread
    )
    
    # UI signals (same thread) - can use DirectConnection for performance
    button.clicked.connect(
        self.on_button_clicked,
        Qt.DirectConnection  # Same thread, immediate execution
    )
    
    # Model signals (may be cross-thread) - use AutoConnection
    model.dataChanged.connect(
        self.on_data_changed,
        Qt.AutoConnection  # Qt decides based on thread context
    )
```

## Testing Strategy

### 1. Unit Tests for Thread Safety
```python
def test_worker_lifecycle_transitions():
    """Test valid state transitions."""
    worker = ThreadSafeWorker()
    assert worker.get_state() == "CREATED"
    assert worker.set_state("STARTING") == True
    assert worker.set_state("RUNNING") == True
    assert worker.set_state("CREATED") == False  # Invalid transition
    assert worker.request_stop() == True
    assert worker.get_state() == "STOPPING"

def test_concurrent_cleanup():
    """Test concurrent cleanup operations."""
    manager = LauncherManager()
    
    # Start multiple cleanup threads
    threads = []
    for _ in range(10):
        t = threading.Thread(target=manager._cleanup_finished_workers)
        threads.append(t)
        t.start()
    
    # All should complete without deadlock
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive()
```

### 2. Stress Tests
```python
def test_rapid_start_stop_cycles():
    """Test rapid worker start/stop cycles."""
    window = MainWindow()
    
    for _ in range(100):
        window._refresh_threede_scenes()
        QTest.qWait(10)  # Small delay
        window.close()
        QTest.qWait(10)
    
    # Should complete without crashes
```

### 3. Thread Sanitizer Testing
```bash
# Run with thread sanitizer to detect race conditions
TSAN_OPTIONS=suppressions=qt_suppressions.txt python -m pytest tests/test_threading.py
```

## Rollout Plan

### Week 1: Foundation
1. Implement ThreadSafeWorker base class
2. Add comprehensive unit tests
3. Test with thread sanitizer

### Week 2: Integration
1. Update LauncherWorker to use ThreadSafeWorker
2. Fix cleanup thread safety
3. Update MainWindow worker management

### Week 3: Testing & Monitoring
1. Run stress tests
2. Monitor for race conditions in production
3. Add performance metrics

## Success Metrics

1. **Zero crashes** from threading issues over 1000 operations
2. **No memory leaks** from improper signal cleanup
3. **Stress test passes** 100 rapid start/stop cycles
4. **Thread sanitizer clean** - no race conditions detected

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Performance regression | Medium | Profile before/after, optimize critical paths |
| Backward compatibility | Low | Keep API unchanged, only internal changes |
| Complex debugging | Medium | Add comprehensive logging at state transitions |
| Qt version differences | Low | Test on Qt 5.15 and 6.x |

## Alternative Approaches Considered

1. **Using QtConcurrent:** Rejected - less control over lifecycle
2. **asyncio integration:** Rejected - Qt event loop conflicts  
3. **multiprocessing:** Rejected - overhead for simple tasks

## Code Review Checklist

- [ ] All workers inherit from ThreadSafeWorker
- [ ] No direct signal disconnection during emission
- [ ] All cross-thread signals use Qt.QueuedConnection
- [ ] State transitions are validated
- [ ] Cleanup is idempotent
- [ ] No double termination possible
- [ ] Thread sanitizer passes
- [ ] Stress tests pass
- [ ] Memory leak tests pass

## Conclusion

This plan addresses all identified threading issues with a systematic approach:
1. **Thread-safe lifecycle management** prevents race conditions
2. **Proper signal handling** prevents crashes
3. **Explicit connection types** ensure correct thread context
4. **Comprehensive testing** validates the fixes

The implementation is backward-compatible and improves overall application stability.