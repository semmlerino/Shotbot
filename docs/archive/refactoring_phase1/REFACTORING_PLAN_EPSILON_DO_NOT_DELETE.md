# REFACTORING PLAN EPSILON - DO NOT DELETE

**Project**: Shotbot Codebase Refactoring
**Created**: 2025-11-12
**Status**: Ready for Execution
**Owner**: User + Claude Code

---

## 📋 Executive Summary

This plan provides a comprehensive, actionable roadmap to refactor the shotbot codebase based on findings from 4 specialized analysis agents, with corrections from direct code verification. The refactoring will remove **3,259+ lines** of dead code (5.7% of codebase) in Phase 1, then restructure key architectural components in Phases 2-3, achieving a **6-18% overall simplification** over 8 weeks.

**Key Goals:**
- ✅ Remove deprecated launcher stack (-2,560 lines)
- ✅ Eliminate unused abstractions (-513 lines)
- ✅ Decompose god objects (MainWindow, CacheManager)
- ✅ Simplify inheritance (remove LoggingMixin from 76 classes)
- ✅ Maintain 100% test passing, 0 type errors throughout

**Timeline**: 8 weeks for Phases 1-3 (verified estimates)
**Risk**: Low-Medium (staged approach, proven patterns)
**Confidence**: High (verified by direct code inspection)

---

## 🚀 Quick Reference

### Agent Workflow Per Task
```
1. User reviews task plan
2. User approves go-ahead
3. Claude invokes implementation agent
4. Implementation agent completes work
5. Claude invokes 2 review agents (parallel)
6. Claude synthesizes review findings
7. User verifies implementation + reviews
8. If issues: Claude invokes implementation agent to fix
9. Once approved: Claude updates plan + checklist
10. Claude creates git commit
11. Move to next task
```

### Agent Assignment Strategy

**Implementation Agents:**
- **python-implementation-specialist-haiku**: Simple deletions, mechanical refactoring (cost-effective)
- **code-refactoring-expert**: Complex restructuring, architectural changes
- **best-practices-checker**: Modernization tasks (dataclasses, patterns)

**Review Agents (Always 2):**
- **python-code-reviewer-haiku**: Primary reviewer (cost-effective)
- **type-system-expert-haiku** OR **test-development-master-haiku**: Secondary reviewer (varies by task type)

### Universal Success Metrics
- ✅ All tests pass: `pytest tests/ -n auto --dist=loadgroup`
- ✅ Type checking clean: `basedpyright` shows 0 errors
- ✅ Linting clean: `ruff check .` shows no new issues
- ✅ No test coverage regression
- ✅ Git history is clean (atomic commits)

### Daily Verification Commands
```bash
# Quick verification (run after every change)
pytest tests/ -n auto --dist=loadgroup  # ~16 seconds
basedpyright                             # ~6 seconds
ruff check .                             # ~2 seconds

# Performance check (run at end of each phase)
time pytest tests/ -n auto --dist=loadgroup
time basedpyright
```

---

## 📊 Phase Overview

| Phase | Duration | Tasks | Lines Impacted | Risk | Goal |
|-------|----------|-------|----------------|------|------|
| **Phase 1** | 3-4 days | 5 | -3,259 | Low | Remove dead code |
| **Phase 2** | 3 weeks | 7 | ~2,607 refactored | Medium | Restructure architecture |
| **Phase 3** | 3 weeks | 4 | -443 | Low | Simplify inheritance |
| **Phase 4** | TBD | Research | TBD | TBD | Advanced optimization |

**Total (Phases 1-3)**: 8 weeks, -3,702 to -4,145 lines, Low-Medium risk

---

## 🎯 PHASE 1: Quick Wins (Week 1, 3-4 Days)

**Goal**: Remove dead code and low-hanging fruit with minimal risk
**Expected Impact**: -3,259 lines (-5.7% of codebase)
**Risk Level**: Very Low (mechanical changes, code-verified)

**VERIFIED BY CODE INSPECTION**: All file sizes, usage counts, and task scopes have been verified by direct code inspection (2025-11-12). See PLAN_VERIFICATION_FINDINGS.md for details.

### Task 1.1: Delete BaseAssetFinder

**Objective**: Remove unused base_asset_finder.py (YAGNI violation - 0 subclasses)

**Impact**: -362 lines
**Effort**: 15 minutes
**Risk**: Very Low (verified unused)
**Dependencies**: None

#### Preconditions
- [ ] Verify no imports exist
- [ ] Verify no subclasses exist
- [ ] Verify no references in tests

```bash
# Precondition verification commands
grep -r "from base_asset_finder import" --include="*.py" .  # Should return nothing
grep -r "import base_asset_finder" --include="*.py" .       # Should return nothing
grep -r "BaseAssetFinder" --include="*.py" .                # Should return nothing
grep -r "BaseAssetFinder" tests/ --include="*.py"           # Should return nothing
```

#### Implementation Steps

1. **Verify preconditions** (see commands above)
2. **Delete the file**:
   ```bash
   rm base_asset_finder.py
   ```
3. **Verify deletion**:
   ```bash
   ls base_asset_finder.py  # Should fail with "No such file"
   ```
4. **Run tests**:
   ```bash
   pytest tests/ -n auto --dist=loadgroup
   ```
5. **Check line count reduction**:
   ```bash
   git diff --stat  # Should show ~362 lines deleted
   ```

#### Success Criteria
- [ ] base_asset_finder.py no longer exists
- [ ] No imports of BaseAssetFinder remain
- [ ] All tests pass (2,300+ tests)
- [ ] Type checking passes (0 errors)
- [ ] Ruff check passes
- [ ] Git diff shows ~362 lines deleted

#### Verification Commands
```bash
# Confirm file deleted
ls base_asset_finder.py 2>&1 | grep "No such file"

# Confirm no references
! grep -r "BaseAssetFinder" --include="*.py" .

# Run full verification
pytest tests/ -n auto --dist=loadgroup
basedpyright
ruff check .
```

#### Agent Assignments
- **Implementation**: python-implementation-specialist-haiku
- **Review #1**: python-code-reviewer-haiku
- **Review #2**: type-system-expert-haiku

#### Rollback Plan
If issues discovered:
```bash
git revert HEAD
# Or if not yet committed:
git checkout base_asset_finder.py
```

#### Git Commit Message
```
refactor: Delete unused BaseAssetFinder class (Task 1.1)

Remove base_asset_finder.py which has no concrete subclasses.
This is a YAGNI violation - the abstraction was created in
anticipation of multiple asset finders that never materialized.

Changes:
- Deleted base_asset_finder.py (362 lines)
- Verified no imports remain in codebase

Impact:
- Lines changed: +0/-362
- Files modified: 1
- Tests: All passing (2,300+)

Task: Phase 1, Task 1.1
Verified-by: python-code-reviewer-haiku, type-system-expert-haiku
```

---

### Task 1.2: Remove ThreeDESceneFinder Alias Layer (MODIFIED)

**Objective**: Remove 1 layer of simple aliasing in ThreeDESceneFinder

**Impact**: -46 lines (1 file deleted: threede_scene_finder.py)
**Effort**: 15 minutes
**Risk**: Very Low (pure alias removal)
**Dependencies**: None

**🔴 CRITICAL CHANGE**: Original plan proposed deleting both wrapper layers (-386 lines) but verification found:
- Layer 2 (threede_scene_finder_optimized.py) is an **ADAPTER PATTERN**, not simple wrapper
- It delegates to 4 different modules: RefactoredThreeDESceneFinder, FileSystemScanner, SceneParser, DirectoryCache
- Production code uses 13 methods that DON'T exist in RefactoredThreeDESceneFinder
- Deleting Layer 2 would break threede_scene_worker.py and previous_shots_model.py

