# Test Isolation Violations - Detailed File Locations

## CRITICAL: Module-Scoped Autouse Fixtures (12 files)

### Unit Tests (3 files)

1. **tests/unit/test_main_window.py:36**
   - Fixture: `setup_qt_imports()`
   - Issue: `@pytest.fixture(scope="module", autouse=True)`
   - Global vars: `MainWindow, CacheManager, Shot, ThreeDEScene`
   - Fix: Remove scope/autouse; import at module level

2. **tests/unit/test_main_window_fixed.py:40**
   - Fixture: `setup_qt_imports()`
   - Issue: `@pytest.fixture(scope="module", autouse=True)`
   - Global vars: `MainWindow, CacheManager, Shot`
   - Fix: Remove scope/autouse; import at module level

3. **tests/unit/test_exr_edge_cases.py:44**
   - Issue: `@pytest.fixture(scope="module", autouse=True)`
   - Global vars: `CacheManager, QCoreApplication, process_qt_events`
   - Fix: Remove scope/autouse; import at module level

### Integration Tests (6 files)

4. **tests/integration/test_cross_component_integration.py:36**
   - Fixture: `setup_qt_imports()`
   - Issue: `@pytest.fixture(scope="module", autouse=True)`
   - Global vars: `MainWindow`

5. **tests/integration/test_main_window_complete.py:59**
   - Issue: `@pytest.fixture(scope="module", autouse=True)`
   - Global vars: `MainWindow, Shot`

6. **tests/integration/test_user_workflows.py:69**
   - Issue: `@pytest.fixture(scope="module", autouse=True)`
   - Global vars: `MainWindow`

7. **tests/integration/test_feature_flag_switching.py:38**
   - Issue: `@pytest.fixture(scope="module", autouse=True)`
   - Global vars: `MainWindow`

8. **tests/integration/test_launcher_panel_integration.py:50**
   - Issue: `@pytest.fixture(scope="module", autouse=True)`
   - Global vars: `MainWindow`

9. **tests/integration/test_main_window_coordination.py:44**
   - Issue: `@pytest.fixture(scope="module", autouse=True)`
   - Global vars: `MainWindow`

---

## CRITICAL: Module-Level QCoreApplication Creation (2 files)

1. **tests/test_subprocess_no_deadlock.py:121**
   - Location: Inside `test_subprocess_handles_large_output()` (test function, not fixture)
   - Code: `app = QCoreApplication.instance() or QCoreApplication([])`
   - Fix: Add `qapp` parameter to test function

2. **tests/test_type_safe_patterns.py:482**
   - Location: Inside context manager / test function
   - Code: `app = QApplication([])`
   - Fix: Use `qapp` fixture instead

---

## CRITICAL: Module-Level Global Variables from Fixtures (9 files)

### Already covered above under module-scoped autouse fixtures:
- test_main_window.py:39 - `global MainWindow, CacheManager, Shot, ThreeDEScene`
- test_main_window_fixed.py:43 - `global MainWindow, CacheManager, Shot`
- test_exr_edge_cases.py:47 - `global CacheManager, QCoreApplication, process_qt_events`
- test_cross_component_integration.py:39 - `global MainWindow`
- test_main_window_complete.py:62 - `global MainWindow, Shot`
- test_user_workflows.py:72 - `global MainWindow`
- test_feature_flag_switching.py:41 - `global MainWindow`
- test_launcher_panel_integration.py:53 - `global MainWindow`
- test_main_window_coordination.py:47 - `global MainWindow`

---

## HIGH: xdist_group Band-Aids (41+ files)

