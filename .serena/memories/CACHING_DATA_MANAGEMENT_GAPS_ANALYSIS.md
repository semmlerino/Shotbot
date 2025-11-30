# Shotbot Caching & Data Management Gaps Analysis

## Executive Summary

This analysis identifies **11 significant functionality gaps** in Shotbot's caching, data loading, and presentation systems that limit user productivity. These gaps fall into 5 categories:

1. **Cache System Gaps** (3 gaps)
2. **File Discovery & Access** (2 gaps)  
3. **Data Synchronization** (2 gaps)
4. **Search & Filtering** (2 gaps)
5. **Performance & Responsiveness** (2 gaps)

**Overall Impact**: Medium-High. These gaps don't break functionality but limit workflow efficiency, particularly for artists working with large shot lists or multi-project setups.

---

## GAP 1: No Cross-Shot Media Summary Cache

**Area**: Cache system → Media aggregation  
**Current Behavior**: Each shot loads its media (3DE, Maya, Nuke files) independently. No cached index of "what media files exist across all shots".  
**Problem**: Artists searching for "which shots have Maya files" or "show me all 3DE scenes" must manually browse or refresh each shot individually.

**Proposed Solution**:
- Add new cache file: `~/.shotbot/cache/media_index.json`
- Structure: `{ "3de": [{"show": "XX", "seq": "sq01", "shot": "001", "count": 5}, ...], "maya": [...], "nuke": [...] }`
- Update mechanism: Incremental merge (like 3DE scenes cache) on each discovery
- TTL: Persistent with optional 1-hour refresh

**Implementation Complexity**: Medium
- Uses existing `CacheManager` infrastructure
- Merge algorithm similar to `merge_scenes_incremental()`
- Add method: `CacheManager.get_media_index_for_type(file_type: FileType) -> dict`

**User Benefit**: Artists can quickly filter/search for shots with specific media types without browsing individually.

**Example Use Case**:
```
Artist: "Show me all shots in sq010 with 3DE files"
Current: Must open shot one-by-one, check if 3DE tab has files
Proposed: Click filter "Has 3DE", see list instantly
```

---

## GAP 2: No Background File Discovery with Progress Reporting

**Area**: File discovery → User feedback  
**Current Behavior**: 3DE scene discovery runs in background, but **no progress indication** to user. Files panel shows "Loading..." spinner but no file count or scan status.

**Problem**: User doesn't know if scan is searching 10 directories or 1000. Unclear if system is working or hung.

**Proposed Solution**:
- Add progress reporting to `ThreeDESceneWorker` → emit progress signals with:
  - `shots_scanned: int` (e.g., "Scanned 247 shots")
  - `files_found: int` (e.g., "Found 1,243 3DE files")
  - `current_show: str` (e.g., "Scanning show: PROJECTX")
  - `estimated_remaining_secs: int`

- Display in Files panel header:
  ```
  Files (Scanning... 247 shots, 1,243 files found, ~8s remaining)
  ```

- Add "Cancel Scan" button while scanning active

**Implementation Complexity**: Simple
- Existing `ThreeDESceneWorker` already emits `progress_reported` signal
- Add counters to worker loop
- Update Files panel header with progress text
- Add cancel button tied to `worker.request_stop()`

**User Benefit**: Clear visibility into background operations reduces anxiety ("Is it working?"), enables user decision ("Should I wait or cancel?").

---

## GAP 3: No TTL-Based Smart Refresh for User-Specific Data

**Area**: Cache system → Data staleness  
**Current Behavior**: "My Shots" cache has 30-minute TTL globally. Doesn't account for whether user workspace has actually changed.

**Problem**: 
- If user doesn't change workspaces, cache is refreshed unnecessarily after 30 min
- If user changes workspaces multiple times, needs 30 min for new data
- No way to force refresh when user knows data changed

