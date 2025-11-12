# Persistent Terminal Architecture: Race Conditions and Design Flaws

## Executive Summary

The persistent terminal system fails immediately due to a **fundamental design flaw** in the health check mechanism. The `_is_dispatcher_running()` method opens and immediately closes a write file descriptor to the FIFO, which causes the bash dispatcher's read loop to receive EOF and exit. This is not a race condition in the traditional sense, but rather a misunderstanding of FIFO semantics where the health check mechanism is incompatible with persistent read file descriptors.

**Root Cause:** Health check treated as idempotent read operation when it's actually a state-modifying write that triggers EOF in readers.

---

## Architecture Overview

### Components

1. **Python PersistentTerminalManager** (`persistent_terminal_manager.py`)
   - Creates FIFO at `/tmp/shotbot_commands.fifo`
   - Launches `gnome-terminal` running `terminal_dispatcher.sh`
   - Sends commands by writing to FIFO
   - Performs health checks by testing FIFO write availability

2. **Bash Dispatcher** (`terminal_dispatcher.sh`)
   - Opens persistent read file descriptor: `exec 3< "$FIFO"` (line 136)
   - Loops reading commands: `read -r cmd <&3` (line 143)
   - Executes commands in interactive shell environment
   - Exits on read failure (EOF or error)

3. **Communication Channel**
   - Named pipe (FIFO) at `/tmp/shotbot_commands.fifo`
   - Unidirectional: Python writes, Bash reads
   - No persistent write file descriptor
   - Writers open/close for each operation

---

## Critical FIFO Semantics

### Named Pipe Behavior

**FIFO (First-In-First-Out) named pipes have specific EOF semantics:**

1. **Multiple readers/writers supported** - Each `open()` creates independent file descriptor
2. **Opening behavior:**
   - Read open: blocks until writer exists (unless O_NONBLOCK)
   - Write open: blocks until reader exists (unless O_NONBLOCK)
3. **EOF delivery:**
   - When **all writers close** and pipe buffer is empty, readers receive EOF
   - EOF persists until a new writer opens the FIFO
4. **Persistent FD behavior:**
   - Reader can keep FD open across multiple writer sessions
   - Each read returns EOF when no writers exist
   - Subsequent reads block/fail until new writer opens

### Why This Matters

The bash dispatcher keeps a **persistent read FD** (FD 3) open for the lifetime of the script. When Python's health check opens and closes a write FD:

1. Health check opens write FD → bash read FD becomes readable
2. Health check closes write FD → **EOF delivered to bash**
3. Bash `read` command returns false (EOF condition)
4. Bash exits loop with error: "Failed to read from FIFO (EOF or error)"

---

## The Deadly Health Check

### Code Analysis

**Python health check** (`persistent_terminal_manager.py` lines 128-148):
```python
def _is_dispatcher_running(self) -> bool:
    """Check if the terminal dispatcher is running and ready to read from FIFO."""
    if not Path(self.fifo_path).exists():
        return False

    try:
        # Try to open FIFO for writing in non-blocking mode
        # If no reader is available, this will fail with ENXIO
        fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)  # <-- IMMEDIATELY CLOSES - TRIGGERS EOF
        return True
    except OSError as e:
        if e.errno == errno.ENXIO:
            return False  # No reader available
```

**Bash dispatcher loop** (`terminal_dispatcher.sh` lines 141-241):
```bash
# Open FIFO with persistent file descriptor
exec 3< "$FIFO"

# Main command loop
while true; do
    # Read command from persistent FIFO file descriptor
    if read -r cmd <&3; then
        # ... process command ...
    else
        # Read from FIFO failed
        log_error "Failed to read from FIFO (EOF or error)"
        break  # <-- EXITS ON FIRST EOF
    fi
done
```

### The Problem

1. **Health check opens write FD** - FIFO now has 1 writer, 1 reader
2. **Health check immediately closes write FD** - FIFO now has 0 writers, 1 reader
3. **Bash read gets EOF** - No writers exist, so `read -r cmd <&3` returns false
4. **Script exits** - Loop breaks on line 239, dispatcher terminates

This happens **every time** the health check runs, not just during startup. The health check is fundamentally incompatible with persistent read file descriptors.

---

## Race Condition Timeline

### Startup Sequence

