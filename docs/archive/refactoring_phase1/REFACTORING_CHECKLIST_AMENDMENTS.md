# REFACTORING CHECKLIST AMENDMENTS - 2025-11-12

**Last Updated**: 2025-11-12 (Critical amendments based on code verification)
**Overall Progress**: 0/2 safe tasks complete (0%), 3 tasks deferred

---

## 📊 Quick Status

### Phase 1 Safe (EXECUTABLE NOW)
- **Status**: Ready for execution
- **Tasks**: 2 (corrected scopes)
- **Duration**: 1-2 days
- **Lines**: -770 (corrected from -3,259)
- **Risk**: Very Low

### Phase 1 Deferred (AWAITING DECISIONS)
- **Status**: Blocked - user decisions required
- **Tasks**: 3 (critical issues found)
- **Duration**: 2-3 days + 3-6 month validation (if approved)
- **Lines**: -2,489 (if approved)
- **Risk**: Medium-High

---

## ✅ PHASE 1 SAFE: Executable Tasks

### Task 1.1: Delete BaseAssetFinder + Test File (CORRECTED)
- **Status**: ⏳ Not Started
- **Effort**: 15 minutes
- **Impact**: -724 lines (CORRECTED from -362)
- **Files to delete**:
  - base_asset_finder.py (363 lines)
  - tests/unit/test_base_asset_finder.py (361 lines)

**Progress**:
- [ ] Files deleted
- [ ] No imports remain
- [ ] Tests passing (2,300+)
- [ ] Type checking clean
- [ ] Git committed

**Correction from original**: Original plan forgot about test file deletion

---

### Task 1.2: Remove ThreeDESceneFinder Alias Layer (REVISED)
- **Status**: ⏳ Not Started
- **Effort**: 15 minutes
- **Impact**: -46 lines (REVISED from -386)
- **Files to delete**:
  - threede_scene_finder.py (46 lines) ONLY
- **Files to keep**:
  - threede_scene_finder_optimized.py (adapter pattern - NOT a simple wrapper)

**Progress**:
- [ ] Alias file deleted
- [ ] 13 import sites updated
- [ ] Tests passing (2,300+)
- [ ] Type checking clean
- [ ] Git committed

**Correction from original**: Layer 2 is adapter pattern coordinating 4 modules, has 13 methods NOT in RefactoredThreeDESceneFinder. Deleting it would break production code.

**Deferred work**: Full wrapper removal requires moving 13 methods to RefactoredThreeDESceneFinder (2-3 days architectural work)

---

## 🔴 PHASE 1 DEFERRED: Awaiting User Decisions

### Task 1.3-DEFERRED: PathUtils Migration
- **Status**: ⚠️ DEFERRED
- **Impact**: -36 lines (if approved)
- **Effort**: 8-12 hours (if approved)

**Blocking Issues**:
1. Circular import exists (verified):
   ```bash
   $ python3 -c "from file_discovery import FileDiscovery"
   ImportError: circular import
   ```
2. Negative ROI: 8-12 hours effort to save 36 lines of good code
3. PathUtils is textbook compatibility layer design

**User Decision**: Proceed with fragile migration or skip?

**If approved**:
- [ ] 123 call sites updated (37 production + 86 tests)
- [ ] Compatibility layer removed from utils.py
- [ ] Tests passing
- [ ] No import errors

---

### Task 1.4-DEFERRED: MayaLatestFinder Consolidation
- **Status**: 🔴 BLOCKED by Task 1.5 dependency
- **Impact**: -155 lines (if approved)
- **Effort**: 15 minutes (after Task 1.5 completes)

**Blocking Issue**: SimplifiedLauncher already uses refactored version. Old version ONLY used by command_launcher.py (deleted in Task 1.5). Must delete command_launcher.py FIRST.

**Dependency**: Unblocks when Task 1.5 completes

**If approved**:
- [ ] maya_latest_finder.py deleted
- [ ] No imports of old version remain
- [ ] Tests passing

---

### Task 1.5-DEFERRED: Launcher Stack Deletion
- **Status**: 🔴 DEFERRED - Violates project validation policy
- **Impact**: -3,239 lines (CORRECTED from -2,560, +679 counting error)
- **Effort**: 2-3 days + 3-6 month validation period

**Blocking Issues**:
1. **Set as default TODAY**, project docs require "EXTENDED VALIDATION PERIOD"
   - SimplifiedLauncher became default: 2025-11-12
   - Plan proposes deletion: Week 1 (3-4 days from now)
   - CLAUDE.md policy: "AFTER EXTENDED VALIDATION PERIOD" (3-6 months)

