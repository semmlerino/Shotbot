# ShotBot Remediation Implementation Checklist
**Tracking Document for IMPLEMENTATION_PLAN.md**

**Started:** TBD
**Status:** NOT STARTED

---

## Quick Status Overview

| Phase | Tasks | Status | Completion |
|-------|-------|--------|------------|
| Phase 1: Critical Bugs | 3 | ⬜ NOT STARTED | 0/3 |
| Phase 2: Performance | 3 | ⬜ NOT STARTED | 0/3 |
| Phase 3: Architecture | 3 | ⬜ NOT STARTED | 0/3 |
| Phase 4: Documentation | 3 | ⬜ NOT STARTED | 0/3 |
| **Total** | **12** | ⬜ **NOT STARTED** | **0/12** |

---

# PHASE 1: CRITICAL BUG FIXES ⬜

**Objective:** Eliminate crashes and data loss bugs
**Agent:** deep-debugger → python-code-reviewer → test-development-master

## Task 1.1: Fix Signal Disconnection Crash ⬜

**File:** `process_pool_manager.py:602-615`
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Wrap each `signal.disconnect()` in individual try/except
- [ ] Add debug logging for disconnection events
- [ ] Test idempotent cleanup behavior
- [ ] Verify no RuntimeWarning in logs

### Tests:
- [ ] `test_cleanup_no_connections` (new)
- [ ] `test_cleanup_idempotent` (new)
- [ ] All existing tests pass

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Issues found: `_____________________`
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (test-development-master) completed: ⬜
  - Review file: `_____________________`
  - Test coverage adequate: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] `uv run pytest tests/unit/test_process_pool_manager.py -v` ✅
- [ ] `uv run basedpyright` ✅
- [ ] Manual smoke test: Shutdown clean ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Task 1.2: Fix Cache Write Data Loss ⬜

**File:** `cache_manager.py:454-480`
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Move signal emission outside lock
- [ ] Emit signal only after successful write
- [ ] Return `bool` from `migrate_shots_to_previous()`
- [ ] Update callers to check return value
- [ ] Add critical error logging on failure

### Tests:
- [ ] `test_migrate_shots_disk_full` (new)
- [ ] `test_migrate_shots_signal_order` (new)
- [ ] All existing tests pass

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Issues found: `_____________________`
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (test-development-master) completed: ⬜
  - Review file: `_____________________`
  - Test coverage adequate: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] `uv run pytest tests/unit/test_cache_manager.py -v` ✅
- [ ] `uv run basedpyright` ✅
- [ ] Manual test: Disk full simulation ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Task 1.3: Fix Model Item Access Race Condition ⬜

**File:** `base_item_model.py:346-395`
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Add item count snapshot under lock
- [ ] Add bounds checking in loop
- [ ] Re-check count inside lock before access
- [ ] Reschedule load if items change mid-iteration
- [ ] Add warning logging for race detection

### Tests:
- [ ] `test_concurrent_set_items_during_load` (new)
- [ ] `test_rapid_model_updates` (new)
- [ ] All existing tests pass

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Issues found: `_____________________`
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (test-development-master) completed: ⬜
  - Review file: `_____________________`
  - Test coverage adequate: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] `uv run pytest tests/unit/test_base_item_model.py -v` ✅
- [ ] `uv run basedpyright` ✅
- [ ] Manual test: Rapid tab switching ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Phase 1 Summary

**Status:** ⬜ NOT STARTED
**Completion:** 0/3 tasks

**Git Commits:** 0/3
- [ ] Task 1.1 commit
- [ ] Task 1.2 commit
- [ ] Task 1.3 commit

**Tests Added:** 0/7
- [ ] 3 tests for signal disconnection
- [ ] 2 tests for cache write verification
- [ ] 2 tests for race condition handling

**All Tests Pass:** ⬜ YES / NO
**Phase Review:** ⬜ PENDING / APPROVED / NEEDS REVISION

