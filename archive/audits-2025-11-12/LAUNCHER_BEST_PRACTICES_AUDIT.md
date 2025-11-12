# Best Practices Audit: Terminal & App Launching System

**Audit Date**: 2025-11-11  
**Focus Areas**: persistent_terminal_manager.py, command_launcher.py, terminal_dispatcher.sh, launcher_manager.py

## Executive Summary

The terminal/app launching system demonstrates **modern Python patterns and solid architecture** with some **critical Qt lifecycle issues** and **performance concerns**. Overall compliance: **75/100**

### Key Findings:
- ✅ Modern type hints and PEP 563 compliance
- ✅ Proper error handling and subprocess management
- ✅ Thread-safe FIFO communication with locks
- ⚠️ Missing parent parameters on QObject subclasses
- ⚠️ Blocking UI operations (time.sleep in event loop)
- ⚠️ Significant code duplication in launch methods
- ⚠️ Shell script eval() without additional safety measures

---

## 1. Python Best Practices

### 1.1 VIOLATION: Missing Parent Parameter on QObject Subclasses

**Severity**: HIGH  
**Location**: 
- persistent_terminal_manager.py, line 39-48
- command_launcher.py, line 66-83

**Issue**:
Both classes inherit from QObject but don't accept a parent parameter in __init__, violating CLAUDE.md requirement:

```python
# ❌ WRONG - persistent_terminal_manager.py, line 39
def __init__(
    self, fifo_path: str | None = None, dispatcher_path: str | None = None
) -> None:
    super().__init__()  # No parent passed!

# ❌ WRONG - command_launcher.py, line 66
def __init__(
    self,
    raw_plate_finder: type[RawPlateFinderType] | None = None,
    # ... other params ...
) -> None:
    super().__init__()  # No parent passed!
```

**Impact**: 
- Qt object ownership issues in multi-parent scenarios
- Memory management complications
- Testing isolation problems (noted in CLAUDE.md singleton pattern requirements)

**Recommended Fix**:
```python
# ✅ CORRECT
def __init__(
    self, 
    fifo_path: str | None = None, 
    dispatcher_path: str | None = None,
    parent: QObject | None = None,  # ✅ ADD THIS
) -> None:
    super().__init__(parent)  # ✅ PASS PARENT
```

---

### 1.2 VIOLATION: Magic Numbers Instead of Named Constants

**Severity**: MEDIUM  
**Location**: persistent_terminal_manager.py, lines 69-70, 425, 433, 601, 671, 681, 705, 725

**Issue**:
Timeout and delay values scattered throughout without centralization:

```python
# ❌ WRONG - Magic numbers throughout
self._heartbeat_timeout: float = 60.0  # line 69
self._heartbeat_check_interval: float = 30.0  # line 70
time.sleep(0.5)  # line 425
timeout = 3.0  # line 433
time.sleep(0.5)  # line 601
time.sleep(0.5)  # line 671
time.sleep(0.5)  # line 681
time.sleep(0.5)  # line 705
timeout = 5.0  # line 725
```

**Impact**: 
- Maintenance difficulty when tuning timeouts
- Inconsistent delay values for similar operations
- No documented rationale for chosen values

**Recommended Fix**:
```python
# ✅ CORRECT - Class-level constants
class PersistentTerminalManager(LoggingMixin, QObject):
    # Timeout and delay constants (documented in docstring)
    HEARTBEAT_TIMEOUT = 60.0  # seconds
    HEARTBEAT_CHECK_INTERVAL = 30.0  # seconds
    TERMINAL_START_DELAY = 0.5  # seconds
    DISPATCHER_STARTUP_TIMEOUT = 3.0  # seconds
    RECOVERY_TIMEOUT = 5.0  # seconds
    POLL_INTERVAL = 0.1  # seconds
    FIFO_WRITE_RETRY_DELAY = 0.2  # seconds
    
    def __init__(self, ...):
        self._heartbeat_timeout = self.HEARTBEAT_TIMEOUT
        self._heartbeat_check_interval = self.HEARTBEAT_CHECK_INTERVAL
```

---

