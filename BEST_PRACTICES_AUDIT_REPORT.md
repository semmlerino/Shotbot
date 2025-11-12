# Shotbot Best Practices Audit Report

**Date:** 2025-11-12  
**Scope:** Controllers, Core, Launcher modules + Manager singletons  
**Focus:** Modern Python 3.11+ patterns, Qt/PySide6 best practices, KISS/DRY principles

---

## Executive Summary

**Overall Score:** 82/100

The codebase demonstrates strong foundational practices with excellent type safety (0 errors/warnings in basedpyright) and solid Qt threading patterns. However, there are opportunities to further align with modern Python idioms and simplify complex patterns. Key areas for improvement:

- DRY violations in repetitive validation and security patterns
- Overly complex mutex locking strategies that could be simplified
- Inconsistent error handling patterns
- Some redundant type checking that modern type hints could eliminate

**Impact Distribution:**
- High impact (5 findings): 3 violations
- Medium impact (12 findings): 7 violations  
- Low impact (8 findings): 5 violations

---

## Critical Findings (High Impact)

### 1. DRY Violation: Duplicated Security Pattern Validation

**Files:** 
- `/home/gabrielh/projects/shotbot/launcher/validator.py` (lines 49-59, 103-122, 137-160)

**Issue:** Security pattern validation is implemented three separate times with redundant logic:

```python
# Pattern 1: Line 49-59 (basic patterns list)
self.security_patterns: list[str] = [
    "rm -rf", "sudo rm", "rm /", "format c:", ...
]

# Pattern 2: Line 103-122 (iterate through patterns)
def _validate_security(self, command: str) -> list[str]:
    for pattern in self.security_patterns:
        if pattern in cmd_lower:
            errors.append(...)

# Pattern 3: Line 137-160 (duplicate regex patterns)
dangerous_patterns = [
    r"\brm\s+-rf\s+/", r"\brm\s+.*\*", ...
]
for pattern in dangerous_patterns:
    if re.search(pattern, cmd_lower):
        return False, f"Command contains dangerous pattern: {pattern}"
```

**Modern Alternative:**

```python
from dataclasses import dataclass
from enum import Enum

@dataclass
class SecurityPattern:
    pattern: str
    pattern_type: str  # "literal" or "regex"
    severity: str  # "critical" or "warning"
    description: str

class SecurityValidator:
    DANGEROUS_PATTERNS: ClassVar[list[SecurityPattern]] = [
        SecurityPattern(
            pattern=r"\brm\s+-rf\s+/",
            pattern_type="regex",
            severity="critical",
            description="Recursive deletion of root"
        ),
        # ... single source of truth
    ]
    
    def validate_security(self, command: str) -> list[str]:
        """Single unified validation method."""
        errors: list[str] = []
        cmd_lower = command.lower()
        
        for sec_pattern in self.DANGEROUS_PATTERNS:
            match_func = (
                re.search if sec_pattern.pattern_type == "regex"
                else lambda p, t: p in t
            )
            if match_func(sec_pattern.pattern, cmd_lower):
                errors.append(
                    f"{sec_pattern.severity}: {sec_pattern.description}"
                )
                break
        
        return errors
```

**Impact:** High - Maintenance nightmare, security patterns out of sync  
**Effort:** Medium - Requires consolidating validation logic  
**Priority:** High

---

### 2. Overly Complex Mutex Locking Strategy

**Files:** 
- `/home/gabrielh/projects/shotbot/launcher/process_manager.py` (lines 51-72, 194-251, 470-553)

**Issue:** Excessive mutex complexity with multiple lock types, making code harder to understand and maintain:

```python
# Multiple different mutex types and locking patterns
self._process_lock = QRecursiveMutex()  # For nested locking
self._cleanup_lock = QMutex()  # For cleanup coordination
self._cleanup_in_progress = False  # Manual flag tracking
self._cleanup_scheduled = False  # Another flag

# Inconsistent usage patterns
with QMutexLocker(self._process_lock):
    self._active_processes[process_key] = process_info

# Later, manual lock/unlock
with QMutexLocker(self._cleanup_lock):
    self._cleanup_scheduled = False
```

