# Terminal/Launcher System - Code Fixes with Examples

This document provides detailed code examples for fixing the identified best practices violations.

## FIX 1: Add Parent Parameter to QObject Subclasses (CRITICAL)

### persistent_terminal_manager.py

**Before** (Line 39-48):
```python
def __init__(
    self, fifo_path: str | None = None, dispatcher_path: str | None = None
) -> None:
    """Initialize the persistent terminal manager.

    Args:
        fifo_path: Path to the FIFO for command communication
        dispatcher_path: Path to the terminal dispatcher script
    """
    super().__init__()
```

**After**:
```python
def __init__(
    self,
    fifo_path: str | None = None,
    dispatcher_path: str | None = None,
    parent: QObject | None = None,
) -> None:
    """Initialize the persistent terminal manager.

    Args:
        fifo_path: Path to the FIFO for command communication
        dispatcher_path: Path to the terminal dispatcher script
        parent: Optional parent QObject for proper Qt ownership
    """
    super().__init__(parent)
```

### command_launcher.py

**Before** (Line 66-83):
```python
def __init__(
    self,
    raw_plate_finder: type[RawPlateFinderType] | None = None,
    nuke_script_generator: type[NukeScriptGeneratorType] | None = None,
    threede_latest_finder: type[ThreeDELatestFinderType] | None = None,
    maya_latest_finder: type[MayaLatestFinderType] | None = None,
    persistent_terminal: PersistentTerminalManager | None = None,
) -> None:
    """Initialize CommandLauncher with optional dependencies.
    
    Args:
        raw_plate_finder: Class for finding raw plates (defaults to RawPlateFinder)
        nuke_script_generator: Class for generating Nuke scripts (defaults to NukeScriptGenerator)
        threede_latest_finder: Class for finding latest 3DE scenes (defaults to ThreeDELatestFinder)
        maya_latest_finder: Class for finding latest Maya scenes (defaults to MayaLatestFinder)
        persistent_terminal: Optional persistent terminal manager for single terminal mode
    """
    super().__init__()
```

**After**:
```python
def __init__(
    self,
    raw_plate_finder: type[RawPlateFinderType] | None = None,
    nuke_script_generator: type[NukeScriptGeneratorType] | None = None,
    threede_latest_finder: type[ThreeDELatestFinderType] | None = None,
    maya_latest_finder: type[MayaLatestFinderType] | None = None,
    persistent_terminal: PersistentTerminalManager | None = None,
    parent: QObject | None = None,
) -> None:
    """Initialize CommandLauncher with optional dependencies.
    
    Args:
        raw_plate_finder: Class for finding raw plates (defaults to RawPlateFinder)
        nuke_script_generator: Class for generating Nuke scripts (defaults to NukeScriptGenerator)
        threede_latest_finder: Class for finding latest 3DE scenes (defaults to ThreeDELatestFinder)
        maya_latest_finder: Class for finding latest Maya scenes (defaults to MayaLatestFinder)
        persistent_terminal: Optional persistent terminal manager for single terminal mode
        parent: Optional parent QObject for proper Qt ownership
    """
    super().__init__(parent)
```

---

## FIX 2: Extract Magic Numbers to Class Constants (MEDIUM)

### persistent_terminal_manager.py

**Before** (Lines 39-90):
```python
def __init__(
    self, fifo_path: str | None = None, dispatcher_path: str | None = None
) -> None:
    """Initialize the persistent terminal manager."""
    super().__init__()
    
    # ... setup code ...
    
    # Health monitoring
    self._last_heartbeat_time: float = 0.0
    self._heartbeat_timeout: float = 60.0  # Magic number!
    self._heartbeat_check_interval: float = 30.0  # Magic number!
```

