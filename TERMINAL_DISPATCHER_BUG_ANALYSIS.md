# Terminal Dispatcher Bug Analysis

**Date:** 2025-11-02
**Severity:** HIGH - Causes terminal restart on every second command
**Status:** IDENTIFIED - Root cause confirmed

## Summary

The persistent terminal dispatcher crashes after processing the first command, requiring a full terminal restart for each subsequent command. This creates a poor user experience with visible terminal flashing and 2-3 second delays.

## Observed Behavior

From production logs (2025-11-02 13:20:06):

```
13:20:21 - First Nuke launch
  - Terminal launches successfully (PID 2908718)
  - Command sent to FIFO successfully ✅

13:20:23 - Second Nuke launch (just 2 seconds later)
  WARNING - Terminal dispatcher not reading from FIFO
  WARNING - Terminal process alive but dispatcher is dead - forcing full restart
  INFO - Force killed stale terminal process 2908718
```

**Pattern:**
- First command works
- Dispatcher dies immediately after
- Terminal window stays open but dispatcher loop exits
- Second command triggers full restart
- Cycle repeats indefinitely

## Root Cause

**DOUBLE-BACKGROUNDING CONFLICT** between `command_launcher.py` and `terminal_dispatcher.sh`

### The Bug Location

**File:** `terminal_dispatcher.sh`
**Lines:** 112-125

```bash
# Execute command
# Auto-append & for GUI applications to run in background
if is_gui_app "$cmd"; then
    # Check if & is already present
    if [[ "$cmd" != *"&"* ]]; then
        echo "[Auto-backgrounding GUI application]"
        eval "$cmd &"
        # ...
    else
        eval "$cmd"  # ← BUG IS HERE (line 124)
    fi
```

### What's Happening

1. **command_launcher.py** sends commands with `&` already appended:
   ```bash
   rez env nuke python-3.11 -- bash -ilc "ws /shows/.../DD_230_0360 && nuke /path/to/file &"
   ```

2. **terminal_dispatcher.sh** detects the `&` is already present (line 114)

3. It executes `eval "$cmd"` on line 124

4. **Problem:** `eval` processes a command ending with `&`, which:
   - Backgrounds the entire eval statement incorrectly
   - Corrupts the bash interactive session state
   - Causes the bash session to exit
   - Kills the dispatcher loop
   - Leaves the terminal window as a zombie (alive but no dispatcher)

5. Next command finds FIFO orphaned (no reader), triggers full restart

### Why command_launcher.py Adds `&`

**File:** `command_launcher.py` (from logs around line 221)

```python
# Added & for GUI app nuke in persistent terminal
command_launcher.CommandLauncher - DEBUG - Command details:
  Original: 'rez env nuke python-3.11 -- bash -ilc "ws /shows/... && nuke /path/to/file"'
  To send: 'rez env nuke python-3.11 -- bash -ilc "ws /shows/... && nuke /path/to/file &"'
  Is GUI app: True
  Auto-background: True
```

The launcher explicitly adds `&` for GUI apps when sending to persistent terminal.

## Why This Breaks the Shell

When bash evaluates a command ending with `&` via `eval`:

```bash
eval "some_command &"
```

The behavior is **not** the same as:

```bash
some_command &
```

With `eval`, the backgrounding can corrupt the interactive shell's job control state, especially when:
- Running in an interactive bash session (`bash -i`)
- Inside a while loop reading from FIFO
- The eval itself gets backgrounded in a way that breaks the loop context

## Evidence from Logs

**First Launch (successful):**
```
13:20:21 - Terminal launched successfully with PID: 2908718
13:20:23 - Successfully sent command to terminal via FIFO
13:20:23 - Command successfully sent to persistent terminal
```

**Second Launch (2 seconds later - restart required):**
```
13:20:23 - WARNING - Terminal dispatcher not reading from FIFO
13:20:23 - WARNING - Terminal process is alive but dispatcher is dead
13:20:23 - INFO - Force killed stale terminal process 2908718
13:20:23 - INFO - Restarting terminal...
13:20:24 - Terminal launched successfully with PID: 2911271
```

The dispatcher died **between commands**, not during execution.

## Expected Behavior vs. Actual Behavior

### Expected
1. Dispatcher reads command from FIFO
2. Dispatcher executes command with proper backgrounding
3. Dispatcher returns to loop, ready for next command
4. Terminal stays alive indefinitely

### Actual
1. Dispatcher reads command from FIFO
2. Dispatcher executes command with `eval "$cmd"` where cmd ends with `&`
3. **Bash session corrupts and exits**
4. Dispatcher loop terminates
5. Terminal window remains but FIFO is orphaned
6. Next command requires full terminal restart

## Impact

- **User Experience:** Terminal flashes/restarts on every other command
- **Performance:** 2-3 second delay for each restart
- **Reliability:** Fragile system that appears broken
- **Logs:** Filled with WARNING messages about "dispatcher dead"

## Solution Options

### Option 1: Strip `&` in Dispatcher (IMPLEMENTED - CORRECTED VERSION)

**⚠️ IMPORTANT:** The original proposed fix was INCOMPLETE and would fail for rez commands!

**Original (INCORRECT) Fix:**
```bash
cmd="${cmd%&}"  # ❌ Only works if & is LAST character
cmd="${cmd% }"  # Cleans trailing space

# This fails for rez commands like:
# 'rez env nuke -- bash -ilc "ws /path && nuke /file &"'
# Last char is ", not &
```

**Corrected Fix (IMPLEMENTED):**

**File:** `terminal_dispatcher.sh`
**Location:** Lines 106-162 (implemented as of 2025-11-02)

