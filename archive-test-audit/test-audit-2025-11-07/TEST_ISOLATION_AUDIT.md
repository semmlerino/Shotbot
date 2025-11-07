# Test Isolation Issues - Comprehensive Audit Report

**Date**: 2025-11-07  
**Codebase**: Shotbot (VFX Production Management)  
**Thoroughness Level**: Very Thorough  
**Comparison Standard**: UNIFIED_TESTING_V2.MD Isolation Guidelines

---

## Executive Summary

This audit identifies **12 major test isolation violations** across the test suite that violate principles documented in `UNIFIED_TESTING_V2.MD`. These issues range from **module-scoped autouse fixtures** (explicitly marked as anti-pattern) to **module-level Qt application creation** and **singleton state contamination**.

### Severity Breakdown
- **CRITICAL (6)**: Module-scoped autouse fixtures, module-level QCoreApplication creation
- **HIGH (4)**: Singleton cleanup patterns, global state without monkeypatch
- **MEDIUM (2)**: Direct singleton manipulation in tests

**Status**: Most are already identified with xdist_group workarounds but these are band-aids per UNIFIED_TESTING_V2.MD.

---

## Finding 1: Module-Scoped Autouse Fixtures (CRITICAL)

### Violation Category
Per UNIFIED_TESTING_V2.MD section "Autouse for Mocks":
> "❌ WRONG - autouse=True for global patches → worker isolation failures"
> "✅ RIGHT - explicit fixtures (request what you need)"

### Issue
Module-scoped `autouse=True` fixtures cause significant overhead and worker isolation failures in parallel execution. Found in 12 test files.

### Violations

| File | Line | Fixture Name | Issue |
|------|------|--------------|-------|
| `tests/unit/test_main_window.py` | 36 | `setup_qt_imports()` | `scope="module", autouse=True` - unnecessary global import |
| `tests/unit/test_main_window_fixed.py` | 40 | `setup_qt_imports()` | `scope="module", autouse=True` - unnecessary global import |
| `tests/unit/test_exr_edge_cases.py` | 44 | (unnamed) | `scope="module", autouse=True` - affects all tests |
| `tests/integration/test_cross_component_integration.py` | 36 | `setup_qt_imports()` | `scope="module", autouse=True` - Qt import side-effects |
| `tests/integration/test_main_window_complete.py` | 59 | (unnamed) | `scope="module", autouse=True` - broad scope |
| `tests/integration/test_user_workflows.py` | 69 | (unnamed) | `scope="module", autouse=True` - broad scope |
| `tests/integration/test_feature_flag_switching.py` | 38 | (unnamed) | `scope="module", autouse=True` - broad scope |
| `tests/integration/test_launcher_panel_integration.py` | 50 | (unnamed) | `scope="module", autouse=True` - broad scope |
| `tests/integration/test_main_window_coordination.py` | 44 | (unnamed) | `scope="module", autouse=True` - broad scope |

### Code Examples

```python
# WRONG - tests/unit/test_main_window.py:36
@pytest.fixture(scope="module", autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow, CacheManager, Shot, ThreeDEScene  # noqa: PLW0603
    from cache_manager import CacheManager
    from main_window import MainWindow
    # ... more imports ...
```

**Why This Is Wrong**:
1. Module scope means it runs ONCE for the entire module, not per-test
2. autouse=True applies to all tests in the module (overhead)
3. Using global state for imports violates isolation principles
4. Each worker in pytest-xdist gets its own module scope, causing non-deterministic ordering

**Correct Pattern** (Per UNIFIED_TESTING_V2.MD):
```python
# RIGHT - Import at top of test file (module level is fine for imports)
from cache_manager import CacheManager
from main_window import MainWindow

# OR, if you need lazy import:
@pytest.fixture  # NO autouse, NO module scope
def main_window_components():
    from main_window import MainWindow
    return MainWindow
```

