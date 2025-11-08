# Test Suite Synchronization Audit Report

**Audit Date:** 2025-11-08  
**Focus:** UNIFIED_TESTING_V2.MD Rule #3: "Use qtbot.waitSignal/waitUntil, never time.sleep()"  
**Test Directory:** `/home/gabrielh/projects/shotbot/tests/`  
**Thoroughness Level:** Medium (comprehensive grep + analysis)

---

## Executive Summary

The test suite has **368 total synchronization violations** across three categories:

| Violation Type | Count | Status |
|---|---|---|
| `time.sleep()` in tests | 25 | ⚠️ Moderate concern |
| `qtbot.wait()` hardcoded delays | 308 | ⚠️ CRITICAL - All should use conditions |
| Bare `processEvents()` calls | 35 | ⚠️ Some acceptable, some questionable |

**Key Finding:** The single largest issue is `qtbot.wait()` usage (308 cases). This is a **timing-based anti-pattern** that can cause flaky tests under parallel execution.

---

## Violation Details

### 1. time.sleep() Usage (25 violations)

**Status:** Moderate concern (documented exceptions)

Most `time.sleep()` violations are appropriately documented as necessary for specific testing scenarios:

#### Well-Documented Cases (Acceptable):
- **Stress tests**: `test_thread_safety_regression.py:176, 373` - Marked with comment "acceptable here to ensure race condition test validity"
- **Test doubles/mocking**: `test_process_pool_manager.py:82` - Simulates execution delay in mock, not actual test logic
- **Worker thread simulation**: `test_qt_integration_optimized.py:41, 289` - 10ms delays in background worker tasks, not critical path
- **Timing-sensitive operations**: `test_threede_scene_worker.py:285` - Ensures time difference for performance calculation testing

#### Questionable Cases:
1. **`test_thread_safety_validation.py`** (3 violations)
   - Line 115, 212, 228: `time.sleep()` in stress test - should use `qtbot.waitUntil()` instead
   - Impact: May cause flaky behavior under high CPU load

2. **`test_previous_shots_worker.py:279`**
   - `time.sleep(0.1)` in worker stop responsiveness test
   - Fix: Replace with `qtbot.waitUntil(lambda: worker.should_stop())`

3. **`test_optimized_threading.py`** (2 violations)
   - Line 113, 191: Slow command simulation
   - These are in mock functions, context-dependent but could use mock patches

4. **`test_output_buffer.py:111`**
   - `time.sleep(0.011)` - seems arbitrary, should use proper Qt timing

5. **`test_threede_recovery.py:44`**
   - File timestamp manipulation - acceptable use case

6. **`test_concurrent_optimizations.py:136`**
   - Cleanup delay in stress test - should use condition instead

7. **`test_logging_mixin.py:48`**
   - Simulating work - should use Qt timer or helper

---

### 2. qtbot.wait() Hardcoded Delays (308 violations)

**Status:** CRITICAL - Most violations of UNIFIED_TESTING_V2.MD Rule #3

This is the **largest issue** in the test suite. While `qtbot.wait()` is better than `time.sleep()`, it's **still a timing-based anti-pattern** that violates the rule.

#### Examples of Problematic Usage:

```python
# ❌ WRONG - hardcoded delay, no condition
qtbot.wait(10)   # Hoping 10ms is enough
qtbot.wait(50)   # Hoping 50ms is enough
qtbot.wait(100)  # Hoping 100ms is enough
qtbot.wait(150)  # Hoping 150ms is enough
```

#### Files with Highest Violation Counts:

1. **`integration/test_main_window_complete.py`** - ~10 violations
   - Pattern: `qtbot.wait(10|50|100)` after various UI operations
   - Needed: Replace with `qtbot.waitExposed()` or `qtbot.waitUntil(lambda: condition)`

2. **`unit/test_threede_shot_grid.py`** - ~6 violations
   - Pattern: `qtbot.wait(1|100)` after grid operations
   - Needed: Use `qtbot.waitSignal()` for grid updates

3. **`unit/test_shot_grid_widget.py`** - ~4 violations
   - Pattern: `qtbot.wait(10|50)` in view operations
   - Needed: Condition-based waiting

