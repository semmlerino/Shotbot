# Launcher/Terminal System Architecture Analysis

**Depth**: Very Thorough  
**Date**: November 14, 2025  
**Focus**: Architectural structure, design patterns, code organization, maintainability

---

## Executive Summary

The launcher/terminal system is a complex multi-component architecture managing application launching, terminal persistence, and process coordination. While the system demonstrates sophisticated engineering in threading and signal management, it suffers from:

- **God Classes** violating Single Responsibility Principle
- **Inconsistent Worker Patterns** across the codebase
- **Complex Lock Hierarchies** with implicit deadlock prevention
- **Tight Component Coupling** hindering maintainability
- **Mixed Synchronization Primitives** (threading.Lock + QMutex)

**Overall Health**: MEDIUM - Functional but increasingly difficult to maintain and extend

---

## Architecture Overview

### Component Graph

```
┌─────────────────────────────────────────────────────────────┐
│                    CommandLauncher                          │
│  (Application launching with shot context)                  │
│  998 lines, 11+ responsibilities                            │
└──────────────┬──────────────────────────────────────────────┘
               │ uses
               ▼
┌──────────────────────────────────────────────────────────────┐
│           PersistentTerminalManager                         │
│  (Terminal session & FIFO management)                       │
│  1,552 lines, 8 major responsibilities                      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  FIFO Management Layer                              │   │
│  │  • _ensure_fifo(), _open_dummy_writer()             │   │
│  │  • _send_command_direct()                           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Terminal Lifecycle Management                      │   │
│  │  • _launch_terminal()                               │   │
│  │  • restart_terminal()                               │   │
│  │  • close_terminal()                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Health Monitoring & Recovery                       │   │
│  │  • _is_dispatcher_healthy()                         │   │
│  │  • _is_dispatcher_running()                         │   │
│  │  • _ensure_dispatcher_healthy()                     │   │
│  │  • _send_heartbeat_ping()                           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Worker & Async Execution                           │   │
│  │  • send_command_async()                             │   │
│  │  • _on_async_command_finished()                     │   │
│  │  • _active_workers list management                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Resource Cleanup & Lifecycle                       │   │
│  │  • cleanup()                                        │   │
│  │  • cleanup_fifo_only()                              │   │
│  │  • _close_dummy_writer_fd()                         │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────┬──────────────────────────────────────────────┘
               │ spawns
               ▼
┌──────────────────────────────────────────────────────────────┐
│        TerminalOperationWorker(QThread)                     │
│  (Background operation executor - INCONSISTENT PATTERN)      │
│  180 lines                                                  │
│  • _run_health_check()                                      │
│  • _run_send_command()                                      │
│  • Phase 1 & 2 signal coordination                          │
└──────────────┬──────────────────────────────────────────────┘
               │ delegates to
               ▼
       ┌───────────────────┐
       │ ProcessVerifier   │
       │ (Process startup  │
       │  verification)    │
       └───────────────────┘

               │ uses
               ▼
┌──────────────────────────────────────────────────────────────┐
│           Launch System Components                          │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌───────────┐   │
│  │ EnvironmentMgr  │  │ CommandBuilder  │  │ ProcessEx │   │
│  │ • Rez detection │  │ • Path safety   │  │ • Spawn   │   │
│  │ • Terminal find │  │ • Logging wrap  │  │ • Verify  │   │
│  └─────────────────┘  └─────────────────┘  └───────────┘   │
└──────────────────────────────────────────────────────────────┘

               │ manages
               ▼
┌──────────────────────────────────────────────────────────────┐
│         ProcessPoolManager (SINGLETON)                      │
│  773 lines, 5 major responsibilities                        │
│                                                             │
│  • Session pooling (round-robin balancing)                 │
│  • Command caching (TTL-based)                             │
│  • Metrics collection                                      │
│  • ThreadPoolExecutor management                           │
│  • Batch execution coordination                            │
└──────────────────────────────────────────────────────────────┘

               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│      Launcher Module (Custom Launcher Management)           │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌───────────┐   │
│  │ LauncherWorker  │  │ LauncherProcess │  │ Models    │   │
│  │ (ThreadSafeWkr) │  │ Manager (Qt)    │  │ (Data)    │   │
│  └─────────────────┘  └─────────────────┘  └───────────┘   │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ LauncherValidator│  │ LauncherRepository│              │
│  │ (Validation)    │  │ (Persistence)   │                  │
│  └─────────────────┘  └─────────────────┘                  │
└──────────────────────────────────────────────────────────────┘
```

---

## Critical Architectural Issues

### 1. CRITICAL: PersistentTerminalManager - God Class Anti-Pattern