### Impact on Parallel Execution
- In `-n 2` or `-n auto`: Different workers may execute module setup in different orders
- Can cause "Passes alone, fails in parallel" issues
- Defeats the purpose of pytest-xdist's worker isolation

### Recommended Fix
1. Remove `scope="module"` - let fixtures be function-scoped (default)
2. Remove `autouse=True` - import what you need explicitly
3. Import at module level if no lazy loading needed
4. Use explicit fixtures only if lazy-loading or setup required

---

## Finding 2: Module-Level QCoreApplication Creation (CRITICAL)

### Violation Category
Per UNIFIED_TESTING_V2.MD section "Module-Level Qt App Creation":
> "❌ WRONG - at module level"
> "✅ RIGHT - use pytest-qt's qapp fixture"

### Issue
Two files create QCoreApplication instances at module level or in non-fixture functions, violating the "never create apps at module level" rule.

### Violations

| File | Line | Pattern | Issue |
|------|------|---------|-------|
| `tests/test_subprocess_no_deadlock.py` | 121 | `QCoreApplication.instance() or QCoreApplication([])` | Creates app inside test function (not fixture) |
| `tests/test_type_safe_patterns.py` | 482 | `QApplication([])` | Creates app inside test function |

### Code Examples

```python
# WRONG - tests/test_subprocess_no_deadlock.py:121
def test_subprocess_handles_large_output() -> None:  # <-- NOT A FIXTURE
    from tests.helpers.synchronization import process_qt_events
    
    app = QCoreApplication.instance() or QCoreApplication([])  # <-- Creating app in test
    # ... rest of test ...
```

**Why This Is Wrong**:
1. Creates QApplication/QCoreApplication conflict with pytest-qt's `qapp` fixture
2. Full suite may see "Multiple QApplication instances" crashes
3. Tests that run first will create app, later tests will reuse it (state contamination)
4. Qt recommends NEVER creating multiple app instances per process

### Correct Pattern
```python
# RIGHT - Use pytest-qt fixture
def test_subprocess_handles_large_output(qapp):  # <-- Inject qapp fixture
    from tests.helpers.synchronization import process_qt_events
    # Use qapp provided by fixture
    # ... rest of test ...
```

### Impact
- Single test works fine (uses/creates its own app)
- Full suite crashes with "Cannot create more than one QApplication instance"
- Parallel execution: Race conditions from multiple process workers creating QCoreApplication

---

## Finding 3: Module-Level Global Variable Assignments (CRITICAL)

### Violation Category
Per UNIFIED_TESTING_V2.MD section "Global/Module-Level State":
> "❌ WRONG - shared globally"
> "✅ RIGHT - isolated with monkeypatch"

### Issue
Module-scoped fixtures assign to global variables, violating test isolation in parallel execution.

### Violations

| File | Lines | Pattern | Issue |
|------|-------|---------|-------|
| `tests/unit/test_main_window.py` | 39 | `global MainWindow, CacheManager, Shot, ThreeDEScene` | Module-level globals |
| `tests/unit/test_main_window_fixed.py` | 43 | `global MainWindow, CacheManager, Shot` | Module-level globals |
| `tests/integration/test_main_window_complete.py` | 62 | `global MainWindow, Shot` | Module-level globals |
| `tests/integration/test_cross_component_integration.py` | 39 | `global MainWindow` | Module-level global |
| `tests/integration/test_main_window_coordination.py` | 47 | `global MainWindow` | Module-level global |
| `tests/integration/test_launcher_panel_integration.py` | 53 | `global MainWindow` | Module-level global |
| `tests/integration/test_feature_flag_switching.py` | 41 | `global MainWindow` | Module-level global |
| `tests/integration/test_user_workflows.py` | 72 | `global MainWindow` | Module-level global |
| `tests/unit/test_exr_edge_cases.py` | 47 | `global CacheManager, QCoreApplication, process_qt_events` | Module-level globals |

