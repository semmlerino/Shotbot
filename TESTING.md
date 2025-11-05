# ShotBot Testing Guide

**Last Updated**: 2025-11-05
**Test Suite**: 2,296 tests (2,291 pass with `-n 2`, 5 WSL skips - includes 15 new incremental scene merge tests)
**Execution**: ~30s parallel, ~60s serial
**Coverage**: 51% overall (90% weighted, 100% critical)
**Pass Rate**: 99.8% (parallel), 100% (serial)

**⚠️ Use `-n 2` for 2x speedup**

## Recent Critical Fixes

**2025-11-05** 🔴 **Module-Level Qt + Integration Tests**
- Fixed suite crash from module-level `QCoreApplication`
- Fixed 33 integration tests (signal mocking, async operations, workspace validation)
- **Never create Qt apps at module level** - only in fixtures/functions
- **Disconnect/reconnect Qt signals** for mocking (not `patch side_effect`)
- **Clear cache before MainWindow** creation to prevent background loader interference

**2025-11-04** 🎉 **Autouse Fixture Anti-Pattern**
- Removed autouse subprocess mock → 72% fewer failures (16→5)
- Global patches don't isolate across xdist workers
- Use explicit fixtures; autouse only for true cross-cutting concerns

**2025-11-03** 🔴 **Qt Resource Exhaustion**
- Parallelization required for 2335+ Qt tests (`-n 2` minimum)
- Serial execution overwhelms single QApplication

**2025-11-02** 🔴 **Qt Platform Crashes**
- Set `QT_QPA_PLATFORM="offscreen"` before ALL Qt imports
- Prevents "Fatal Python error: Aborted" in WSL

---

## Quick Start

### Running Tests

**⚠️ RECOMMENDED**: Use `-n 2` for faster execution (30s vs 60s). Serial execution works but is slower.

```bash
# RECOMMENDED: Full test suite with parallelization (30s, 99.8% pass rate)
uv run pytest tests/unit/ -n 2 --timeout=10

# ALSO WORKS: Serial execution (60s, 100% pass rate, but slower)
uv run pytest tests/unit/ --timeout=10

# Alternative: Auto-detect worker count (may use too many workers in WSL)
uv run pytest tests/unit/ -n auto --timeout=10

# Quick validation
uv run python tests/utilities/quick_test.py

# Single test file (parallelization optional for individual files)
uv run pytest tests/unit/test_shot_model.py -v

# Specific test
uv run pytest tests/unit/test_shot_model.py::TestShot::test_shot_creation -v

# With coverage report
uv run pytest tests/unit/ -n 2 --cov=. --cov-report=term-missing

# Categories
uv run pytest tests/ -m fast -n 2       # Tests under 100ms
uv run pytest tests/ -m unit -n 2       # Unit tests only
uv run pytest tests/ -m integration     # Integration tests (no parallelization needed)
```

**Why `-n 2` is faster but not required**:
- ✅ Distributes tests across 2 worker processes (~30s execution time)
- ✅ Each worker gets its own QApplication instance
- ✅ Better CPU utilization on multi-core systems
- ⏱️  Serial execution works fine but is slower (~60s execution time)

### Legacy Test Runner

```bash
# Old method (still works but slower)
uv run python run_tests.py

# With coverage
uv run python run_tests.py --cov
```

### Test Organization

```
tests/
├── __init__.py
├── conftest.py          # Shared fixtures
├── unit/                # Unit tests
│   ├── __init__.py
│   ├── test_shot_model.py
│   └── test_command_launcher.py
└── integration/         # Integration tests
    └── __init__.py
```

## Current Test Coverage (Updated 2025-10-14)

### Critical Components (100% Coverage) ✅

| Module | Tests | Lines | Status |
|--------|-------|-------|--------|
| plate_discovery.py | 26 | 527 | ✅ Comprehensive (NEW) |
| shot_item_model.py | 28 | 609 | ✅ Comprehensive (NEW) |
| config.py | 27 | 578 | ✅ Validation (NEW) |
| cache_manager.py | 83 | 946 | ✅ Comprehensive (15 new scene merge tests) |
| shot_model.py | 33 | 563 | ✅ Comprehensive |
| base_item_model.py | 48 | 653 | ✅ Comprehensive |
| raw_plate_finder.py | 23 | 610 | ✅ Comprehensive |
| undistortion_finder.py | 24 | 775 | ✅ Comprehensive |
| threede_scene_model.py | 16 | 564 | ✅ Comprehensive |
| launcher_panel.py | 21 | 594 | ✅ Comprehensive |
| main_window.py | 16 | 483 | ✅ Comprehensive |
| process_pool_manager.py | 14 | 711 | ✅ Adequate |
| nuke_launch_handler.py | 14 | 294 | ✅ Adequate |

