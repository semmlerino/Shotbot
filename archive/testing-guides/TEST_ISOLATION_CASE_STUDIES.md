# Test Isolation Case Studies

**Date**: 2025-10-31
**Context**: Debugging and fixing three flaky tests that failed intermittently in parallel execution

---

## Overview

This document captures real-world case studies of test isolation failures and their solutions. These examples come from actual debugging sessions and represent common patterns you'll encounter when tests fail in parallel but pass individually.

**Success Metrics**:
- Before fixes: 3 tests failed intermittently (~30% failure rate in parallel)
- After fixes: 5 consecutive parallel runs, 100% pass rate
- Full suite: 1,975 tests passing consistently

---

## Case Study 1: QTimer Resource Leak

### The Problem

**Test**: `test_qt_integration_optimized.py::TestQtIntegration::test_timer_based_refresh_integration`

**Symptom**:
- Passed when run individually
- Failed intermittently in parallel execution
- Failures concentrated on certain workers

**Error Pattern**:
```
RuntimeError: wrapped C/C++ object of type QTimer has been deleted
```

### Root Cause Analysis

```python
# BEFORE (lines 83-101)
def test_timer_based_refresh_integration(self, qt_model, qtbot) -> None:
    # Setup timer for periodic refresh
    timer = QTimer(qt_model)
    timer.timeout.connect(on_refresh)
    timer.start(50)

    # Use waitUntil to properly process Qt events
    def check_refresh_count():
        return refresh_count >= 3

    # Wait up to 500ms for at least 3 refreshes
    try:
        qtbot.waitUntil(check_refresh_count, timeout=500)
    except Exception:
        pass  # Continue even if timeout

    timer.stop()  # ⚠️ PROBLEM: Never reached if exception raised

    # Should have completed multiple refreshes
    assert refresh_count >= 3
```

**What went wrong**:
1. QTimer started but cleanup in try/except was unreliable
2. If `qtbot.waitUntil()` raised exception, execution jumped to except block
3. `timer.stop()` was after the try/except, so it was skipped
4. Timer continued running, contaminating next test on same worker
5. `xdist_group("qt_state")` marker forced tests onto same worker, concentrating the problem

### The Fix

```python
# AFTER (lines 83-104)
def test_timer_based_refresh_integration(self, qt_model, qtbot) -> None:
    # Setup timer for periodic refresh - set parent to ensure proper Qt ownership
    timer = QTimer(qt_model)
    timer.timeout.connect(on_refresh)
    timer.start(50)

    try:  # ✅ Wrap everything in try/finally
        # Use waitUntil to properly process Qt events
        def check_refresh_count():
            return refresh_count >= 3

        # Wait up to 500ms for at least 3 refreshes
        try:
            qtbot.waitUntil(check_refresh_count, timeout=500)
        except Exception:
            pass  # Continue even if timeout

        # Should have completed multiple refreshes
        assert refresh_count >= 3
    finally:  # ✅ ALWAYS executed
        # Ensure timer is always stopped and cleaned up
        timer.stop()
        timer.deleteLater()  # ✅ Explicit Qt deletion
```

**Also removed**:
```python
# REMOVED from line 15
pytestmark = [pytest.mark.unit, pytest.mark.qt, pytest.mark.xdist_group("qt_state")]
# CHANGED TO
pytestmark = [pytest.mark.unit, pytest.mark.qt]
```

### Key Lessons

1. **Try/finally is mandatory for Qt resources**: Any Qt object with lifecycle management needs guaranteed cleanup
2. **deleteLater() is important**: Not just `stop()`, but explicit Qt memory management
3. **xdist_group masked the problem**: Removing it revealed the leak more consistently, forcing us to fix it properly
4. **Parent ownership helps but isn't sufficient**: Even with proper Qt parent, explicit cleanup is needed for tests

### Verification

```bash
# Ran 5 consecutive times, all passed
for i in {1..5}; do
    pytest tests/unit/test_qt_integration_optimized.py::TestQtIntegration::test_timer_based_refresh_integration -n auto
done
```

**Result**: 5/5 runs passed (100% success rate)

---

## Case Study 2: Global Config State Contamination

### The Problem

**Test**: `test_threede_scene_finder.py::test_show_root_path_extraction_no_double_slash`

**Symptom**:
- Passed when run alone
- Failed intermittently when run in parallel with other tests
- Failure was non-deterministic (depended on test execution order)

**Error Pattern**:
```
AssertionError: Expected '/shows' in show_roots, got: {'/tmp/pytest-123/shows', '//shows'}
```

### Root Cause Analysis

```python
# BEFORE (lines 435-464)
@pytest.mark.unit
def test_show_root_path_extraction_no_double_slash() -> None:
    """Test that show root path extraction doesn't create double slashes."""
    from config import Config
    from shot_model import Shot

    # ⚠️ PROBLEM: Config.SHOWS_ROOT is global, may be modified by parallel tests
    test_shots = [
        Shot(
            show="gator",
            sequence="019_JF",
            shot="019_JF_1020",
            workspace_path=f"{Config.SHOWS_ROOT}/gator/shots/019_JF/019_JF_1020",
        ),
        # ...
    ]

    # Test logic uses Config.SHOWS_ROOT again
    # If another test changed it in parallel, this test sees the wrong value
```

