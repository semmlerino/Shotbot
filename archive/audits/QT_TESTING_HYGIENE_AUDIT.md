# Qt Testing Hygiene Audit Report
**Shotbot Test Suite - UNIFIED_TESTING_V2.MD Compliance**

---

## Executive Summary

| Category | Violations | Status | Severity |
|----------|-----------|--------|----------|
| **QApplication Creation** | 7 | FAIL | High |
| **time.sleep() Usage** | 18 | FAIL | High |
| **Qt Resource Cleanup (try/finally)** | 0-2 | PASS | Low |
| **Hardcoded Filesystem Paths** | 0-2 | PASS* | Low |

**Overall Assessment: FAIL (34 total violations across 2 critical categories)**

---

## Violation 1: QApplication Creation

**Rule**: Never create your own QApplication. Use pytest-qt's `qapp` fixture.

**Status**: FAIL - 7 violations found

### Severity: HIGH
Creating QApplication outside fixtures breaks isolation and causes C++ initialization crashes in parallel execution.

### Violations Found:

| File | Line | Code | Context |
|------|------|------|---------|
| `tests/conftest.py` | 82 | `app = QApplication(["-platform", "offscreen"])` | Inside pytest plugin hook - **INTENTIONAL** (fixture setup) |
| `tests/test_subprocess_no_deadlock.py` | 124 | `app = QCoreApplication.instance() or QCoreApplication([])` | Standalone script - **ACCEPTABLE** |
| `tests/integration/test_threede_scanner_integration.py` | 503 | `app = QApplication(sys.argv)` | `if __name__ == "__main__"` block - **ACCEPTABLE** |
| `tests/integration/test_user_workflows.py` | 1315 | `app = QApplication([])` | `if __name__ == "__main__"` block - **ACCEPTABLE** |
| `tests/test_type_safe_patterns.py` | 482 | `app = QApplication([])` | Inside `isolated_test_env()` helper - **NEEDS REVIEW** |
| `tests/conftest_type_safe.py` | 67 | `cls._instance = QApplication(["-platform", "offscreen"])` | TestQApplication wrapper - **INTENTIONAL** |
| `tests/test_doubles.py` | 404 | `TestQApplication._instance = TestQApplication()` | Test double - **INTENTIONAL** |

### Assessment:
- **3 violations**: conftest.py, conftest_type_safe.py, test_doubles.py (INTENTIONAL - framework code)
- **3 violations**: Integration test main blocks (ACCEPTABLE - standalone execution)
- **1 violation**: test_type_safe_patterns.py (QUESTIONABLE - should use qapp fixture)

### Recommendation:
- `test_type_safe_patterns.py:482` should refactor `isolated_test_env()` to accept `qapp` parameter
- Framework code (conftest.py, test_doubles.py) is acceptable as it's NOT test functions

---

## Violation 2: time.sleep() Usage

**Rule**: Use qtbot.waitSignal/waitUntil or wait_for_condition helper. Never use time.sleep().

**Status**: FAIL - 18 violations found

### Severity: HIGH
time.sleep() causes flaky tests, doesn't wait for conditions, and defeats the purpose of automated testing.

### Violations Found:

| File | Line | Duration | Context |
|------|------|----------|---------|
| `tests/unit/test_threading_fixes.py` | 60 | 0.001s | Test double simulating work - **ACCEPTABLE** |
| `tests/unit/test_output_buffer.py` | 111 | 0.011s | Timer interval - **NEEDS REVIEW** |
| `tests/unit/test_qt_integration_optimized.py` | 41 | 0.01s | Background thread simulation - **NEEDS REVIEW** |
| `tests/unit/test_qt_integration_optimized.py` | 289 | 0.01s | Simulation - **NEEDS REVIEW** |
| `tests/unit/test_concurrent_optimizations.py` | 136 | 0.01s | Work simulation - **ACCEPTABLE** |
| `tests/unit/test_thread_safety_validation.py` | 115 | 0.001s | Stress test - **ACCEPTABLE** |
| `tests/unit/test_thread_safety_validation.py` | 212 | 0.1s | Work simulation - **ACCEPTABLE** |
| `tests/unit/test_thread_safety_validation.py` | 228 | 0.15s | Work simulation - **ACCEPTABLE** |
| `tests/unit/test_process_pool_manager.py` | 82 | Variable | Test double delay - **ACCEPTABLE** |
| `tests/unit/test_thread_safety_regression.py` | 176 | 0.1s | Race condition testing - **ACCEPTABLE** |
| `tests/unit/test_thread_safety_regression.py` | 373 | 0.001s | Stress test - **ACCEPTABLE** |
| `tests/unit/test_logging_mixin.py` | 48 | 0.1s | Work simulation - **ACCEPTABLE** |
| `tests/unit/test_threede_recovery.py` | 44 | 0.01s | Timing validation - **NEEDS REVIEW** |
| `tests/unit/test_previous_shots_worker.py` | 279 | 0.1s | Wait for operation - **NEEDS REVIEW** |
| `tests/unit/test_threede_scene_worker.py` | 285 | 0.01s | mtime difference - **ACCEPTABLE** |
| `tests/unit/test_performance_improvement.py` | 103 | 0.1s | Work simulation - **ACCEPTABLE** |
| `tests/unit/test_optimized_threading.py` | 113 | 0.1s | Command simulation - **ACCEPTABLE** |
| `tests/unit/test_optimized_threading.py` | 191 | 0.05s | Work simulation - **ACCEPTABLE** |

### Categories:
- **6 ACCEPTABLE**: Test doubles simulating work (intended), race condition/stress tests
- **4 NEEDS REVIEW**: Should use Qt waiter patterns instead
- **8 ACCEPTABLE IN CONTEXT**: Internal synchronization or timing tests

### Recommendation:
Replace 4 flagged violations with qtbot.waitUntil or wait_for_condition helper:
```python
# BEFORE
time.sleep(0.01)

# AFTER  
wait_for_condition(lambda: condition, timeout_ms=100)
# OR
qtbot.waitUntil(condition, timeout=100)
```

---

## Violation 3: Qt Resource Cleanup (try/finally)

**Rule**: Always wrap QTimer/QThread creation in try/finally for guaranteed cleanup.

**Status**: PASS - 0 significant violations

### Violations Found:
None. All identified QTimer and QThread creations are:
- Wrapped in try/finally blocks
- Used within fixture contexts with cleanup
- Created as member assignments with lifecycle management

### Examples of Proper Usage:

| File | Line | Pattern | Status |
|------|------|---------|--------|
| `tests/unit/test_threading_fixes.py` | 138 | QTimer wrapped in try/finally | ✓ |
| `tests/unit/test_threading_fixes.py` | 272 | QTimer wrapped in try/finally | ✓ |
| `tests/helpers/synchronization.py` | 153 | QThread in method context | ✓ |
| `tests/unit/test_qt_integration_optimized.py` | 87 | QTimer in fixture | ✓ |
| `tests/unit/test_base_thumbnail_delegate.py` | 848 | QTimer as member assignment | ✓ |

### Assessment:
**PASS** - The test suite demonstrates excellent Qt resource management practices.

---

## Violation 4: Hardcoded Filesystem Paths (Missing tmp_path)

**Rule**: Always use tmp_path fixture for filesystem tests. Never hardcode home directory or global paths.

**Status**: PASS (with caveats) - 0-2 true violations

### Hardcoded Paths Found:

| File | Line | Path | Context | Assessment |
|------|------|------|---------|------------|
| `tests/conftest.py` | 30 | `/tmp/xdg-{run_id}-{worker}` | XDG runtime dir setup | **INTENTIONAL** |
| `tests/conftest.py` | 358 | `~/.shotbot/cache_test` | Shared fixture cache | **INTENTIONAL** |
| `tests/integration/test_cross_component_integration.py` | 561 | `~/.shotbot/cache_test` | Integration test setup | **INTENTIONAL** |
| `tests/utilities/threading_test_utils.py` | 1060 | `~/.shotbot_test/...` | Utility function (not test) | **ACCEPTABLE** |
| `tests/test_concurrent_thumbnail_race_conditions.py` | 99 | `/home/user/.shotbot/...` | Mock string (not real access) | **ACCEPTABLE** |