**Severity**: CRITICAL  
**File**: `persistent_terminal_manager.py` (1,552 lines)  
**Evidence**: Single class with 8+ distinct responsibilities

#### Responsibilities (SRP Violations):

1. **FIFO I/O Management** (lines 290-354)
   - FIFO creation, validation, dummy writer management
   - Non-blocking write operations with retry logic
   - File descriptor lifecycle

2. **Terminal Process Lifecycle** (lines 706-827, 1319-1437)
   - Terminal emulator launching (tries multiple emulators)
   - Restart logic with atomic FIFO recreation
   - PID tracking and process verification

3. **Health Monitoring & Diagnostics** (lines 414-644)
   - Dispatcher process detection
   - FIFO reader availability checking
   - Heartbeat mechanism with file-based communication
   - Health check state machine

4. **Worker Thread Coordination** (lines 1002-1093, 1094-1223)
   - Active worker tracking (line 267)
   - Async command queuing
   - Signal emission for Phase 1 & 2 lifecycle
   - Worker cleanup and garbage collection prevention

5. **State Management & Recovery** (lines 234-260, 839-910)
   - Fallback mode with auto-recovery after 5 minutes
   - Restart attempt counter and max attempts
   - Complex state transitions
   - Three separate locks protecting different state pieces

6. **Resource Cleanup** (lines 1439-1587)
   - Complex cleanup sequence with deadlock prevention (comments at lines 1441-1477)
   - FIFO removal and terminal termination
   - Worker thread joining with timeouts
   - Class-level test instance tracking

7. **Process Verification Delegation** (lines 164-167)
   - Owns ProcessVerifier instance
   - Manages PID file cleanup

8. **Heartbeat Communication** (lines 536-601)
   - File-based PING/PONG protocol
   - Heartbeat file creation/deletion
   - Timeout-based response checking

#### Lock Complexity & Deadlock Risk:

```python
# Three separate locks with potential ordering issues
self._write_lock = threading.RLock()      # Line 256: FIFO writes + health checks
self._state_lock = threading.Lock()       # Line 260: All shared state
self._restart_lock = threading.Lock()     # Line 264: Serializes terminal restarts
```

**Lock Acquisition Patterns**:
- `_write_lock` → `_state_lock` (send_command, line 892-914)
- `_restart_lock` → `_state_lock` (restart_terminal, multiple places)
- `_state_lock` acquired multiple times in cleanup (line 1487)

**Deadlock Prevention Comments** (Line 1441-1477):
```
CRITICAL: Workers must be stopped FIRST to prevent deadlock on _state_lock.
...
DO NOT call terminate() - it kills threads holding locks
```

This indicates the design is inherently fragile and difficult to reason about.

#### Impact:

- **Testability**: 36+ test files reference this class; changes require extensive testing
- **Maintainability**: New features require understanding 1,552 lines of logic
- **Bug Risk**: Changes to lock ordering or state management can introduce subtle deadlocks
- **Reusability**: Cannot reuse individual components (FIFO management, health checking, etc.)

#### Refactoring Approach:

Extract into 4-5 focused classes:

```
FIFOManager
├── _ensure_fifo()
├── _open_dummy_writer()
├── _send_command_direct()
└── _close_dummy_writer_fd()

TerminalProcessManager
├── _launch_terminal()
├── restart_terminal()
├── close_terminal()
└── _is_terminal_alive()

DispatcherHealthChecker
├── _is_dispatcher_healthy()
├── _is_dispatcher_running()
├── _send_heartbeat_ping()
└── _check_heartbeat()

TerminalRecoveryManager
├── _ensure_dispatcher_healthy()
├── _perform_restart_internal()
└── fallback mode logic

PersistentTerminalOrchestrator (NEW - slim coordinator)
├── Composes above four classes
├── send_command()
├── send_command_async()
└── cleanup()
```

**Effort Estimate**: 3-4 weeks (including tests)

---

### 2. CRITICAL: Inconsistent Worker Pattern - Design Anti-Pattern

**Severity**: CRITICAL  
**Location**: `TerminalOperationWorker` vs `LauncherWorker`

#### Problem:

Two worker classes with fundamentally different design patterns:

**TerminalOperationWorker** (180 lines):
```python
class TerminalOperationWorker(QThread):  # ← Direct QThread inheritance (WRONG)
    def __init__(self, manager, operation, parent=None):
        super().__init__(parent)
        self.manager = manager  # ← Holds reference to manager
        self.command = ""
    
    def run(self):
        if self.operation == "health_check":
            self._run_health_check()
        elif self.operation == "send_command":
            self._run_send_command()
    
    def _run_health_check(self):
        # Accesses manager's PRIVATE methods with pyright suppressions
        if self.manager._is_dispatcher_healthy():  # pyright: ignore
            ...
        if self.manager._ensure_dispatcher_healthy(worker=self):  # pyright: ignore
            ...
```

