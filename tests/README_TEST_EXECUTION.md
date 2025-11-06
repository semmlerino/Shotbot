# Test Execution Guide

## Overview

The ShotBot test suite contains 2580 tests (2318 unit + 195 integration + 67 performance). Due to Qt's initialization requirements and mass import overhead, tests should be run separately by category for optimal reliability and performance.

## Quick Start

### Run All Tests (Separately by Category)
```bash
# Run unit tests
~/.local/bin/uv run pytest -p no:rerunfailures tests/unit/ -v --no-cov

# Run integration tests
~/.local/bin/uv run pytest -p no:rerunfailures tests/integration/ -v --no-cov

# Run performance tests
~/.local/bin/uv run pytest -p no:rerunfailures tests/performance/ -v --no-cov
```

### Run Specific Test File
```bash
~/.local/bin/uv run pytest -p no:rerunfailures tests/unit/test_cache_manager.py -v --no-cov
```

## Important Flags

- `-p no:rerunfailures`: Disables pytest-rerunfailures plugin (incompatible with Qt threading)
- `--no-cov`: Disables coverage reporting for faster execution
- `-v`: Verbose output showing individual test results
- `-x`: Stop on first failure (useful for debugging)

## Why Not Run All Tests Together?

Running all 2580 tests in a single pytest command causes:

```bash
# ❌ THIS WILL CRASH
~/.local/bin/uv run pytest tests/ --no-cov

# Output: Fatal Python error: Aborted
# Location: logging_mixin.py line 269 in __init__ (during Qt widget initialization)
```

### Root Cause

**Mass Import Overhead**: When pytest collects 2580 test modules simultaneously:
1. Python imports 2580+ test files with Qt dependencies at once
2. Qt initialization happens inconsistently across massive import scope
3. First integration test tries to create `ShotInfoPanel` → Qt initialization conflicts cause crash

**What's Actually Happening**:
- This is NOT "Qt corruption" - it's mass import causing Qt initialization race conditions
- Qt's event loop and object system expect orderly initialization
- Importing 2580 files simultaneously creates conflicting Qt initialization states

**Individual Test Files Work**: When tests run in smaller batches (by category), Qt initializes cleanly for each batch.

## Test Categories

### Unit Tests (2318 tests)
Location: `tests/unit/`
Purpose: Test individual components in isolation
Execution Time: ~15-20 minutes
```bash
~/.local/bin/uv run pytest -p no:rerunfailures tests/unit/ --no-cov
```

### Integration Tests (195 tests)
Location: `tests/integration/`
Purpose: Test components working together (async workflows, cross-component coordination)
Execution Time: ~5-10 minutes (includes slow subprocess/timeout tests)
```bash
~/.local/bin/uv run pytest -p no:rerunfailures tests/integration/ --no-cov
```

### Performance Tests (67 tests)
Location: `tests/performance/`
Purpose: Test performance characteristics and benchmarks
Execution Time: ~3-5 minutes
```bash
~/.local/bin/uv run pytest -p no:rerunfailures tests/performance/ --no-cov
```

## Real Qt Widgets in Tests

**This is EXPECTED and NECESSARY**:

- **Integration tests** create real Qt widgets to test component integration
- **Unit tests for Qt widgets** create real widgets to test widget behavior
- **Tests use `qtbot.addWidget()`** to ensure proper lifecycle management

Real widgets are NOT the problem - the problem is mass import overhead during test collection.

## Known Test Issues

### 1. pytest-rerunfailures Plugin Conflict
**Problem**: Creates background thread incompatible with Qt's main-thread-only requirement
**Solution**: Always use `-p no:rerunfailures` flag
**Status**: Fixed in `pytest.ini`

### 2. Mass Test Collection Crash
**Problem**: Collecting 2580 tests simultaneously causes Qt initialization conflicts
**Solution**: Run test categories separately (unit/integration/performance)
**Status**: Documented workaround (no code fix needed)

### 3. Qt Thread Cleanup (RESOLVED)
**Problem**: Missing `deleteLater()` + event processing caused Qt C++ object accumulation
**Solution**: Use `cleanup_qthread_properly()` helper from `tests/helpers/qt_thread_cleanup.py`
**Status**: ✅ Fixed - All worker tests now use proper cleanup sequence

### 4. Slow Subprocess/Timeout Tests
**Problem**: `test_subprocess_failure_handled_gracefully` and similar tests wait for full timeouts
**Workaround**: Run with `-x` flag to skip remaining tests after first failure
**Status**: Expected behavior (testing timeout handling)

## Test Markers

Tests are organized with pytest markers:

```bash
# Run only Qt-heavy tests
~/.local/bin/uv run pytest -m qt_heavy

# Run only fast tests
~/.local/bin/uv run pytest -m fast

# Run only thread-safety tests
~/.local/bin/uv run pytest -m thread_safety

# Exclude slow tests
~/.local/bin/uv run pytest -m "not slow"
```

Available markers:
- `unit`: Unit tests
- `integration`: Integration tests
- `qt`: Tests requiring Qt
- `qt_heavy`: Tests creating multiple Qt widgets
- `slow`: Tests taking >1 second
- `fast`: Tests taking <0.1 seconds
- `concurrent`: Concurrency/threading tests
- `thread_safety`: Thread-safety validation tests
- `performance`: Performance benchmarks
- `critical`: Critical path tests (must pass)
- `gui_mainwindow`: Tests for main window GUI
- `integration_safe`: Integration tests that can run in any order
- `integration_unsafe`: Integration tests with side effects

## Continuous Integration

For CI/CD pipelines, run tests separately:

```yaml
# Example GitHub Actions / GitLab CI
test-unit:
  script:
    - uv run pytest -p no:rerunfailures tests/unit/ --no-cov -x

test-integration:
  script:
    - uv run pytest -p no:rerunfailures tests/integration/ --no-cov -x

test-performance:
  script:
    - uv run pytest -p no:rerunfailures tests/performance/ --no-cov -x
```

## Debugging Test Failures

### 1. Run Single Test with Full Output
```bash
~/.local/bin/uv run pytest -p no:rerunfailures tests/unit/test_cache_manager.py::TestCacheManagerInitialization::test_initialization_creates_directories -vv -s --no-cov
```

### 2. Run with Python Debugger
```bash
~/.local/bin/uv run pytest -p no:rerunfailures tests/unit/test_cache_manager.py -vv --pdb
```

### 3. Check Test Logs
```bash
# Logs written to /tmp/ during test runs
tail -f /tmp/pytest_unit_tests.log
tail -f /tmp/pytest_integration_tests.log
```

## Test Development Guidelines

### Creating New Tests

1. **Unit tests**: Place in `tests/unit/`, use `qtbot` fixture for Qt widgets
2. **Integration tests**: Place in `tests/integration/`, ensure proper cleanup
3. **Mark appropriately**: Use `@pytest.mark.slow`, `@pytest.mark.qt_heavy`, etc.

### Qt Widget Testing Best Practices

```python
def test_widget_creation(qtbot, qapp, cache_manager):
    """Test widget can be created and displayed."""
    # Create widget
    widget = ShotInfoPanel(cache_manager)

    # Register with qtbot for proper cleanup
    qtbot.addWidget(widget)

    # Verify widget is functional
    assert widget.isVisible() is False  # Not shown yet
    widget.show()
    assert widget.isVisible() is True

    # qtbot handles cleanup automatically
```

### Qt QThread Testing Best Practices

For tests using QThread workers, always use proper cleanup:

```python
from tests.helpers.qt_thread_cleanup import cleanup_qthread_properly

def test_worker_operation(qtbot):
    """Test worker performs operation correctly."""
    worker = MyWorker()

    # Track signal handlers for cleanup
    signal_handlers = [
        (worker.finished, on_finished),
        (worker.progress, on_progress),
    ]

    try:
        with qtbot.waitSignal(worker.finished):
            worker.start()

        # Test assertions...
    finally:
        # CRITICAL: Proper cleanup sequence:
        # 1. Disconnect signals
        # 2. Stop thread gracefully
        # 3. deleteLater() + processEvents()
        cleanup_qthread_properly(worker, signal_handlers)
```

**Why This Matters**:
- Without `deleteLater()` + event processing, Qt C++ objects accumulate
- Accumulation causes segfaults after many tests (even in serial mode)
- The cleanup helper implements the complete Qt cleanup sequence
- See `QT_TEST_HYGIENE_AUDIT.md` for detailed explanation

### Thread-Safety Testing Best Practices

```python
def test_concurrent_access(cache_manager):
    """Test thread-safe cache access."""
    import threading

    def worker():
        # Access shared resource
        cache_manager.cache_thumbnail(...)

    # Start multiple threads
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    # Verify no corruption occurred
    assert len(cache_manager.get_cached_shots()) == expected_count
```

## Summary

**Key Takeaway**: Run unit, integration, and performance tests SEPARATELY to avoid Qt initialization conflicts during mass import. Tests pass reliably when run by category - this is the expected and supported workflow.

## Additional Resources

- **Qt Test Hygiene**: See `QT_TEST_HYGIENE_AUDIT.md` for details on proper Qt cleanup patterns
- **Thread Cleanup**: See `tests/helpers/qt_thread_cleanup.py` for reusable cleanup helper
- **General Testing Guide**: See `UNIFIED_TESTING_V2.MD` for comprehensive testing guidance
