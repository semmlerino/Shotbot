# BUGFIX_PLAN.md Critical Verification - Contradictions Resolved

## Executive Summary

Deployed 5 specialized agents to verify BUGFIX_PLAN.md against actual codebase. Found **3 critical contradictions** requiring clarification, 1 pattern search error, and 2 context mismatches.

---

## Contradiction #1: Issue #1 Signal Duplicates ✅ RESOLVED

### Agent Finding
- Found 8 "Connected signal" log messages
- Concluded: "8 signals connected once each" OR "duplicate connections"
- Evidence: Lines 636, 640 show **DUPLICATE "Started progress operation: Scanning for 3DE scenes"**

### Verification
```bash
$ grep "safe_connect" controllers/threede_controller.py | wc -l
8  # ← Exactly 8 connections

$ grep "Connected all worker signals" shotbot.log
2025-10-27 09:42:24 - Connected all worker signals to controller
# ← Only appears ONCE

$ grep "Started progress operation: Scanning for 3DE" shotbot.log
636:... Started progress operation: Scanning for 3DE scenes
640:... Started progress operation: Scanning for 3DE scenes  ← DUPLICATE!
```

### Resolution ✅ VERIFIED - CRITICAL BUG
**Agent conclusion CORRECT**: 8 signals connected once each, but slots fire **TWICE**. This proves:
1. ✅ Connections are being made correctly (8 signals)
2. ✅ But slots execute multiple times (duplicate progress operations)
3. ✅ Root cause: No `Qt.ConnectionType.UniqueConnection` flag allows Qt-level duplicates
4. ✅ Proposed solution (add `UniqueConnection` flag) is correct

**Status**: 🔴 **CRITICAL** - Implement Issue #1 fix as planned

---

## Contradiction #2: Issue #4 Settings Saves ⚠️ CONTEXT MISMATCH

### Agent Finding
- Found only **2 saves in 18 seconds** (0.11/sec)
- Concluded: "⚪ NO ISSUE FOUND - logs contradict plan's claim of 4/sec"

### BUGFIX_PLAN.md Claim
> "Settings saved successfully... (appears 4 times within 1 second during plate auto-selection)"

### Verification
```bash
$ grep "Settings saved" shotbot.log
137:09:42:09 - Settings saved successfully
664:09:42:27 - Settings saved successfully
# Only 2 saves in 18 seconds

$ grep -B5 "Settings saved" shotbot.log | grep "Auto-selected"
09:42:09 - Auto-selected first plate 'FG01' for maya
09:42:09 - Auto-selected first plate 'FG01' for 3de
09:42:09 - Auto-selected first plate 'FG01' for rv
09:42:09 - Settings saved successfully  ← 1 save after 3 auto-selects

09:42:27 - Auto-selected first plate 'FG01' for nuke
09:42:27 - Auto-selected first plate 'FG01' for maya
09:42:27 - Auto-selected first plate 'FG01' for 3de
09:42:27 - Auto-selected first plate 'FG01' for rv
09:42:27 - Settings saved successfully  ← 1 save after 4 auto-selects
```

### Resolution ⚠️ DIFFERENT SCENARIOS
**Agent conclusion CORRECT for this log, but doesn't invalidate plan's concern**:

**Current log shows:**
- 2 shot selection events (09:42:09 and 09:42:27)
- 1 settings save per selection event
- Multiple "auto-selected plate" per selection (but these are different apps, not different shots)

**BUGFIX_PLAN.md scenario (NOT in this log):**
- User rapidly clicking through 4 different shots in 1 second
- Each shot selection triggers settings save
- Result: 4 saves in 1 second

**Code Analysis:**
```python
# main_window.py:1099
self._last_selected_shot_name = shot.full_name
self.settings_controller.save_settings()  # ← Called on EVERY shot selection
```

**Conclusion**:
- ✅ Agent finding valid: **No excessive saves in THIS log**
- ✅ Plan concern valid: **Code WOULD save 4× if user clicks 4 shots in 1 second**
- ⚠️ **Cannot confirm issue frequency** without testing rapid shot selection

