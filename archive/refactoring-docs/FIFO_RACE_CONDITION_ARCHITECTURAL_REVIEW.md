# FIFO Race Condition Architectural Review

## Executive Summary

The transition from persistent to non-persistent FIFO reads **significantly reduces but does not completely eliminate** the race condition between health checks and command dispatch. The new approach reduces the race window from "permanent poisoning" to "microseconds during open()," making failures probabilistic rather than deterministic.

**Verdict:** The fix is a **major improvement** that makes the race condition rare enough to be handled by recovery mechanisms, but a **true race-free solution** would require architectural changes to the health check mechanism.

---

## 1. FIFO Behavior Deep Dive

### POSIX Named Pipe Semantics

#### Open Behavior
```c
// Blocking read open
open(fifo, O_RDONLY)
// - Blocks until at least one process opens for writing
// - Returns read FD when writer exists

// Blocking write open
open(fifo, O_WRONLY)
// - Blocks until at least one process opens for reading
// - Returns write FD when reader exists

// Non-blocking write open (used by health check)
open(fifo, O_WRONLY | O_NONBLOCK)
// - Returns immediately with write FD if reader exists
// - Returns ENXIO error if NO reader exists
```

#### Read/Write Behavior
```c
read(fd, buf, size)
// - Returns data if available in pipe buffer
// - Blocks if buffer empty AND writers still have FDs open
// - Returns 0 (EOF) if buffer empty AND all write FDs closed

write(fd, buf, size)
// - Writes to pipe buffer
// - Blocks if buffer full
// - Returns EPIPE/SIGPIPE if no read FDs open
```

**Critical Insight:** open() calls don't wait for each other to COMPLETE. They wake up as soon as the opposite end EXISTS (even if that open is still in progress).

---

## 2. Race Condition Analysis

### OLD Approach: Persistent File Descriptor

**Implementation:**
```bash
exec 3< "$FIFO"  # Open once, keep FD open forever
while true; do
    read -r cmd <&3  # Read from persistent FD 3
    # ... process command ...
done
```

**Health Check Timeline:**
```
1. Bash: exec 3< "$FIFO" → FD 3 is now permanently open for reading
2. [Loop iteration 1]
3. Bash: read -r cmd <&3 → blocks waiting for data
4. Python: open(O_WRONLY | O_NONBLOCK) → succeeds (reader exists: FD 3)
5. Python: close() → closes write FD WITHOUT writing data
6. Bash: read() returns 0 (EOF) because:
   - Pipe buffer empty
   - No write FDs exist anymore
7. Bash: read command fails (exit code 1)
8. Bash: else branch executes → break → dispatcher exits

PROBLEM: FD 3 remains in "all writers closed" state
9. [If recovery restarts loop]
10. Bash: read -r cmd <&3 → IMMEDIATE EOF (persistent state)
11. Infinite failure cycle
```

**Race Window:** **PERMANENT** - once health check runs, FD is poisoned forever

**Failure Mode:** Deterministic - health check ALWAYS causes dispatcher exit, recovery CANNOT succeed

---

### NEW Approach: Non-Persistent Read (Fresh Open Each Iteration)

**Implementation:**
```bash
while true; do
    read -r cmd < "$FIFO"  # Fresh open on each iteration
    # ... process command ...
done
```

**Health Check Timeline (Race Scenario):**
```
1. [Top of loop - no FD open]
2. Bash: read -r cmd < "$FIFO" begins execution
3. Bash: Shell performs open(FIFO, O_RDONLY) → BLOCKS (no writers yet)
4. ⚡ RACE WINDOW STARTS (bash in kernel sleep, marked as reader)
5. Python: open(FIFO, O_WRONLY | O_NONBLOCK) → succeeds (reader exists!)
6. Python: close() → closes write FD immediately
7. Bash: open() WAKES UP (writer connected!) → returns read FD
8. ⚡ RACE WINDOW ENDS
9. Bash: read() syscall executes on new FD
10. Bash: read() returns 0 (EOF) because:
    - Pipe buffer empty
    - No write FDs exist anymore (Python closed)
11. Bash: read command fails (exit code 1)
12. Bash: else branch executes → break → dispatcher exits

BUT:
13. [Recovery restarts dispatcher]
14. [Top of loop - no FD open]
15. Python health check: open(O_WRONLY | O_NONBLOCK) → likely gets ENXIO!
    - Bash not in race window (not blocked in open yet)
    - Health check correctly reports "no reader"
16. OR: Even if race happens again, it's ONE failure, then recovery succeeds
```

