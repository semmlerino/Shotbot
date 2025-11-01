# Mock Reduction Analysis

## Summary
After analyzing the test suite, here are the findings on mock usage and recommendations for reduction.

## Areas Where Mocking is Necessary

1. **External Process Management (QProcess)**
   - Mocking QProcess signals and methods is necessary to avoid real subprocess execution
   - However, we should use real QProcess objects instead of Mock(spec=QProcess) to avoid segfaults
   - Example: `process.exitCode = Mock(return_value=0)` is safer than full process mocking

2. **File System Operations**
   - os.remove, os.path.exists, etc. should remain mocked to avoid actual file operations
   - Helps tests run faster and prevents side effects

3. **Subprocess Calls**
   - FFmpeg detection, hardware acceleration checks need mocking
   - These would be slow and environment-dependent without mocks

## Areas Where Mocking Can Be Reduced

1. **Qt Widgets**
   - Many tests mock QLabel, QProgressBar, etc. when real widgets could be used
   - Real widgets provide better integration testing
   - Example: ProcessMonitor creates real widgets, so tests should use them

2. **Internal Components**
   - Consider using real ProcessManager, ProgressTracker in integration tests
   - Reduces brittleness when internal APIs change

3. **Data Structures**
   - Avoid manually creating widget data structures when the actual methods can create them
   - Example: Use `monitor.create_process_widget()` instead of manually building widget dict

## Recommendations

1. **Segfault Prevention**
   - Never use `Mock(spec=QProcess)` - causes segfaults with Qt signals
   - Use real QProcess objects and mock specific methods as needed

2. **Integration Testing**
   - Create separate integration test files that use real components
   - Keep unit tests focused with appropriate mocking

3. **Mock Granularity**
   - Mock at the boundary (external systems, I/O)
   - Use real objects for internal component interactions

4. **Performance Considerations**
   - Balance between test speed and integration coverage
   - Fast unit tests with mocks + slower integration tests with real components

## Example Patterns

### Bad Pattern
```python
# Causes segfaults
mock_process = Mock(spec=QProcess)
```

### Good Pattern
```python
# Use real QProcess, mock specific behavior
process = QProcess()
process.exitCode = Mock(return_value=0)
```

### Better Pattern (for integration tests)
```python
# Use real components where possible
process_manager = ProcessManager()
monitor = ProcessMonitor(process_manager, real_scroll_area)
widget = monitor.create_process_widget(process, path)
# Test real behavior
```

## Conclusion

The current test suite uses appropriate mocking for most external dependencies. The main improvements would be:
1. Using real Qt widgets in tests where feasible
2. Creating integration tests with real component interactions
3. Avoiding Mock(spec=QProcess) pattern that causes segfaults
4. Keeping mocks at system boundaries (file I/O, subprocesses, external commands)