# Testing Best Practices for ShotBot

> **⚠️ ARCHIVED**: This document has been consolidated into `UNIFIED_TESTING_V2.MD` (2025-10-31)
>
> **Reason**: We had three overlapping testing guides causing confusion. All content from this guide has been merged into the single authoritative `UNIFIED_TESTING_V2.MD` guide.
>
> **Please use**: `/UNIFIED_TESTING_V2.MD` - The consolidated testing guide with all best practices
>
> **See also**: `docs/TEST_ISOLATION_CASE_STUDIES.md` - Real debugging examples

---

# ARCHIVED CONTENT BELOW (2025-10-31)

## Executive Summary

This document outlines best practices for maintaining and running the ShotBot test suite, based on Phase 3A fixes that resolved test isolation issues and enabled efficient parallel test execution.

## Key Principles

1. **Test What Exists**: Tests must match the actual implementation, not imagined interfaces
2. **Avoid Anti-patterns**: No `time.sleep()` or `QApplication.processEvents()` in tests
3. **Test Isolation**: Tests must not share state or depend on execution order
4. **Parallel Safety**: Qt tests require special handling for parallel execution

## Running Tests

### Quick Validation
```bash
~/.local/bin/uv run python tests/utilities/quick_test.py
```

### Serial Execution (slower but reliable)
```bash
~/.local/bin/uv run pytest tests/ -p no:xdist
```

### Parallel Execution (faster but requires proper markers)
```bash
~/.local/bin/uv run pytest tests/  # Uses -n auto from pytest.ini
```

### Specific Test Categories
```bash
# Unit tests only
~/.local/bin/uv run pytest tests/unit/

# Integration tests
~/.local/bin/uv run pytest tests/integration/

# Fast tests (<100ms)
~/.local/bin/uv run pytest tests/ -m fast

# Qt tests (run serially for stability)
~/.local/bin/uv run pytest tests/ -m qt -p no:xdist
```

## Anti-Pattern Replacements

### ❌ DON'T: Use time.sleep()
```python
# WRONG - blocks parallel execution
time.sleep(0.1)
```

### ✅ DO: Use synchronization helpers
```python
# RIGHT - non-blocking simulation
from tests.helpers.synchronization import simulate_work_without_sleep
simulate_work_without_sleep(100)  # milliseconds
```

### ❌ DON'T: Use QApplication.processEvents()
```python
# WRONG - causes race conditions
app.processEvents()
```

### ✅ DO: Use process_qt_events()
```python
# RIGHT - thread-safe event processing
from tests.helpers.synchronization import process_qt_events
process_qt_events(app, 10)  # milliseconds
```

### ❌ DON'T: Use bare waits
```python
# WRONG - unreliable timing
widget.do_something()
time.sleep(1)
assert widget.is_done
```

### ✅ DO: Use condition-based waiting
```python
# RIGHT - waits only as long as needed
from tests.helpers.synchronization import wait_for_condition
widget.do_something()
wait_for_condition(lambda: widget.is_done, timeout_ms=1000)
```

## Test Markers for Parallel Execution

### ⚠️ IMPORTANT: xdist_group Markers Are Usually WRONG

**Common Misconception**: Using `xdist_group` to fix parallel test failures
**Reality**: `xdist_group` is a band-aid that masks isolation problems

**DON'T DO THIS**:
```python
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.xdist_group("qt_state")  # ❌ WRONG - masks real issues
]
```

**Why xdist_group is problematic**:
1. Forces tests onto same worker, concentrating state pollution
2. Doesn't guarantee cleanup between tests in the group
3. Makes failures intermittent instead of consistent
4. Hides the root cause (shared state, improper cleanup)

**DO THIS INSTEAD**: Fix the actual isolation problem
- Use proper cleanup (try/finally blocks)
- Isolate global state (monkeypatch)
- Clear caches before tests
- Ensure Qt resources are properly deleted