**Issues**:
- Inherits QThread directly instead of ThreadSafeWorker (no state machine, no zombie protection)
- Accesses manager private methods (encapsulation violation)
- Phase 1 & 2 signal lifecycle embedded in worker logic
- No standardized lifecycle management
- Comments at lines 88-116 document thread-safety assumptions rather than enforcing them

**LauncherWorker** (296 lines):
```python
class LauncherWorker(ThreadSafeWorker):  # ← Inherits from ThreadSafeWorker (CORRECT)
    def do_work(self):
        # Proper lifecycle management through base class
        self._process = subprocess.Popen(...)
        # Drain threads for stdout/stderr
        self._stdout_thread = threading.Thread(...)
        ...
```

**Issues**:
- Has separate drain threads for stream handling (lines 268-280)
- Complex cleanup logic (lines 225-281)
- Requires explicit join on drain threads

#### Design Patterns Mismatch:

| Aspect | TerminalOperationWorker | LauncherWorker |
|--------|----------------------|-----------------|
| Base Class | QThread (direct) | ThreadSafeWorker |
| Lifecycle | Manual state tracking | Automated state machine |
| Zombie Protection | NONE | Yes (line 498-587) |
| Encapsulation | Accesses manager._private | Self-contained |
| Error Handling | Signal emission in do_work | Automatic via state machine |
| Stop Request Checking | Manual isInterruptionRequested() | self.should_stop() |

#### Root Cause:

TerminalOperationWorker was created before ThreadSafeWorker and never refactored. It represents a "legacy" pattern still in use.

#### Impact:

- **Inconsistency**: New developers must learn two worker patterns
- **Maintenance**: Bug fixes in ThreadSafeWorker don't apply to TerminalOperationWorker
- **Testing**: Two different test approaches required
- **Risk**: TerminalOperationWorker lacks zombie thread protection

#### Refactoring:

```python
# Option 1: Migrate TerminalOperationWorker to ThreadSafeWorker
class TerminalOperationWorker(ThreadSafeWorker):
    def do_work(self):
        if self.operation == "health_check":
            self._run_health_check()
        elif self.operation == "send_command":
            self._run_send_command()
    
    def _run_health_check(self):
        # Move signal emission to coordinator
        success = self.health_checker.is_healthy()
        self.operation_result.emit(success, "message")
```

**Effort Estimate**: 1-2 weeks (including tests)

---

### 3. CRITICAL: Complex Lock Hierarchy & Deadlock Risk

**Severity**: CRITICAL  
**Location**: `persistent_terminal_manager.py` (lines 256-268)

#### Lock Structure:

```python
self._write_lock = threading.RLock()    # RLock allows re-acquisition by same thread
self._state_lock = threading.Lock()     # Regular lock - NOT reentrant
self._restart_lock = threading.Lock()   # Serializes restart operations
```

#### Problematic Acquisition Sequences:

**Sequence 1: send_command() - Lines 892-914**
```python
def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    with self._state_lock:      # Lock 1
        fallback_mode = self._fallback_mode
    
    with self._write_lock:      # Lock 2
        if ensure_terminal:
            if not self._ensure_dispatcher_healthy():
                with self._state_lock:  # Lock 1 AGAIN (DEADLOCK if lock 1 is not reentrant!)
                    fallback_mode = self._fallback_mode
```

**Sequence 2: _ensure_dispatcher_healthy() - Lines 1131-1150**
```python
def _ensure_dispatcher_healthy(self, worker=None) -> bool:
    # Called from _write_lock context in send_command
    # Then acquires _restart_lock
    with self._restart_lock:           # Lock 3
        with self._state_lock:         # Lock 1 AGAIN
            if self._restart_attempts >= self._max_restart_attempts:
```

**Sequence 3: restart_terminal() - Lines 1345-1354**
```python
def restart_terminal(self, worker=None) -> bool:
    with self._restart_lock:           # Lock 3
        # Multiple _state_lock acquisitions (lines 1378, 1487)
        with self._state_lock:         # Lock 1 AGAIN
            pid_to_kill = self.terminal_pid
```

#### Deadlock Scenarios:

**Scenario 1**: Multiple threads in send_command
```
Thread A: _write_lock → _state_lock → _restart_lock → _state_lock AGAIN
Thread B: _state_lock → (waits for _write_lock held by A)
           → DEADLOCK if _state_lock not reentrant
```