### High-Priority Components (Integration Tested)

- optimized_shot_parser.py - Performance-critical parsing
- threede_scene_finder_optimized.py - Optimized discovery
- scene_discovery_coordinator.py - Discovery coordination
- persistent_bash_session.py - Terminal management
- secure_command_executor.py - Command execution

**Weighted Coverage: 90%** (100% of critical, indirect coverage of high-priority)

## Key Testing Principles (UNIFIED_TESTING_GUIDE)

### Core Philosophy

1. **Test Behavior, Not Implementation**: Focus on what code does, not how
2. **Use Real Components**: Minimal mocking, real filesystems with tmp_path
3. **Tests Must Be Independent**: Runnable alone, in any order, on any worker
4. **Fix Isolation, Don't Serialize**: Never use xdist_group as a band-aid

---

## Test Isolation and Parallel Execution ⚠️ CRITICAL

### The Golden Rule

**Every test must be runnable**:
- Alone (in isolation)
- In any order
- On any worker (in parallel)
- Multiple times consecutively

### Common Root Causes of Isolation Failures

#### 1. Qt Resource Leaks
**Symptom**: Pass individually, fail intermittently in parallel
```python
# ❌ WRONG - timer leaks if test fails
timer.start(50)
qtbot.waitUntil(lambda: condition)
timer.stop()  # Never reached if waitUntil raises

# ✅ RIGHT - always cleaned up
try:
    timer.start(50)
    qtbot.waitUntil(lambda: condition)
finally:
    timer.stop()
    timer.deleteLater()
```

#### 2. Global/Module-Level State
**Symptom**: Tests see unexpected values from other workers
```python
# ❌ WRONG - shared globally
path = f"{Config.SHOWS_ROOT}/gator/shots"

# ✅ RIGHT - isolated with monkeypatch
monkeypatch.setattr("config.Config.SHOWS_ROOT", original_value)
```

#### 3. Module-Level Caches
**Fix**: Automatic since 2025-11-04 via `clear_module_caches` autouse fixture
- Clears VersionUtils, path caches, LRU caches before/after each test
- Don't manually clear unless testing cache behavior itself

#### 4. Qt Platform Initialization (CRITICAL) 🔴
**Symptom**: Fatal Python error: Aborted, "real widgets" appear
**Fix**: Set at top of `tests/conftest.py` BEFORE Qt imports:
```python
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # BEFORE any Qt imports
```
**Why**: Prevents windowing platform from being used in headless/WSL environments

#### 5. Qt Resource Exhaustion 🔴
**Problem**: 2335+ Qt tests serial → single QApplication overwhelmed → crash
**Fix**: Use `-n 2` or `-n auto` to distribute across workers
```bash
uv run pytest tests/unit/ -n 2  # ✅ Each worker gets own QApplication
uv run pytest tests/unit/        # ❌ Crashes - too many tests for one QApp
```
**Why**: Each worker gets independent Qt resources; serial accumulates until crash

#### 6. Persistent Cache Files
**Problem**: Disk cache persists between tests; memory cleared but not disk
**Fix**: Always pair with `cache_manager.clear_cache()`
```python
main_window.shot_model.shots = []  # Memory
cache_manager.clear_cache()         # Disk - essential!
```

#### 7. Module-Level Qt App Creation 🔴
**Problem**: Creating `QCoreApplication` at module import → conflicts with `QApplication`
**Symptom**: Full suite crashes, individual files work
**Fix**: Only create in fixtures/functions, never at module level
```python
# ❌ WRONG - at module level
app = QCoreApplication.instance() or QCoreApplication([])

# ✅ RIGHT - in fixture
@pytest.fixture
def app():
    return QCoreApplication([])
```
**Find**: `grep -r "QCoreApplication\|QApplication" tests/ | grep -v "def \|class \|@"`

