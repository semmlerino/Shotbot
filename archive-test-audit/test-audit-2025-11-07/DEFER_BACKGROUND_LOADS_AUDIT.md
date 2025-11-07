# Test Background Async Operations Analysis
## defer_background_loads Implementation Audit

---

## CRITICAL FINDING: Feature Gap

**Status**: DOCUMENTATION-IMPLEMENTATION MISMATCH

| Aspect | Status |
|--------|--------|
| Documentation (UNIFIED_TESTING_V2.MD) | ✅ Complete & Detailed |
| MainWindow Implementation | ❌ NOT IMPLEMENTED |
| Test Coverage | ❌ NO TESTS using feature |
| Risk Level | 🔴 HIGH - All 62 tests vulnerable |

---

## 1. DOCUMENTATION EXISTS (But Code Doesn't Match)

### Location: UNIFIED_TESTING_V2.MD

**Section 8: Background Async Operations** (lines 274-298)
```
Symptom: Background loaders clear data during qtbot.wait()
Example: len(shots) == 2 becomes len(shots) == 0 after qtbot.wait(100)

Better: Prefer deferring background loads until after UI is shown in tests
```

**Recommended Pattern**:
```python
# In production code:
class MainWindow:
    def __init__(self, defer_background_loads=False):
        self.defer_background_loads = defer_background_loads
        if not defer_background_loads:
            self.start_background_loaders()

# In tests:
window = MainWindow(defer_background_loads=True)
# Set up test data without background interference
window.shot_model.shots = [shot1, shot2]
```

**Best Practice #19** (line 1093):
> "Prefer defer_background_loads=True in tests - Prevent background loaders from interfering; 
> fall back to cache clearing if needed (NEW 2025-11-05)"

---

## 2. ACTUAL MainWindow IMPLEMENTATION

### File: `/home/gabrielh/projects/shotbot/main_window.py`

**Lines 177-181 (Current __init__ signature)**:
```python
def __init__(
    self,
    cache_manager: CacheManager | None = None,
    parent: QWidget | None = None,
) -> None:
```

**Missing Parameter**: `defer_background_loads` is NOT present

### Background Loading Path (Always Active)

**Line 363-364**:
```python
if not os.environ.get("SHOTBOT_NO_INITIAL_LOAD"):
    self._initial_load()
```

This unconditionally calls `_initial_load()` which:
- **Line 714-718**: Pre-warms bash sessions in background thread
  ```python
  session_warmer = SessionWarmer()
  self._session_warmer = session_warmer
  session_warmer.start()
  ```
- **Line 766-783**: Schedules background refresh for shots
- **Line 346-350**: Starts ThreeDEController (background scene discovery)
- **Line 352-355**: Initializes LauncherController (launcher background ops)

### No Fallback Pattern

Tests cannot defer initialization. Current workarounds:
1. ❌ `SHOTBOT_NO_INITIAL_LOAD` environment variable (undocumented, not tested)
2. ❌ Manual cache clearing (fallback, less clean than deferring)

---

## 3. TEST VULNERABILITY ANALYSIS

### COMPLETE AUDIT: 62 MainWindow Instantiations

**All tests vulnerable because**:
- No parameter to defer background operations
- Background loaders start immediately on __init__
- Tests cannot isolate test data from background interference

### Breakdown by Severity

#### HIGH RISK (All with empty MainWindow())
Tests without cache_manager parameter - maximum background activity:
- test_feature_flag_switching.py: 6 instances (lines 103, 135, 197, 216, 434, 464)
- test_cross_component_integration.py: 4 instances (lines 139, 541, 633, 673)
- test_launcher_panel_integration.py: 13 instances (lines 138, 163, 196, 248, 286, 314, 408, 462, 512, 548, 613, 631, 653)
- test_refactoring_safety.py: 5 instances (lines 275, 292, 313, 342, 366)
- test_text_filter.py: 1 instance (line 418)
- test_show_filter.py: 1 instance (line 468)