**After**:
```python
@final
class PersistentTerminalManager(LoggingMixin, QObject):
    """Manages a single persistent terminal for all commands."""

    # Signals
    terminal_started = Signal(int)  # PID of terminal
    terminal_closed = Signal()
    command_sent = Signal(str)  # Command that was sent

    # Timeout and delay constants (seconds)
    # These values are tuned for reliable terminal startup and health monitoring
    HEARTBEAT_TIMEOUT = 60.0  # Max age of heartbeat before considered stale
    HEARTBEAT_CHECK_INTERVAL = 30.0  # How often to check heartbeat
    TERMINAL_START_DELAY = 0.5  # Grace period after launching terminal
    DISPATCHER_STARTUP_TIMEOUT = 3.0  # Max wait for dispatcher script to start
    RECOVERY_TIMEOUT = 5.0  # Max wait for dispatcher to recover
    POLL_INTERVAL = 0.1  # Polling interval for async operations
    FIFO_WRITE_RETRY_DELAY = 0.2  # Delay between FIFO write retries
    MAX_WRITE_RETRIES = 2  # Maximum write retry attempts

    def __init__(
        self,
        fifo_path: str | None = None,
        dispatcher_path: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the persistent terminal manager.

        Args:
            fifo_path: Path to the FIFO for command communication
            dispatcher_path: Path to the terminal dispatcher script
            parent: Optional parent QObject for proper Qt ownership
        """
        super().__init__(parent)

        # Set up paths
        self.fifo_path = fifo_path or "/tmp/shotbot_commands.fifo"
        self.heartbeat_path = "/tmp/shotbot_heartbeat.txt"
        self.dispatcher_log_path = str(Path.home() / ".shotbot/logs/dispatcher_debug.log")

        # Find dispatcher script relative to this module
        if dispatcher_path:
            self.dispatcher_path = dispatcher_path
        else:
            module_dir = Path(__file__).parent
            self.dispatcher_path = str(module_dir / "terminal_dispatcher.sh")

        # Terminal state
        self.terminal_pid: int | None = None
        self.terminal_process: subprocess.Popen[bytes] | None = None
        self.dispatcher_pid: int | None = None  # Track dispatcher bash script PID

        # Health monitoring (using class constants)
        self._last_heartbeat_time: float = 0.0
        self._heartbeat_timeout: float = self.HEARTBEAT_TIMEOUT
        self._heartbeat_check_interval: float = self.HEARTBEAT_CHECK_INTERVAL

        # Auto-recovery state
        self._restart_attempts: int = 0
        self._max_restart_attempts: int = 3
        self._fallback_mode: bool = False

        # Thread safety: Lock for serializing FIFO writes
        self._write_lock = threading.Lock()

        # Ensure FIFO exists
        if not self._ensure_fifo():
            self.logger.warning(
                f"Failed to create FIFO at {self.fifo_path}, persistent terminal may not work properly"
            )
```

Then replace all time.sleep() and timeout assignments:

**Before** (Line 425):
```python
# Give terminal time to start
time.sleep(0.5)
```

**After**:
```python
# Give terminal time to start
time.sleep(self.TERMINAL_START_DELAY)
```

**Before** (Lines 433-445):
```python
# Wait for dispatcher script to start (up to 3 seconds)
timeout = 3.0
poll_interval = 0.2
elapsed = 0.0

while elapsed < timeout:
    self.dispatcher_pid = self._find_dispatcher_pid()
    if self.dispatcher_pid is not None:
        self.logger.info(
            f"Dispatcher script started with PID: {self.dispatcher_pid}"
        )
        break
    time.sleep(poll_interval)
    elapsed += poll_interval
```

**After**:
```python
# Wait for dispatcher script to start
timeout = self.DISPATCHER_STARTUP_TIMEOUT
poll_interval = self.POLL_INTERVAL
elapsed = 0.0

while elapsed < timeout:
    self.dispatcher_pid = self._find_dispatcher_pid()
    if self.dispatcher_pid is not None:
        self.logger.info(
            f"Dispatcher script started with PID: {self.dispatcher_pid}"
        )
        break
    time.sleep(poll_interval)
    elapsed += poll_interval
```