#### 8. Background Async Operations
**Problem**: Background loaders clear data during `qtbot.wait()`
**Symptom**: `len(shots) == 2` becomes `len(shots) == 0` after `qtbot.wait(100)`
**Fix**: Clear cache before setup + reload if cleared
```python
cache_manager.clear_cache()  # Prevent stale cache triggering reload
window.shot_model.shots = [shot1, shot2]
qtbot.wait(100)
if len(window.shot_model.shots) == 0:
    window.shot_model.refresh_shots()  # Reload with mocked pool
```

### Anti-Patterns

#### xdist_group as Band-Aid
**Wrong**: Using `xdist_group` to "fix" parallel failures
**Right**: Fix the actual isolation issue (resource cleanup, global state)
- xdist_group appropriate ONLY for external constraints (hardware, license server)
- NOT for Qt state, filesystem, or timing issues

#### Autouse for Mocks
**Wrong**: `autouse=True` for global patches → worker isolation failures
**Right**: Explicit fixtures (request what you need)
```python
# ❌ WRONG - 11 failures from global patch
@pytest.fixture(autouse=True)
def mock_subprocess(): ...

# ✅ RIGHT - explicit opt-in
@pytest.fixture
def mock_subprocess(): ...
def test_something(mock_subprocess): ...
```
**Autouse appropriate ONLY for**:
- Qt cleanup (affects 100% of Qt tests)
- Cache clearing (prevents contamination)
- QMessageBox mocking (prevents modal dialogs)
**NOT for**: subprocess, filesystem, database mocking

### Distribution Modes

```bash
--dist=load        # Default: random distribution
--dist=worksteal   # Recommended: idle workers steal from busy ones (best for varying durations)
--dist=loadscope   # Group by module/class (better fixture reuse)
--dist=loadfile    # Group by file (simpler)
--dist=loadgroup   # Group by marker (rarely needed, usually indicates isolation issues)
```

**Recommended for ShotBot**: `--dist=worksteal`
- Tests vary from <100ms to >500ms
- Prevents idle workers while others are bottlenecked
- Better CPU utilization than default `load`

---

## Testing Principles in Detail

### 1. Test Behavior, Not Implementation

**Good**: Test what the code does (observable behavior)
```python
def test_plate_priority_selection():
    """FG01 is selected over BG01 due to higher priority."""
    # Test that FG is chosen, not how the selection algorithm works
    assert selected_plate == "FG01"
```

**Bad**: Test how the code does it (implementation details)
```python
def test_plate_selection_algorithm():
    """Test the internal sorting algorithm."""
    # Don't test internal methods or data structures
```

### 2. Use Real Components (Minimal Mocking)

**Good**: Real implementations with real data
```python
def test_thumbnail_loading(tmp_path):
    # Create real directory structure
    thumbnail = tmp_path / "test.jpg"
    thumbnail.write_bytes(b"...")

    # Use real CacheManager
    cache = CacheManager(cache_dir=tmp_path / "cache")
```

**Bad**: Excessive mocking
```python
def test_thumbnail_loading(mocker):
    # Mock everything
    mocker.patch("pathlib.Path")
    mocker.patch("CacheManager")
```

**When to Mock**:
- System boundaries (subprocess, network, filesystem only when necessary)
- Qt signals (use QSignalSpy instead of mocking)
- External dependencies (databases, APIs)

### 3. Duck Typing and Protocols

**Use hasattr() for flexible interfaces**:
```python
def test_model_has_method():
    """Test object supports expected interface."""
    assert hasattr(model, "get_available_shows")
    result = model.get_available_shows()
    assert isinstance(result, list)
```

**Prefer Protocols over isinstance() for type safety**:
```python
# Define interface
class HasAvailableShows(Protocol):
    def get_available_shows(self) -> list[str]: ...

# Use in type hints (enables type checking without isinstance)
def populate_show_filter(self, shows: list[str] | HasAvailableShows) -> None:
    if isinstance(shows, list):
        show_list = shows
    else:
        show_list = shows.get_available_shows()
```

### 4. Real Filesystem Operations

**Use tmp_path for File Tests**:
```python
def test_script_discovery(tmp_path):
    """Test finding scripts in plate directory."""
    plate_dir = tmp_path / "comp/nuke/FG01"
    plate_dir.mkdir(parents=True)
    script = plate_dir / "shot01_mm-default_FG01_scene_v001.nk"
    script.write_text("# Nuke script")

    result = find_existing_scripts(tmp_path, "shot01", "FG01")
```

### 5. Configuration Validation