**Modern Alternative (KISS Principle):**

```python
from dataclasses import dataclass
from threading import Lock

@dataclass
class ProcessTracker:
    """Single responsibility: track process lifecycle."""
    active_processes: dict[str, ProcessInfo]
    active_workers: dict[str, LauncherWorker]
    lock: Lock = field(default_factory=Lock)
    
    def add_process(self, key: str, info: ProcessInfo) -> None:
        """Thread-safe process addition."""
        with self.lock:
            self._active_processes[key] = info
    
    def get_processes_snapshot(self) -> dict[str, ProcessInfo]:
        """Get safe snapshot without exposing locks."""
        with self.lock:
            return dict(self._active_processes)

# Simpler class that delegates to ProcessTracker
class LauncherProcessManager:
    def __init__(self):
        self._tracker = ProcessTracker({}, {})
        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(self.CLEANUP_INTERVAL_MS)
```

**Impact:** High - Code complexity, maintenance burden  
**Effort:** High - Requires significant refactoring  
**Priority:** High - Improves maintainability significantly

---

### 3. Inconsistent Signal/Slot Connection Pattern

**Files:**
- `/home/gabrielh/projects/shotbot/launcher/process_manager.py` (lines 175-188)
- `/home/gabrielh/projects/shotbot/controllers/launcher_controller.py` (lines 111-141)

**Issue:** Inconsistent connection types - some use `Qt.ConnectionType.QueuedConnection` explicitly, others rely on defaults:

```python
# Inconsistent Pattern A: Explicit type with type annotation
_ = worker.command_started.connect(
    on_started,
    Qt.ConnectionType.QueuedConnection,  # ✓ Modern explicit
)

# Inconsistent Pattern B: No type specification (relying on default)
_ = self.window.launcher_panel.app_launch_requested.connect(self.launch_app)
_ = self.window.command_launcher.command_executed.connect(
    self.window.log_viewer.add_command
)
```

**Modern Best Practice:**

```python
# Unified pattern: Always explicit for clarity
from PySide6.QtCore import Qt

class ProcessManager(QObject):
    def __init__(self):
        super().__init__()
        self._setup_signals()
    
    def _setup_signals(self) -> None:
        """Setup all signal connections with explicit connection types."""
        # Define connection type once
        _QUEUED = Qt.ConnectionType.QueuedConnection
        _UNIQUE = Qt.ConnectionType.UniqueConnection
        
        # Apply consistently
        _ = self.worker.started.connect(
            self._on_worker_started,
            type=_QUEUED,
        )
        _ = self.worker.finished.connect(
            self._on_worker_finished,
            type=_QUEUED | _UNIQUE,
        )
```

**Impact:** High - Thread safety not obvious, maintenance risk  
**Effort:** Medium - Search and update all signal connections  
**Priority:** High

---

## Major Findings (Medium Impact)

### 4. Verbose Exception Handling with Bare `except Exception`

**Files:**
- `/home/gabrielh/projects/shotbot/launcher/validator.py` (lines 155-159, 193-194, 278-296)
- `/home/gabrielh/projects/shotbot/cache_manager.py` - Throughout

**Issue:** Overly broad exception catching masks specific error types:

```python
# Too broad - catches everything
try:
    if re.search(pattern, cmd_lower):
        return False, f"Command contains dangerous pattern: {pattern}"
except re.error:
    self.logger.warning(f"Invalid regex pattern: {pattern}")
except Exception as e:  # Also too broad
    return False, f"Command validation failed: {e}"

# Later in same function:
try:
    _ = template.safe_substitute({})
except ValueError as e:
    return False, f"Invalid template syntax: {e}"
except Exception as e:  # Catches things meant for ValueError
    return False, f"Command validation failed: {e}"
```