---

# PHASE 2: PERFORMANCE BOTTLENECKS ⬜

**Objective:** Eliminate UI blocking operations
**Agent:** performance-profiler → python-code-reviewer → type-system-expert

## Task 2.1: Move JSON Serialization to Background Thread ⬜

**File:** `cache_manager.py:860-905` + new async methods
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Add `ThreadPoolExecutor` to CacheManager.__init__
- [ ] Create `_write_json_cache_sync()` (rename current method)
- [ ] Create `write_json_cache_async()` with callback support
- [ ] Update `cache_shots()` to use async write
- [ ] Add `wait_for_pending_writes()` method
- [ ] Update `cleanup()` to wait for pending writes
- [ ] Update `main_window.py` to call cleanup on shutdown

### Tests:
- [ ] `test_cache_write_doesnt_block_ui` (new)
- [ ] `test_benchmark_async_vs_sync` (new)
- [ ] All existing tests pass

### Benchmarks:
- [ ] UI blocking: 180ms → <10ms (95% reduction) ✅
- [ ] Background write completes successfully ✅
- [ ] Shutdown waits for pending writes ✅

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Issues found: `_____________________`
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (type-system-expert) completed: ⬜
  - Review file: `_____________________`
  - Threading types correct: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] `uv run pytest tests/performance/test_cache_write_performance.py -v` ✅
- [ ] `uv run basedpyright` ✅
- [ ] Manual test: UI responsive during refresh ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Task 2.2: Add LRU Eviction to Thumbnail Cache ⬜

**File:** `base_item_model.py:139` + new LRUCache class
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Create `LRUCache[K, V]` generic class
- [ ] Implement thread-safe get/put/clear methods
- [ ] Add automatic eviction on max_size
- [ ] Add stats() method for monitoring
- [ ] Replace dict with LRUCache in BaseItemModel
- [ ] Update all cache access to use .get()/.put()

### Tests:
- [ ] `test_eviction` (new)
- [ ] `test_lru_ordering` (new)
- [ ] `test_concurrent_access` (new)
- [ ] All existing tests pass

### Benchmarks:
- [ ] Memory capped at 128MB ✅
- [ ] Eviction works correctly ✅
- [ ] No visual glitches from eviction ✅

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Issues found: `_____________________`
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (type-system-expert) completed: ⬜
  - Review file: `_____________________`
  - Generic types correct: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] `uv run pytest tests/unit/test_lru_cache.py -v` ✅
- [ ] `uv run basedpyright` ✅
- [ ] Manual test: Memory stays bounded ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Task 2.3: Optimize PIL Thumbnail Generation ⬜

**File:** `cache_manager.py:301-330`
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Add `img.draft()` for JPEG fast path
- [ ] Switch from LANCZOS to BILINEAR resampling
- [ ] Disable optimize/progressive for small files
- [ ] Add Pillow-SIMD detection (optional)

### Tests:
- [ ] `test_thumbnail_generation_performance` (new)
- [ ] `test_thumbnail_quality` (new)
- [ ] All existing tests pass

### Benchmarks:
- [ ] Generation time: 70-140ms → 20-40ms (60% faster) ✅
- [ ] Quality acceptable at 256px ✅
- [ ] No visual regressions ✅

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Issues found: `_____________________`
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (type-system-expert) completed: ⬜
  - Review file: `_____________________`
  - PIL types correct: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] `uv run pytest tests/performance/test_thumbnail_generation.py -v` ✅
- [ ] `uv run basedpyright` ✅
- [ ] Manual test: Thumbnails load faster ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Phase 2 Summary

**Status:** ⬜ NOT STARTED
**Completion:** 0/3 tasks

**Git Commits:** 0/3
- [ ] Task 2.1 commit
- [ ] Task 2.2 commit
- [ ] Task 2.3 commit