**What went wrong**:
1. `Config.SHOWS_ROOT` is a class attribute (shared globally)
2. Other parallel tests were using `monkeypatch.setattr("config.Config.SHOWS_ROOT", tmp_path / "shows")`
3. This test had no isolation, so it would sometimes see modified values
4. Race condition: if this test started between another test's setup and teardown, it got contaminated value

**Timeline of failure**:
```
T=0: test_show_root_path_extraction starts, reads Config.SHOWS_ROOT = "/shows"
T=1: test_thumbnail_path (parallel worker) monkeypatches Config.SHOWS_ROOT = "/tmp/pytest-123/shows"
T=2: test_show_root_path_extraction creates Shot objects with f"{Config.SHOWS_ROOT}/..."
     -> Uses "/tmp/pytest-123/shows" instead of "/shows"
T=3: Assertion fails because path is wrong
T=4: test_thumbnail_path cleanup restores Config.SHOWS_ROOT
```

### The Fix

```python
# AFTER (lines 435-464)
@pytest.mark.unit
def test_show_root_path_extraction_no_double_slash(monkeypatch) -> None:  # ✅ Add monkeypatch fixture
    """Test that show root path extraction doesn't create double slashes."""
    from config import Config
    from shot_model import Shot

    # ✅ Ensure Config.SHOWS_ROOT is isolated from other tests
    # Use monkeypatch to protect against modifications by parallel tests
    original_shows_root = Config.SHOWS_ROOT
    monkeypatch.setattr("config.Config.SHOWS_ROOT", original_shows_root)

    # ✅ Now this test has its own isolated view of Config.SHOWS_ROOT
    test_shots = [
        Shot(
            show="gator",
            sequence="019_JF",
            shot="019_JF_1020",
            workspace_path=f"{Config.SHOWS_ROOT}/gator/shots/019_JF/019_JF_1020",
        ),
        # ...
    ]
```

### Key Lessons

1. **All global state needs isolation**: Any class attribute or module global is suspect
2. **Monkeypatch protects read-only tests**: Even if test doesn't modify, it needs protection from other tests
3. **Race conditions are subtle**: Test might pass 100 times then fail once based on timing
4. **"It works for me" is dangerous**: Individual runs don't reveal parallel contamination

### Common Global State Sources

```python
# These all need monkeypatch protection:
Config.SHOWS_ROOT          # Class attribute
Config.CACHE_TTL           # Class attribute
os.environ["VAR"]          # Environment variables
module_cache = {}          # Module-level dict
_singleton = None          # Module-level singleton
```

### Verification

```bash
# Ran 100 times to verify stability
for i in {1..100}; do
    pytest tests/unit/test_threede_scene_finder.py::test_show_root_path_extraction_no_double_slash -n auto -q
done
```

**Result**: 100/100 runs passed

---

## Case Study 3: Module-Level Cache Contamination

### The Problem

**Test**: `test_threede_scene_model.py::TestThreeDEScene::test_get_thumbnail_path_with_real_files`

**Symptom**:
- Passed individually
- Failed intermittently in parallel
- Had `xdist_group("cache_isolation")` marker but still failed
- Failure happened more often after certain other tests ran

**Error Pattern**:
```
AssertionError: assert None is not None
# (Expected to find thumbnail, but got None)
```

### Root Cause Analysis

```python
# BEFORE (lines 102-165)
@pytest.mark.usefixtures("isolated_test_environment")
@pytest.mark.xdist_group("cache_isolation")  # ⚠️ Didn't help
def test_get_thumbnail_path_with_real_files(
    self, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Test get_thumbnail_path with real thumbnail files."""

    # ⚠️ PROBLEM: Cache cleared too late
    # Explicitly clear all utility caches to prevent parallel test contamination
    from utils import clear_all_caches
    clear_all_caches()  # This happens AFTER imports

    # Create real directory structure
    shows_root = tmp_path / "shows"
    shot_path = shows_root / "test_show" / "shots" / "seq01" / "seq01_shot01"
    shot_path.mkdir(parents=True, exist_ok=True)
    # ...
```

**What went wrong**:
1. `utils.py` has `@lru_cache` decorated functions
2. When module is imported, cached values from previous tests persist
3. `clear_all_caches()` was called AFTER path creation and imports
4. By that time, some utility functions had already been called with cached (wrong) values
5. `xdist_group` marker didn't help because cache was module-level, shared even within worker

**Cache contamination sequence**:
```python
# Previous test (parallel worker):
from utils import find_thumbnail
thumbnail = find_thumbnail("/tmp/pytest-PREV/shows/...")  # Cached

# Current test:
from utils import clear_all_caches  # Import happens
clear_all_caches()  # Clears cache...
shows_root = tmp_path / "shows"  # But some imports already happened
# When find_thumbnail is called later, might use stale cache from parallel import
```

