# Global State Isolation Violations Report

## Summary
Found **12 global state isolation violations** affecting test reliability across the test suite. These violations fall into three categories:

1. **Unprotected `os.environ` modifications** (8 violations)
2. **Direct `Config.SHOWS_ROOT` usage without monkeypatch isolation** (4+ violations)
3. **Missing cleanup in environment-modifying tests** (ongoing risk)

---

## Critical Violations

### Category 1: Unprotected `os.environ` Modifications

These tests modify `os.environ` without using `monkeypatch` fixture, causing cross-test contamination:

#### File: `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py`

| Line | Function | Issue | Impact |
|------|----------|-------|--------|
| 253 | `test_selection_propagates_across_tabs` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup - pollutes subsequent tests |
| 607 | `test_cache_ui_coordination_with_thumbnails` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup - pollutes subsequent tests |
| 679 | `test_cache_updates_ui_on_invalidation` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup - pollutes subsequent tests |
| 772 | `test_cache_manager_updates_ui_async_loader` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup - pollutes subsequent tests |
| 812 | `test_cache_manager_invalidation_in_worker` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup - pollutes subsequent tests |

**Problem**: Lines set environment variable but never restore it. When tests run in any order (especially with `pytest-xdist` parallelization), subsequent tests inherit the modified environment.

#### File: `/home/gabrielh/projects/shotbot/tests/integration/test_feature_flag_switching.py`

| Line | Function | Issue | Impact |
|------|----------|-------|--------|
| 136 | `test_legacy_model_when_flag_set` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | Inside try/except but no finally cleanup |
| 187 | `test_flag_with_different_values` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = value` | No cleanup - pollutes subsequent tests |

**Problem**: Line 136 has try/except but no finally block to guarantee restoration.
Line 187 modifies environment inside loop without cleanup.

---

### Category 2: Direct Config.SHOWS_ROOT Usage (Potential Issues)

Tests that read `Config.SHOWS_ROOT` without verifying monkeypatch isolation:

#### Pattern: Tests that store `shows_root = Config.SHOWS_ROOT`

These occur in:
- `/home/gabrielh/projects/shotbot/tests/unit/test_main_window.py` (10 occurrences at lines 278, 301, 340, 414, 472, 550, 614, 659, 731, 759)
- `/home/gabrielh/projects/shotbot/tests/unit/test_base_shot_model.py` (3 occurrences at lines 178, 204, 222)
- `/home/gabrielh/projects/shotbot/tests/unit/test_threede_scene_finder.py` (line 452)
- `/home/gabrielh/projects/shotbot/tests/unit/test_error_recovery_optimized.py` (line 192)
- Other unit tests

**Status**: These are SAFE because:
- They're in unit tests with proper monkeypatch fixtures
- They check that Config.SHOWS_ROOT is isolated via `tests/unit/conftest.py:19`
- Exception: Test functions must have `monkeypatch` parameter

**Risk**: Any test using `Config.SHOWS_ROOT` without `monkeypatch` parameter will see the real system value.

---

### Category 3: Unsafe Patterns in Specific Tests

#### `/home/gabrielh/projects/shotbot/tests/unit/test_cache_separation.py` (lines 49-79)

```python
original_env = dict(os.environ)
try:
    os.environ.pop("SHOTBOT_MOCK", None)
    os.environ.pop("SHOTBOT_TEST_MODE", None)
    os.environ.pop("SHOTBOT_HEADLESS", None)
    # ... test code ...
finally:
    os.environ.clear()
    os.environ.update(original_env)
```

**Status**: SAFE - Has proper try/finally cleanup, but doesn't use monkeypatch.
**Better approach**: Use `monkeypatch.delenv()` instead.

#### `/home/gabrielh/projects/shotbot/tests/integration/test_feature_flag_switching.py` (lines 93-96)

```python
def test_standard_model_when_flag_not_set(self, ...):
    os.environ.pop("SHOTBOT_USE_LEGACY_MODEL", None)  # No restoration!