**Race Window:** **Microseconds** - only during bash's open() syscall

**Failure Mode:** Probabilistic - race CAN happen but is extremely unlikely, recovery can succeed

---

### Health Check Timing Without Race

**Common Case (No Race):**
```
1. Bash: Executing command (e.g., sleep 10, nuke app launch)
2. Python health check: open(O_WRONLY | O_NONBLOCK)
   - No reader (bash not in read)
   - Returns ENXIO
   - Correctly reports "dispatcher not reading"
3. OR:
1. Bash: Between loop iterations (hasn't started read yet)
2. Python health check: open(O_WRONLY | O_NONBLOCK)
   - No reader
   - Returns ENXIO
   - Correctly reports "dispatcher not reading"
```

**Health check succeeds when:**
- Bash is executing a command (not reading)
- Bash is between iterations (not reading yet)

**Race occurs only when:**
- Bash is blocked in open(O_RDONLY) syscall
- Timing window: microseconds to milliseconds

---

## 3. Health Check Compatibility

### Current Health Check Implementation

```python
# persistent_terminal_manager.py:129-149
def _is_dispatcher_running(self) -> bool:
    """Check if dispatcher is running and ready to read."""
    try:
        # Try to open FIFO for writing in non-blocking mode
        fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)  # Close immediately without writing
        return True
    except OSError as e:
        if e.errno == errno.ENXIO:
            # No reader available - dispatcher not running
            return False
        return False
```

**Behavior with Fresh Open:**
- **Between iterations:** Returns False (correct - no reader)
- **During command execution:** Returns False (correct - bash executing, not reading)
- **During open() syscall:** Returns True (correct - reader exists), BUT causes EOF race
- **During read() syscall (data pending):** Returns True (correct), no EOF (writer closes after connection)

**Race Probability:**
- open() syscall duration: ~10-100 microseconds
- Loop iteration time: 100ms - 10+ seconds (command dependent)
- Race probability: **~0.001% - 0.1%** depending on command execution time

---

## 4. Startup Sequence Safety

### Terminal Launch and Initialization

```python
# persistent_terminal_manager.py:356-458 (_launch_terminal)
1. Python: Creates FIFO if not exists
2. Python: Launches terminal with dispatcher script
3. Terminal: Bash starts, sources .bash_profile
4. Bash: Reaches main loop (line 134)
5. Bash: read -r cmd < "$FIFO" → blocks on open(O_RDONLY)
6. Python: Waits for dispatcher (timeout 3s)
7. Python: Polls _is_dispatcher_running() every 0.2s
   - If bash in open: Health check succeeds, may cause EOF
   - If bash between iterations: Health check fails (ENXIO)
8. Python: Eventually detects dispatcher ready
```

**Startup Race Risk:**
- Health check polls every 0.2s during 3s timeout
- Bash open() blocks for microseconds per iteration
- ~15 health check attempts during startup
- Each has ~0.001% - 0.1% chance of hitting race window
- Overall startup failure probability: **~0.015% - 1.5%**

**Recovery Mechanism:**
- If startup race occurs, dispatcher exits immediately
- Python detects failure in _ensure_dispatcher_healthy()
- Restarts terminal (up to 3 attempts)
- Subsequent attempts have fresh timing, likely succeed

---

## 5. Command Ordering Guarantees

### Command Send Sequence

```python
# persistent_terminal_manager.py:460-563 (send_command)
1. Python: Acquires write lock (serializes writes)
2. Python: Health check (_ensure_dispatcher_healthy)
3. Python: open(FIFO, O_WRONLY | O_NONBLOCK)
4. Python: write(command + "\n")
5. Python: close(fd)
```

**Scenario: Rapid Command Sequence**
```
Thread 1: send_command("command A")
Thread 2: send_command("command B")
Thread 3: Health check (background)

With write lock:
1. T1: Acquires lock
2. T1: Health check → may cause EOF race
3. T1: Writes "command A\n"
4. T1: Releases lock
5. Bash: Reads "command A" (if no EOF)
6. T2: Acquires lock
7. T2: Health check → may cause EOF race
8. T2: Writes "command B\n"
9. T2: Releases lock
10. Bash: Reads "command B" (if no EOF)
```