### Available Markers
- `fast`: Tests completing in <100ms
- `slow`: Tests taking >1s
- `unit`: Unit tests
- `integration`: Integration tests
- `qt`: Tests requiring Qt event loop
- `gui`: GUI tests requiring display
- `gui_mainwindow`: Tests creating MainWindow (must be serialized)
- ~~`xdist_group(name)`: Tests that must run in same worker~~ **DEPRECATED** - Fix isolation instead

## GUI Popup Prevention

### Automatic Popup Prevention
Tests run with comprehensive popup prevention implemented at module import time in `conftest.py`:

1. **Offscreen Qt Platform**: Set before any Qt imports
```python
os.environ["QT_QPA_PLATFORM"] = "offscreen"
```

2. **Complete Widget Show Prevention**: All Qt show/visibility methods are patched
```python
# Virtual visibility tracking for tests
_virtually_visible_widgets = set()

# Patched methods:
QWidget.show = _mock_widget_show         # Prevents actual display
QWidget.hide = _mock_widget_hide         # Manages virtual visibility
QWidget.setVisible = _mock_widget_setVisible
QWidget.isVisible = _mock_widget_isVisible  # Returns virtual state
QMainWindow.show = _mock_widget_show
QDialog.exec = _mock_dialog_exec         # Returns without blocking
QEventLoop.exec = _mock_eventloop_exec   # Processes events without blocking
```

3. **QRunnable Signal Support**: Event loop mock processes events properly
```python
def _mock_eventloop_exec(self):
    """Process events for QThreadPool signals without blocking."""
    # Processes events for up to 100ms
    # Allows QRunnable signals to propagate from worker threads
    # Calls QCoreApplication.sendPostedEvents() for deferred deletions
```

### Best Practices for Qt Widget Tests
- **DON'T** call `widget.show()` in tests - it's not needed
- **DO** use `qtbot.addWidget(widget)` for proper lifecycle management
- **DON'T** use `QMessageBox` directly - it's automatically mocked
- **DO** trust that widgets are testable without being visible

### Testing Widget Visibility
```python
# CORRECT - Test visibility state without showing
widget = MyWidget()
qtbot.addWidget(widget)  # Manages lifecycle
assert not widget.isVisible()  # Initially hidden
widget.setVisible(True)  # Set state without actual popup
assert widget.isVisible()  # State changed

# WRONG - Attempting to show actual window
widget = MyWidget()
widget.show()  # Don't do this - automatically prevented anyway
```

## Test Isolation and Parallel Execution (CRITICAL)

### The Golden Rule: Tests Must Be Completely Independent

**Every test must be runnable**:
- Alone (in isolation)
- In any order
- On any worker (in parallel)
- Multiple times consecutively

### Common Root Causes of Isolation Failures

#### 1. Qt Resource Leaks

**Problem**: QTimer, QThread, or other Qt objects continue running after test
**Symptom**: Tests pass individually, fail intermittently in parallel
**Fix**: Use try/finally blocks with explicit cleanup

```python
# ❌ WRONG - timer may leak if test fails
def test_qt_timer(qtbot):
    timer = QTimer()
    timer.start(50)
    qtbot.waitUntil(lambda: condition, timeout=500)
    timer.stop()  # Never reached if waitUntil raises

# ✅ RIGHT - timer always cleaned up
def test_qt_timer(qtbot):
    timer = QTimer(parent_object)  # Parent for Qt ownership
    timer.start(50)

    try:
        qtbot.waitUntil(lambda: condition, timeout=500)
        assert condition
    finally:
        timer.stop()
        timer.deleteLater()  # Explicit deletion
```

#### 2. Global/Module-Level State

**Problem**: Class attributes or module globals modified by parallel tests
**Symptom**: Tests see unexpected values from other tests
**Fix**: Use monkeypatch to isolate state