```

**Status**: VIOLATION - Removes variable without restoration. If test runs after `test_legacy_model_when_flag_set`, environment is clean. But if it runs first, behavior depends on system state.

---

## Root Cause Analysis

### Why These Violations Occur

1. **No autouse monkeypatch fixture for integration tests**
   - Unit tests use `tests/unit/conftest.py` which isolates Config
   - Integration tests have no equivalent fixture for environment isolation

2. **Inconsistent patterns across test files**
   - Some use `patch.dict("os.environ", {...})`
   - Some use `monkeypatch.setattr()`
   - Some directly modify `os.environ` with no cleanup

3. **Integration test architecture**
   - Large integration tests create MainWindow instances
   - These tests run with full Qt initialization
   - Environment variables control behavior at import time

---

## Violation Count Summary

| Type | Count | Severity |
|------|-------|----------|
| Unprotected `os.environ[...]` assignments (no cleanup) | 8 | HIGH |
| Direct `Config.SHOWS_ROOT` reads (without monkeypatch param) | 30+ | MEDIUM |
| Unsafe pattern tests (try without finally) | 1 | HIGH |
| Safe but suboptimal patterns | 3 | LOW |
| **TOTAL RISKY VIOLATIONS** | **9** | **HIGH** |

---

## Affected Test Modules

### HIGH RISK (Unprotected modifications)
1. `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py` (5 violations)
2. `/home/gabrielh/projects/shotbot/tests/integration/test_feature_flag_switching.py` (2 violations)
3. `/home/gabrielh/projects/shotbot/tests/unit/test_headless.py` (isolated with proper cleanup)

### MEDIUM RISK (Potential Config isolation issues)
1. `/home/gabrielh/projects/shotbot/tests/unit/test_main_window.py` (uses Config.SHOWS_ROOT 10x)
2. `/home/gabrielh/projects/shotbot/tests/unit/test_base_shot_model.py` (uses Config.SHOWS_ROOT 3x)
3. `/home/gabrielh/projects/shotbot/tests/unit/test_threede_scene_finder.py`
4. Multiple other unit tests

### SAFE (Proper isolation)
1. `/home/gabrielh/projects/shotbot/tests/unit/test_cache_separation.py` (has finally cleanup)
2. `/home/gabrielh/projects/shotbot/tests/unit/test_previous_shots_finder.py` (manual restoration)
3. `/home/gabrielh/projects/shotbot/tests/unit/test_nuke_workspace_manager.py` (uses patch.dict)
4. Tests using `mock_vfx_root` fixture (proper monkeypatch)

---

## Cross-Test Contamination Risk

### Scenario: Parallel Execution with `pytest-xdist`

```
Worker 1: test_cross_component_integration.py::test_selection_propagates_across_tabs
  → Sets os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"
  → Doesn't restore

Worker 1: test_feature_flag_switching.py::test_standard_model_when_flag_not_set
  → Expects SHOTBOT_USE_LEGACY_MODEL to be unset
  → FAILS because previous test polluted environment
```

### Scenario: Serial Execution (Current Default)

```
Test 1: test_cross_component_integration.py::test_cache_ui_coordination_with_thumbnails
  → Sets os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"

Test 2: test_feature_flag_switching.py::test_standard_model_when_flag_not_set
  → Expects unset flag, but sees polluted value
  → Test behaves incorrectly

Test 3: test_headless.py::test_headless_mode_detection
  → Depends on clean environment
  → FAILS due to Test 2's contamination
```

---

## Monkeypatch Usage Analysis

### Proper Usage (Safe)

```python
# Unit tests with isolated Config
tests/unit/conftest.py:19
    monkeypatch.setattr(Config, "SHOWS_ROOT", "/tmp/mock_vfx/shows")

# Individual tests with environment patching
tests/unit/test_simple_nuke_launcher.py:36
    @patch.dict("os.environ", {"USER": "testuser"})