### 1.3 POSITIVE: Modern Type Hints and PEP 563 Compliance

**Status**: ✅ EXCELLENT  
**Location**: Throughout both files

**Observations**:
```python
# ✅ CORRECT - Modern union syntax (Python 3.10+)
fifo_path: str | None = None  # ✅ Not Optional[str]
terminal_pid: int | None = None
persistent_terminal: PersistentTerminalManager | None = None

# ✅ CORRECT - PEP 563 future imports
from __future__ import annotations

# ✅ CORRECT - TYPE_CHECKING pattern for circular imports
if TYPE_CHECKING:
    from persistent_terminal_manager import PersistentTerminalManager
```

---

### 1.4 POSITIVE: Pathlib Usage

**Status**: ✅ GOOD  
**Location**: persistent_terminal_manager.py, lines 19, 59, 98-102

**Observations**:
```python
# ✅ CORRECT - Pathlib instead of os.path
from pathlib import Path
module_dir = Path(__file__).parent
self.dispatcher_path = str(module_dir / "terminal_dispatcher.sh")
```

---

### 1.5 POSITIVE: Context Managers and Resource Cleanup

**Status**: ✅ GOOD  
**Location**: persistent_terminal_manager.py, lines 101-102, 351-356, 527-531

**Observations**:
```python
# ✅ CORRECT - contextlib.suppress for clean exception handling
with contextlib.suppress(FileNotFoundError):
    Path(self.fifo_path).unlink()

# ✅ CORRECT - Context manager for file operations
with os.fdopen(fd, "wb", buffering=0) as fifo:
    _ = fifo.write(command.encode("utf-8"))
    _ = fifo.write(b"\n")
```

---

## 2. Qt Best Practices

### 2.1 VIOLATION: Missing @Slot Decorators

**Severity**: MEDIUM  
**Location**: persistent_terminal_manager.py, command_launcher.py

**Issue**:
Methods that handle signals or are called from Qt connections lack @Slot decorators for performance optimization:

```python
# ❌ WRONG - No @Slot decorator
def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    """Send a command to the persistent terminal."""

def _launch_terminal(self) -> bool:
    """Launch the persistent terminal with dispatcher script."""

def restart_terminal(self) -> bool:
    """Restart the persistent terminal."""
```

**Impact**:
- Performance penalty: method lookups slower without @Slot optimization
- Qt doesn't recognize these as true slots for connection safety
- Thread safety assumptions may not be enforced

**Recommended Fix**:
```python
# ✅ CORRECT
from PySide6.QtCore import Slot

class PersistentTerminalManager(LoggingMixin, QObject):
    @Slot(str, bool)  # ✅ ADD DECORATOR
    def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
        """Send a command to the persistent terminal."""
    
    @Slot()  # ✅ ADD DECORATOR
    def restart_terminal(self) -> bool:
        """Restart the persistent terminal."""
```

---

### 2.2 VIOLATION: Blocking UI Operations (time.sleep in Event Loop)

**Severity**: HIGH  
**Location**: persistent_terminal_manager.py, lines 290-293, 425, 601, 671, 681, 705, 725-734

**Issue**:
send_command() and other methods use time.sleep() when called from UI thread, freezing the application:

```python
# ❌ WRONG - Blocks Qt event loop
if not self._send_command_direct("__HEARTBEAT__"):
    return False

# Poll for PONG response
start_time = time.time()
while (time.time() - start_time) < timeout:
    if self._check_heartbeat():
        return True
    time.sleep(0.1)  # ❌ FREEZES UI!

# Also in _launch_terminal():
time.sleep(0.5)  # ❌ UI FREEZE at line 425
while elapsed < timeout:
    # ...
    time.sleep(poll_interval)  # ❌ UI FREEZE
```

**Impact**:
- UI becomes unresponsive during terminal operations
- User perceives application as frozen/crashed
- Can trigger watchdog timeouts in VFX systems
- Makes UI-based testing unreliable