Apply similar replacements at:
- Line 520: `max_retries = 2` → `max_retries = self.MAX_WRITE_RETRIES`
- Line 545: `time.sleep(0.2)` → `time.sleep(self.FIFO_WRITE_RETRY_DELAY)`
- Line 601: `time.sleep(0.5)` → `time.sleep(self.TERMINAL_START_DELAY)`
- Line 615: `timeout = 5.0` → `timeout = self.RECOVERY_TIMEOUT`
- Line 627: `time.sleep(poll_interval)` → `time.sleep(self.POLL_INTERVAL)` (but poll_interval already uses it)
- Lines 725-734: Use constants throughout

---

## FIX 3: Replace time.sleep() with QTimer (CRITICAL - UI Blocking)

### persistent_terminal_manager.py - Replace blocking _send_heartbeat_ping()

**Before** (Lines 269-300):
```python
def _send_heartbeat_ping(self, timeout: float = 2.0) -> bool:
    """Send a heartbeat ping and wait for response.

    Args:
        timeout: Maximum time to wait for response (seconds)

    Returns:
        True if PONG received within timeout, False otherwise
    """
    try:
        # Remove old heartbeat file
        heartbeat_file = Path(self.heartbeat_path)
        if heartbeat_file.exists():
            heartbeat_file.unlink()

        # Send PING command
        if not self._send_command_direct("__HEARTBEAT__"):
            return False

        # Poll for PONG response
        start_time = time.time()
        while (time.time() - start_time) < timeout:  # ❌ BLOCKS UI!
            if self._check_heartbeat():
                return True
            time.sleep(0.1)  # ❌ BLOCKS UI!

        self.logger.debug(f"No heartbeat response after {timeout}s")
        return False

    except Exception as e:
        self.logger.debug(f"Error sending heartbeat ping: {e}")
        return False
```

**After** - Split into async methods:
```python
# Add new signal for async heartbeat verification
heartbeat_response_received = Signal()
heartbeat_timeout_occurred = Signal()

def _send_heartbeat_ping_async(self) -> None:
    """Send heartbeat ping asynchronously using QTimer.
    
    Non-blocking alternative to _send_heartbeat_ping() that doesn't freeze the UI.
    """
    try:
        # Remove old heartbeat file
        heartbeat_file = Path(self.heartbeat_path)
        if heartbeat_file.exists():
            heartbeat_file.unlink()

        # Send PING command
        if not self._send_command_direct("__HEARTBEAT__"):
            self.heartbeat_timeout_occurred.emit()
            return

        # Set up async polling with QTimer
        self._heartbeat_check_timer = QTimer()
        self._heartbeat_check_timer.setInterval(100)  # 100ms polling interval
        self._heartbeat_start_time = time.time()
        self._heartbeat_timeout_duration = 2.0

        @self._heartbeat_check_timer.timeout.connect
        def check_heartbeat_response():
            if self._check_heartbeat():
                self._heartbeat_check_timer.stop()
                self.logger.debug("Heartbeat response received")
                self.heartbeat_response_received.emit()
            elif (time.time() - self._heartbeat_start_time) > self._heartbeat_timeout_duration:
                self._heartbeat_check_timer.stop()
                self.logger.debug("Heartbeat timeout occurred")
                self.heartbeat_timeout_occurred.emit()

        # Start polling
        self._heartbeat_check_timer.start()

    except Exception as e:
        self.logger.debug(f"Error sending heartbeat ping: {e}")
        self.heartbeat_timeout_occurred.emit()

def _send_heartbeat_ping(self, timeout: float = 2.0) -> bool:
    """DEPRECATED: Synchronous heartbeat ping. Use _send_heartbeat_ping_async() instead.
    
    This method blocks the UI thread. For new code, use the async version.
    Kept for backward compatibility.
    
    Args:
        timeout: Maximum time to wait for response (seconds)

    Returns:
        True if PONG received within timeout, False otherwise
    """
    self.logger.warning(
        "_send_heartbeat_ping() is deprecated and blocks the UI. "
        "Use _send_heartbeat_ping_async() instead."
    )
    
    try:
        # Remove old heartbeat file
        heartbeat_file = Path(self.heartbeat_path)
        if heartbeat_file.exists():
            heartbeat_file.unlink()

        # Send PING command
        if not self._send_command_direct("__HEARTBEAT__"):
            return False

        # Poll for PONG response (with warning about blocking)
        start_time = time.time()
        max_iterations = int(timeout / 0.05)  # Limit iterations to prevent forever loops
        iteration = 0
        
        while iteration < max_iterations:
            if self._check_heartbeat():
                return True
            time.sleep(0.05)  # Smaller interval
            iteration += 1

        self.logger.debug(f"No heartbeat response after {timeout}s")
        return False

    except Exception as e:
        self.logger.debug(f"Error sending heartbeat ping: {e}")
        return False
```