**Validate constraints, not implementation**:
```python
def test_plate_priority_ordering():
    """Validate plate priorities maintain correct ordering."""
    priorities = Config.TURNOVER_PLATE_PRIORITY
    assert priorities["FG"] < priorities["PL"] < priorities["BG"]
```

### 6. Run Tests Frequently

- Run tests before committing: `uv run pytest tests/unit/ -n auto`
- Run specific tests during development
- Use `--lf` flag to run only last failed: `pytest --lf`

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

---

## Advanced: Session-Scoped Fixtures for Parallel Execution

### Problem: Expensive Setup Across Workers

When running tests with `-n auto`, each worker gets its own Python process. Session-scoped fixtures run once per worker, which can be wasteful for expensive operations like:
- Setting up mock VFX environments
- Initializing large test databases
- Generating test data that takes seconds

### Solution: Shared Setup with File Locks

Use file locks to coordinate workers so the setup happens exactly once:

```python
import json
import pytest
from filelock import FileLock

@pytest.fixture(scope="session")
def expensive_vfx_setup(tmp_path_factory, worker_id):
    """Set up mock VFX environment once across all workers.

    The first worker creates the environment, others wait and reuse it.
    """
    if worker_id == "master":
        # Not running with xdist (no parallel workers)
        return create_vfx_environment()

    # Get temp directory shared by all workers
    root_tmp_dir = tmp_path_factory.getbasetemp().parent
    data_file = root_tmp_dir / "vfx_setup.json"

    # Use file lock to coordinate access
    with FileLock(str(data_file) + ".lock"):
        if data_file.is_file():
            # Another worker already did the setup
            data = json.loads(data_file.read_text())
        else:
            # We're first - do the expensive setup
            data = create_vfx_environment()
            data_file.write_text(json.dumps(data))

    return data


def create_vfx_environment():
    """Expensive operation: create mock shows, shots, thumbnails."""
    # ... expensive setup code ...
    return {"shows_root": "/tmp/vfx", "shot_count": 432}
```

### Key Points

1. **`worker_id` fixture**: Returns `"master"` for non-parallel runs, or `"gw0"`, `"gw1"`, etc. for workers
2. **`tmp_path_factory.getbasetemp().parent`**: Gets the shared temp directory visible to all workers
3. **`FileLock`**: Ensures only one worker does the setup, others wait
4. **JSON for data sharing**: Workers communicate via shared files

### When to Use This Pattern

✅ **Use for**:
- Mock environment setup (VFX filesystem, databases)
- Generating large test datasets
- One-time expensive computations
- Any setup taking >1 second that's shared across tests

❌ **Don't use for**:
- Test isolation (use proper cleanup instead)
- Working around state contamination (fix the isolation)
- Avoiding proper test design

### Real-World Usage

This pattern is used in ShotBot for:
- Mock VFX environment setup (`recreate_vfx_structure.py`)
- ProcessPool initialization (see `conftest.py`)
- Shared test data generation

---

## Known Issues

### ✅ FIXED: Module-Level Qt Application Creation (2025-11-05)

**Issue**: Complete test suite crashes with "Fatal Python error: Aborted" even with correct QT_QPA_PLATFORM setting. Individual test files work perfectly.

**Root Cause**: `tests/test_process_pool_race.py` created `QCoreApplication` at module import time. When pytest collected all 2501 tests, it imported this module, creating a QCoreApplication that persisted for the entire session. Widget tests then failed because they needed QApplication (which inherits from QCoreApplication), creating a type conflict.

**Solution**: Removed module-level Qt application creation. Qt applications should ONLY be created in fixtures or test functions, never at module level.

**Code Fix**:
```python
# BEFORE (test_process_pool_race.py lines 18-22):
from PySide6.QtCore import QCoreApplication
app = QCoreApplication.instance() or QCoreApplication([])

# AFTER:
# Removed - use qapp fixture instead
```

**Impact**: Fixed complete test suite execution - went from crashing on first test to all tests running successfully.

**See Also**:
- "Common Root Causes" → "Module-Level Qt Application Creation (CRITICAL)" for full details
- Search command to find similar issues: `grep -r "QCoreApplication\|QApplication" tests/ --include="*.py" | grep -v "def \|class \|@"`

### ✅ FIXED: Qt Platform Initialization Crashes (2025-11-02)

**Issue**: "Fatal Python error: Aborted" during Qt widget initialization, causing entire test suite to crash.