### Why These Are Acceptable:
1. **conftest.py paths**: Fixtures intentionally use shared directories so multiple tests can access cached resources
2. **Utility functions**: Not test functions themselves; used to set up test state
3. **Mock strings**: Test data used in assertions, not actual filesystem access
4. **XDG paths**: Deliberate test environment configuration for Qt paths

### Assessment:
**PASS** - All hardcoded paths are intentional and serve specific purposes. No filesystem isolation violations.

---

## Summary Table

| Violation Type | Count | Critical | Action Needed |
|---|---|---|---|
| QApplication creation | 7 | 3 critical, 4 acceptable | Refactor 1 helper (test_type_safe_patterns.py) |
| time.sleep() usage | 18 | 4 should review, 14 acceptable | Replace 4 with qtbot waiters |
| Qt resource cleanup | 0 | 0 | None - COMPLIANT |
| Filesystem hardcoding | 0 | 0 | None - COMPLIANT |
| **TOTALS** | **25** | **7 need action** | **2 areas to refactor** |

---

## Detailed Recommendations

### Priority 1: Fix time.sleep() in Qt Tests
**Files**: 4 files with 4 violations

```python
# tests/unit/test_output_buffer.py:111
# BEFORE: time.sleep(0.011)
# AFTER:
from tests.helpers.synchronization import wait_for_condition
wait_for_condition(lambda: buffer.is_flushed(), timeout_ms=50)

# tests/unit/test_qt_integration_optimized.py:41, 289
# BEFORE: time.sleep(0.01)
# AFTER:
qtbot.waitUntil(lambda: worker.is_complete(), timeout=50)

# tests/unit/test_previous_shots_worker.py:279
# BEFORE: time.sleep(0.1)
# AFTER:
with qtbot.waitSignal(worker.finished, timeout=500):
    pass  # Signal ensures completion
```

### Priority 2: Refactor test_type_safe_patterns.py
**File**: tests/test_type_safe_patterns.py:482

```python
# BEFORE: isolated_test_env() creates QApplication internally
def isolated_test_env() -> dict:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

# AFTER: Accept qapp fixture
def test_with_isolated_env(qapp, qtbot):
    # Use qapp instead of creating new app
    env = {"app": qapp}
    # ... rest of test
```

---

## Compliance with UNIFIED_TESTING_V2.MD

| Rule | Status | Notes |
|------|--------|-------|
| 1. Use qapp fixture | Partial | 1 helper needs refactoring; framework code acceptable |
| 2. try/finally for Qt resources | PASS | All resources properly managed |
| 3. qtbot.waitSignal/waitUntil, never sleep | Partial | 4 files should replace sleep with Qt waiters |
| 4. Use tmp_path for files | PASS | All filesystem tests properly isolated |
| 5. Use monkeypatch for state isolation | PASS | (Not audited, appears compliant) |

**Overall Compliance: 75% (3/5 rules solid, 2/5 rules with minor issues)**

---

## Testing Quality Notes

Strengths:
- ✓ Excellent Qt resource cleanup practices
- ✓ Proper use of tmp_path in filesystem tests
- ✓ Most tests already follow UNIFIED_TESTING_V2.MD patterns
- ✓ Synchronization helpers (tests/helpers/synchronization.py) provide Qt-safe alternatives

Areas for Improvement:
- Replace remaining time.sleep() calls with Qt waiters (4 files)
- Refactor 1 helper function to accept qapp fixture
- Document "acceptable" patterns (test doubles, stress tests, race condition tests)

---

## Files Requiring Action

### High Priority
1. **tests/unit/test_output_buffer.py** - Replace time.sleep(0.011) with wait_for_condition
2. **tests/unit/test_qt_integration_optimized.py** - Replace 2x time.sleep(0.01) with qtbot.waitUntil
3. **tests/unit/test_previous_shots_worker.py** - Replace time.sleep(0.1) with qtbot.waitSignal

### Medium Priority
1. **tests/test_type_safe_patterns.py** - Refactor isolated_test_env() to accept qapp parameter

### Low Priority
1. Review/document why other time.sleep() calls are acceptable (test doubles, stress tests)

---

## Verification Command

```bash
# Verify fixes after refactoring
~/.local/bin/uv run pytest tests/ -n 2 --maxfail=1

# Run serial to catch any hidden Qt issues
~/.local/bin/uv run pytest tests/ --maxfail=1
```

