# Detailed Violations Index

## time.sleep() Violations (25 total)

### Acceptable Cases (Documented/Mock Context) - 18 cases

| File | Line | Code | Reason | Status |
|---|---|---|---|---|
| unit/test_process_pool_manager.py | 82 | `time.sleep(self.execution_delay)` | Test double simulating execution delay | ✅ OK |
| unit/test_qt_integration_optimized.py | 41 | `time.sleep(0.01)` | Background worker simulation (10ms) | ✅ OK |
| unit/test_qt_integration_optimized.py | 289 | `time.sleep(0.01)` | Command execution simulation | ✅ OK |
| unit/test_threede_recovery.py | 44 | `time.sleep(0.01)` | File timestamp manipulation | ✅ OK |
| unit/test_threede_scene_worker.py | 285 | `time.sleep(0.01)` | Timing-sensitive performance test | ✅ OK |
| unit/test_thread_safety_regression.py | 176 | `time.sleep(0.1)` | Stress test (documented) | ✅ OK |
| unit/test_thread_safety_regression.py | 373 | `time.sleep(0.001)` | Stress test (documented) | ✅ OK |
| unit/test_optimized_threading.py | 113 | `time.sleep(0.1)` | Mock function for slow command | ✅ OK |
| unit/test_optimized_threading.py | 191 | `time.sleep(0.05)` | Mock iteration simulation | ✅ OK |
| unit/test_logging_mixin.py | 48 | `time.sleep(0.1)` | Simulating work (could use mock) | ⚠️ REVIEW |
| unit/test_output_buffer.py | 111 | `time.sleep(0.011)` | Batch interval testing | ⚠️ REVIEW |
| unit/test_performance_improvement.py | 103 | `time.sleep(0.1)` | Async loader processing | ⚠️ REVIEW |

### Questionable Cases (Test Logic) - 7 cases

| File | Line | Code | Issue | Fix |
|---|---|---|---|---|
| unit/test_thread_safety_validation.py | 115 | `time.sleep(0.001)` | Worker stress test | Use `qtbot.waitUntil()` |
| unit/test_thread_safety_validation.py | 212 | `time.sleep(0.1)` | Task completion wait | Use `qtbot.waitUntil()` |
| unit/test_thread_safety_validation.py | 228 | `time.sleep(0.15)` | Task cancellation wait | Use condition variable |
| unit/test_threading_fixes.py | 60 | `time.sleep(0.001)` | Step simulation | Document or use mock.patch |
| unit/test_previous_shots_worker.py | 279 | `time.sleep(0.1)` | Worker stop wait | Use `qtbot.waitUntil(worker.should_stop)` |
| unit/test_concurrent_optimizations.py | 136 | `time.sleep(0.01)` | Cleanup delay | Use condition check |

### Comments/Documentation (Not code) - 0 violations

---

## qtbot.wait() Violations (308 total)

### By Delay Duration

```
1ms:    12 cases (probably test edge cases, verify necessity)
10ms:   18 cases (minimal processing)
50ms:   47 cases (signal processing)
100ms:  87 cases (most common - async operations)
150ms:   3 cases (heavy operations)
Other: 141 cases (various/unclear delays)
```

### Top Files by Violation Count

#### 1. integration/test_main_window_complete.py (~10 violations)

Pattern: UI operation synchronization
```python
window.resize(new_width, new_height)
qtbot.wait(100)  # ❌ Should use qtbot.waitExposed()

action.trigger()
qtbot.wait(50)   # ❌ Should use qtbot.waitSignal()
```

Lines: 315, 463, 473, 497, 561, 593, 610, 621, 643, 647

#### 2. unit/test_threede_shot_grid.py (~6 violations)

Pattern: Grid view updates
```python
grid.refresh()
qtbot.wait(100)  # ❌ Should use signal wait
```

Lines: 159, 191, 220, 264, 296, and 2 more

#### 3. unit/test_shot_grid_widget.py (~4 violations)

Pattern: List view operations
```python
view.setFocus()
qtbot.wait(50)   # ❌ Should use condition
```

Lines: 143, 186, and 2 more

#### 4. integration/test_launcher_panel_integration.py (~4 violations)

Pattern: Panel state changes
```python
launcher.show()
qtbot.wait(50)   # ❌ Should use waitExposed()
```