**Scenario 2**: Worker thread interrupted during cleanup
- Lines 1470-1477 document: "DO NOT call terminate()"
- Indicates workers holding locks can cause deadlock during shutdown

#### Mitigation Comments in Code:

```python
# Line 256-260: "RLock allows re-acquisition by the same thread"
# Line 1441-1477: "CRITICAL: Workers must be stopped FIRST"
# Line 1494: "CRITICAL: Do NOT call methods that acquire locks"
```

These defensive comments indicate the design is fragile and error-prone.

#### Why This Design Is Problematic:

1. **RLock in _write_lock** masks the real issue (allows same thread re-acquisition)
2. **_state_lock is NOT reentrant** but acquired in sequences that cross thread boundaries
3. **_restart_lock adds another serialization point** with unclear ordering relative to other locks
4. **Cleanup code explicitly avoids locks** (line 1487) rather than properly coordinating

#### Impact:

- **Maintenance Risk**: Lock ordering changes can introduce subtle deadlocks
- **Testing**: Race conditions hard to detect and reproduce
- **Scalability**: Lock contention as more workers spawn
- **Correctness**: Comments indicate developers don't fully trust the locking strategy

#### Better Approach:

```python
# Option 1: Single comprehensive lock
class PersistentTerminalManager:
    def __init__(self):
        self._manager_lock = threading.RLock()  # Reentrant for safety
        
        # All state accessed under this single lock:
        self._terminal_pid = None
        self._dispatcher_pid = None
        self._restart_attempts = 0
        self._fallback_mode = False
        self._active_workers = []

# Option 2: Message queue pattern (async/await style)
class TerminalCommandQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
    
    async def send_command(self, cmd):
        await self.queue.put(cmd)

# Option 3: State machine with explicit transitions
class TerminalState:
    IDLE, RESTARTING, HEALTHY, UNHEALTHY = range(4)
```

**Effort Estimate**: 2-3 weeks (high risk, extensive testing required)

---

## High-Severity Architectural Issues

### 4. HIGH: CommandLauncher - Large Class with Mixed Concerns

**Severity**: HIGH  
**File**: `command_launcher.py` (998 lines)  
**Evidence**: 6 major responsibility areas

#### Responsibilities:

1. **Application Launching** (lines 531-822)
   - launch_app()
   - launch_app_with_scene()
   - launch_app_with_scene_context()

2. **Shot Context Management** (line 229-231)
   - set_current_shot()
   - Using self.current_shot throughout

3. **Scene File Discovery & Handling** (lines 612-667, 640-666, 824-900)
   - Latest 3DE scene finding
   - Latest Maya scene finding
   - Raw plate finding (lines 849-892)

4. **Nuke-Specific Logic** (lines 590-607, 675-691)
   - Delegates to NukeLaunchRouter
   - Environment fixes
   - Command preparation

5. **Environment & Command Building** (lines 700-717)
   - Rez environment wrapping
   - Workspace path validation
   - Logging redirection

6. **Signal Management & Error Handling** (lines 94-95, 147-173, 196-227)
   - 11+ signal connections tracked in list (lines 117, 128-142, 147-173)
   - Manual cleanup required (cleanup() method)
   - Fallback retry mechanism with pending queue (lines 113-114, 301-355)

#### Code Size Breakdown:

```
Lines 1-100:     Imports and LaunchContext definition
Lines 101-230:   __init__, timestamp property, cleanup methods
Lines 231-261:   Signal handlers (_on_execution_*) - 40 lines
Lines 262-299:   Command lifecycle handlers - 37 lines
Lines 300-356:   Fallback retry mechanism - 56 lines
Lines 357-530:   Template methods (_try_persistent_terminal, _launch_in_new_terminal, 
                  _execute_launch) - 173 lines
Lines 531-732:   launch_app() main method - 201 lines ← LARGEST
Lines 733-822:   launch_app_with_scene() - 89 lines
Lines 824-942:   launch_app_with_scene_context() - 118 lines
Lines 947-986:   _validate_workspace_before_launch() - 39 lines
Lines 990-998:   _emit_error() helper - 8 lines
```

#### Issues:

1. **Manual Signal Cleanup** (lines 196-227)
   ```python
   def cleanup(self) -> None:
       """Disconnect signals and cleanup resources."""
       if hasattr(self, "_signal_connections"):
           for connection in self._signal_connections:
               try:
                   QObject.disconnect(connection)
       # ... 10+ more lines
   ```
   - This is an antipattern; should use context managers or RAII
   - Indicates tight coupling to Qt signals