```python
# ❌ WRONG - Config.SHOWS_ROOT is shared globally
def test_path_parsing():
    # Other parallel tests may have modified Config.SHOWS_ROOT
    path = f"{Config.SHOWS_ROOT}/gator/shots"

# ✅ RIGHT - monkeypatch isolates this test's view
def test_path_parsing(monkeypatch):
    original_shows_root = Config.SHOWS_ROOT
    monkeypatch.setattr("config.Config.SHOWS_ROOT", original_shows_root)
    path = f"{Config.SHOWS_ROOT}/gator/shots"
```

**Common sources of shared state**:
- `Config.SHOWS_ROOT` - used by many tests
- Module-level caches in `utils.py`
- Class attributes on singletons
- Qt application settings

#### 3. Module-Level Caches

**Problem**: Cached values from previous tests contaminate current test
**Symptom**: Tests fail in parallel but pass individually, especially after certain other tests
**Fix**: Clear caches FIRST, before any other operations

```python
# ❌ WRONG - cache cleared after contamination possible
def test_thumbnail_path(tmp_path, monkeypatch):
    shows_root = tmp_path / "shows"
    shot_path = shows_root / "test_show" / "shots"
    shot_path.mkdir(parents=True)

    from utils import clear_all_caches
    clear_all_caches()  # Too late - already imported with cached values

# ✅ RIGHT - cache cleared BEFORE operations
def test_thumbnail_path(tmp_path, monkeypatch):
    from utils import clear_all_caches
    clear_all_caches()  # FIRST operation

    # NOW safe to create paths and use them
    shows_root = tmp_path / "shows"
    shot_path = shows_root / "test_show" / "shots"
```

### The xdist_group Anti-Pattern

**What it does**: Forces tests with same group marker onto same worker
**When to use it**: Almost never
**Why it fails**: Serialization doesn't equal isolation

```python
# ❌ WRONG - using xdist_group as a band-aid
@pytest.mark.xdist_group("qt_state")
def test_with_leak():
    timer = QTimer()
    timer.start()  # Leaks into next test in group

# ✅ RIGHT - fix the leak, remove the marker
def test_with_proper_cleanup():
    timer = QTimer()
    timer.start()
    try:
        # test code
    finally:
        timer.stop()
        timer.deleteLater()
```

**The xdist_group trap**:
1. Test fails in parallel → add xdist_group
2. Failure becomes intermittent (still happens, just less often)
3. Root cause (leak/shared state) remains unfixed
4. Tests grouped together contaminate each other
5. Failures are harder to debug (only happen after certain other tests)

