# ProcessManager Test Mocking Analysis

## Current State
- 12 tests use `Mock(spec=QProcess)` 
- 2 tests fixed to use real QProcess objects (to avoid segfaults)
- Heavy mocking of QProcess behavior throughout

## Problems Identified

### 1. Segfault Risk
- `Mock(spec=QProcess)` causes segfaults when Qt signals are emitted
- Already fixed in 2 tests that directly trigger signal emission

### 2. Over-Mocking Issues
- Tests are tightly coupled to implementation details
- Mocking QProcess internals makes tests brittle
- Hard to verify actual Qt integration works correctly

### 3. Tests That Could Use Real QProcess
Many tests mock QProcess unnecessarily:
- `test_empty_output_handling` - safe because bytesAvailable()=0 prevents signal emission
- `test_process_queue_management` - only tests queue logic, QProcess not actually used
- `test_process_finished_handling` - mocks finished signal behavior

## Recommendations

### 1. Use Real QProcess Where Possible
For tests that don't actually start FFmpeg processes:
```python
process = QProcess()
# Only mock specific methods needed
process.waitForStarted = Mock(return_value=True)
```

### 2. Create Test Helper
```python
def create_test_process():
    """Create a QProcess configured for testing"""
    process = QProcess()
    process.waitForStarted = Mock(return_value=True)
    return process
```

### 3. Tests That Should Keep Mocks
- Tests verifying FFmpeg command construction
- Tests checking subprocess.run calls
- Tests where we need to control exact output/behavior

### 4. Integration Test Approach
Consider creating integration tests that:
- Use real QProcess
- Start a simple command (like `echo` or `sleep`)
- Test actual signal/slot behavior

## Next Steps
1. Replace Mock(spec=QProcess) with real QProcess in safe tests
2. Create test helper functions
3. Add integration tests for critical paths
4. Document which tests need mocks and why