2. **Scene Finder Creation** (lines 177-185)
   ```python
   from maya_latest_finder import MayaLatestFinder
   from nuke_script_generator import NukeScriptGenerator
   from raw_plate_finder import RawPlateFinder
   from threede_latest_finder import ThreeDELatestFinder

   self._raw_plate_finder = RawPlateFinder()
   self._nuke_script_generator = NukeScriptGenerator()
   self._threede_latest_finder = ThreeDELatestFinder()
   self._maya_latest_finder = MayaLatestFinder()
   ```
   - Hard-coded dependencies (not injected)
   - Scene finding logic mixed with launching

3. **Fallback Retry Queue** (lines 301-356)
   ```python
   # Stores commands for potential fallback retry
   self._pending_fallback: dict[str, tuple[str, str, float]] = {}
   
   def _on_persistent_terminal_operation_finished(self, operation, success, message):
       if success:
           # Clean up old entries
           now = time.time()
           to_remove = []
           # ... 15+ lines of cleanup logic
       else:
           # Retry logic with FIFO queue selection
   ```
   - Complex queue management for fallback
   - Adds state that must be coordinated with signals

4. **Nuke Handler Integration** (line 124)
   ```python
   self.nuke_handler = NukeLaunchRouter()
   ```
   - Hard-coded dependency
   - Special-case logic for Nuke (lines 590-607, 675-691)

#### Refactoring Proposal:

```
CommandLauncher (coordinator) - 200 lines
├── delegates to ↓

ApplicationLauncher - 300 lines
├── launch_app()
├── launch_app_with_scene()
├── launch_app_with_scene_context()

ExecutionStrategySelector - 100 lines
├── _try_persistent_terminal()
├── _launch_in_new_terminal()
├── _execute_launch()

ScenePreparer - 150 lines
├── prepare_nuke_scene()
├── prepare_3de_scene()
├── prepare_maya_scene()
├── prepare_raw_plate()

EnvironmentBuilder - 100 lines
├── apply_rez_environment()
├── apply_nuke_fixes()
├── add_logging()
└── validate_workspace()

FallbackRetryManager - 80 lines
├── queue_for_retry()
├── process_retry()
└── cleanup_old_entries()
```

**Effort Estimate**: 2-3 weeks

---

### 5. HIGH: ProcessPoolManager - Mixed Concerns Singleton

**Severity**: HIGH  
**File**: `process_pool_manager.py` (773 lines)  
**Pattern**: Singleton with 5 distinct responsibilities

#### Responsibilities:

1. **Session Pooling** (lines 269-274, 391-450)
   - Round-robin session selection
   - Session creation management
   - Session type pools

2. **Command Caching** (lines 78-204)
   - Separate `CommandCache` class (126 lines)
   - TTL-based expiration
   - Cache statistics

3. **Metrics Collection** (lines 682-739)
   - Separate `ProcessMetrics` class (57 lines)
   - Response time tracking
   - Cache hit rates

4. **ThreadPoolExecutor Management** (lines 265-267, 554-659)
   - 5-stage shutdown sequence
   - Error handling with defensive try-catch blocks

5. **Batch Execution** (lines 391-450)
   - Parallel command execution
   - Futures-based coordination

#### Singleton Implementation Issues:

```python
def __new__(cls, max_workers: int = 4, sessions_per_type: int = 3):
    if cls._instance is None:
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.__init__(max_workers, sessions_per_type)
                cls._instance = instance
                cls._initialized = True
    return cls._instance

def __init__(self, max_workers: int = 4, sessions_per_type: int = 3):
    if hasattr(self, "_init_done") and self._init_done:
        return
    # ... initialization
    self._init_done = True
```

**Problems**:
- Manual __init__ call in __new__ (line 242) is unusual and error-prone
- Two flags tracking initialization state (_initialized in class, _init_done in instance)
- __init__ may still be called by Python after __new__ (line 249-260)

#### Mutex Type Inconsistency:

```python
# Line 216: Python's threading.Lock
_lock = threading.Lock()

# Line 276: Qt's QMutex
self._session_lock = QMutex()
self._mutex = QMutex()

# Line 92: CommandCache uses QMutex
self._lock = QMutex()
```

**Problem**: Mixing two mutex types suggests indecision about thread model

#### Shutdown Complexity:

```python
# 5 distinct stages (lines 554-659)
def shutdown(self, timeout: float = 5.0) -> None:
    # Stage 1: Clear session tracking
    # Stage 1.5: Clear session pools
    # Stage 2: Graceful executor shutdown
    # Stage 3: Clean up resources
    # Stage 5: Force garbage collection
```