**Recommended Fix**:
```python
# ✅ CORRECT - Use QTimer instead of time.sleep()
from PySide6.QtCore import QTimer

class PersistentTerminalManager(LoggingMixin, QObject):
    heartbeat_ping = Signal()  # Add signal for heartbeat retry
    
    def _send_heartbeat_ping_async(self, timeout: float = 2.0) -> None:
        """Send heartbeat ping asynchronously using QTimer."""
        self._heartbeat_timer = QTimer()
        self._heartbeat_timer.setInterval(100)  # 100ms polling
        self._heartbeat_start = time.time()
        self._heartbeat_timeout_duration = timeout
        
        @self._heartbeat_timer.timeout.connect
        def check_heartbeat():
            if self._check_heartbeat():
                self._heartbeat_timer.stop()
                self.heartbeat_responded.emit()
            elif (time.time() - self._heartbeat_start) > self._heartbeat_timeout_duration:
                self._heartbeat_timer.stop()
                self.heartbeat_timeout.emit()
        
        # Send ping and start timer
        if self._send_command_direct("__HEARTBEAT__"):
            self._heartbeat_timer.start()
```

---

### 2.3 VIOLATION: No Signal/Slot Pattern for Recovery

**Severity**: MEDIUM  
**Location**: persistent_terminal_manager.py, lines 569-631

**Issue**:
Auto-recovery uses direct method calls instead of Qt signal/slot pattern:

```python
# ❌ WRONG - Direct method call, synchronous
if not self._ensure_dispatcher_healthy():
    return False

# Inside _ensure_dispatcher_healthy():
if not self.restart_terminal():  # ❌ Synchronous call
    self.logger.error("Failed to restart terminal")
    return False
```

**Recommended Fix**:
```python
# ✅ CORRECT - Use Qt signals for asynchronous recovery
class PersistentTerminalManager(LoggingMixin, QObject):
    recovery_requested = Signal()
    recovery_completed = Signal(bool)  # success
    
    @Slot()
    def _on_recovery_requested(self) -> None:
        """Handle recovery request asynchronously."""
        success = self.restart_terminal()
        self.recovery_completed.emit(success)
    
    def _ensure_dispatcher_healthy(self) -> bool:
        """Ensure dispatcher is healthy, requesting recovery if needed."""
        if self._is_dispatcher_healthy():
            return True
        
        # Emit signal for async recovery instead of blocking
        self.recovery_requested.emit()
        return False  # Or use a different pattern for async verification
```

---

## 3. Process Management Best Practices

### 3.1 POSITIVE: Proper Signal Handling

**Status**: ✅ EXCELLENT  
**Location**: persistent_terminal_manager.py, lines 595-607, terminal_dispatcher.sh lines 43-46

**Observations**:
```python
# ✅ CORRECT - Graceful shutdown with SIGTERM then SIGKILL
if self._is_terminal_alive() and self.terminal_pid:
    try:
        self.logger.debug(f"Force killing terminal process {self.terminal_pid}")
        os.kill(self.terminal_pid, signal.SIGTERM)
        time.sleep(0.5)
        if self._is_terminal_alive():
            os.kill(self.terminal_pid, signal.SIGKILL)
```

```bash
# ✅ CORRECT - Shell signal trapping
trap 'cleanup_and_exit 0 "Normal EXIT signal"' EXIT
trap 'cleanup_and_exit 1 "ERROR signal (command failed)"' ERR
trap 'cleanup_and_exit 130 "Caught SIGINT (Ctrl+C)"' INT
trap 'cleanup_and_exit 143 "Caught SIGTERM"' TERM
```

---

### 3.2 POSITIVE: Zombie Process Detection

**Status**: ✅ GOOD  
**Location**: persistent_terminal_manager.py, lines 225-226

**Observations**:
```python
# ✅ CORRECT - Check for zombie status
if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
    return True
```

---

### 3.3 POSITIVE: Non-blocking I/O for FIFO

**Status**: ✅ EXCELLENT  
**Location**: persistent_terminal_manager.py, lines 145, 352, 525

**Observations**:
```python
# ✅ CORRECT - Non-blocking operations prevent deadlocks
fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)

fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
```

---

### 3.4 POSITIVE: Thread-Safe FIFO Access