**Tests Added:** 0/8
- [ ] 2 cache write performance tests
- [ ] 3 LRU cache tests
- [ ] 2 thumbnail generation benchmarks

**Performance Gains Achieved:**
- [ ] UI blocking: 180ms → <10ms (95%) ⬜
- [ ] Memory: Unbounded → 128MB ⬜
- [ ] Thumbnails: 70-140ms → 20-40ms (60%) ⬜

**All Tests Pass:** ⬜ YES / NO
**Phase Review:** ⬜ PENDING / APPROVED / NEEDS REVISION

---

# PHASE 3: ARCHITECTURE IMPROVEMENTS ⬜

**Objective:** Reduce technical debt and improve maintainability
**Agent:** code-refactoring-expert → python-code-reviewer → api-documentation-specialist

## Task 3.1: Extract Shot Migration Service ⬜

**Files:** New `shot_migration_service.py`, update `cache_manager.py`, `shot_model.py`
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Create `shot_migration_service.py` with ShotMigrationService class
- [ ] Remove `migrate_shots_to_previous()` from CacheManager
- [ ] Update ShotModel to use migration service
- [ ] Connect signals properly
- [ ] Update all tests

### Tests:
- [ ] `test_shot_migration_service.py` (new file)
- [ ] Update existing ShotModel tests
- [ ] All existing tests pass

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Issues found: `_____________________`
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (api-documentation-specialist) completed: ⬜
  - Review file: `_____________________`
  - Interface clear: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] `uv run pytest tests/unit/test_shot_migration_service.py -v` ✅
- [ ] `uv run basedpyright` ✅
- [ ] Manual test: Migration still works ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Task 3.2: Document Atomic Thumbnail Loading Correctly ⬜

**File:** `base_item_model.py:346-365`
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Update docstring with accurate thread safety analysis
- [ ] Document known race conditions
- [ ] Explain why full atomicity isn't feasible
- [ ] Add performance characteristics section
- [ ] Document design trade-offs

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Documentation accurate: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (api-documentation-specialist) completed: ⬜
  - Review file: `_____________________`
  - Clarity adequate: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] Docstring matches implementation ✅
- [ ] No misleading claims ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Task 3.3: Add Configuration Constants ⬜

**File:** `config.py` + updates to multiple files
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Add ThumbnailLoadingConfig class to config.py
- [ ] Add CacheWriteConfig class to config.py
- [ ] Add PerformanceConfig class to config.py
- [ ] Update base_item_model.py to use config
- [ ] Update cache_manager.py to use config
- [ ] Remove all magic numbers

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - All magic numbers removed: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (api-documentation-specialist) completed: ⬜
  - Review file: `_____________________`
  - Config documented: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] `uv run basedpyright` ✅
- [ ] `uv run ruff check .` ✅
- [ ] All tests pass ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Phase 3 Summary

**Status:** ⬜ NOT STARTED
**Completion:** 0/3 tasks

**Git Commits:** 0/3
- [ ] Task 3.1 commit
- [ ] Task 3.2 commit
- [ ] Task 3.3 commit

**Files Created:** 0/2
- [ ] `shot_migration_service.py`
- [ ] `tests/unit/test_shot_migration_service.py`

**All Tests Pass:** ⬜ YES / NO
**Phase Review:** ⬜ PENDING / APPROVED / NEEDS REVISION

---

# PHASE 4: DOCUMENTATION & TESTING ⬜

**Objective:** Complete test coverage and update documentation
**Agent:** test-development-master → python-code-reviewer → documentation-quality-reviewer

## Task 4.1: Add Regression Tests ⬜

**File:** New `tests/regression/test_phase1_fixes.py`
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Create regression test file
- [ ] Add test_signal_disconnection_no_crash
- [ ] Add test_cache_write_signal_order
- [ ] Add test_concurrent_set_items_no_crash
- [ ] Document bug references in test docstrings