**Modern Best Practice:**

```python
def validate_command_syntax(self, command: str) -> tuple[bool, str | None]:
    """Validate with specific exception types."""
    if not command:
        return False, "Command cannot be empty"
    
    # Specific exception handling per operation
    security_errors = self._validate_security_patterns(command)
    if security_errors:
        return False, security_errors[0]
    
    # Separate try block for template validation
    try:
        template = string.Template(command)
        _ = template.safe_substitute({})
        return True, None
    except ValueError as e:
        return False, f"Invalid template syntax: {e}"
    # Don't catch Exception - let unexpected errors propagate
```

**Impact:** Medium - Makes debugging harder  
**Effort:** Low - Search and be more specific  
**Priority:** Medium

---

### 5. Inefficient Dictionary Access Pattern

**Files:**
- `/home/gabrielh/projects/shotbot/launcher/validator.py` (lines 65-91)
- `/home/gabrielh/projects/shotbot/controllers/launcher_controller.py` (lines 200-218)

**Issue:** Manually constructing dicts when modern Python offers better patterns:

```python
# Verbose pattern - manual construction
app_options: dict[str, list[str]] = {
    "nuke": [
        "include_raw_plate",
        "open_latest_scene",
        "create_new_file",
    ],
    "3de": ["open_latest_threede"],
    "maya": ["open_latest_maya"],
}

options: dict[str, bool] = {}
for option in app_options.get(app_name, []):
    options[option] = self.window.launcher_panel.get_checkbox_state(
        app_name, option
    )
```

**Modern Alternative:**

```python
from typing import TypedDict

class AppOptions(TypedDict):
    nuke: list[str]
    threede: list[str]
    maya: list[str]

# Option 1: Dictionary comprehension (more concise)
options = {
    option: self.window.launcher_panel.get_checkbox_state(app_name, option)
    for option in APP_OPTIONS.get(app_name, [])
}

# Option 2: Use dataclass for configuration (more scalable)
@dataclass(frozen=True)
class AppLaunchConfig:
    app_name: str
    required_options: list[str]
    
    def get_selected_options(self, panel: LauncherPanel) -> dict[str, bool]:
        return {
            opt: panel.get_checkbox_state(self.app_name, opt)
            for opt in self.required_options
        }

APP_CONFIGS = {
    "nuke": AppLaunchConfig("nuke", [...]),
    "3de": AppLaunchConfig("3de", [...]),
}
```

**Impact:** Medium - Code readability, maintainability  
**Effort:** Low - Simple refactoring  
**Priority:** Medium

---

### 6. Repetitive Null/None Checking

**Files:**
- `/home/gabrielh/projects/shotbot/controllers/launcher_controller.py` (lines 262-286, 426-452)
- `/home/gabrielh/projects/shotbot/launcher/process_manager.py` (throughout)

**Issue:** Inconsistent and verbose None checks that could use modern guards:

```python
# Pattern 1: Nested ifs
if not self.window.command_launcher.current_shot:
    if self._current_shot:
        # Re-sync
        self.window.command_launcher.set_current_shot(self._current_shot)
    else:
        # No context
        self.logger.error("No shot or scene context available for launch")
        return

# Pattern 2: Multiple checks for same thing
shot = current_shot
if not shot:
    ...
if shot is not None:
    ...
```

**Modern Best Practice:**

```python
# Use match statement (Python 3.10+)
def get_launch_context(self) -> Shot | None:
    match (self._current_scene, self._current_shot):
        case (None, None):
            self.logger.error("No shot or scene context available")
            return None
        case (scene, _) if scene is not None:
            # Scene context takes precedence
            return Shot.from_scene(scene)
        case (_, shot) if shot is not None:
            return shot
        case _:
            return None

# Or use union operators for cleaner guard clauses
def launch_app(self, app_name: str) -> None:
    context = self._current_scene or self._current_shot
    if not context:
        self._handle_no_context()
        return
    
    # context is guaranteed to be non-None here
    self._perform_launch(context, app_name)
```