**Status**: ✅ EXCELLENT  
**Location**: persistent_terminal_manager.py, lines 80, 351-356, 517-531

**Observations**:
```python
# ✅ CORRECT - Lock for serializing FIFO writes
self._write_lock = threading.Lock()

# ✅ CORRECT - Lock usage prevents byte-level corruption
with self._write_lock:
    fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "wb", buffering=0) as fifo:
        _ = fifo.write(command.encode("utf-8"))
        _ = fifo.write(b"\n")
```

---

## 4. Shell Script Best Practices

### 4.1 POSITIVE: Error Handling with pipefail and Signal Traps

**Status**: ✅ EXCELLENT  
**Location**: terminal_dispatcher.sh, lines 2, 43-46

**Observations**:
```bash
#!/bin/bash
set -o pipefail  # ✅ Capture exit codes in pipelines

# ✅ CORRECT - Comprehensive signal handling
trap 'cleanup_and_exit 0 "Normal EXIT signal"' EXIT
trap 'cleanup_and_exit 1 "ERROR signal (command failed)"' ERR
trap 'cleanup_and_exit 130 "Caught SIGINT (Ctrl+C)"' INT
trap 'cleanup_and_exit 143 "Caught SIGTERM"' TERM
```

---

### 4.2 VIOLATION: Missing set -u (Undefined Variables)

**Severity**: LOW  
**Location**: terminal_dispatcher.sh, line 2

**Issue**:
Script doesn't use `set -u` to error on undefined variables:

```bash
# ❌ WRONG - Missing set -u
#!/bin/bash
set -o pipefail

# This would silently fail with undefined $UNDEFINED_VAR:
echo "Value: $UNDEFINED_VAR"  # No error!
```

**Recommended Fix**:
```bash
# ✅ CORRECT
#!/bin/bash
set -o pipefail
set -u  # ✅ ADD THIS - Error on undefined variables
set -e  # Already implemented via ERR trap, but explicit is clearer
```

---

### 4.3 VIOLATION: eval() Without Explicit Safety Documentation

**Severity**: MEDIUM  
**Location**: terminal_dispatcher.sh, lines 205, 214

**Issue**:
Uses eval for command execution without documented security assumptions:

```bash
# ⚠️ CAUTION - eval() used, but pre-validated in Python
eval "$cmd &"  # Line 205
eval "$cmd"    # Line 214
```

**Note**: This is mitigated by Python-side validation in command_launcher.py `_validate_path_for_shell()`, but should be documented.

**Recommended Fix**:
```bash
# Add explicit security comment
log_info "Executing command (pre-validated by Python): $cmd"
eval "$cmd"
```

**Documentation needed**: Add comment explaining that commands are validated in Python's `_validate_path_for_shell()`.

---

### 4.4 VIOLATION: Fragile Command Parsing in is_gui_app()

**Severity**: LOW  
**Location**: terminal_dispatcher.sh, lines 85-126

**Issue**:
GUI app detection uses regex parsing that could fail with unusual command structures:

```bash
# ⚠️ FRAGILE - Regex-based parsing
if [[ "$cmd" =~ bash[[:space:]]+-[^\"]*\"(.*)\" ]]; then
    local inner_cmd="${BASH_REMATCH[1]}"
    if [[ "$inner_cmd" == *"&&"* ]]; then
        local last_segment="${inner_cmd##*&&}"
        local actual_cmd="${last_segment%% *}"
        case "$actual_cmd" in
            nuke|maya|rv|3de|...)
                return 0
                ;;
        esac
    fi
fi
```

**Impact**:
- Unusual quote styles could break parsing
- Complex command chains might not parse correctly
- New apps require script modification

**Recommended Fix**:
Pass GUI app indicator as environment variable from Python instead of parsing:

```python
# command_launcher.py - Pass GUI flag in environment
os.environ['SHOTBOT_IS_GUI_APP'] = 'true' if is_gui else 'false'
self.persistent_terminal.send_command(full_command)
```

