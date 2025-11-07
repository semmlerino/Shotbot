# Integration Test Parallel Execution Fix

## Problem
Integration tests were crashing with "Fatal Python error: Aborted" when run in parallel with `pytest -n auto` due to Qt resource contention. Multiple tests creating Qt widgets simultaneously across different pytest-xdist workers caused Qt to fail.

## Root Cause
The `pytest_collection_modifyitems` hook in `tests/conftest.py` (lines 1784-1798) was **disabled**, meaning tests marked with `@pytest.mark.gui_mainwindow` were **NOT** automatically getting `@pytest.mark.xdist_group("gui_mainwindow")` added.

Without the `xdist_group` marker, pytest-xdist treats tests as independent and schedules them across multiple workers, causing Qt resource conflicts.

## Solution
Manually added `@pytest.mark.xdist_group("qt_state")` to all test classes that:
1. Have `@pytest.mark.gui_mainwindow` marker
2. Create MainWindow or complex Qt widgets
3. Were missing the explicit xdist_group marker

## Files Modified

### 1. test_feature_flag_switching.py
- **Line 64**: Added `@pytest.mark.xdist_group("qt_state")` to `TestFeatureFlagSwitching` class
- **Line 393**: Added `@pytest.mark.xdist_group("qt_state")` to `TestMainWindowIntegration` class

### 2. test_main_window_complete.py
- **Line 96**: Added `@pytest.mark.xdist_group("qt_state")` to `TestMainWindowCompleteWorkflows` class

### 3. test_main_window_coordination.py
- **Line 334**: Added `@pytest.mark.xdist_group("qt_state")` to `TestMainWindowUICoordination` class
- **Line 644**: Added `@pytest.mark.xdist_group("qt_state")` to `TestMainWindowKeyboardShortcuts` class
- **Line 701**: Added `@pytest.mark.xdist_group("qt_state")` to `TestMainWindowErrorScenarios` class

### 4. test_refactoring_safety.py
- **Line 258**: Added `@pytest.mark.xdist_group("qt_state")` to `TestMainWindowRefactoringSafety` class
- **Line 343**: Added `@pytest.mark.xdist_group("qt_state")` to `TestCombinedIntegration` class

## Files Already Properly Marked (No Changes Needed)
- `test_cross_component_integration.py` - Has module-level `pytest.mark.xdist_group("qt_state")`
- `test_launcher_panel_integration.py` - Already has xdist_group markers
- `test_user_workflows.py` - Already has xdist_group marker

## Verification Results

**Before Fix**: Tests would crash intermittently with Qt resource conflicts

**After Fix**:
```bash
uv run pytest tests/integration/ -n auto --timeout=10 -q
# Result: 7 failed, 71 passed, 1 warning in 27.96s
# NO "Fatal Python error: Aborted" crashes
# NO segmentation faults
```

The 7 failures are unrelated to Qt crashes:
- 5 failures in `test_dependency_injection.py` (doesn't use Qt)
- 2 failures in `test_launcher_panel_integration.py` (pre-existing test issues)

## How xdist_group Works

The `@pytest.mark.xdist_group("qt_state")` marker tells pytest-xdist to:
1. Run ALL tests with this marker in the **same worker process**
2. Execute them **serially** within that worker
3. Prevent Qt resource conflicts by ensuring only one test creates Qt widgets at a time

## Best Practices

### For New Qt Tests
Always add BOTH markers to test classes that create Qt widgets:

```python
@pytest.mark.gui_mainwindow  # Semantic marker indicating Qt usage
@pytest.mark.xdist_group("qt_state")  # Technical marker for xdist grouping
class TestMyQtFeature:
    """Test Qt feature."""
    pass
```

### For Module-Level Marking
Use `pytestmark` for entire modules:

```python
pytestmark = [
    pytest.mark.integration,
    pytest.mark.qt,
    pytest.mark.xdist_group("qt_state"),  # All tests in this module grouped
]
```

## Why Automatic Grouping Was Disabled

From `tests/conftest.py` comments (line 1785):
> "Disabled automatic marker addition - we manage xdist_group explicitly in test files.
> This prevents conflicts between different group names (qt_state vs gui_mainwindow)"

The project chose **explicit manual marking** over automatic grouping to avoid conflicts when different test files need different grouping strategies.

## References
- **Documentation**: `UNIFIED_TESTING_GUIDE.md` - Section on "Parallel Test Execution with pytest-xdist"
- **Configuration**: `pyproject.toml` lines 180-214 - Marker definitions
- **Hook**: `tests/conftest.py` lines 1784-1798 - Disabled automatic grouping

## Testing
Run integration tests in parallel to verify no Qt crashes:
```bash
uv run pytest tests/integration/ -n auto --timeout=10
```

Expected: Tests pass or fail normally (no crashes, no "Fatal Python error: Aborted")