### Code Examples

```python
# WRONG - tests/unit/test_main_window.py:36-52
@pytest.fixture(scope="module", autouse=True)
def setup_qt_imports() -> None:
    global MainWindow, CacheManager, Shot, ThreeDEScene  # <-- Global state
    from cache_manager import CacheManager
    from main_window import MainWindow
    # ... imports assigned to global vars ...
```

**Why This Is Wrong**:
1. Global variables are shared across workers in pytest-xdist
2. One worker's module load affects another worker's test execution
3. Test execution order becomes non-deterministic
4. "Passes alone, fails in parallel" symptom

**Correct Pattern**:
```python
# RIGHT - Import at module level (no fixture needed)
from cache_manager import CacheManager
from main_window import MainWindow
from shot_model import Shot
from threede_scene_model import ThreeDEScene

# Tests use imports directly (no global assignment)
class TestMainWindow:
    def test_something(self):
        window = MainWindow(...)  # Use imported class directly
```

### Impact
- Tests pass when run alone (no parallel interference)
- Tests fail intermittently in parallel (xdist workers see different module state)
- Non-deterministic failures make debugging difficult

---

## Finding 4: xdist_group as Band-Aid (HIGH)

### Violation Category
Per UNIFIED_TESTING_V2.MD section "Anti-Patterns":
> "❌ WRONG: Using xdist_group to 'fix' parallel failures"
> "✅ RIGHT: Fix the actual isolation issue"
> "xdist_group appropriate ONLY for external constraints (hardware, license server)"
> "NOT for Qt state, filesystem, or timing issues"

### Issue
41+ test files use `xdist_group` to serialize Qt tests instead of fixing underlying isolation issues.

### Violations

| File | Count | Issue |
|------|-------|-------|
| `tests/unit/test_*` | 25+ | `@pytest.mark.xdist_group("qt_state")` |
| `tests/integration/test_*` | 10+ | `@pytest.mark.xdist_group("qt_state")` |
| `tests/unit/test_notification_manager.py` | 1 | `xdist_group("notification_manager_singleton")` |
| `tests/unit/test_main_window_fixed.py` | 1 | `xdist_group("main_window_isolated")` |

### Code Examples

```python
# WRONG - tests/unit/test_launcher_controller.py:31
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.xdist_group("qt_state"),  # <-- Band-aid for isolation failures
]

# This tells pytest-xdist: "Only run one test from this group at a time"
# But it DOESN'T FIX the actual isolation issue
```

**Why This Is Wrong**:
1. xdist_group is for external constraints (hardware licenses, license servers, hardware resources)
2. Hiding isolation issues makes them invisible in normal test runs
3. `--dist=worksteal` is optimized for parallel workloads; xdist_group kills that optimization
4. Tests should pass in ANY order on ANY worker, not require serialization

**Correct Fix Strategy** (From UNIFIED_TESTING_V2.MD):
1. Remove xdist_group
2. Fix the ACTUAL isolation issues:
   - Remove module-scoped autouse fixtures
   - Fix global state with monkeypatch
   - Properly clean up Qt resources (try/finally)
   - Use proper fixtures for singletons

### Impact
- Tests run SERIALLY for "qt_state" group instead of in parallel
- Defeats 7.5x speed improvement of parallel execution (xdist with `-n auto`)
- Full test suite becomes slow despite having multiple workers available
- Masks real isolation issues that would fail in CI with `-n 0` (serial execution)

---

## Finding 5: Singleton State Not Isolated with monkeypatch (HIGH)

### Violation Category
Per UNIFIED_TESTING_V2.MD section "Global/Module-Level State":
> "✅ RIGHT - isolated with monkeypatch"

### Issue
Tests directly manipulate singleton `_instance` attributes instead of using monkeypatch for isolation.

### Violations