**Proposed Solution**:
- Track workspace path in cache metadata: `{ "data": [...], "cached_at": "...", "workspace_path": "..." }`
- Before serving cached shots, check: `is_workspace_path_different(cached_path, current_path)`
- If different, invalidate cache and refresh immediately
- Add "Refresh Now" button in My Shots header (manual refresh)
- Add Settings option: "Auto-refresh when workspace changes"

**Implementation Complexity**: Simple
- Modify `CacheManager._write_json_cache()` to include workspace_path in metadata
- Add `_read_json_cache()` check for path change
- Add refresh button signal → slot in MainWindow

**User Benefit**: 
- No unnecessary refreshes when workspace hasn't changed
- Instant data sync when workspace does change
- Manual refresh option for edge cases

---

## GAP 4: No Incremental Plate/Media List Caching

**Area**: File discovery → Plate discovery  
**Current Behavior**: Raw plates discovered per-shot on demand. No cache of "which shots have which plate types" (FG, BG, COMP, etc.).

**Problem**: If artist needs "all shots with background plates", must manually check each shot. No aggregation.

**Proposed Solution**:
- Cache discovered plate types per shot in persistent cache: `~/.shotbot/cache/plate_types_by_shot.json`
- Structure: `{ "PROJECTX/sq010/001": ["FG", "BG"], "PROJECTX/sq010/002": ["FG"], ... }`
- Update on each raw plate scan (incremental merge)
- Enable filter: "Has BG Plates", "Missing FG Plates", etc.

**Implementation Complexity**: Medium
- Reuse incremental merge pattern from 3DE scenes
- Add `RawPlateFinder.get_plate_summary()` method
- Add filter UI to Shot grid header

**User Benefit**: Quick filtering/searching for shots by plate availability.

---

## GAP 5: No File Watch/Auto-Refresh for External Changes

**Area**: File discovery → Change detection  
**Current Behavior**: New files only discovered on manual refresh or TTL expiration. If files added externally (another artist, automated pipeline), user sees stale data until refresh.

**Problem**: 
- Multi-artist workflow doesn't sync in real-time
- Automated file generation (batch 3DE export) invisible until refresh
- No warning that data may be stale

**Proposed Solution**:
- Optional file watch mode (Settings → "Auto-refresh on file changes")
- Uses `watchdog` library to monitor cache directories for changes
- When .3de, .ma, .nk files added/removed, emit refresh signal
- Update Files section within 2 seconds of file change
- Add indicator: "Data auto-refreshed 30s ago"

**Implementation Complexity**: Medium
- Add `FileWatcher` class using `watchdog.FileSystemEventHandler`
- Register watchers on show/sequence/shot directories
- Emit signals to `ThreeDESceneModel`, `ShotModel` to refresh
- Add Settings checkbox + indicator label

**User Benefit**: Real-time visibility into external file changes without manual refresh.

---

## GAP 6: No Shot Search by Partial Attributes

**Area**: Search & filtering → Query capability  
**Current Behavior**: Filters only by:
- Show (dropdown)
- Text (substring in shot name)

No way to filter by: version range, date range, creator, file count, media type combo.

**Problem**: Artist needs "all shots created by this department in the last week with both 3DE and Maya" → impossible without manual browsing.

**Proposed Solution**:
- Add `AdvancedSearchWidget` with query builder:
  ```
  [ Show dropdown ] [ ≥ Version ] [ From Date ] [ To Date ]
  [ Media Type ] [ Creator ] [ File Count ] [ Apply ]
  ```

- Query format: `show=XX AND version>=5 AND created>2024-11-20`
- Save searches as presets: "My Department's Latest", "Needs 3DE", etc.
- Execute via cached data (no new scan needed)

**Implementation Complexity**: Medium
- Add `ShotQuery` dataclass to represent filters
- Add `ShotModel.filter_shots(query: ShotQuery)` method
- Add UI widget with preset management
- Store presets in `SettingsManager`

**User Benefit**: Quick access to complex shot subsets without manual work.

---

