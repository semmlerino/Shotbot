# Phase 2: Timeout Handling Implementation Plan (v2)

**Date**: 2025-11-09
**Status**: Ready for Implementation
**Risk Level**: 🟢 Low (Existing test coverage, clear implementation path)
**Estimated Time**: 25-30 minutes (implementation) + 15 minutes (test updates) = **40-50 minutes total**

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Changes from v1](#changes-from-v1)
3. [Current State Analysis](#current-state-analysis)
4. [Problem Statement](#problem-statement)
5. [Solution Overview](#solution-overview)
6. [Implementation Steps](#implementation-steps)
7. [Testing Strategy](#testing-strategy)
8. [Rollback Plan](#rollback-plan)
9. [Verification Checklist](#verification-checklist)
10. [Risk Mitigation](#risk-mitigation)

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

**Files Modified**: 2
- `filesystem_scanner.py` (~15 lines)
- `tests/unit/test_worker_stop_responsiveness.py` (~50 lines added/changed)

**Breaking Changes**: Yes (return type changed)
**Callers Affected**: 1 (line 834)
**Tests Affected**: 1 existing test updated, 2 new tests added

---

## Changes from v1

**Multi-Agent Verification Results** (4 agents + manual code inspection):

### ✅ Verified Accurate
- Problem exists exactly as described (timeout returns `[]`)
- Only one caller site (line 834)
- Four crash points confirmed (924, 928, 932+936, 944)
- No parameter validation exists
- Type safety claims all accurate

### 🔴 Corrections Made

**1. Removed OSError Handling** (v1 Task 2.1)
- **v1 Claim**: "Process.kill() can raise OSError if process already finished"
- **Testing Result**: `process.kill()` does NOT raise OSError in this scenario
- **Change**: Removed try/except OSError wrapper (unnecessary)

**2. Updated Test Coverage Assessment**
- **v1 Claim**: "No automated tests for _run_find_with_polling"
- **Actual**: 8 tests exist in `test_worker_stop_responsiveness.py`
- **Issue**: Tests use mocks that don't verify None vs [] distinction
- **Change**: Added test update tasks (2.6, 2.7, 2.8)

**3. Critical Test Breakage Identified**
- **Breaking Test**: `test_timeout_still_enforced_without_cancel_flag` (line 355)
- **Current**: `assert isinstance(result, list)`
- **After Phase 2**: This assertion will FAIL (timeout returns None)
- **Fix**: Task 2.6 updates this test

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
3. No validation on `max_wait_time` parameter (accepts 0 or negative)

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
2. Missing parameter validation
3. Existing test will break after implementation

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

1. **Parameter validation**: Raise ValueError if `max_wait_time <= 0`
2. **Better logging**: Distinguish timeout from success in final message
3. **Test updates**: Fix breaking test + add regression tests

---

## Implementation Steps

### CRITICAL: Implementation Order

**The changes MUST be made in this order** to avoid breaking intermediate states:

1. ✅ **Task 2.2**: Update method signature (add `| None`)
2. ✅ **Task 2.3**: Add parameter validation
3. ✅ **Task 2.4**: Update caller with None check (BEFORE changing return)
4. ✅ **Task 2.1**: Change timeout return to `None`
5. ✅ **Task 2.5**: Update success/failure messaging
6. ✅ **Task 2.6**: Update existing test (fix breakage)
7. ✅ **Task 2.7**: Add test for None vs [] distinction
8. ✅ **Task 2.8**: Add test for successful empty search (optional)

**Why this order?**
- Adding `| None` to signature makes subsequent changes type-safe
- Updating caller before changing return prevents runtime crashes
- Changing return value after caller ready ensures no breakage
- Test updates last (after implementation complete)

---

### Task 2.1: Change Timeout Return Value

**File**: `filesystem_scanner.py`
**Location**: Line 682
**Risk**: 🔴 High (breaks caller if done before Task 2.4)

**Current Code** (Line 675-682):
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
    process.kill()
    _ = process.wait()
    return None  # Explicit timeout signal
```

**Changes**:
- Line 682: `return []` → `return None`

**Rationale**:
- `None` is explicit sentinel value for timeout
- No try/except needed (process.kill() is safe)

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

### Task 2.6: Update Existing Test (Fix Breakage)

**File**: `tests/unit/test_worker_stop_responsiveness.py`
**Location**: Line 355
**Risk**: 🔴 High (test will FAIL without this fix)

**Current Code** (Line 354-356):
```python
        # Should return empty list (fallback was called)
        assert isinstance(result, list)
```

**New Code**:
```python
        # Should return None on timeout (changed in Phase 2)
        assert result is None, "Timeout should return None (not [])"
```

**Changes**:
- Line 354-355: Update comment and assertion

**Rationale**:
- Test now verifies new timeout behavior (returns None)
- Prevents test breakage after Task 2.1

---

### Task 2.7: Add Test for None vs [] Distinction

**File**: `tests/unit/test_worker_stop_responsiveness.py`
**Location**: After line 356 (new test in `TestFileSystemScannerInterruptibility` class)
**Risk**: 🟢 Low (adds coverage, doesn't change existing)

**New Code**:
```python
    def test_timeout_returns_none_not_empty_list(self) -> None:
        """Test that timeout returns None (not []) to distinguish from empty results.

        This is a regression test for Phase 2 timeout handling where we changed
        timeout behavior to return None instead of [] so callers can distinguish
        between:
        - Timeout: None (incomplete search)
        - Empty results: [] (successful search, no files found)
        """
        scanner = FileSystemScanner()

        # Mock a process that times out immediately
        mock_process = Mock()
        mock_process.poll.return_value = None  # Never finishes
        mock_process.kill = Mock()
        mock_process.wait = Mock()

        with (
            patch("filesystem_scanner.subprocess.Popen", return_value=mock_process),
            patch("pathlib.Path.exists", return_value=True),
            patch("time.sleep"),  # Speed up test
        ):
            # Use very short timeout to trigger immediately
            result = scanner._run_find_with_polling(
                find_cmd=["find", "/fake/path", "-name", "*.3de"],
                show_path=Path("/shows/test"),
                show="test",
                excluded_users=set(),
                cancel_flag=None,
                max_wait_time=0.001,  # Immediate timeout
            )

            # Critical: timeout must return None (not [])
            assert result is None, "Timeout should return None"
            assert result != [], "Timeout should NOT return empty list"

            # Verify process was killed
            assert mock_process.kill.called, "Process should be killed on timeout"
```

**Rationale**:
- Explicitly tests the None vs [] distinction
- Prevents regression to old behavior
- Documents the contract for future developers

---

### Task 2.8: Add Test for Successful Empty Search (Optional)

**File**: `tests/unit/test_worker_stop_responsiveness.py`
**Location**: After Task 2.7 (new test in `TestFileSystemScannerInterruptibility` class)
**Risk**: 🟢 Low (adds coverage, completeness)

**New Code**:
```python
    def test_successful_empty_search_returns_empty_list(self) -> None:
        """Test that successful search with no results returns [] (not None).

        Verifies that [] is reserved for successful-but-empty searches,
        while None is reserved for timeout.
        """
        scanner = FileSystemScanner()

        # Mock a process that completes successfully with no output
        mock_process = Mock()
        mock_process.poll.return_value = 0  # Finished successfully
        mock_process.communicate.return_value = ("", "")  # No stdout, no stderr
        mock_process.returncode = 0

        with (
            patch("filesystem_scanner.subprocess.Popen", return_value=mock_process),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = scanner._run_find_with_polling(
                find_cmd=["find", "/fake/path", "-name", "*.3de"],
                show_path=Path("/shows/test"),
                show="test",
                excluded_users=set(),
                cancel_flag=None,
            )

            # Critical: successful empty search returns []
            assert result == [], "Successful empty search should return []"
            assert result is not None, "Successful search should NOT return None"
```

**Rationale**:
- Completes the test coverage (timeout=None, empty=[], results=list)
- Prevents future confusion about what `[]` means
- Documents expected behavior

---

## Testing Strategy

### Pre-Implementation Testing

**Goal**: Establish baseline behavior

1. **Run existing tests**:
   ```bash
   cd ~/projects/shotbot
   ~/.local/bin/uv run pytest tests/unit/test_worker_stop_responsiveness.py -v
   ```

   **Expected**: All 8 tests pass (baseline)

2. **Note breaking test**:
   - `test_timeout_still_enforced_without_cancel_flag` will break after Task 2.1
   - Fixed by Task 2.6

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
- Check None handling at line 834-843
- Verify `| None` in signature at line 631
- Check all usages of `user_results` (should all use converted value)

---

### Linting Verification

**Run after implementation**:
```bash
cd ~/projects/shotbot
~/.local/bin/uv run ruff check filesystem_scanner.py
~/.local/bin/uv run ruff check tests/unit/test_worker_stop_responsiveness.py
```

**Expected Output**:
```
All checks passed!
```

---

### Test Suite Verification

**Run after test updates**:
```bash
cd ~/projects/shotbot
~/.local/bin/uv run pytest tests/unit/test_worker_stop_responsiveness.py -v
```

**Expected Output**:
```
test_worker_stops_quickly_during_scan PASSED
test_cancel_flag_checked_during_subprocess PASSED
test_subprocess_killed_on_cancellation PASSED
test_cancel_flag_parameter_exists PASSED
test_cancel_flag_none_works PASSED
test_timeout_still_enforced_without_cancel_flag PASSED  ← Fixed by Task 2.6
test_timeout_returns_none_not_empty_list PASSED  ← Added by Task 2.7
test_successful_empty_search_returns_empty_list PASSED  ← Added by Task 2.8

8 passed in X.XXs
```

---

## Rollback Plan

### Quick Rollback (Git)

**If implementation fails**:
```bash
cd ~/projects/shotbot
git checkout HEAD -- filesystem_scanner.py
git checkout HEAD -- tests/unit/test_worker_stop_responsiveness.py
```

**Verify rollback**:
```bash
git diff filesystem_scanner.py  # Should show no changes
git diff tests/unit/test_worker_stop_responsiveness.py  # Should show no changes
~/.local/bin/uv run basedpyright filesystem_scanner.py  # Should pass
~/.local/bin/uv run pytest tests/unit/test_worker_stop_responsiveness.py  # Should pass
```

### Partial Rollback (Specific Tasks)

**If only certain tasks cause issues**, revert in reverse order:

1. **Revert Task 2.8** (optional test):
   ```bash
   # Delete test_successful_empty_search_returns_empty_list method
   ```

2. **Revert Task 2.7** (None vs [] test):
   ```bash
   # Delete test_timeout_returns_none_not_empty_list method
   ```

3. **Revert Task 2.6** (test fix):
   ```python
   # Line 355: Change back to
   assert isinstance(result, list)
   ```

4. **Revert Task 2.5** (messaging):
   ```bash
   git diff HEAD filesystem_scanner.py  # Find message changes
   # Manually revert lines 927-952
   ```

5. **Revert Task 2.1** (return None):
   ```python
   # Line 681: Change back to
   return []  # Return empty on timeout
   ```

6. **Revert Task 2.4** (caller):
   ```python
   # Lines 834-843: Change back to
   user_results = self._run_find_with_polling(
       find_cmd_user, show_path, show, excluded_users, cancel_flag, max_wait_time=150
   )
   ```

7. **Revert Task 2.3** (validation):
   ```python
   # Remove lines after 644:
   # if max_wait_time <= 0:
   #     raise ValueError(...)
   ```

8. **Revert Task 2.2** (signature):
   ```python
   # Line 631: Remove | None
   ) -> list[tuple[Path, str, str, str, str, str]]:
   ```

---

## Verification Checklist

### Pre-Implementation

- [ ] Read this entire plan document
- [ ] Understand the implementation order (2.2 → 2.3 → 2.4 → 2.1 → 2.5 → 2.6 → 2.7 → 2.8)
- [ ] Run existing tests to establish baseline
- [ ] Have rollback plan ready (`git checkout HEAD -- ...`)

### During Implementation (Code Changes)

- [ ] **Task 2.2**: Update signature to `| None`
- [ ] **Task 2.3**: Add max_wait_time validation
- [ ] **Task 2.4**: Update caller with None check (CRITICAL - do before 2.1)
- [ ] **Task 2.1**: Change timeout return to `None` (do AFTER 2.4)
- [ ] **Task 2.5**: Update messaging

### During Implementation (Test Updates)

- [ ] **Task 2.6**: Update existing test (fix `isinstance(result, list)`)
- [ ] **Task 2.7**: Add test for None vs [] distinction
- [ ] **Task 2.8**: Add test for successful empty search (optional)

### Post-Implementation

- [ ] Type checking passes: `~/.local/bin/uv run basedpyright filesystem_scanner.py`
- [ ] Linting passes: `~/.local/bin/uv run ruff check filesystem_scanner.py`
- [ ] Linting passes: `~/.local/bin/uv run ruff check tests/unit/test_worker_stop_responsiveness.py`
- [ ] Full codebase type check: `~/.local/bin/uv run basedpyright`
- [ ] All tests pass: `~/.local/bin/uv run pytest tests/unit/test_worker_stop_responsiveness.py -v`

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
- [ ] All 8+ tests passing (8 existing + 2 new minimum)

---

## Risk Mitigation

### Risk 1: Breaking Change to Return Type

**Risk**: Changing `[]` to `None` could crash callers

**Mitigation**:
- Only ONE caller site (line 834)
- Update caller BEFORE changing return (Task 2.4 before 2.1)
- Type checker will catch missing None checks
- Conversion to `[]` makes existing code work unchanged

**Status**: ✅ Mitigated

---

### Risk 2: Test Breakage

**Risk**: Existing test expects `list`, will fail after Phase 2

**Mitigation**:
- Task 2.6 fixes the breaking test
- Task 2.7 adds regression test for new behavior
- Test updates after implementation (safe order)
- Full test suite run before commit

**Status**: ✅ Mitigated by test update tasks

---

### Risk 3: Invalid max_wait_time

**Risk**: max_wait_time=0 causes immediate timeout

**Mitigation**:
- Add validation (Task 2.3)
- Raise ValueError with clear message
- Fail fast before any work

**Status**: ✅ Mitigated

---

### Risk 4: OSError from process.kill() (v1 concern)

**Risk**: Process.kill() might raise OSError if process finished

**Verification**: Multi-agent testing + manual inspection proved this does NOT occur

**Mitigation**: None needed - process.kill() is safe

**Status**: ✅ No mitigation needed (false concern from v1)

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

✅ **FR5**: Test coverage maintained
- Existing test updated (no breakage)
- New tests added (regression protection)
- All tests pass

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
- Test coverage prevents regression

---

## Post-Implementation Notes

### What Changed

**Summary**:
- Return type: `list[...]` → `list[...] | None`
- Timeout return: `[]` → `None`
- Caller: Added None check and conversion
- Messaging: Conditional based on timeout flag
- Validation: Added max_wait_time > 0 check
- Tests: Fixed 1 breaking test, added 2 new tests

### Files Modified

**`filesystem_scanner.py`**:
- Line 631: Return type annotation
- Lines 645-647: Parameter validation (new)
- Line 681: Return value (modified)
- Lines 834-843: Caller with None handling (modified)
- Lines 927-929: Conditional messaging (modified)
- Lines 943-952: Conditional messaging (modified)

**`tests/unit/test_worker_stop_responsiveness.py`**:
- Line 355: Test assertion updated (fixed breakage)
- After line 356: New test for None vs [] (added ~25 lines)
- After new test: Optional test for empty results (added ~25 lines)

### Testing Performed

- [ ] Manual test scenario 1: Success with results
- [ ] Manual test scenario 2: Empty results
- [ ] Manual test scenario 3: Timeout
- [ ] Manual test scenario 4: Parameter validation
- [ ] Type checking: basedpyright
- [ ] Linting: ruff
- [ ] Test suite: pytest (all tests passing)

### Issues Encountered

*Document any issues encountered during implementation*

### Lessons Learned

*Document any insights gained during implementation*

---

## Appendix A: Complete Code Snippets

### Modified Timeout Section (Task 2.1)

**Lines 675-681** (with changes):
```python
                if elapsed_time >= max_wait_time:
                    self.logger.error(
                        f"Find command timed out after {max_wait_time} seconds"
                    )
                    process.kill()
                    _ = process.wait()
                    return None  # Explicit timeout signal
```

### Modified Method with Validation (Task 2.3)

**Lines 644-649** (with changes):
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

### Modified Caller (Task 2.4)

**Lines 834-843** (with changes):
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

### Modified Messaging (Task 2.5)

**Lines 927-952** (with changes):
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
- **Multi-Agent Verification**: Performed 2025-11-09 (4 agents + manual inspection)
- **Project README**: `CLAUDE.md`

---

**End of Plan v2**