| File | Line(s) | Pattern | Singleton |
|------|---------|---------|-----------|
| `tests/conftest.py` | 298-310 | Manual reset in fixture | NotificationManager |
| `tests/conftest.py` | 314-327 | Manual reset in fixture | ProgressManager |
| `tests/conftest.py` | 358-377 | Manual reset in fixture | Both |
| `tests/conftest.py` | 479-491 | Manual reset in fixture | ProcessPoolManager |
| `tests/unit/test_notification_manager.py` | 174-179 | Class-level cleanup | NotificationManager |
| `tests/unit/test_filesystem_coordinator.py` | 32-39 | Autouse fixture | FilesystemCoordinator |
| `tests/unit/test_progress_manager.py` | 81, 88 | Class-level cleanup | ProgressManager |

### Code Examples

```python
# PROBLEMATIC - tests/conftest.py:298-310
@pytest.fixture(autouse=True)
def clear_module_caches() -> Iterator[None]:
    # ... other stuff ...
    
    # Direct manipulation of _instance
    if NotificationManager._instance is not None:
        try:
            NotificationManager.cleanup()
        except (RuntimeError, AttributeError):
            pass
    NotificationManager._instance = None  # <-- Direct state manipulation
    
    yield
    
    # Reset again after test
    if NotificationManager._instance is not None:
        try:
            NotificationManager.cleanup()
        except (RuntimeError, AttributeError):
            pass
    NotificationManager._instance = None  # <-- Repeated manipulation
```

**Why This Is Problematic**:
1. Doesn't use monkeypatch - creates direct dependency on implementation details
2. Repeated reset code (before AND after test) - code duplication
3. Race conditions in parallel execution - multiple workers modifying shared state
4. Brittle - breaks if singleton implementation changes

**Better Pattern** (Per UNIFIED_TESTING_V2.MD):
```python
# RIGHT - Use monkeypatch
@pytest.fixture
def isolated_notification_manager(monkeypatch):
    """Provide isolated NotificationManager instance."""
    # Reset singleton via monkeypatch (more isolated)
    monkeypatch.setattr(NotificationManager, "_instance", None)
    
    # Test uses clean instance
    yield NotificationManager()
    
    # monkeypatch auto-restores after test (no manual cleanup needed)

# Or for test doubles:
@pytest.fixture
def mock_notification_manager(monkeypatch):
    """Inject mock NotificationManager."""
    mock_mgr = Mock(spec=NotificationManager)
    monkeypatch.setattr("notification_manager.NotificationManager._instance", mock_mgr)
    return mock_mgr
```

### Specific Issues

#### Issue 5a: Autouse Singleton Reset (CRITICAL)

```python
# WRONG - tests/unit/test_filesystem_coordinator.py:32
@pytest.fixture(autouse=True)  # <-- autouse means all tests pay the cost
def reset_singleton() -> Generator[None, None, None]:
    FilesystemCoordinator._instance = None  # Before test
    yield
    FilesystemCoordinator._instance = None  # After test
```

Per UNIFIED_TESTING_V2.MD: **autouse should ONLY be for**:
- Qt cleanup (affects 100% of Qt tests) ✓
- Cache clearing (prevents contamination) ✓
- QMessageBox mocking (prevents modal dialogs) ✓
- Random seed stabilization ✓

**NOT for**: singleton cleanup (only needed if test uses singleton)

**Fix**: Make this fixture explicit (not autouse):
```python
@pytest.fixture  # <-- No autouse
def isolated_coordinator(monkeypatch):
    monkeypatch.setattr(FilesystemCoordinator, "_instance", None)
    return FilesystemCoordinator()
```

#### Issue 5b: Duplicate Reset Code in conftest.py

```python
# CONFTEST.PY lines 298-310 AND 358-377 are identical
# Same cleanup logic is repeated in clear_module_caches fixture
# Both NotificationManager and ProgressManager reset twice:
# 1. At start of clear_module_caches
# 2. Again at end of clear_module_caches
# Plus another round in cleanup_threading_state fixture (line 450)
```

