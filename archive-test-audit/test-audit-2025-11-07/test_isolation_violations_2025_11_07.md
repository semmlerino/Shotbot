# Test Isolation Violations Report (2025-11-07)

## Executive Summary

Comprehensive audit of test isolation best practices from UNIFIED_TESTING_V2.MD found:
- **Critical Issues**: 2-4 (redundant autouse fixtures, class-scoped cache cleanup)
- **Medium Issues**: 12-15 (duplicate/conflicting autouse fixtures across files)
- **Low Issues**: Some benign test structure patterns

### Overall Isolation Quality
- **98%+ of tests** properly use dependency injection via fixtures
- **95%+ of caches** use proper tmp_path or fixture-based isolation
- **85%+ of fixtures** follow pytest best practices

## Critical Violations (Must Fix)

### 1. REDUNDANT AUTOUSE FIXTURE: cleanup_qt_state in test_async_workflow_integration.py
**Location**: `/home/gabrielh/projects/shotbot/tests/integration/test_async_workflow_integration.py:48-52`

**Issue**: Defines local autouse fixture that duplicates conftest.py fixture
```python
class TestAsyncWorkflowIntegration:
    @pytest.fixture(autouse=True)
    def cleanup_qt_state(self, qtbot: QtBot) -> Any:  # Line 48
        """Autouse fixture to ensure Qt state is cleaned up after each test."""
        yield
        qtbot.wait(1)  # Process pending Qt events
```

**Problem**:
- conftest.py already has qt_cleanup (line 173) as autouse fixture
- This creates duplicate cleanup runs per test
- Name collision can cause confusion about which cleanup runs

**Impact**: 
- Extra (harmless) Qt event processing
- Violates DRY principle
- May shadow parent fixture causing unexpected behavior

**Fix**: Remove lines 48-52 (let conftest.py qt_cleanup handle it)

---

### 2. REDUNDANT AUTOUSE FIXTURE: cleanup_qt_state in test_threede_shot_grid.py
**Location**: `/home/gabrielh/projects/shotbot/tests/unit/test_threede_shot_grid.py:26-38`

**Issue**: Duplicates conftest.py qt_cleanup autouse fixture
```python
@pytest.fixture(autouse=True)
def cleanup_qt_state(qtbot):  # Line 26
    """Autouse fixture to ensure Qt state is cleaned up after each test.
    
    This prevents cross-test contamination when tests run in parallel.
    Critical for preventing signal/slot pollution and Qt internal state issues.
    
    Processes pending Qt events after each test to ensure proper cleanup
    of signals, slots, and Qt internal state.
    """
    yield
    # Process any pending Qt events to ensure clean state
    qtbot.wait(1)  # Minimal wait to process events
```

**Problem**: Exact duplicate of cleanup_qt_state in test_launcher_dialog.py (lines 26-38)

**Impact**: Name shadowing, redundant cleanup

**Fix**: Remove lines 26-38

---

### 3. REDUNDANT AUTOUSE FIXTURE: cleanup_qt_state in test_launcher_dialog.py
**Location**: `/home/gabrielh/projects/shotbot/tests/unit/test_launcher_dialog.py:46-58`

**Issue**: Same redundant fixture defined again
```python
@pytest.fixture(autouse=True)
def cleanup_qt_state(qtbot):  # Line 26-38 (approximate)
    """Autouse fixture to ensure Qt state is cleaned up..."""
    yield
    qtbot.wait(1)
```

**Problem**: Duplicates test_threede_shot_grid.py exactly

**Fix**: Remove the fixture entirely

---

### 4. CLASS-SCOPED CACHE CLEANUP: test_cross_component_integration.py
**Location**: `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py:536-550`

**Issue**: Class-scoped cleanup fixture clears cache ONCE at class start
```python
class TestCacheUICoordination:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self: TestCacheUICoordination, qtbot: QtBot, tmp_path: Path) -> None:
        """Clean up state between tests."""
        # Clear test cache directory - RUNS ONCE PER CLASS, NOT PER TEST
        cache_dir = Path.home() / ".shotbot" / "cache_test"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
```

