**Findings (ordered by impact)**

1. ~~Large chunk of suite is non-test/demo content being collected, adding bloat with near-zero coverage value.~~
**DONE** (cfacf835) — Deleted 24 files: 7 stub files, 3 template/demo files, 3 script-style benchmarks, 3 misplaced infrastructure files (test_doubles.py, test_protocols.py, doubles.py), 6 redundant parser/pipeline files, 1 ThreeDEOptimization duplicate, 1 dead feature-flag file. Inlined two protocols from test_protocols.py into their sole consumers (test_main_window.py, test_shot_model.py). **79 tests removed.**

2. ~~Parser/pipeline tests are heavily duplicative and script-style.~~
**DONE** (cfacf835) — Deleted all 6 redundant parser files (test_ws_parsing.py, test_ws_parsing_standalone.py, test_shot_parsing.py, test_shot_extraction_standalone.py, test_shot_processing_pipeline.py, test_final_pipeline_validation.py). Coverage preserved in test_scene_parser.py (33), test_optimized_shot_parser.py (25), test_targeted_shot_finder.py (43), test_shot_parsing_vfx_paths.py (8). **18 tests removed.**

3. ~~Subprocess integration coverage is over-replicated across four files.~~
**DONE** (38f689d3) — Consolidated to single file test_real_subprocess.py (25 tests). Deleted test_subprocess_smoke.py. Migrated 3 unique shell-chaining tests from test_real_command_patterns.py. Removed untracked test_real_workspace_commands.py and test_real_command_patterns.py. **30 net tests removed.**

4. ~~Feature-flag tests are duplicated and inconsistent on env var semantics.~~
**DONE** (cfacf835) — Deleted test_feature_flag_switching.py (11 tests for non-existent `SHOTBOT_USE_LEGACY_MODEL` env var). test_feature_flag_simplified.py (6 tests) retained as the canonical suite. **11 tests removed.**

5. ~~MainWindow coverage is spread across many large suites with repeated scenarios.~~
**DONE** (b1f90de3) — Deleted test_main_window_fixed.py (5 tests) and test_main_window_complete.py (12 tests). Retained 80 tests across test_main_window.py (29), test_main_window_widgets.py (30), test_main_window_coordination.py (13), test_user_workflows.py (8). **16 tests removed** (was 17 in plan, actual was 16).

6. ~~`test_threede_optimization_coverage_fixed.py` is low-value duplication.~~
**DONE** (cfacf835) — Deleted. 3 tests that were subsets of test_threede_optimization_coverage.py (20 tests) using a fake local DirectoryCache.

7. Performance traps are widespread: 66 `time.sleep` occurrences across 68 files.
**DEFERRED** — Most sleeps are legitimate (race condition tests, subprocess timeouts). Would require event-driven wait rewrite per test; low ROI without measured slowdown.

8. Test-double infrastructure is fragmented (`doubles_library.py`, `doubles_extended.py`, `fixtures/test_doubles.py`).
**DEFERRED** — Larger refactor with no functional impact. `tests/unit/test_doubles.py` and `tests/doubles.py` (the unused duplicates) were deleted in finding 1. Remaining fragmentation is in active fixture files.

---

**Summary**

| Finding | Status | Tests removed |
|---------|--------|---------------|
| 1. Non-test/demo bloat | DONE | 79 |
| 2. Parser/pipeline duplication | DONE | (included in #1) |
| 3. Subprocess over-replication | DONE | 30 |
| 4. Feature-flag duplication | DONE | (included in #1) |
| 5. MainWindow duplication | DONE | 16 |
| 6. ThreeDEOptimization duplicate | DONE | (included in #1) |
| 7. time.sleep performance traps | DEFERRED | — |
| 8. Test-double fragmentation | DEFERRED | — |
| **Total** | **6/8 done** | **125** |

**Before:** 3613 tests | **After:** 3488 tests | **Files removed:** 27 tracked + 2 untracked
