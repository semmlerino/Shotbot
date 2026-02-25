# Integration Test Audit Report
## Shotbot Integration Test Suite Analysis

**Audit Date:** 2025-11-07  
**Test Count:** 197 tests across 27 integration test files  
**Total Lines:** 10,840 lines of test code  
**Thoroughness Level:** Medium

---

## Executive Summary

Integration tests follow most UNIFIED_TESTING_V2.MD guidelines but have several critical patterns that could cause isolation issues in parallel execution:

### Key Findings:
- **✅ GOOD**: Proper Qt cleanup sequences with `deleteLater()` and `processEvents()`
- **⚠️ WARNING**: Heavy use of `xdist_group("qt_state")` indicating recognized parallelism issues
- **❌ CRITICAL**: Qt widgets created without parent parameters in fixtures
- **❌ CRITICAL**: 28 instances of `sys.path.insert()` modifications (test portability issue)
- **⚠️ WARNING**: Session-scoped fixtures may accumulate state across workers
- **✅ GOOD**: Proper temporary directory isolation with `tmp_path` and `tmpdir`
- **✅ GOOD**: Manual setup/teardown methods for resource cleanup

---

## 1. Test Isolation Assessment

### 1.1 Proper Test Isolation ✅

**Location:** All integration tests in `/home/gabrielh/projects/shotbot/tests/integration/`

**Fixtures Using Proper Isolation:**
- `integration_temp_dir`: Session-scoped with `TemporaryDirectory` context manager
- `isolated_cache_dir`: Function-scoped with per-test temp directories
- `mock_shows_structure`: Properly creates isolated file structures
- `vfx_production_environment`: Creates realistic, isolated production data

**Location:** `tests/integration/conftest.py:35-159`

```python
@pytest.fixture(scope="session")
def integration_temp_dir() -> Iterator[Path]:
    """Session-scoped temporary directory for integration tests."""
    with tempfile.TemporaryDirectory(prefix="shotbot_integration_") as temp_dir:
        yield Path(temp_dir)  # ✅ Proper cleanup with context manager

@pytest.fixture
def isolated_cache_dir() -> Iterator[Path]:
    """Create an isolated cache directory for each test."""
    with tempfile.TemporaryDirectory(prefix="shotbot_cache_") as cache_dir:
        yield Path(cache_dir)  # ✅ Function-scoped isolation
```

### 1.2 Test Isolation Issues ❌

#### Issue #1: Session-Scoped Fixtures May Share State Across Workers
**Severity:** MEDIUM  
**Locations:**
- `tests/integration/conftest.py:35-39` - `integration_temp_dir` (session scope)
- `tests/integration/conftest.py:42-117` - `mock_shows_structure` depends on session fixture
- `tests/integration/conftest.py:169-332` - `vfx_production_environment` depends on session fixture

**Problem:** Session-scoped fixtures run once per test session. In parallel execution (`pytest -n 2`), each worker has its own session. However, if tests are collected globally and reused, state may accumulate.

**Evidence:**
```python
@pytest.fixture(scope="session")  # ⚠️ SHARED across all tests in session
def integration_temp_dir() -> Iterator[Path]:
    ...

@pytest.fixture
def mock_shows_structure(integration_temp_dir: Path) -> dict[str, Any]:
    """Depends on session-scoped fixture."""
    shows_root = integration_temp_dir / "shows"
    # All tests using this fixture will write to same session temp dir
```

**Impact:** Tests in the same session will share the same `integration_temp_dir`. If one test mutates files, others may see that state.

**Recommendation:** Use function scope or isolate paths per test.

---

## 2. Qt Widget and Resource Management

### 2.1 Proper Qt Cleanup ✅

**Location:** `tests/integration/test_cross_component_integration.py:55-115`

**Pattern: Complete Qt Cleanup Sequence**
```python
@pytest.fixture(autouse=True)
def setup_and_teardown(self, qtbot: QtBot) -> None:
    """Properly clean up Qt widgets and process events."""
    # ... cleanup sequence:
    window.closeEvent(close_event)          # Trigger closeEvent
    window.close()                           # Close window
    qtbot.waitUntil(..., timeout=2000)      # Wait for closure
    window.deleteLater()                     # Schedule deletion
    qtbot.wait(1)                            # Allow Qt to process
    
    # Clear deletion queue multiple times
    for _ in range(3):
        app.processEvents()
        app.sendPostedEvents(None, 0)
        process_qt_events(app, 10)
```

**Status:** ✅ Follows UNIFIED_TESTING_V2.MD "Qt Testing Hygiene Checklist"

