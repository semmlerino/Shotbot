# Test Isolation Issues - Quick Reference

**12 Major Violations Found** | **Status**: Masked by xdist_group band-aids  
**Severity**: 6 CRITICAL, 4 HIGH, 2 MEDIUM

## Critical Issues (Fix First)

### Issue #1: Module-Scoped Autouse Fixtures (12 files)
```python
# ❌ WRONG
@pytest.fixture(scope="module", autouse=True)  # Line 36 in test_main_window.py
def setup_qt_imports():
    global MainWindow  # Global state + module scope = isolation failure
    from main_window import MainWindow
```
**Files**: test_main_window.py:36, test_main_window_fixed.py:40, test_exr_edge_cases.py:44, 
6 integration tests

**Fix**: Remove scope="module" and autouse=True; import at module level

---

### Issue #2: Module-Level QCoreApplication Creation (2 files)
```python
# ❌ WRONG
def test_subprocess_handles_large_output():  # test_subprocess_no_deadlock.py:121
    app = QCoreApplication.instance() or QCoreApplication([])  # Creates app in test
```
**Files**: test_subprocess_no_deadlock.py:121, test_type_safe_patterns.py:482

**Fix**: Use `qapp` fixture instead: `def test_name(qapp):`

---

### Issue #3: Global Variable Assignments (9 files)
```python
# ❌ WRONG
@pytest.fixture(scope="module", autouse=True)
def setup_qt_imports():
    global MainWindow  # ← Shared across workers in parallel execution
    from main_window import MainWindow
```
**Files**: test_main_window*.py, 6 integration tests, test_exr_edge_cases.py

**Fix**: Import at module level (no fixture needed)

---

## High Priority Issues

### Issue #4: xdist_group Band-Aids (41+ files)
```python
# ❌ WRONG - Masks real isolation issues
pytestmark = [pytest.mark.xdist_group("qt_state")]  # Serializes tests
```
**Files**: 25+ unit tests, 10+ integration tests

**Impact**: Tests run serially instead of parallel → 7-8x speed loss

**Fix**: Remove xdist_group, fix root causes (Issues #1-3)

---

### Issue #5: Singleton State Not Using monkeypatch (7 files)
```python
# PROBLEMATIC - Direct manipulation
@pytest.fixture(autouse=True)
def clear_module_caches():
    NotificationManager._instance = None  # Direct state manipulation
    yield
    NotificationManager._instance = None  # Repeated cleanup
```
**Files**: conftest.py (3 singletons), test_notification_manager.py, test_filesystem_coordinator.py, 
test_progress_manager.py

**Fix**: Use monkeypatch instead: `monkeypatch.setattr(NotificationManager, "_instance", None)`

---

### Issue #5a: Unnecessary Autouse Singleton Resets (2 files)
```python
# ❌ WRONG - Autouse for non-essential fixture
@pytest.fixture(autouse=True)  # Applies to ALL tests
def reset_singleton():
    FilesystemCoordinator._instance = None
```
**Files**: test_filesystem_coordinator.py:32, conftest.py

**Fix**: Make explicit (only use autouse for Qt, cache, QMessageBox, random)

---

## Medium Priority Issues

### Issue #6: time.sleep() Instead of Synchronization (20+ instances)
```python
# ❌ WRONG
time.sleep(0.02)  # Flaky, slow, non-deterministic

# ✅ RIGHT
with qtbot.waitSignal(worker.finished, timeout=5000):
    worker.start()
```
**Files**: 11 test files with 20+ sleep() calls

**Impact**: Flaky tests, slow execution, non-deterministic failures

---

### Issue #7: Incomplete Qt Cleanup in Test Classes (2 files)
```python
# PROBLEM - Only cleans THIS test class
class TestNotificationManager:
    @pytest.fixture(autouse=True)
    def cleanup(self):
        yield
        NotificationManager.cleanup()  # Only for THIS class
```
**Files**: test_notification_manager.py:174, test_progress_manager.py:74

**Fix**: Centralize in conftest.py autouse fixture (affects all tests)

---

## Summary

| Issue | Count | Severity | Fix Effort | Impact |
|-------|-------|----------|-----------|--------|
| Module-scoped autouse | 12 | CRITICAL | 2-3h | Blocks parallelism |
| Module-level QApp | 2 | CRITICAL | 30m | Crash risk |
| Global vars | 9 | CRITICAL | 1-2h | Isolation failure |
| xdist_group band-aids | 41+ | HIGH | 3-4h | 7-8x speed loss |
| Singleton not monkeypatched | 7 | HIGH | 1-2h | Race conditions |
| Unnecessary autouse | 2 | HIGH | 30m | Overhead |
| time.sleep() | 20+ | MEDIUM | 2-3h | Flakiness |
| Incomplete Qt cleanup | 2 | MEDIUM | 1h | Coverage gap |

**Total Effort**: 12-16 hours  
**Expected Speed Gain**: 7-8x (30s vs 60s serial run)

---

## Verification Checklist

After fixes:
- [ ] Run serially: `pytest tests/ -n 0` ✓ passes
- [ ] Run parallel: `pytest tests/ -n auto` ✓ passes same tests
- [ ] Run random order: `pytest tests/ --randomly-seed=auto` ✓ passes
- [ ] No xdist_group marks (except external constraints)
- [ ] No module-scoped autouse fixtures
- [ ] No global variable assignments from fixtures
- [ ] All singletons reset via monkeypatch (explicit fixtures)

---

## Quick Fixes by Priority

**TODAY (30 min):**
1. Fix test_subprocess_no_deadlock.py:121 - Add qapp fixture
2. Fix test_type_safe_patterns.py:482 - Add qapp fixture

**THIS WEEK (6-8 hours):**
3. Remove module-scoped autouse fixtures (12 files)
4. Move imports to module level (9 files)
5. Remove 41+ xdist_group marks
6. Run tests in parallel to verify

**NEXT WEEK (4-6 hours):**
7. Replace time.sleep() with synchronization
8. Centralize Qt cleanup
9. Use monkeypatch for singletons

---

## Key Reference Files

- Full audit: `TEST_ISOLATION_AUDIT.md`
- Testing guide: `UNIFIED_TESTING_V2.MD`
- Current conftest: `tests/conftest.py`
- Example violation: `tests/unit/test_main_window.py:36-52`
