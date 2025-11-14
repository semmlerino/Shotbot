# Threading Teardown Crash Fix Summary

## Problem
Test suite crashed during teardown with `Fatal Python error: Aborted` when PersistentTerminalManager workers spawned subprocesses during pytest-qt teardown.

### Root Cause
1. **Worker threads still active during teardown**: Workers pulled tasks from queue and called `_launch_terminal()` → subprocess spawn → crash
2. **Timing race**: Shutdown checks happened at worker entry, but workers already past those checks
3. **Fixture ordering**: pytest-qt teardown ran BEFORE our cleanup fixtures, so workers still active when Qt shut down

### Stack Trace
```
persistent_terminal_manager.py:785 in _launch_terminal
→ subprocess.Popen() during pytest-qt teardown
→ Fatal Python error: Aborted
```

## Solution

### 1. Instance Tracking (persistent_terminal_manager.py)
Added class-level tracking to enable cleanup of all instances:

```python
class PersistentTerminalManager(LoggingMixin, QObject):
    # Class-level tracking for test cleanup
    _test_instances: ClassVar[list[PersistentTerminalManager]] = []
    _test_instances_lock: ClassVar[threading.Lock] = threading.Lock()
    
    def __init__(self, ...):
        ...
        # Track instance for test cleanup
        with self.__class__._test_instances_lock:
            self.__class__._test_instances.append(self)
    
    def cleanup(self) -> None:
        # Remove from test instances tracking
        with self.__class__._test_instances_lock:
            if self in self.__class__._test_instances:
                self.__class__._test_instances.remove(self)
        ...
    
    @classmethod
    def cleanup_all_instances(cls) -> None:
        """Clean up all tracked instances (for test teardown)."""
        with cls._test_instances_lock:
            instances = list(cls._test_instances)
        
        for instance in instances:
            try:
                instance.cleanup()
            except Exception:
                pass
```

### 2. Early Cleanup Fixture (tests/conftest.py)
Updated `cleanup_persistent_terminals` autouse fixture to actually cleanup instances:

```python
@pytest.fixture(autouse=True)
def cleanup_persistent_terminals(qtbot: QtBot) -> Iterator[None]:
    """Stop all PersistentTerminalManager workers BEFORE Qt teardown."""
    yield
    
    # This runs BEFORE pytest-qt teardown
    try:
        from persistent_terminal_manager import PersistentTerminalManager
        PersistentTerminalManager.cleanup_all_instances()
    except (ImportError, RuntimeError):
        pass
```

### 3. Test Fixture Cleanup
Updated all test fixtures to call `cleanup()` in teardown:

- `tests/unit/test_persistent_terminal_manager.py`: Added cleanup to `terminal_manager` and `terminal_manager_with_real_paths` fixtures
- `tests/unit/test_persistent_terminal.py`: Changed `cleanup_fifo_only()` to `cleanup()`

## Key Design Decisions

### Why Instance Tracking?
- **No singleton pattern**: PersistentTerminalManager is instantiated per-test
- **pytest-qt runs first**: Our cleanup fixtures run AFTER pytest-qt teardown
- **Need early cleanup**: Must stop workers BEFORE Qt starts tearing down
- **Solution**: Track all instances and cleanup in autouse fixture

### Why ClassVar Annotations?
- **Type safety**: Proper annotations for class-level variables
- **Static analysis**: basedpyright understands these are shared across instances
- **Documentation**: Clear intent that these are class-level, not instance-level

### Defense in Depth
1. **Individual test cleanup**: Each fixture calls `manager.cleanup()`
2. **Autouse fixture**: `cleanup_persistent_terminals` catches any missed instances
3. **Shutdown flag check**: Workers check `_shutdown_flag` at entry point
4. **Safe cleanup**: `cleanup_all_instances()` ignores exceptions

## Test Results

### Before Fix
```
Fatal Python error: Aborted
tests/integration/test_user_workflows.py → CRASH
```

### After Fix
```
tests/unit/test_persistent_terminal_manager.py: 41/41 passed ✓
tests/integration/test_user_workflows.py: Running without crash ✓
```

## Files Modified

1. **persistent_terminal_manager.py**
   - Added `ClassVar` import
   - Added `_test_instances` and `_test_instances_lock` class variables
   - Added instance registration in `__init__`
   - Added instance removal in `cleanup()`
   - Added `cleanup_all_instances()` classmethod

2. **tests/conftest.py**
   - Updated `cleanup_persistent_terminals` fixture to call `cleanup_all_instances()`

3. **tests/unit/test_persistent_terminal_manager.py**
   - Added `manager.cleanup()` to `terminal_manager` fixture
   - Added `manager.cleanup()` to `terminal_manager_with_real_paths` fixture

4. **tests/unit/test_persistent_terminal.py**
   - Changed `cleanup_fifo_only()` to `cleanup()`

## Verification

Run full test suite:
```bash
~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup
```

Expected: 0 teardown crashes, all tests passing.

## References

- **UNIFIED_TESTING_V2.MD**: Qt Testing Hygiene Rule 2 - "Stop all async operations"
- **PersistentTerminalManager.cleanup()**: Lines 1368-1406 - Comprehensive worker cleanup
- **ThreadSafeWorker.safe_stop()**: Proper QThread shutdown with timeout
