# Test Suite Refactoring Guide

## Overview

This guide demonstrates how to refactor test files from unittest.mock anti-patterns to behavior-focused testing following UNIFIED_TESTING_GUIDE principles.

## Key Refactoring Patterns

### 1. Remove ALL unittest.mock Usage

**Before (Anti-pattern):**
```python
from unittest.mock import Mock, patch, MagicMock

with patch("subprocess.Popen") as mock_popen:
    mock_popen.return_value = Mock(returncode=0)
    mock_popen.assert_called_with(...)
```

**After (Best Practice):**
```python
from tests.test_doubles_library import PopenDouble, TestSubprocess

subprocess_handler = SubprocessDouble()
worker = TestableLauncherWorker("id", "cmd", subprocess_handler)
# Test behavior through signals and state changes
```

### 2. Use Dependency Injection

**Before (Anti-pattern):**
```python
@patch("launcher_manager.subprocess.Popen")
def test_something(mock_popen):
    manager = LauncherManager()
    # Patching reaches into internals
```

**After (Best Practice):**
```python
class TestableLauncherManager(LauncherManager):
    def set_subprocess_handler(self, handler):
        self._subprocess_handler = handler

manager = TestableLauncherManager()
manager.set_subprocess_handler(SubprocessDouble())
```

### 3. Test Behavior, Not Implementation

**Before (Anti-pattern):**
```python
mock_worker.do_work.assert_called_once()
mock_process.terminate.assert_called()
```

**After (Best Practice):**
```python
# Use QSignalSpy to observe behavior
start_spy = QSignalSpy(worker.command_started)
finish_spy = QSignalSpy(worker.command_finished)

worker.do_work()

# Test what happened, not how
assert start_spy.count() == 1
assert finish_spy.at(0)[1] == True  # success
```

### 4. Use Real Components Where Possible

**Before (Anti-pattern):**
```python
mock_config = Mock()
mock_config.load_launchers.return_value = {}
```

**After (Best Practice):**
```python
with tempfile.TemporaryDirectory() as temp_dir:
    config = LauncherConfig(temp_dir)  # Real config
    launchers = config.load_launchers()  # Real I/O
```

### 5. Mock Only at System Boundaries

**System Boundaries to Mock:**
- subprocess.Popen / subprocess.run
- File I/O (only when necessary)
- Network calls
- System time (when testing timeouts)

**NOT System Boundaries (Use Real):**
- Application classes
- Qt widgets and signals
- Business logic
- Data models

## Refactored Test Structure

### Test Double at System Boundary
```python
class SubprocessDouble:
    """Replaces subprocess operations with predictable behavior."""
    
    def create_process(self, command: str) -> PopenDouble:
        if "sleep" in command:
            process = PopenDouble(command)
            process._should_hang = True
        elif "fail" in command:
            process = PopenDouble(command, returncode=1)
        else:
            process = PopenDouble(command, returncode=0)
        return process
```

### Enhanced Class with Dependency Injection
```python
class TestableLauncherWorker(LauncherWorker):
    """Real LauncherWorker with injected subprocess handler."""
    
    def __init__(self, launcher_id: str, command: str, subprocess_handler=None):
        super().__init__(launcher_id, command)
        self._subprocess_handler = subprocess_handler or SubprocessDouble()
```

### Behavior-Focused Test
```python
def test_successful_execution(self, qtbot):
    """Test execution behavior through observable outcomes."""
    # Setup with dependency injection
    subprocess_handler = SubprocessDouble()
    worker = TestableLauncherWorker("id", "cmd", subprocess_handler)
    
    # Observe behavior with QSignalSpy
    finish_spy = QSignalSpy(worker.command_finished)
    
    # Execute
    worker.do_work()
    
    # Verify behavior (what happened)
    assert finish_spy.count() == 1
    assert finish_spy.at(0)[1] == True  # success
```

## Files to Refactor

### Priority 1: Core Test Files (10 files)
1. `test_launcher_manager.py` - Main launcher tests
2. `test_command_launcher.py` - Command execution tests
3. `test_main_window.py` - Main window tests
4. `test_shot_model.py` - Shot model tests
5. `test_cache_manager.py` - Cache management tests
6. `test_threede_scene_finder.py` - 3DE scene discovery
7. `test_previous_shots_worker.py` - Previous shots worker
8. `test_shot_grid.py` - Shot grid widget tests
9. `test_thumbnail_processor.py` - Thumbnail processing
10. `test_process_pool_manager_simple.py` - Process pool tests