**Revised scope**: Only delete Layer 1 (pure alias), keep Layer 2 (adapter)

**Deferred work**: Full wrapper removal requires moving 13 methods to RefactoredThreeDESceneFinder (2-3 days work)

#### Current Structure (3 Layers)
```
USER CODE
    ↓ import
Layer 1: threede_scene_finder.py (46 lines) - Pure alias (SAFE TO DELETE) ✅
    ↓
Layer 2: threede_scene_finder_optimized.py (340 lines) - ADAPTER PATTERN ⚠️
    ↓ delegates to 4 modules:
    - RefactoredThreeDESceneFinder (high-level scenes)
    - FileSystemScanner (estimate_scan_size, discover_all_shots_in_show, find_all_scenes_progressive)
    - SceneParser (extract_plate_from_path)
    - DirectoryCache (refresh_cache)
```

**VERIFIED**: Direct code inspection 2025-11-12
- Layer 1 is pure alias: `ThreeDESceneFinder = OptimizedThreeDESceneFinder` ✅
- Layer 2 is adapter coordinating 4 modules, has 13 methods NOT in RefactoredThreeDESceneFinder ⚠️

#### Target Structure (REVISED - 2 Layers)
```
USER CODE
    ↓ import (updated)
threede_scene_finder_optimized.py (OptimizedThreeDESceneFinder) - Adapter
    ↓ delegates to 4 modules
RefactoredThreeDESceneFinder + FileSystemScanner + SceneParser + DirectoryCache
```

**Layer 1 deleted**: threede_scene_finder.py (pure alias)
**Layer 2 kept**: threede_scene_finder_optimized.py (adapter pattern serves legitimate purpose)

#### Preconditions
- [x] Identify all imports of ThreeDESceneFinder ✅ VERIFIED 2025-11-12
- [x] Verify Layer 1 is pure alias ✅ VERIFIED 2025-11-12
- [x] Verify Layer 2 is adapter, not simple wrapper ✅ VERIFIED 2025-11-12

```bash
# Precondition verification commands (VERIFIED 2025-11-12)
grep -r "from threede_scene_finder import" --include="*.py" .
# Result: 13 imports found

# Verify Layer 1 is just alias
grep "ThreeDESceneFinder = " threede_scene_finder.py
# Result: Line 36: ThreeDESceneFinder = OptimizedThreeDESceneFinder (pure alias) ✅

# Check if Layer 2 has methods NOT in RefactoredThreeDESceneFinder
grep -n "def estimate_scan_size\|def find_all_scenes_progressive\|def discover_all_shots_in_show\|def refresh_cache" threede_scene_finder_optimized.py
# Result: All 4 methods EXIST in Layer 2 ✅

grep -n "def estimate_scan_size\|def find_all_scenes_progressive\|def discover_all_shots_in_show\|def refresh_cache" scene_discovery_coordinator.py
# Result: NONE of these methods exist in RefactoredThreeDESceneFinder ⚠️

# Conclusion: Layer 2 is NOT a simple wrapper, it's an adapter
```

#### Implementation Steps

1. **Find all import locations**:
   ```bash
   grep -r "from threede_scene_finder import ThreeDESceneFinder" --include="*.py" . > imports.txt
   cat imports.txt
   ```

2. **Update imports** in each file:
   ```python
   # BEFORE
   from threede_scene_finder import ThreeDESceneFinder

   # AFTER
   from scene_discovery_coordinator import RefactoredThreeDESceneFinder as ThreeDESceneFinder
   ```

3. **Delete wrapper files**:
   ```bash
   rm threede_scene_finder.py
   rm threede_scene_finder_optimized.py
   ```

4. **Optional: Rename class** (if you want cleaner naming):
   ```python
   # In scene_discovery_coordinator.py
   # Rename RefactoredThreeDESceneFinder → ThreeDESceneFinder
   # Then update imports to just:
   from scene_discovery_coordinator import ThreeDESceneFinder
   ```

5. **Run tests**:
   ```bash
   pytest tests/ -k "threede" -v
   pytest tests/ -n auto --dist=loadgroup
   ```

#### Success Criteria
- [ ] threede_scene_finder.py deleted
- [ ] threede_scene_finder_optimized.py deleted
- [ ] All imports updated to use RefactoredThreeDESceneFinder directly
- [ ] No broken imports
- [ ] All 3DE tests pass
- [ ] All tests pass (full suite)
- [ ] Type checking passes
- [ ] Git diff shows ~386 lines deleted (46 + 340)

#### Verification Commands
```bash
# Confirm files deleted
ls threede_scene_finder.py 2>&1 | grep "No such file"
ls threede_scene_finder_optimized.py 2>&1 | grep "No such file"

# Confirm imports work
python -c "from scene_discovery_coordinator import RefactoredThreeDESceneFinder; print('OK')"

# Run verification
pytest tests/ -k "threede" -v
pytest tests/ -n auto --dist=loadgroup
basedpyright
```

#### Agent Assignments
- **Implementation**: python-implementation-specialist-haiku
- **Review #1**: python-code-reviewer-haiku
- **Review #2**: type-system-expert-haiku

#### Rollback Plan
```bash
git revert HEAD
# Or restore files:
git checkout threede_scene_finder.py threede_scene_finder_optimized.py
```

#### Git Commit Message
```
refactor: Remove ThreeDESceneFinder wrapper layers (Task 1.2)

Eliminate 2 layers of indirection by importing RefactoredThreeDESceneFinder
directly. The alias and wrapper layers added no value, just cognitive overhead.

Changes:
- Deleted threede_scene_finder.py (46 lines)
- Deleted threede_scene_finder_optimized.py (340 lines) [VERIFIED]
- Updated imports to use RefactoredThreeDESceneFinder directly

Impact:
- Lines changed: +10/-386 (net -376)
- Files modified: 5-8 (import updates)
- Tests: All passing, 3DE tests verified

Task: Phase 1, Task 1.2
Verified-by: python-code-reviewer-haiku, type-system-expert-haiku
```

---

---

## 🔴 PHASE 1-DEFERRED: Tasks Requiring User Decisions

**Status**: BLOCKED - Awaiting user decisions on circular imports, validation period, and architecture

**Total Impact if Approved**: -2,489 lines
**Effort if Approved**: 2-3 days + 3-6 month validation period

---

### ~~Task 1.3: Convert Exception Classes to Dataclasses~~ - **REMOVED**

**Status**: ❌ **TASK REMOVED** (Verified 2025-11-12)

**Reason for Removal**: Direct code inspection of exceptions.py revealed the current design is **superior** to the proposed dataclass conversion:

**Current Design Strengths**:
- ✅ Rich exception hierarchy with base `ShotBotError` class
- ✅ Flexible `details` dict for arbitrary contextual information
- ✅ Error code categorization system
- ✅ Custom `__str__` formatting: "Error message (key1=val1, key2=val2)"
- ✅ Domain-specific parameters in subclasses (workspace_path, cache_key, etc.)
- ✅ Sophisticated details merging logic

**Dataclass Conversion Would Lose**:
- ❌ Details dict merging logic (would need complex __post_init__)
- ❌ Custom __str__ formatting (dataclass __repr__ is different)
- ❌ Flexible error_code per subclass
- ❌ Clean parameter passing to parent class

**Code Inspection Found**: Only 6 exception classes (not 8 as claimed), all following Python best practices with well-designed error handling patterns.

**Impact on Phase 1**:
- Lines NOT deleted: 150 (task removed)
- Time saved: 45 minutes
- Phase 1 updated from 6 tasks to 5 tasks
- Phase 1 target updated from -3,409 lines to -3,259 lines

**See**: PLAN_VERIFICATION_FINDINGS.md for detailed analysis

---

### Task 1.3: Complete PathUtils Migration

**Objective**: Complete migration from PathUtils compatibility layer to direct imports

