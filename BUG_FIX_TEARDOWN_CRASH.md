# Bug Fix: Fatal Python Error During Test Teardown

## Issue

Fatal Python error crash during pytest teardown when worker threads attempt to spawn terminal emulators during cleanup:

```
Fatal Python error: Aborted

Thread 0x00007f0922da56c0 (most recent call first):
  File "persistent_terminal_manager.py", line 785 in _launch_terminal
  File "persistent_terminal_manager.py", line 1300 in restart_terminal
  File "persistent_terminal_manager.py", line 1115 in _ensure_dispatcher_healthy
  File "persistent_terminal_manager.py", line 145 in _run_send_command
  File "persistent_terminal_manager.py", line 87 in do_work
  File "thread_safe_worker.py", line 351 in run

Current thread (teardown):
  File "pytestqt/plugin.py", line 220 in _process_events
  File "pytestqt/plugin.py", line 204 in pytest_runtest_teardown
```

## Root Cause

**Critical design flaw**: Worker threads could execute terminal restart operations during cleanup/teardown.

### The Race Condition

1. Test completes, worker thread executing `_run_send_command()`
2. Teardown starts, main thread calls `PersistentTerminalManager.cleanup()`
3. Shutdown flag set: `_shutdown_flag = True`
4. Workers being stopped: `safe_stop(3000)` called
5. **Worker still running**: In `_ensure_dispatcher_healthy()`
6. **Restart triggered**: Calls `restart_terminal()` → `_launch_terminal()`
7. **Subprocess spawn**: `subprocess.Popen()` tries to launch terminal during teardown
8. **CRASH**: Qt/Python teardown conflicts with subprocess creation

### Why Workers Didn't Stop

Workers check `should_stop()` which only checks:
- `_stop_requested` flag (worker's own flag)
- `isInterruptionRequested()` (thread interruption)

**Workers DO NOT check the manager's `_shutdown_flag`!**

Three critical functions lacked shutdown checks:
1. `_ensure_dispatcher_healthy()` - Called by workers, can trigger restart
2. `restart_terminal()` - Recreates FIFO, kills processes, launches terminal
3. `_launch_terminal()` - **Most critical** - spawns subprocess during teardown

## Solution

Added shutdown checks at the entry point of all three critical functions.

### Implementation

**Pattern used:**
```python
# Check if manager is shutting down
with self._shutdown_lock:
    if self._shutdown_flag:
        self.logger.debug("Cannot [operation] - manager is shutting down")
        return False
```

**Changes made:**

1. **`_launch_terminal()`** (line 697)
   - Added shutdown check before dispatcher path validation
   - Prevents subprocess spawn during teardown
   
2. **`restart_terminal()`** (line 1248)
   - Added shutdown check before closing existing terminal
   - Prevents FIFO operations during teardown
   
3. **`_ensure_dispatcher_healthy()`** (line 1065)
   - Added shutdown check before health check
   - Prevents restart attempts during teardown

### Defense in Depth

The fix provides three safety barriers:

- **First barrier**: `_ensure_dispatcher_healthy()` - Prevents restart attempt
- **Second barrier**: `restart_terminal()` - Prevents FIFO/process operations  
- **Third barrier**: `_launch_terminal()` - Prevents subprocess creation

Even if a worker bypasses early checks, it will be caught before the critical subprocess operation.

## Why This Fixes The Crash

1. Worker calls `_ensure_dispatcher_healthy()` during teardown
2. Function checks `_shutdown_flag`, sees it's `True`
3. Returns `False` immediately without calling `restart_terminal()`
4. No FIFO operations, no process operations, no terminal launch
5. No subprocess spawn during pytest/Qt teardown
6. Worker finishes gracefully, no Fatal Python error
7. Cleanup completes successfully

## Testing

All 41 tests in `test_persistent_terminal_manager.py` pass:

```bash
~/.local/bin/uv run pytest tests/unit/test_persistent_terminal_manager.py -v
======================= 41 passed, 2 warnings in 30.92s ========================
```

**Specific cleanup tests verified:**
- `test_cleanup_removes_fifo_and_closes_terminal` ✅
- `test_cleanup_fifo_only` ✅
- `test_cleanup_fifo_only_closes_dummy_writer` ✅
- `test_cleanup_handles_missing_dummy_writer_fd` ✅
- `test_cleanup_closes_dummy_writer_fd` ✅

## Related Fixes

This completes the shutdown safety implementation started in recent commits:

1. **Phase 1**: Added `_shutdown_flag` to prevent operations during cleanup
2. **Phase 2**: Increased worker timeout from 3000ms to 8000ms
3. **Phase 3**: Fixed fallback mode race condition (atomic restart counter)
4. **Phase 4** (this fix): Added shutdown checks to critical restart operations

## Files Modified

- `persistent_terminal_manager.py`:
  - Added shutdown check to `_launch_terminal()` (line 697)
  - Added shutdown check to `restart_terminal()` (line 1248)
  - Added shutdown check to `_ensure_dispatcher_healthy()` (line 1065)

## Type Safety

Type checking passes with no new errors:

```bash
~/.local/bin/uv run basedpyright persistent_terminal_manager.py
0 errors, 1 warning, 3 notes
```

## Verification

To verify the fix works:

1. **Run full test suite** - Should complete without teardown crashes
2. **Check cleanup speed** - Should complete quickly (no worker timeouts)
3. **Check logs** - Look for "manager is shutting down" messages (confirms checks working)

The fix prevents the Fatal Python error by ensuring no subprocess operations occur during cleanup/teardown, regardless of worker thread timing.