- 8 separate try-catch blocks
- 3 different warning types
- Defensive gc.collect() call at end
- 100 lines for what should be simple cleanup

#### Impact:

- **Maintainability**: Complex singleton initialization
- **Testability**: Reset method required for test isolation (line 661-679)
- **Uncertainty**: Mixed mutex types suggest architectural uncertainty
- **Resource Leaks**: Complex shutdown indicates potential cleanup issues

#### Extraction Proposal:

```
ProcessPoolManager (Facade) - 150 lines
├── delegates to ↓

SessionPool - 200 lines
├── Round-robin selection
├── Creation management
├── Per-type tracking

CommandCache - 126 lines (already extracted, use as-is)

ProcessMetrics - 57 lines (already extracted, use as-is)

ExecutorManager - 150 lines
├── ThreadPoolExecutor lifecycle
├── Batch execution
├── Shutdown coordination
```

**Keep as Singleton**: ProcessPoolManager (facade only)  
**Make Plain Classes**: SessionPool, ExecutorManager

**Effort Estimate**: 1-2 weeks

---

## Medium-Severity Issues

### 6. MEDIUM: Tight Component Coupling

**Severity**: MEDIUM  
**Impact**: Hard to test, hard to extend

#### Coupling Points:

1. **CommandLauncher → Scene Finders** (lines 177-185)
   ```python
   self._raw_plate_finder = RawPlateFinder()
   self._nuke_script_generator = NukeScriptGenerator()
   ```
   - Should be injected or obtained from factory
   - Prevents using alternative implementations

2. **CommandLauncher → NukeLaunchRouter** (line 124)
   ```python
   self.nuke_handler = NukeLaunchRouter()
   ```
   - Hard-coded dependency
   - Can't test without Nuke handler

3. **PersistentTerminalManager → ProcessVerifier** (line 271)
   ```python
   self._process_verifier = ProcessVerifier(self.logger)
   ```
   - Created internally, not injected
   - Can't substitute test double

4. **CommandLauncher → ProcessExecutor → Config** (line 121)
   ```python
   self.process_executor = ProcessExecutor(persistent_terminal, Config)
   ```
   - Direct Config dependency (not injected)
   - Can't test different configurations

5. **ProcessPoolManager → CommandCache/ProcessMetrics** (lines 275, 277)
   ```python
   self._cache = CommandCache(default_ttl=30)
   self._metrics = ProcessMetrics()
   ```
   - Created internally
   - Should be dependency-injected for testing

#### Refactoring Approach:

```python
# Dependency injection pattern
class CommandLauncher:
    def __init__(
        self,
        persistent_terminal: PersistentTerminalManager | None = None,
        scene_finders: SceneFinderFactory | None = None,
        nuke_handler: NukeLaunchRouter | None = None,
        parent: QObject | None = None,
    ):
        self.persistent_terminal = persistent_terminal
        self._scene_finders = scene_finders or DefaultSceneFinderFactory()
        self._nuke_handler = nuke_handler or NukeLaunchRouter()

class ProcessPoolManager:
    def __init__(
        self,
        max_workers: int = 4,
        cache: CommandCache | None = None,
        metrics: ProcessMetrics | None = None,
    ):
        self._cache = cache or CommandCache()
        self._metrics = metrics or ProcessMetrics()
```

**Effort Estimate**: 1 week

---

### 7. MEDIUM: Test Isolation Concerns

**Severity**: MEDIUM  
**Location**: PersistentTerminalManager, ThreadSafeWorker, ProcessPoolManager

#### Issue 1: Class-Level Singleton Tracking (PersistentTerminalManager)

```python
# Lines 186-188
class PersistentTerminalManager:
    _test_instances: ClassVar[list[PersistentTerminalManager]] = []
    _test_instances_lock: ClassVar[threading.Lock] = threading.Lock()
    
    def __init__(self, ...):
        # Track instance for test cleanup
        with self.__class__._test_instances_lock:
            self.__class__._test_instances.append(self)
    
    @classmethod
    def cleanup_all_instances(cls) -> None:
        """Clean up all tracked instances (for test teardown)."""
        with cls._test_instances_lock:
            instances = list(cls._test_instances)
        
        for instance in instances:
            try:
                instance.cleanup()
```

**Problem**: Requires manual test cleanup hook

#### Issue 2: Zombie Thread Collection (ThreadSafeWorker)

```python
# Lines 81-88
class ThreadSafeWorker:
    _zombie_threads: ClassVar[list[ThreadSafeWorker]] = []
    _zombie_timestamps: ClassVar[dict[int, float]] = {}
    _zombie_mutex: ClassVar[QMutex] = QMutex()
    _zombie_cleanup_timer: ClassVar[QTimer | None] = None
```

