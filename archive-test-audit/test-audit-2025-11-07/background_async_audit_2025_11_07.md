# Background Async Operation Issues in MainWindow Tests

## Summary
Found critical race conditions between background async loaders and manual test data assignment. No MainWindow instances explicitly use `defer_background_loads` because this parameter doesn't exist. Instead, background loaders are managed through `ShotModel._async_loader` which can clear test data when background refresh completes.

## Key Findings

### 1. MainWindow Instantiation Patterns

**All 47+ MainWindow() creations in tests lack any mechanism to prevent async loading:**

- `/home/gabrielh/projects/shotbot/tests/integration/test_launcher_panel_integration.py` - 13 instances (lines 156, 181, 214, 272, 320, 348, 448, 513, 568, 604, 670, 688, 710)
- `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py` - 6 instances (lines 266, 468, 617, 681, 774, 814)
- `/home/gabrielh/projects/shotbot/tests/integration/test_user_workflows.py` - 11 instances (lines 283, 363, 446, 524, 637, 737, 890, 995, 1052, 1144)
- `/home/gabrielh/projects/shotbot/tests/integration/test_main_window_coordination.py` - 1 instance (line 413)
- `/home/gabrielh/projects/shotbot/tests/unit/test_main_window.py` - 16 instances (lines 194, 220, 228, 241, 270, 297, 330, 374, 399, 468, 488, 504, 517, 538, 610, 655, 704, 727)
- `/home/gabrielh/projects/shotbot/tests/unit/test_notification_manager.py` - 1 instance (line 64 - uses QMainWindow, not MainWindow)

### 2. Background Loader Behavior

**The ShotModel starts async loading immediately during initialization:**

File: `/home/gabrielh/projects/shotbot/shot_model.py` lines 193-241

```python
def initialize_async(self) -> RefreshResult:
    """Initialize with cached data and start background refresh."""
    # Step 1: Load cached shots immediately
    cached_shots = self.cache_manager.get_cached_shots()
    if cached_shots:
        self.shots = [Shot.from_dict(s) for s in cached_shots]
        
    # Step 2: Start background refresh
    self._start_background_refresh()  # <-- PROBLEM: Starts immediately!
```

The `_start_background_refresh()` method creates an `AsyncShotLoader` that runs in a separate thread.

### 3. Race Condition Pattern

**This is the critical race condition found in tests:**

File: `/home/gabrielh/projects/shotbot/tests/integration/test_user_workflows.py` lines 750-843

```python
# Test stops the async loader
main_window.shot_model._async_loader.stop()
main_window.shot_model._loading_in_progress = False

# Clear any cached shots
main_window.shot_model.shots = []

# Create and assign test shots
main_window.shot_model.shots = all_shots  # Line 828
main_window._on_shots_changed(all_shots)  # Line 835

# Wait for UI updates
qtbot.wait(100)  # Line 843

# DEBUG SHOWS: shot_model may have different shot count after wait!
# This suggests async loader is being restarted and clearing data
```

### 4. Tests Manually Clearing Loader State

**These tests must manually manage async loader state:**

- `/home/gabrielh/projects/shotbot/tests/integration/test_user_workflows.py:750-762` - Manually stops loader, clears shots, clears cache
- `/home/gabrielh/projects/shotbot/tests/integration/test_main_window_coordination.py:423` - Replaces shot_model's process pool
- `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py:273` - Has comment "Stop any background loaders that might have started"

### 5. Cache-Related Issues

**Test setups must clear cache to prevent reload of old data:**

- `/home/gabrielh/projects/shotbot/tests/integration/test_user_workflows.py:762` - `main_window.shot_model._cache = None`
- `/home/gabrielh/projects/shotbot/tests/integration/test_launcher_panel_integration.py` - Uses mocked ProcessPoolManager
- `/home/gabrielh/projects/shotbot/tests/integration/test_main_window_coordination.py:413` - Creates with cache_manager but replaces process_pool post-init

## Root Cause

**No mechanism to defer background loads exists.**

MainWindow __init__ (lines 177-181):
```python
def __init__(
    self,
    cache_manager: CacheManager | None = None,
    parent: QWidget | None = None,
) -> None:
```

The constructor:
1. Creates ShotModel (line 263)
2. Calls `self.shot_model.initialize_async()` (line 266)
3. This immediately calls `_start_background_refresh()` which launches AsyncShotLoader in a thread

**There is NO parameter to prevent this or any way to control timing.**

## Vulnerable Test Patterns

### Pattern 1: Manual Data Assignment Race
```python
window = MainWindow()
window.shot_model.shots = [test_shot]
qtbot.wait(100)  # May get cleared by background loader
assert window.shot_model.shots  # May fail!
```

Location: `/home/gabrielh/projects/shotbot/tests/integration/test_main_window_coordination.py:523, 616, 813`

### Pattern 2: Missing Cache Clearing
```python
window = MainWindow()  # May load shots from cache
# Test assumes empty model but cache has old data
window.shot_model.shots = []  # Assign test data
qtbot.wait()  # Cache may be reloaded by async
```

Location: `/home/gabrielh/projects/shotbot/tests/integration/test_user_workflows.py:759`

### Pattern 3: Uncontrolled Async with qtbot.wait()
```python
window = MainWindow()
qtbot.wait(100)  # Process all pending Qt events
# Background loader may complete during this wait
# and merge/replace shot data unexpectedly
```

Locations: Multiple in test_launcher_panel_integration.py

## Recommended Fixes

### Option 1: Add defer_background_loads Parameter (RECOMMENDED)
```python
def __init__(
    self,
    cache_manager: CacheManager | None = None,
    parent: QWidget | None = None,
    defer_background_loads: bool = False,  # <-- NEW
) -> None:
    ...
    if not defer_background_loads:
        init_result = self.shot_model.initialize_async()
```

### Option 2: Stop Loader Explicitly in Test Fixtures
```python
@pytest.fixture
def main_window_for_tests(qtbot):
    window = MainWindow()
    # Stop async loader immediately
    if window.shot_model._async_loader:
        window.shot_model._async_loader.request_stop()
        window.shot_model._async_loader.wait()
    return window
```

### Option 3: Clear Test Data Preparation Pattern
```python
# Before assigning test data:
if window.shot_model._async_loader and window.shot_model._async_loader.isRunning():
    window.shot_model._async_loader.request_stop()
    window.shot_model._async_loader.wait(1000)
    
# Now safe to assign test data
window.shot_model.shots = test_shots
```

## Test Files Affected

### HIGH PRIORITY (Direct MainWindow usage with test data)
1. `/home/gabrielh/projects/shotbot/tests/integration/test_main_window_coordination.py` - Direct shot assignment, no loader control
2. `/home/gabrielh/projects/shotbot/tests/integration/test_user_workflows.py` - Complex async sequences with manual loader stopping
3. `/home/gabrielh/projects/shotbot/tests/integration/test_launcher_panel_integration.py` - 13 MainWindow instances with potential race conditions

### MEDIUM PRIORITY (Signal-based workflows)
4. `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py` - Has some loader awareness but inconsistent
5. `/home/gabrielh/projects/shotbot/tests/unit/test_main_window.py` - 16 instances, mostly in unit context

## Implementation Status
- `defer_background_loads` parameter: NOT IMPLEMENTED
- No control mechanism: Confirmed
- Manual workarounds: PRESENT but inconsistent across test files
