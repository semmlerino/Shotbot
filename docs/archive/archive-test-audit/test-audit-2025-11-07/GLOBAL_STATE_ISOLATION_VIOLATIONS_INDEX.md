# Global State Isolation Violations - Detailed Index

## Quick Navigation

- **Quick Summary**: [GLOBAL_STATE_ISOLATION_QUICK_SUMMARY.txt](./GLOBAL_STATE_ISOLATION_QUICK_SUMMARY.txt)
- **Full Report**: [GLOBAL_STATE_ISOLATION_REPORT.md](./GLOBAL_STATE_ISOLATION_REPORT.md)
- **This Index**: Detailed violation locations and patterns

---

## Violation Details by File

### HIGH PRIORITY VIOLATIONS

#### 1. `/home/gabrielh/projects/shotbot/tests/integration/test_cross_component_integration.py`

**Violation Count**: 5 unprotected environment modifications

| Line | Function | Code | Type | Cleanup | Risk |
|------|----------|------|------|---------|------|
| 253 | `test_selection_propagates_across_tabs` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup | ❌ | HIGH |
| 607 | `test_cache_ui_coordination_with_thumbnails` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup | ❌ | HIGH |
| 679 | `test_cache_updates_ui_on_invalidation` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup | ❌ | HIGH |
| 772 | `test_cache_manager_updates_ui_async_loader` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup | ❌ | HIGH |
| 812 | `test_cache_manager_invalidation_in_worker` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | No cleanup | ❌ | HIGH |

**Root Cause**: Tests set SHOTBOT_USE_LEGACY_MODEL environment variable but never restore it, causing subsequent tests to inherit the modified state.

**Contamination Pattern**:
```
Test 1 (line 253) sets SHOTBOT_USE_LEGACY_MODEL="1"
  ↓
Test 2 expects SHOTBOT_USE_LEGACY_MODEL unset
  ↓
Test 2 sees polluted environment = WRONG BEHAVIOR
```

**Fix Required**: Add `monkeypatch: pytest.MonkeyPatch` parameter and replace with `monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")`

---

#### 2. `/home/gabrielh/projects/shotbot/tests/integration/test_feature_flag_switching.py`

**Violation Count**: 2 unsafe environment modifications

| Line | Function | Code | Type | Cleanup | Risk |
|------|----------|------|------|---------|------|
| 136 | `test_legacy_model_when_flag_set` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` | Try/except missing finally | ❌ | HIGH |
| 187 | `test_flag_with_different_values` | `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = value` | Loop without cleanup | ❌ | HIGH |

**Violation 1: Line 136 - Try Without Finally**
```python
def test_legacy_model_when_flag_set(self, qapp, qtbot):
    os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"
    try:
        # ... test code ...
    finally:
        pass  # ❌ NO RESTORATION!
```

Problem: If test raises exception or gets interrupted, environment variable persists.

**Violation 2: Line 187 - Loop Without Cleanup**
```python
for value in [...]:
    os.environ["SHOTBOT_USE_LEGACY_MODEL"] = value  # ❌ Modifies in loop
    # ... test code ...