**Problem**: Prevents garbage collection, requires periodic cleanup timer

#### Issue 3: ProcessPoolManager Reset (line 661-679)

```python
@classmethod
def reset(cls) -> None:
    """Reset singleton for testing. INTERNAL USE ONLY."""
    if cls._instance is not None:
        try:
            cls._instance.shutdown(timeout=2.0)
    with cls._lock:
        cls._instance = None
        cls._initialized = False
```

**Problem**: Singleton pattern requires special reset method for tests

#### Better Approach:

```python
# Use context manager pattern
@contextmanager
def temporary_terminal_manager():
    manager = PersistentTerminalManager()
    try:
        yield manager
    finally:
        manager.cleanup()

# Usage in tests
def test_something():
    with temporary_terminal_manager() as mgr:
        # test code
        pass  # Auto-cleanup
```

**Effort Estimate**: 1 week

---

### 8. MEDIUM: Signal/Slot Lifecycle Complexity

**Severity**: MEDIUM  
**Location**: CommandLauncher, PersistentTerminalManager

#### Issue 1: Manual Signal Tracking (CommandLauncher lines 117-173)

```python
self._signal_connections: list[QMetaObject.Connection] = []

# 11+ signal connections stored in list
self._signal_connections.append(
    self.process_executor.execution_progress.connect(...)
)
# ... 10 more
self._signal_connections.append(
    self.persistent_terminal.operation_finished.connect(...)
)

# Cleanup required
def cleanup(self) -> None:
    for connection in self._signal_connections:
        try:
            QObject.disconnect(connection)
        except (RuntimeError, TypeError):
            pass
```

**Problems**:
- Manual connection tracking is error-prone
- Cleanup can fail silently
- No guarantee all connections disconnected

#### Issue 2: Phase 1 & 2 Lifecycle (PersistentTerminalManager lines 200-204)

```python
# Emit lifecycle signals
command_queued = Signal(str, str)           # Phase 0: Queued
command_executing = Signal(str)             # Phase 1: Executing
command_verified = Signal(str, str)         # Phase 2: Verified
command_error = Signal(str, str)            # Phase 2: Error
command_result = Signal(bool, str)          # Backward compat
```

**Problems**:
- Multiple signal paths for success/failure
- Backward compat signal masks actual result
- Phase 1 & 2 coordination buried in worker code (lines 136-178)

#### Better Approach:

```python
# Single structured result signal
@dataclass
class CommandResult:
    command_id: str
    status: Literal["queued", "executing", "verified", "failed"]
    message: str
    timestamp: str
    process_pid: int | None = None

class PersistentTerminalManager(QObject):
    command_lifecycle = Signal(CommandResult)

# Usage
def send_command_async(self, command):
    cmd_id = str(uuid.uuid4())
    self.command_lifecycle.emit(
        CommandResult(cmd_id, "queued", command, self.timestamp)
    )
```

**Effort Estimate**: 2 weeks

---

## Summary: Issue Severity Matrix

| Issue | Severity | LOC | Root Cause | Effort |
|-------|----------|-----|-----------|--------|
| PersistentTerminalManager God Class | CRITICAL | 1,552 | Scope creep | 3-4w |
| TerminalOperationWorker Design | CRITICAL | 180 | Legacy pattern | 1-2w |
| Lock Hierarchy Deadlock Risk | CRITICAL | 256-268 | Over-complex sync | 2-3w |
| CommandLauncher Size/Coupling | HIGH | 998 | Mixed concerns | 2-3w |
| ProcessPoolManager Concerns | HIGH | 773 | Feature creep | 1-2w |
| Component Tight Coupling | MEDIUM | Various | No DI pattern | 1w |
| Test Isolation Anti-patterns | MEDIUM | Various | Manual cleanup | 1w |
| Signal/Slot Complexity | MEDIUM | Various | No structure | 2w |

---

## Recommended Improvement Plan

### Phase 1: Critical (4-6 weeks)

1. **Standardize Worker Pattern** (1-2w)
   - Migrate TerminalOperationWorker → ThreadSafeWorker
   - Consolidate worker test patterns
   - Benefits: Consistency, zombie thread protection, easier testing

2. **Simplify Lock Strategy** (2-3w) 
   - Evaluate single lock vs. message queue approach
   - Add comprehensive deadlock tests
   - Benefits: Eliminates deadlock risk, improves maintainability

### Phase 2: High Priority (3-4 weeks)

3. **Extract PersistentTerminalManager** (3-4w)
   - FIFOManager + TerminalProcessManager + HealthChecker + RecoveryManager
   - Each < 400 lines with single responsibility
   - Benefits: Testability, reusability, understandability