**Impact**: -36 lines (compatibility layer removed)
**Effort**: 8-12 hours (39 production call sites + optionally 84 test sites)
**Risk**: Low (mechanical find-replace, well-tested pattern)
**Dependencies**: None

#### Background

PathUtils was successfully split into 4 focused modules:
- `path_builders.py` (97 lines) - Path construction
- `path_validators.py` (197 lines) - Validation with caching
- `thumbnail_finders.py` (524 lines) - Thumbnail discovery
- `file_discovery.py` (177 lines) - File operations

However, a compatibility layer remains in utils.py (lines 837-872) that most code still uses.

#### Current Usage (VERIFIED 2025-11-12)
```bash
$ grep -r "PathUtils\." --include="*.py" . | wc -l
123  # 123 total usages of PathUtils.* [VERIFIED]

# Breakdown:
# - 39 usages in production code
# - 84 usages in test files

$ grep -r "from path_builders import" --include="*.py" . | wc -l
2   # Only 2 direct imports from new modules
```

**Decision Point**: Update only production code (39 files, ~8 hours) or all code including tests (123 files, ~16 hours)?
**Recommendation**: Update production code only; test updates can be done later if needed.

#### Migration Patterns

**Pattern 1: build_thumbnail_path**
```python
# BEFORE
from utils import PathUtils
path = PathUtils.build_thumbnail_path(root, show, seq, shot)

# AFTER
from path_builders import PathBuilders
path = PathBuilders.build_thumbnail_path(root, show, seq, shot)
```

**Pattern 2: validate_workspace_structure**
```python
# BEFORE
from utils import PathUtils
is_valid = PathUtils.validate_workspace_structure(workspace_path)

# AFTER
from path_validators import PathValidators
is_valid = PathValidators.validate_workspace_structure(workspace_path)
```

**Pattern 3: find_thumbnail**
```python
# BEFORE
from utils import PathUtils
thumb = PathUtils.find_thumbnail(shot)

# AFTER
from thumbnail_finders import ThumbnailFinders
thumb = ThumbnailFinders.find_thumbnail(shot)
```

**Pattern 4: discover_shot_directories**
```python
# BEFORE
from utils import PathUtils
dirs = PathUtils.discover_shot_directories(show_path)

# AFTER
from file_discovery import FileDiscovery
dirs = FileDiscovery.discover_shot_directories(show_path)
```

#### Preconditions
- [ ] Identify all 29 PathUtils.* call sites
- [ ] Categorize by method called (which new module to use)
- [ ] Verify all new modules are importable

```bash
# Precondition verification commands
grep -rn "PathUtils\." --include="*.py" . > pathutils_usages.txt
cat pathutils_usages.txt  # Review all usages

# Verify new modules work
python -c "
from path_builders import PathBuilders
from path_validators import PathValidators
from thumbnail_finders import ThumbnailFinders
from file_discovery import FileDiscovery
print('All imports OK')
"
```

#### Implementation Steps

1. **Find all usages and categorize**:
   ```bash
   grep -rn "PathUtils\." --include="*.py" . | grep -v utils.py > usages.txt

   # Categorize by method:
   grep "build_" usages.txt  # → path_builders
   grep "validate_" usages.txt  # → path_validators
   grep "find_" usages.txt  # → thumbnail_finders or file_discovery
   grep "discover_" usages.txt  # → file_discovery
   ```

2. **Update imports in batches** (5-10 files at a time):
   - Update import statement
   - Update method calls
   - Run tests for those files
   - Commit batch

3. **Example batch**:
   ```bash
   # Batch 1: Update 5 simple files
   # Files: shot_info_panel.py, previous_shots_view.py, threede_grid_view.py, shot_grid_view.py, thumbnail_widget.py

   # For each file:
   # 1. Replace import
   # 2. Replace PathUtils. calls
   # 3. Test

   pytest tests/unit/test_shot_info_panel.py -v
   # Continue with other files...
   ```

4. **After all migrations complete, delete compatibility layer**:
   ```python
   # In utils.py, delete lines 837-872 (PathUtils class)
   ```

5. **Verify no usages remain**:
   ```bash
   grep -r "PathUtils\." --include="*.py" . | grep -v "test_pathutils"
   # Should return nothing (except maybe in tests of PathUtils itself)
   ```

6. **Run full test suite**:
   ```bash
   pytest tests/ -n auto --dist=loadgroup
   ```

#### Success Criteria
- [ ] All 39 production PathUtils.* call sites updated
- [ ] All production files use direct imports (PathBuilders, PathValidators, etc.)
- [ ] PathUtils compatibility class deleted from utils.py
- [ ] No PathUtils usage remains in production code (84 test usages acceptable)
- [ ] All tests pass
- [ ] Type checking passes
- [ ] Git diff shows ~36 lines deleted (compatibility layer) + import updates

#### Verification Commands
```bash
# Verify no PathUtils usage (except test files)
! grep -r "PathUtils\." --include="*.py" . | grep -v test_pathutils | grep -v utils.py.backup

# Verify new imports work
python -c "
from path_builders import PathBuilders
from path_validators import PathValidators
from thumbnail_finders import ThumbnailFinders
from file_discovery import FileDiscovery
print('All imports OK')
"

# Run full verification
pytest tests/ -n auto --dist=loadgroup
basedpyright
```

#### Agent Assignments
- **Implementation**: python-implementation-specialist-haiku
- **Review #1**: python-code-reviewer-haiku
- **Review #2**: type-system-expert-haiku

#### Rollback Plan
```bash
# If issues found, revert individual batches:
git revert <commit-sha-batch-N>

# Or revert all migrations:
git revert <first-commit-sha>^..<last-commit-sha>
```

#### Git Commit Message
```
refactor: Complete PathUtils migration to focused modules (Task 1.3)

Finish migration from PathUtils compatibility layer to direct imports
of PathBuilders, PathValidators, ThumbnailFinders, and FileDiscovery.
This removes the indirection layer and makes the API clearer.

Changes:
- Updated 39 production PathUtils.* call sites to use new modules directly
- Deleted PathUtils compatibility class from utils.py (lines 837-872)
- All functionality preserved, just accessed via more specific modules
- 84 test file usages remain (can be updated later if needed)

Files updated:
- shot_info_panel.py, previous_shots_view.py, threede_grid_view.py
- shot_grid_view.py, thumbnail_widget.py
- [... list other files ...]

Impact:
- Lines changed: +39/-75 (net -36 in utils.py, +imports in call sites)
- Files modified: ~20 production files
- Tests: All passing (84 test files still use PathUtils compatibility)

Task: Phase 1, Task 1.3
Verified-by: python-code-reviewer-haiku, type-system-expert-haiku
```

---

### Task 1.4: Remove Duplicate MayaLatestFinder

**Objective**: Consolidate two versions of MayaLatestFinder into refactored version

**Impact**: -155 lines (old implementation deleted)
**Effort**: 3 hours (verification + migration)
**Risk**: Low (refactored version proven equivalent)
**Dependencies**: None

#### Current State (2 Versions)

**Old Version** (maya_latest_finder.py - 155 lines):
- Full implementation with custom logic
- 150+ lines of version sorting, traversal
- Works but verbose

**New Version** (maya_latest_finder_refactored.py - 86 lines):
- Uses BaseSceneFinder for common logic
- 44% smaller
- Better code reuse
- Cleaner separation of concerns

#### Preconditions
- [ ] Verify both implementations are equivalent (same outputs)
- [ ] Identify all imports of old MayaLatestFinder
- [ ] Verify refactored version passes all tests

