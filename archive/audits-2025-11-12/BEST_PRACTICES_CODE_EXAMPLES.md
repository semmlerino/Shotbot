# Shotbot Best Practices - Detailed Code Examples

This document provides concrete before/after code examples for improving the Shotbot codebase.

---

## Finding 1: Consolidate Duplicated Security Validation

### Current Implementation (Problematic)

**File: `/home/gabrielh/projects/shotbot/launcher/validator.py`**

Three separate security validation implementations:

```python
# Pattern 1: __init__ defines basic patterns
def __init__(self) -> None:
    self.security_patterns: list[str] = [
        "rm -rf",
        "sudo rm",
        "rm /",
        "format c:",
        "del /s",
        "> /dev/sda",
        "dd if=",
        "mkfs.",
        "fdisk",
    ]

# Pattern 2: _validate_security uses basic patterns
def _validate_security(self, command: str) -> list[str]:
    errors: list[str] = []
    cmd_lower = command.lower()
    for pattern in self.security_patterns:
        if pattern in cmd_lower:
            errors.append(f"Command contains potentially dangerous pattern: {pattern}")
            break
    return errors

# Pattern 3: validate_command_syntax uses DIFFERENT regex patterns
def validate_command_syntax(self, command: str) -> tuple[bool, str | None]:
    dangerous_patterns = [
        r"\brm\s+-rf\s+/",
        r"\brm\s+.*\*",
        r";\s*rm\s",
        r"&&\s*rm\s",
        r"\|\s*rm\s",
        r"`rm\s",
        r"\$\(rm\s",
        r";\s*sudo\s",
        r"&&\s*sudo\s",
        r";\s*su\s",
        r"&&\s*su\s",
        r"/etc/passwd",
        r"/etc/shadow",
    ]
    
    cmd_lower = command.lower()
    for pattern in dangerous_patterns:
        try:
            if re.search(pattern, cmd_lower):
                return False, f"Command contains dangerous pattern: {pattern}"
        except re.error:
            self.logger.warning(f"Invalid regex pattern: {pattern}")
    
    # ... more validation
```

**Problems:**
- Three separate pattern lists that could get out of sync
- Two different validation approaches (literal strings vs regex)
- Maintenance nightmare if patterns need updating
- Security holes if one is updated but others aren't

### Improved Implementation

```python
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

@dataclass(frozen=True)
class SecurityPattern:
    """Represents a single security validation pattern."""
    pattern: str          # The actual pattern to match
    pattern_type: str     # "literal" or "regex"
    severity: str         # "critical" or "warning"
    category: str         # "file_ops", "privilege_escalation", "system_access"
    description: str      # Human-readable description for logging

class PatternCategory(Enum):
    """Categories of dangerous operations."""
    FILE_OPERATIONS = "file_ops"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    SYSTEM_ACCESS = "system_access"
    NETWORK_OPS = "network_ops"

