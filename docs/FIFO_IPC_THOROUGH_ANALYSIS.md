# FIFO-Based IPC & Terminal Persistence Analysis

## Critical Issues Found

### ISSUE #1: BLOCKING LOCK DURING I/O RETRY LOOP (HIGH SEVERITY)

**Location**: `persistent_terminal_manager.py` lines 889-986 in `send_command()`

**Problem**: The `_write_lock` is held for the entire retry loop, which includes blocking sleep() calls. This serializes ALL terminal operations across threads.

**Code**:
```python
with self._write_lock:  # Lock acquired here
    if ensure_terminal:
        if not self._ensure_dispatcher_healthy():
            return False
    
    for attempt in range(max_retries):
        try:
            fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
            with os.fdopen(fifo_fd, "wb", buffering=0) as fifo:
                fifo_fd = None
                fifo.write(...)
            return True
        except OSError as e:
            if e.errno == errno.ENOENT:
                if not is_last_attempt:
                    time.sleep(_CLEANUP_POLL_INTERVAL_SECONDS)  # ← LOCK HELD!
                    if self._ensure_fifo():
                        time.sleep(_CLEANUP_POLL_INTERVAL_SECONDS)  # ← LOCK HELD!
                        continue
            elif e.errno == errno.ENXIO:
                if not is_last_attempt:
                    time.sleep(0.5)  # ← LOCK HELD!
                    continue
            elif e.errno == errno.EAGAIN:
                if not is_last_attempt:
                    backoff = 0.1 * (2 ** attempt)  # Up to 0.4s
                    time.sleep(backoff)  # ← LOCK HELD!
                    continue
```

**Impact**:
- Other threads waiting to send commands are blocked
- Health checks from other workers are blocked
- Heartbeat pings are blocked
- Total lock contention time: 0.2s + 0.5s + 0.4s = 1.1s maximum per retry cycle
- With 3 retries and worst-case sleeps, lock can be held for ~3+ seconds
- During this time, NO other command can be sent, heartbeats fail, health checks fail

**Recommendation**: 
- Release lock during sleep operations
- Only hold lock during actual open/write/close
- Implement backoff outside the lock:
```python
with self._write_lock:
    # Health check and initial attempt
    ...
    if not attempt_send():
        # Release lock before sleeping
        pass
# Outside lock - sleep and retry
for attempt in range(max_retries):
    time.sleep(backoff)
    with self._write_lock:
        if attempt_send():
            return True
```

---

### ISSUE #2: CONCURRENT FIFO RECREATION RACE (MEDIUM SEVERITY)

**Location**: `persistent_terminal_manager.py` lines 1330-1365 in `restart_terminal()`

**Problem**: Race condition between `restart_terminal()` and `send_command()` when both try to manage FIFO simultaneously.

**Scenario**:
```
Thread A (restart_terminal)           Thread B (send_command)
1. Acquires _restart_lock
2. _close_dummy_writer_fd()          
3. os.unlink(old_FIFO)
4. [Context switch]
                                     1. _write_lock acquired
                                     2. os.open() → ENOENT
                                     3. _ensure_fifo() called
                                     4. Creates NEW FIFO
5. os.mkfifo(temp_FIFO) → SUCCESS
6. os.rename(temp_FIFO, final) → OVERWRITES Thread B's FIFO
7. Dispatcher opens final_FIFO
                                     5. Commands written to FIFO but reader is NEW dispatcher
                                     6. Old/stale commands in old FIFO?
```

**Why It Matters**:
- Both threads can operate on FIFO independently (_restart_lock doesn't protect send_command's FIFO access)
- Old FIFO can be deleted while new FIFO is created by send_command
- New restart's FIFO can overwrite send_command's FIFO
- Dispatcher might not be reading from correct FIFO

**Code Evidence**: 
- `restart_terminal()` holds `_restart_lock` (line 1329)
- `send_command()` does NOT hold `_restart_lock` when calling `_ensure_fifo()` (line 923)
- No synchronization between restart and send_command FIFO operations

**Recommendation**:
- Acquire `_restart_lock` in `send_command()` when checking/creating FIFO
- Or: Use a FIFO version/generation counter to detect stale FIFOs
- Or: Prevent send_command from proceeding during restart window

---

### ISSUE #3: STALE PID FILE ACCUMULATION (LOW SEVERITY - Storage/Performance)

**Location**: `terminal_dispatcher.sh` lines 306-313

**Problem**: PID files are written to `/tmp/shotbot_pids/` but never cleaned up automatically.

**Code**:
```bash
pid_file="$PID_DIR/${app_name}_${timestamp}.pid"
echo "$gui_pid" > "$pid_file"
log_info "Wrote PID file: $pid_file"
```

**Impact**:
- PID files accumulate in `/tmp/shotbot_pids/`
- Each launched application creates one (e.g., `nuke_20251114_123456.pid`)
- Over time: hundreds of stale PID files
- ProcessVerifier scans all files in directory during verification (line 101-120 of process_verifier.py)
- Performance degrades as directory grows