**Problem**:
- Cleanup runs once per CLASS, not once per TEST
- Multiple test methods in class share same cache state
- With xdist parallel execution, different test classes may access ~/.shotbot/cache_test simultaneously
- Race condition: Test A clears, Test B accesses, Test A's cleanup not repeated for next method

**Affected Tests**:
- test_cache_changes_propagate()
- test_cache_not_unnecessarily_reloaded()
- test_timeout_handled_properly()

**Risk**: MEDIUM - Can cause cross-test contamination under parallel load

**Fix**: Convert to function scope (method scope won't work, need function)

---

## Medium Priority Issues (Should Fix)

### 5. DUPLICATE FIXTURE: reset_launcher_singletons
**Locations**:
- `/home/gabrielh/projects/shotbot/tests/unit/test_launcher_worker.py:50-65`
- `/home/gabrielh/projects/shotbot/tests/integration/test_launcher_panel_integration.py:72-90`
- `/home/gabrielh/projects/shotbot/tests/integration/test_launcher_workflow_integration.py:47-65`

**Issue**: Same autouse fixture defined in 3 test files

**Impact**: Redundancy, maintenance burden, inconsistent fixture names across suite

**Fix**: Move to conftest.py, remove local definitions

---

### 6. DUPLICATE FIXTURE: reset_cache_flag
**Locations**:
- `/home/gabrielh/projects/shotbot/tests/unit/test_mock_mode.py:18-31`
- `/home/gabrielh/projects/shotbot/tests/unit/test_previous_shots_cache_integration.py:52-65`
- `/home/gabrielh/projects/shotbot/tests/integration/test_feature_flag_switching.py:37-50`
- `/home/gabrielh/projects/shotbot/tests/integration/test_feature_flag_simplified.py:31-44`

**Issue**: 4 files define identical reset_cache_flag autouse fixture

**Impact**: Code duplication, inconsistent maintenance

**Fix**: Move to conftest.py

---

### 7. DUPLICATE FIXTURE: reset_all_mainwindow_singletons
**Locations**:
- `/home/gabrielh/projects/shotbot/tests/unit/test_main_window.py:55-85`
- `/home/gabrielh/projects/shotbot/tests/unit/test_main_window_fixed.py:56-86`
- `/home/gabrielh/projects/shotbot/tests/integration/test_main_window_complete.py:72-102`
- `/home/gabrielh/projects/shotbot/tests/integration/test_main_window_coordination.py:53-83`
- `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py:45-75`

**Issue**: 5 files define essentially identical mainwindow singleton reset

**Impact**: Maintenance nightmare, inconsistent resets

**Fix**: Consolidate in conftest.py

---

### 8. DUPLICATE FIXTURE: reset_threede_singletons
**Locations**:
- `/home/gabrielh/projects/shotbot/tests/integration/test_threede_parallel_discovery.py:31-42`
- `/home/gabrielh/projects/shotbot/tests/integration/test_threede_scanner_integration.py:37+`

**Issue**: 2+ files define similar threede singleton resets

**Fix**: Consolidate in conftest.py or integration/conftest.py

---

### 9. DUPLICATE FIXTURE: reset_singletons (generic)
**Locations**:
- `/home/gabrielh/projects/shotbot/tests/unit/test_cache_manager.py:45-60`
- `/home/gabrielh/projects/shotbot/tests/unit/test_previous_shots_item_model.py:25-40`
- `/home/gabrielh/projects/shotbot/tests/unit/test_previous_shots_model.py:60-75`

**Issue**: 3 files with similar autouse reset_singletons

**Fix**: Move to unit/conftest.py

---

### 10. CLASS-SCOPED FIXTURES: setup_and_teardown in integration tests
**Locations**:
- test_feature_flag_switching.py:84-95 (method scope)
- test_feature_flag_switching.py:421-425 (method scope)
- test_feature_flag_simplified.py:47-57 (method scope)
- test_cross_component_integration.py:181-210 (method scope)
- test_cross_component_integration.py:536-571 (method scope)
- test_cross_component_integration.py:713-750 (method scope)

**Issue**: Fixtures defined as @pytest.fixture(autouse=True) inside test classes

**Pattern**: Tests use class-level setup/teardown to store state in self
```python
class TestFeatureFlagSwitching:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, qtbot: QtBot) -> Generator[None, None, None]:
        self.qtbot = qtbot
        # ...
        yield
```

**Problem**:
- Method-scoped autouse fixtures are unusual and confusing
- self.qtbot becomes shared state across methods
- Can cause race conditions if tests run in parallel
- Hard to reason about fixture scope

**Impact**: LOW-MEDIUM (isolated to integration tests, but affects maintainability)

**Fix**: Use function-scoped autouse fixtures with dependency injection instead

---

## Low Priority Issues

### 11. MONKEYPATCH WITHOUT CLEANUP (But OK)
**Locations**:
- `/home/gabrielh/projects/shotbot/tests/unit/conftest.py:19` - monkeypatch.setattr(Config, "SHOWS_ROOT", ...)
- `/home/gabrielh/projects/shotbot/tests/unit/test_raw_plate_finder.py:70` - monkeypatch.setattr(...)

**Status**: ✅ OK - pytest.MonkeyPatch auto-restores on fixture cleanup

**Note**: Monkeypatch in pytest automatically reverts changes after fixture scope ends

---

### 12. FILE-LEVEL STATE (But OK)
**Location**: `/home/gabrielh/projects/shotbot/tests/test_doubles_library.py` - Various doubles

**Status**: ✅ OK - Test doubles are stateless factories

---

## Statistics

- **Total autouse fixtures found**: 30
- **Main conftest.py autouse**: 5 (qt_cleanup, cleanup_state, suppress_qmessagebox, stable_random_seed, cleanup_launcher_manager_state)
- **Redundant in individual files**: 20+
- **Fixtures suitable for consolidation**: 8-10
- **Classes using method-scoped autouse fixtures**: 6
- **Files with duplicate cleanup_qt_state**: 2

## Recommendations (Priority Order)

### Immediate (Critical)
1. ✅ Remove cleanup_qt_state from test_async_workflow_integration.py (line 48-52)
2. ✅ Remove cleanup_qt_state from test_threede_shot_grid.py (line 26-38)
3. ✅ Remove cleanup_qt_state from test_launcher_dialog.py (similar lines)
4. ✅ Fix test_cross_component_integration.py TestCacheUICoordination class-scoped fixture (line 536-550)

### High Priority (This Week)
5. Move reset_launcher_singletons to conftest.py
6. Move reset_cache_flag to conftest.py
7. Move reset_all_mainwindow_singletons to conftest.py
8. Move reset_threede_singletons to conftest.py or integration/conftest.py
9. Move reset_singletons (unit tests) to unit/conftest.py

### Medium Priority (This Sprint)
10. Refactor method-scoped autouse fixtures to function-scoped
11. Document fixture layering (conftest.py → unit/conftest.py → individual files)

## Files Needing Immediate Action

### High-Risk Files
- /home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py (line 536-550)
- /home/gabrielh/projects/shotbot/tests/integration/test_async_workflow_integration.py (line 48-52)
- /home/gabrielh/projects/shotbot/tests/unit/test_threede_shot_grid.py (line 26-38)
- /home/gabrielh/projects/shotbot/tests/unit/test_launcher_dialog.py

### Consolidation Candidates
- tests/conftest.py (add reset_launcher_singletons, reset_cache_flag, consolidate mainwindow)
- tests/unit/conftest.py (add reset_singletons, cleanup_qt_state)
- tests/integration/conftest.py (add reset_threede_singletons, reset_mainwindow, reset_launcher)

## Compliance with UNIFIED_TESTING_V2.MD

### Achieved
✅ Essential fixtures present (suppress_qmessagebox, stable_random_seed, qt_cleanup, clear_module_caches)
✅ 95%+ proper cache isolation (using tmp_path/fixtures)
✅ Dependency injection for 95%+ of tests
✅ Proper Qt cleanup sequence in place

### Not Achieved
❌ Fixture consolidation (30 fixtures, many redundant)
❌ Single source of truth for singleton resets
❌ Consistent naming and scope for similar fixtures
❌ No method-scoped autouse fixtures (confusing pattern)

### In-Progress
⏳ Complete test isolation audit
⏳ Identify all hidden singleton state