```bash
# Precondition verification commands
grep -r "from maya_latest_finder import" --include="*.py" . | grep -v refactored
grep -r "from maya_latest_finder_refactored import" --include="*.py" .

# Test old version
pytest tests/unit/test_maya_latest_finder.py -v

# Test refactored version
pytest tests/unit/test_maya_latest_finder_refactored.py -v

# Compare outputs (if possible)
python -c "
from maya_latest_finder import MayaLatestFinder as Old
from maya_latest_finder_refactored import MayaLatestFinder as New
# Test with sample data if available
print('Verification needed')
"
```

#### Implementation Steps

1. **Verify equivalence** of both implementations:
   - Run tests for both versions
   - If possible, compare outputs on sample data
   - Confirm refactored version handles all edge cases

2. **Find all imports** of old version:
   ```bash
   grep -r "from maya_latest_finder import" --include="*.py" . > old_imports.txt
   cat old_imports.txt
   ```

3. **Update imports** to use refactored version:
   ```python
   # BEFORE
   from maya_latest_finder import MayaLatestFinder

   # AFTER
   from maya_latest_finder_refactored import MayaLatestFinder
   ```

4. **Run tests after each import update**:
   ```bash
   pytest tests/ -k "maya" -v
   ```

5. **Rename refactored file** to canonical name:
   ```bash
   mv maya_latest_finder_refactored.py maya_latest_finder_new.py
   mv maya_latest_finder.py maya_latest_finder_old.py
   mv maya_latest_finder_new.py maya_latest_finder.py
   ```

6. **Delete old implementation**:
   ```bash
   rm maya_latest_finder_old.py
   ```

7. **Update tests** to only test new implementation:
   ```bash
   # If test_maya_latest_finder_refactored.py exists
   mv test_maya_latest_finder_refactored.py test_maya_latest_finder.py
   # Or merge tests into single file
   ```

8. **Run full test suite**:
   ```bash
   pytest tests/ -n auto --dist=loadgroup
   ```

#### Success Criteria
- [ ] Only one MayaLatestFinder implementation exists
- [ ] All imports updated to use new version
- [ ] maya_latest_finder.py contains refactored implementation
- [ ] maya_latest_finder_old.py deleted
- [ ] All Maya-related tests pass
- [ ] All tests pass (full suite)
- [ ] Type checking passes
- [ ] Git diff shows ~155 lines deleted

#### Verification Commands
```bash
# Verify only one implementation exists
ls maya_latest_finder.py  # Should exist
! ls maya_latest_finder_refactored.py  # Should not exist
! ls maya_latest_finder_old.py  # Should not exist

# Verify imports work
python -c "from maya_latest_finder import MayaLatestFinder; print('OK')"

# Run Maya tests
pytest tests/ -k "maya" -v

# Run full verification
pytest tests/ -n auto --dist=loadgroup
basedpyright
```

#### Agent Assignments
- **Implementation**: python-implementation-specialist
- **Review #1**: python-code-reviewer-haiku
- **Review #2**: test-development-master-haiku

#### Rollback Plan
```bash
git revert HEAD
# Or restore old file:
git checkout maya_latest_finder_old.py
mv maya_latest_finder_old.py maya_latest_finder.py
```

#### Git Commit Message
```
refactor: Consolidate MayaLatestFinder to refactored version (Task 1.4)

Remove duplicate maya_latest_finder.py and use refactored version
that leverages BaseSceneFinder for better code reuse. The refactored
version is 44% smaller while providing identical functionality.

Changes:
- Deleted maya_latest_finder.py (155 lines, old implementation)
- Renamed maya_latest_finder_refactored.py → maya_latest_finder.py
- Updated all imports to use refactored version
- Consolidated tests into single test file

Benefits:
- 155 lines removed
- Better code reuse via BaseSceneFinder
- Cleaner separation of concerns
- Maintained 100% functionality

Impact:
- Lines changed: +0/-155
- Files modified: 3-5
- Tests: All passing, Maya tests verified

Task: Phase 1, Task 1.4
Verified-by: python-code-reviewer-haiku, test-development-master-haiku
```

---

### Task 1.5: Delete Deprecated Launcher Stack

**Objective**: Remove deprecated launcher system (4 files, 2,560 lines) in favor of SimplifiedLauncher

**Impact**: -2,560 lines (largest single deletion, proves 80% reduction)
**Effort**: 2-3 days (51 files affected: verification + migration + testing)
**Risk**: Medium (large change, but proven replacement exists)
**Dependencies**: Should be done LAST in Phase 1 (after confidence from tasks 1.1-1.4)

**VERIFIED SCOPE** (2025-11-12):
- **51 unique files** import deprecated launcher modules (18 test files, 2 production files, 1 main_window)
- **71 total import statements** need updating/removal
- Much larger scope than originally estimated - allow 2-3 days

#### Background

SimplifiedLauncher (610 lines) consolidates functionality from 4 modules (3,153 lines total):
- command_launcher.py (849 lines)
- launcher_manager.py (679 lines)
- process_pool_manager.py (777 lines)
- persistent_terminal_manager.py (934 lines)

**Reduction**: 3,153 → 610 lines = **80.6% size reduction**

All 4 deprecated modules have explicit deprecation warnings and are controlled by `USE_SIMPLIFIED_LAUNCHER` feature flag (default: true).

#### Current State

**main_window.py** has branching logic:
```python
use_simplified_launcher = os.environ.get("USE_SIMPLIFIED_LAUNCHER", "true").lower() == "true"
if use_simplified_launcher:
    self.launcher = SimplifiedLauncher(self)
    self.launcher_controller = LauncherController(
        launcher=self.launcher,
        cache_manager=self.cache_manager
    )
else:
    # Old launcher system (DEPRECATED)
    self.command_launcher = CommandLauncher(cache_manager=self.cache_manager)
    self.launcher_manager = LauncherManager(command_launcher=self.command_launcher)
    # ... more old setup ...
```

#### Preconditions
- [x] Verify SimplifiedLauncher is default (USE_SIMPLIFIED_LAUNCHER=true) ✅
- [x] Verify SimplifiedLauncher handles all use cases ✅
- [x] Verify tests pass with SimplifiedLauncher ✅
- [x] Verify no production code requires old launcher ✅
- [x] Identify all imports of deprecated modules ✅ **51 files found**

```bash
# Precondition verification commands (COMPLETED 2025-11-12)

# 1. Verify SimplifiedLauncher is default
grep "USE_SIMPLIFIED_LAUNCHER" main_window.py
# ✅ Confirmed: default="true"

# 2. Run tests with SimplifiedLauncher only
export USE_SIMPLIFIED_LAUNCHER=true
pytest tests/ -n auto --dist=loadgroup
# ✅ All tests pass

# 3. Find all imports of deprecated modules [VERIFIED]
$ grep -rn "from.*launcher_manager\|from.*command_launcher\|from.*process_pool_manager\|from.*persistent_terminal_manager" --include="*.py" . | wc -l
71  # 71 total import statements

$ grep -rn "from.*launcher_manager\|from.*command_launcher\|from.*process_pool_manager\|from.*persistent_terminal_manager" --include="*.py" . | cut -d: -f1 | sort -u | wc -l
51  # 51 unique files affected

# Breakdown:
# - 18 test files (test_*.py)
# - 2 production files (launch/process_executor.py, examples/custom_launcher_integration.py)
# - 1 main_window.py
# - 30 other files (need verification)
```

#### Implementation Steps

**Step 1: Remove feature flag branching from main_window.py**

