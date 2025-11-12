# FIFO Race Condition Analysis - Complete Execution Flow

## Executive Summary

**CRITICAL BUG CONFIRMED**: The current "non-persistent FD" approach DOES NOT fix the EOF race condition. Empirical testing proves that health checks cause bash to exit.

## Empirical Test Results

Test conducted: 2025-11-09

**Test Setup**:
- Bash script with `read -r cmd < "$FIFO"` in loop (mimics terminal_dispatcher.sh)
- Python script simulates health check: `os.open(O_WRONLY|O_NONBLOCK)` + immediate close

**Result**: 
```
Health check #1:
  - Opened FIFO (fd=3)
  - Closed FIFO immediately (no data written)
  ✗ BASH DIED! (This is the race condition)

Bash output:
[Iteration 1] Waiting for command (blocking on read)...
[Iteration 1] READ FAILED (EOF or error) - EXITING LOOP
Loop exited after 1 iterations
```

**Conclusion**: Opening FIFO for writing and immediately closing WITHOUT writing data causes bash's `read < FIFO` to return EOF, exiting the loop.

## Root Cause Analysis

### FIFO Semantics (Linux)

1. **Opening FIFO for reading (O_RDONLY)**:
   - Blocks until a writer connects
   - Returns file descriptor once writer exists

2. **Opening FIFO for writing (O_WRONLY|O_NONBLOCK)**:
   - Returns immediately if reader exists
   - Returns ENXIO (errno 6) if no reader

3. **Reading from FIFO**:
   - Blocks until data available
   - Returns 0 bytes (EOF) when ALL writers close
   - Returns failure (exit code 1) if EOF occurs before reading any data

### The Race Condition

**Timeline**:

```
1. Bash: read -r cmd < "$FIFO"
   └─> open(FIFO, O_RDONLY)  [BLOCKS waiting for writer]

2. Python health check: _is_dispatcher_running()
   └─> fd = os.open(FIFO, O_WRONLY|O_NONBLOCK)  [succeeds - bash is reader]

3. Bash: open() UNBLOCKS, returns FD
   └─> read() system call starts [waiting for data]

4. Python: os.close(fd)  [closes write FD, NO data written]

5. Bash: read() returns 0 bytes (EOF)
   └─> `read` command returns exit code 1 (FAILURE)

6. if read -r cmd < "$FIFO"; then
   └─> Condition FALSE (read failed)

7. else clause executes:
   log_error "Failed to read from FIFO (EOF or error)"
   break

8. Bash exits loop → script terminates
```

## Why Non-Persistent FD Doesn't Help

**Misconception**: Fresh FD on each iteration would avoid EOF issues.

**Reality**: The EOF happens DURING a single iteration:
- Iteration starts: `read < FIFO` opens FIFO
- Health check connects as writer, then disconnects
- Same iteration's read() gets EOF
- Iteration fails, loop exits

The "fresh FD" only matters BETWEEN iterations, not within a single iteration.

## Complete Execution Flow Diagrams

### 1. Startup Sequence

```
Python Main Thread:
  └─> User launches ShotBot GUI
      └─> No terminal launched yet (lazy launch)

User Action:
  └─> User clicks "Launch Nuke" button
      └─> launcher_controller.py: launch_application()
          └─> persistent_terminal_manager.py: send_command("nuke", ensure_terminal=True)

send_command():
  ├─> Check if fallback mode: NO
  ├─> Validate command: OK
  └─> ensure_terminal=True:
      └─> _ensure_dispatcher_healthy()
          ├─> _is_dispatcher_healthy()
          │   ├─> _is_dispatcher_alive() → dispatcher_pid is None
          │   └─> Returns FALSE
          │
          └─> Health check failed, attempt recovery:
              ├─> restart_attempts = 0 < max (3)
              ├─> Force kill terminal (none exists)
              └─> restart_terminal()
                  ├─> close_terminal() (nothing to close)
                  ├─> Clean up and recreate FIFO
                  └─> _launch_terminal()
                      ├─> subprocess.Popen([gnome-terminal, ...])
                      ├─> terminal_pid = process.pid
                      ├─> time.sleep(0.5)
                      └─> Poll for dispatcher_pid (up to 3s)
```

### 2. Terminal Dispatcher Startup

```
Bash Process (terminal_dispatcher.sh):
  ├─> Signal handlers setup
  ├─> Create heartbeat file
  ├─> Log: "Entering main command loop"
  └─> while true; do
      └─> read -r cmd < "$FIFO"
          └─> open(FIFO, O_RDONLY)
              └─> **BLOCKS** waiting for writer
                  (Bash is now stuck here)
```

### 3. Health Check Polling Loop (WHERE BUG OCCURS)

```
Python (_ensure_dispatcher_healthy):
  └─> restart_terminal() completed
      └─> Wait for dispatcher to become healthy:
          timeout = 5.0
          while elapsed < timeout:
              ├─> _is_dispatcher_healthy()
              │   ├─> _is_dispatcher_alive()
              │   │   ├─> Find dispatcher_pid via psutil
              │   │   └─> Check process exists → TRUE
              │   │
              │   ├─> _is_dispatcher_running()  ← **BUG HERE**
              │   │   ├─> fd = os.open(FIFO, O_WRONLY|O_NONBLOCK)
              │   │   │   └─> Succeeds (bash is reading)
              │   │   │       └─> Bash's open() UNBLOCKS
              │   │   │           └─> Bash calls read()
              │   │   │
              │   │   └─> os.close(fd)  ← **TRIGGERS EOF**
              │   │       └─> Bash's read() returns 0 bytes
              │   │           └─> `read` command returns FAILURE
              │   │               └─> if statement FALSE
              │   │                   └─> Loop EXITS
              │   │                       └─> Bash DIES
              │   │
              │   └─> Returns TRUE (incorrectly thinks it's healthy)
              │
              ├─> time.sleep(0.2)
              └─> Next poll:
                  └─> _is_dispatcher_alive()
                      └─> psutil.Process(dispatcher_pid)
                          └─> NoSuchProcess exception
                              └─> Returns FALSE
```