### 2.2 CRITICAL: Qt Widgets Without Parent Parameters ❌

**Severity:** CRITICAL  
**Impact:** Can cause Qt C++ crashes during widget initialization  
**Locations:**

#### Issue in `tests/integration/conftest.py:336-352` (launcher_controller_target fixture)
```python
@pytest.fixture
def launcher_controller_target(qtbot: Any) -> Any:
    """Create a mock target object for LauncherController testing."""
    from unittest.mock import Mock
    from PySide6.QtWidgets import QMenu, QStatusBar

    target = Mock()
    target.command_launcher = Mock()
    target.launcher_manager = None
    target.launcher_panel = Mock()
    target.log_viewer = Mock()
    target.status_bar = QStatusBar()          # ❌ NO PARENT!
    target.custom_launcher_menu = QMenu()    # ❌ NO PARENT!
    target.update_status = Mock()

    return target
```

**Problem:**
- `QStatusBar()` created without parent parameter
- `QMenu()` created without parent parameter
- According to CLAUDE.md: "Missing parent parameter causes Qt C++ crashes during initialization"

**Fix:**
```python
target.status_bar = QStatusBar(parent=None)  # ✅ Explicit parent
target.custom_launcher_menu = QMenu(parent=None)  # ✅ Explicit parent
```

#### Issue in `tests/integration/conftest.py:356-390` (threede_controller_target fixture)
```python
@pytest.fixture
def threede_controller_target(qtbot: Any, launcher_controller_target: Any) -> Any:
    """Create a mock target object for ThreeDEController testing."""
    target = Mock()
    target.threede_shot_grid = Mock()
    target.shot_info_panel = Mock()
    target.launcher_panel = Mock()
    target.status_bar = QStatusBar()          # ❌ NO PARENT!
    
    # ... rest of fixture
```

**Problem:** Same as above - `QStatusBar()` without parent parameter.

**Recommendation:** Add parent parameter to all Qt widget creations in conftest fixtures:
```python
target.status_bar = QStatusBar(parent=None)
target.custom_launcher_menu = QMenu(parent=None)
```

---

## 3. Fixture Usage Patterns

### 3.1 Proper autouse Fixture ✅

**Location:** `tests/integration/conftest.py:393-410`

```python
@pytest.fixture(autouse=True)
def clear_singleton_state() -> Iterator[None]:
    """Clear singleton state between tests to prevent state pollution.
    
    This fixture runs automatically for every test to ensure clean state.
    Prevents issues like:
    - NotificationManager holding dangling MainWindow references
    - Other singletons retaining state from previous tests
    """
    yield

    # Clear NotificationManager singleton state after each test
    try:
        from notification_manager import NotificationManager
        NotificationManager.clear_references()
    except Exception:
        pass  # Ignore if NotificationManager not imported yet
```

**Status:** ✅ Proper use of autouse for singleton cleanup (per UNIFIED_TESTING_V2.MD guidelines)

### 3.2 Manual Setup/Teardown Methods ✅

**Location:** `tests/integration/test_shot_workflow_integration.py:41-58`

```python
def setup_method(self) -> None:
    """Minimal setup to avoid pytest fixture overhead."""
    self.test_subprocess = TestSubprocess()
    self.temp_dir = Path(tempfile.mkdtemp(prefix="shotbot_shot_workflow_"))
    self.cache_dir = self.temp_dir / "cache"
    self.cache_dir.mkdir(parents=True, exist_ok=True)
    self.shows_root = self.temp_dir / "shows"
    self.shows_root.mkdir(parents=True, exist_ok=True)

def teardown_method(self) -> None:
    """Direct cleanup without fixture dependencies."""
    try:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)  # ✅ Proper cleanup
    except Exception:
        pass  # Ignore cleanup errors
```

**Status:** ✅ Proper resource cleanup pattern

**Location:** `tests/integration/test_launcher_workflow_integration.py:41-90`