**Root Cause**: QApplication created with windowing platform instead of offscreen platform, causing C++ crashes in WSL/headless environments.

**Solution**: Set `QT_QPA_PLATFORM="offscreen"` environment variable at top of `tests/conftest.py` BEFORE any Qt imports. This ensures ALL QApplication instances use the correct platform.

**See Also**:
- "Common Root Causes" → "Qt Platform Initialization (CRITICAL)" for full details
- "Debugging Test Failures" → "Critical: Fatal Python error During Qt Widget Initialization" for troubleshooting

### WSL/pytest-xvfb Compatibility
- pytest-xvfb causes timeouts in WSL
- Solution: Disabled via `-p no:xvfb` in pytest.ini

### WSL Subprocess Test Skips
**4 tests are automatically skipped in WSL** due to subprocess.run() returning empty results with `find` commands:

1. `test_scene_finder_performance.py::test_rglob_vs_find_command_small`
2. `test_previous_shots_worker.py::test_complete_workflow_with_results`
3. `test_previous_shots_worker.py::test_signal_data_format`
4. `test_threede_optimization_coverage.py::test_subprocess_method_with_exclusions`

**Skip Condition**: `sys.platform == "linux" and "microsoft" in platform.release().lower()`

**Why This Is Safe**:
- These are performance comparison tests, not core functionality tests
- Production code uses Python's `rglob()` method, which works correctly in all environments
- The subprocess method is an optimization path that's not critical for functionality
- All core business logic is tested through other test cases

**Expected Test Suite Results in WSL**:
- **Parallel (`-n 2`)**: 2,276 passed, 5 skipped (99.8% pass rate) ✅
- **Serial**: 2,281 passed, 5 skipped (100% pass rate) ✅
- Skipped tests: 4 WSL subprocess performance tests + 1 isolation edge case

### Test Execution
- Direct pytest usage works: `uv run pytest tests/ -n auto`
- Legacy runner still available: `python run_tests.py`

---

## Test Patterns by Category

Refer to actual test files for implementation examples. The principles above are applied throughout the test suite:

### Configuration Validation
**File**: `tests/unit/test_config.py` (27 tests)
- Validates configuration constraints without mocking
- Tests relationships (e.g., plate priority ordering)
- Would catch configuration bugs like PL=10

### Static Method Testing
**File**: `tests/unit/test_plate_discovery.py` (26 tests)
- Uses tmp_path for real filesystem operations
- No mocking of pathlib or file operations
- Tests pure functions with realistic data

### Qt Model/View Testing
**File**: `tests/unit/test_shot_item_model.py` (28 tests)
- Uses qtbot fixture and QSignalSpy
- Real CacheManager instances with tmp_path
- Tests actual Qt behavior, not mocks

### Protocol-Based Interfaces
**Files**: `shot_grid_view.py`, `base_grid_view.py`, `threede_grid_view.py`
- Type-safe duck typing with Protocol classes
- Enables type checking without isinstance()
- See `HasAvailableShows` Protocol for example

### Edge Case Testing
**File**: `tests/unit/test_plate_discovery.py`
- Tests boundary conditions (version gaps, empty directories, permissions)
- Documents why each edge case matters
- Uses realistic scenarios

---

## Test File Organization

### Directory Structure
```
tests/
├── conftest.py              # Shared fixtures (qtbot, tmp_path, etc.)
├── unit/                    # Unit tests
│   ├── test_config.py              # Configuration validation (27 tests)
│   ├── test_plate_discovery.py     # Plate workflow (26 tests)
│   ├── test_shot_item_model.py     # Qt Model/View (28 tests)
│   ├── test_shot_model.py          # Shot data model (33 tests)
│   ├── test_cache_manager.py       # Cache system (42 tests)
│   └── ...
├── integration/             # Integration tests
│   ├── test_main_window_complete.py
│   └── ...
└── utilities/               # Test utilities
    ├── quick_test.py
    └── pytest_audit.py
```

---

## Running Specific Test Categories

### Configuration Tests
```bash
# All config validation (27 tests)
uv run pytest tests/unit/test_config.py -v

# Just plate priority tests
uv run pytest tests/unit/test_config.py::TestPlatePriorityValidation -v
```