### Unit Tests with `xdist_group("qt_state")` (25+)
- tests/unit/test_launcher_controller.py:31
- tests/unit/test_example_best_practices.py:33
- tests/unit/test_base_shot_model.py:30
- tests/unit/test_main_window.py:31
- tests/unit/test_main_window_widgets.py:50
- tests/unit/test_log_viewer.py:29
- tests/unit/test_threading_fixes.py:27
- tests/unit/test_persistent_terminal_manager.py:26
- tests/unit/test_error_recovery_optimized.py:20
- tests/unit/test_base_item_model.py:34
- tests/unit/test_notification_manager.py:38 - `xdist_group("notification_manager_singleton")`
- tests/unit/test_launcher_panel.py:36
- tests/unit/test_cache_manager.py:38
- tests/unit/test_design_system.py:42
- tests/unit/test_shot_grid_widget.py:54
- tests/unit/test_progress_manager.py:39
- tests/unit/test_settings_manager.py:28
- tests/unit/test_concurrent_optimizations.py:19
- tests/unit/test_template.py:22
- tests/unit/test_previous_shots_worker.py:54
- tests/unit/test_shot_info_panel_comprehensive.py:39
- tests/unit/test_main_window_fixed.py:35 - `xdist_group("main_window_isolated")`
- tests/unit/test_previous_shots_grid.py:50
- tests/unit/test_cleanup_manager.py:24
- tests/unit/test_threede_shot_grid.py:23

### Integration Tests with `xdist_group("qt_state")` (10+)
- tests/integration/test_terminal_integration.py:22
- tests/integration/test_user_workflows.py:81
- tests/integration/test_main_window_complete.py:103
- tests/integration/test_main_window_coordination.py:359, 675, 732
- tests/integration/test_refactoring_safety.py:258, 351
- tests/integration/test_launcher_panel_integration.py:62
- tests/integration/test_cross_component_integration.py:45

---

## HIGH: Singleton State Not Using monkeypatch (7 files)

### conftest.py (Multiple Issues)

**Issue 5a: NotificationManager - Lines 298-310**
```
BEFORE TEST: NotificationManager._instance = None
AFTER TEST: NotificationManager._instance = None  (duplicate)
```

**Issue 5b: ProgressManager - Lines 314-327**
```
BEFORE TEST: ProgressManager._instance = None
AFTER TEST: ProgressManager._instance = None  (duplicate)
```

**Issue 5c: Singleton Reset Duplication - Lines 358-377**
```
BEFORE TEST: Both NotificationManager and ProgressManager reset
AFTER TEST: Both reset again (DUPLICATE of 298-327)
```

**Issue 5d: ProcessPoolManager - Lines 479-491**
```
Directly manipulates ProcessPoolManager._instance
No monkeypatch usage
```

**Issue 5e: cleanup_threading_state - Line 450**
```
Third location calling NotificationManager.cleanup()
```

### test_notification_manager.py (Class-level cleanup)

**Line 174-179:**
```python
@pytest.fixture(autouse=True)
def cleanup(self):
    yield
    NotificationManager.cleanup()
    NotificationManager._instance = None
```
- Only applies to TestNotificationManager class
- Should be in conftest.py autouse for all tests

### test_filesystem_coordinator.py (Autouse singleton reset)

**Line 32-39:**
```python
@pytest.fixture(autouse=True)  # ← Unnecessary autouse
def reset_singleton():
    FilesystemCoordinator._instance = None  # Before test
    yield
    FilesystemCoordinator._instance = None  # After test
```
- Should be explicit fixture (not autouse)
- Should use monkeypatch

### test_progress_manager.py (Class-level cleanup)

**Line 74-88:**
```python
@pytest.fixture(autouse=True)
def cleanup(self):
    yield
    ProgressManager.clear_all_operations()
    ProgressManager._instance = None
```
- Only applies to test class
- Should be in conftest.py

---

## MEDIUM: time.sleep() Instead of Synchronization (20+ instances)

### tests/test_concurrent_thumbnail_race_conditions.py
- Line 78: `time.sleep(0.001)`
- Line 150: `time.sleep(0.001)`
- Line 226: `time.sleep(0.01)`
- Line 246: `time.sleep(0.001)`

### tests/conftest.py
- Line 232: `time.sleep(0.05)` - Qt cleanup (acceptable but can be optimized)

### tests/test_subprocess_no_deadlock.py
- Line 151: `time.sleep(0.1)`

