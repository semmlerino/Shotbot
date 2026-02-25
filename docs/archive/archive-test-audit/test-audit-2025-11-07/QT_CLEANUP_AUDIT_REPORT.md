# Qt Resource Cleanup Audit Report

**Date**: 2025-11-07  
**Status**: VIOLATIONS FOUND  
**Compliance Target**: UNIFIED_TESTING_V2.MD "Large Qt Test Suite Stability" section  

---

## Executive Summary

The test suite has **95 violations** across **23 test files** where `deleteLater()` is called without flushing deferred deletes using `processEvents()` or `sendPostedEvents()`.

### Key Violation Pattern

```python
# ❌ WRONG - Qt C++ objects accumulate, crashes in large suites
worker.deleteLater()
# Returns immediately without cleanup

# ✅ RIGHT - Qt C++ objects actually deleted
worker.deleteLater()
QCoreApplication.processEvents()  # Flush deletion queue
QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)  # Handle cascades
QCoreApplication.processEvents()  # Process cascading deletes
```

### Why This Matters

From UNIFIED_TESTING_V2.MD section "Large Qt Test Suite Stability":

> After `deleteLater()`, flush deferred deletes (processEvents + sendPostedEvents)
> This is CRITICAL - without deleteLater() + flushing, the Qt C++ object accumulates across tests, causing segfaults in large test suites when run serially.

---

## Violation Severity Classification

### CRITICAL (Affects Try/Finally Blocks)
**38 violations** in `/tests/unit/test_launcher_worker.py`

All 38 violations follow the pattern:
```python
try:
    # test code
finally:
    worker.safe_stop()
    worker.deleteLater()
    # ❌ MISSING: processEvents() after deleteLater()
```

**Impact**: Try/finally cleanup guaranteed, but Qt C++ objects NOT freed immediately → accumulate

---

## Files with Violations

### HIGH IMPACT (Multiple deleteLater() per file)

1. **`tests/unit/test_launcher_worker.py`** - 38 violations
   - Lines: 100, 111, 131, 157, 173, 186, 199, 211, 225, 261, 295, 318, 355, 382, 409, 446, 473, 503, 526, 555, 572, 594, 614, 648, 674, 713, 746, 747, 772, 794, 827, 845, 858, 890, 909, 935, 955, 983
   - Pattern: All in finally blocks, all missing event processing

2. **`tests/integration/test_async_workflow_integration.py`** - 4 violations
   - Lines: 156, 157, 431, 470

3. **`tests/integration/test_cross_component_integration.py`** - 5 violations
   - Lines: 95, 157, 356, 437, 602

4. **`tests/unit/test_previous_shots_model.py`** - 6 violations
   - Lines: 93, 123, 137, 471, 570, 593

5. **`tests/unit/test_show_filter.py`** - 5 violations
   - Lines: 154, 237, 297, 379, 388

### MEDIUM IMPACT (3-4 violations)

- `tests/integration/test_launcher_panel_integration.py` - 3 violations (lines 122, 392, 598)
- `tests/unit/test_previous_shots_grid.py` - 3 violations (lines 120, 151, 539)
- `tests/unit/test_shot_info_panel_comprehensive.py` - 3 violations (lines 65, 238, 394)
- `tests/unit/test_qt_integration_optimized.py` - 3 violations (lines 31, 104, 174)
- `tests/unit/test_text_filter.py` - 5 violations (lines 278, 331, 381, 400, 401)
- `tests/unit/test_template.py` - 3 violations (lines 82, 185, 219)

### LOW IMPACT (1-2 violations)

- `tests/integration/test_feature_flag_simplified.py` - 2 violations (lines 194, 206)
- `tests/integration/test_launcher_workflow_integration.py` - 1 violation (line 78)
- `tests/integration/test_main_window_complete.py` - 1 violation (line 161)
- `tests/integration/test_main_window_coordination.py` - 1 violation (line 345)
- `tests/integration/test_terminal_integration.py` - 1 violation (line 419)
- `tests/integration/test_threede_worker_workflow.py` - 1 violation (line 25)
- `tests/integration/test_user_workflows.py` - 1 violation (line 754)
- `tests/unit/test_base_thumbnail_delegate.py` - 1 violation (line 858)
- `tests/unit/test_launcher_process_manager.py` - 1 violation (line 52)
- `tests/unit/test_previous_shots_item_model.py` - 1 violation (line 56)
- `tests/unit/test_shot_item_model_comprehensive.py` - 2 violations (lines 65, 180)
- `tests/unit/test_threading_fixes.py` - 4 violations (lines 112, 160, 291, 325)

---

## Compliant Patterns Found

Some test files DO follow the correct pattern. Examples:

### ✅ Correct Pattern in `test_threading_fixes.py:325`
```python
finally:
    # Clean up all test timers
    for timer in test_timers:
        if timer is not None:
            timer.stop()
            try:
                timer.timeout.disconnect()
            except RuntimeError:
                pass
            timer.deleteLater()

    # Process Qt events to ensure cleanup is executed  ← ✅ CORRECT
    qtbot.wait(1)
```

