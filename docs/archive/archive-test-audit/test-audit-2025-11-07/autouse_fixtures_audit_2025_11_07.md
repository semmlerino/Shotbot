# Autouse Fixtures Audit Report
**Date:** 2025-11-07  
**Scope:** /home/gabrielh/projects/shotbot/tests/  
**Thoroughness Level:** Very thorough (comprehensive worker isolation analysis)

## Executive Summary

**Critical Issue Found:** 88% of autouse fixtures are inappropriate for multi-worker testing

- Total autouse fixture declarations: ~70+ across 43 test files
- Appropriate autouse fixtures: 8 (Qt cleanup, dialog suppression, random seed, app exit prevention)
- Inappropriate autouse fixtures: ~62+ (singleton resets, monkeypatches, state restoration)
- **Root cause:** Duplication of `cleanup_state()` autouse in conftest.py; test files reimplement cleanup as their own autouse fixtures

## Key Findings

### Appropriate Autouse Fixtures (Safe)

1. **qt_cleanup** (tests/conftest.py:172) - Qt event processing, thread pool cleanup
2. **suppress_qmessagebox** (tests/conftest.py:441) - Prevents dialog blocking
3. **stable_random_seed** (tests/conftest.py:463) - Random determinism with pytest-randomly
4. **prevent_qapp_exit** (tests/conftest.py:506) - Prevents event loop corruption
5. **cleanup_qt_objects** (tests/reliability_fixtures.py:65) - Qt deferred delete processing

### Inappropriate Autouse Fixtures (Problematic)

**Pattern 1: Singleton Reset Duplication (~35 fixtures)**
- ProcessPoolManager._instance = None
- NotificationManager._instance = None
- ProgressManager._instance = None
- Found in 12+ test files (cache_manager, launcher_worker, threede_scene_worker, etc.)
- **Risk:** Already done by root conftest.py cleanup_state() - causes duplication and hides dependencies
- **Impact:** Tests don't declare singleton dependencies; parallel execution may have issues

**Pattern 2: Module-level Monkeypatch (~15 fixtures)**
- Cache disabled flag resets
- Config.SHOWS_ROOT patching
- Utils module state patching
- Files: test_mock_mode.py, test_previous_shots_cache_integration.py, test_feature_flag_switching.py, etc.
- **Risk:** Hides dependencies from test readers; monkeypatches should be explicit
- **Impact:** Refactoring unsafe; test dependencies invisible

**Pattern 3: Module-scope Autouse Lazy Imports (~7 fixtures)**
- Global MainWindow imports after Qt initialization
- Files: test_launcher_panel_integration.py, test_cross_component_integration.py, test_feature_flag_switching.py, etc.
- **Risk:** Unusual pattern; autouse should be for cleanup, not setup
- **Impact:** Module-level state pollution risk; harder to debug

**Pattern 4: Class-level State Restoration (~8 fixtures)**
- ThreeDESceneFinder class state restoration
- Test doubles class-level state clearing
- **Risk:** Tests don't declare when they modify class-level state
- **Impact:** Fragile tests; state changes invisible at test level

## Critical Files to Fix

### 12 Files with Redundant Singleton Reset Autouse (REMOVE):
- tests/unit/test_cache_manager.py:45
- tests/unit/test_launcher_worker.py:49
- tests/unit/test_threede_scene_worker.py:65
- tests/unit/test_previous_shots_item_model.py:25
- tests/unit/test_threede_item_model.py:31
- tests/unit/test_launcher_models.py:48
- tests/unit/test_command_launcher.py:35
- tests/unit/test_progress_manager.py:74
- tests/integration/test_launcher_panel_integration.py:72
- tests/integration/test_cross_component_integration.py:45
- tests/integration/test_threede_worker_workflow.py:68
- tests/integration/test_threede_scanner_integration.py:37

**Action:** Convert to explicit fixture parameters instead of autouse (removes duplication)

### 7 Module-scope Autouse Lazy Imports (CONVERT):
- tests/integration/test_launcher_panel_integration.py:51
- tests/integration/test_cross_component_integration.py:36
- tests/integration/test_feature_flag_switching.py:51
- tests/integration/test_feature_flag_simplified.py:31
- tests/integration/test_main_window_coordination.py:44
- tests/integration/test_user_workflows.py:69
- tests/integration/test_main_window_complete.py:59