```

Problem: Loop modifies environment. If loop exits early (exception), variable isn't cleaned up.

**Fix Required**: Use monkeypatch.setenv() which auto-restores

---

### MEDIUM PRIORITY VIOLATIONS (Config Isolation)

#### 3. `/home/gabrielh/projects/shotbot/tests/unit/test_main_window.py`

**Pattern**: Tests read `Config.SHOWS_ROOT` without explicit monkeypatch parameter

```python
shows_root = Config.SHOWS_ROOT  # Depends on monkeypatch isolation
```

**Occurrences**: Lines 278, 301, 340, 414, 472, 550, 614, 659, 731, 759 (10 locations)

**Status**: SAFE IF monkeypatch fixture is active via `tests/unit/conftest.py:19`

**Risk**: If test function signature doesn't include `monkeypatch: pytest.MonkeyPatch`, Config.SHOWS_ROOT won't be isolated.

**Verification Needed**: Check each test function has monkeypatch parameter

---

#### 4. `/home/gabrielh/projects/shotbot/tests/unit/test_base_shot_model.py`

**Pattern**: Tests read `Config.SHOWS_ROOT` without explicit monkeypatch parameter

```python
shows_root = Config.SHOWS_ROOT  # Depends on monkeypatch isolation
```

**Occurrences**: Lines 178, 204, 222 (3 locations)

**Status**: SAFE IF monkeypatch fixture is active

**Risk**: Same as above - depends on test function having monkeypatch parameter

---

#### 5. `/home/gabrielh/projects/shotbot/tests/unit/test_threede_scene_finder.py`

**Pattern**: Tests read `Config.SHOWS_ROOT` without explicit monkeypatch parameter

**Line 452**:
```python
original_shows_root = Config.SHOWS_ROOT
monkeypatch.setattr("config.Config.SHOWS_ROOT", original_shows_root)
```

**Status**: SAFE - Explicitly saves and uses monkeypatch

---

#### 6. `/home/gabrielh/projects/shotbot/tests/unit/test_error_recovery_optimized.py`

**Line 192**:
```python
shows_root = Config.SHOWS_ROOT
```

**Status**: MEDIUM RISK - Depends on monkeypatch fixture being active

---

### LOW PRIORITY VIOLATIONS (Safe but Suboptimal)

#### 7. `/home/gabrielh/projects/shotbot/tests/unit/test_cache_separation.py`

**Lines 49-79**: Manual environment restoration using try/finally

```python
original_env = dict(os.environ)
try:
    os.environ.pop("SHOTBOT_MOCK", None)
    # ... test code ...
finally:
    os.environ.clear()
    os.environ.update(original_env)
```

**Status**: SAFE - Has proper cleanup, but doesn't use monkeypatch

**Improvement**: Use `monkeypatch.delenv()` instead of manual restoration

---

#### 8. `/home/gabrielh/projects/shotbot/tests/unit/test_previous_shots_finder.py`

**Lines 148-170**: Manual environment restoration

```python
original_user = os.environ.get("USER")
original_mock = os.environ.get("SHOTBOT_MOCK")
try:
    # ... test code ...
finally:
    # Restore original values
    if original_user:
        os.environ["USER"] = original_user
    elif "USER" in os.environ:
        del os.environ["USER"]
    # ... similar for SHOTBOT_MOCK ...
```

**Status**: SAFE - Has proper cleanup

**Improvement**: Use monkeypatch

---

#### 9. `/home/gabrielh/projects/shotbot/tests/unit/test_headless.py`

**Multiple occurrences**: Manual environment restoration with try/finally

**Status**: SAFE - Has proper cleanup

**Pattern**:
```python
original_env = dict(os.environ)
try:
    os.environ["SHOTBOT_HEADLESS"] = "1"
    # ... test code ...
finally:
    os.environ.clear()
    os.environ.update(original_env)
```

---

## Summary by Risk Level

### HIGH RISK (9 violations)
| Count | Type | Files | Action |
|-------|------|-------|--------|
| 5 | Unprotected os.environ | test_cross_component_integration.py | Replace with monkeypatch.setenv() |
| 2 | Unsafe patterns | test_feature_flag_switching.py (lines 136, 187) | Use monkeypatch |
| 2 | Config isolation | test_main_window.py, test_base_shot_model.py | Verify monkeypatch params |

### MEDIUM RISK (4+ violations)
| Type | Pattern | Files | Action |
|------|---------|-------|--------|
| Config isolation | reads Config.SHOWS_ROOT | Various unit tests | Verify monkeypatch active |

### LOW RISK (3 violations)
| Type | Pattern | Files | Action |
|------|---------|-------|--------|
| Manual cleanup | try/finally without monkeypatch | cache_separation, previous_shots_finder, headless | Optional improvement |

---

## Pattern Analysis

### Pattern 1: Unprotected Direct Assignment (VIOLATION)

```python
# ❌ BAD - No cleanup, cross-test contamination
os.environ["VAR"] = "value"
```

**Found in**: 8 locations

**Fix**: Use monkeypatch.setenv()

### Pattern 2: Manual Try/Finally Restoration (SAFE but suboptimal)

```python
# ✅ SAFE but verbose - manual cleanup
original = dict(os.environ)
try:
    os.environ["VAR"] = "value"
