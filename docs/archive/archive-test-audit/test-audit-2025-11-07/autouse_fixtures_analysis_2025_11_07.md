# Autouse Fixtures Analysis - Shotbot Test Suite
Generated: 2025-11-07

## Executive Summary

**Total autouse fixtures found**: 30 across the test suite
- **Main conftest.py**: 9 autouse fixtures (mostly compliant)
- **Integration conftest.py**: 1 autouse fixture (problematic)
- **Individual test files**: 20 autouse fixtures (redundant/problematic)

## Key Findings

### Compliance with UNIFIED_TESTING_V2.MD
- ✅ **Essential fixtures present**: suppress_qmessagebox, stable_random_seed, qt_cleanup, clear_module_caches
- ❌ **Redundancy issues**: 30% of autouse fixtures are duplicate or conflicting
- ⚠️ **Name shadowing**: cleanup_qt_state and setup_and_teardown defined in multiple files
- ❌ **Non-compliant autouse usage**: Some fixtures should be explicit (reset_threede_finder, reset_singleton, ensure_qt_cleanup)

## Critical Issues

1. **Duplicate cleanup fixtures** (cleanup_threading_state and clear_module_caches both reset ProgressManager/NotificationManager)
2. **Name collisions** (cleanup_qt_state shadows parent fixture in 4 files)
3. **Redundant local fixtures** (test_threede_shot_grid.py and test_launcher_dialog.py cleanup_qt_state should be removed)
4. **Improper autouse conversion** (reset_threede_finder, reset_singleton, ensure_qt_cleanup for specific components should be explicit)

## Files Requiring Immediate Action

### High Priority
1. tests/conftest.py - Consolidate cleanup_threading_state into clear_module_caches
2. tests/unit/test_threede_shot_grid.py - Remove cleanup_qt_state (redundant)
3. tests/unit/test_launcher_dialog.py - Remove cleanup_qt_state (redundant)
4. tests/integration/test_async_workflow_integration.py - Remove duplicate cleanup_qt_state in classes

### Medium Priority
1. tests/unit/test_threede_scene_worker.py - Convert reset_threede_finder to explicit fixture
2. tests/unit/test_filesystem_coordinator.py - Convert reset_singleton to explicit fixture
3. tests/unit/test_command_launcher.py - Convert ensure_qt_cleanup to explicit fixture
4. tests/integration/conftest.py - Consolidate clear_singleton_state or remove

### Low Priority
1. tests/conftest.py - Remove reset_config_state (monkeypatch auto-restores)
2. tests/conftest.py - Clarify/remove cleanup_launcher_manager_state (only gc.collect())
3. tests/reliability_fixtures.py - Remove cleanup_qt_objects if not actively used

## Fixture Scope Analysis

- **Session scope (1)**: qapp (appropriate)
- **Function scope (29)**: All others (mostly appropriate)
- **Method scope (6)**: setup_and_teardown fixtures in integration tests (should be class-scoped or moved to conftest)

## 75 time.sleep() calls found

- Most in intended locations (test_cache_manager.py, test_process_pool_manager.py)
- Could be replaced with condition-based waiting in some cases per UNIFIED_TESTING_V2.MD