4. **Refactor CommandLauncher** (2-3w)
   - Extract: ApplicationLauncher, ExecutionStrategy, ScenePreparer, EnvironmentBuilder
   - Add dependency injection
   - Benefits: Smaller classes, easier testing, better separation of concerns

### Phase 3: Medium Priority (2-3 weeks)

5. **Consolidate Singletons** (1-2w)
   - ProcessPoolManager: keep facade, extract SessionPool/ExecutorManager
   - Use context managers for test isolation
   - Benefits: Cleaner initialization, better testability

6. **Improve Coupling** (1w)
   - Add dependency injection to all major classes
   - Create factory pattern for scene finders
   - Benefits: Better testability, easier to extend

7. **Signal Architecture** (2w)
   - Create structured result objects
   - Single unified lifecycle signal
   - Remove manual connection tracking
   - Benefits: Simpler to reason about, fewer silent failures

---

## Code Organization Recommendations

### Current Structure (Problems):
```
launcher/
├── worker.py (LauncherWorker)
├── process_manager.py (single class)
└── models.py (data models)

launch/
├── environment_manager.py
├── command_builder.py
└── process_executor.py

persistent_terminal_manager.py (GOD CLASS)
command_launcher.py (TOO LARGE)
process_pool_manager.py (TOO LARGE)
```

### Recommended Structure:
```
terminal/                          # New package
├── __init__.py
├── fifo_manager.py               # FIFO I/O (200 lines)
├── process_manager.py            # Terminal lifecycle (250 lines)
├── health_checker.py             # Health monitoring (200 lines)
├── recovery_manager.py           # Auto-recovery (200 lines)
├── orchestrator.py               # Coordinator (100 lines)
└── worker.py                     # TerminalOperationWorker (refactored)

launcher/                          # Expand existing
├── __init__.py
├── worker.py                      # (unchanged)
├── process_manager.py
├── application_launcher.py        # New: 300 lines
├── execution_strategy.py          # New: 100 lines
├── scene_preparer.py             # New: 150 lines
├── environment_builder.py        # New: 100 lines
├── fallback_manager.py           # New: 80 lines
├── models.py
├── validator.py
└── repository.py

process/                           # New package (refactored pool)
├── __init__.py
├── session_pool.py               # New: 200 lines
├── executor_manager.py           # New: 150 lines
├── cache.py                      # (move from process_pool_manager)
├── metrics.py                    # (move from process_pool_manager)
└── pool_manager.py               # Facade: 100 lines

command_launcher.py                # New structure: 200 lines (facade only)
```

---

## Testing Implications

### Current Test Challenges:

1. **PersistentTerminalManager** requires:
   - Mock terminal emulator
   - FIFO cleanup between tests
   - Class-level cleanup hook
   - Complex state initialization

2. **CommandLauncher** requires:
   - Mock all scene finders
   - Mock ProcessExecutor
   - Mock PersistentTerminalManager
   - Signal connection cleanup

3. **ProcessPoolManager** requires:
   - Singleton reset between tests
   - Executor shutdown handling
   - Session pool cleanup

### Improvements After Refactoring:

```python
# Better test structure
def test_fifo_manager_creation():
    """FIFO manager is testable in isolation."""
    mgr = FIFOManager("/tmp/test.fifo")
    try:
        assert mgr.create_fifo()
    finally:
        mgr.cleanup()

def test_health_checker():
    """Health checker with mock dispatcher."""
    checker = HealthChecker(dispatcher_checker=MockDispatcherChecker())
    assert not checker.is_healthy()  # Mock returns unhealthy

def test_launcher_with_injected_components():
    """Launcher with all dependencies injected."""
    launcher = ApplicationLauncher(
        scene_finder=MockSceneFinder(),
        environment_builder=MockEnvironmentBuilder(),
    )
    result = launcher.launch_app("nuke", LaunchContext())
    assert result == True
```

---

## Conclusion

The launcher/terminal system demonstrates sophisticated engineering in specific areas (thread safety, signal coordination, resource cleanup) but suffers from accumulation of complexity that makes it increasingly difficult to maintain and extend.

**Key Recommendations**:

1. **Immediately address Critical issues** (lock hierarchy, worker pattern) - these pose correctness risks
2. **Plan Phase 1-2 refactoring** over next 6-10 weeks
3. **Invest in comprehensive testing** during refactoring - this system is safety-critical
4. **Establish architectural guidelines** to prevent future complexity creep (max class size, max responsibilities per class, DI patterns)

The system is functional but approaching the complexity ceiling where further changes become increasingly risky.