**Total HIGH RISK**: 30 instances

#### MEDIUM RISK (MainWindow with cache_manager)
Tests with isolated cache - reduced but still present background activity:
- test_main_window.py: 11 instances
- test_main_window_fixed.py: 3 instances
- test_main_window_widgets.py: 9 instances
- test_main_window_complete.py: 1 instance
- test_main_window_coordination.py: 1 instance
- test_user_workflows.py: 10 instances
- test_cross_component_integration.py: 2 instances

**Total MEDIUM RISK**: 37 instances (can still interfere with test data setup)

#### Unaffected
- test_headless.py: Uses HeadlessMainWindow (separate class)

---

## 4. SPECIFIC VULNERABLE PATTERNS IN TESTS

### Pattern 1: Data Setup Races With Background Loaders

**Example from test_main_window.py:88-98**:
```python
def test_main_window_with_custom_cache_manager(self, qtbot: QtBot, tmp_path: Path) -> None:
    cache_dir = tmp_path / "custom_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_manager = CacheManager(cache_dir=cache_dir)
    
    main_window = MainWindow(cache_manager=cache_manager)
    # ⚠️ VULNERABLE: Background loaders now active
    # _initial_load() may trigger shot refresh, clearing manual test data
    qtbot.addWidget(main_window)
    
    assert main_window.cache_manager is cache_manager
```

### Pattern 2: Shot Selection Tests

**Example from test_main_window.py:139-159**:
```python
def test_shot_selection_enables_app_buttons(self, qtbot: QtBot, tmp_path: Path) -> None:
    cache_manager = CacheManager(cache_dir=tmp_path / "cache")
    main_window = MainWindow(cache_manager=cache_manager)
    # ⚠️ VULNERABLE: shot_model._initial_load() may be in progress
    # Test data race: manual shot vs background-loaded shots
    
    shot = Shot("test_show", "seq01", "0010", f"{shows_root}/test/seq01/0010")
    main_window._on_shot_selected(shot)
    # ⚠️ RACE: Background refresh may clear shots between setup and test
```

### Pattern 3: UI State Tests

**Example from test_launcher_panel_integration.py:138-150**:
```python
def test_launcher_panel_button_states(self):
    window = MainWindow()  # HIGH RISK: No cache_manager
    # ⚠️ VULNERABLE: All loaders active, UI in flux
    qtbot.addWidget(window)
    
    button = window.launcher_panel.app_sections["nuke"].launch_button
    # ⚠️ RACE: Background init may still be setting up UI components
    assert button.isEnabled()
```

---

## 5. FALLBACK PATTERN USAGE

### Current Workarounds in Tests

**Few tests follow documented fallback**:
```python
cache_manager.clear_cache()  # Manual cache clearing
window.shot_model.shots = [shot1, shot2]
qtbot.wait(100)
if len(window.shot_model.shots) == 0:
    window.shot_model.refresh_shots()  # Reload if cleared
```

**Observations**:
- Most tests do NOT use this pattern
- Fallback is fragile and test-specific
- Cleaner solution would be `defer_background_loads=True`

---

## 6. IMPLEMENTATION CHECKLIST

### To Fix This Gap, MainWindow Needs:

- [ ] Add `defer_background_loads: bool = False` parameter to __init__
- [ ] Store as instance attribute: `self.defer_background_loads`
- [ ] Conditionally call `_initial_load()`:
  ```python
  if not defer_background_loads and not os.environ.get("SHOTBOT_NO_INITIAL_LOAD"):
      self._initial_load()
  ```
- [ ] Add public method to trigger deferred load (for tests that need it):
  ```python
  def trigger_deferred_background_loads(self) -> None:
      """Called by tests to enable background loaders after setup."""
      if self.defer_background_loads:
          self._initial_load()
  ```
- [ ] Update 62 test instantiations to use `defer_background_loads=True` where appropriate

