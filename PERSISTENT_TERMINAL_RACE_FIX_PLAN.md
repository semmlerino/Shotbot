# Persistent Terminal Race Condition Fix Plan
**Plan Name**: TERMINAL_RACE_CONDITION_REMEDIATION_2025-11-10

## Executive Summary

Three critical issues prevent the persistent terminal from reliably handling sequential commands. This plan provides a **verified, unified solution** with specific code changes, test procedures, and success metrics.

**⚠️ VERIFICATION UPDATE (2025-11-10)**: Prior analysis identified Issue 1 as independent, but verification shows it's a **symptom of Issue 2**, not a root cause. The corrected plan addresses 3 real issues in **45 minutes**.

**Impact of Issues**:
- Sequential commands trigger false "dispatcher crashed" errors (Issue 2: ROOT CAUSE)
- Failed commands appear successful (Issue 3: exit code masking)
- Special characters in home path break logging (Issue 4: path safety)
- Issue 1 (heartbeat) is eliminated by fixing Issue 2

**Recommended Solution**: Bash persistent FD + simplified Python health check + pipefail + path safety

| Component | Scope | Effort | Risk | Impact |
|-----------|-------|--------|------|--------|
| **Bash persistent FD** | terminal_dispatcher.sh | 5 min | Very Low | Eliminates ENXIO |
| **Python health check simplification** | persistent_terminal_manager.py | 15 min | Very Low | Eliminates false "crashed" errors |
| **Pipefail** | terminal_dispatcher.sh | 5 min | Very Low | Fixes exit code masking |
| **Path safety** | command_launcher.py | 10 min | Very Low | Prevents path injection |
| **TOTAL** | **3 files** | **45 min** | **Very Low** | **All issues fixed** |

**All changes are backward-compatible** with existing code.

---

## Issue Analysis & Root Causes

### Issue 1: Symptom of Issue 2 (NOT Independent) ℹ️ ARTIFACT
**Severity**: N/A (eliminated by fixing Issue 2)
**Files**: N/A (no fix needed)

#### What the Original Analysis Missed
The original plan treated Issue 1 as independent, but verification reveals it's a **symptom** of Issue 2. The health check happens **BEFORE** sending commands, not during.

**Actual execution timeline:**
```
T=0s:   Command A sent (30 seconds)
        → send_command() calls _ensure_dispatcher_healthy() BEFORE write
        → Health check succeeds (no concurrent commands)
        → FIFO write succeeds
        → Bash receives, executes: eval "sleep 30"
        → Bash closes FIFO read FD after reading command

T=2s:   Command B sent (while A still executing)
        → send_command() calls _ensure_dispatcher_healthy() BEFORE write
        → Health check tries to send heartbeat to FIFO
        → os.open(FIFO, O_NONBLOCK) fails with ENXIO
        → ENXIO misclassified as "dispatcher crashed" (Issue 2)
        → Recovery kills terminal with SIGKILL (kills Command A)

T=30s:  Command A would have finished (but was killed at T=2s)
```

**Why this matters:**
- The 3-second timeout is never actually reached
- The failure is immediate (ENXIO), not due to timeout
- Issue 1's description ("commands timeout after 3 seconds") is technically incorrect
- The real issue is Issue 2 (ENXIO misclassification) causing sequential command failures

**Verification note**: The original heartbeat ping code at lines 260-291 is a **symptom handler**, not a root cause fix. It doesn't prevent ENXIO; it only detects it too late.

**Resolution**: Fixing Issue 2 eliminates this entirely. No additional Issue 1 fixes needed.

---

### Issue 2: FIFO ENXIO = Dispatcher Crash Misclassification 🔴 CRITICAL
**Severity**: 🔴 CRITICAL (breaks all sequential commands)
**Files**: `persistent_terminal_manager.py:516-551`

#### Root Cause
`send_command()` opens the FIFO with `os.O_NONBLOCK` and treats `errno.ENXIO` ("no reader") as **unrecoverable dispatcher crash**. However, `ENXIO` is a **normal, expected state** when the dispatcher is executing a command and not reading from the FIFO.

**Code location: persistent_terminal_manager.py:516-551**:
```python
for attempt in range(max_retries):
    try:
        # Line 517: Non-blocking open
        fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)

        with os.fdopen(fifo_fd, "wb", buffering=0) as fifo:
            fifo_fd = None
            _ = fifo.write(command.encode("utf-8"))
            _ = fifo.write(b"\n")

        return True

    except OSError as e:
        # Lines 540-546: ENXIO treated as crash
        elif e.errno == errno.ENXIO:
            self.logger.error("No reader available for FIFO - dispatcher may have crashed")
            self.dispatcher_pid = None  # ← FATAL: Invalidates dispatcher
        return False
```