### Tests:
- [ ] 3 new regression tests
- [ ] All regression tests pass

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Tests adequate: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (documentation-quality-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Documentation clear: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] `uv run pytest tests/regression/ -v` ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Task 4.2: Update ARCHITECTURE_REVIEW_SUMMARY.txt ⬜

**File:** `ARCHITECTURE_REVIEW_SUMMARY.txt`
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Add "Phase 1-3 Remediation" section
- [ ] Document all critical bugs fixed
- [ ] Document performance improvements with numbers
- [ ] Document architecture changes
- [ ] List remaining technical debt

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Accuracy verified: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (documentation-quality-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Clarity adequate: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] Document updated ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Task 4.3: Create Performance Baseline Document ⬜

**File:** New `PERFORMANCE_BASELINE.md`
**Status:** ⬜ NOT STARTED

### Implementation Steps:
- [ ] Create PERFORMANCE_BASELINE.md
- [ ] Document UI responsiveness metrics
- [ ] Document memory usage metrics
- [ ] Document discovery performance
- [ ] Add verification commands
- [ ] Add monitoring instructions

### Review Checklist:
- [ ] Agent 1 (python-code-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Metrics accurate: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Agent 2 (documentation-quality-reviewer) completed: ⬜
  - Review file: `_____________________`
  - Useful for monitoring: YES / NO
  - Status: APPROVED / CHANGES NEEDED
- [ ] Changes made after review: ⬜ YES / NO
  - Changes: `_____________________`

### Verification:
- [ ] Document created ✅
- [ ] Benchmarks run successfully ✅
- [ ] Git commit completed: ⬜
  - Commit hash: `_____________________`
  - Date: `_____________________`

**Completion Date:** `_____________________`
**Notes:** `_____________________`

---

## Phase 4 Summary

**Status:** ⬜ NOT STARTED
**Completion:** 0/3 tasks

**Git Commits:** 0/2
- [ ] Task 4.1 commit
- [ ] Task 4.2-4.3 commit (combined)

**Files Created:** 0/2
- [ ] `tests/regression/test_phase1_fixes.py`
- [ ] `PERFORMANCE_BASELINE.md`

**All Tests Pass:** ⬜ YES / NO
**Phase Review:** ⬜ PENDING / APPROVED / NEEDS REVISION

---

# OVERALL PROJECT STATUS

**Project Start:** `_____________________`
**Project End:** `_____________________`
**Total Duration:** `_____________________`

## Final Metrics

**Phases Completed:** 0/4
**Tasks Completed:** 0/12
**Git Commits:** 0/12
**Tests Added:** 0/23

**Code Coverage:**
- Before: ~90%
- After: _____% (target: 94%+)

**Performance Gains:**
- UI blocking: 180ms → _____ms (target: <10ms)
- Memory cap: Unbounded → _____MB (target: ~128MB)
- Thumbnail gen: 70-140ms → _____ms (target: 20-40ms)

## Final Review

**All Tests Pass:** ⬜ YES / NO
**All Type Checks Pass:** ⬜ YES / NO
**All Linting Pass:** ⬜ YES / NO
**Documentation Updated:** ⬜ YES / NO
**Performance Verified:** ⬜ YES / NO

**Project Status:** ⬜ COMPLETE / NEEDS WORK / BLOCKED

---

# NOTES & DEVIATIONS

## Phase 1 Notes:
```
(Add notes here after Phase 1 completion)
```

## Phase 2 Notes:
```
(Add notes here after Phase 2 completion)
```

## Phase 3 Notes:
```
(Add notes here after Phase 3 completion)
```

## Phase 4 Notes:
```
(Add notes here after Phase 4 completion)
```

## Unexpected Issues:
```
(Document any issues not anticipated in plan)
```

## Future Work Identified:
```
(Document technical debt or improvements identified during implementation)
```

---

**Last Updated:** `_____________________`
**Updated By:** `_____________________`