2. **Incomplete replacement**:
   - LauncherManager custom launcher CRUD: ❌ NOT in SimplifiedLauncher
   - launch_app_with_scene_context() method: ❌ NOT in SimplifiedLauncher
   - Deleting LauncherManager breaks launcher_dialog.py

3. **Line count error**: Plan claimed 2,560, actual 3,239 (+679 error)

**User Decisions Required**:
1. Accept immediate deletion (violates docs) or wait 3-6 months?
2. LauncherManager feature: keep, delete, or extract to separate module?
3. Need launch_app_with_scene_context() functionality?

**If approved**:
- [ ] User decision: validation period vs immediate deletion
- [ ] User decision: LauncherManager feature handling
- [ ] 51 import sites updated
- [ ] 4 files deleted (command_launcher, launcher_manager, process_pool_manager, persistent_terminal_manager)
- [ ] launcher_dialog.py handled per user decision
- [ ] Tests passing
- [ ] SimplifiedLauncher validated in production

---

## 📊 Overall Metrics

### Phase 1 Safe (Executable)
- **Tasks**: 2
- **Lines**: -770
- **Time**: 1-2 days
- **Commits**: 2 atomic commits

**Breakdown**:
- Task 1.1: -724 lines (CORRECTED)
- Task 1.2: -46 lines (REVISED)

### Phase 1 Deferred (Awaiting Decisions)
- **Tasks**: 3
- **Lines**: -2,489 (if all approved)
- **Time**: 2-3 days + validation period

**Breakdown**:
- Task 1.3: -36 lines (circular import issue)
- Task 1.4: -155 lines (blocked by Task 1.5)
- Task 1.5: -3,239 lines (premature deletion, incomplete replacement) - Note: Line count corrected
- ~~Task 1.3 (old): -150 lines~~ **REMOVED** (superior current design)

### Original vs Amended
| Metric | Original Plan | Amended Safe | Deferred | Total if Approved |
|--------|--------------|--------------|----------|-------------------|
| Tasks | 5 | 2 | 3 | 5 |
| Lines | -3,259 | -770 | -2,489 | -3,259 |
| Days | 3-4 | 1-2 | 2-3 + validation | varies |
| Issues | 5 critical | 0 | 3 critical | varies |

---

## 🎯 Next Actions

### Immediate (Can Execute Now)
1. [ ] User reviews REFACTORING_PLAN_AMENDMENTS.md
2. [ ] User approves Phase 1 Safe scope
3. [ ] Execute Task 1.1 (BaseAssetFinder + test deletion)
4. [ ] Execute Task 1.2 (alias layer deletion)
5. [ ] Verify all tests pass, type checking clean
6. [ ] Update this checklist with progress

### Awaiting User Decisions
1. [ ] Task 1.3: PathUtils migration - proceed or skip?
2. [ ] Task 1.5: Launcher deletion - immediate or wait 3-6 months?
3. [ ] Task 1.5: LauncherManager feature - keep, delete, or extract?
4. [ ] Task 1.4: Automatically unblocks when Task 1.5 decided

---

## ✅ Verification Evidence

All amendments verified by:
- ✅ Direct code inspection (grep, wc, Read tools)
- ✅ 6 concurrent agent reviews
- ✅ Manual circular import testing
- ✅ Cross-reference with CLAUDE.md policy
- ✅ Production code usage analysis

**See**: REFACTORING_PLAN_AMENDMENTS.md for detailed verification findings

---

## 🚨 Critical Notes

1. **DO NOT execute original Phase 1 plan** - it has 5 critical issues
2. **Execute only Phase 1 Safe tasks** (1.1-1.2 corrected) until user decisions received
3. **Original line counts were wrong**:
   - Task 1.1: Claimed -362, actual -724 (forgot test file)
   - Task 1.2: Claimed -386, actual -46 (Layer 2 is adapter, not wrapper)
   - Task 1.5: Claimed -2,560, actual -3,239 (+679 counting error)
4. **Task order is wrong**: Task 1.4 must happen AFTER Task 1.5 (dependency reversed)
5. **Validation period violation**: SimplifiedLauncher set as default TODAY, plan deletes legacy in Week 1 (violates "extended validation period" policy)

---

**Status**: Ready for user review and approval of Phase 1 Safe scope