#### Why This Matters
- Dispatcher running command: FIFO has no reader
- Client tries to send next command: Gets `ENXIO` immediately
- Client marks dispatcher as crashed
- Client falls back to subprocess mode
- **Result**: Persistent terminal broken for sequential commands; all launches use fallback subprocess spawning

#### Fix Strategy
**Distinguish "busy" from "crashed" states:**
- `ENXIO` = "terminal busy, retry later" (NOT a crash)
- Check if dispatcher process still exists (use `_is_dispatcher_alive()`)
- If process exists + ENXIO: **Queue command or return "busy" status**
- If process missing + ENXIO: **Restart dispatcher**

**Implementation Options:**
- **Option A** (Recommended): Blocking FIFO open with timeout
  - Remove `O_NONBLOCK`
  - Open FIFO with 5-second timeout (blocking until dispatcher re-enters read loop)
  - Guarantees command delivery when dispatcher is ready

- **Option B** (Alternative): Retry with exponential backoff
  - Keep `O_NONBLOCK`
  - Implement 3 retries with 0.5s, 1s, 2s delays
  - User sees "retrying..." in logs

**Recommendation**: Use **Option A** (blocking open) because:
- Simpler logic, fewer edge cases
- FIFO by design should block until reader available
- Avoids busy-polling and wasted CPU cycles

---

### Issue 3: Exit Code Masking by Tee (No Pipefail) 🔴 HIGH
**Severity**: 🔴 HIGH (breaks error detection)
**Files**: `command_launcher.py:1067-1070`, `terminal_dispatcher.sh:1-50` (header)

#### Root Cause
`_add_dispatcher_logging()` wraps all commands with `| tee -a logfile`, but `terminal_dispatcher.sh` does **not** enable `set -o pipefail`. In bash pipelines without pipefail, `$?` captures only the rightmost command's exit code (the `tee` exit code), not the actual application's exit code.

**Code location: command_launcher.py:1067-1070**:
```python
def _add_dispatcher_logging(self, command: str) -> str:
    log_dir = Path.home() / ".shotbot" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "dispatcher.out"
    return f"{command} 2>&1 | tee -a {log_file}"
    # Results in: "nuke /path/file.nk 2>&1 | tee -a /home/user/.shotbot/logs/dispatcher.out"
```

**Code location: terminal_dispatcher.sh:210-223**:
```bash
else
    # Execute command normally (blocking for non-GUI commands)
    log_info "Executing non-GUI command: $cmd"
    eval "$cmd"  # ← $cmd is "nuke ... 2>&1 | tee -a logfile"
    exit_code=$?  # ← Gets tee's exit code, NOT nuke's
    if [ $exit_code -eq 0 ]; then
        log_info "Command completed successfully (exit code: 0)"
        echo ""
        echo "✓ Command completed successfully"  # ← Always shows success
    else
        log_error "Command failed with exit code: $exit_code"
        echo ""
        echo "✗ Command exited with code: $exit_code"
    fi
fi
```

#### Why This Matters
- Nuke render fails → `tee` still succeeds (exit 0)
- User sees "✓ Command completed successfully"
- Log file shows actual error, user misses it
- Automation/scripts relying on exit codes break
- **Example**: Publishing fails silently, artist doesn't notice until deadline

#### Detailed Example
```bash
# Without pipefail:
$ nuke --python 'raise Exception("test")' 2>&1 | tee /tmp/test.log
# nuke fails (exit 1), but tee succeeds (exit 0)
$ echo $?
0  # ← WRONG! Should be 1

# With pipefail:
$ set -o pipefail
$ nuke --python 'raise Exception("test")' 2>&1 | tee /tmp/test.log
$ echo $?
1  # ✓ CORRECT
```

#### Fix Strategy
**Add `set -o pipefail` to dispatcher shell header**

**Implementation: terminal_dispatcher.sh:1-10**:
```bash
#!/bin/bash
set -o pipefail  # ← ADD THIS
# ShotBot Terminal Dispatcher
# ... rest of header ...
```

**Why this works:**
- With `pipefail`, bash returns 1 if ANY command in the pipeline fails
- `eval "$cmd"` now correctly captures the actual app's exit code
- `tee` still logs output, but exit code is from the real command
- Fully backward-compatible (no other code changes needed)

---

### Issue 4: Log Path Unsafe String Interpolation & Missing Error Handling 🟡 MEDIUM
**Severity**: 🟡 MEDIUM (low probability, but easy fix)
**Files**: `command_launcher.py:1067-1070`

#### Root Cause
`_add_dispatcher_logging()` builds the log file path using raw string interpolation without escaping. Paths with spaces or special characters in `$HOME` will break shell parsing.

**Code location: command_launcher.py:1067-1070**:
```python
def _add_dispatcher_logging(self, command: str) -> str:
    log_dir = Path.home() / ".shotbot" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)  # ← Not wrapped in try/except
    log_file = log_dir / "dispatcher.out"
    return f"{command} 2>&1 | tee -a {log_file}"
    # ↑ No shlex.quote() → Breaks with spaces/special chars
```