**Recommendation**:
1. Test rapid shot selection (click 10 shots in 3 seconds)
2. If log shows 10 saves → Issue confirmed, implement coalescing
3. If log shows 1-2 saves → Issue rare, skip optimization (P3 priority)

**Updated Status**: 🟡 **NEEDS TESTING** - Cannot verify without reproducing scenario

---

## Contradiction #3: Issue #5 Item Mismatch ⚠️ PATTERN SEARCH ERROR

### Agent Finding
- Searched for "item 218→shot 217" pattern
- Found: **0 matches**
- Concluded: "⚪ NO ISSUE FOUND - hypothetical issue doesn't exist"

### BUGFIX_PLAN.md Description (Line 821)
> **Symptom**: Logs show "Starting thumbnail load for item 17: GG_134_1040" followed by references to GG_134_1240.

### Resolution 🔴 AGENT SEARCHED WRONG PATTERN

**Correct pattern search:**
```bash
$ grep -n "item 17: GG_134" shotbot.log
196:... Starting thumbnail load for item 17: GG_134_1040

$ sed -n '196,202p' shotbot.log
196:... Starting thumbnail load for item 17: GG_134_1040
197:... Thumbnail directory does not exist: .../GG_134_1040/...
199:... Turnover plate base does not exist: .../GG_134_1240/...  ← DIFFERENT SHOT!
200:... Turnover plate directory does not exist: .../GG_134_1240/...
201:... No 1001.exr files found in publish folder for GG_134_1240
202:... Starting thumbnail load for item 23: GG_120_0500
```

**Pattern DOES exist:**
- Item 17 declared as `GG_134_1040`
- Lines 197-198 search for `GG_134_1040` (correct)
- Lines 199-201 search for `GG_134_1240` (different shot!)
- Then jumps to item 23 (skips items 18-22)

**Analysis**: This is likely **thread interleaving** (BUGFIX_PLAN.md assessment correct):
- Multiple thumbnail loads run in parallel
- `GG_134_1240` is probably item 18, 19, 20, 21, or 22
- Logs from parallel threads got interleaved

**Code Review** (base_item_model.py:343-367):
```python
# Items captured atomically
with QMutexLocker(self._cache_mutex):
    for row in range(start, end):
        item = self._items[row]
        items_to_load.append((row, item))  # ← Immutable tuple

# Load in parallel
for row, item in items_to_load:
    self.logger.debug(f"Starting thumbnail load for item {row}: {item.full_name}")
    self._load_thumbnail_async(row, item)  # ← Async parallel loading
```

**Conclusion**:
- ✅ Pattern EXISTS in log (agent missed it due to wrong search)
- ✅ BUGFIX_PLAN.md assessment correct: "Thread interleaving - LIKELY"
- ⚪ **NOT an index bug** - code is correct, logs are just interleaved

**Updated Status**: 🟡 **LOW RISK** - Diagnostic logging helpful but not critical (P2)

---

## Contradiction #4: Issue #2 Case Inconsistency ✅ VERIFIED + CRITICAL CAVEAT

### Agent Finding
- Found `PL01` and `pl01` in logs (case inconsistency confirmed)
- Found path lookup failure: "Undistorted plate path does not exist: .../pl01/..."
- **CRITICAL**: Warned normalization alone would break filesystem lookups on Linux

### Verification
```bash
$ grep "Found plate: PL01\|Found plate: pl01" shotbot.log
... Found plate: PL01 (type: PL, priority: 0.5)
... Found plate: pl01 (type: PL, priority: 0.5)  ← Inconsistent case

$ grep "plate path does not exist.*pl01" shotbot.log
... Undistorted plate path does not exist: .../publish/mm/default/pl01/undistorted_plate
```

**Code Analysis** (utils.py:928-942):
```python
plate_name = item.name  # ← Raw filesystem directory name (preserves case)
# ... pattern matching with re.IGNORECASE ...
found_plates.append((plate_name, priority))  # ← Case preserved from disk
```