**Example Accumulation**:
```
/tmp/shotbot_pids/
  nuke_20251114_100000.pid
  nuke_20251114_100100.pid
  nuke_20251114_100200.pid
  ... (100s of files)
  nuke_20251114_235959.pid
```

**Recommendation**:
- Implement automatic cleanup of PID files older than 24 hours
- Or: Cleanup during dispatcher startup
- Or: Use single PID file per app (overwrite, not accumulate)

---

### ISSUE #4: HEARTBEAT TIMEOUT RACE IN _send_heartbeat_ping() (MEDIUM SEVERITY)

**Location**: `persistent_terminal_manager.py` lines 569-600

**Problem**: Heartbeat response file can be stale or missed due to filesystem timing.

**Code**:
```python
def _send_heartbeat_ping(self, timeout: float = ...) -> bool:
    # Write heartbeat command
    if not self._send_command_direct("__HEARTBEAT__"):
        return False
    
    # Wait for response file
    start_time = time.time()
    while time.time() - start_time < timeout:
        if Path(self.heartbeat_path).exists():
            try:
                with open(self.heartbeat_path) as f:
                    response = f.read().strip()
                if response == "PONG":
                    return True
            except (FileNotFoundError, OSError):
                pass
        time.sleep(0.1)
    
    return False  # Timeout
```

**Race Conditions**:
1. File check passes, file is opened
2. Between check and open, file is deleted by dispatcher cleanup
3. Open raises FileNotFoundError
4. Continue looping until timeout

**Worse Case**:
1. Heartbeat sent successfully
2. Dispatcher writes PONG response atomically: `echo "PONG" > temp && mv temp heartbeat_file`
3. Between the write and our check, file is deleted (old timeout cleanup?)
4. We never see PONG
5. Health check fails

**Recommendation**:
- Verify heartbeat file is recent (check mtime)
- Don't rely on file existence alone - verify content is fresh
- Consider using nanosecond precision timestamps

---

### ISSUE #5: FIFO PERMISSION RACE (LOW SEVERITY - Security/Access)

**Location**: `persistent_terminal_manager.py` lines 301-303

**Problem**: FIFO created with `0o600` (user-only), but no verification after creation.

**Code**:
```python
os.mkfifo(self.fifo_path, 0o600)  # Only user can read/write
```

**Potential Issues**:
1. Umask could affect permissions
2. Directory permissions might be too restrictive
3. No verification that FIFO permissions are correct after creation
4. If another process creates stale FIFO with different permissions, mkfifo() fails silently

**Recommendation**:
- Verify permissions after creation
- Check both FIFO and parent directory permissions
- Explicitly set permissions with os.chmod() after mkfifo()

---

### ISSUE #6: ZOMBIE REAPER SUBPROCESS LEAK (LOW SEVERITY)

**Location**: `terminal_dispatcher.sh` lines 208-218

**Problem**: Background zombie reaper is started but never explicitly killed.

**Code**:
```bash
(
    while true; do
        wait -n 2>/dev/null
        sleep 0.1
    done
) &
REAPER_PID=$!
```

**Issues**:
- Reaper runs forever in infinite loop
- When dispatcher exits, reaper becomes orphaned
- init process (PID 1) becomes parent
- Reaper keeps running in background consuming CPU
- No mechanism to kill it on dispatcher exit

**Recommendation**:
- Add trap handler to kill reaper on exit
- Store REAPER_PID and kill in cleanup_and_exit()
- Or: Replace with built-in wait mechanism

---

### ISSUE #7: DUMMY WRITER FD DOUBLE-OPEN VULNERABILITY (LOW SEVERITY)

**Location**: `persistent_terminal_manager.py` lines 343-350

**Problem**: `_open_dummy_writer()` doesn't check if FD is already held before opening.

**Code**:
```python
def _open_dummy_writer(self) -> bool:
    with self._state_lock:
        if self._dummy_writer_fd is not None:
            return True  # Already open
        
        try:
            self._dummy_writer_fd = os.open(
                self.fifo_path, os.O_WRONLY | os.O_NONBLOCK
            )
```

**Race Scenario**:
```
Thread A                              Thread B
1. Check: _dummy_writer_fd is None
2. [Context switch - release lock]
                                     1. Check: _dummy_writer_fd is None  
                                     2. os.open() succeeds, FD=5
                                     3. _dummy_writer_fd = 5
3. os.open() succeeds, FD=6
4. _dummy_writer_fd = 6 (OVERWRITES FD 5!)
5. FD 5 now leaked
```

Wait, looking again - the whole block is inside `with self._state_lock`. So this race cannot happen. The check and open are atomic.

Actually, this is SAFE. The state lock protects against concurrent access. **Revising: NOT AN ISSUE.**

---

### ISSUE #8: HEARTBEAT FILE NOT CLEANED UP ON DISPATCHER EXIT (LOW SEVERITY)

**Location**: `terminal_dispatcher.sh` lines 41-42

**Problem**: Heartbeat file cleanup is done, but stale heartbeat files persist if dispatcher crashes.