```bash
# terminal_dispatcher.sh - Check environment variable
if [ "${SHOTBOT_IS_GUI_APP:-false}" = "true" ]; then
    eval "$cmd &"
else
    eval "$cmd"
fi
```

---

## 5. Code Quality & Maintainability

### 5.1 VIOLATION: Significant Code Duplication

**Severity**: MEDIUM  
**Location**: command_launcher.py, lines 259-549, 550-747, 749-973

**Issue**:
Three nearly identical launch methods with ~90% duplicate code:

```python
# ❌ WRONG - Three separate implementations
def launch_app(self, app_name: str, ...) -> bool:
    # ~290 lines of launch logic

def launch_app_with_scene(self, app_name: str, scene: ThreeDEScene) -> bool:
    # ~200 lines, ~90% duplicate from launch_app

def launch_app_with_scene_context(self, app_name: str, scene: ThreeDEScene, ...) -> bool:
    # ~225 lines, ~90% duplicate from launch_app
```

Common blocks appear in all three:
- Workspace validation (lines 292-295, 584-585, 827-828)
- Nuke/Maya/3DE app-specific handling (lines 320-376, 349-376, 773-824)
- Command building with rez wrapping (lines 378-429, 587-631, 830-857)
- Terminal detection and execution (lines 475-549, 674-747, 900-973)

**Impact**:
- 250+ lines of duplicate code to maintain
- Bug fixes must be applied in three places
- High risk of inconsistency between methods

**Recommended Fix**:
```python
# ✅ CORRECT - Extract common logic
def _prepare_launch_context(
    self,
    app_name: str,
    shot: Shot | None = None,
    scene: ThreeDEScene | None = None,
    include_raw_plate: bool = False,
) -> tuple[str, bool]:
    """Prepare common launch context (command, is_gui).
    
    Extracted from launch_app* methods to reduce duplication.
    """
    # Workspace validation
    workspace_path = scene.workspace_path if scene else shot.workspace_path
    if not self._validate_workspace_before_launch(workspace_path, app_name):
        return "", False
    
    # Command building
    command = self._build_app_command(
        app_name, shot, scene, include_raw_plate
    )
    
    # Rez wrapping
    if self._is_rez_available():
        command = self._wrap_with_rez(command, app_name)
    
    # Logging
    command = self._add_dispatcher_logging(command)
    
    is_gui = self._is_gui_app(app_name)
    return command, is_gui

def launch_app(self, app_name: str, ...) -> bool:
    """Launch app - public API."""
    command, is_gui = self._prepare_launch_context(
        app_name, shot=self.current_shot, ...
    )
    return self._execute_command(command, is_gui)

def launch_app_with_scene(self, app_name: str, scene: ThreeDEScene) -> bool:
    """Launch app with scene - public API."""
    command, is_gui = self._prepare_launch_context(
        app_name, scene=scene, ...
    )
    return self._execute_command(command, is_gui)
```

---

### 5.2 VIOLATION: Hardcoded Application Lists

**Severity**: LOW  
**Location**: command_launcher.py, lines 985-994, terminal_dispatcher.sh lines 110-111

**Issue**:
Application names repeated in multiple places without centralization:

```python
# ❌ WRONG - Hardcoded in command_launcher.py
gui_apps = {
    "3de", "nuke", "maya", "rv", "houdini", "mari", "katana", "clarisse",
}

# ❌ WRONG - Also hardcoded in shell script
case "$actual_cmd" in
    nuke|maya|rv|3de|houdini|katana|mari|clarisse)
        return 0 ;;
esac
```

**Recommended Fix**:
```python
# config.py - Centralize application configuration
GUI_APPLICATIONS = {
    "3de", "nuke", "maya", "rv", "houdini", "mari", "katana", "clarisse",
}

# command_launcher.py
def _is_gui_app(self, app_name: str) -> bool:
    return app_name.lower() in Config.GUI_APPLICATIONS
```

Then pass the list to the shell script or use environment variables.

---

### 5.3 POSITIVE: Excellent Documentation

**Status**: ✅ EXCELLENT  
**Location**: Throughout both files