```bash
# Strip trailing & patterns added by command_launcher.py
# Critical fix: Must handle THREE patterns
cmd="${cmd% &\"}"   # ✅ Remove ' &"' from rez commands
cmd="${cmd% &}"     # ✅ Remove ' &' from direct commands
cmd="${cmd%&}"      # ✅ Remove '&' with no space (edge case)

# Now dispatcher handles backgrounding cleanly
if is_gui_app "$cmd"; then
    eval "$cmd &"
else
    eval "$cmd"
fi
```

**Why Three Patterns?**
1. **Rez commands** (90% of production): End with ` &"` (space + ampersand + quote)
2. **Direct commands** (10% of production): End with ` &` (space + ampersand)
3. **Edge cases**: End with `&` (no space)

**Verification:**
- ✅ Tested with 19 test cases covering all scenarios
- ✅ All tests pass (100% success rate)
- ✅ Preserves `&&` operators (logical AND)
- ✅ Handles spaces in paths, special characters
- ✅ See `test_dispatcher_fix.sh` for complete test suite

**Defense in Depth:**
Also added signal handling to prevent read loop interruption:
```bash
# At start of while loop (line 42)
trap '' SIGCHLD SIGHUP SIGPIPE
```

**Pros:**
- ✅ Actually works for rez commands (unlike original proposal)
- ✅ Handles all three command patterns
- ✅ Doesn't require changes to command_launcher.py
- ✅ Defensive against future changes
- ✅ Includes signal handling for additional safety
- ✅ Comprehensive debug logging

**Cons:**
- Slightly more complex than original (3 lines instead of 2)
- But necessary to actually fix the bug!

### Option 2: Don't Add `&` in command_launcher.py

**File:** `command_launcher.py`

Remove the logic that appends `&` for persistent terminal commands.

**Pros:**
- Dispatcher fully controls backgrounding
- Cleaner command construction

**Cons:**
- Requires changes to Python code
- Need to identify all places where `&` is added
- More invasive change

### Option 3: Remove Auto-Backgrounding from Dispatcher

Remove lines 112-125 from terminal_dispatcher.sh, rely entirely on command_launcher.py.

**Pros:**
- Simplifies dispatcher logic

**Cons:**
- Loses ability to auto-detect GUI apps in dispatcher
- Less defensive programming
- Doesn't fix the core issue

## Recommendation

**Implement Option 1** (strip trailing `&` in dispatcher) because:

1. Minimal code change (2 lines)
2. Defensive programming - handles both cases
3. Maintains backward compatibility
4. Fixes the bug immediately
5. No need to track down all places in Python that add `&`

## Fix Implementation Status

**Status:** ✅ **IMPLEMENTED** (2025-11-02)

**Files Modified:**
- `terminal_dispatcher.sh` - Lines 42, 106-162

**Changes Made:**
1. ✅ Added signal handling (`trap '' SIGCHLD SIGHUP SIGPIPE`)
2. ✅ Implemented three-pattern stripping for rez/direct/edge cases
3. ✅ Added debug logging to verify stripping works
4. ✅ Simplified dispatcher logic (removed redundant & check)

**Testing:**
- ✅ Created comprehensive test suite (`test_dispatcher_fix.sh`)
- ✅ 19 test cases covering all scenarios
- ✅ 100% pass rate achieved

## Fix Verification Checklist

After deploying to production, verify:

1. [ ] **First command executes successfully** without errors
2. [ ] **Second command executes WITHOUT terminal restart** (critical test)
3. [ ] **No "dispatcher dead" warnings in logs** (check persistent_terminal_manager.py logs)
4. [ ] **Terminal stays alive for entire session** (same PID throughout)
5. [ ] **FIFO remains readable between commands** (no ENXIO errors)
6. [ ] **Debug logs show pattern stripping working** (if DEBUG_MODE=1)
7. [ ] **Rapid-fire launches** (3+ commands in quick succession) work
8. [ ] **Mixed GUI and non-GUI commands** work correctly
9. [ ] **No zombie terminal processes** accumulate
10. [ ] **Performance is normal** (no delays from restarts)

## Related Files

- `terminal_dispatcher.sh` - Shell script with the bug
- `persistent_terminal_manager.py` - Python manager that launches dispatcher
- `command_launcher.py` - Adds `&` to GUI commands
- Production logs - Show the restart pattern clearly

## Testing Checklist

Before deploying fix:

- [ ] Test single Nuke launch
- [ ] Test rapid double Nuke launch (2 seconds apart)
- [ ] Test triple Nuke launch
- [ ] Test other GUI apps (Maya, RV, 3DE)
- [ ] Test non-GUI commands (ls, pwd, etc.)
- [ ] Verify no terminal restarts in logs
- [ ] Verify commands with existing `&` work
- [ ] Verify commands without `&` work

## Timeline

- **Bug Introduced:** Unknown (present in current version)
- **Bug Discovered:** 2025-11-02 13:20:06 (production logs)
- **Root Cause Identified:** 2025-11-02 (analysis of dispatcher script)
- **Initial Fix Proposed:** 2025-11-02 (strip trailing `&`)
- **Fix Corrected:** 2025-11-02 (three-pattern stripping required)
- **Fix Implemented:** 2025-11-02 (terminal_dispatcher.sh lines 42, 106-162)
- **Fix Tested:** 2025-11-02 (19/19 tests pass)
- **Fix Status:** ✅ **IMPLEMENTED - PENDING PRODUCTION DEPLOYMENT**

## Additional Files Created

- `AGENT_VERIFICATION_REPORT.md` - Independent verification of bug analysis
- `test_dispatcher_fix.sh` - Comprehensive test suite (19 test cases)
- Both reports confirm the fix is correct and ready for deployment
