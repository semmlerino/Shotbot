# Phase 2: Timeout Handling Implementation Plan

**Date**: 2025-11-09
**Status**: Ready for Implementation
**Risk Level**: 🟡 Medium (No test coverage, requires careful manual testing)
**Estimated Time**: 15-20 minutes (implementation) + 10-15 minutes (testing)

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Current State Analysis](#current-state-analysis)
3. [Problem Statement](#problem-statement)
4. [Solution Overview](#solution-overview)
5. [Implementation Steps](#implementation-steps)
6. [Testing Strategy](#testing-strategy)
7. [Rollback Plan](#rollback-plan)
8. [Verification Checklist](#verification-checklist)

---

## Executive Summary

**Goal**: Make timeout distinguishable from successful empty search results.

**Current Behavior**:
- Timeout returns `[]` (empty list)
- Success with no files returns `[]` (empty list)
- User sees "✅ Search complete" even after timeout

**Target Behavior**:
- Timeout returns `None`
- Success with no files returns `[]`
- User sees "⚠️ Search incomplete (timeout)" after timeout
- User sees "✅ Search complete: No files found" for empty results

**Files Modified**: 1 (`filesystem_scanner.py`)
**Lines Changed**: ~15 lines
**Breaking Changes**: Yes (return type changed)
**Callers Affected**: 1 (line 834)

---

## Current State Analysis

### Method Signature

**File**: `filesystem_scanner.py`
**Method**: `_run_find_with_polling`
**Location**: Line 623

**Current Signature** (Line 631):
```python
) -> list[tuple[Path, str, str, str, str, str]]:
```

**Parameters**:
- `find_cmd: list[str]` - The find command
- `show_path: Path` - Show directory path
- `show: str` - Show name
- `excluded_users: set[str]` - Users to exclude
- `cancel_flag: Callable[[], bool] | None` - Cancellation callback
- `max_wait_time: float = 300.0` - Timeout in seconds

### Current Return Behavior

| Scenario | Return Value | Log Message |
|----------|-------------|-------------|
| **Success with results** | `list[tuple[...]]` (populated) | "✅ Dual search complete: X files found..." |
| **Success with no files** | `[]` (empty list) | "✅ Dual search complete: 0 user files found..." |
| **Timeout** | `[]` (empty list) | "Find command timed out..." + "✅ Dual search complete: 0 user files found..." |
| **Cancellation** | `[]` (empty list) | "Find command cancelled..." |

**Problem**: Timeout and empty results are indistinguishable to caller.

### Caller Analysis

**Single Caller** (Line 834-836):
```python
user_results = self._run_find_with_polling(
    find_cmd_user, show_path, show, excluded_users, cancel_flag, max_wait_time=150
)
```

**Usage Sites** (all unsafe if `user_results` is None):

1. **Line 924** - List comprehension iteration:
```python
results = [
    result for result in user_results  # ❌ TypeError: 'NoneType' object is not iterable
    if (result[2], result[3]) in shots_with_published_mm
]
```

2. **Line 928** - len() in logging:
```python
self.logger.info(
    f"Filtered {len(user_results)} user files..."  # ❌ TypeError: object of type 'NoneType' has no len()
)
```

3. **Line 932** - Assignment (propagates None):
```python
results = user_results  # Results becomes None
# Then line 936:
file_count = len(results)  # ❌ TypeError
```

4. **Line 944** - len() in success logging:
```python
self.logger.info(
    f"✅ Dual search complete: {len(user_results)} user files found..."  # ❌ TypeError
)
```

### Current Timeout Logic

**Location**: Lines 675-681

```python
if elapsed_time >= max_wait_time:
    self.logger.error(
        f"Find command timed out after {max_wait_time} seconds"
    )
    process.kill()
    _ = process.wait()
    return []  # Return empty on timeout
```

**Issues**:
1. Returns `[]` (same as successful empty search)
2. No distinction at caller level
3. Process.kill() can raise OSError if process already finished (race condition)
4. No validation on `max_wait_time` parameter (accepts 0 or negative)

---

## Problem Statement

### UX Issue
Users cannot distinguish between:
- **Timeout**: "Search took too long, incomplete results"
- **Empty results**: "Search completed successfully, no files found"

Both scenarios currently log:
```
✅ Dual search complete: 0 user files found...
```

### Technical Issue
Caller has no way to detect timeout and respond appropriately:
- Cannot show different message to user
- Cannot trigger retry logic
- Cannot fall back to cached data

### Code Quality Issues
1. Sentinel value confusion (`[]` used for multiple meanings)
2. Race condition in `process.kill()`
3. Missing parameter validation

---

## Solution Overview

### Type System Approach

Use type system to distinguish scenarios:
- **Timeout**: `None` (explicit sentinel)
- **Empty results**: `[]` (empty list)
- **Results**: `list[tuple[...]]` (populated list)

**New Return Type**:
```python
) -> list[tuple[Path, str, str, str, str, str]] | None:
```

### Caller Pattern

```python
# Get raw result (may be None on timeout)
user_results_raw = self._run_find_with_polling(...)

# Track timeout state for conditional logic
user_timed_out = user_results_raw is None

# Convert to safe list for existing code
user_results = user_results_raw if user_results_raw is not None else []

# Use timeout flag for appropriate messaging
if user_timed_out:
    self.logger.warning("⚠️ User search incomplete (timeout)")
else:
    self.logger.info("✅ User search complete")
```

### Additional Improvements

1. **Race condition fix**: Wrap `process.kill()` in try/except OSError
2. **Parameter validation**: Raise ValueError if `max_wait_time <= 0`
3. **Better logging**: Distinguish timeout from success in final message

---

## Implementation Steps

### CRITICAL: Implementation Order

**The changes MUST be made in this order** to avoid breaking intermediate states:

1. ✅ **Task 2.2**: Update method signature (add `| None`)
2. ✅ **Task 2.3**: Add parameter validation
3. ✅ **Task 2.4**: Update caller with None check (BEFORE changing return)
4. ✅ **Task 2.1**: Change timeout return to `None`
5. ✅ **Task 2.5**: Update success/failure messaging

**Why this order?**
- Adding `| None` to signature makes subsequent changes type-safe
- Updating caller before changing return prevents runtime crashes
- Changing return value last ensures all infrastructure is ready

---

### Task 2.1: Change Timeout Return Value

**File**: `filesystem_scanner.py`
**Location**: Line 681
**Risk**: 🔴 High (breaks caller if done before Task 2.4)

**Current Code** (Line 675-681):
```python
if elapsed_time >= max_wait_time:
    self.logger.error(
        f"Find command timed out after {max_wait_time} seconds"
    )
    process.kill()
    _ = process.wait()
    return []  # Return empty on timeout
```

**New Code**:
```python
if elapsed_time >= max_wait_time:
    self.logger.error(
        f"Find command timed out after {max_wait_time} seconds"
    )
    try:
        process.kill()
    except OSError:
        # Process may have finished between check and kill
        pass
    _ = process.wait()
    return None  # Explicit timeout signal
```

**Changes**:
- Line 681: `return []` → `return None`
- Lines 679-682: Add try/except OSError around `process.kill()`

**Rationale**:
- `None` is explicit sentinel value for timeout
- OSError handling prevents race condition crash

---

### Task 2.2: Update Method Signature

**File**: `filesystem_scanner.py`
**Location**: Line 631
**Risk**: 🟢 Low (only adds type option)

**Current Code**:
```python
) -> list[tuple[Path, str, str, str, str, str]]:
```

**New Code**:
```python
) -> list[tuple[Path, str, str, str, str, str]] | None:
```

**Changes**:
- Line 631: Add `| None` to return type

**Rationale**:
- Type system now reflects reality (method can return None)
- basedpyright will enforce None checks at call sites

---

### Task 2.3: Add Parameter Validation

**File**: `filesystem_scanner.py`
**Location**: After line 644 (start of method body)
**Risk**: 🟢 Low (only adds validation)

**Current Code** (Line 644-648):
```python
        """
        # Standard library imports
        import subprocess
        import time

        results: list[tuple[Path, str, str, str, str, str]] = []
```

**New Code**:
```python
        """
        # Validate parameters
        if max_wait_time <= 0:
            raise ValueError(f"max_wait_time must be positive, got {max_wait_time}")

        # Standard library imports
        import subprocess
        import time

        results: list[tuple[Path, str, str, str, str, str]] = []
```

**Changes**:
- Insert 2 lines after line 644 (after docstring)
- Validate `max_wait_time > 0`

**Rationale**:
- Prevents immediate timeout with invalid values
- Fails fast with clear error message

---

### Task 2.4: Update Caller to Handle None

**File**: `filesystem_scanner.py`
**Location**: Lines 834-836
**Risk**: 🔴 High (must be done before Task 2.1)

**Current Code** (Lines 834-836):
```python
            user_results = self._run_find_with_polling(
                find_cmd_user, show_path, show, excluded_users, cancel_flag, max_wait_time=150
            )
```

**New Code**:
```python
            # Run user directory search with timeout detection
            user_results_raw = self._run_find_with_polling(
                find_cmd_user, show_path, show, excluded_users, cancel_flag, max_wait_time=150
            )

            # Track timeout state for conditional messaging
            user_timed_out = user_results_raw is None

            # Convert None to empty list for safe iteration
            user_results = user_results_raw if user_results_raw is not None else []
```

**Changes**:
- Line 834: `user_results` → `user_results_raw`
- Insert 2 lines: timeout detection and safe conversion

**Rationale**:
- `user_results` is guaranteed to be a list (never None)
- All existing code at lines 924, 928, 932, 944 works unchanged
- `user_timed_out` flag available for conditional logic

---

### Task 2.5: Update Success/Failure Messaging

**File**: `filesystem_scanner.py`
**Location**: Lines 927-929 and 943-945
**Risk**: 🟢 Low (only changes log messages)

**Current Code** (Lines 927-929):
```python
                self.logger.info(
                    f"Filtered {len(user_results)} user files to {len(results)} from shots with published MM"
                )
```

**New Code**:
```python
                msg_prefix = "⚠️ Partial results (timeout):" if user_timed_out else "Filtered"
                self.logger.info(
                    f"{msg_prefix} {len(user_results)} user files to {len(results)} from shots with published MM"
                )
```

**Current Code** (Lines 943-945):
```python
            self.logger.info(
                f"✅ Dual search complete: {len(user_results)} user files found, {len(results)} files from shots with published MM ({len(unique_shots)} shots, {elapsed:.1f}s)"
            )
```

**New Code**:
```python
            if user_timed_out:
                self.logger.warning(
                    f"⚠️ Search incomplete (timeout): {len(user_results)} user files found, {len(results)} files from shots with published MM ({len(unique_shots)} shots, {elapsed:.1f}s)"
                )
            else:
                self.logger.info(
                    f"✅ Dual search complete: {len(user_results)} user files found, {len(results)} files from shots with published MM ({len(unique_shots)} shots, {elapsed:.1f}s)"
                )
```

**Changes**:
- Lines 927-929: Add prefix based on timeout flag
- Lines 943-945: Split into conditional (warning vs info)

**Rationale**:
- User sees different message for timeout vs success
- Warning level for timeout draws attention
- Success emoji only for actual success

---

## Testing Strategy

### Pre-Implementation Testing

**Goal**: Establish baseline behavior

1. **Run application normally**:
   ```bash
   cd ~/projects/shotbot
   ~/.local/bin/uv run python shotbot.py
   ```

2. **Trigger 3DE scene search**:
   - Open application
   - Click "Load Other 3DE Scenes"
   - Observe log messages
   - Note: Should see "✅ Dual search complete"

3. **Document baseline**:
   - Screenshot of log output
   - Note file counts in success message

### Manual Test Scenarios

#### Scenario 1: Normal Success (Has Results)

**Setup**:
- Normal operation
- VFX production directories accessible
- Multiple .3de files present

**Expected Behavior**:
```
✅ Dual search complete: 50 user files found, 25 files from shots with published MM (15 shots, 2.3s)
```

**Verification**:
- ✅ No timeout
- ✅ Files displayed in grid
- ✅ Success emoji shown

---

#### Scenario 2: Empty Results (No Files Found)

**Setup**:
- Search in empty show directory
- OR search with very restrictive filters

**Expected Behavior**:
```
✅ Dual search complete: 0 user files found, 0 files from shots with published MM (0 shots, 0.5s)
```

**Verification**:
- ✅ No timeout
- ✅ Empty grid
- ✅ Success emoji (search completed successfully)

---

#### Scenario 3: Timeout (Search Takes Too Long)

**Setup Option A** - Code modification (temporary):
```python
# In find_all_3de_files_in_show_targeted(), line 835
# Change max_wait_time from 150 to 1 for testing
user_results_raw = self._run_find_with_polling(
    find_cmd_user, show_path, show, excluded_users, cancel_flag, max_wait_time=1  # Test timeout
)
```

**Setup Option B** - Slow filesystem:
- Search over slow network mount
- OR search very large directory tree

**Expected Behavior**:
```
ERROR: Find command timed out after 1 seconds
⚠️ Search incomplete (timeout): 0 user files found, 0 files from shots with published MM (0 shots, 1.0s)
```

**Verification**:
- ✅ Timeout detected
- ✅ Warning emoji shown
- ✅ "incomplete" message instead of "complete"
- ✅ No crash (user_results safely converted to [])

**Cleanup**: Revert max_wait_time to 150 after testing

---

#### Scenario 4: Parameter Validation

**Setup** - Code modification (temporary):
```python
# In find_all_3de_files_in_show_targeted(), line 835
user_results_raw = self._run_find_with_polling(
    find_cmd_user, show_path, show, excluded_users, cancel_flag, max_wait_time=0  # Test validation
)
```

**Expected Behavior**:
```
ValueError: max_wait_time must be positive, got 0
```

**Verification**:
- ✅ Raises ValueError immediately
- ✅ Clear error message
- ✅ Application doesn't hang

**Cleanup**: Remove test code

---

### Type Checking Verification

**Run after implementation**:
```bash
cd ~/projects/shotbot
~/.local/bin/uv run basedpyright filesystem_scanner.py
```

**Expected Output**:
```
0 errors, 0 warnings, 0 notes
```

**If errors occur**:
- Check None handling at line 834-836
- Verify `| None` in signature at line 631
- Check all usages of `user_results` (should all use converted value)

---

### Linting Verification

**Run after implementation**:
```bash
cd ~/projects/shotbot
~/.local/bin/uv run ruff check filesystem_scanner.py
```

**Expected Output**:
```
All checks passed!
```

---

## Rollback Plan

### Quick Rollback (Git)

**If implementation fails**:
```bash
cd ~/projects/shotbot
git checkout HEAD -- filesystem_scanner.py
```

**Verify rollback**:
```bash
git diff filesystem_scanner.py  # Should show no changes
~/.local/bin/uv run basedpyright filesystem_scanner.py  # Should pass
```

### Partial Rollback (Specific Tasks)

**If only certain tasks cause issues**, revert in reverse order:

1. **Revert Task 2.5** (messaging):
   ```bash
   git diff HEAD filesystem_scanner.py  # Find message changes
   # Manually revert lines 927-945
   ```

2. **Revert Task 2.1** (return None):
   ```python
   # Line 681: Change back to
   return []  # Return empty on timeout
   ```

3. **Revert Task 2.4** (caller):
   ```python
   # Lines 834-836: Change back to
   user_results = self._run_find_with_polling(
       find_cmd_user, show_path, show, excluded_users, cancel_flag, max_wait_time=150
   )
   ```

4. **Revert Task 2.3** (validation):
   ```python
   # Remove lines after 644:
   # if max_wait_time <= 0:
   #     raise ValueError(...)
   ```

5. **Revert Task 2.2** (signature):
   ```python
   # Line 631: Remove | None
   ) -> list[tuple[Path, str, str, str, str, str]]:
   ```

---

## Verification Checklist

### Pre-Implementation

- [ ] Read this entire plan document
- [ ] Understand the implementation order (2.2 → 2.3 → 2.4 → 2.1 → 2.5)
- [ ] Have baseline test (run application and trigger scene search)
- [ ] Have rollback plan ready (`git checkout HEAD -- filesystem_scanner.py`)

### During Implementation

- [ ] **Task 2.2**: Update signature to `| None`
- [ ] **Task 2.3**: Add max_wait_time validation
- [ ] **Task 2.4**: Update caller with None check (CRITICAL - do before 2.1)
- [ ] **Task 2.1**: Change timeout return to `None` (do AFTER 2.4)
- [ ] **Task 2.5**: Update messaging

### Post-Implementation

- [ ] Type checking passes: `~/.local/bin/uv run basedpyright filesystem_scanner.py`
- [ ] Linting passes: `~/.local/bin/uv run ruff check filesystem_scanner.py`
- [ ] Full codebase type check: `~/.local/bin/uv run basedpyright`

### Manual Testing

- [ ] **Scenario 1**: Normal success with results (see "✅ Dual search complete")
- [ ] **Scenario 2**: Empty results (see "✅ Dual search complete: 0 user files")
- [ ] **Scenario 3**: Timeout (see "⚠️ Search incomplete (timeout)")
- [ ] **Scenario 4**: Parameter validation (ValueError for max_wait_time=0)

### Final Verification

- [ ] No crashes during normal operation
- [ ] Timeout is distinguishable from empty results
- [ ] Log messages are clear and appropriate
- [ ] No type errors in full codebase check

---

## Risk Mitigation

### Risk 1: No Test Coverage

**Risk**: No automated tests for `_run_find_with_polling`

**Mitigation**:
- Extensive manual testing with all 4 scenarios
- Type checking enforces None handling
- Only one caller site to verify

**Future Work**: Create `tests/unit/test_filesystem_scanner.py`

### Risk 2: Breaking Change to Return Type

**Risk**: Changing `[]` to `None` could crash callers

**Mitigation**:
- Only ONE caller site (line 834)
- Update caller BEFORE changing return (Task 2.4 before 2.1)
- Type checker will catch missing None checks
- Conversion to `[]` makes existing code work unchanged

### Risk 3: Process Kill Race Condition

**Risk**: `process.kill()` can raise OSError if process finished

**Mitigation**:
- Wrap in try/except OSError (Task 2.1)
- Exception is expected and safe to ignore

### Risk 4: Invalid max_wait_time

**Risk**: max_wait_time=0 causes immediate timeout

**Mitigation**:
- Add validation (Task 2.3)
- Raise ValueError with clear message
- Fail fast before any work

---

## Success Criteria

### Functional Requirements

✅ **FR1**: Timeout is distinguishable from empty results
- Timeout returns `None`
- Empty results return `[]`

✅ **FR2**: User sees appropriate message for each scenario
- Success: "✅ Dual search complete"
- Timeout: "⚠️ Search incomplete (timeout)"
- Empty: "✅ Dual search complete: 0 user files found"

✅ **FR3**: No crashes or type errors
- All usages of `user_results` are safe
- Type checking passes
- No runtime TypeError

✅ **FR4**: Parameter validation
- max_wait_time <= 0 raises ValueError
- Clear error message

### Non-Functional Requirements

✅ **NFR1**: Type safety
- basedpyright 0 errors
- Return type accurately reflects behavior

✅ **NFR2**: Code quality
- Linting passes
- No new technical debt
- Clear, self-documenting code

✅ **NFR3**: Maintainability
- Single caller site makes changes easy
- None handling is explicit and clear
- No hidden sentinel values

---

## Post-Implementation Notes

### What Changed

**Summary**:
- Return type: `list[...]` → `list[...] | None`
- Timeout return: `[]` → `None`
- Caller: Added None check and conversion
- Messaging: Conditional based on timeout flag
- Validation: Added max_wait_time > 0 check
- Race fix: OSError handling in process.kill()

### Files Modified

- `filesystem_scanner.py`:
  - Line 631: Return type annotation
  - Line 645-647: Parameter validation (new)
  - Lines 679-682: OSError handling (modified)
  - Line 681: Return value (modified)
  - Lines 834-843: Caller with None handling (modified)
  - Lines 927-929: Conditional messaging (modified)
  - Lines 943-952: Conditional messaging (modified)

### Testing Performed

- [ ] Manual test scenario 1: Success with results
- [ ] Manual test scenario 2: Empty results
- [ ] Manual test scenario 3: Timeout
- [ ] Manual test scenario 4: Parameter validation
- [ ] Type checking: basedpyright
- [ ] Linting: ruff

### Issues Encountered

*Document any issues encountered during implementation*

### Lessons Learned

*Document any insights gained during implementation*

---

## Appendix A: Code Snippets

### Complete Modified Method (Timeout Section)

**Lines 645-682** (with all changes):
```python
        # Validate parameters
        if max_wait_time <= 0:
            raise ValueError(f"max_wait_time must be positive, got {max_wait_time}")

        # Standard library imports
        import subprocess
        import time

        results: list[tuple[Path, str, str, str, str, str]] = []

        try:
            # Run find command with interruptible polling for responsive cancellation
            process = subprocess.Popen(
                find_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Poll process while checking for cancellation
            poll_interval = 0.1  # Check every 100ms
            elapsed_time = 0.0

            while process.poll() is None:  # While process is still running
                # Check for cancellation
                if cancel_flag and cancel_flag():
                    self.logger.info(
                        "Find command cancelled by cancel_flag, killing process"
                    )
                    process.kill()
                    _ = process.wait()  # Clean up zombie process
                    return []  # Return empty list on cancellation

                # Check for timeout
                if elapsed_time >= max_wait_time:
                    self.logger.error(
                        f"Find command timed out after {max_wait_time} seconds"
                    )
                    try:
                        process.kill()
                    except OSError:
                        # Process may have finished between check and kill
                        pass
                    _ = process.wait()
                    return None  # Explicit timeout signal

                # Sleep briefly and update elapsed time
                time.sleep(poll_interval)
                elapsed_time += poll_interval
```

### Complete Modified Caller

**Lines 830-850** (with all changes):
```python
            self.logger.info("🔍 Running dual search: user files + publish/mm directories")

            # Search 1: User directories - find actual .3de files
            self.logger.debug(f"Search 1 (user): {' '.join(find_cmd_user)}")

            # Run user directory search with timeout detection
            user_results_raw = self._run_find_with_polling(
                find_cmd_user, show_path, show, excluded_users, cancel_flag, max_wait_time=150
            )

            # Track timeout state for conditional messaging
            user_timed_out = user_results_raw is None

            # Convert None to empty list for safe iteration
            user_results = user_results_raw if user_results_raw is not None else []

            # Check cancellation between searches
            if cancel_flag and cancel_flag():
                return []
```

### Complete Modified Messaging

**Lines 927-952** (with all changes):
```python
                msg_prefix = "⚠️ Partial results (timeout):" if user_timed_out else "Filtered"
                self.logger.info(
                    f"{msg_prefix} {len(user_results)} user files to {len(results)} from shots with published MM"
                )
            else:
                # No publish/mm directories found - show all user results
                results = user_results
                self.logger.info("No publish/mm directories found - showing all user files")

            # Track statistics
            file_count = len(results)
            parsed_count = len(results)
            for _, _, sequence, shot, _, _ in results:
                unique_shots.add(f"{sequence}/{shot}")

            # Log combined results with timeout awareness
            elapsed = time.time() - start_time
            if user_timed_out:
                self.logger.warning(
                    f"⚠️ Search incomplete (timeout): {len(user_results)} user files found, {len(results)} files from shots with published MM ({len(unique_shots)} shots, {elapsed:.1f}s)"
                )
            else:
                self.logger.info(
                    f"✅ Dual search complete: {len(user_results)} user files found, {len(results)} files from shots with published MM ({len(unique_shots)} shots, {elapsed:.1f}s)"
                )
```

---

## Appendix B: Related Documentation

- **Plan GAMMA v2**: `docs/PLAN_GAMMA_V2.md`
- **Audit Summary**: `docs/PLAN_GAMMA_AUDIT_SUMMARY.md`
- **Project README**: `CLAUDE.md`

---

**End of Plan**