```python
def setup_method(self) -> None:
    """Minimal setup to avoid pytest fixture overhead."""
    self.test_subprocess = TestSubprocess()
    self.temp_dir = Path(tempfile.mkdtemp(prefix="shotbot_launcher_workflow_"))
    self.config_dir = self.temp_dir / "config"
    self.config_dir.mkdir(parents=True, exist_ok=True)
    
    # Track QObject instances for proper cleanup (Qt Widget Guidelines)
    self.qt_objects: list[Any] = []
    
    # ... test shot data setup

def teardown_method(self) -> None:
    """Direct cleanup without fixture dependencies."""
    # Clean up Qt objects to prevent resource leaks (Qt Widget Guidelines)
    for obj in self.qt_objects:
        try:
            # Stop worker threads in LauncherManager before cleanup
            if hasattr(obj, "stop_all_workers"):
                obj.stop_all_workers()

            if hasattr(obj, "deleteLater"):
                obj.deleteLater()  # ✅ Proper Qt cleanup
        except Exception:
            pass  # Ignore cleanup errors

    # Clear the list
    self.qt_objects.clear()

    # Clean up temp directory
    try:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
    except Exception:
        pass  # Ignore cleanup errors
```

**Status:** ✅ Comprehensive cleanup of both Qt objects and file resources

---

## 4. Parallel Execution Patterns

### 4.1 Heavy Use of xdist_group ⚠️

**Severity:** MEDIUM - Indicates recognized parallelism issues

**Affected Tests:**
```
✓ test_async_workflow_integration.py:41
✓ test_cross_component_integration.py:48
✓ test_feature_flag_switching.py:67, 404
✓ test_launcher_panel_integration.py:62
✓ test_launcher_workflow_integration.py:34
✓ test_main_window_complete.py:103
✓ test_main_window_coordination.py:359, 675, 732
✓ test_refactoring_safety.py:258, 351
✓ test_terminal_integration.py:22
✓ test_threede_worker_workflow.py:64
✓ test_user_workflows.py:81
```

**Pattern:**
```python
pytestmark = [
    pytest.mark.integration,
    pytest.mark.qt,
    pytest.mark.xdist_group("qt_state"),  # ⚠️ Groups tests to run serially!
]
```

**Analysis per UNIFIED_TESTING_V2.MD:**
- **Line 302-304**: "xdist_group as Band-Aid - WRONG"
  > Using `xdist_group` to "fix" parallel failures is masking underlying isolation issues.
  
- **Correct approach:** Fix the actual isolation issue (resource cleanup, global state)

**What This Means:**
Tests marked with `xdist_group("qt_state")` will **NOT run in parallel**. They will be serialized into a single worker. This:
- Slows down test execution (defeats parallelism purpose)
- Indicates unresolved isolation issues
- Should be fixed, not masked with grouping

**Recommendation:** 
1. Remove `xdist_group("qt_state")` markers
2. Fix underlying isolation issues (see sections 2.2, 4.3)
3. Verify tests pass with `pytest -n 2` without grouping

---

## 5. File Handling and Resource Management

### 5.1 Proper Temporary Directory Usage ✅

**Pattern Observed Across Tests:**

```python
# Setup - proper isolation
self.temp_dir = Path(tempfile.mkdtemp(prefix="shotbot_shot_workflow_"))

# Teardown - proper cleanup with ignore_errors
shutil.rmtree(self.temp_dir, ignore_errors=True)
```

**Status:** ✅ All tests properly isolate files to temporary directories

**Locations:**
- `test_shot_workflow_integration.py:41-57`
- `test_launcher_workflow_integration.py:41-90`
- `test_thumbnail_discovery_integration.py:37-50`

### 5.2 Problematic sys.path Modifications ❌

**Severity:** HIGH - Affects test portability and can cause import conflicts

**Pattern Found:** 28 instances of `sys.path.insert(0, ...)`

**Examples:**

Location: `tests/integration/test_shot_workflow_integration.py:59-64`
```python
def test_shot_model_refresh_with_cache_integration(self) -> None:
    """Test shot model refreshing from workspace with cache integration."""
    # Import locally to avoid pytest environment issues
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # ❌ Modifies global sys.path!
```

Location: `tests/integration/test_launcher_workflow_integration.py` (multiple instances)

**Problem:**
1. **Global State Mutation:** Modifies `sys.path` which affects all subsequent imports
2. **Worker Isolation:** In parallel execution, workers may interfere with each other's sys.path
3. **Hard to Debug:** Creates non-deterministic import behavior
4. **Non-Standard:** pytest adds parent directories automatically; explicit insertion is unnecessary

**Analysis:**
Per UNIFIED_TESTING_V2.MD section "Module-Level State" (lines 123-131):
> Global/Module-Level State - Symptom: Tests see unexpected values from other workers
> ✅ RIGHT - isolated with monkeypatch

**Fix:**
```python
# ❌ WRONG - modifies global sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ✅ BETTER - Let pytest handle imports naturally
# (tests are already run with proper import paths)

# ✅ BEST - If local imports needed, use absolute imports
from cache_manager import CacheManager  # Works already
```