**When xdist_group is actually appropriate** (rare):
- Tests that *must* run serially due to external constraints (single hardware device, license server, etc.)
- NOT for fixing Qt state issues (fix the state management instead)
- NOT for shared filesystem issues (use tmp_path instead)
- NOT for timing issues (fix the timing, don't serialize)

## Common Issues and Solutions

### Issue: Tests Pass Individually but Fail in Parallel
**Cause**: Test isolation problems - tests share state
**Solution**:
1. Run test with `-vv` to see exact failure
2. Check for global state (Config attributes, module caches)
3. Check for Qt resource leaks (QTimer, QThread not cleaned up)
4. Check for module-level state (utils.py caches, singletons)
5. Fix the isolation problem, DON'T add xdist_group

### Issue: AttributeError with Mock Objects
**Cause**: Mock missing required attributes
**Solution**: Ensure mocks include all class-level attributes:
```python
MockProcessPoolManagerClass = type(
    "MockProcessPoolManager",
    (),
    {
        "_instance": None,
        "_lock": QMutex(),
        "_initialized": False,  # Don't forget class attributes!
        "get_instance": staticmethod(lambda: test_pool),
    },
)
```

### Issue: Qt Tests Intermittently Failing
**Cause**: Qt resources not properly cleaned up
**Solution**: Use try/finally blocks and explicit deleteLater() calls:
```python
timer = QTimer(parent)
try:
    # test code
finally:
    timer.stop()
    timer.deleteLater()
```

### Issue: Tests Testing Non-Existent Methods
**Cause**: Tests written for different implementation
**Solution**: Skip or rewrite to match actual code:
```python
def test_old_implementation(self):
    """Test for old widget-based implementation."""
    pytest.skip("ThreeDEGridView uses Model/View architecture")
```

### Issue: Cache Contamination
**Cause**: Module-level caches not cleared before test
**Solution**: Clear caches as FIRST operation:
```python
def test_with_cache(tmp_path):
    from utils import clear_all_caches
    clear_all_caches()  # First line after imports
    # Now safe to use cached functions
```

## Synchronization Helper Reference

Available in `tests/helpers/synchronization.py`:

```python
# Simulate work without blocking
simulate_work_without_sleep(duration_ms: int)

# Wait for condition with timeout
wait_for_condition(
    condition: Callable[[], bool],
    timeout_ms: int = 1000,
    poll_interval_ms: int = 10
) -> bool

# Process Qt events safely
process_qt_events(app: QApplication, duration_ms: int = 10)

# Wait for Qt signal
wait_for_qt_signal(
    qtbot,
    signal,
    timeout: int = 1000,
    raising: bool = True
)
```

## Configuration

### pytest.ini Settings
```ini
[pytest]
addopts =
    # Enable parallel by default
    -n auto

    # Use loadgroup distribution for marked tests
    --dist=loadgroup

    # Show test durations
    --durations=20

    # Stop after 5 failures
    --maxfail=5
```

To disable parallel execution temporarily:
```bash
# Command line override
~/.local/bin/uv run pytest -p no:xdist

# Or edit pytest.ini and comment out:
# -n auto
# --dist=loadgroup
```

## Best Practices Summary

1. **Always use synchronization helpers** instead of sleep/processEvents
2. **Fix isolation issues, DON'T use xdist_group** as a band-aid
3. **Test actual implementation**, not imagined interfaces
4. **Skip broken tests** with clear explanations rather than leaving them failing
5. **Run tests frequently** during development to catch issues early
6. **Use parallel execution** for faster feedback, serial for debugging
7. **Keep tests isolated** - no shared state between tests
8. **Fix the root cause** - don't patch over test failures
9. **Use try/finally for Qt resources** - ensure cleanup always happens
10. **Isolate global state with monkeypatch** - protect from parallel test contamination
11. **Clear caches FIRST** - before any operations that might use them

## Maintenance Guidelines

### When Adding New Tests
1. Check if testing actual implementation
2. Add appropriate markers (qt, unit, slow, etc.)
3. Use synchronization helpers for timing
4. Ensure test isolation
5. Run both serial and parallel to verify

### When Tests Fail
1. Run individually to check for isolation issues
2. Check for global state contamination (Config, module caches)
3. Check for Qt resource leaks (QTimer, QThread)
4. Verify testing actual implementation
5. Look for anti-patterns (sleep, processEvents)
6. Fix the isolation problem - DON'T add xdist_group

### When Refactoring Code
1. Update tests to match new implementation
2. Skip obsolete tests with explanations
3. Don't test implementation details
4. Focus on behavior, not structure

---

**Last Updated**: 2025-10-31
**Comprehensive test suite with best practices for parallel execution and Qt testing**

## Recent Updates (2025-10-31)

### Test Isolation Fixes
Fixed three flaky tests that were failing intermittently in parallel execution:
1. **test_timer_based_refresh_integration**: Added try/finally for QTimer cleanup
2. **test_show_root_path_extraction_no_double_slash**: Added monkeypatch for Config.SHOWS_ROOT isolation
3. **test_get_thumbnail_path_with_real_files**: Moved cache clearing to first operation

**Key Learnings**:
- `xdist_group` markers were masking problems, not solving them
- Removing `xdist_group` and fixing root causes made tests more stable
- Tests now run successfully 100% of the time in parallel (verified with 5 consecutive runs)
- All 1,975 tests pass consistently with `pytest -n auto`

**See Also**: "Test Isolation and Parallel Execution (CRITICAL)" section above for detailed patterns and anti-patterns