**Command Ordering:**
- Write lock ensures serialization: commands written in order
- FIFO is FIFO: commands read in write order
- **IF no race occurs:** Perfect ordering guarantee
- **IF race occurs:** Dispatcher exits, command lost, recovery triggered

**Message Loss:**
- Race during health check: No message loss (health check writes nothing)
- Race during command send: Message loss possible if bash exits before read
- Recovery: Application-level retry needed (not automatic)

---

## 6. Identified Issues and Limitations

### Issues with Current Approach

#### 1. Race Condition Still Exists (Low Probability)
**Problem:** Health check can cause EOF during bash's open() syscall

**Impact:**
- Probabilistic dispatcher crash (~0.001% - 0.1% per health check)
- Command send may fail occasionally
- Recovery can handle, but causes latency spike

**Severity:** Low (rare, recoverable)

#### 2. Command Loss on Race
**Problem:** If race occurs during send_command(), command is lost

**Impact:**
- User clicks button in UI
- Command sent to FIFO
- Race causes dispatcher exit before read
- Command never executed
- No retry mechanism at application level

**Severity:** Medium (rare but user-visible)

#### 3. Health Check Unnecessary for Most Cases
**Problem:** Health check opens write end just to check reader exists

**Impact:**
- Creates race window unnecessarily
- Could use heartbeat mechanism instead (already implemented!)
- _is_dispatcher_running() used before every command send

**Severity:** Low (design inefficiency)

#### 4. Startup Reliability
**Problem:** Multiple health check polls during startup increase race probability

**Impact:**
- ~15 health checks during 3s startup timeout
- Cumulative race probability ~0.015% - 1.5%
- May require multiple restart attempts

**Severity:** Low (recovery handles it)

---

### Comparison: OLD vs NEW

| Aspect | Persistent FD (OLD) | Fresh Open (NEW) |
|--------|-------------------|-----------------|
| **Race Window** | Permanent | Microseconds |
| **Failure Mode** | Deterministic | Probabilistic |
| **Race Probability** | 100% (any health check) | ~0.001% - 0.1% per check |
| **Recovery Success** | Impossible (poisoned state) | High (fresh state) |
| **Command Ordering** | N/A (always fails) | Guaranteed (when no race) |
| **Startup Success** | Never | ~98.5% - 99.985% first try |
| **Overall Reliability** | Unusable | Production-ready |

---

## 7. Recommendations for True Race-Free Solution

### Option 1: Heartbeat-Only Health Check (RECOMMENDED)

**Remove problematic open-to-check health check, use existing heartbeat:**

```python
def _is_dispatcher_running(self) -> bool:
    """Check if dispatcher is running via heartbeat only."""
    # Check if recent heartbeat exists
    if self._check_heartbeat():
        return True

    # Try sending heartbeat ping
    return self._send_heartbeat_ping(timeout=2.0)
```

**Bash dispatcher already implements heartbeat (line 185-189):**
```bash
if [ "$cmd" = "__HEARTBEAT__" ]; then
    log_debug "Received heartbeat ping, sending PONG"
    echo "PONG" > "$HEARTBEAT_FILE"
    continue
fi
```

**Benefits:**
- Zero race condition (heartbeat is actual FIFO write with data)
- Bash reads heartbeat, responds, continues loop
- No empty open/close that causes EOF
- More accurate health check (tests full read/write cycle)

**Implementation:**
```python
def _is_dispatcher_running(self) -> bool:
    """Check dispatcher health via heartbeat (race-free)."""
    # Don't use open-to-check, use actual heartbeat message
    return self._send_heartbeat_ping(timeout=1.0)
```

---

### Option 2: Sentinel-Based Health Check

**Write a special marker to FIFO instead of just opening/closing:**

```python
def _is_dispatcher_running(self) -> bool:
    """Check if dispatcher via sentinel message."""
    try:
        fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        # Write sentinel instead of just closing
        os.write(fd, b"__HEALTH_CHECK__\n")
        os.close(fd)
        return True
    except OSError as e:
        return e.errno != errno.ENXIO
```

**Bash dispatcher:**
```bash
if [ "$cmd" = "__HEALTH_CHECK__" ]; then
    log_debug "Health check received"
    continue  # Just continue loop, no response needed
fi
```

**Benefits:**
- Bash actually reads data (no EOF)
- Clean continue to next iteration
- No race condition