4. **`integration/test_launcher_panel_integration.py`** - ~4 violations
   - Pattern: Various delays for panel operations
   - Needed: `qtbot.waitSignal()` for signal-based operations

5. **`integration/test_user_workflows.py`** - Multiple violations
   - Pattern: Timing-based workflow synchronization
   - Needed: Comprehensive replacement with proper conditions

#### Distribution by Delay Duration:

```
1ms   - 12 cases (test edge cases, probably unnecessary)
10ms  - 18 cases (minimal processing)
50ms  - 47 cases (signal processing)
100ms - 87 cases (async operations) - MOST COMMON
150ms - 3 cases (heavy operations)
Other - 141 cases (unclear/varied)
```

**Key Problem:** Under parallel test execution with CPU contention, a 100ms delay can easily become insufficient, causing intermittent failures.

---

### 3. Bare processEvents() Calls (35 violations)

**Status:** Mixed - context-dependent

#### Acceptable Usage (Cleanup Context):
Most `processEvents()` calls are in cleanup/finally blocks:

```python
# ✅ ACCEPTABLE - cleanup context
finally:
    qapp.processEvents()  # Process deletion queue
    qapp.processEvents()  # Process cascading cleanups
```

Files in this category:
- `conftest.py` (7 calls) - All in fixture cleanup
- `test_thread_safety_regression.py` (3 calls) - All in cleanup
- `test_main_window_fixed.py` (2 calls) - In cleanup
- `test_actual_parsing.py` (1 call) - Documented cleanup

#### Questionable Usage:
1. **`test_main_window.py:125, 177`** - Not in cleanup context
   - Replace with `qtbot.waitUntil(lambda: window.isVisible())`

2. **`integration/test_cross_component_integration.py:528, 536`** - Mid-test processing
   - Lines 528/536: `QApplication.processEvents()` without condition
   - Fix: Wrap in `qtbot.waitUntil()` or signal waiter

3. **`test_optimized_threading.py:155, 351, 387`** - Mixed contexts
   - Some acceptable (after deleteLater), some should use conditions

---

## Rule #3 Compliance Checklist

According to UNIFIED_TESTING_V2.MD Rule #3:

```python
# ✅ CORRECT PATTERNS
with qtbot.waitSignal(worker.finished, timeout=5000):
    worker.start()

qtbot.waitUntil(lambda: condition, timeout=2000)

from tests.helpers.synchronization import wait_for_condition
wait_for_condition(lambda: widget.is_ready, timeout_ms=2000)

# ❌ VIOLATIONS
time.sleep(0.5)          # Direct sleep - flaky
qtbot.wait(100)          # Timing-based - flaky under load
QCoreApplication.processEvents()  # Without condition - flaky
```

---

## Violation Summary by File

### Top Offenders (by violation count):

| File | time.sleep() | qtbot.wait() | processEvents() | Action |
|---|---|---|---|---|
| `integration/test_main_window_complete.py` | 0 | ~10 | 3 | HIGH: Replace qtbot.wait() with waitExposed/waitUntil |
| `unit/test_threede_shot_grid.py` | 0 | ~6 | 0 | HIGH: Replace with signal/condition waiting |
| `unit/test_shot_grid_widget.py` | 0 | ~4 | 0 | HIGH: Use condition-based waiting |
| `conftest.py` | 0 | 2 | 7 | ACCEPTABLE: All in cleanup context |
| `unit/test_threading_fixes.py` | 1 | 5 | 0 | MEDIUM: Review sleep context, replace qtbot.wait() |
| `integration/test_cross_component_integration.py` | 0 | 8 | 5 | HIGH: Document processEvents context |

---

## Recommended Fixes

### Priority 1: Replace qtbot.wait() with Conditions (308 cases)

**Pattern 1 - Signal-based waiting:**
```python
# ❌ BEFORE
action.trigger()
qtbot.wait(100)
assert result == expected

# ✅ AFTER
with qtbot.waitSignal(widget.signal_updated, timeout=1000):
    action.trigger()
assert result == expected
```