**Code**:
```bash
cleanup_and_exit() {
    local exit_code=$1
    local reason=$2
    log_info "Dispatcher exiting: $reason (exit code: $exit_code)"
    rm -f "$HEARTBEAT_FILE"  # ← Only removes current heartbeat
    exec 3<&- 2>/dev/null || true
    exit "$exit_code"
}
```

**Issues**:
- Only removes `$HEARTBEAT_FILE` (default: `/tmp/shotbot_heartbeat.txt`)
- Multiple dispatcher instances might create different heartbeat files
- If dispatcher crashes before cleanup, file persists
- Health checks might read stale heartbeat from previous session

**Recommendation**:
- Include timestamp in heartbeat file name per instance
- Or: Verify heartbeat freshness (check mtime)
- Or: Use process-specific heartbeat files

---

### ISSUE #9: NO ATOMIC PID FILE WRITE IN DISPATCHER (MEDIUM SEVERITY)

**Location**: `terminal_dispatcher.sh` lines 310-312

**Problem**: PID file write is NOT atomic. Race between dispatcher write and ProcessVerifier read.

**Code**:
```bash
pid_file="$PID_DIR/${app_name}_${timestamp}.pid"
echo "$gui_pid" > "$pid_file"  # ← NOT atomic!
log_info "Wrote PID file: $pid_file"
```

**Race Scenario**:
```
Dispatcher (background GUI app write)  ProcessVerifier (verification read)
1. echo "$gui_pid" starts writing
2. [Partial write: file contains "1234" of "12345"]
                                       1. File exists!
                                       2. Read file content: "1234"
                                       3. Try: psutil.Process(1234)
3. [Context switch]
4. Finish write: "12345"              4. psutil.Process(1234) - WRONG PID!
5. File now contains "12345"          5. Verification uses wrong PID
```

**Better Example**:
- GUI app PID: 12345 (5 digits)
- Partial write: "123\n" (4 bytes before context switch)
- Verifier reads: 123 (wrong PID, might be unrelated process!)

**Recommendation**:
- Use atomic write pattern (already done in heartbeat!):
```bash
echo "$gui_pid" > "${pid_file}.tmp" && mv "${pid_file}.tmp" "$pid_file"
```
- Or: Write to temp, then atomically rename

---

### ISSUE #10: NO VALIDATION OF EXTRACTED APP NAME (LOW SEVERITY)

**Location**: `terminal_dispatcher.sh` lines 152-201 (extract_app_name) and `launch/process_verifier.py` lines 98-150

**Problem**: App name extraction from complex commands is fragile and not validated.

**Code** (dispatcher):
```bash
extract_app_name() {
    local cmd="$1"
    
    # Complex regex parsing...
    if [[ "$cmd" =~ bash[[:space:]]+-[^\"]*\"(.*)\" ]]; then
        # ... more parsing ...
    fi
    
    echo "$actual_cmd"  # Returns extracted name or empty
}
```

**Issues**:
1. If extraction fails, returns empty string
2. PID file created with empty app name: `/tmp/shotbot_pids/__<timestamp>.pid`
3. ProcessVerifier cannot find/identify the file
4. Process verification fails even though process started

**Code** (verifier):
```python
app_name = self._extract_app_name(command)
if not app_name:
    return True, "Could not extract app name (skipping verification)"
```

Verifier treats failed extraction as "OK" (returns success), but no process verification happened!

**Recommendation**:
- Validate extracted app name is non-empty
- Log warning/error if extraction fails
- Fall back to generic PID matching if extraction fails

---

## Summary Table

| # | Issue | Severity | Impact | Fixability |
|---|-------|----------|--------|-----------|
| 1 | Lock held during I/O sleeps | HIGH | 3+ sec lock contention | High - restructure retry logic |
| 2 | FIFO recreation race | MEDIUM | FIFO conflicts, lost commands | High - add sync point |
| 3 | Stale PID file accumulation | LOW | Dir bloat, perf degradation | High - add cleanup |
| 4 | Heartbeat file race | MEDIUM | Health check false negatives | Medium - add freshness check |
| 5 | FIFO permission issues | LOW | Potential access denied | Medium - add verification |
| 6 | Zombie reaper leak | LOW | Orphaned process, CPU usage | Medium - add trap handler |
| 7 | [Revised] Dummy writer FD | SAFE | N/A - protected by lock | N/A |
| 8 | Stale heartbeat file | LOW | False health checks | Low - add timestamp/cleanup |
| 9 | Non-atomic PID write | MEDIUM | Wrong PID in verification | High - use atomic write |
| 10 | App name validation | LOW | Verification skipped silently | High - add validation |

---

## Recommended Fix Priority

1. **CRITICAL**: Issue #1 (blocking lock) - Causes 3+ second delays
2. **HIGH**: Issue #9 (atomic PID write) - Data corruption potential  
3. **HIGH**: Issue #2 (FIFO race) - Concurrent operation issues
4. **MEDIUM**: Issue #4 (heartbeat race) - Health check reliability
5. **MEDIUM**: Issue #10 (app name validation) - Silent failures
6. **LOW**: Issues #3, #5, #6, #8 (cleanup/optimization)