### ✅ Correct Pattern in `test_thread_safety_regression.py:328-330`
```python
receiver.deleteLater()
qapp.processEvents()  # Process deletion ← ✅ CORRECT
```

### ✅ Correct Pattern in `qt_thread_cleanup.py:99-111`
```python
# Step 3: Schedule Qt C++ object for deletion
thread.deleteLater()

# Step 4: Process events to flush the deletion queue
QCoreApplication.processEvents()

# Step 5: Process deferred deletes explicitly
QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

# Step 6: Process events again for cascading cleanups
QCoreApplication.processEvents()
```

---

## Recommended Fix Strategy

### Option 1: Minimal - Add Event Processing (RECOMMENDED)

Add after each `deleteLater()` call:
```python
worker.deleteLater()
qtbot.wait(1)  # Flushes processEvents() internally
```

OR explicitly:
```python
worker.deleteLater()
QCoreApplication.processEvents()
QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
QCoreApplication.processEvents()
```

### Option 2: Use Cleanup Helpers

Use provided helper from `/tests/helpers/qt_thread_cleanup.py`:
```python
from tests.helpers.qt_thread_cleanup import cleanup_qthread_properly

try:
    worker.start()
    # test code
finally:
    cleanup_qthread_properly(worker)  # Handles all cleanup + event processing
```

### Option 3: Fixture-Based Cleanup (BEST PRACTICE)

Create fixture that ensures cleanup:
```python
@pytest.fixture
def worker_with_cleanup(qtbot):
    worker = LauncherWorker("test", "maya")
    yield worker
    try:
        worker.safe_stop()
    finally:
        worker.deleteLater()
        # Flush Qt deferred delete queue
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QCoreApplication.processEvents()
```

---

## Implementation Guidance

### Priority 1 - CRITICAL (Fix First)
File: `tests/unit/test_launcher_worker.py` (38 violations)
- All violations are in finally blocks (good!)
- Just need to add event processing at end of finally blocks

**Estimated Fix**: 15-20 minutes (mechanical replacement)

### Priority 2 - HIGH
Files with integration/cross-component tests:
- `tests/integration/test_async_workflow_integration.py`
- `tests/integration/test_cross_component_integration.py`
- `tests/integration/test_launcher_panel_integration.py`
- `tests/unit/test_previous_shots_model.py`

**Estimated Fix**: 30-45 minutes total

### Priority 3 - MEDIUM/LOW
Remaining 18 files with 1-5 violations each

**Estimated Fix**: 60-90 minutes total

---

## Testing After Fix

To verify the fix:

```bash
# Run in serial to catch Qt leaks deterministically
cd ~/projects/shotbot
~/.local/bin/uv run pytest tests/ -n 0 -v

# Run repeatedly to ensure no gradual degradation
for i in {1..5}; do
  ~/.local/bin/uv run pytest tests/ -n 0 -q
  echo "Run $i completed"
done
```

---

## References

- **UNIFIED_TESTING_V2.MD**: Section "Large Qt Test Suite Stability" (lines 624-741)
  - Cleanup pattern documentation
  - Explanation of Qt C++ object accumulation
  - Complete hardening checklist

- **Qt Thread Cleanup Helpers**: `/tests/helpers/qt_thread_cleanup.py`
  - `cleanup_qthread_properly()` - Complete cleanup sequence
  - `create_cleanup_handler()` - For use in try/finally blocks

- **Qt Documentation**: 
  - [QObject::deleteLater()](https://doc.qt.io/qt-6/qobject.html#deleteLater)
  - [Qt Object Trees](https://doc.qt.io/qt-6/objecttrees.html)
  - [QCoreApplication::processEvents](https://doc.qt.io/qt-6/qcoreapplication.html#processEvents)

---

## Appendix: Complete Violation List

### test_launcher_worker.py (38 violations)

**Lines with missing event processing:**
100, 111, 131, 157, 173, 186, 199, 211, 225, 261, 295, 318, 355, 382, 409, 446, 473, 503, 526, 555, 572, 594, 614, 648, 674, 713, 746, 747, 772, 794, 827, 845, 858, 890, 909, 935, 955, 983

**Pattern example (line 100):**
```python
finally:
    worker.safe_stop()
    worker.deleteLater()
    # ❌ Missing: processEvents()
```

### test_async_workflow_integration.py (4 violations)
Lines: 156, 157, 431, 470

### test_cross_component_integration.py (5 violations)
Lines: 95, 157, 356, 437, 602

### test_launcher_panel_integration.py (3 violations)
Lines: 122, 392, 598

### test_previous_shots_model.py (6 violations)
Lines: 93, 123, 137, 471, 570, 593

### test_show_filter.py (5 violations)
Lines: 154, 237, 297, 379, 388

### test_text_filter.py (5 violations)
Lines: 278, 331, 381, 400, 401

### And 16 more files with 1-4 violations each...

---

**Report Generated**: 2025-11-07  
**Status**: Ready for remediation