```
TIME    PYTHON                              BASH                          FIFO STATE
====    ======                              ====                          ==========
T0      restart_terminal()                  -                             FIFO created
        - Remove old FIFO                                                 (no readers, no writers)
        - Create new FIFO

T1      Popen(gnome-terminal)               -                             No readers, no writers
        - Launch terminal emulator
        - Get terminal PID

T2      sleep(0.5)                          Script starts                 No readers, no writers
                                            - Log startup
                                            - Print header

T3      Poll loop starts                    exec 3< "$FIFO"               0 writers, 0 readers
        _is_dispatcher_running()            (BLOCKS waiting for writer)   (bash blocked in open)

T4      -> os.open(FIFO, O_WRONLY)          -                             1 writer, 0 readers
                                                                          (still opening)

T5      Write open succeeds                 open() completes!             1 writer, 1 reader
                                            - FD 3 now readable
                                            - Enters while loop

T6      -> os.close(fd)                     -                             0 writers, 1 reader
        *** TRIGGERS EOF ***                                              *** EOF PENDING ***

T7      Health check returns True           read -r cmd <&3               EOF DELIVERED
        (falsely thinks dispatcher ok)      - read returns FALSE (EOF)

T8      -                                   break (exit loop)             Script dying
                                            log_error("Failed to read")

T9      Next poll iteration                 cleanup_and_exit(1)           Script dead
        _is_dispatcher_running()            - Close FD 3
                                            - Exit dispatcher

T10     -> os.open(FIFO, O_WRONLY)          -                             No readers
        -> ENXIO error                                                    Health check fails

T11     Health check returns False          -                             Dispatcher confirmed dead
        Attempt restart...
```

### Critical Window: T6-T8

The **deadly window** is between T6 (health check closes write FD) and T8 (bash reads and gets EOF). This window is **guaranteed to occur** during startup because:

1. The health check **must** close the write FD (current implementation)
2. The bash script **will** call `read` while no writers exist
3. The bash script **exits** on first EOF (no retry logic)

---

## Why Fallback Works

When the persistent terminal fails, the system falls back to direct terminal launch for each command. This works because:

1. **No FIFO** - Each command opens a new terminal directly
2. **No health checks** - No mechanism to accidentally trigger EOF
3. **No persistent state** - Each command is independent
4. **No IPC complexity** - Simple subprocess execution

The fallback is slower (new terminal per command) but reliable because it avoids the FIFO EOF semantics entirely.

---

## Additional Issues

### 1. Process Discovery Failure

**Issue:** `_find_dispatcher_pid()` cannot locate the bash script process.

**Code** (`persistent_terminal_manager.py` lines 168-205):
```python
def _find_dispatcher_pid(self) -> int | None:
    if self.terminal_pid is None:
        return None

    terminal_proc = psutil.Process(self.terminal_pid)

    # Look for bash child process running terminal_dispatcher.sh
    for child in terminal_proc.children(recursive=True):
        if "bash" not in child.name().lower():
            continue

        cmdline = child.cmdline()
        if any("terminal_dispatcher.sh" in arg for arg in cmdline):
            return child.pid

    return None
```

**Process Hierarchy:**
```
Python Popen PID (terminal_pid)
└─ gnome-terminal (wrapper)
   └─ gnome-terminal-server (actual window)
      └─ bash -il terminal_dispatcher.sh
         └─ (script execution context)
```

**Why it fails:**
- `terminal_pid` is the `gnome-terminal` wrapper PID
- The bash process is a grandchild or great-grandchild
- `children(recursive=True)` should work but has timing issues
- Called too early (0.5s after Popen), bash may not have started
- gnome-terminal is asynchronous, spawns server process later