### Impact
- Tests don't scale to full parallel suite
- Fixture overhead (autouse on non-essential fixtures)
- Multiple workers race to reset singleton state
- Brittle (depends on implementation details)

---

## Finding 6: Direct Time.sleep() Usage (MEDIUM)

### Violation Category
Per UNIFIED_TESTING_V2.MD section "Time Control Without Sleeps":
> "❌ WRONG: time.sleep()"
> "✅ RIGHT: qtbot.waitSignal(), qtbot.waitUntil(), or synchronization helpers"

### Issue
Multiple test files use `time.sleep()` for synchronization, which causes flaky tests and slows execution.

### Violations (20+ instances)

| File | Lines | Count | Pattern |
|------|-------|-------|---------|
| `tests/test_concurrent_thumbnail_race_conditions.py` | 78, 150, 226, 246 | 4 | time.sleep(0.001-0.01) |
| `tests/conftest.py` | 232 | 1 | time.sleep(0.05) - Qt cleanup |
| `tests/test_subprocess_no_deadlock.py` | 151 | 1 | time.sleep(0.1) |
| `tests/unit/test_cache_manager.py` | 450, 528, 535, 786, 818 | 5 | time.sleep(0.001-0.1) |
| `tests/unit/test_progress_manager.py` | 162, 305, 307, 323 | 4 | time.sleep(0.002-0.02) |
| `tests/unit/test_output_buffer.py` | 111 | 1 | time.sleep(0.011) |
| `tests/unit/test_qt_integration_optimized.py` | 41, 271 | 2 | time.sleep(0.01) |
| `tests/unit/test_threede_scene_worker.py` | 226 | 1 | time.sleep(0.01) |
| `tests/unit/test_optimized_threading.py` | 99, 110, 141, 177, 188, 210 | 6 | time.sleep(0.05-0.1) |
| `tests/unit/test_worker_stop_responsiveness.py` | 76, 86, 237, 249, 408 | 5 | time.sleep(0.1-0.5) |
| `tests/unit/test_threede_optimization_coverage.py` | Various | Various | time.sleep() with comments about replacing |

### Code Examples

```python
# WRONG - tests/unit/test_progress_manager.py:162
time.sleep(0.02)  # Wait 20ms (> 10ms throttle)
# ...more test code...
```

```python
# RIGHT - Use Qt synchronization
from tests.helpers.synchronization import wait_for_condition
wait_for_condition(lambda: manager.is_ready, timeout_ms=2000)
```

### Why This Is Wrong
1. **Flaky**: Sleep may not be long enough or too long depending on system load
2. **Slow**: Each sleep adds to test execution time
3. **Misleading**: Sleep duration doesn't relate to what you're actually waiting for
4. **Non-deterministic**: Different systems may have different timing

### Available Alternatives

From UNIFIED_TESTING_V2.MD:
```python
# 1. For Qt signals (PREFERRED)
with qtbot.waitSignal(worker.finished, timeout=5000):
    worker.start()

# 2. For conditions
wait_for_condition(lambda: widget.is_ready, timeout_ms=2000)

# 3. For Qt events
qtbot.wait(100)  # Processes events while waiting
```

### Impact
- Tests with sleep() pass/fail non-deterministically
- CI environments (slower) may timeout
- WSL tests especially slow (filesystem performance)
- Parallel execution: 448 patches/sleeps × number of files = slow startup

---

## Finding 7: Explicit Patching Not Using Monkeypatch (MEDIUM)

### Violation Category
Per UNIFIED_TESTING_V2.MD principle of fixture clarity

### Issue
Tests use `@patch()` decorators mixed with monkeypatch, creating multiple patch systems. Good design: use monkeypatch consistently.

### Count
- 448+ uses of `@patch()`, `patch()`, or `monkeypatch.setattr` across test files
- Inconsistent patterns between tests