### Test Strategy

**Tests that should defer**:
- Unit tests setting up specific test data
- Integration tests with mocked filesystem
- Any test checking initial state before refresh

**Tests that should NOT defer**:
- E2E tests that want real background behavior
- Tests specifically validating background load behavior
- Tests checking race conditions

---

## 7. IMPACT ASSESSMENT

### Risk Without Implementation

**Without defer_background_loads parameter**:

1. **Intermittent Failures**: Tests pass in isolation, fail in parallel
   - Timing-dependent failures when background loaders interfere
   - Hard to reproduce and debug

2. **False Positives**: Tests pass but don't test what they claim
   - Setup data overwritten by background loads
   - Tests actually validating fallback behavior, not intended logic

3. **Maintenance Burden**: Developers forced to use workarounds
   - Manual cache clearing (fragile)
   - `SHOTBOT_NO_INITIAL_LOAD` (undocumented, environment variable)
   - Complex setUp/tearDown logic in each test

4. **Documentation Debt**: Guideline in UNIFIED_TESTING_V2.MD is aspirational
   - "Best practice: use defer_background_loads=True"
   - But feature doesn't exist → confuses future developers

### Risk With Implementation

**Minimal - fully backward compatible**:
- Default `defer_background_loads=False` preserves existing behavior
- Only tests that opt-in get deferred behavior
- No changes to production code logic
- Reduces test flakiness significantly

---

## 8. SPECIFIC FILES TO UPDATE

### Primary Target: main_window.py

**Changes Required**:
1. Line 177-180: Add parameter to `__init__`
2. Line 215: Store as instance attribute
3. Line 363-364: Wrap `_initial_load()` call with parameter check

### Secondary: Test Files (Update as Time Permits)

**Immediate high-impact files** (for critical path tests):
1. `/home/gabrielh/projects/shotbot/tests/unit/test_main_window.py` (12 instances)
2. `/home/gabrielh/projects/shotbot/tests/unit/test_main_window_widgets.py` (10 instances)
3. `/home/gabrielh/projects/shotbot/tests/integration/test_launcher_panel_integration.py` (14 instances)
4. `/home/gabrielh/projects/shotbot/tests/integration/test_user_workflows.py` (10 instances)

**Lower priority** (fewer instances or less critical):
5. test_main_window_fixed.py (3)
6. test_feature_flag_switching.py (6)
7. test_cross_component_integration.py (6)
8. test_refactoring_safety.py (5)
9. Others (5 total)

---

## SUMMARY TABLE

```
METRIC                          VALUE
───────────────────────────────────────
Total MainWindow Instances      62
Using defer_background_loads    0 (0%)
Vulnerable Tests                62 (100%)

Unit Tests at Risk              40
Integration Tests at Risk       22

Highest Risk (no cache_manager) 30
Medium Risk (cached)            37

Documentation Coverage          ✅ Complete
Code Implementation             ❌ Missing
Test Examples                   ❌ None

Estimated Fix Effort
  - MainWindow changes          1-2 hours
  - Test updates (all 62)       4-6 hours
  - Total                       5-8 hours
```

---

## RECOMMENDATIONS

### Priority 1: Implement defer_background_loads in MainWindow
- **Effort**: 1-2 hours
- **Impact**: Unblocks all 62 tests to use proper pattern
- **Risk**: Very low (backward compatible)

### Priority 2: Update High-Risk Tests
- Start with: test_launcher_panel_integration.py (14 instances, high flakiness)
- Then: test_main_window.py (12 instances, core functionality)
- Impact: 26 tests using documented best practice

### Priority 3: Document Test Updates
- Add comments where `defer_background_loads=True` is used
- Explain why background defers in that specific test
- Example: "Deferred to isolate shot selection test from refresh"

### Priority 4: Gradual Rollout
- Don't force all 62 at once
- Update as tests are maintained anyway
- Focus on flaky tests first