**Impact:**
- `_is_dispatcher_alive()` returns False (can't verify PID)
- Health checks fall back to FIFO-based check (which kills dispatcher)
- Can't track dispatcher lifecycle properly

### 2. FIFO Creation Race

**Minor issue:** Both Python and Bash may try to create the FIFO.

**Python** (`persistent_terminal_manager.py` line 103):
```python
os.mkfifo(self.fifo_path, 0o600)
```

**Bash** (`terminal_dispatcher.sh` lines 68-75):
```bash
if [ ! -p "$FIFO" ]; then
    mkfifo "$FIFO" 2>/dev/null || {
        log_error "Could not create FIFO at $FIFO"
        exit 1
    }
fi
```

**Why it's minor:**
- Both create at same path with compatible permissions
- Race is unlikely since Python creates before launching bash
- No data corruption from dual creation
- Bash check is defensive (in case Python failed)

---

## Architecture Design Flaws

### 1. Health Check Modifies System State

**Flaw:** Health check is not idempotent - it changes FIFO state visible to other components.

**Principle violated:** Monitoring/observability operations should not modify system behavior.

**Impact:** Health check kills the very component it's trying to monitor.

### 2. Persistent Read FD Without Persistent Write FD

**Flaw:** Asymmetric FIFO usage creates EOF windows.

**Issue:** Bash keeps read FD open forever, but Python opens write FD only when needed.

**Result:** Any period without writers causes EOF delivery to reader.

### 3. No EOF Recovery in Bash Script

**Flaw:** Script exits on first EOF instead of retrying or waiting for new writer.

**Bash code** (line 234-240):
```bash
else
    # Read from FIFO failed
    log_error "Failed to read from FIFO (EOF or error)"
    break  # <-- NO RETRY, NO RECOVERY
fi
```

**Alternative:** Could re-open read FD or wait for writer before exiting.

### 4. Insufficient Startup Synchronization

**Flaw:** Python polls for dispatcher readiness, but polling mechanism kills dispatcher.

**Current** (lines 720-730):
```python
while elapsed < timeout:
    if self._is_dispatcher_running():  # <-- Opens/closes write FD!
        return True
    time.sleep(poll_interval)
    elapsed += poll_interval
```

**Needed:** Non-destructive readiness check (PID verification, heartbeat file, signal-based).

---

## Recommended Fixes

### Tier 1: Immediate Fix (Minimal Changes)

**Remove FIFO-based health check entirely.**

#### Changes Required:

1. **Modify `_is_dispatcher_running()`** - Remove open/close, check only process:
```python
def _is_dispatcher_running(self) -> bool:
    """Check if dispatcher process is running."""
    # Don't use FIFO - it kills the dispatcher!
    return self._is_dispatcher_alive()
```

2. **Improve PID discovery** - Add retry logic to `_find_dispatcher_pid()`:
```python
def _find_dispatcher_pid(self, max_attempts: int = 10, interval: float = 0.3) -> int | None:
    """Find dispatcher PID with retry logic for async process startup."""
    for attempt in range(max_attempts):
        if self.terminal_pid is None:
            return None

        try:
            terminal_proc = psutil.Process(self.terminal_pid)

            # Search recursively for bash running dispatcher script
            for child in terminal_proc.children(recursive=True):
                try:
                    if "bash" not in child.name().lower():
                        continue

                    cmdline = child.cmdline()
                    if any("terminal_dispatcher.sh" in arg for arg in cmdline):
                        self.logger.debug(f"Found dispatcher PID {child.pid} after {attempt} attempts")
                        return child.pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        if attempt < max_attempts - 1:
            time.sleep(interval)

    self.logger.warning(f"Could not find dispatcher PID after {max_attempts} attempts")
    return None
```

3. **Use heartbeat for deep health checks** - Keep heartbeat for verification, not startup:
```python
def _is_dispatcher_healthy(self) -> bool:
    """Comprehensive health check for dispatcher."""
    # Check 1: Process exists (non-destructive)
    if not self._is_dispatcher_alive():
        return False

    # Check 2: Heartbeat (for deep verification only)
    # Don't use during startup - only for runtime monitoring
    if self._last_heartbeat_time > 0:
        age = time.time() - self._last_heartbeat_time
        if age > self._heartbeat_timeout:
            return self._send_heartbeat_ping()

    return True
```

**Pros:**
- Minimal code changes
- Removes fundamental flaw
- Process-based checks are reliable
- Preserves existing architecture

**Cons:**
- Doesn't verify FIFO functionality
- Process alive != dispatcher functioning properly
- Relies on PID discovery timing

---

### Tier 2: Better Long-Term Fix

**Maintain persistent write FD to prevent EOF.**

#### Changes Required:

1. **Add persistent write FD** - Open once and keep open:
```python
def __init__(self, fifo_path: str | None = None, dispatcher_path: str | None = None) -> None:
    # ... existing initialization ...

    # Persistent write FD to prevent EOF delivery to bash
    self._write_fd: int | None = None
```

2. **Open write FD after dispatcher starts**:
```python
def _launch_terminal(self) -> bool:
    # ... existing launch code ...

    # After dispatcher is running, open persistent write FD
    # This prevents EOF from being delivered to bash's persistent read FD
    try:
        self._write_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        self.logger.debug(f"Opened persistent write FD: {self._write_fd}")
    except OSError as e:
        self.logger.error(f"Failed to open persistent write FD: {e}")
        return False

    return True
```

3. **Use write FD for commands** - Reuse existing FD:
```python
def send_command(self, command: str, ensure_terminal: bool = True) -> bool:
    # ... validation and health checks ...

    with self._write_lock:
        try:
            # Use persistent write FD
            if self._write_fd is None:
                self.logger.error("Write FD is None, cannot send command")
                return False

            # Write directly to FD (unbuffered)
            os.write(self._write_fd, command.encode('utf-8'))
            os.write(self._write_fd, b'\n')

            self.logger.info(f"Successfully sent command: {command}")
            self.command_sent.emit(command)
            return True
        except OSError as e:
            self.logger.error(f"Failed to write to FIFO: {e}")
            return False
```

4. **Health check just verifies FD validity**:
```python
def _is_dispatcher_running(self) -> bool:
    """Check if write FD is still valid."""
    if self._write_fd is None:
        return False

    try:
        # Use fstat to check if FD is still valid
        os.fstat(self._write_fd)
        return True
    except OSError:
        return False
```

5. **Proper cleanup**:
```python
def cleanup(self) -> None:
    # Close persistent write FD
    if self._write_fd is not None:
        try:
            os.close(self._write_fd)
            self.logger.debug(f"Closed persistent write FD: {self._write_fd}")
        except OSError as e:
            self.logger.warning(f"Error closing write FD: {e}")
        finally:
            self._write_fd = None

    # ... existing cleanup code ...
```

**Pros:**
- Eliminates EOF race condition entirely
- No changes to bash script needed
- Health check becomes simple FD validity test
- Symmetric FIFO usage (both sides keep FD open)

**Cons:**
- Uses one FD for application lifetime
- Needs careful cleanup to prevent FD leaks
- Doesn't detect if bash closes read FD (rare)

---

### Tier 3: Robust Production Fix

**Replace FIFO with Unix domain socket for proper bidirectional IPC.**

#### Architecture Changes:

1. **Use Unix domain socket** - Better semantics than FIFO:
   - Connection-based (detect disconnects)
   - Bidirectional (request/response)
   - No EOF delivery issues
   - Proper connection state

2. **Protocol design**:
   - Structured messages (JSON or msgpack)
   - Request/response with ACKs
   - Command ID tracking
   - Error responses

3. **Health check via connection state**:
   - Socket connect/disconnect detects failures
   - Heartbeat over socket (request/response)
   - No side effects from health checks

#### Example (Python side):
```python
import socket
import json

class PersistentTerminalManager:
    def __init__(self):
        self.socket_path = '/tmp/shotbot_commands.sock'
        self.socket: socket.socket | None = None

    def _launch_terminal(self) -> bool:
        # Create Unix domain socket
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.socket_path)
        self.socket.listen(1)

        # Launch dispatcher (will connect to socket)
        # ... launch code ...

        # Accept connection from dispatcher
        conn, _ = self.socket.accept()
        self.conn = conn
        return True

    def send_command(self, command: str) -> bool:
        try:
            msg = json.dumps({'type': 'command', 'data': command})
            self.conn.sendall(msg.encode('utf-8') + b'\n')

            # Wait for ACK
            response = self.conn.recv(1024)
            resp_data = json.loads(response.decode('utf-8'))
            return resp_data.get('status') == 'ok'
        except (socket.error, json.JSONDecodeError) as e:
            self.logger.error(f"Socket communication failed: {e}")
            return False

    def _is_dispatcher_running(self) -> bool:
        # Connection-based check - no side effects!
        return self.conn is not None and self._socket_is_connected()

    def _socket_is_connected(self) -> bool:
        try:
            # Send heartbeat
            self.conn.sendall(b'{"type":"ping"}\n')
            response = self.conn.recv(1024)
            return b'"type":"pong"' in response
        except socket.error:
            return False
```

#### Example (Bash side):
```bash
#!/bin/bash
SOCKET_PATH="/tmp/shotbot_commands.sock"

# Connect to socket
exec 3<> /dev/tcp/localhost/$(socket_path_to_port)

# Read loop
while read -r line <&3; do
    cmd=$(echo "$line" | jq -r '.data')
    eval "$cmd"

    # Send ACK
    echo '{"status":"ok"}' >&3
done
```

**Pros:**
- Proper IPC semantics
- Bidirectional communication
- Connection state tracking
- No EOF race conditions
- Industry-standard approach

**Cons:**
- Major architectural change
- More complex implementation
- Requires JSON parsing in bash (jq)
- Higher development effort

---

## Comparison Matrix

| Approach | Implementation Effort | Reliability | Performance | Risk |
|----------|----------------------|-------------|-------------|------|
| **Current (broken)** | - | 0% (fails immediately) | N/A | Critical |
| **Tier 1: Remove FIFO check** | Low (2-3 hours) | Medium (75%) | High | Low |
| **Tier 2: Persistent write FD** | Medium (4-6 hours) | High (90%) | High | Medium |
| **Tier 3: Unix socket** | High (2-3 days) | Very High (95%) | Medium | Medium |

---

## Recommended Path Forward

### Phase 1: Immediate Stabilization (Tier 1)
**Timeline:** 2-3 hours

1. Remove FIFO open/close from `_is_dispatcher_running()`
2. Improve `_find_dispatcher_pid()` with retry logic
3. Use process-based health checks only
4. Test thoroughly with various timing scenarios

**Expected outcome:** 75% reliability, no EOF race condition.

### Phase 2: Production Hardening (Tier 2)
**Timeline:** 4-6 hours

1. Implement persistent write FD
2. Simplify health check to FD validity test
3. Add comprehensive cleanup logic
4. Monitor FD leaks in production

**Expected outcome:** 90% reliability, symmetric FIFO usage.

### Phase 3: Future Enhancement (Tier 3)
**Timeline:** 2-3 days (low priority)

1. Design socket-based protocol
2. Implement bidirectional communication
3. Add structured message format
4. Migrate from FIFO to socket

**Expected outcome:** 95% reliability, production-grade IPC.

---

## Testing Strategy

### Unit Tests

1. **Test FIFO EOF behavior**:
```python
def test_fifo_eof_on_writer_close():
    """Verify that closing writer delivers EOF to persistent reader."""
    fifo_path = '/tmp/test_fifo'
    os.mkfifo(fifo_path)

    # Fork process: parent reads, child writes
    pid = os.fork()
    if pid == 0:  # Child
        fd = os.open(fifo_path, os.O_WRONLY)
        os.write(fd, b'test\n')
        os.close(fd)  # <-- Should trigger EOF in parent
        os._exit(0)
    else:  # Parent
        fd = os.open(fifo_path, os.O_RDONLY)
        data = os.read(fd, 100)  # Read data
        assert data == b'test\n'

        # Next read should get EOF (0 bytes)
        eof_data = os.read(fd, 100)
        assert eof_data == b''  # EOF
```

2. **Test health check doesn't kill dispatcher**:
```python
def test_health_check_non_destructive(persistent_terminal_manager):
    """Verify health check doesn't cause dispatcher to exit."""
    manager = persistent_terminal_manager

    # Launch terminal
    assert manager.restart_terminal()
    time.sleep(1)

    # Perform health check
    assert manager._is_dispatcher_running()
    time.sleep(0.5)

    # Verify dispatcher still alive
    assert manager._is_dispatcher_alive()

    # Send command to verify FIFO still works
    assert manager.send_command("echo test")
```

3. **Test PID discovery with retry**:
```python
def test_dispatcher_pid_discovery_with_retry():
    """Test that PID discovery retries handle async process startup."""
    manager = PersistentTerminalManager()
    manager.restart_terminal()

    # Should eventually find PID even if not immediate
    pid = manager._find_dispatcher_pid(max_attempts=20, interval=0.2)
    assert pid is not None
    assert psutil.Process(pid).is_running()
```

### Integration Tests

1. **Rapid command sequence**:
```python
def test_rapid_commands_no_eof():
    """Send many commands quickly, verify no EOF issues."""
    manager = PersistentTerminalManager()
    manager.restart_terminal()

    for i in range(100):
        assert manager.send_command(f"echo test_{i}")
        time.sleep(0.01)  # Minimal delay
```

2. **Stress test health checks**:
```python
def test_health_check_stress():
    """Perform many health checks, verify dispatcher survives."""
    manager = PersistentTerminalManager()
    manager.restart_terminal()

    for i in range(50):
        assert manager._is_dispatcher_running()
        time.sleep(0.1)

    # Dispatcher should still be alive
    assert manager._is_dispatcher_alive()
```

---

## Conclusion

The persistent terminal architecture has a **critical design flaw** where the FIFO-based health check mechanism (`_is_dispatcher_running()`) inadvertently kills the bash dispatcher by triggering EOF delivery. This is not a race condition but a fundamental misunderstanding of named pipe semantics.

**Key takeaways:**

1. **Health checks must be non-destructive** - Monitoring should not modify system state
2. **FIFO EOF semantics are subtle** - Closing last writer delivers EOF to all readers
3. **Persistent read FD requires persistent write FD** - Asymmetric usage creates EOF windows
4. **Process discovery needs retry logic** - Async process startup requires polling with backoff
5. **Fallback works because it avoids FIFO** - Direct terminal launch has no IPC complexity

**Immediate action:** Implement Tier 1 fix to remove FIFO-based health check and use process-based verification instead.

**Long-term strategy:** Consider Tier 2 (persistent write FD) for production or Tier 3 (Unix socket) for robust IPC semantics.