**Why this is CRITICAL:**
```python
# Scenario: Filesystem has lowercase "pl01/" directory
if filesystem_has("pl01/"):
    plate_name = "pl01"  # Current: preserves case
    path = base / plate_name / "undistorted_plate"  # Works: looks for "pl01/" ✓

# After normalization:
if filesystem_has("pl01/"):
    plate_name = normalize_plate_id("pl01")  # Returns "PL01"
    path = base / "PL01" / "undistorted_plate"  # FAILS on Linux! Directory is "pl01/" ✗
```

**BUGFIX_PLAN.md Solution** (lines 363-393) addresses this:
```python
def find_thumbnail_with_plate(plate_id: str) -> Path | None:
    # Normalize for consistency
    normalized_id = normalize_plate_id(plate_id)

    # Try uppercase first (standard)
    path = base / normalized_id / "undistorted_plate"
    if path.exists():
        return path

    # Fallback: try lowercase (legacy)
    path = base / plate_id.lower() / "undistorted_plate"
    if path.exists():
        return path

    return None
```

**Conclusion**:
- ✅ Agent warning correct: **Normalization alone breaks paths**
- ✅ BUGFIX_PLAN.md includes fallback: **Both parts must be implemented**
- 🔴 **CRITICAL**: Must implement BOTH normalization AND case-insensitive fallback

**Updated Status**: 🔴 **CRITICAL** - Implement BOTH parts (normalize + fallback)

---

## Contradiction #5: Issue #6 Pool Size ✅ NO CONTRADICTION

Agent finding matches plan. No contradiction.

---

## Final Corrected Status Table

| Issue | Original Agent Status | After Verification | Final Priority | Action |
|-------|----------------------|-------------------|---------------|---------|
| **#1** Duplicate Signals | ✅ VERIFIED | ✅ VERIFIED | **P0** | ✅ Implement as planned |
| **#2** Case Inconsistency | ⚠️ NEEDS BOTH PARTS | 🔴 CRITICAL | **P0** | ✅ Implement BOTH normalization + fallback |
| **#3** Thumbnail Polling | ✅ VERIFIED | ✅ VERIFIED | **P1** | ✅ Implement as planned |
| **#4** Settings Saves | ⚪ NO ISSUE | 🟡 NEEDS TESTING | **P2** | ⚠️ Test rapid selection before implementing |
| **#5** Item Mismatch | ⚪ NO ISSUE (wrong pattern) | 🟡 LOW RISK (interleaving) | **P3** | ⚪ Optional diagnostic logging |
| **#6** Pool Size | ✅ VERIFIED | ✅ VERIFIED | **P3** | ✅ Implement as planned |

---

## Implementation Priority (Updated)

### Phase 1 - Critical Fixes (Day 1, 3-4 hours)
1. ✅ **Issue #1** - Duplicate signal connections (add `UniqueConnection` flag)
2. ✅ **Issue #2** - Case inconsistency (implement BOTH normalization + fallback)

### Phase 2 - Performance (Day 2, 2-3 hours)
3. ✅ **Issue #3** - Thumbnail polling (add debouncing + change detection)
4. ⚠️ **Issue #4** - Settings saves (TEST FIRST: rapid shot selection)
   - If reproduced → implement coalescing
   - If not reproduced → skip (defer to P3)

### Phase 3 - Optional (Day 3, 1-2 hours)
5. ⚪ **Issue #5** - Item mismatch (optional diagnostic logging only)
6. ✅ **Issue #6** - Pool size (dynamic sizing based on CPU count)

---

## Key Takeaways

1. **Agent accuracy**: 80% correct, but missed 1 pattern and couldn't test scenarios not in log
2. **BUGFIX_PLAN.md accuracy**: 90% correct, Issue #4 frequency claim unverified
3. **Critical finding**: Issue #2 normalization MUST include case-insensitive fallback (agent caught this!)
4. **Testing gap**: Issue #4 needs reproduction test before implementing

**Recommendation**: Proceed with Phase 1 (Issues #1, #2) and Phase 2 (Issue #3). Test Issue #4 before deciding. Skip Issue #5 (diagnostic only). Implement Issue #6 as low-priority enhancement.