## GAP 7: No Bulk Operations on Cached Data

**Area**: Data management → Batch operations  
**Current Behavior**: Users can select individual shots and launch them. No batch operations (bulk refresh, bulk export metadata, bulk cache clear by criteria).

**Problem**: 
- To refresh 50 shots, must refresh each individually
- To export shot list for reporting, must manual copy-paste
- Cache gets stale selectively (some shows, not others)

**Proposed Solution**:
- Add bulk operations:
  - "Refresh Selected Shots" (show progress bar)
  - "Export Shot List" (CSV with metadata)
  - "Clear Cache for Show" (only refresh that show)
  - "Verify Cache Integrity" (check all cached data valid)

- Add multi-select in Shot grid (Ctrl+Click)
- Add "Bulk Operations" menu in right-click context

**Implementation Complexity**: Medium
- Use existing `QThreadPool` to parallelize refreshes
- Add progress dialog: "Refreshing 50 shots (23/50 complete)"
- Add CSV export via `CacheManager.get_shots_for_export()`

**User Benefit**: Faster data management for large shot lists.

---

## GAP 8: No Thumbnail Pre-Caching/Warming

**Area**: Performance → Thumbnail loading  
**Current Behavior**: Thumbnails loaded on-demand as rows become visible (viewport-aware loading). First scroll slow while images generate.

**Problem**: 
- Opening app with 1000 shots = slow first scroll
- Switching to Shot grid after opening = lag while thumbnails load
- No pre-generation during idle

**Proposed Solution**:
- Add background thumbnail pre-caching:
  - When app is idle (no user input for 10 seconds), start generating thumbnails for visible + next 50 rows
  - Queue: `ThreadPool` with low priority
  - Reuse existing `ThumbnailLoaderRunnable` infrastructure
  - Skip if user actively scrolling (cancel queue, restart on idle)

- Add "Warm Thumbnail Cache" button in Settings
  - Generates all thumbnails for current show in background
  - Shows progress dialog: "Generating thumbnails (523/1000)"

**Implementation Complexity**: Simple
- Add `IdleTimer` using `QTimer` to detect user inactivity
- Add `ThumbnailPrewarmer` class extending `ThreadPool` logic
- Reuse existing thumbnail generation code
- Add button to `SettingsDialog`

**User Benefit**: Faster scrolling, smoother user experience.

---

## GAP 9: No Dependent Data Invalidation

**Area**: Cache system → Data consistency  
**Current Behavior**: Each cache type (shots, 3DE scenes, previous shots) invalidated independently. **No cascade invalidation** when dependencies change.

**Problem**:
- If "My Shots" refreshes and shots are added/removed, 3DE scenes cache remains stale
- If user clears cache, only current tab affected, others still have old data
- Inconsistent state possible

**Proposed Solution**:
- Create dependency graph in `CacheManager`:
  ```python
  DEPENDENCIES = {
      "shots": ["3de_scenes", "previous_shots"],  # Changing shots affects these
      "3de_scenes": [],  # Independent
      "previous_shots": [],  # Independent
  }
  ```

- When `cache_shots()` called:
  - Clear dependent caches automatically
  - Emit `cache_invalidated` signal with dependency info
  - Update UI to show what was cleared

- Add `clear_cache_cascade(cache_type)` method

**Implementation Complexity**: Simple
- Add `DEPENDENCIES` dict to `CacheManager`
- Modify `_write_json_cache()` to clear dependents
- Emit signal with cleared cache names

**User Benefit**: Guaranteed consistency, no stale data surprises.

---

## GAP 10: No Cache Validation/Integrity Check

**Area**: Cache system → Data reliability  
**Current Behavior**: Cached JSON loaded as-is. No validation that data is:
- Complete (all required fields present)
- Consistent (no duplicate shots, valid paths)
- Current (metadata valid)

**Problem**: 
- Corrupted JSON silently fails → empty shot list
- Duplicate shots from merge errors → overcounting
- Stale paths (shot moved) → broken thumbnails