**Impact:** Medium - Readability, modern Python idioms  
**Effort:** Low - Refactoring existing checks  
**Priority:** Medium

---

### 7. Missing Type Aliases for Complex Types

**Files:**
- `/home/gabrielh/projects/shotbot/launcher/config_manager.py` (lines 20-27)
- `/home/gabrielh/projects/shotbot/launcher/models.py` (throughout)

**Issue:** Complex nested type annotations repeated without TypeAlias:

```python
# Repeated throughout
dict[str, dict[str, str | dict[str, str | bool | list[str] | None] | list[str]]]

# In ConfigData
launchers: dict[
    str, dict[str, str | dict[str, str | bool | list[str] | None] | list[str]]
]
```

**Modern Best Practice:**

```python
from typing import TypeAlias

# Define once at module level
LauncherDict: TypeAlias = dict[str, str | dict[str, str | bool | list[str] | None] | list[str]]
LauncherConfigDict: TypeAlias = dict[str, LauncherDict]

class ConfigData(TypedDict):
    version: str
    launchers: LauncherConfigDict
    terminal_preferences: list[str]

# Usage is cleaner
def load_launchers(self) -> dict[str, CustomLauncher]:
    with self.config_file.open() as f:
        data: ConfigData = json.load(f)
        launchers: LauncherConfigDict = data.get("launchers", {})
```

**Impact:** Medium - Type safety, readability  
**Effort:** Low - Define TypeAliases  
**Priority:** Low

---

### 8. Inefficient Resource Cleanup Pattern

**Files:**
- `/home/gabrielh/projects/shotbot/launcher/process_manager.py` (lines 242-251, 538-545)
- `/home/gabrielh/projects/shotbot/launcher/worker.py` (lines 242-255)

**Issue:** Repetitive signal disconnection with try/except patterns:

```python
# Pattern repeated 3+ times
try:
    _ = worker.command_started.disconnect()
    _ = worker.command_finished.disconnect()
    _ = worker.command_error.disconnect()
except (RuntimeError, TypeError):
    # Signals may already be disconnected
    pass
```

**Modern Best Practice:**

```python
def _disconnect_worker_signals(self, worker: LauncherWorker) -> None:
    """Safely disconnect all worker signals (DRY)."""
    signals = [
        worker.command_started,
        worker.command_finished,
        worker.command_error,
    ]
    for signal in signals:
        try:
            _ = signal.disconnect()
        except (RuntimeError, TypeError):
            pass  # Already disconnected

# Usage (simpler)
def _on_worker_finished(self, worker_key: str, ...) -> None:
    if worker := self._active_workers.get(worker_key):
        self._disconnect_worker_signals(worker)
        del self._active_workers[worker_key]
```

**Impact:** Medium - Code duplication  
**Effort:** Low - Extract to helper method  
**Priority:** Low

---

### 9. Missing Context Manager for File Operations

**Files:**
- `/home/gabrielh/projects/shotbot/launcher/config_manager.py` (lines 66-86)

**Issue:** Manual resource management when context managers are available:

```python
# Modern but could be cleaner
with self.config_file.open() as f:
    data = cast(
        "dict[str, str | dict[...]",
        json.load(f),
    )
```

**Alternative with Error Context:**

```python
def load_launchers(self) -> dict[str, CustomLauncher]:
    """Load launchers with proper error context."""
    launchers: dict[str, CustomLauncher] = {}
    
    if not self.config_file.exists():
        return launchers
    
    try:
        with self.config_file.open() as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        self.logger.error(f"Failed to load config from {self.config_file}: {e}")
        return launchers
    
    # Process data...
    return launchers
```

**Impact:** Medium - Could be more pythonic  
**Effort:** Low  
**Priority:** Low

---

## Minor Findings (Low Impact)

### 10. Inconsistent Underscore Usage for Unused Return Values

