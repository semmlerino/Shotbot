# Test Performance Improvements

## Summary
Implemented quick performance optimizations to reduce test execution time by 8-10 seconds.

## Changes Made

### 1. Reduced Sleep Times (Saved ~2-3 seconds)
- `test_logging_system.py`: Reduced sleep times from 0.1s → 0.01s and 0.05s → 0.005s
- `test_output_buffer.py`: Reduced batch interval from 0.1s → 0.01s

### 2. Reduced Qt Signal Timeouts (Saved ~1-2 seconds)
- Changed all Qt signal timeouts from 1000ms → 100ms in:
  - `test_file_list_widget.py`
  - `test_process_monitor.py`
  - `test_settings_panel.py`

### 3. Added Pytest Markers for Slow Tests
- Added `slow` marker to pytest.ini
- Marked tests with large datasets or iterations:
  - `test_conversion_controller.py::test_memory_cleanup_on_large_queue` (1000 items)
  - `test_process_manager.py::test_output_buffer_management` (100 iterations)
  - `test_progress_tracker.py::test_frequent_progress_updates` (100 iterations)

### 4. Installed pytest-xdist
- Enabled parallel test execution with `pytest -n auto`
- Use `pytest -m "not slow"` to skip slow tests during development

## Usage

### Run all tests in parallel:
```bash
pytest -n auto
```

### Run only fast tests:
```bash
pytest -m "not slow"
```

### Run fast tests in parallel:
```bash
pytest -n auto -m "not slow"
```

## Results
- Test execution time reduced from ~10-20s to ~1-2s for common test runs
- No functionality changes - only timing adjustments
- All 274 tests still passing
- Fixed one test failure in `test_full_conversion_workflow` (missing mock)
- **Fixed critical segfault** in `test_process_manager.py` by replacing `Mock(spec=QProcess)` with real QProcess objects

## Critical Fix: Segfault Resolution
Fixed segmentation faults in `test_process_manager.py` by:
- Replacing `Mock(spec=QProcess)` with real `QProcess()` objects
- Mocking only specific methods needed for tests
- This prevents crashes when Qt signals are emitted with mock objects

## Next Steps
1. Consider further optimization of tests with 1000-item datasets
2. Investigate Qt event loop optimizations
3. Add CI configuration to run slow tests separately
4. Review other test files for similar Mock(spec=QProcess) patterns