### tests/unit/test_cache_manager.py
- Line 450: `time.sleep(0.01)`
- Line 528: `time.sleep(0.001)`
- Line 535: `time.sleep(0.002)`
- Line 786: `time.sleep(0.001)`
- Line 818: `time.sleep(0.1)`

### tests/unit/test_progress_manager.py
- Line 162: `time.sleep(0.02)`
- Line 305: `time.sleep(0.01)`
- Line 307: `time.sleep(0.01)`
- Line 323: `time.sleep(0.002)`

### tests/unit/test_output_buffer.py
- Line 111: `time.sleep(0.011)`

### tests/unit/test_qt_integration_optimized.py
- Line 41: `time.sleep(0.01)`
- Line 271: `time.sleep(0.01)`

### tests/unit/test_threede_scene_worker.py
- Line 226: `time.sleep(0.01)`

### tests/unit/test_optimized_threading.py
- Line 99: `time.sleep(0.1)`
- Line 110: `time.sleep(0.01)`
- Line 141: `time.sleep(0.1)`
- Line 177: `time.sleep(0.05)`
- Line 188: `time.sleep(0.1)`
- Line 210: `time.sleep(0.1)`

### tests/unit/test_worker_stop_responsiveness.py
- Line 76: `time.sleep(0.1)`
- Line 86: `time.sleep(0.3)`
- Line 237: `time.sleep(0.1)`
- Line 249: `time.sleep(0.5)`
- Line 408: `time.sleep(0.1)`

---

## MEDIUM: Incomplete Qt Cleanup in Test Classes (2 files)

1. **tests/unit/test_notification_manager.py:174-179**
   - Class-level autouse fixture in TestNotificationManager
   - Only cleans THIS test class
   - Should be centralized in conftest.py

2. **tests/unit/test_progress_manager.py:74-88**
   - Class-level autouse fixture
   - Only cleans THIS test class
   - Should be centralized in conftest.py

---

## Additional Notes

### Duplicate Code in conftest.py
- NotificationManager reset: Lines 298-310 AND 358-377 (identical code)
- ProgressManager reset: Lines 314-327 AND 364-377 (identical code)
- Solution: Consolidate into single fixture

### Correct Pattern (Per UNIFIED_TESTING_V2.MD)
```python
# RIGHT - Centralized, using monkeypatch where possible
@pytest.fixture(autouse=True)
def isolate_singletons(monkeypatch):
    """Isolate all singletons between tests."""
    # Use monkeypatch for isolation
    monkeypatch.setattr(NotificationManager, "_instance", None)
    monkeypatch.setattr(ProgressManager, "_instance", None)
    
    yield
    
    # monkeypatch auto-restores, but also do cleanup
    try:
        NotificationManager.cleanup()
        ProgressManager.clear_all_operations()
    except (RuntimeError, AttributeError):
        pass  # Already deleted
```

---

## Fix Priority Order

1. **TODAY (30 min)**
   - [ ] tests/test_subprocess_no_deadlock.py:121
   - [ ] tests/test_type_safe_patterns.py:482

2. **THIS WEEK (6-8 hours)**
   - [ ] Remove 12 module-scoped autouse fixtures
   - [ ] Remove 41+ xdist_group marks
   - [ ] Consolidate singleton cleanup in conftest.py

3. **NEXT WEEK (4-6 hours)**
   - [ ] Replace 20+ time.sleep() calls
   - [ ] Move class-level Qt cleanup to conftest

---

## Verification Commands

```bash
# Find all xdist_group marks
grep -r "xdist_group" tests/ --include="*.py" | wc -l

# Find all module-scoped fixtures
grep -r 'scope="module"' tests/ --include="*.py"

# Find all global statements
grep -r "^global " tests/ --include="*.py" | grep -v "noqa"

# Find all time.sleep calls
grep -r "time\.sleep" tests/ --include="*.py" | grep -v "# " | grep -v "@patch"

# Count QApplication creations in tests
grep -r "QApplication\|QCoreApplication" tests/ --include="*.py" | grep -v "QApplication.instance" | grep -v "def " | grep -v "class " | wc -l
```