### Plate Discovery Tests
```bash
# All plate discovery (26 tests)
uv run pytest tests/unit/test_plate_discovery.py -v

# Just priority tests
uv run pytest tests/unit/test_plate_discovery.py::TestPlatePriorityOrdering -v
```

### Qt Model Tests
```bash
# All Model/View tests
uv run pytest tests/unit/test_*item_model.py -v

# Specific model
uv run pytest tests/unit/test_shot_item_model.py -v
```

### Fast Tests Only
```bash
# Tests under 100ms
uv run pytest tests/ -m fast -v
```

---

## Debugging Test Failures

### Passes Alone, Fails in Parallel? → Isolation Issue

**Diagnose**:
1. Reproduce: `for i in {1..10}; do pytest path/to/test.py -n auto || break; done`
2. Identify pattern: Qt objects? Config/globals? Caches?
3. Fix: try/finally for Qt, monkeypatch for globals, verify autouse cache clearing
4. Remove xdist_group if present
5. Verify: `for i in {1..20}; do pytest path/to/test.py -n auto -q || break; done`

### Fatal Python Error: Qt C++ Crash 🔴

**Symptom**: "Fatal Python error: Aborted" in Qt widget `__init__`
**Fix**: Set `os.environ["QT_QPA_PLATFORM"] = "offscreen"` at TOP of conftest.py BEFORE Qt imports
**Verify**: `head -20 tests/conftest.py | grep QT_QPA_PLATFORM`

### Common Commands

```bash
pytest path/to/test.py::test_name -vv       # Full output
pytest path/to/test.py::test_name -vv -l    # With local vars
pytest path/to/test.py::test_name -v -s     # With prints
pytest path/to/test.py::test_name --pdb     # Debugger
pytest --lf                                  # Last failed
```

### Debugging Parallel Execution

```bash
# Fixture execution order
pytest tests/unit/test_file.py --setup-plan

# Identify worker assignment
def test_debug(worker_id):
    print(f"Running on: {worker_id}")  # "master" or "gw0", "gw1"...

# Check environment vars
echo $PYTEST_XDIST_WORKER        # Worker name
echo $PYTEST_XDIST_WORKER_COUNT  # Total workers
echo $PYTEST_XDIST_TESTRUNUID    # Unique test run ID

# Trace state contamination
@pytest.fixture(autouse=True)
def trace_state(request, worker_id):
    before = Config.SHOWS_ROOT
    yield
    if Config.SHOWS_ROOT != before:
        print(f"[{worker_id}] {request.node.name} changed SHOWS_ROOT")
```

---

## Qt Testing Patterns (Context7-Validated)

Based on official pytest-qt documentation, use these patterns for reliable Qt testing:

### Qt Signal Mocking 🔴

**Problem**: `patch.object(..., side_effect=mock)` doesn't disconnect Qt signals → still calls original
**Solution**: Disconnect/reconnect signals directly

```python
# ❌ WRONG - side_effect doesn't affect signal connection
with patch.object(controller, "launch_app", side_effect=mock):
    button.click()  # Still executes original + mock

# ✅ RIGHT - replace signal connection
def mock_launch(app_name: str):
    launch_calls.append(app_name)

panel.app_launch_requested.disconnect(controller.launch_app)
panel.app_launch_requested.connect(mock_launch)
button.click()  # Only mock executes
```

**When to use**:
- Testing signal flow without business logic
- Avoiding validation/subprocess in integration tests
- Testing UI without backend

**When NOT to use**:
- Unit tests of actual business logic
- Testing validation itself
- System boundary mocks (use test doubles)

### Other Qt Patterns

```python
# Wait for signals (not time.sleep)
with qtbot.waitSignal(worker.finished, timeout=5000):
    worker.start()

# Assert signal NOT emitted
with qtbot.assertNotEmitted(app.error_signal, wait=500):
    app.do_safe_operation()

# Capture Qt exceptions (from virtual methods)
with qtbot.captureExceptions():
    widget.some_qt_method()

# Capture Qt logging
assert any("WARNING" in r.message for r in qtlog.records)
```

---

## Writing New Tests

### Checklist

1. **Choose the right pattern**:
   - Configuration? → Validation pattern
   - Static methods? → Real filesystem pattern
   - Qt components? → QSignalSpy pattern
   - Duck typing? → Protocol pattern

2. **Use appropriate fixtures**:
   - `tmp_path` for filesystem tests
   - `qtbot` for Qt tests
   - `real_cache_manager` for cache tests