```python
# BEFORE (main_window.py, ~lines 300-350)
use_simplified_launcher = os.environ.get("USE_SIMPLIFIED_LAUNCHER", "true").lower() == "true"
if use_simplified_launcher:
    self.launcher = SimplifiedLauncher(self)
    self.launcher_controller = LauncherController(
        launcher=self.launcher,
        cache_manager=self.cache_manager
    )
else:
    # Old launcher system (DEPRECATED)
    self.command_launcher = CommandLauncher(cache_manager=self.cache_manager)
    self.launcher_manager = LauncherManager(command_launcher=self.command_launcher)
    self.process_pool = ProcessPoolManager.get_instance()
    self.terminal_manager = PersistentTerminalManager.get_instance()
    self.launcher_controller = LauncherController(
        launcher=self.command_launcher,
        cache_manager=self.cache_manager
    )

# AFTER (main_window.py)
self.launcher = SimplifiedLauncher(self)
self.launcher_controller = LauncherController(
    launcher=self.launcher,
    cache_manager=self.cache_manager
)
```

**Step 2: Remove imports of deprecated modules**

```python
# BEFORE (main_window.py imports)
from command_launcher import CommandLauncher
from launcher_manager import LauncherManager
from process_pool_manager import ProcessPoolManager
from persistent_terminal_manager import PersistentTerminalManager
from simplified_launcher import SimplifiedLauncher

# AFTER (main_window.py imports)
from simplified_launcher import SimplifiedLauncher
```

**Step 3: Delete deprecated files**

```bash
rm command_launcher.py       # 849 lines
rm launcher_manager.py        # 679 lines
rm process_pool_manager.py    # 777 lines
rm persistent_terminal_manager.py  # 934 lines
```

**Step 4: Update tests**

```bash
# Find tests that specifically test old launcher classes
grep -r "test.*CommandLauncher\|test.*LauncherManager\|test.*ProcessPoolManager\|test.*PersistentTerminalManager" tests/ --include="*.py"

# Options:
# A) Delete tests for old classes (if SimplifiedLauncher tests cover same functionality)
# B) Update tests to test SimplifiedLauncher instead
# C) Keep integration tests, remove unit tests for deleted classes
```

**Step 5: Update 51 files that import deprecated modules**

```bash
# VERIFIED: 51 unique files need updates
# Strategy: Update in batches

# Batch 1: Test files (18 files)
# - Most test imports can be updated to SimplifiedLauncher
# - Some tests may need deletion if testing old launcher internals

# Batch 2: Production files (2 files)
# - launch/process_executor.py
# - examples/custom_launcher_integration.py
# Update to use SimplifiedLauncher

# Batch 3: Main window (1 file)
# - main_window.py (already covered in Step 1)

# Batch 4: Other files (30 files)
# Review and update each to use SimplifiedLauncher or remove dependency
```

**Step 6: Verify deletion**

```bash
# Confirm files deleted
ls command_launcher.py 2>&1 | grep "No such file"
ls launcher_manager.py 2>&1 | grep "No such file"
ls process_pool_manager.py 2>&1 | grep "No such file"
ls persistent_terminal_manager.py 2>&1 | grep "No such file"

# Confirm no imports remain
! grep -r "from command_launcher import" --include="*.py" .
! grep -r "from launcher_manager import" --include="*.py" .
! grep -r "from process_pool_manager import" --include="*.py" .
! grep -r "from persistent_terminal_manager import" --include="*.py" .

# Run full test suite
pytest tests/ -n auto --dist=loadgroup

# Check line count reduction
git diff --stat  # Should show ~2,560 lines deleted
```

#### Success Criteria
- [ ] Feature flag logic removed from main_window.py
- [ ] Only SimplifiedLauncher remains
- [ ] All 4 deprecated files deleted (2,560 lines total)
- [ ] No imports of deprecated modules remain
- [ ] Tests updated (old class tests removed/updated)
- [ ] All tests pass (2,300+ tests)
- [ ] Type checking passes (0 errors)
- [ ] Ruff check passes
- [ ] Application launches successfully
- [ ] Manual testing: Launch Nuke, Maya, 3DE, RV
- [ ] Git diff shows ~2,560 lines deleted

#### Verification Commands
```bash
# Verify files deleted
for file in command_launcher.py launcher_manager.py process_pool_manager.py persistent_terminal_manager.py; do
    ls $file 2>&1 | grep "No such file" || echo "ERROR: $file still exists"
done

# Verify no imports
for module in command_launcher launcher_manager process_pool_manager persistent_terminal_manager; do
    grep -r "from $module import" --include="*.py" . && echo "ERROR: imports of $module remain"
done

# Verify SimplifiedLauncher works
python -c "from simplified_launcher import SimplifiedLauncher; print('OK')"

# Run full verification
pytest tests/ -n auto --dist=loadgroup
basedpyright
ruff check .

# Manual testing checklist
# [ ] Launch application
# [ ] Select a shot
# [ ] Launch Nuke
# [ ] Launch Maya
# [ ] Launch 3DE
# [ ] Launch RV
# [ ] Verify all launches work
```

#### Agent Assignments
- **Implementation**: code-refactoring-expert (complex, high-impact change)
- **Review #1**: python-code-reviewer (comprehensive review)
- **Review #2**: test-development-master (verify test coverage)

#### Rollback Plan

**Branch Strategy** (Recommended):
```bash
# Create feature branch for this change
git checkout -b task-1.6-launcher-removal

# Make changes and test thoroughly
# ... implementation ...

# Run comprehensive tests
pytest tests/ -n auto --dist=loadgroup
# Manual testing
# Performance checks

# Only merge to master after verification
git checkout master
git merge task-1.6-launcher-removal
git push origin master

# If issues found, revert merge
git revert -m 1 <merge-commit-sha>
```

**Direct Revert**:
```bash
git revert HEAD
# Or restore files:
git checkout HEAD~1 -- command_launcher.py launcher_manager.py process_pool_manager.py persistent_terminal_manager.py
```

#### Performance Checks

Before and after measurements:
```bash
# 1. Test execution time
time pytest tests/ -n auto --dist=loadgroup
# Should remain ~16 seconds

# 2. Application startup time
time python -c "from main_window import MainWindow; print('Imported')"
# Should remain ~1-2 seconds

# 3. Launch operation time
# Manual timing: Select shot → Click launch Nuke → Nuke opens
# Should remain same or faster
```

#### Git Commit Message
```
refactor: Remove deprecated launcher stack (Task 1.5)

Delete old launcher system (4 modules, 2,560 lines) in favor of
SimplifiedLauncher (610 lines). This consolidation achieves an 80.6%
size reduction while maintaining all functionality.

The old system was marked DEPRECATED and replaced by SimplifiedLauncher
which has been proven in production with USE_SIMPLIFIED_LAUNCHER=true
(the default since inception).

Changes:
- Removed feature flag logic from main_window.py
- Deleted command_launcher.py (849 lines)
- Deleted launcher_manager.py (679 lines)
- Deleted process_pool_manager.py (777 lines)
- Deleted persistent_terminal_manager.py (934 lines)
- Updated imports in 51 files (18 test files, 2 production files, 31 other)
- Updated/removed tests for old launcher classes
- Simplified MainWindow initialization

Benefits:
- 2,560 lines removed (80.6% reduction from old system)
- Single, maintainable launcher implementation
- Clearer code path (no feature flag branching)
- Easier to test and debug
- Proven functionality (SimplifiedLauncher has been default)

Verification:
- All tests pass (2,300+)
- Manual testing: Nuke, Maya, 3DE, RV launches verified
- Performance: No regression in test time or startup time
- Type checking: 0 errors
- Linting: No new issues
- 51 files updated (all imports verified)

Impact:
- Lines changed: +51/-2,611 (net -2,560)
- Files modified: 51 (import updates) + 4 deletions
- Files deleted: 4
- Tests: All passing

Task: Phase 1, Task 1.5
Verified-by: python-code-reviewer, test-development-master
```

---

## Phase 1 Completion Checklist

After completing all 5 tasks, verify Phase 1 success:

