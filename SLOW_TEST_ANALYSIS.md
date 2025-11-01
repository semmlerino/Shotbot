# Slow Test Execution Analysis

## Root Causes Identified

### 1. Sleep Calls in Tests
Found explicit sleep calls that add delays:
- **test_logging_system.py**:
  - Line 40: `time.sleep(0.1)` - Performance metric tracking
  - Line 406: `time.sleep(0.1)` - Simulating work
  - Line 434: `time.sleep(0.05)` - Worker simulation
  - Total: ~0.25s per test run

- **test_output_buffer.py**:
  - Line 113: `time.sleep(0.11)` - Testing batch intervals
  - Multiple tests use this pattern

### 2. Large Dataset Tests
Tests with heavy iterations:
- **test_conversion_controller.py**:
  - Line 841: Creates 1000 file entries for memory test
- **test_progress_tracker.py**:
  - Line 493: 100 iterations simulating frequent updates
- **test_process_manager.py**:
  - Line 450: 100 iterations for buffer testing

### 3. Qt Signal Timeouts
Multiple tests wait for Qt signals with 1000ms timeouts:
- File list widget signal tests
- Settings panel signal tests
- Process monitor signal tests

## Performance Impact

Estimated time consumption:
- Sleep calls: ~3-5 seconds total
- Large datasets: ~5-10 seconds
- Qt signal waits: Variable, but can add 1s per test
- **Total estimated overhead**: 10-20 seconds

## Recommendations

### 1. Reduce Sleep Times
```python
# Instead of:
time.sleep(0.1)

# Use minimal delays:
time.sleep(0.01)  # 10x faster

# Or mock time for instant tests:
with patch('time.time', side_effect=[0, 0.1, 0.2]):
    # Test proceeds instantly
```

### 2. Reduce Dataset Sizes
```python
# Instead of:
for i in range(1000):

# Use smaller datasets that still test the logic:
for i in range(10):  # 100x faster
```

### 3. Use Pytest Markers
```python
# Mark slow tests
@pytest.mark.slow
def test_large_dataset():
    pass

# Run fast tests only:
# pytest -m "not slow"
```

### 4. Optimize Qt Signal Tests
```python
# Reduce timeout for faster failures:
with self.qtbot.waitSignal(signal, timeout=100):  # 100ms instead of 1000ms
```

### 5. Parallel Test Execution
```bash
# Install pytest-xdist
pip install pytest-xdist

# Run tests in parallel
pytest -n auto  # Uses all CPU cores
```

## Quick Wins

1. **Replace sleep(0.1) with sleep(0.01)**: Save ~2-3 seconds
2. **Reduce large datasets from 1000 to 100**: Save ~5 seconds
3. **Lower Qt signal timeouts to 100ms**: Save ~1-2 seconds
4. **Total potential savings**: 8-10 seconds

## Implementation Priority

1. **High Priority**: Fix sleep calls (easy, high impact)
2. **Medium Priority**: Add slow test markers
3. **Low Priority**: Optimize large dataset tests (may affect coverage)