---

## FIX 4: Add @Slot Decorators (MEDIUM)

### persistent_terminal_manager.py

**Before**:
```python
def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    """Send a command to the persistent terminal."""
    # ... implementation ...
```

**After**:
```python
from PySide6.QtCore import Slot

class PersistentTerminalManager(LoggingMixin, QObject):
    
    @Slot(str, bool)
    def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
        """Send a command to the persistent terminal."""
        # ... implementation ...

    @Slot()
    def restart_terminal(self) -> bool:
        """Restart the persistent terminal."""
        # ... implementation ...

    @Slot()
    def clear_terminal(self) -> bool:
        """Clear the terminal screen."""
        # ... implementation ...

    @Slot()
    def close_terminal(self) -> bool:
        """Close the persistent terminal."""
        # ... implementation ...
```

### command_launcher.py

**Before**:
```python
def launch_app(
    self,
    app_name: str,
    include_raw_plate: bool = False,
    ...
) -> bool:
    """Launch an application in the current shot context."""
```

**After**:
```python
from PySide6.QtCore import Slot

class CommandLauncher(LoggingMixin, QObject):
    
    @Slot(str, bool, bool, bool, bool, bool, str)
    def launch_app(
        self,
        app_name: str,
        include_raw_plate: bool = False,
        open_latest_threede: bool = False,
        open_latest_maya: bool = False,
        open_latest_scene: bool = False,
        create_new_file: bool = False,
        selected_plate: str | None = None,
    ) -> bool:
        """Launch an application in the current shot context."""
```

---

## FIX 5: Extract Launch Method Common Logic (MEDIUM)

### command_launcher.py

**Before** (3 nearly identical methods, 700+ lines):
```python
def launch_app(self, app_name: str, ...) -> bool:
    # ~290 lines
    
def launch_app_with_scene(self, app_name: str, scene: ThreeDEScene) -> bool:
    # ~200 lines (90% duplicate)
    
def launch_app_with_scene_context(self, app_name: str, scene: ThreeDEScene, ...) -> bool:
    # ~225 lines (90% duplicate)
```