#### 5-10. Other integration tests (~270 violations distributed across)

Files with multiple violations:
- integration/test_user_workflows.py
- integration/test_launcher_workflow_integration.py
- integration/test_threede_worker_workflow.py
- unit/test_threading_fixes.py (5+ violations)
- reliability_fixtures.py
- test_doubles_extended.py

---

## processEvents() Violations (35 total)

### Acceptable Usage (Cleanup Context) - ~25 cases

```python
# ✅ OK - Cleanup context
finally:
    qapp.processEvents()  # Process deletion queue
    qapp.processEvents()  # Process cascading cleanups
```

Files and lines:
- conftest.py: 266, 296, 304, 312, 410, 716, 725 (all cleanup)
- test_thread_safety_regression.py: 244, 270, 336 (all cleanup)
- test_main_window_fixed.py: 116, 158 (cleanup)
- helpers/qt_thread_cleanup.py: 103, 111 (cleanup)
- test_actual_parsing.py: 172 (documented cleanup)

### Questionable Usage (Mid-Test) - ~10 cases

| File | Line | Code | Issue |
|---|---|---|---|
| test_main_window.py | 125 | `app.processEvents()` | Not in cleanup - use waitUntil |
| test_main_window.py | 177 | `app.processEvents()` | Not in cleanup - use waitUntil |
| test_optimized_threading.py | 155 | `qapp.processEvents()` | Mixed context - clarify |
| test_optimized_threading.py | 351 | `qapp.processEvents()` | Mixed context - clarify |
| test_optimized_threading.py | 387 | `qapp.processEvents()` | Mixed context - clarify |
| test_cross_component_integration.py | 528 | `QApplication.processEvents()` | Mid-test - wrap in condition |
| test_cross_component_integration.py | 536 | `QApplication.processEvents()` | Mid-test - wrap in condition |
| test_cross_component_integration.py | 117, 169, 232, 599, 765 | `app.processEvents()` | Various - audit context |

---

## By Test Category

### Unit Tests with Violations

**High Impact:**
- test_threede_shot_grid.py - 6+ qtbot.wait()
- test_shot_grid_widget.py - 4+ qtbot.wait()
- test_threading_fixes.py - 5+ qtbot.wait(), 1 time.sleep()

**Medium Impact:**
- test_thread_safety_validation.py - 3 time.sleep()
- test_thread_safety_regression.py - 2 time.sleep(), some processEvents()
- test_concurrent_optimizations.py - 1 time.sleep()

**Low Impact (Acceptable):**
- test_process_pool_manager.py - time.sleep() in mock
- test_logging_mixin.py - 1 time.sleep() (document or fix)

### Integration Tests with Violations

**High Impact:**
- test_main_window_complete.py - 10+ qtbot.wait()
- test_user_workflows.py - many qtbot.wait()
- test_launcher_panel_integration.py - 4+ qtbot.wait()
- test_cross_component_integration.py - 8+ qtbot.wait(), 5 processEvents()

**Medium Impact:**
- test_launcher_workflow_integration.py - multiple qtbot.wait()
- test_threede_worker_workflow.py - multiple qtbot.wait()

---

## Recommended Fix Priority

### Phase 1 (This Week)
- [ ] Document all time.sleep() usage with comments
- [ ] Add context comments to processEvents() calls
- [ ] Identify which signals/conditions to use for qtbot.wait() replacements

### Phase 2 (2 Weeks)
- [ ] Replace qtbot.wait() in test_main_window_complete.py with waitExposed/waitUntil
- [ ] Replace qtbot.wait() in test_threede_shot_grid.py
- [ ] Fix questionable time.sleep() in test_thread_safety_validation.py

### Phase 3 (1 Month)
- [ ] Systematic replacement of remaining qtbot.wait() calls
- [ ] Add helper functions for common patterns
- [ ] Add pytest plugin to catch new violations

---

## Testing Verification

After fixes, verify:

```bash
# Serial execution (baseline)
pytest tests/ -n 0

# Parallel execution (stress test)
pytest tests/ -n 2
pytest tests/ -n auto

# High CPU load test
pytest tests/ -n 4 --stress  # If marked
```

All should pass consistently without flaky failures.