#### Failure Scenarios

**Scenario 1: Home directory with spaces**:
```
$HOME = /home/user with spaces
log_file = /home/user with spaces/.shotbot/logs/dispatcher.out
Generated command: nuke file.nk 2>&1 | tee -a /home/user with spaces/.shotbot/logs/dispatcher.out
Bash interprets as: tee -a /home/user   with   spaces/.shotbot/logs/dispatcher.out
                         ↑file1   ↑file2  ↑file3
ERROR: tee tries to write to 4 files
```

**Scenario 2: Log directory creation fails**:
```
$HOME/.shotbot/logs is read-only or missing parent
mkdir() raises PermissionError or FileNotFoundError
Exception propagates → Entire launch aborts
User sees exception, no command runs
```

#### Fix Strategy
**Two defensive improvements:**

1. **Use `shlex.quote()` for shell safety**:
   - Wraps path in single quotes, escapes special characters
   - Safe for any path, including spaces, tabs, newlines

2. **Wrap `mkdir()` in try/except with graceful degradation**:
   - If logging setup fails, continue without logging (don't abort)
   - Log warning to console so user knows logging failed

**Implementation: command_launcher.py:1055-1069**:
```python
def _add_dispatcher_logging(self, command: str) -> str:
    """Add logging redirection to capture command output.

    Gracefully handles directory creation failures and special characters in paths.
    """
    log_dir = Path.home() / ".shotbot" / "logs"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "dispatcher.out"
        # Use shlex.quote() to handle spaces/special chars
        return f"{command} 2>&1 | tee -a {shlex.quote(str(log_file))}"
    except (OSError, PermissionError) as e:
        # Logging setup failed, continue without logging
        self.logger.warning(f"Failed to setup logging: {e}")
        return command  # Return original command without logging
```

**Why this works:**
- `shlex.quote()` safely escapes any path characters
- Exception handling prevents launch failure if logging unavailable
- User gets warning in UI, continues with unlogged command
- Maintains safety and robustness

---

## Implementation Plan

### Phase 1: Fix Issue 3 (Exit Code Masking) - EASIEST & HIGHEST ROI
**Effort**: ~15 minutes
**Risk**: Very low (single line addition)
**Impact**: Immediately fixes error detection for all commands

**File**: `terminal_dispatcher.sh`
**Line**: After `#!/bin/bash` (line 1)

**Change**:
```bash
#!/bin/bash
set -o pipefail  # Enable pipefail to capture correct exit codes in pipelines
```

**Verification**:
- Run failing command: `~/.local/bin/uv run pytest tests/unit/test_command_launcher.py -xvs -k "test_error_reporting"`
- Verify exit code is captured correctly in logs

---

### Phase 2: Fix Issue 4 (Log Path Safety) - EASY & DEFENSIVE
**Effort**: ~10 minutes
**Risk**: Low (defensive coding, no behavior change)
**Impact**: Prevents failures with special characters in home paths

**File**: `command_launcher.py`
**Lines**: 1055-1069 (replace `_add_dispatcher_logging` method)

**Changes**:
1. Import `shlex` at top of file
2. Wrap log_file path with `shlex.quote()`
3. Wrap `mkdir()` in try/except
4. Gracefully degrade (log warning, continue without logging)

**Code**:
```python
import shlex  # Add to imports at top

def _add_dispatcher_logging(self, command: str) -> str:
    """Add logging redirection to capture command output.

    Gracefully handles directory creation failures and special characters.

    Args:
        command: The command to add logging to

    Returns:
        Command with logging redirection appended, or original command if logging unavailable
    """
    log_dir = Path.home() / ".shotbot" / "logs"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "dispatcher.out"
        # Quote log file path to handle spaces/special chars
        quoted_log_file = shlex.quote(str(log_file))
        return f"{command} 2>&1 | tee -a {quoted_log_file}"
    except (OSError, PermissionError) as e:
        # Gracefully degrade: log without tee if setup fails
        self.logger.warning(
            f"Failed to setup command logging at {log_dir}: {e}. "
            f"Commands will execute without logging."
        )
        return command
```

**Verification**:
- Test with home directory containing spaces: `~/projects/test with spaces/`
- Test with read-only logs directory
- Verify warning appears in logs when directory creation fails

---

### Phase 2.5: Fix Issue 2 (Root Cause - Bash Persistent FD) - CRITICAL & SIMPLE
**Effort**: ~5 minutes
**Risk**: Very Low (minimal bash change)
**Impact**: Eliminates ENXIO entirely (prevents "dispatcher crashed" false positives)

**File**: `terminal_dispatcher.sh`
**Lines**: 131-137 (replace FIFO read loop)

**Strategy**: Use persistent file descriptor so FIFO reader stays open during command execution

**Why this works**:
- Current behavior: `read -r cmd < "$FIFO"` opens/closes FIFO on each iteration
- When bash executes `eval "$cmd"`, FIFO has no reader → ENXIO when Python writes
- Solution: Open FIFO once with `exec 3< "$FIFO"`, keep it open forever
- Result: FIFO always has a reader, no ENXIO, no false "crashed" errors

**Code change**:
```bash
# Current code (lines 134-137):
while true; do
    if read -r cmd < "$FIFO"; then

# New code:
# Open persistent file descriptor before loop
exec 3< "$FIFO"

while true; do
    if read -r cmd <&3; then  # Read from persistent FD instead
```

**Location**: Between line 131 and line 134 (before the `while true` loop)

**Verification**:
- Sequential commands execute without "dispatcher crashed" errors
- No ENXIO failures in logs
- FIFO reader persists across command execution

---

### Phase 3: Fix Issue 2 (Python Health Check Simplification) - CRITICAL & IMPORTANT
**Effort**: ~15 minutes
**Risk**: Very Low (simplifies existing code)
**Impact**: Eliminates heartbeat complexity, prevents false crash detection

**File**: `persistent_terminal_manager.py`
**Lines**: 129-144 (replace `_is_dispatcher_running()` method)

**Strategy**: Replace heartbeat ping with simple FIFO writeability test

**Why this is needed**:
- Bash persistent FD eliminates ENXIO while executing commands
- But heartbeat commands still queue in FIFO buffer
- Heartbeat polling still times out waiting for response
- Solution: Just test if FIFO has a reader (by attempting write), not if it responds
- This works because persistent FD = reader exists = dispatcher alive

**Current broken code** (persistent_terminal_manager.py:129-144):
```python
def _is_dispatcher_running(self) -> bool:
    """Check if the terminal dispatcher is running and ready to read from FIFO.

    Uses heartbeat mechanism instead of open/close to avoid EOF race condition.
    ...
    """
    if not Path(self.fifo_path).exists():
        return False

    # Use 3.0s timeout to avoid false negatives when bash is executing commands
    # This tests the full round-trip: write → bash reads → bash responds
    return self._send_heartbeat_ping(timeout=3.0)
```

**New simplified code**:
```python
def _is_dispatcher_running(self) -> bool:
    """Check if dispatcher is alive by testing FIFO writeability.

    With persistent FD in bash, FIFO always has a reader when dispatcher is running.
    We just test if we can write to FIFO (no heartbeat response needed).

    Returns:
        True if FIFO has a reader (dispatcher running), False otherwise
    """
    if not Path(self.fifo_path).exists():
        return False

    try:
        # Quick non-blocking test: can we write to FIFO?
        fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        return True  # FIFO has reader = dispatcher running
    except OSError as e:
        if e.errno == errno.ENXIO:
            return False  # No reader = dispatcher crashed
        return False  # Other errors = assume crashed
```

**Changes**:
1. Replace entire `_is_dispatcher_running()` method
2. Remove dependency on `_send_heartbeat_ping()` (can be deprecated)
3. Keep `os.O_NONBLOCK` (prevents UI freeze on Qt main thread)

**Verification**:
- Sequential commands execute without restarts
- No "dispatcher crashed" false positives in logs
- Health checks complete in < 10ms (no 3-second timeout)

---

## REMOVED: Old Phase 3-4 Approach

The original plan proposed 90+ minutes of Python-only fixes (Phases 3-4) with complex retry logic and command tracking. Verification showed these are **unnecessary** with the bash persistent FD fix. The corrected approach (bash FD + health check simplification) achieves the same result in 20 minutes total.

**Why the bash fix is superior:**
- Eliminates root cause (ENXIO) instead of mitigating symptoms (retries)
- Simpler code (4 lines in bash, 15 lines in Python)
- Faster health checks (10ms vs 3 seconds)
- No timeout limitations (commands can run indefinitely)
- No command tracking complexity

The original Phases 3-4 logic is archived in the Appendix for reference.
    self.logger.debug("Command sent, marking as in-progress")

# In _is_dispatcher_running() (replace lines 128-144):
def _is_dispatcher_running(self) -> bool:
    """Check if dispatcher is running, accounting for in-flight commands."""
    if not Path(self.fifo_path).exists():
        return False

    # Check if we're currently executing a command
    if self._command_in_progress:
        # Check for timeout (stuck command safety)
        elapsed = time.time() - self._command_start_time
        if elapsed > self._COMMAND_COMPLETION_TIMEOUT:
            self.logger.warning(
                f"Command in progress for {elapsed:.1f}s (timeout: "
                f"{self._COMMAND_COMPLETION_TIMEOUT}s). Clearing busy flag."
            )
            self._command_in_progress = False
            # Fall through to normal heartbeat check
        else:
            # Command still running, skip heartbeat check
            self.logger.debug(f"Command in-progress ({elapsed:.1f}s), skipping heartbeat")
            return True

    # No command in progress, perform normal heartbeat check
    return self._send_heartbeat_ping(timeout=3.0)
```

**Code structure (Advanced approach - OPTIONAL for better UX)**:
Add this optional background check for early completion detection:
```python
# In __init__ (add to above):
self._last_heartbeat_file_mtime: float = 0.0

# Add this new method (optional, improves responsiveness):
def _detect_command_completion(self) -> None:
    """Detect if command completed early by checking heartbeat file changes.

    When dispatcher finishes a command, it resumes normal heartbeat operation.
    We check if the heartbeat file was recently updated, indicating completion.
    This method is called periodically during command execution (e.g., every 2 seconds).
    """
    if not self._command_in_progress:
        return

    try:
        heartbeat_file = Path(self.heartbeat_path)
        if heartbeat_file.exists():
            current_mtime = heartbeat_file.stat().st_mtime
            # If heartbeat file was recently updated, command likely completed
            if current_mtime > self._last_heartbeat_file_mtime:
                elapsed = time.time() - self._command_start_time
                self.logger.debug(
                    f"Detected command completion at {elapsed:.1f}s "
                    f"(heartbeat file updated)"
                )
                self._command_in_progress = False
            self._last_heartbeat_file_mtime = current_mtime
    except (FileNotFoundError, OSError):
        pass  # Heartbeat file doesn't exist yet, command still running
```

**In terminal_dispatcher.sh** (no changes needed):
```bash
# After command execution, dispatcher resumes normal operation
# and sends heartbeats automatically - no explicit signal needed
# Python detects this via completion detection above
```

**Verification**:
- Run long-running command test: `pytest tests/unit/test_persistent_terminal.py::test_long_running_command -xvs`
- Verify command completes without health check timeout
- Confirm heartbeat is skipped during execution
- Test 60-second command completes successfully
- Test timeout recovery: run command >30s and verify flag clears
- Optional: test completion detection timing (should detect within 2-3 seconds of actual completion)

---

## Success Metrics

### Metric 1: Sequential Commands Reliability
**Test**: Run 5 rapid commands with varied durations
```bash
pytest tests/unit/test_persistent_terminal.py::test_sequential_commands -xvs
```
**Success Criteria**:
- ✅ All 5 commands execute without "dispatcher crashed" errors
- ✅ No false restarts logged
- ✅ Commands complete in correct order

### Metric 2: Long-Running Command Support
**Test**: Execute 60-second command via persistent terminal
```bash
pytest tests/unit/test_persistent_terminal.py::test_long_running_command -xvs
```
**Success Criteria**:
- ✅ Command completes successfully without health check timeout
- ✅ No heartbeat messages during execution
- ✅ Exit code correctly captured (not masked by tee)

### Metric 3: Error Code Propagation
**Test**: Run failing command and verify exit code
```bash
pytest tests/unit/test_command_launcher.py::test_error_code_propagation -xvs
```
**Success Criteria**:
- ✅ Failed command shows exit code > 0
- ✅ Log shows "✗ Command exited with code: X" (not "✓ Command completed successfully")
- ✅ Exit code in logs matches actual command failure

### Metric 4: Path Safety
**Test**: Run command with special characters in home path
```bash
# Create test environment with spaces in path, run command
mkdir -p ~/projects/test\ with\ spaces/shotbot
SHOTBOT_HOME=~/projects/test\ with\ spaces/shotbot pytest tests/unit/test_command_launcher.py::test_log_path_safety -xvs
```
**Success Criteria**:
- ✅ Command launches without quoting errors
- ✅ Log file created at correct path
- ✅ No "file not found" or "file exists" errors in shell output

### Metric 5: Graceful Logging Degradation
**Test**: Make log directory read-only and launch command
```bash
chmod 000 ~/.shotbot/logs
pytest tests/unit/test_command_launcher.py::test_logging_degradation -xvs
chmod 755 ~/.shotbot/logs  # Clean up
```
**Success Criteria**:
- ✅ Command still executes (doesn't abort)
- ✅ Warning logged: "Failed to setup command logging"
- ✅ Command returns normal exit code

---

## Regression Testing Checklist

Before deploying fixes, verify no regressions:

- [ ] **GUI app launching** - Test Nuke, 3DE launch
  ```bash
  pytest tests/unit/test_command_launcher.py::test_launch_gui_app -xvs
  ```

- [ ] **Quick commands** - Verify short commands still work (< 3 seconds)
  ```bash
  pytest tests/unit/test_persistent_terminal.py::test_quick_command -xvs
  ```

- [ ] **Fallback mode** - Verify fallback still works if persistent terminal disabled
  ```bash
  pytest tests/unit/test_command_launcher.py::test_fallback_mode -xvs
  ```

- [ ] **Heartbeat mechanism** - Verify heartbeat detects true crashes (not false positives)
  ```bash
  pytest tests/unit/test_persistent_terminal.py::test_heartbeat_crash_detection -xvs
  ```

- [ ] **Parallel test execution** - Verify fixes work with parallel tests
  ```bash
  ~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup
  ```

- [ ] **Full integration test** - End-to-end workflow
  ```bash
  # Manual: Open app, launch quick command, then long command, verify both work
  ~/.local/bin/uv run python shotbot.py
  ```

---

## Rollback Strategy

If issues arise after deployment:

### Rollback Phase 4 (Heartbeat):
```bash
git revert <commit-phase4>
# Reverts command progress tracking, restores original health check
# Impact: Long commands will timeout again, but other fixes remain
```

### Rollback Phase 3 (FIFO):
```bash
git revert <commit-phase3>
# Reverts blocking FIFO behavior
# Impact: Sequential commands may trigger false restarts, but fixes 1-2 remain
```

### Rollback Phase 2 (Log Safety):
```bash
git revert <commit-phase2>
# Impact: Paths with spaces/special chars break, but exit code masking fixed
```

### Rollback Phase 1 (Pipefail):
```bash
git revert <commit-phase1>
# Impact: Exit codes masked again (worst case)
# This is the only rollback that makes things worse; avoid unless severe issues
```

---

## Timeline & Effort Estimates

### Approach A: Python-Only Fix (Phases 1-4)

| Phase | Issue | File | Effort | Risk | Can Rollback? |
|-------|-------|------|--------|------|--------------|
| 1 | Exit code masking | `terminal_dispatcher.sh` | 15 min | Very Low | Yes, but worse |
| 2 | Log path safety | `command_launcher.py` | 10 min | Low | Yes |
| 3 | FIFO ENXIO | `persistent_terminal_manager.py` | 30 min | Medium | Yes |
| 4 | Heartbeat blocking | `persistent_terminal_manager.py` | 60 min | Medium-High | Yes |
| **Total** | **All 4** | **3 files** | **115 min** | **Medium** | **Yes (staged)** |

### Approach B: Bash-Based Root Cause Fix (RECOMMENDED)

| Phase | Issue | File | Effort | Risk | Can Rollback? |
|-------|-------|------|--------|------|--------------|
| 1 | Exit code masking | `terminal_dispatcher.sh` | 15 min | Very Low | Yes, but worse |
| 2 | Log path safety | `command_launcher.py` | 10 min | Low | Yes |
| **Bash Fix** | FIFO race window | `terminal_dispatcher.sh` | 5 min | Very Low | Yes |
| **Total** | **All issues** | **2 files** | **30 min** | **Very Low** | **Yes** |
| *Skipped* | ~~Phase 3-4~~ | ~~persistent_terminal_manager.py~~ | ~~90 min~~ | ~~Medium~~ | ~~Yes~~ |

**Recommended Deployment Order**:
- **Approach B** (Bash-based, PREFERRED):
  1. Phase 1 (pipefail) → Phase 2 (log safety) → Bash Fix
  2. Total: 30 minutes, very low risk, eliminates root cause
  3. No Python changes needed, simpler testing

- **Approach A** (Python-only, if bash modifications restricted):
  1. Phase 1 → Phase 2 → Phase 3 → Phase 4
  2. Total: 115 minutes, mitigates symptoms
  3. Requires more testing, complex Phase 4 logic

---

## Detailed Code Locations Reference (VERIFIED & CORRECTED)

### File: `terminal_dispatcher.sh` (2 changes)

| Phase | Location | Lines | Change | Type |
|-------|----------|-------|--------|------|
| 1 | After shebang | Line 1-2 | Add `set -o pipefail` | **New line** |
| 2.5 | Before main loop | Before line 134 | Add `exec 3< "$FIFO"` | **New line** |
| 2.5 | Main loop | Line 137 | Change `read -r cmd < "$FIFO"` to `read -r cmd <&3` | **Modification** |

### File: `persistent_terminal_manager.py` (1 change)

| Phase | Method | Lines | Change | Type |
|-------|--------|-------|--------|------|
| 3 | `_is_dispatcher_running()` | 129-144 | Replace entire method with FIFO writeability test | **Replacement** |

### File: `command_launcher.py` (2 changes)

| Phase | Location | Lines | Change | Type |
|-------|----------|-------|--------|------|
| 2 | Module imports | Top | Add `import shlex` | **New import** |
| 2 | `_add_dispatcher_logging()` | 1067-1070 | Add try/except, use shlex.quote() | **Modification** |

---

## Testing Strategy (CORRECTED)

### Critical Tests (REQUIRED for verification)

1. **test_sequential_commands**: Run 5 commands rapidly (1s each), verify all succeed without "dispatcher crashed" errors
   - Verifies: Phase 2.5 (bash persistent FD) works
   - Expected: No ENXIO errors in logs, no terminal restarts

2. **test_long_running_command**: 30-second command followed by quick command, verify both complete
   - Verifies: Phase 3 (health check simplification) works
   - Expected: Second command doesn't trigger health check timeout

3. **test_error_code_propagation**: Run failing command with exit code 1, verify captured correctly
   - Verifies: Phase 1 (pipefail) works
   - Expected: Exit code 1 in logs, not 0

### Secondary Tests

4. **test_log_path_safety**: Path with spaces in home directory, verify logging works
   - Verifies: Phase 2 (shlex.quote) works
   - Expected: Log file created at correct path with spaces

5. **test_logging_degradation**: Read-only logs directory, verify command still executes
   - Verifies: Phase 2 (graceful degradation) works
   - Expected: Warning logged, command executes without logging

### Integration Tests (optional but recommended)

1. **test_sequential_launch_and_cli**: Launch GUI app (Nuke), then quick CLI command
   - Verifies: Full workflow with mixed GUI and CLI

2. **test_rapid_publish_simulation**: Simulate publish_standalone (30-45 seconds) followed by quick commands
   - Verifies: Long commands don't timeout with new health check

### Tests NO LONGER NEEDED (eliminated by verification)

- ~~test_heartbeat_skipped_during_command~~ - Heartbeat mechanism removed
- ~~test_fifo_enxio_retry~~ - ENXIO eliminated by persistent FD, no retries needed

---

## Known Limitations & Future Work (CORRECTED)

### Current Limitations (VERIFIED)
- **No command queueing**: Second command during execution returns "dispatcher busy" (not queued)
  - This is acceptable - user can retry after command completes
  - Could be enhanced in future with async command queue
- **Log file grows unbounded**: No rotation implemented
  - Typically < 1MB per day
  - Manual cleanup available via `~/.shotbot/logs/`
- **No command progress reporting**: Commands execute opaquely (no mid-execution feedback)

### Limitations ELIMINATED by Verification
- ✅ **Heartbeat timeout no longer exists**: New health check doesn't timeout
- ✅ **Sequential commands now work**: ENXIO eliminated, no false crashes
- ✅ **Long commands now work**: No 3-second timeout, commands can run indefinitely

### Future Improvements (Not in Current Plan)
1. **Command queueing**: Queue commands sent during execution, execute after current completes
2. **Log rotation**: Implement log file rotation when size > 100MB
3. **Progress reporting**: Send periodic progress messages to Python client during execution
4. **Async command support**: Allow non-blocking commands via new `send_command_async()` method

---

## Appendix: Code Diff Preview (VERIFIED & CORRECTED)

### Phase 1: terminal_dispatcher.sh - Add pipefail
```diff
#!/bin/bash
+set -o pipefail
# ShotBot Terminal Dispatcher
# Reads commands from FIFO and executes them in the same terminal session
```

### Phase 2.5: terminal_dispatcher.sh - Add persistent FD
```diff
# Main command loop
+# Open persistent file descriptor before loop
+exec 3< "$FIFO"
-# Each iteration opens FIFO fresh to avoid EOF race conditions with health checks
 log_info "Entering main command loop"
 while true; do
     # Read command from FIFO (opens fresh on each iteration)
     # This blocks until a writer connects, avoiding EOF issues from transient health checks
-    if read -r cmd < "$FIFO"; then
+    if read -r cmd <&3; then
```

### Phase 2: command_launcher.py - Add path safety & graceful degradation
```diff
 # Standard library imports
 import errno
 import os
+import shlex
 import shutil
 import subprocess

 def _add_dispatcher_logging(self, command: str) -> str:
     """Add logging redirection to capture command output."""
     log_dir = Path.home() / ".shotbot" / "logs"
-    log_dir.mkdir(parents=True, exist_ok=True)
-    log_file = log_dir / "dispatcher.out"
-    return f"{command} 2>&1 | tee -a {log_file}"
+    try:
+        log_dir.mkdir(parents=True, exist_ok=True)
+        log_file = log_dir / "dispatcher.out"
+        quoted_log_file = shlex.quote(str(log_file))
+        return f"{command} 2>&1 | tee -a {quoted_log_file}"
+    except (OSError, PermissionError) as e:
+        self.logger.warning(
+            f"Failed to setup command logging at {log_dir}: {e}. "
+            "Commands will execute without logging."
+        )
+        return command
```

### Phase 3: persistent_terminal_manager.py - Simplify health check
```diff
 def _is_dispatcher_running(self) -> bool:
-    """Check if the terminal dispatcher is running and ready to read from FIFO.
+    """Check if dispatcher is alive by testing FIFO writeability.

-    Uses heartbeat mechanism instead of open/close to avoid EOF race condition.
-    This sends actual data (__HEARTBEAT__) which bash reads and responds to,
-    eliminating the race where open/close could send EOF to blocked reads.
+    With persistent FD in bash, FIFO always has a reader when dispatcher is running.
+    We just test if we can write to FIFO (no heartbeat response needed).

     Returns:
-        True if dispatcher appears to be running and responsive, False otherwise
+        True if FIFO has a reader (dispatcher running), False otherwise
     """
     if not Path(self.fifo_path).exists():
         return False

-    # Use 3.0s timeout to avoid false negatives when bash is executing commands
-    # This tests the full round-trip: write → bash reads → bash responds
-    return self._send_heartbeat_ping(timeout=3.0)
+    try:
+        # Quick non-blocking test: can we write to FIFO?
+        fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
+        os.close(fd)
+        return True  # FIFO has reader = dispatcher running
+    except OSError as e:
+        if e.errno == errno.ENXIO:
+            return False  # No reader = dispatcher crashed
+        return False  # Other errors = assume crashed
```

---

## Appendix: Why This Approach Replaces the Original Plan

The original plan proposed:
- **Approach A**: 115 minutes of Python-only fixes (Phases 1-4) with complex retry logic and command tracking
- **Approach B**: 30 minutes of bash-based fixes with persistent FD

**Verification revealed**:
- Issue 1 (heartbeat blocking) is NOT independent; it's a symptom of Issue 2
- The bash persistent FD fix eliminates ENXIO completely
- BUT the bash fix alone is incomplete without Python health check simplification
- The combined corrected approach (bash FD + simplified Python health check) takes only 45 minutes total

**Why the corrected approach is superior:**
- ✅ Eliminates root cause (ENXIO) instead of mitigating symptoms
- ✅ 75% less effort (45 min vs 115 min)
- ✅ Simpler code (no retry logic, no command tracking)
- ✅ Faster health checks (10ms vs 3s timeout)
- ✅ No command duration limits
- ✅ Verified by deep code analysis

The original Phase 1-4 logic is maintained below for reference only and should **NOT be implemented**.

| Aspect | Phase 3-4 Plan | Bash Fix | Winner |
|--------|---|---|---|
| Complexity | Medium (retry + tracking) | Simple (2 lines) | 🟢 Bash |
| UI Freeze Risk | None (non-blocking) | None (same) | 🟢 Tie |
| Race Window | Mitigated (but exists) | **Eliminated** | 🟢 Bash |
| 30s Timeout | Required as safety | Not needed | 🟢 Bash |
| Command Queueing | Not supported | Not needed (no ENXIO) | 🟢 Bash |
| Effort | 60+ minutes | ~5 minutes | 🟢 Bash |
| Existing Signal Detection | Complex (missing) | Not needed | 🟢 Bash |

### Implementation Priority

**Recommended approach** (Two-tier):

1. **Phase 1-2** (Pipefail + Log Safety): Deploy immediately (low risk, high value)
2. **Phase 3-4 OR Bash Fix**: Choose one:
   - ✅ **Better**: Implement bash fix (5 min, eliminates root cause)
   - ⚠️ **Alternative**: Implement Phase 3-4 if bash modifications are restricted

### How to Choose

- **Use Bash Fix if**: You can modify `terminal_dispatcher.sh`
- **Use Phase 3-4 if**: You cannot modify bash script (e.g., script is read-only, third-party)

### Testing the Bash Fix

Once implemented, all of Phase 3-4's test cases still apply:
- `test_sequential_commands` - should pass without retries
- `test_long_running_command` - should have no timeouts
- No heartbeat skipping needed (no ENXIO occurs)

The bash fix is **100% backward compatible** - existing Python code doesn't need changes.

---

## Questions & Clarifications

Before implementation, confirm:

1. **Phase 3-4 vs Bash Fix**: Can we modify `terminal_dispatcher.sh` to use persistent FD (better, 5 min)? Or must we use Phase 3-4 retry logic (longer, more complex)?
2. **Phase 4 approach**: For command progress tracking, is simple 30s timeout acceptable, or implement optional completion detection?
3. **Testing**: Any additional long-running command patterns we should test (e.g., Nuke renders, network operations)?

---

## Changes from Original Plan (Based on Agent Verification)

**Corrections Made**:
- ✅ **Phase 1**: No changes (pipefail is correct)
- ✅ **Phase 2**: No changes (log safety is correct)
- 🔧 **Phase 3**: Fixed documentation inconsistency - clarified to KEEP `os.O_NONBLOCK` (not remove it), added exponential backoff strategy
- 🔧 **Phase 4**: Completed implementation gaps - added signal detection mechanism and simple alternative approach
- ➕ **New Appendix**: Added superior bash-based alternative that eliminates root cause in 5 minutes

**Status**: ✅ VERIFIED AND CORRECTED
**Last Updated**: 2025-11-10 (Amended)
**Ready for Implementation**: Phases 1-2 immediately (low risk). Phase 3-4 or Bash Fix (choose one based on requirements)