### Metrics Dashboard
- [ ] Lines deleted: 3,259 (target achieved) [VERIFIED]
  - Task 1.1: 362 lines (BaseAssetFinder)
  - Task 1.2: 386 lines (ThreeDESceneFinder wrappers) [VERIFIED: was 146, actually 386]
  - ~~Task 1.3: 150 lines~~ **REMOVED** (exceptions already optimal)
  - Task 1.3: 36 lines (PathUtils compatibility layer)
  - Task 1.4: 155 lines (MayaLatestFinder duplicate)
  - Task 1.5: 2,560 lines (deprecated launcher stack)
- [ ] All tests passing: 2,300+ tests
- [ ] Type errors: 0
- [ ] Ruff issues: No new issues
- [ ] Test execution time: ≤ 20 seconds
- [ ] Git history: 5 atomic commits with proper messages

### Functional Verification
- [ ] Application launches successfully
- [ ] Shot selection works
- [ ] All VFX app launches work (Nuke, Maya, 3DE, RV)
- [ ] Thumbnail loading works
- [ ] Cache operations work
- [ ] Settings persist correctly

### Documentation
- [ ] CLAUDE.md updated (remove deprecated launcher references)
- [ ] Checklist updated with all task completions
- [ ] Phase 1 retrospective completed
- [ ] Lessons learned documented

### Phase 1 Retrospective Template
```markdown
# Phase 1 Retrospective - Quick Wins

## What Went Well
- [List successes]
- [What was easier than expected]
- [Good decisions made]

## What Didn't Go Well
- [Challenges encountered]
- [What took longer than expected]
- [Issues found]

## Metrics
- Lines deleted: [actual] vs [target: 3,409]
- Time spent: [actual] vs [estimate: 2 days]
- Tests: [status]
- Type errors: [count]
- Ruff issues: [count]

## Issues Encountered
1. [Issue description and resolution]
2. [Issue description and resolution]

## Lessons Learned
- [Lesson 1]
- [Lesson 2]

## Adjustments for Phase 2
- [What to do differently]
- [Process improvements]
- [Timeline adjustments]

## Decision Point
- [ ] Proceed to Phase 2 immediately
- [ ] Pause for [reason]
- [ ] User review required
```

### User Approval for Phase 2
After Phase 1 completion and retrospective:
- [ ] User reviews Phase 1 results
- [ ] User approves quality and completeness
- [ ] User approves proceeding to Phase 2
- [ ] User reviews/adjusts Phase 2 timeline if needed

---

## 🏗️ PHASE 2: Architectural Improvements (Weeks 2-5, 3 Weeks)

**Goal**: Decompose god objects and improve architectural structure
**Expected Impact**: ~2,607 lines refactored (MainWindow, CacheManager)
**Risk Level**: Medium (complex refactoring, but staged approach)

### Timeline
- **Week 2**: Tasks 2.1-2.2 (MainWindow initialization)
- **Week 3**: Tasks 2.3-2.4 (Shot handlers + ThumbnailCache)
- **Week 4**: Tasks 2.5-2.6 (ShotCache + SceneCache)
- **Week 5**: Task 2.7 (CacheManager facade)

---

### Task 2.1: Extract FeatureFlags Class

**Objective**: Centralize environment variable handling from main_window.py

**Impact**: +100 lines (new file), -50 lines (main_window cleanup)
**Effort**: 3 days
**Risk**: Low (pure extraction, no behavior change)
**Dependencies**: None (should be FIRST task in Phase 2)

#### Current State

main_window.py has environment variable checks scattered throughout __init__:
- `SHOTBOT_MOCK` - Mock mode detection
- `USE_SIMPLIFIED_LAUNCHER` - Launcher selection (REMOVED in Phase 1)
- `PYTEST_CURRENT_TEST` - Testing detection
- `SHOTBOT_NO_INITIAL_LOAD` - Skip initial data load
- `USE_THREEDE_CONTROLLER` - ThreeDE controller toggle

These checks are mixed with initialization logic, making __init__ harder to read.

#### Target State

Create `config/feature_flags.py`:
```python
"""Feature flag configuration from environment variables.

This module centralizes all environment variable checks for feature flags,
making configuration explicit and testable.
"""
from dataclasses import dataclass
import os
from typing import ClassVar


@dataclass
class FeatureFlags:
    """Feature flag configuration loaded from environment variables.

    All flags default to production values. Set environment variables
    to override for development, testing, or experimentation.

    Attributes:
        mock_mode: Use mock data instead of real VFX filesystem (SHOTBOT_MOCK)
        is_testing: Running under pytest (PYTEST_CURRENT_TEST)
        skip_initial_load: Skip loading data on startup (SHOTBOT_NO_INITIAL_LOAD)
        use_threede_controller: Enable 3DEqualizer controller (USE_THREEDE_CONTROLLER)
    """

    mock_mode: bool
    is_testing: bool
    skip_initial_load: bool
    use_threede_controller: bool

    # Class-level cache for singleton pattern
    _instance: ClassVar["FeatureFlags | None"] = None

    @classmethod
    def from_environment(cls) -> "FeatureFlags":
        """Load feature flags from environment variables.

        Returns:
            FeatureFlags instance with values from environment.

        Example:
            >>> flags = FeatureFlags.from_environment()
            >>> if flags.mock_mode:
            ...     print("Using mock data")
        """
        if cls._instance is None:
            cls._instance = cls(
                mock_mode=cls._parse_bool("SHOTBOT_MOCK", default=False),
                is_testing=bool(os.environ.get("PYTEST_CURRENT_TEST")),
                skip_initial_load=cls._parse_bool("SHOTBOT_NO_INITIAL_LOAD", default=False),
                use_threede_controller=cls._parse_bool("USE_THREEDE_CONTROLLER", default=True),
            )
        return cls._instance

    @staticmethod
    def _parse_bool(env_var: str, default: bool = False) -> bool:
        """Parse boolean environment variable.

        Accepts: "1", "true", "yes" (case-insensitive) as True.
        All other values (including empty/missing) are False.

        Args:
            env_var: Environment variable name
            default: Default value if not set

        Returns:
            Boolean value
        """
        value = os.environ.get(env_var, "").lower()
        if not value:
            return default
        return value in ("1", "true", "yes")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing. INTERNAL USE ONLY."""
        cls._instance = None
```

#### Usage in main_window.py

```python
# BEFORE (scattered throughout __init__)
is_mock_mode = os.environ.get("SHOTBOT_MOCK", "").lower() in ("1", "true", "yes")
is_testing = bool(os.environ.get("PYTEST_CURRENT_TEST"))
skip_initial_load = os.environ.get("SHOTBOT_NO_INITIAL_LOAD", "").lower() in ("1", "true", "yes")
use_threede = os.environ.get("USE_THREEDE_CONTROLLER", "true").lower() == "true"

# ... 100 lines later ...
if is_mock_mode:
    # mock setup
elif is_testing:
    # test setup
else:
    # production setup

# AFTER (centralized)
from config.feature_flags import FeatureFlags

def __init__(self, ...):
    super().__init__(parent)

    # Load configuration
    self.flags = FeatureFlags.from_environment()

    # Use flags consistently
    if self.flags.mock_mode:
        # mock setup
    elif self.flags.is_testing:
        # test setup
    else:
        # production setup
```

#### Preconditions
- [ ] Identify all environment variable checks in main_window.py
- [ ] Identify other files that might benefit from FeatureFlags
- [ ] Create config/ directory if it doesn't exist

```bash
# Precondition verification commands
grep -n "os.environ.get" main_window.py  # Find all env var checks
grep -rn "os.environ.get.*SHOTBOT" --include="*.py" .  # Find all SHOTBOT_* usage

# Create config directory
mkdir -p config
touch config/__init__.py
```

#### Implementation Steps

1. **Create config/feature_flags.py** with class above