**Pattern 2 - Condition-based waiting:**
```python
# ❌ BEFORE
view.refresh()
qtbot.wait(50)
assert view.item_count > 0

# ✅ AFTER
view.refresh()
qtbot.waitUntil(lambda: view.item_count > 0, timeout=1000)
```

**Pattern 3 - Helper-based waiting:**
```python
# ❌ BEFORE
qtbot.wait(100)

# ✅ AFTER (from tests/helpers/synchronization.py)
from tests.helpers.synchronization import wait_for_condition
wait_for_condition(lambda: widget.property_updated, timeout_ms=1000)
```

### Priority 2: Clean up time.sleep() (25 cases)

1. **Stress tests** - Already documented, acceptable
2. **Worker simulation** - Acceptable in test doubles
3. **Timing-sensitive tests** - Consider using `unittest.mock.patch` for time

### Priority 3: Document processEvents() (35 cases)

Current usage is mostly acceptable, but add clarity:
```python
# ✅ GOOD - explicit cleanup context
try:
    widget.start()
    qtbot.waitUntil(lambda: widget.done, timeout=2000)
finally:
    # Process deletion queue (deleteLater() calls)
    qapp.processEvents()
```

---

## Test Isolation Impact

These violations directly impact test reliability under parallel execution (`pytest -n 2`, `-n auto`):

1. **qtbot.wait() (308 cases)**: HIGH IMPACT
   - CPU contention can make delays insufficient
   - Intermittent failures under load
   - Flaky test reports

2. **time.sleep() (25 cases)**: MEDIUM IMPACT
   - Except in documented stress tests
   - Slows down test suite unnecessarily

3. **processEvents() (35 cases)**: LOW IMPACT
   - Most are in cleanup context (acceptable)
   - Need documentation for clarity

---

## Recommended Audit Actions

### Immediate (This Week):
- [ ] Add inline documentation for all `time.sleep()` usage explaining why it's necessary
- [ ] Add comments distinguishing cleanup `processEvents()` from mid-test `processEvents()`

### Short-term (2 weeks):
- [ ] Replace high-risk `qtbot.wait()` in integration tests with proper conditions
- [ ] Create helper functions for common synchronization patterns in `tests/helpers/synchronization.py`

### Medium-term (1 month):
- [ ] Systematic replacement of all `qtbot.wait()` with `qtbot.waitSignal()` or `qtbot.waitUntil()`
- [ ] Add linter rule to catch new `time.sleep()` violations in tests/
- [ ] Document expected synchronization pattern for each test file

### Long-term (Ongoing):
- [ ] Consider pytest plugin to warn on timing-based patterns
- [ ] CI check for synchronization rule compliance
- [ ] Training for developers on proper Qt test patterns

---

## Files Requiring Attention

### High Priority (Many violations, easily fixable):
1. `/home/gabrielh/projects/shotbot/tests/integration/test_main_window_complete.py`
2. `/home/gabrielh/projects/shotbot/tests/unit/test_threede_shot_grid.py`
3. `/home/gabrielh/projects/shotbot/tests/unit/test_shot_grid_widget.py`

### Medium Priority (Review needed):
1. `/home/gabrielh/projects/shotbot/tests/unit/test_thread_safety_validation.py`
2. `/home/gabrielh/projects/shotbot/tests/integration/test_user_workflows.py`
3. `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py`

### Low Priority (Mostly acceptable):
1. `/home/gabrielh/projects/shotbot/tests/conftest.py` (cleanup context)
2. `/home/gabrielh/projects/shotbot/tests/unit/test_process_pool_manager.py` (mock context)

---

## Conclusion

The test suite has **systematic use of timing-based waiting patterns** that violate UNIFIED_TESTING_V2.MD Rule #3. While not immediately critical (tests pass most of the time), this creates **fragility under high-load conditions** and **intermittent failures in parallel execution**.

**Primary Issue:** 308 `qtbot.wait()` calls that should use condition-based waiting

**Secondary Issues:** 25 `time.sleep()` calls and 35 bare `processEvents()` calls

**Recommended Action:** Prioritize replacing `qtbot.wait()` with `qtbot.waitUntil()`/`qtbot.waitSignal()` in the identified high-priority files, focusing on integration tests which are most sensitive to timing variations.