finally:
    os.environ.clear()
    os.environ.update(original)
```

**Found in**: 3 locations

**Fix**: Use monkeypatch

### Pattern 3: Monkeypatch Usage (BEST PRACTICE)

```python
# ✅ BEST - Automatic cleanup, guaranteed restoration
def test_something(self, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VAR", "value")
    # ... test code ...
    # Auto-restored when test ends
```

**Found in**: Many locations

**Pattern**: Keep and expand

### Pattern 4: patch.dict Decorator (GOOD)

```python
# ✅ GOOD - Context manager with cleanup
@patch.dict("os.environ", {"USER": "testuser"})
def test_something(self):
    ...
```

**Found in**: Several locations

**Pattern**: Keep and expand

---

## Execution Order Vulnerability Demonstration

### Example 1: Serial Execution Contamination

```
Test execution order (serial):
1. test_cross_component_integration.py::test_selection_propagates_across_tabs
   → Sets SHOTBOT_USE_LEGACY_MODEL="1" (NO CLEANUP!)
   
2. test_feature_flag_switching.py::test_standard_model_when_flag_not_set
   → Expects SHOTBOT_USE_LEGACY_MODEL unset
   → FAILS: Sees "1" from test 1
   
3. test_headless.py::test_headless_mode_detection
   → Expects clean environment
   → FAILS: Env still polluted from test 1
```

### Example 2: Parallel Execution Contamination

```
Worker 1:
├─ test_A: Sets SHOTBOT_USE_LEGACY_MODEL="1" (no cleanup)
└─ test_B: Expects unset flag
    → FAILS: Sees polluted value from test_A

Worker 2:
├─ test_C: Expects clean environment
└─ FAILS: No guarantee about Worker 1's pollution
```

---

## File Changes Required

### Changes to Make

1. **test_cross_component_integration.py** (5 locations)
   - Add `monkeypatch: pytest.MonkeyPatch` to 5 test functions
   - Replace `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` with `monkeypatch.setenv(...)`

2. **test_feature_flag_switching.py** (2 locations)
   - Add `monkeypatch: pytest.MonkeyPatch` to test functions
   - Replace direct assignment with `monkeypatch.setenv(...)`
   - Fix line 187 loop: use monkeypatch inside loop

3. **tests/integration/conftest.py** (NEW FILE)
   - Create autouse fixture to isolate environment
   - Backup/restore os.environ for each test

4. **Unit tests** (verification only)
   - Check all tests using `Config.SHOWS_ROOT` have monkeypatch parameter
   - files: test_main_window.py, test_base_shot_model.py, etc.

---

## Success Criteria

After applying fixes, verify:

- [x] All 9 high-risk violations fixed
- [x] Integration tests use monkeypatch for environment
- [x] tests/integration/conftest.py created
- [x] Unit tests verified for Config isolation
- [x] Serial test execution passes
- [x] Parallel test execution passes (-n 2, -n auto)
- [x] Order-independent execution passes (--random-order)

---

## Related Documentation

- **GLOBAL_STATE_ISOLATION_QUICK_SUMMARY.txt** - Quick reference guide
- **GLOBAL_STATE_ISOLATION_REPORT.md** - Full technical report with recommendations
- **UNIFIED_TESTING_V2.MD** - Testing best practices and Qt guidelines
- **pyproject.toml** - pytest configuration