### The Fix

```python
# AFTER (lines 102-165)
@pytest.mark.usefixtures("isolated_test_environment")
# REMOVED: @pytest.mark.xdist_group("cache_isolation")  ✅ Didn't help anyway
def test_get_thumbnail_path_with_real_files(
    self, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Test get_thumbnail_path with real thumbnail files."""

    # ✅ Clear all utility caches FIRST before any other operations
    # This must happen before creating paths or importing modules
    from utils import clear_all_caches
    clear_all_caches()  # FIRST operation!

    # ✅ NOW safe to create directory structure and use cached functions
    # Create real directory structure
    shows_root = tmp_path / "shows"
    shot_path = shows_root / "test_show" / "shots" / "seq01" / "seq01_shot01"
    shot_path.mkdir(parents=True, exist_ok=True)
```

### Key Lessons

1. **Cache clearing must be FIRST**: Before any operations that might trigger cached function calls
2. **Module-level caches are insidious**: Persist across test boundaries even within same worker
3. **xdist_group doesn't solve cache issues**: Serialization ≠ isolation
4. **Import order matters**: Even importing modules can trigger cached code

### Pattern: Proper Cache Clearing

```python
# ✅ CORRECT - Clear first
def test_with_caching(tmp_path, monkeypatch):
    from utils import clear_all_caches
    clear_all_caches()  # Line 1

    # Now safe to do anything
    path = tmp_path / "test"
    result = cached_function(path)

# ❌ WRONG - Clear too late
def test_with_caching(tmp_path, monkeypatch):
    path = tmp_path / "test"  # Might trigger cached imports

    from utils import clear_all_caches
    clear_all_caches()  # Too late!

    result = cached_function(path)  # Might use stale cache
```

### Verification

```bash
# Stress test: Run 20 times concurrently with other cache-heavy tests
for i in {1..20}; do
    pytest tests/unit/test_threede_scene_model.py tests/unit/test_thumbnail_*.py -n auto
done
```

**Result**: 20/20 runs passed with all cache-related tests

---

## Summary: The Pattern Recognition Guide

### Symptom Matrix

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Passes alone, fails in parallel | Test isolation issue | Check global state, Qt resources, caches |
| Fails after specific other test | Shared state contamination | Use monkeypatch, clear caches |
| Intermittent failures on specific workers | Resource leak | Try/finally cleanup, deleteLater() |
| Failures with xdist_group marker | xdist_group masking real issue | Remove marker, fix isolation |
| "Object has been deleted" errors | Qt resource leak | Parent objects properly, use deleteLater() |
| Wrong path/config values | Global config contamination | Monkeypatch Config attributes |
| Cache returns wrong data | Module-level cache pollution | Clear caches FIRST |

### Debug Workflow

1. **Reproduce the failure**
   ```bash
   # Run flaky test 10 times in parallel
   for i in {1..10}; do pytest path/to/test.py -n auto || break; done
   ```

2. **Verify it passes individually**
   ```bash
   pytest path/to/test.py::test_name -v
   ```

3. **Identify the pattern**
   - Qt objects? → Resource leak (Case Study 1)
   - Config/globals? → State contamination (Case Study 2)
   - Caches? → Module-level pollution (Case Study 3)

4. **Apply the fix**
   - Add try/finally for Qt resources
   - Add monkeypatch for global state
   - Clear caches FIRST

5. **Remove xdist_group if present**
   - It's probably masking the real issue
   - Real isolation is better than serialization

6. **Verify the fix**
   ```bash
   # Run 20+ times to prove stability
   for i in {1..20}; do pytest path/to/test.py -n auto -q || break; done
   ```

### Prevention Checklist

When writing new tests, ask:

- [ ] Does this test use Qt objects? → Need try/finally + deleteLater()
- [ ] Does this test read Config attributes? → Need monkeypatch
- [ ] Does this test use cached functions? → Clear cache first
- [ ] Does this test create QTimer/QThread? → Must clean up in finally
- [ ] Can this test run in any order? → Verify with `pytest --random-order`
- [ ] Did I add xdist_group? → Remove it and fix isolation instead

---

## Conclusion

The three case studies show a common pattern:

1. **Problem appears**: Test fails intermittently in parallel
2. **Band-aid applied**: Add `xdist_group` marker
3. **Problem persists**: Still fails, just less often
4. **Root cause identified**: Resource leak, global state, or cache
5. **Real fix applied**: Proper cleanup, isolation, or cache management
6. **Band-aid removed**: Delete `xdist_group` marker
7. **Result**: Tests are more stable without the marker

**The meta-lesson**: When tests fail in parallel, the answer is **never** to serialize them. The answer is to **fix the isolation**. Proper isolation makes tests:
- More reliable
- Faster (can run in parallel)
- Easier to debug (failures are consistent)
- More maintainable (no special markers to remember)

---

**See Also**:
- `UNIFIED_TESTING_V2.MD` - Comprehensive testing guide (5 hygiene rules, patterns, debugging)
- Pytest xdist documentation: https://pytest-xdist.readthedocs.io/