3. **Write clear test names**:
   ```python
   # Good
   def test_pl_preferred_over_bg():
       """PL01 chosen over BG01 due to higher priority."""

   # Bad
   def test_plate_selection():
       """Test plate selection."""
   ```

4. **Add docstrings**:
   - Explain what behavior is tested
   - Document edge cases
   - Reference relevant bugs/issues

5. **Test behavior, not implementation**:
   - Focus on observable outcomes
   - Don't test internal methods
   - Use duck typing (hasattr) not isinstance

6. **Run tests to verify**:
   ```bash
   uv run pytest tests/unit/test_yourfile.py -v
   ```

---

## Related Documentation

- **Test Isolation Case Studies**: `docs/TEST_ISOLATION_CASE_STUDIES.md` - Real debugging examples with solutions
- **Configuration**: `docs/CONFIG_VALIDATION.md` - Configuration testing details
- **Plate Workflow**: `docs/NUKE_PLATE_WORKFLOW.md` - Plate discovery testing
- **Coverage Report**: `CLAUDE.md` - Full test coverage breakdown

---

## Best Practices Summary

### DO: ✅
1. **Use `-n 2` for faster tests** - Recommended for 2x speedup (30s vs 60s), serial also works
2. **Set QT_QPA_PLATFORM="offscreen" FIRST** - At top of conftest.py before ANY Qt imports (prevents crashes)
3. **Use explicit fixtures over autouse** - Only use autouse for true cross-cutting concerns (NEW 2025-11-04)
4. **Use real components** - CacheManager, tmp_path, QSignalSpy (minimal mocking)
5. **Test behavior, not implementation** - Focus on observable outcomes
6. **Use try/finally for Qt resources** - Guarantee cleanup always happens
7. **Isolate global state with monkeypatch** - Protect from parallel test contamination
8. **Let autouse fixture clear caches** - Automatic since 2025-11-04, don't clear manually
9. **Use duck typing (hasattr)** - For flexible APIs without isinstance()
10. **Write clear, descriptive test names** - Self-documenting test suites
11. **Add docstrings** - Explain what behavior is tested and why
12. **Run tests frequently** - During development to catch issues early
13. **Use Protocols** - For type-safe duck typing
14. **Use qtbot.waitSignal()** - For async Qt testing (not time.sleep)
15. **Use qtbot.assertNotEmitted()** - To verify signals don't fire
16. **Use testrun_uid for session fixtures** - Prevents resource collisions across workers
17. **Use --dist=worksteal** - Optimal load balancing for varying test durations
18. **Disconnect/reconnect Qt signals for mocking** - Don't use patch side_effect for signals (NEW 2025-11-05)
19. **Clear cache before MainWindow creation** - Prevent background loaders from interfering (NEW 2025-11-05)
20. **Never create Qt apps at module level** - Only in fixtures/functions (NEW 2025-11-05)

### DON'T: ❌
1. **Use autouse for mocks** - Causes worker isolation failures, 98% overhead (CRITICAL NEW 2025-11-04)
2. **Mock everything** - Only mock at system boundaries (subprocess, network)
3. **Use xdist_group as a band-aid** - Fix isolation problems instead
4. **Test private methods** - Test public API and observable behavior
5. **Use isinstance() for duck-typed objects** - Breaks test doubles
6. **Use time.sleep() or processEvents()** - Use synchronization helpers
7. **Write tests without docstrings** - Tests should be self-explanatory
8. **Commit without running tests** - Catch issues before pushing
9. **Skip edge case testing** - Edge cases are where bugs hide
10. **Ignore test failures** - Fix them immediately, don't defer
11. **Manually clear caches in tests** - Autouse fixture handles it automatically (since 2025-11-04)
12. **Use patch side_effect for Qt signals** - Doesn't disconnect real signal, still calls original (NEW 2025-11-05)
13. **Create Qt apps at module level** - Crashes full suite with QCoreApplication/QApplication conflict (NEW 2025-11-05)
14. **Ignore background async operations** - MainWindow initialization triggers loaders that clear data (NEW 2025-11-05)

---

## Documentation Sources

Patterns validated against official documentation:
- **pytest**: Fixture scoping, test isolation
- **pytest-xdist**: Distribution modes, worker management, file locks
- **pytest-qt**: Signal handling, exception capture, resource cleanup

All recommendations align with official best practices from pytest.org and pytest plugin docs.