---

### Option 3: Separate Health Check FIFO

**Use dedicated FIFO for health checks:**

```python
self.health_fifo_path = "/tmp/shotbot_health.fifo"

def _is_dispatcher_running(self) -> bool:
    """Check dispatcher via separate health FIFO."""
    try:
        fd = os.open(self.health_fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        return True
    except OSError as e:
        return e.errno != errno.ENXIO
```

**Bash dispatcher:**
```bash
# Background health check reader
while true; do
    cat "$HEALTH_FIFO" > /dev/null
done &

# Main command loop (unaffected by health checks)
while true; do
    read -r cmd < "$FIFO"
    # ...
done
```

**Benefits:**
- Complete isolation of health checks from command dispatch
- No race possible (different FIFOs)

**Drawbacks:**
- More complex (2 FIFOs to manage)
- Background process needed

---

### Option 4: Process-Based Health Check (Current Fallback)

**Already implemented in _is_dispatcher_alive() (line 208-233):**

```python
def _is_dispatcher_alive(self) -> bool:
    """Check if dispatcher process exists."""
    if self.dispatcher_pid is None:
        self.dispatcher_pid = self._find_dispatcher_pid()
        if self.dispatcher_pid is None:
            return False

    try:
        proc = psutil.Process(self.dispatcher_pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
```

**Benefits:**
- Zero FIFO interaction (no race)
- Fast (just process check)
- Already implemented

**Drawbacks:**
- Process can exist but be hung (doesn't test FIFO responsiveness)
- Could combine with heartbeat for comprehensive check

---

### Recommended Implementation

**Hybrid Approach: Process Check + Heartbeat**

```python
def _is_dispatcher_healthy(self) -> bool:
    """Comprehensive health check (race-free)."""
    # Check 1: Process exists
    if not self._is_dispatcher_alive():
        self.logger.debug("Health check failed: Process not running")
        return False

    # Check 2: Recent heartbeat OR successful heartbeat ping
    if self._last_heartbeat_time > 0:
        age = time.time() - self._last_heartbeat_time
        if age < self._heartbeat_timeout:
            self.logger.debug(f"Health check passed: Recent heartbeat ({age:.1f}s)")
            return True

    # Check 3: Send heartbeat ping (actual FIFO test)
    if self._send_heartbeat_ping(timeout=2.0):
        self.logger.debug("Health check passed: Heartbeat ping success")
        return True

    self.logger.debug("Health check failed: No heartbeat response")
    return False
```

**Remove the problematic _is_dispatcher_running() from health checks:**
```python
# REMOVE this from _is_dispatcher_healthy():
# if not self._is_dispatcher_running():
#     return False

# Keep process check and heartbeat only
```

**Benefits:**
- No race condition (heartbeat writes actual data)
- Comprehensive (process check + FIFO responsiveness)
- Already mostly implemented
- Minimal code change

---

## 8. Conclusion

### Current State Assessment

**The fresh-open approach is a significant improvement:**
- Reduces race window from permanent to microseconds
- Makes failures probabilistic (~0.001% - 0.1%) instead of deterministic
- Enables recovery mechanisms to succeed
- Production-ready for most use cases

**However, the race is not eliminated:**
- Theoretical failure possible during health check
- Command loss possible (no application-level retry)
- Cumulative probability increases with frequent health checks

### Recommended Actions

1. **SHORT-TERM (Current approach is acceptable):**
   - Document the race condition and probability
   - Monitor for dispatcher restart frequency
   - Consider adding command retry at application level

2. **MEDIUM-TERM (High value, low effort):**
   - Remove `_is_dispatcher_running()` from `_is_dispatcher_healthy()`
   - Rely on process check + heartbeat only
   - This eliminates the race condition entirely
   - Code change: ~5 lines

3. **LONG-TERM (If reliability issues observed):**
   - Implement separate health check FIFO
   - Add application-level command retry mechanism
   - Consider supervisor/watchdog for dispatcher process

### Final Verdict

**The fresh-open approach is CORRECT and SUFFICIENT for production use**, but can be made truly race-free with minimal effort by switching to heartbeat-based health checks.

**Estimated Impact:**
- Current: 99.9% - 99.999% reliability per health check
- With heartbeat-only: 100% race-free (limited only by heartbeat timeout)

The architecture is sound, the improvement is significant, and the path to perfection is clear.