**After** (Refactored with shared logic):
```python
def _get_launch_workspace(
    self, shot: Shot | None = None, scene: ThreeDEScene | None = None
) -> str | None:
    """Get workspace path from shot or scene.
    
    Args:
        shot: Current shot (optional)
        scene: 3DE scene (optional)
        
    Returns:
        Workspace path or None if neither provided
    """
    if scene is not None:
        return scene.workspace_path
    if shot is not None:
        return shot.workspace_path
    return None

def _build_launch_command(
    self,
    app_name: str,
    base_command: str,
    workspace_path: str,
    is_rez_wrapped: bool = False,
) -> str:
    """Build the complete command to execute.
    
    Handles:
    - Workspace setup (ws command)
    - Rez environment wrapping
    - Logging redirection
    
    Args:
        app_name: Name of the application
        base_command: Base command (app name + args)
        workspace_path: Workspace directory path
        is_rez_wrapped: Whether command should be wrapped with rez
        
    Returns:
        Complete shell command ready to execute
    """
    try:
        safe_workspace_path = self._validate_path_for_shell(workspace_path)
    except ValueError as e:
        self._emit_error(f"Invalid workspace path: {e!s}")
        return ""

    # Build base command with workspace
    env_fixes = ""
    if app_name == "nuke":
        env_fixes = self.nuke_handler.get_environment_fixes()
    
    ws_command = f"ws {safe_workspace_path} && {env_fixes}{base_command}"

    # Wrap with rez if needed
    if is_rez_wrapped and self._is_rez_available():
        rez_packages = self._get_rez_packages_for_app(app_name)
        if rez_packages:
            packages_str = " ".join(rez_packages)
            full_command = f'rez env {packages_str} -- bash -ilc "{ws_command}"'
        else:
            full_command = ws_command
    else:
        full_command = ws_command

    # Add logging redirection
    full_command = self._add_dispatcher_logging(full_command)
    return full_command

def _execute_launch(
    self,
    app_name: str,
    command: str,
    timestamp_prefix: str = "",
) -> bool:
    """Execute launch command via persistent terminal or new terminal.
    
    Args:
        app_name: Name of the application
        command: Complete command to execute
        timestamp_prefix: Optional prefix for logging
        
    Returns:
        True if launch successful, False otherwise
    """
    # Log the command
    timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
    full_log = command
    if timestamp_prefix:
        full_log = f"{timestamp_prefix} {command}"
    self.command_executed.emit(timestamp, full_log)

    # Try persistent terminal first
    if (
        self.persistent_terminal
        and Config.PERSISTENT_TERMINAL_ENABLED
        and Config.USE_PERSISTENT_TERMINAL
    ):
        success = self.persistent_terminal.send_command(command)
        if success:
            self.logger.debug("Command successfully sent to persistent terminal")
            return True
        
        self.logger.warning("Failed to send to persistent terminal, falling back")
        timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
        self.command_executed.emit(
            timestamp,
            "⚠ Persistent terminal not available, launching in new terminal...",
        )

    # Fallback to new terminal
    terminal = self._detect_available_terminal()
    if terminal is None:
        self._emit_error(
            "No terminal emulator found (gnome-terminal, konsole, xterm, x-terminal-emulator)"
        )
        return False

    try:
        # Build terminal command based on emulator type
        if terminal == "gnome-terminal":
            term_cmd = ["gnome-terminal", "--", "bash", "-ilc", command]
        elif terminal == "konsole":
            term_cmd = ["konsole", "-e", "bash", "-ilc", command]
        elif terminal in ["xterm", "x-terminal-emulator"]:
            term_cmd = [terminal, "-e", "bash", "-ilc", command]
        else:
            term_cmd = ["/bin/bash", "-ilc", command]

        process = subprocess.Popen(term_cmd)

        # Verify spawn after 100ms
        QTimer.singleShot(100, partial(self._verify_spawn, process, app_name))
        return True

    except FileNotFoundError as e:
        filename_str = _safe_filename_str(cast("str | bytes | int | None", e.filename))
        self._emit_error(
            f"Cannot launch {app_name}: Application or terminal not found. Details: {filename_str}"
        )
        NotificationManager.error("Launch Failed", f"{app_name} executable not found")
        self._available_terminal = None
        return False

    except (PermissionError, OSError) as e:
        self._emit_error(f"Cannot launch {app_name}: {e!s}")
        self._available_terminal = None
        return False

# Refactored public methods (now much simpler!)
def launch_app(
    self,
    app_name: str,
    include_raw_plate: bool = False,
    open_latest_threede: bool = False,
    open_latest_maya: bool = False,
    open_latest_scene: bool = False,
    create_new_file: bool = False,
    selected_plate: str | None = None,
) -> bool:
    """Launch an application in shot context."""
    if not self.current_shot:
        self._emit_error("No shot selected")
        return False

    if app_name not in Config.APPS:
        self._emit_error(f"Unknown application: {app_name}")
        return False

    # Get workspace
    workspace_path = self.current_shot.workspace_path
    if not self._validate_workspace_before_launch(workspace_path, app_name):
        return False

    # Get base command
    command = Config.APPS[app_name]

    # Apply app-specific modifications
    # (3DE, Maya, Nuke-specific logic - moved to helper functions)
    
    # Build complete command
    full_command = self._build_launch_command(
        app_name, command, workspace_path, is_rez_wrapped=True
    )
    
    if not full_command:
        return False

    # Execute
    return self._execute_launch(app_name, full_command)

def launch_app_with_scene(
    self, app_name: str, scene: ThreeDEScene
) -> bool:
    """Launch application with specific 3DE scene file."""
    if app_name not in Config.APPS:
        self._emit_error(f"Unknown application: {app_name}")
        return False

    if not self._validate_workspace_before_launch(scene.workspace_path, app_name):
        return False

    # Get base command with scene
    command = Config.APPS[app_name]
    try:
        safe_scene_path = self._validate_path_for_shell(str(scene.scene_path))
        if app_name == "3de":
            command = f"{command} -open {safe_scene_path}"
        elif app_name == "maya":
            command = f"{command} -file {safe_scene_path}"
        else:
            command = f"{command} {safe_scene_path}"
    except ValueError as e:
        self._emit_error(f"Invalid scene path: {e!s}")
        return False

    # Build complete command
    full_command = self._build_launch_command(
        app_name, command, scene.workspace_path, is_rez_wrapped=True
    )
    
    if not full_command:
        return False

    # Log scene info
    timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
    self.command_executed.emit(
        timestamp,
        f"Scene by: {scene.user}, Plate: {scene.plate}",
    )

    # Execute
    return self._execute_launch(app_name, full_command)
```