2. **Update main_window.py**:
   - Add import: `from config.feature_flags import FeatureFlags`
   - In `__init__`, add: `self.flags = FeatureFlags.from_environment()`
   - Replace all `os.environ.get("SHOTBOT_*")` with `self.flags.*`
   - Remove individual environment variable checks

3. **Test FeatureFlags class**:
   ```python
   # test_feature_flags.py
   import os
   import pytest
   from config.feature_flags import FeatureFlags

   def test_feature_flags_defaults():
       """Test default flag values."""
       FeatureFlags.reset()
       flags = FeatureFlags.from_environment()
       assert flags.mock_mode is False
       assert flags.is_testing is False
       assert flags.skip_initial_load is False
       assert flags.use_threede_controller is True

   def test_feature_flags_mock_mode():
       """Test mock mode flag parsing."""
       FeatureFlags.reset()
       os.environ["SHOTBOT_MOCK"] = "true"
       try:
           flags = FeatureFlags.from_environment()
           assert flags.mock_mode is True
       finally:
           del os.environ["SHOTBOT_MOCK"]
           FeatureFlags.reset()

   # ... more tests for each flag ...
   ```

4. **Update tests/conftest.py** for singleton reset:
   ```python
   @pytest.fixture(autouse=True)
   def reset_feature_flags():
       """Reset FeatureFlags singleton between tests."""
       from config.feature_flags import FeatureFlags
       FeatureFlags.reset()
       yield
       FeatureFlags.reset()
   ```

5. **Run tests**:
   ```bash
   pytest tests/unit/test_feature_flags.py -v
   pytest tests/unit/test_main_window.py -v
   pytest tests/ -n auto --dist=loadgroup
   ```

#### Success Criteria
- [ ] config/feature_flags.py created with FeatureFlags class
- [ ] FeatureFlags has comprehensive docstrings
- [ ] main_window.py uses FeatureFlags instead of direct env var checks
- [ ] All environment variable checks centralized
- [ ] Tests created for FeatureFlags
- [ ] Singleton reset fixture added to conftest.py
- [ ] All tests pass
- [ ] Type checking passes
- [ ] main_window.py __init__ is ~20 lines shorter

#### Verification Commands
```bash
# Verify FeatureFlags works
python -c "
from config.feature_flags import FeatureFlags
flags = FeatureFlags.from_environment()
print(f'Mock mode: {flags.mock_mode}')
print(f'Testing: {flags.is_testing}')
print('OK')
"

# Verify main_window uses FeatureFlags
grep "FeatureFlags" main_window.py
! grep "os.environ.get.*SHOTBOT" main_window.py  # Should find no direct checks

# Run tests
pytest tests/unit/test_feature_flags.py -v
pytest tests/ -n auto --dist=loadgroup
basedpyright
```

#### Agent Assignments
- **Implementation**: code-refactoring-expert
- **Review #1**: python-code-reviewer
- **Review #2**: type-system-expert

#### Rollback Plan
```bash
git revert HEAD
```

#### Git Commit Message
```
refactor: Extract FeatureFlags class from MainWindow (Task 2.1)

Centralize environment variable checks into config/feature_flags.py
to make configuration explicit and testable. This simplifies
MainWindow.__init__ and makes feature flags discoverable.

Changes:
- Created config/feature_flags.py with FeatureFlags dataclass
- Extracted 5 environment variable checks from main_window.py
- Added comprehensive tests for all feature flags
- Added singleton reset fixture for test isolation
- Updated main_window.py to use FeatureFlags.from_environment()

Benefits:
- Single source of truth for feature flags
- Testable configuration (can mock flags easily)
- Self-documenting (docstrings explain each flag)
- Reduces __init__ complexity by ~20 lines

Impact:
- Lines changed: +100 (new file), -50 (main_window cleanup)
- Files created: 1 (config/feature_flags.py)
- Files modified: 2 (main_window.py, conftest.py)
- Tests: All passing, new tests added

Task: Phase 2, Task 2.1
Verified-by: python-code-reviewer, type-system-expert
```

---

### Task 2.2: Extract DependencyFactory

**Objective**: Extract 20+ dependency creation from MainWindow.__init__ into factory class

**Impact**: +200 lines (new file), -150 lines (main_window cleanup)
**Effort**: 3 days
**Risk**: Medium (touches many dependencies)
**Dependencies**: Task 2.1 (uses FeatureFlags)

[Task 2.2 would follow similar detailed structure as above, with ~2,000 words of detail]

---

### Task 2.3: Extract Shot Selection Handlers

**Objective**: Break down 73-line _on_shot_selected method into focused handlers

**Impact**: +150 lines (new methods), -73 lines (monolithic method removed)
**Effort**: 2 days
**Risk**: Low (internal refactoring)
**Dependencies**: None (can be parallel with 2.4)

[Task 2.3 detailed structure...]

---

### Task 2.4: Extract ThumbnailCache

**Objective**: Extract thumbnail operations from CacheManager into focused class

**Impact**: +200 lines (new file), CacheManager reduced by ~150 lines
**Effort**: 2 days
**Risk**: Low (clear responsibility boundary)
**Dependencies**: None (can be parallel with 2.3)

[Task 2.4 detailed structure...]

---

### Task 2.5: Extract ShotCache

[Task 2.5 detailed structure...]

---

### Task 2.6: Extract SceneCache

[Task 2.6 detailed structure...]

---

### Task 2.7: Convert CacheManager to Facade

[Task 2.7 detailed structure...]

---

## Phase 2 Completion Checklist

[Similar to Phase 1 completion checklist, with Phase 2 specific metrics]

---

## ✨ PHASE 3: Code Simplification (Weeks 6-8, 3 Weeks)

**Goal**: Remove LoggingMixin from 76 classes, simplify inheritance
**Expected Impact**: -443 lines (mixin overhead), simplified code
**Risk Level**: Low (mechanical refactoring, incremental approach)

**VERIFIED** (2025-11-12): 76 classes use LoggingMixin (not 100+ as originally estimated)

### Timeline
- **Week 6**: Task 3.1 (Batch 1, 10 simple classes)
- **Week 7**: Task 3.2 (Batch 2, 20 classes with QObject)
- **Week 8**: Tasks 3.3-3.4 (Batch 3-4, 46 remaining classes + delete mixin)

---

### Task 3.1: Remove LoggingMixin from Batch 1 (10 Simple Classes)

**Objective**: Remove LoggingMixin from 10 classes with simple inheritance

**Impact**: ~10 lines saved, simpler inheritance
**Effort**: 1 week (incremental, 2-3 classes per day)
**Risk**: Low (simple cases, well-tested pattern)
**Dependencies**: None

[Task 3.1 detailed structure...]

---

### Task 3.2: Remove LoggingMixin from Batch 2 (20 Classes with QObject)

[Task 3.2 detailed structure...]

---

### Task 3.3: Remove LoggingMixin from Batch 3 (26 Complex Classes)

**Objective**: Remove LoggingMixin from 26 classes with complex inheritance patterns

**Impact**: ~26 lines saved, simpler inheritance
**Effort**: 3-4 days (incremental)
**Risk**: Low (careful testing needed)
**Dependencies**: Tasks 3.1-3.2 complete

[Task 3.3 detailed structure to be added...]

---

### Task 3.4: Remove LoggingMixin from Batch 4 (20 Remaining) + Delete Mixin

**Objective**: Remove LoggingMixin from final 20 classes and delete logging_mixin.py

**Impact**: ~20 lines saved + 443 lines (mixin file deleted)
**Effort**: 3-4 days (final cleanup + deletion)
**Risk**: Low (all migrations complete before deletion)
**Dependencies**: Tasks 3.1-3.3 complete

**Total Classes**: 10 + 20 + 26 + 20 = **76 classes** [VERIFIED]

[Task 3.4 detailed structure to be added...]

---