### Priority 2: Integration Tests (5 files)
1. `test_cache_integration.py`
2. `test_launcher_workflow_integration.py`
3. `test_shot_workflow_integration.py`
4. `test_threede_scanner_integration.py`
5. `test_thumbnail_discovery_integration.py`

### Priority 3: Supporting Tests (14 files)
- Worker tests
- Model tests
- Utility tests
- Widget tests

## Implementation Steps

### Step 1: Create Test Doubles
- Identify system boundaries in the test
- Create test doubles for those boundaries only
- Add to test_doubles_library.py if reusable

### Step 2: Add Dependency Injection
- Create Testable* versions of classes
- Add setter methods for injecting test doubles
- Keep original class interface intact

### Step 3: Replace Mock Assertions
- Replace `assert_called*` with state checks
- Replace `Mock.return_value` with test double behavior
- Use QSignalSpy for signal testing

### Step 4: Use Real Components
- Replace mocked application classes with real ones
- Use tempfile for file operations
- Use real Qt widgets and models

### Step 5: Verify Behavior
- Test outcomes, not method calls
- Check state changes
- Verify signal emissions
- Ensure error handling works

## Example Transformation

### Original File (with anti-patterns):
```python
from unittest.mock import Mock, patch

class TestLauncherManager:
    @patch("subprocess.Popen")
    def test_execution(self, mock_popen):
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        
        manager = LauncherManager()
        manager.execute_launcher("test")
        
        mock_popen.assert_called_once()
        mock_process.poll.assert_called()
```

### Refactored File (best practices):
```python
from tests.test_doubles_library import PopenDouble

class TestLauncherManager:
    def test_execution(self, qtbot):
        # Use dependency injection
        subprocess_handler = SubprocessDouble()
        manager = TestableLauncherManager()
        manager.set_subprocess_handler(subprocess_handler)
        
        # Observe behavior with signals
        started_spy = QSignalSpy(manager.execution_started)
        
        # Execute
        launcher_id = manager.create_launcher("Test", "echo test")
        success = manager.execute_launcher(launcher_id)
        
        # Verify behavior, not implementation
        assert started_spy.count() > 0
        assert success in [True, False]  # Actual result
```

## Benefits of Refactoring

1. **More Reliable Tests**: No brittle mock setups
2. **Better Coverage**: Tests actual behavior, not mocked returns
3. **Clearer Intent**: Tests show what the system does
4. **Easier Maintenance**: Changes to implementation don't break tests
5. **Faster Debugging**: Real components provide real stack traces

## Common Pitfalls to Avoid

1. **Don't Mock Qt Objects**: Use real Qt objects with QSignalSpy
2. **Don't Mock Business Logic**: Test it directly
3. **Don't Use assert_called**: Check actual outcomes instead
4. **Don't Mock Too Deep**: Only mock at system boundaries
5. **Don't Ignore Threading**: Use ThreadSafeTestImage for worker tests

## Validation Checklist

For each refactored file, verify:
- [ ] No `unittest.mock` imports
- [ ] No `Mock()` or `MagicMock()` usage
- [ ] No `@patch` decorators
- [ ] No `assert_called*` methods
- [ ] Uses test doubles from library
- [ ] Tests behavior through state/signals
- [ ] Uses real components where possible
- [ ] Only mocks system boundaries
- [ ] Has proper Qt signal testing with QSignalSpy

## Running the Tests

```bash
# Run a single refactored test
pytest tests/unit/test_launcher_manager_refactored.py -v

# Run with Qt support
pytest tests/unit/test_launcher_manager_refactored.py -v --qt-api=pyside6

# Check for mock usage
grep -r "unittest.mock" tests/unit/test_launcher_manager_refactored.py
# Should return nothing

# Verify behavior testing
grep -c "QSignalSpy" tests/unit/test_launcher_manager_refactored.py
# Should return multiple matches
```

## Next Steps

1. Start with `test_launcher_manager_coverage.py` as the template
2. Apply patterns to Priority 1 files first
3. Update test_doubles_library.py with new reusable doubles
4. Run tests after each refactoring to ensure they still pass
5. Document any new patterns discovered

The refactored `test_launcher_manager_refactored.py` serves as a complete example of all these principles in action.