class SecurityValidator(LoggingMixin):
    """Unified security validation with single source of truth."""
    
    # Single source of truth for all dangerous patterns
    DANGEROUS_PATTERNS: ClassVar[list[SecurityPattern]] = [
        # File destruction patterns
        SecurityPattern(
            pattern=r"\brm\s+-rf\s+/",
            pattern_type="regex",
            severity="critical",
            category="file_ops",
            description="Recursive deletion of root filesystem"
        ),
        SecurityPattern(
            pattern=r"\brm\s+.*\*",
            pattern_type="regex",
            severity="critical",
            category="file_ops",
            description="Wildcard deletion with rm"
        ),
        SecurityPattern(
            pattern="rm -rf",
            pattern_type="literal",
            severity="critical",
            category="file_ops",
            description="Forced recursive deletion"
        ),
        
        # Privilege escalation
        SecurityPattern(
            pattern=r";\s*sudo\s",
            pattern_type="regex",
            severity="critical",
            category="privilege_escalation",
            description="Sudo command after semicolon"
        ),
        SecurityPattern(
            pattern="sudo rm",
            pattern_type="literal",
            severity="critical",
            category="privilege_escalation",
            description="Privileged file deletion"
        ),
        
        # System access
        SecurityPattern(
            pattern="/etc/passwd",
            pattern_type="literal",
            severity="warning",
            category="system_access",
            description="System password file access"
        ),
        SecurityPattern(
            pattern="/etc/shadow",
            pattern_type="literal",
            severity="critical",
            category="system_access",
            description="System shadow file access"
        ),
    ]
    
    def __init__(self) -> None:
        """Initialize with patterns already defined."""
        super().__init__()
        # Validate all patterns are syntactically correct
        self._validate_patterns()
    
    def _validate_patterns(self) -> None:
        """Ensure all regex patterns are valid."""
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.pattern_type == "regex":
                try:
                    re.compile(pattern.pattern)
                except re.error as e:
                    self.logger.error(
                        f"Invalid regex in security pattern '{pattern.description}': {e}"
                    )
                    raise
    
    def validate_command_security(
        self,
        command: str,
        check_literal: bool = True,
        check_regex: bool = True
    ) -> tuple[bool, str | None]:
        """
        Validate command against all security patterns.
        
        Args:
            command: Command to validate
            check_literal: Include literal pattern matching
            check_regex: Include regex pattern matching
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not command:
            return False, "Command cannot be empty"
        
        cmd_lower = command.lower()
        errors: list[str] = []
        
        for pattern in self.DANGEROUS_PATTERNS:
            # Skip patterns not requested
            if pattern.pattern_type == "literal" and not check_literal:
                continue
            if pattern.pattern_type == "regex" and not check_regex:
                continue
            
            match = False
            try:
                if pattern.pattern_type == "literal":
                    match = pattern.pattern in cmd_lower
                else:  # regex
                    match = bool(re.search(pattern.pattern, cmd_lower))
            except re.error as e:
                self.logger.error(f"Regex error for pattern '{pattern.description}': {e}")
                continue
            
            if match:
                error_msg = (
                    f"{pattern.severity.upper()}: {pattern.description} "
                    f"(pattern: {pattern.pattern})"
                )
                errors.append(error_msg)
                # Only return first critical error for immediate feedback
                if pattern.severity == "critical":
                    return False, error_msg
        
        if errors:
            # Multiple warnings but no critical errors
            return True, "; ".join(errors)  # Return as warning
        
        return True, None

# Usage in validation
validator = SecurityValidator()

# Unified API - just call one method
is_valid, error = validator.validate_command_security(
    user_command,
    check_literal=True,
    check_regex=True
)
if not is_valid:
    return False, error
```

**Benefits:**
- Single source of truth for all patterns
- Easy to add/modify/remove patterns
- Better maintainability
- Clear categorization of pattern types
- Detailed descriptions for logging and debugging

---

## Finding 2: Simplify Mutex Locking Strategy

### Current Implementation (Problematic)

**File: `/home/gabrielh/projects/shotbot/launcher/process_manager.py`**

```python
class LauncherProcessManager(LoggingMixin, QObject):
    def __init__(self) -> None:
        super().__init__()
        
        # Multiple lock types and flags for coordination
        self._active_processes: dict[str, ProcessInfo] = {}
        self._active_workers: dict[str, LauncherWorker] = {}
        self._process_lock = QRecursiveMutex()        # Main lock
        self._cleanup_lock = QMutex()                 # Separate cleanup lock
        self._cleanup_in_progress = False             # Flag 1
        self._cleanup_scheduled = False               # Flag 2
        
        # Timers for cleanup
        self._cleanup_retry_timer = QTimer()
        self._cleanup_timer = QTimer()
        
        self._shutting_down = False
    
    def execute_with_subprocess(self, ...) -> str | None:
        # Get lock, add process
        with QMutexLocker(self._process_lock):
            self._active_processes[process_key] = process_info
    
    def _on_worker_finished(self, worker_key: str, ...) -> None:
        # Complex cleanup with nested locks
        worker = None
        with QMutexLocker(self._process_lock):
            if worker_key in self._active_workers:
                worker = self._active_workers[worker_key]
                try:
                    del self._active_workers[worker_key]
                except Exception as e:
                    self.logger.warning(f"Error during cleanup: {e}")
        
        # Disconnect outside lock
        if worker:
            try:
                _ = worker.command_started.disconnect()
                _ = worker.command_finished.disconnect()
                _ = worker.command_error.disconnect()
            except (RuntimeError, TypeError):
                pass
        
        self.process_finished.emit(launcher_id, success, return_code)
    
    def _cleanup_finished_processes(self) -> None:
        # Manual snapshot pattern
        with QMutexLocker(self._process_lock):
            processes_snapshot = list(self._active_processes.items())
        
        # Check outside lock
        for process_key, process_info in processes_snapshot:
            try:
                if process_info.process.poll() is not None:
                    finished_keys.append(process_key)
            except (OSError, AttributeError) as e:
                self.logger.debug(f"Error checking process {process_key}: {e}")
        
        # Remove with lock
        if finished_keys:
            with QMutexLocker(self._process_lock):
                for key in finished_keys:
                    if key in self._active_processes:
                        del self._active_processes[key]
```

**Problems:**
- Too many locks (recursive + regular)
- State flags that could get out of sync
- Complex lock/unlock patterns
- Hard to understand thread safety guarantees
- Prone to deadlocks or missed updates

### Improved Implementation (KISS Principle)

```python
from dataclasses import dataclass, field
from threading import Lock
from typing import Generic, TypeVar

T = TypeVar('T')

@dataclass
class ThreadSafeDict(Generic[T]):
    """Simple thread-safe dictionary wrapper (KISS principle)."""
    _data: dict[str, T] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    
    def get(self, key: str) -> T | None:
        """Get value by key."""
        with self._lock:
            return self._data.get(key)
    
    def set(self, key: str, value: T) -> None:
        """Set value by key."""
        with self._lock:
            self._data[key] = value
    
    def pop(self, key: str) -> T | None:
        """Remove and return value."""
        with self._lock:
            return self._data.pop(key, None)
    
    def snapshot(self) -> dict[str, T]:
        """Get safe copy of all data."""
        with self._lock:
            return dict(self._data)
    
    def items(self) -> list[tuple[str, T]]:
        """Get copy of items."""
        with self._lock:
            return list(self._data.items())
    
    def clear(self) -> None:
        """Clear all items."""
        with self._lock:
            self._data.clear()
    
    def __len__(self) -> int:
        """Get count of items."""
        with self._lock:
            return len(self._data)

class LauncherProcessManager(LoggingMixin, QObject):
    """Simplified process manager using single lock."""
    
    # Qt signals
    process_started = Signal(str, str)
    process_finished = Signal(str, bool, int)
    process_error = Signal(str, str)
    
    # Configuration constants
    CLEANUP_INTERVAL_MS = 5000
    
    def __init__(self) -> None:
        super().__init__()
        
        # Single thread-safe collections (KISS)
        self._processes = ThreadSafeDict[ProcessInfo]()
        self._workers = ThreadSafeDict[LauncherWorker]()
        
        # Simple boolean for shutdown
        self._shutting_down = False
        
        # Single cleanup timer
        self._cleanup_timer = QTimer()
        _ = self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(self.CLEANUP_INTERVAL_MS)
    
    def execute_with_subprocess(
        self,
        launcher_id: str,
        launcher_name: str,
        command: list[str],
        working_dir: str | None = None,
    ) -> str | None:
        """Execute command in subprocess."""
        try:
            process = subprocess.Popen(
                command,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=working_dir,
                start_new_session=True,
            )
            
            process_key = f"{launcher_id}_{process.pid}"
            
            # Simple add - ThreadSafeDict handles locking
            process_info = ProcessInfo(
                process=process,
                launcher_id=launcher_id,
                launcher_name=launcher_name,
                command=" ".join(command),
                timestamp=time.time(),
            )
            self._processes.set(process_key, process_info)
            
            self.logger.info(f"Started subprocess: {launcher_name} (PID: {process.pid})")
            self.process_started.emit(launcher_id, " ".join(command))
            
            return process_key
        
        except Exception as e:
            self.logger.error(f"Failed to start subprocess: {e}")
            self.process_error.emit(launcher_id, str(e))
            return None
    
    def _on_worker_finished(
        self,
        worker_key: str,
        launcher_id: str,
        success: bool,
        return_code: int
    ) -> None:
        """Handle worker completion (much simpler)."""
        # Get and remove worker in one operation
        worker = self._workers.pop(worker_key)
        
        if worker:
            # Simple helper to clean up signals
            self._disconnect_signals(worker)
        
        self.process_finished.emit(launcher_id, success, return_code)
    
    def _disconnect_signals(self, worker: LauncherWorker) -> None:
        """Centralized signal cleanup (DRY)."""
        for signal in [
            worker.command_started,
            worker.command_finished,
            worker.command_error,
        ]:
            try:
                _ = signal.disconnect()
            except (RuntimeError, TypeError):
                pass
    
    def _periodic_cleanup(self) -> None:
        """Clean up finished processes (much simpler)."""
        if self._shutting_down:
            return
        
        # Get snapshot (thread-safe)
        processes = self._processes.items()
        
        # Check which are finished
        finished_keys = [
            key for key, info in processes
            if info.process.poll() is not None
        ]
        
        # Remove finished processes
        for key in finished_keys:
            _ = self._processes.pop(key)
            self.logger.debug(f"Cleaned up process {key}")
        
        # Same for workers
        workers = self._workers.items()
        finished_worker_keys = [
            key for key, worker in workers
            if not worker.isRunning()
        ]
        
        for key in finished_worker_keys:
            worker = self._workers.pop(key)
            if worker:
                self._disconnect_signals(worker)
            self.logger.debug(f"Cleaned up worker {key}")
```

**Benefits:**
- Single lock for all data
- Clear thread-safety guarantees
- No nested locks
- No state flags
- Much easier to understand and maintain
- Simpler error handling
- DRY principle applied (signal cleanup)

---

## Finding 3: Standardize Signal/Slot Connections

### Current Implementation (Inconsistent)

**File: `/home/gabrielh/projects/shotbot/controllers/launcher_controller.py`**

```python
def _setup_signals(self) -> None:
    """Setup signal connections - INCONSISTENT patterns."""
    
    # Pattern A: No connection type specified (relies on defaults)
    _ = self.window.launcher_panel.app_launch_requested.connect(self.launch_app)
    _ = self.window.launcher_panel.custom_launcher_requested.connect(
        self.execute_custom_launcher
    )
    
    # Pattern B: Different connection types for different signals
    _ = self.window.command_launcher.command_executed.connect(
        self.window.log_viewer.add_command
    )
    _ = self.window.command_launcher.command_error.connect(
        self.window.log_viewer.add_error
    )
    
    # Pattern C: Manual connection with explicit type (from process_manager.py)
    _ = worker.command_started.connect(
        on_started,
        Qt.ConnectionType.QueuedConnection,
    )
```

**Problems:**
- Thread safety guarantees not obvious
- Defaults might change between Qt versions
- Hard to understand which connections are safe for worker threads
- Inconsistent style makes code harder to review

### Improved Implementation

```python
from PySide6.QtCore import Qt, Signal

class ProcessManager(LoggingMixin, QObject):
    """Example of consistent signal/slot patterns."""
    
    # Signals
    process_started = Signal(str, str)
    process_finished = Signal(str, bool, int)
    process_error = Signal(str, str)
    
    def __init__(self) -> None:
        super().__init__()
        # Setup signals EARLY, consistently
        self._setup_signal_connections()
    
    def _setup_signal_connections(self) -> None:
        """
        Setup all signal connections with explicit, consistent types.
        
        Connection types:
        - DirectConnection: Immediate, same thread (default)
        - QueuedConnection: Deferred, different thread (safe for workers)
        - AutoConnection: Direct same thread, Queued different thread
        """
        # Cache connection type for consistency
        QUEUED = Qt.ConnectionType.QueuedConnection
        DIRECT = Qt.ConnectionType.DirectConnection
        UNIQUE = Qt.ConnectionType.UniqueConnection
        
        # Workers emit signals from different threads → use Queued
        # This keeps UI code in main thread only
        if hasattr(self, '_worker'):
            _ = self._worker.started.connect(
                self._on_worker_started,
                type=QUEUED,  # ← Explicit, clear
            )
            _ = self._worker.finished.connect(
                self._on_worker_finished,
                type=QUEUED,
            )
            _ = self._worker.error.connect(
                self._on_worker_error,
                type=QUEUED,
            )
        
        # Local signals can use Direct (faster, same thread)
        _ = self.process_started.connect(
            self._on_process_started,
            type=DIRECT,
        )
        
        # Unique connections prevent duplicates
        _ = self.process_finished.connect(
            self._on_process_finished,
            type=QUEUED | UNIQUE,  # Queued + Unique
        )

class LauncherController(LoggingMixin):
    """Application launcher controller with consistent patterns."""
    
    def __init__(self, window: LauncherTarget) -> None:
        super().__init__()
        self.window = window
        self._setup_signals()
    
    def _setup_signals(self) -> None:
        """Setup all signal connections consistently."""
        QUEUED = Qt.ConnectionType.QueuedConnection
        DIRECT = Qt.ConnectionType.DirectConnection
        
        # Define connection points with explicit types for clarity
        signal_connections: list[tuple[Signal, Any, Qt.ConnectionType]] = [
            # Launcher panel signals (UI → controller, same thread)
            (
                self.window.launcher_panel.app_launch_requested,
                self.launch_app,
                DIRECT,
            ),
            (
                self.window.launcher_panel.custom_launcher_requested,
                self.execute_custom_launcher,
                DIRECT,
            ),
            
            # Command launcher signals (possibly from worker threads)
            (
                self.window.command_launcher.command_executed,
                self.window.log_viewer.add_command,
                QUEUED,  # Safe for worker threads
            ),
            (
                self.window.command_launcher.command_error,
                self.window.log_viewer.add_error,
                QUEUED,  # Safe for worker threads
            ),
            (
                self.window.command_launcher.command_error,
                self._on_command_error,
                QUEUED,
            ),
        ]
        
        # Connect all with explicit types
        for signal, slot, connection_type in signal_connections:
            try:
                _ = signal.connect(slot, type=connection_type)
                self.logger.debug(
                    f"Connected {signal} to {slot.__name__} "
                    f"(type={connection_type.name})"
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to connect signal {signal}: {e}"
                )
        
        # Launcher manager signals (if available)
        if self.window.launcher_manager:
            manager_connections = [
                (
                    self.window.launcher_manager.launchers_changed,
                    self.update_launcher_menu,
                    DIRECT,
                ),
                (
                    self.window.launcher_manager.launchers_changed,
                    self.update_custom_launcher_buttons,
                    DIRECT,
                ),
                (
                    self.window.launcher_manager.execution_started,
                    self._on_launcher_started,
                    DIRECT,
                ),
                (
                    self.window.launcher_manager.execution_finished,
                    self._on_launcher_finished,
                    DIRECT,
                ),
            ]
            
            for signal, slot, connection_type in manager_connections:
                try:
                    _ = signal.connect(slot, type=connection_type)
                except Exception as e:
                    self.logger.error(f"Failed to connect signal: {e}")
        
        self.logger.debug("Signal connections setup complete")
```

**Benefits:**
- Explicit connection types document thread safety
- Consistent style throughout codebase
- Easy to verify thread safety
- Easier to debug signal-related issues
- Clear documentation of intent

---

## Finding 4: Use Dictionary Comprehensions

### Current Implementation

**File: `/home/gabrielh/projects/shotbot/controllers/launcher_controller.py` (lines 200-218)**

```python
def get_launch_options(self, app_name: str) -> dict[str, bool]:
    """Get app-specific launch options from checkbox states."""
    # Verbose manual construction
    app_options: dict[str, list[str]] = {
        "nuke": [
            "include_raw_plate",
            "open_latest_scene",
            "create_new_file",
        ],
        "3de": ["open_latest_threede"],
        "maya": ["open_latest_maya"],
    }
    
    # Verbose loop to build result
    options: dict[str, bool] = {}
    for option in app_options.get(app_name, []):
        options[option] = self.window.launcher_panel.get_checkbox_state(
            app_name, option
        )
    
    return options
```

### Improved Implementation

```python
from typing import ClassVar

class LauncherController(LoggingMixin):
    """Controller with cleaner configuration."""
    
    # Configuration as class constant
    APP_OPTIONS: ClassVar[dict[str, list[str]]] = {
        "nuke": [
            "include_raw_plate",
            "open_latest_scene",
            "create_new_file",
        ],
        "3de": ["open_latest_threede"],
        "maya": ["open_latest_maya"],
    }
    
    def get_launch_options(self, app_name: str) -> dict[str, bool]:
        """Get app-specific launch options - much cleaner."""
        # Dictionary comprehension (Pythonic)
        return {
            option: self.window.launcher_panel.get_checkbox_state(app_name, option)
            for option in self.APP_OPTIONS.get(app_name, [])
        }
    
    # Even better: Use dataclass for configuration
    
@dataclass(frozen=True)
class AppLaunchConfig:
    """Configuration for app launching."""
    name: str
    options: list[str]
    
    def get_selected_options(self, panel: LauncherPanel) -> dict[str, bool]:
        """Get selected options for this app."""
        return {
            opt: panel.get_checkbox_state(self.name, opt)
            for opt in self.options
        }

class LauncherControllerV2(LoggingMixin):
    """Even cleaner with dataclass configuration."""
    
    # Configuration as data objects
    APP_CONFIGS: ClassVar[dict[str, AppLaunchConfig]] = {
        "nuke": AppLaunchConfig(
            name="nuke",
            options=[
                "include_raw_plate",
                "open_latest_scene",
                "create_new_file",
            ]
        ),
        "3de": AppLaunchConfig(
            name="3de",
            options=["open_latest_threede"]
        ),
        "maya": AppLaunchConfig(
            name="maya",
            options=["open_latest_maya"]
        ),
    }
    
    def get_launch_options(self, app_name: str) -> dict[str, bool]:
        """Get options using configuration objects."""
        config = self.APP_CONFIGS.get(app_name)
        if not config:
            return {}
        
        return config.get_selected_options(self.window.launcher_panel)
```

---

## Summary of Improvements

| Finding | Current | Improved | Impact |
|---------|---------|----------|--------|
| 1. Security Validation | 3 separate implementations | 1 unified class | High |
| 2. Mutex Strategy | 2 locks + 2 flags | 1 ThreadSafeDict wrapper | High |
| 3. Signal Connections | Inconsistent types | Explicit consistent types | High |
| 4. Dict Operations | Manual loops | Dictionary comprehensions | Medium |
| 5. Exception Handling | Bare `Exception` | Specific exceptions | Medium |
| 6. Type Aliases | Repeated complex types | Single TypeAlias | Medium |
| 7. Signal Cleanup | Duplicated try/except | Extracted helper method | Low |