**Proposed Solution**:
- Add `CacheValidator` class with checks:
  ```python
  def validate_shots(shots: list[ShotDict]) -> ValidationResult:
      errors = []
      if not isinstance(shots, list):
          errors.append("Not a list")
      for shot in shots:
          if "show" not in shot: errors.append(f"Missing 'show' in {shot}")
          if "sequence" not in shot: errors.append(...)
          # ... more checks
      return ValidationResult(is_valid=len(errors)==0, errors=errors)
  ```

- Call validator before returning cached data
- Log validation errors: "Cache validation failed: 3 errors"
- Fallback to empty data if validation fails
- Add "Validate All Caches" button in Settings

**Implementation Complexity**: Simple
- Add `validators.py` module
- Call in `_read_json_cache()` before returning
- Add button to `SettingsDialog` to trigger manual check

**User Benefit**: Earlier error detection, prevents silent data loss.

---

## GAP 11: No Shared Workspace Cache (Multi-User)

**Area**: Data synchronization → Multi-artist workflow  
**Current Behavior**: Each user has their own `~/.shotbot/cache/`. No ability to share discoveries (e.g., "scenes I found on the network").

**Problem**: 
- If Artist A discovers all 3DE scenes (slow scan), Artist B must re-scan them (redundant)
- No central "known" 3DE scenes list
- Multi-artist workflows inefficient

**Proposed Solution**:
- Add optional "Shared Cache" location (network path in Settings):
  - `{SHARED_CACHE}/3de_scenes_shared.json` (read-only, updated by admin)
  - `{SHARED_CACHE}/plate_types_shared.json` (read-only)

- Merge strategy:
  1. Load user's local cache (fast)
  2. Load shared cache if configured (adds discovered items)
  3. Merge: user local + shared (user local takes precedence if same key)
  4. Report: "Found 1,000 local scenes + 500 shared = 1,500 total"

- Add Settings option: "Shared Cache Path"
- Add status indicator: "Using shared cache: /mnt/cache"

**Implementation Complexity**: Medium
- Add `shared_cache_path` to `SettingsManager`
- Add `_load_shared_cache()` method to `CacheManager`
- Add merge logic: prefer local over shared on key collision
- Add settings UI and status indicator

**User Benefit**: Faster discovery in multi-artist teams, reduces redundant work.

---

## SUMMARY TABLE

| Gap # | Category | Complexity | User Impact | Implementation |
|-------|----------|-----------|------------|---------------|
| 1 | Cache | Medium | High | Media index cache + merge logic |
| 2 | Discovery | Simple | Medium | Progress signals + UI label |
| 3 | Cache | Simple | Medium | Metadata tracking + refresh button |
| 4 | Discovery | Medium | Medium | Plate cache + filters |
| 5 | Discovery | Medium | High | File watcher + auto-refresh |
| 6 | Search | Medium | High | Query builder + presets |
| 7 | Management | Medium | Medium | Bulk ops UI + threading |
| 8 | Performance | Simple | Medium | Idle timer + pre-caching |
| 9 | Cache | Simple | High | Dependency graph + cascade clear |
| 10 | Cache | Simple | Medium | Validator class + error reporting |
| 11 | Sync | Medium | Low | Shared cache path + merge |

---

## Prioritization Recommendation

**High Impact, Simple to Implement** (Do First):
- Gap 3: Smart TTL with workspace change detection
- Gap 9: Dependent data invalidation
- Gap 10: Cache validation

**High Impact, Medium Effort** (Do Second):
- Gap 2: Progress reporting for file discovery
- Gap 6: Advanced search/filtering
- Gap 5: File watch for external changes

**Nice-to-Have** (Do Later):
- Gap 1: Media index cache
- Gap 4: Plate types cache
- Gap 7: Bulk operations
- Gap 8: Thumbnail pre-caching
- Gap 11: Shared workspace cache