**Observations**:
```python
# ✅ CORRECT - Comprehensive docstrings
def _ensure_dispatcher_healthy(self) -> bool:
    """Comprehensive health check for dispatcher.

    Uses multiple checks:
    1. Dispatcher process exists and is running
    2. FIFO has a reader (existing check)
    3. Heartbeat response (if enabled)

    Returns:
        True if dispatcher appears healthy, False otherwise
    """

def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    """Send a command to the persistent terminal.

    Args:
        command: The command to execute
        ensure_terminal: Whether to launch terminal if not running

    Returns:
        True if command was sent successfully, False otherwise
    """
```

---

### 5.4 POSITIVE: Comprehensive Error Handling

**Status**: ✅ EXCELLENT  
**Location**: command_launcher.py, lines 504-548

**Observations**:
```python
# ✅ CORRECT - Specific exception handling
except FileNotFoundError as e:
    filename_not_found: str = _safe_filename_str(cast("str | bytes | int | None", e.filename))
    self._emit_error(...)

except PermissionError as e:
    filename_perm: str = _safe_filename_str(cast("str | bytes | int | None", e.filename))
    self._emit_error(...)

except OSError as e:
    if e.errno == errno.EACCES:
        msg = "Permission denied - check file permissions"
    elif e.errno == errno.ENOSPC:
        msg = "No space left on device"
    # ... etc
```

---

## 6. Summary Table

| Category | Finding | Severity | Location |
|----------|---------|----------|----------|
| Qt Lifecycle | Missing parent parameter on QObject | HIGH | persistent_terminal_manager.py:39, command_launcher.py:66 |
| Qt Performance | Missing @Slot decorators | MEDIUM | Both files, multiple methods |
| UI Responsiveness | Blocking time.sleep() in event loop | HIGH | persistent_terminal_manager.py:290-734 |
| Code Organization | Code duplication in launch_app* | MEDIUM | command_launcher.py:259-973 |
| Configuration | Magic numbers without constants | MEDIUM | persistent_terminal_manager.py:69-725 |
| Configuration | Hardcoded app names | LOW | command_launcher.py:985, terminal_dispatcher.sh:110 |
| Shell Script | Missing set -u | LOW | terminal_dispatcher.sh:2 |
| Shell Script | Fragile command parsing | LOW | terminal_dispatcher.sh:85-126 |
| Documentation | Excellent overall | ✅ POSITIVE | Throughout |
| Type Safety | Modern type hints, PEP 563 | ✅ POSITIVE | Throughout |
| Process Management | Signal handling, thread safety | ✅ POSITIVE | Throughout |

---

## 7. Compliance Checklist vs CLAUDE.md

| Requirement | Status | Notes |
|-------------|--------|-------|
| Qt parent parameter required | ❌ FAIL | Both classes need parent parameter |
| Type hints (3.11+) | ✅ PASS | Modern union syntax used throughout |
| Pathlib for paths | ✅ PASS | Used throughout |
| Context managers | ✅ PASS | FIFO operations properly wrapped |
| PEP 8 compliance | ✅ PASS | Code follows PEP 8 |
| f-strings | ✅ PASS | Used throughout, no old formatting |
| Error handling | ✅ PASS | Comprehensive try-except blocks |
| Singleton reset() | N/A | Not singletons (good design choice) |
| @Slot decorators | ⚠️ PARTIAL | Methods not decorated for performance |

---

## 8. Recommended Priority Actions

### CRITICAL (Do First - Blocks Testing)
1. Add parent parameter to PersistentTerminalManager and CommandLauncher
2. Replace time.sleep() polling with QTimer-based async operations
3. Fix code duplication in launch_app* methods

### HIGH (Do Second - Improves Performance)
1. Add @Slot decorators to all Qt-connected methods
2. Extract timeout constants to class attributes
3. Refactor is_gui_app() to use environment variables instead of shell parsing

### MEDIUM (Do Third - Code Quality)
1. Add set -u to shell script
2. Centralize application list in config.py
3. Document eval() security assumptions

### LOW (Nice to Have - Polish)
1. Add shell function docs for is_gui_app()
2. Consider factory pattern for terminal detection