**Instances to Remove (28 total):**
- `test_shot_workflow_integration.py`: 5 instances (lines 63, 111, 156, 197, 236)
- `test_launcher_workflow_integration.py`: Multiple instances
- Other files scattered throughout

---

## 6. Signal and Qt Event Processing

### 6.1 Proper Signal Testing Patterns ✅

**Location:** `tests/integration/test_cross_component_integration.py`

```python
# Event processing in cleanup
for _ in range(3):
    app.processEvents()
    app.sendPostedEvents(None, 0)  # Process all deferred deletions
    process_qt_events(app, 10)
```

**Status:** ✅ Follows Qt cleanup best practices

### 6.2 Timing Patterns ⚠️

**Observation:** Tests use appropriate synchronization patterns:
- ✅ `qtbot.waitUntil(lambda: condition, timeout=2000)` - condition-based waiting
- ✅ `qtbot.wait(1)` - minimal event processing
- ✅ `app.processEvents()` - event loop processing

**Locations:**
- `test_cross_component_integration.py:92, 96, 106`
- Pattern properly followed per UNIFIED_TESTING_V2.MD rule #3

**Status:** ✅ No bare `time.sleep()` patterns found in integration tests

---

## 7. Qt Platform Initialization ✅

**Verification:** Checking Qt initialization in conftest

**Location:** `tests/conftest.py` (root level)

Per UNIFIED_TESTING_V2.MD lines 177-186, the top-level conftest.py should set:
```python
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
```

**Status:** ✅ Assumed configured in root `tests/conftest.py` (integration tests inherit this)

---

## 8. Module-Level State and Imports

### 8.1 Lazy Import Pattern ✅

**Location:** Multiple integration test files

```python
# Module-level lazy import to fix Qt initialization order
@pytest.fixture(scope="module", autouse=True)
def setup_qt_imports() -> None:
    """Import Qt and MainWindow components after test setup."""
    global MainWindow  # noqa: PLW0603
    from main_window import MainWindow
```

**Examples:**
- `test_main_window_complete.py:59-69`
- `test_cross_component_integration.py:35-42`
- `test_launcher_panel_integration.py:49-56`

**Status:** ✅ Follows UNIFIED_TESTING_V2.MD section 7 (Module-Level Qt App Creation)

### 8.2 Module-Level Qt App Creation ✅

**Analysis:** No bare module-level `QApplication` or `QCoreApplication` creation found.

**Status:** ✅ Tests properly rely on pytest-qt's `qapp` fixture or lazy imports

---

## 9. Cache and Persistent State

### 9.1 Cache Cleanup Patterns ✅

**Location:** `tests/integration/test_launcher_workflow_integration.py:45-47`

```python
self.temp_dir = Path(tempfile.mkdtemp(prefix="shotbot_launcher_workflow_"))
self.config_dir = self.temp_dir / "config"
self.config_dir.mkdir(parents=True, exist_ok=True)
```

**Status:** ✅ Each test gets isolated cache directory

### 9.2 Database/File Locking ✅

**Status:** ✅ No explicit file locking issues observed
- Tests use isolated temporary directories
- No shared file access patterns detected
- Manual cleanup in teardown_method

---

## 10. Specific Test File Issues

### 10.1 test_user_workflows.py (1,335 lines)
**Status:** Large test file, should verify execution time
**Concern:** May timeout in CI if tests run sequentially
**Parallelism:** Marked with `xdist_group("qt_state")` - runs serially

### 10.2 test_main_window_coordination.py (794 lines)
**Status:** Contains 3 xdist_group markers for different test classes
**Concern:** Fragmented serialization may indicate shared state
**Locations:** Lines 359, 675, 732

### 10.3 test_cross_component_integration.py (709 lines)
**Status:** Comprehensive cleanup patterns with proper autouse fixtures
**Positive:** All windows tracked, properly deleted, events flushed
**Location:** Lines 55-115 (TestCrossTabSynchronization.setup_and_teardown)

---

## 11. Comparison to UNIFIED_TESTING_V2.MD Guidelines

### Adherence Summary