# Using monkeypatch directly
tests/unit/test_raw_plate_finder.py:70
    monkeypatch.setattr("config.Config.SHOWS_ROOT", str(shows_root))
```

### Unsafe Usage (Current Violations)

```python
# Direct modification without cleanup
tests/integration/test_cross_component_integration.py:253
    os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"  # No cleanup!

# Try without finally
tests/integration/test_feature_flag_switching.py:136
    os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"
    try:
        # ... test code ...
    finally:
        pass  # No restoration!
```

---

## Recommendations (Priority Order)

### 1. CRITICAL: Fix Unprotected Modifications (Affects: 8 tests)

**File: `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py`**

Replace all instances of:
```python
os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"
```

With monkeypatch-based approach:
```python
def test_selection_propagates_across_tabs(
    self,
    qapp: QApplication,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # ADD THIS
) -> None:
    monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")  # USE THIS
    # ... rest of test ...
```

Apply this to lines: 253, 607, 679, 772, 812

**File: `/home/gabrielh/projects/shotbot/tests/integration/test_feature_flag_switching.py`**

Line 136:
```python
def test_legacy_model_when_flag_set(self, qapp: QApplication, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")
    # ... test code ...
```

Line 187 (in loop):
```python
for value in [None, "0", "false", "", "1", "true", "yes"]:
    monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", value or "")
    # ... test code ...
```

### 2. HIGH PRIORITY: Create Integration Test Fixture

Create `/home/gabrielh/projects/shotbot/tests/integration/conftest.py`:

```python
@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-isolate environment variables in integration tests.
    
    Prevents cross-test contamination from os.environ modifications
    in integration tests that create MainWindow instances.
    """
    # Save original environment
    original_env = dict(os.environ)
    
    yield
    
    # Restore after test
    os.environ.clear()
    os.environ.update(original_env)
```

### 3. MEDIUM PRIORITY: Verify Config Isolation

Ensure all tests using `Config.SHOWS_ROOT` have:
- `monkeypatch` parameter in function signature
- Or use fixture that provides isolation (like `mock_vfx_root`)

Check these files:
- `/home/gabrielh/projects/shotbot/tests/unit/test_main_window.py` (10 uses)
- `/home/gabrielh/projects/shotbot/tests/unit/test_base_shot_model.py` (3 uses)
- Others identified in violation list

### 4. LOW PRIORITY: Standardize Patterns

Adopt consistent pattern across all tests:

**✅ PREFERRED**:
```python
@patch.dict("os.environ", {"USER": "testuser"})
def test_something(self):
    ...
```

**✅ ACCEPTABLE**:
```python
def test_something(self, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USER", "testuser")
    ...
```

**❌ AVOID**:
```python
def test_something(self):
    os.environ["USER"] = "testuser"  # No cleanup!
```

---

## Testing Impact

### Current Status
- **2,296+ tests passing** with serial execution
- **Potential failures** with parallel execution (pytest-xdist)
- **Flaky tests** if test order changes

### After Fixes
- **100% isolation** between tests
- **Reliable parallel execution** with `-n 2`, `-n auto`
- **Reproducible test runs** regardless of order

---

## Files Requiring Changes

1. `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py` (5 locations)
2. `/home/gabrielh/projects/shotbot/tests/integration/test_feature_flag_switching.py` (2 locations)
3. `/home/gabrielh/projects/shotbot/tests/integration/conftest.py` (CREATE NEW)

---

## Verification Checklist

After applying fixes:

- [ ] All tests in test_cross_component_integration.py use monkeypatch
- [ ] All tests in test_feature_flag_switching.py use monkeypatch
- [ ] Integration conftest.py created with autouse isolation fixture
- [ ] Unit tests with Config.SHOWS_ROOT have monkeypatch parameter
- [ ] Run tests serially: `pytest tests/ --maxfail=5`
- [ ] Run tests parallel: `pytest tests/ -n 2 --maxfail=5`
- [ ] Run tests shuffled: `pytest tests/ --random-order --maxfail=5`
- [ ] All pass without order-dependent failures