---

## FIX 6: Centralize Application Configuration (LOW)

### config.py

**Add**:
```python
# Application configuration
GUI_APPLICATIONS = frozenset({
    "3de",
    "nuke", 
    "maya",
    "rv",
    "houdini",
    "katana",
    "mari",
    "clarisse",
})

CLI_APPLICATIONS = frozenset({
    "bash",
    "python",
    "nuke_archive",
})
```

### command_launcher.py

**Replace** (lines 975-995):
```python
# ❌ OLD
def _is_gui_app(self, app_name: str) -> bool:
    """Check if an application is a GUI application."""
    gui_apps = {
        "3de", "nuke", "maya", "rv", "houdini", "mari", "katana", "clarisse",
    }
    return app_name.lower() in gui_apps
```

**With**:
```python
# ✅ NEW
def _is_gui_app(self, app_name: str) -> bool:
    """Check if an application is a GUI application."""
    return app_name.lower() in Config.GUI_APPLICATIONS
```

### terminal_dispatcher.sh

**Replace** (lines 85-126 with environment variable approach):
```bash
# Instead of is_gui_app() parsing the command, pass a flag from Python
# This eliminates fragile regex parsing

# Check environment variable set by Python
is_gui_app() {
    # If Python set SHOTBOT_IS_GUI_APP=true, this is a GUI app
    if [ "${SHOTBOT_IS_GUI_APP:-false}" = "true" ]; then
        return 0  # true
    fi
    return 1  # false
}
```

---

## FIX 7: Shell Script Error Handling (LOW)

### terminal_dispatcher.sh

**Before** (Line 2):
```bash
#!/bin/bash
set -o pipefail  # Enable pipefail to capture correct exit codes in pipelines
```

**After**:
```bash
#!/bin/bash
# Enable strict error handling
set -o pipefail  # Capture correct exit codes in pipelines
set -u            # Error on undefined variables
set -e            # Error on command failure (handled via ERR trap, but explicit is clearer)
```

**Also add documentation comment before eval() calls**:
```bash
# Execute command (pre-validated by command_launcher.py._validate_path_for_shell())
# Commands are validated on the Python side to prevent injection
log_info "Executing command (pre-validated): $cmd"
eval "$cmd &"
```

---

## Testing These Changes

After implementing these fixes, test with:

```bash
# Type checking
~/.local/bin/uv run basedpyright

# Linting
~/.local/bin/uv run ruff check .

# Run tests to verify QObject parent parameter fix
~/.local/bin/uv run pytest tests/unit/test_persistent_terminal_manager.py -v

# Run tests to verify command launcher changes
~/.local/bin/uv run pytest tests/unit/test_command_launcher.py -v

# Full regression
~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup
```