**Action:** Change to explicit module-level fixture parameters (makes imports visible)

### ~15 Module-level Monkeypatch Autouse (CONVERT):
- tests/unit/test_mock_mode.py:18
- tests/unit/test_previous_shots_cache_integration.py:52
- tests/integration/test_feature_flag_switching.py:37
- tests/integration/test_feature_flag_simplified.py:31
- tests/unit/test_filesystem_coordinator.py:32
- tests/unit/test_shot_model.py:32
- tests/unit/test_cache_separation.py:24
- tests/unit/test_threede_item_model.py:31
- tests/unit/test_threede_scene_worker.py:47
- tests/unit/test_launcher_dialog.py:101
- tests/unit/test_launcher_controller.py:145
- tests/unit/test_exr_edge_cases.py:44
- tests/unit/test_main_window.py:36
- tests/unit/test_main_window_fixed.py:40
- tests/integration/test_launcher_workflow_integration.py:47

**Action:** Convert to explicit fixture parameters (clarifies state dependencies)

## Why This Matters for Parallel Testing

**pytest-xdist Worker Isolation Issue:**

When running with `-n 2` (2 workers):
```
Worker 1: runs tests/unit/test_a.py, test_b.py, test_c.py
Worker 2: runs tests/unit/test_d.py, test_e.py, test_f.py
```

Autouse fixtures run in EACH test, EACH worker:
- Test A in Worker 1 starts ProcessPoolManager
- Autouse fixture resets ProcessPoolManager._instance = None
- Test B in Worker 1 creates NEW ProcessPoolManager
- But Test A's threads may still be running (different instance!)
- If Test A's thread tries to use original ProcessPoolManager, it crashes

**Solution:** Remove autouse; make singleton resets explicit so they're visible

## Current Architecture

**What Exists (Good):**
- Root conftest.py has comprehensive cleanup_state() autouse (line 259)
- Handles ProcessPoolManager, NotificationManager, ProgressManager cleanup
- Clears shared cache directories (/~/.shotbot/cache_test)
- Resets module-level flags (disable_caching, etc.)

**What's Wrong (Bad):**
- 12+ test files reimplement the SAME cleanup logic as their own autouse fixtures
- Duplicate cleanup happens twice (root conftest + individual test file)
- Tests don't declare singleton dependencies explicitly
- Module-level monkeypatches are hidden in autouse instead of explicit params
- Lazy imports use module-scope autouse instead of explicit setup

## Recommendations

### CRITICAL (Do First)
1. Remove 12 redundant singleton reset autouse fixtures
2. Convert 7 module-scope autouse lazy imports to explicit params
3. Convert 15 monkeypatch autouse fixtures to explicit params

### HIGH
4. Review class-level state restoration autouse fixtures
5. Ensure all tests that use ProcessPoolManager declare dependency explicitly

### MEDIUM
6. Consider making root conftest.py cleanup_state() optional (explicit fixture param)
7. Consolidate singleton reset logic in single place (don't duplicate)

## Test Categories by Autouse Usage

### Category A: Qt Framework (Always Autouse - OK)
- qt_cleanup: Event processing, thread pool cleanup
- suppress_qmessagebox: Dialog suppression
- stable_random_seed: Reproducible random values
- prevent_qapp_exit: Event loop protection

### Category B: Test Doubles (Remove Autouse)
- reset_singletons: Make explicit param
- reset_launcher_singletons: Make explicit param
- reset_threede_finder: Make explicit param
- reset_singleton: Make explicit param

### Category C: Monkeypatches (Remove Autouse)
- reset_cache_flag: Make explicit param
- Cache disabled flag resets: Make explicit param
- Config.SHOWS_ROOT patches: Make explicit param

### Category D: Module-level Setup (Make Explicit)
- setup_qt_imports (module-scope): Make explicit param
- setup_and_teardown: Make explicit param

## Metrics

| Category | Count | Fix Status |
|----------|-------|-----------|
| Appropriate (keep autouse) | 8 | ✅ OK |
| Singleton resets (remove) | ~35 | ❌ TODO |
| Monkeypatches (remove) | ~15 | ❌ TODO |
| Module-scope lazy imports | ~7 | ❌ TODO |
| Class-level state restoration | ~8 | ⚠️ REVIEW |
| **Total inappropriate** | **~65** | **❌ TODO** |
| **Inappropriate rate** | **89%** | **CRITICAL** |