**Files:**
- `/home/gabrielh/projects/shotbot/controllers/launcher_controller.py` (lines 111-141, 500-514)
- `/home/gabrielh/projects/shotbot/launcher/process_manager.py` (lines 65-66, 130-131)

**Issue:** Mixing `_ =` assignments and just not capturing return values:

```python
# Pattern A: Capture to underscore
_ = self.window.launcher_panel.app_launch_requested.connect(self.launch_app)

# Pattern B: Don't capture at all  
self.window.command_launcher.command_error.connect(self._on_command_error)

# Pattern C: Use underscore for lambda parameter
_ = action.triggered.connect(
    lambda _=False,
    lid=launcher.id: self.execute_custom_launcher(lid),
)
```

**Modern Best Practice (PEP 8):**

```python
# Be consistent - use one style throughout
# For Qt signals, the return value (signal connection object) is rarely used
# but it's good practice to capture it for debugging/testing

def _setup_signals(self) -> None:
    """Setup signal connections with consistent style."""
    # Capture if debugging is enabled
    connection_ids: list[Any] = []
    
    if self.DEBUG:
        # Store connections for debugging
        connection_ids.append(
            self.launcher_panel.app_launch_requested.connect(self.launch_app)
        )
    else:
        # Just connect without capturing
        self.launcher_panel.app_launch_requested.connect(self.launch_app)
    
    # Or consistently use underscore for clarity
    _ = self.launcher_manager.launchers_changed.connect(
        self.update_launcher_menu
    )
```

**Impact:** Low - Style consistency  
**Effort:** Minimal - Use linting rules  
**Priority:** Low

---

### 11. Hardcoded Constants that Could be Configuration

**Files:**
- `/home/gabrielh/projects/shotbot/launcher/process_manager.py` (lines 45-49)
- `/home/gabrielh/projects/shotbot/cache_manager.py` (lines 78-81)

**Issue:** Magic numbers embedded in code:

```python
# In process_manager.py
CLEANUP_INTERVAL_MS = 5000
CLEANUP_RETRY_DELAY_MS = 2000
PROCESS_STARTUP_TIMEOUT_MS = ThreadingConfig.SUBPROCESS_TIMEOUT * 1000

# Better approach: Config dataclass
@dataclass(frozen=True)
class ProcessManagerConfig:
    cleanup_interval_ms: int = 5000
    cleanup_retry_delay_ms: int = 2000
    process_startup_timeout_ms: int = 30000
```

**Impact:** Low - Configuration flexibility  
**Effort:** Low  
**Priority:** Low

---

### 12. Missing Protocol Usage for Interfaces

**Files:**
- `/home/gabrielh/projects/shotbot/controllers/launcher_controller.py` (lines 51-64)

**Finding:** This is actually WELL DONE! LauncherTarget protocol is excellent example:

```python
class LauncherTarget(Protocol):
    """Protocol defining the interface required by LauncherController."""
    command_launcher: CommandLauncher | SimplifiedLauncher
    launcher_manager: LauncherManager | None
    launcher_panel: LauncherPanel
    log_viewer: LogViewer
    status_bar: QStatusBar
    
    def update_status(self, message: str) -> None: ...
```

**Improvement:** More modules could use this pattern.

---

## Qt/PySide6 Best Practices - Findings

### 13. Modern Qt Enum Syntax Usage

**Files:**
- `/home/gabrielh/projects/shotbot/launcher/process_manager.py` (lines 175-177)

**Status:** ✓ EXCELLENT - Using modern syntax:

```python
# Modern (Qt6/PySide6) - CORRECT
_ = worker.command_started.connect(
    on_started,
    Qt.ConnectionType.QueuedConnection,  # ✓ Modern syntax with enum
)
```

---

### 14. Thread Safety Patterns

**Files:**
- `/home/gabrielh/projects/shotbot/shot_model.py`
- `/home/gabrielh/projects/shotbot/launcher/worker.py` (lines 90-184)