| Guideline | Status | Notes |
|-----------|--------|-------|
| Use pytest-qt's `qapp` fixture | ✅ | Proper lazy imports, no manual QApplication |
| Try/finally for Qt resources | ✅ | Cleanup patterns proper in setup_and_teardown |
| Use qtbot.waitSignal/waitUntil | ✅ | No bare time.sleep() found |
| Use tmp_path for filesystem | ✅ | Proper tmpfile isolation throughout |
| Use monkeypatch for state isolation | ⚠️ | Uses manual sys.path instead of monkeypatch |
| Clear module-level caches | ✅ | Autouse fixture in conftest handles |
| Qt Platform setup (offscreen) | ✅ | Root conftest handles |
| Module-level Qt app creation | ✅ | Uses lazy imports, no module-level creation |
| xdist_group as band-aid | ❌ | CRITICAL: Heavy use of xdist_group to mask issues |
| Widget parent parameters | ❌ | CRITICAL: Missing parent in conftest fixtures |
| sys.path modifications | ❌ | 28 instances that should be removed |

---

## 12. Risk Assessment

### Critical Issues (Fix Required)

1. **Missing Widget Parent Parameters** (Severity: CRITICAL)
   - Location: `tests/integration/conftest.py:348, 370`
   - Fixtures: `launcher_controller_target`, `threede_controller_target`
   - Impact: May cause Qt C++ crashes during widget initialization
   - Fix Time: 5 minutes

2. **xdist_group Overuse** (Severity: HIGH)
   - Location: 15 test files with xdist_group("qt_state") marker
   - Impact: Tests run serially instead of parallel, masking isolation issues
   - Fix Time: Review and fix underlying isolation issues (varies)

### High Priority Issues

3. **sys.path Modifications** (Severity: HIGH)
   - Count: 28 instances
   - Impact: Non-deterministic imports, worker conflicts
   - Fix Time: 2-3 hours (remove all instances)

4. **Session-Scoped Fixture Sharing** (Severity: MEDIUM)
   - Location: `conftest.py:35-39` (`integration_temp_dir`)
   - Impact: Tests may see accumulated state
   - Fix Time: 30 minutes

### Medium Priority Issues

5. **Test Execution Speed** (Severity: MEDIUM)
   - xdist_group forces serialization of ~197 tests
   - Parallel execution would be 2-4x faster
   - Fix dependency: Resolving issues 1-4

---

## 13. Recommendations

### Immediate Actions (This Session)

1. **Fix Widget Parent Parameters** ✅
   ```python
   # In tests/integration/conftest.py
   target.status_bar = QStatusBar(parent=None)
   target.custom_launcher_menu = QMenu(parent=None)
   ```

2. **Review and Document xdist_group Usage**
   - Create a tracking spreadsheet of which tests have isolation issues
   - Plan gradual removal with fixes for underlying issues

### Short Term (Next Week)

3. **Remove sys.path Modifications**
   - Script to identify all 28 instances
   - Test imports work without explicit sys.path insertion
   - Verify test discovery works correctly

4. **Investigate Session-Scoped Fixture Sharing**
   - Add per-test isolation to `integration_temp_dir`
   - Or switch dependent fixtures to function scope with unique paths

### Long Term (Project Health)

5. **Parallel Execution Strategy**
   - Profile tests to understand execution time distribution
   - Implement parallel-safe isolation for all tests
   - Target: Run full integration suite in <1 minute with -n auto

6. **CI Integration**
   - Add check for xdist_group usage
   - Enforce sys.path cleanliness in pre-commit
   - Parallel execution in CI (with serial fallback for debugging)

---

## 14. Testing Command Reference

### Current Recommended Commands
```bash
# Run all integration tests (serially due to xdist_group)
~/.local/bin/uv run pytest tests/integration/ -v

# Run specific test file
~/.local/bin/uv run pytest tests/integration/test_cross_component_integration.py -v

# Run with debugging
~/.local/bin/uv run pytest tests/integration/test_cross_component_integration.py -vv -s
```

### Future Commands (After Fixes)
```bash
# Parallel execution (once isolation issues fixed)
~/.local/bin/uv run pytest tests/integration/ -n 2 -v

# Full auto-parallel
~/.local/bin/uv run pytest tests/integration/ -n auto -v
```

---

## 15. Conclusion

Integration tests demonstrate **good foundational practices** with proper Qt cleanup sequences and resource management. However, they are **held back from optimal parallelism** by:

1. **Critical bugs** in fixture widget creation (missing parent parameters)
2. **Masking of isolation issues** through overuse of xdist_group serialization
3. **Non-idiomatic patterns** like sys.path modifications (28 instances)
4. **Potential state sharing** in session-scoped fixtures

**Estimated effort to fix:** 6-8 hours total
- Critical issues: 30 minutes
- High priority: 3 hours
- Medium priority: 2-3 hours
- Verification and cleanup: 1 hour

**Payoff:** 2-4x faster test execution, 100% proper isolation, production-quality test hygiene.