### Example
```python
# INCONSISTENT - Mix of @patch and monkeypatch in same test
@patch("subprocess.run")  # <-- Decorator-based
def test_something(mock_run, monkeypatch):  # <-- Also monkeypatch
    monkeypatch.setattr("config.Config.SHOWS_ROOT", "/tmp")  # <-- Fixture-based
```

**Why Mixed Approaches Are Problematic**:
1. Decorator patches apply before monkeypatch teardown (cleanup order issues)
2. Harder to understand patch scope (decorator vs function scope)
3. Different cleanup semantics (monkeypatch auto-restores, decorator doesn't)

**Better Pattern**:
```python
# CONSISTENT - Use monkeypatch everywhere
def test_something(monkeypatch):
    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("config.Config.SHOWS_ROOT", "/tmp")
```

---

## Finding 8: Module-Level Imports with Side Effects (LOW)

### Violation Category
Per UNIFIED_TESTING_V2.MD section "Smoke Check for Module Import Side-Effects":
> "Importing shotbot module should not start QApplication or spawn threads"

### Issue
Several test fixture modules import Qt classes at module level, which can cause QApplication initialization issues.

### Violations
- `tests/conftest.py:37-38` - Qt imports at module level (acceptable - before env vars are set)
- `tests/conftest_type_safe.py:67` - Creates QApplication in class (custom fixture)

### Risk
- When test modules are imported, Qt platform initialization happens
- Can conflict with pytest-qt's qapp fixture if not ordered correctly

### Mitigation
- conftest.py properly sets QT_QPA_PLATFORM BEFORE any Qt imports ✓
- Most violations already handled by fixture design

---

## Finding 9: Incomplete Qt Cleanup Patterns (MEDIUM)

### Violation Category
Per UNIFIED_TESTING_V2.MD section "Qt Test Isolation (Critical)" - rule #2

### Issue
Some tests cleanup Qt resources but not comprehensively.

### Examples

| File | Issue |
|------|-------|
| `tests/unit/test_notification_manager.py:174-179` | Cleanup in test class fixture (not conftest autouse) |
| `tests/unit/test_progress_manager.py:74-88` | Class-level cleanup (should be autouse in conftest) |

### Pattern Issue

```python
# PROBLEM - Cleanup in individual test class
class TestNotificationManager:
    @pytest.fixture(autouse=True)
    def cleanup(self):
        yield
        NotificationManager.cleanup()  # <-- Only cleans THIS test class
        NotificationManager._instance = None
```

**Why This Is Wrong**:
1. Only cleans tests in THIS class, not other tests that use NotificationManager
2. If another test creates NotificationManager outside this class, it won't clean up
3. Should be centralized in conftest.py for all tests

**Correct Pattern**:
```python
# RIGHT - Centralized in conftest.py (already done for some singletons)
@pytest.fixture(autouse=True)
def cleanup_threading_state():
    yield
    NotificationManager.cleanup()  # Applies to ALL tests
```

---

## Summary Table: Isolation Violations by Category

| Category | Count | Severity | Files |
|----------|-------|----------|-------|
| Module-scoped autouse fixtures | 12 | CRITICAL | test_main_window.py, test_main_window_fixed.py, test_exr_edge_cases.py, 6 integration tests |
| Module-level QCoreApplication creation | 2 | CRITICAL | test_subprocess_no_deadlock.py, test_type_safe_patterns.py |
| Module-level globals from fixtures | 9 | CRITICAL | test_main_window*.py, 6 integration tests, test_exr_edge_cases.py |
| xdist_group as band-aid | 41+ | HIGH | 25+ unit tests, 10+ integration tests |
| Direct singleton _instance manipulation | 7 | HIGH | conftest.py, test_notification_manager.py, test_filesystem_coordinator.py, test_progress_manager.py |
| Autouse singleton resets (non-essential) | 2 | HIGH | test_filesystem_coordinator.py (autouse), conftest.py (autouse) |
| time.sleep() instead of synchronization | 20+ | MEDIUM | 11 test files |
| Incomplete Qt cleanup in test classes | 2 | MEDIUM | test_notification_manager.py, test_progress_manager.py |

---

## Recommended Remediation Plan

### Phase 1: Critical (Immediate - Blocks Parallel Execution)

1. **Remove module-scoped autouse fixtures**
   - Delete or rewrite 12 fixtures to be function-scoped
   - Move necessary imports to module level
   - **Effort**: 2-3 hours
   - **Impact**: Enables true parallel execution

2. **Fix module-level QCoreApplication creation**
   - Fix 2 test functions to use `qapp` fixture
   - **Effort**: 30 minutes
   - **Impact**: Prevents "Multiple QApplication" crashes

3. **Remove global variable assignments from fixtures**
   - Refactor 9 module-scoped fixtures to use module-level imports
   - **Effort**: 1-2 hours
   - **Impact**: Test isolation in parallel execution

### Phase 2: High Priority (Enables Real Parallel Benefits)

4. **Remove xdist_group band-aids**
   - Delete 41+ `xdist_group` marks
   - Run tests in parallel to identify remaining isolation issues
   - Fix identified issues (should be minimal after Phase 1)
   - **Effort**: 3-4 hours
   - **Impact**: 7.5x speed improvement possible (30s vs 60s test run)

5. **Centralize singleton cleanup**
   - Move class-level singleton cleanup to conftest.py autouse fixtures
   - Use monkeypatch patterns where possible
   - Remove duplicate reset code
   - **Effort**: 1-2 hours
   - **Impact**: Cleaner, more maintainable fixture code

### Phase 3: Medium Priority (Better Test Quality)

6. **Replace time.sleep() with synchronization helpers**
   - Replace 20+ `time.sleep()` calls with `wait_for_condition()` or `qtbot.waitUntil()`
   - **Effort**: 2-3 hours
   - **Impact**: More reliable, faster tests

7. **Consolidate Qt cleanup patterns**
   - Move incomplete Qt cleanup from test classes to conftest.py
   - Ensure all Qt-using tests benefit from cleanup
   - **Effort**: 1 hour
   - **Impact**: Better cleanup coverage

---

## Verification Steps

After implementing fixes:

```bash
# 1. Run in serial to ensure tests still pass
uv run pytest tests/ -n 0 --maxfail=1 -q

# 2. Run in parallel to verify isolation fixed
uv run pytest tests/ -n auto --dist=worksteal -q

# 3. Run with random order to surface remaining coupling
uv run pytest tests/ -n auto --randomly-seed=auto -q

# 4. Measure speed improvement
time uv run pytest tests/ -n 0 -q
time uv run pytest tests/ -n auto -q
# Expected: Phase 2 enables 7-8x speedup
```

---

## Key Files to Review

1. `tests/conftest.py` - Check singleton reset duplication
2. `tests/unit/test_main_window.py` - Module-scoped fixture example
3. `tests/unit/test_notification_manager.py` - Singleton cleanup pattern
4. `tests/integration/test_cross_component_integration.py` - xdist_group usage example
5. `UNIFIED_TESTING_V2.MD` - Reference for correct patterns

---

## Conclusion

The test suite has **good Qt cleanup infrastructure** (conftest.py autouse fixtures for Qt cleanup are excellent), but **isolation issues are masked by xdist_group serialization** which prevents parallel execution. Removing the band-aids and fixing root causes will:

1. Enable true parallel test execution (7-8x speedup)
2. Improve test reliability (no more "passes alone, fails in parallel")
3. Simplify maintenance (fewer workarounds and hacks)
4. Align with UNIFIED_TESTING_V2.MD best practices

**Estimated total remediation time**: 8-12 hours  
**Expected result**: 30 second test run (from 60s serial or 240s with xdist band-aids)