**Status:** ✓ EXCELLENT - Proper thread safety:

```python
# Correct: Worker runs in thread, emits signals for UI updates
@override
def do_work(self) -> None:
    """Execute in worker thread."""
    try:
        # Parse command
        cmd_list, use_shell = self._sanitize_command(self.command)
        
        # Start process
        self._process = subprocess.Popen(...)
        
        # Monitor with periodic checks for stop requests
        while not self.is_stop_requested():
            # Check if process finished
            return_code = self._process.wait(timeout=1.0)
            self.command_finished.emit(self.launcher_id, success, return_code)
            return
```

---

### 15. Qt Lifecycle Management

**Files:**
- `/home/gabrielh/projects/shotbot/launcher/worker.py` (lines 37-59)
- `/home/gabrielh/projects/shotbot/launcher/process_manager.py` (lines 159)

**Status:** ✓ EXCELLENT - Proper parent/child relationships:

```python
# Correct: Accept parent parameter
def __init__(
    self,
    launcher_id: str,
    command: str,
    working_dir: str | None = None,
    parent: QObject | None = None,  # ✓ Required for Qt ownership
) -> None:
    super().__init__(parent)  # ✓ Pass to parent
```

---

## Positive Patterns Found

### Type Safety Excellence
- Comprehensive type hints throughout codebase
- Excellent use of `TypedDict` for JSON structures
- Proper use of `final` decorator for concrete classes
- Protocol usage for interface definition (LauncherTarget)

### Qt Threading
- Proper signal/slot for thread communication
- Correct lifecycle management with parent parameters
- Good use of worker threads to prevent UI blocking
- Proper cleanup and resource management

### Modern Python Usage
- Good use of dataclasses (`LauncherParameter`, `ProgressConfig`)
- Proper use of `@override` from typing_compat
- Good documentation with docstrings
- Context managers for resource management

---

## Recommendations Summary

### Priority 1 (Do First)
1. **Consolidate validation patterns** - Merge duplicated security checks (HIGH impact, MEDIUM effort)
2. **Simplify mutex strategy** - Reduce lock complexity (HIGH impact, HIGH effort but worth it)
3. **Standardize signal connections** - Use explicit `type=` everywhere (HIGH impact, MEDIUM effort)

### Priority 2 (Do Soon)
4. **Be specific with exceptions** - Replace broad `except Exception` (MEDIUM impact, LOW effort)
5. **Use dict comprehensions** - Simplify option building (MEDIUM impact, LOW effort)
6. **Add type aliases** - For complex nested types (MEDIUM impact, LOW effort)

### Priority 3 (Nice to Have)
7. **Extract helper methods** - DRY up signal disconnection (LOW impact, LOW effort)
8. **Use match statements** - For context handling (LOW impact, LOW effort)
9. **Consistent style** - Underscore usage for returns (LOW impact, LOW effort)

---

## Metrics

| Category | Score | Notes |
|----------|-------|-------|
| Type Safety | 95/100 | Excellent, 0 basedpyright errors |
| Qt Patterns | 90/100 | Strong thread safety, good cleanup |
| Code Organization | 85/100 | Good separation of concerns |
| DRY Principle | 75/100 | Some duplication in validators |
| KISS Principle | 78/100 | Mutex complexity could be reduced |
| Modern Python | 80/100 | Good patterns, could use more match/walrus |
| **Overall** | **82/100** | Strong foundation, specific improvements listed |

---

## Conclusion

Shotbot demonstrates **excellent foundational practices** with comprehensive type safety, solid Qt patterns, and good separation of concerns. The identified violations are primarily in the DRY/KISS categories rather than fundamental flaws.

The three critical findings (validator duplication, mutex complexity, inconsistent signal connections) represent the best opportunities for improvement and would have immediate positive impact on maintainability and readability.

The codebase is **well-architected** for a production VFX tool and the specific improvements suggested should be prioritized based on team capacity rather than severity of issues.