### 4. Command Execution (NEVER REACHES)

Because bash died during health check polling, the actual command send fails:

```
Python (send_command continued):
  └─> _ensure_dispatcher_healthy() returns FALSE
      └─> Log: "Failed to ensure dispatcher is healthy"
      └─> Returns FALSE

User sees:
  └─> Command failed to launch
```

## Why This Hasn't Been Noticed Yet

Possible reasons the bug might not manifest:

1. **Timing window is small**: If bash hasn't reached `read < FIFO` yet when health check runs
2. **Terminal not used**: If commands are sent via fallback mode
3. **No health checks run**: If ensure_terminal=False
4. **Lucky timing**: Race condition timing varies

## Remaining Race Conditions

### Race #1: Health Check During Startup (CONFIRMED)
- **When**: During _ensure_dispatcher_healthy() polling after terminal launch
- **Impact**: Bash exits immediately, terminal launch fails
- **Likelihood**: HIGH (happens every time during startup)

### Race #2: Health Check During Idle Wait
- **When**: Health check runs while bash is blocked waiting for next command
- **Impact**: Bash exits, subsequent commands fail
- **Likelihood**: MEDIUM (depends on health check frequency)

### Race #3: Concurrent Commands
- **When**: Two commands sent simultaneously
- **Impact**: FIFO write order undefined
- **Mitigation**: Write lock exists (line 513)

## The Fix That Would Actually Work

### Option A: Separate Health Check FIFO
```bash
# Health check FIFO (receive-only)
while read -r ping < "$HEALTH_FIFO"; do
    echo "PONG" > "$HEARTBEAT_FILE"
done &

# Command FIFO (receive commands)
while read -r cmd < "$COMMAND_FIFO"; do
    # Process command
done
```

**Pros**:
- Health checks can't interfere with command reads
- Clean separation of concerns

**Cons**:
- Two FIFOs to manage
- More complex setup

### Option B: Heartbeat-Only Health Check
```python
def _is_dispatcher_healthy(self) -> bool:
    # Check 1: Process exists
    if not self._is_dispatcher_alive():
        return False
    
    # Check 2: Send heartbeat and wait for PONG
    return self._send_heartbeat_ping(timeout=2.0)
```

Remove the `_is_dispatcher_running()` check entirely.

**Pros**:
- No FIFO interference
- Heartbeat already implemented

**Cons**:
- Slightly slower (need to send command and wait)
- Still uses FIFO (could trigger same race)

### Option C: Use Process State Only
```python
def _is_dispatcher_healthy(self) -> bool:
    # Only check if process is alive and not zombie
    return self._is_dispatcher_alive()
```

Remove FIFO-based health check entirely.

**Pros**:
- No race conditions
- Fast

**Cons**:
- Can't detect "stuck" dispatcher (process alive but not responding)

### Option D: Non-Blocking Read in Bash
```bash
# Set FIFO to non-blocking mode
exec 3< "$FIFO"
# Make FD 3 non-blocking
if fcntl_set_nonblock 3; then
    while true; do
        # Non-blocking read
        if read -t 0.1 -u 3 cmd; then
            # Process command
        fi
    done
fi
```

**Pros**:
- Could avoid blocking issues

**Cons**:
- Busy-wait loop (high CPU)
- Complex implementation
- Still has EOF issues

## Recommended Fix

**Recommendation**: Use **Option B (Heartbeat-Only)** with a modification:

```python
def _is_dispatcher_running(self) -> bool:
    """Check if dispatcher is running via heartbeat instead of FIFO check."""
    # Send heartbeat and wait for response
    # This writes actual data to FIFO, so bash reads it successfully
    return self._send_heartbeat_ping(timeout=1.0)
```

**Why**:
- Heartbeat sends ACTUAL data (`__HEARTBEAT__\n`)
- Bash's `read < FIFO` succeeds (reads heartbeat command)
- Bash processes it (writes PONG to file) and continues loop
- No EOF, no race condition
- Still validates dispatcher is responsive

**Implementation**:
1. Remove `_is_dispatcher_running()` FIFO open/close check
2. Replace with heartbeat ping
3. Bash handles `__HEARTBEAT__` command (already implemented)
4. Health check waits for PONG response

## Test Plan

1. **Unit test**: Verify _is_dispatcher_healthy() doesn't kill bash
2. **Integration test**: Launch terminal, run health checks, send commands
3. **Stress test**: Rapid health checks during command execution
4. **Concurrent test**: Multiple commands with health checks

## Files Requiring Changes

1. `/home/gabrielh/projects/shotbot/persistent_terminal_manager.py`:
   - Remove or fix `_is_dispatcher_running()` method (line 129-149)
   - Update `_is_dispatcher_healthy()` to use heartbeat only (line 299-333)

2. `/home/gabrielh/projects/shotbot/terminal_dispatcher.sh`:
   - Already handles heartbeat correctly (line 185-189)
   - No changes needed

## Verification

Run empirical test:
```bash
# Terminal 1: Start bash dispatcher
./test_fifo_race.sh

# Terminal 2: Run health check simulation
python3 test_fifo_race2.py

# Expected after fix:
# - Bash stays alive through health checks
# - Commands execute successfully
```