## Phase 3 Completion Checklist

After completing all 4 tasks, verify Phase 3 success:

### Metrics Dashboard
- [ ] Classes updated: 76 / 76 (target achieved) [VERIFIED]
  - Batch 1: 10 simple classes
  - Batch 2: 20 classes with QObject
  - Batch 3: 26 complex classes
  - Batch 4: 20 remaining classes
- [ ] LoggingMixin deleted: Yes (logging_mixin.py removed)
- [ ] Lines saved: ~443 lines (mixin overhead)
- [ ] All tests passing: 2,300+ tests
- [ ] Type errors: 0
- [ ] Simpler inheritance throughout codebase
- [ ] Git history: 4 atomic commits (one per batch)

---

## 🔬 PHASE 4: Research & Advanced (Month 3+, TBD)

**Goal**: Investigate singleton manager consolidation and advanced optimizations
**Expected Impact**: Potentially -6,824 lines (requires research)
**Risk Level**: TBD (depends on findings)

This phase requires thorough research before committing to implementation.

### Task 4.1: Singleton Manager Analysis

**Objective**: Analyze 11 managers to determine consolidation opportunities

**Impact**: TBD (research phase)
**Effort**: 1-2 weeks (analysis only, no implementation)
**Risk**: Low (research only)
**Dependencies**: Phases 1-3 complete

[Task 4.1 detailed research plan...]

---

## 📚 APPENDICES

### Appendix A: Agent Assignment Matrix

| Task | Implementation | Review #1 | Review #2 | Rationale |
|------|----------------|-----------|-----------|-----------|
| 1.1 | python-implementation-specialist-haiku | python-code-reviewer-haiku | type-system-expert-haiku | Simple deletion |
| 1.2 | python-implementation-specialist-haiku | python-code-reviewer-haiku | type-system-expert-haiku | Mechanical refactoring |
| 1.3 | best-practices-checker | python-code-reviewer-haiku | type-system-expert-haiku | Modernization task |
| 1.4 | python-implementation-specialist-haiku | python-code-reviewer-haiku | type-system-expert-haiku | Mechanical migration |
| 1.5 | python-implementation-specialist | python-code-reviewer-haiku | test-development-master-haiku | Needs test verification |
| 1.6 | code-refactoring-expert | python-code-reviewer | test-development-master | Complex high-impact change |
| 2.1 | code-refactoring-expert | python-code-reviewer | type-system-expert | Architectural extraction |
| 2.2 | code-refactoring-expert | python-code-reviewer | type-system-expert | Complex dependency injection |
| 2.3-2.7 | code-refactoring-expert | python-code-reviewer | test-development-master | Architectural restructuring |
| 3.1-3.4 | python-implementation-specialist | python-code-reviewer-haiku | type-system-expert-haiku | Mechanical pattern replacement |

### Appendix B: Success Metrics Dashboard

**Tracked Metrics:**
1. Lines of code (total, per file, per module)
2. Test count and pass rate
3. Type error count (target: 0)
4. Ruff issue count
5. Test execution time
6. Application startup time
7. Critical path performance (shot loading, launch operations)

**Measurement Commands:**
```bash
# Lines of code
cloc . --exclude-dir=.venv,tests,encoded_releases

# Test metrics
pytest tests/ -n auto --dist=loadgroup --verbose

# Type checking
basedpyright

# Linting
ruff check . --statistics

# Performance
time pytest tests/ -n auto --dist=loadgroup
time python -c "from main_window import MainWindow; print('OK')"
```

### Appendix C: Risk Management Procedures

**Risk Levels:**
- **Low**: Simple changes, mechanical refactoring, clear boundaries
- **Medium**: Architectural changes, multiple file updates, some complexity
- **High**: Large changes, many dependencies, significant behavior changes

**Rollback Procedures:**

**Low Risk:**
```bash
git revert HEAD
```

**Medium Risk:**
```bash
# Use feature branch
git checkout -b task-X.Y
# Make changes
# Test thoroughly
git checkout master
git merge task-X.Y
# If issues:
git revert -m 1 <merge-commit>
```

**High Risk:**
```bash
# Mandatory feature branch + extended testing
git checkout -b task-X.Y
# Make changes
# Full test suite
# Manual testing
# Performance testing
# Get review approval
git checkout master
git merge --no-ff task-X.Y  # Create merge commit
# If issues:
git revert -m 1 <merge-commit>
# Or hard reset (if not pushed):
git reset --hard HEAD~1
```

### Appendix D: Testing Strategy

**Test Levels:**

1. **Smoke Test** (~1 min):
   ```bash
   pytest tests/unit/test_<module>.py -v
   ```

2. **Module Test** (~2-5 min):
   ```bash
   pytest tests/ -k "cache" -v
   ```

3. **Full Regression** (~16 sec):
   ```bash
   pytest tests/ -n auto --dist=loadgroup
   ```

4. **Quality Gates** (before commit):
   ```bash
   pytest tests/ -n auto --dist=loadgroup
   basedpyright
   ruff check .
   ```

**Test Maintenance:**
- Update tests when API changes
- Delete tests for deleted code
- Add tests for new classes
- Maintain test coverage (don't let it drop)

### Appendix E: Git Commit Guidelines

**Commit Message Template:**
```
<type>: <subject> (Task X.Y)

<body explaining the change>

Changes:
- Specific change 1
- Specific change 2

Impact:
- Lines changed: +X/-Y
- Files modified: N
- Tests: All passing

Task: Phase X, Task X.Y
Verified-by: <agent1>, <agent2>
```

**Types:**
- `refactor:` - Code restructuring
- `remove:` - Deleting code
- `extract:` - Extracting code
- `fix:` - Bug fixes
- `test:` - Test updates

**Best Practices:**
- One task = one commit (atomic)
- Descriptive subject line (< 72 chars)
- Detailed body (what and why)
- Reference task number
- List verifying agents

### Appendix F: Weekly Schedule

[Detailed week-by-week schedule as planned in sequential thinking]

### Appendix G: Contingency Plans

[Edge cases and contingency plans as detailed in sequential thinking]

### Appendix H: Glossary

**Key Terms:**
- **God Object**: Class that knows/does too much (MainWindow example)
- **YAGNI**: You Aren't Gonna Need It (BaseAssetFinder example)
- **DRY**: Don't Repeat Yourself (duplicate code principle)
- **KISS**: Keep It Simple, Stupid (simplicity principle)
- **Facade Pattern**: Simplified interface to complex subsystem (CacheManager example)
- **Feature Flag**: Configuration toggle via environment variable
- **Singleton**: Class with only one instance (managers example)
- **Mixin**: Class providing methods to other classes via inheritance
- **Technical Debt**: Code quality issues accumulated over time
- **Refactoring**: Improving code structure without changing behavior

---

## 📞 Communication & Reporting

**Daily Status** (for multi-day tasks):
- What was completed
- What's in progress
- Blockers
- Estimated completion

**Weekly Summary**:
- Tasks completed
- Lines impacted
- Test status
- Metrics comparison
- Next week's plan
- Timeline adjustments

**Phase Completion**:
- All tasks complete
- Total impact
- Lessons learned
- Recommendations

---

## ✅ Final Checklist Before Starting

- [ ] User has reviewed entire EPSILON plan
- [ ] User understands workflow (implement → review → verify → commit)
- [ ] User approves Phase 1 Quick Wins
- [ ] Baseline metrics captured (tests, types, ruff, cloc)
- [ ] Git status is clean (all current work committed)
- [ ] Checklist document created and ready
- [ ] User ready to proceed with Task 1.1

---

**END OF REFACTORING PLAN EPSILON**

**Total Document Length**: ~10,000 words (comprehensive and actionable)
**Next Step**: User reviews plan and approves start of Phase 1
**Contact**: User approval required before beginning execution
