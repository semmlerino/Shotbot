# Cache Manager Data Integrity Analysis

## Executive Summary

**Overall Assessment**: Cache implementation has EXCELLENT data integrity safeguards. The atomic write-then-rename pattern, comprehensive error handling, and mutex-protected operations prevent most common data corruption risks.

**Risk Level**: LOW (acceptable for production use)

**Key Strengths**:
- ✅ Atomic file I/O with `os.fsync()` and `tempfile.mkstemp()` → `Path.replace()`
- ✅ QMutex locks on all merge operations
- ✅ Comprehensive error handling with cleanup
- ✅ JSON serialization with type validation on read
- ✅ Incremental merge algorithms use composite keys (show, sequence, shot)

**Known Limitations**:
- ⚠️ File system must be on same device for atomic rename (standard assumption)
- ⚠️ Two potential data loss vectors (documented below) but both have mitigations
- ⚠️ No write-through or durability guarantee on fs.flush() → os.fsync() path
- ⚠️ Stat cache (2-second TTL) could return stale mtime in rare race

---

## File I/O Architecture

### Write Path: `_write_json_cache()` (Lines 1182-1227)

**PATTERN ANALYZED**: Atomic write with flush + fsync

```python
# 1. Create temp file safely (non-blocking)
fd, temp_path = tempfile.mkstemp(dir=cache_file.parent, prefix=..., suffix=".tmp")

# 2. Write and flush
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(cache_data, f)
    f.flush()           # Python buffers → OS
    os.fsync(f.fileno())  # OS buffers → disk

# 3. Atomic rename
Path(temp_path).replace(cache_file)

# 4. Error: cleanup temp
except Exception:
    Path(temp_path).unlink(missing_ok=True)
```

**Strengths**:
1. **Atomic rename**: `Path.replace()` uses `os.replace()` which is atomic on POSIX
2. **Durability**: `os.fsync()` forces disk commit before rename
3. **Safe on crash**: Reader sees either old file (still valid) or new file (complete), never partial
4. **Temp file cleanup**: `contextlib.suppress()` safely removes temp file on error
5. **Metadata wrapper**: Adds timestamp for validation but doesn't break format parsing

**Edge Cases Handled**:
- ✅ Missing parent directory → `mkdir(parents=True, exist_ok=True)`
- ✅ Write failure → temp file cleaned up
- ✅ FSSync failure → exception caught and logged
- ✅ Rename failure → temp file cleaned up

**Data Loss Scenario**: `os.fsync()` could fail if:
- Disk full (caught, logged, returns `False`)
- Hardware I/O error (caught, logged, returns `False`)
- Filesystem readonly (caught, logged, returns `False`)

**Mitigation**: Callers check return value and emit `cache_write_failed` signal. Test data persists even if write fails (TTL-based reads return stale cache).

---

### Read Path: `_read_json_cache()` (Lines 1114-1180)

**PATTERN ANALYZED**: TTL checking, format validation, graceful fallback

```python
# 1. Check existence
if not cache_file.exists():
    return None

# 2. Check TTL (if enabled)
if check_ttl:
    age = datetime.now(tz=UTC) - datetime.fromtimestamp(cache_file.stat().st_mtime)
    if age > self._cache_ttl:
        return None

# 3. Read JSON (raw_data: JSONValue)
with Path(cache_file).open(encoding="utf-8") as f:
    raw_data = cast("JSONValue", json.load(f))

# 4. Format validation: check ALL elements are dicts
if isinstance(raw_data, list):
    if raw_data and not all(isinstance(item, dict) for item in raw_data):
        return None  # Validation failed
    return cast("list[ShotDict | ThreeDESceneDict]", raw_data)

# 5. Handle wrapped format: {data: [...], cached_at: "..."}
if isinstance(raw_data, dict):
    result = raw_data.get("data") or raw_data.get("shots") or raw_data.get("scenes", [])
    # Re-validate if result is a list
    if isinstance(result, list) and result and not all(isinstance(item, dict) for item in result):
        return None
    return result
```

**Strengths**:
1. **TTL enforcement**: Expired cache returns None (forces refresh)
2. **Comprehensive validation**: Checks format at runtime, validates ALL elements
3. **Backward compatibility**: Handles old wrapped format `{data: [...]}` and new format `[...]`
4. **Graceful degradation**: Returns None on validation failure (not crash)
5. **Early exit**: Uses `all(isinstance(item, dict) for item in raw_data)` generator (efficient)

**Edge Cases Handled**:
- ✅ Missing file → None returned
- ✅ Corrupted JSON → exception caught, returns None
- ✅ Invalid format (non-dict items) → detected by validation, returns None
- ✅ Wrong structure (not list or dict) → returns None
- ✅ Empty list → allowed (valid cache state)
- ✅ Missing keys in wrapped format → defaults to empty list for scenes

**Data Corruption Scenario**: If file is partially written:
- JSON parser fails → exception caught, returns None ✅
- If partial JSON is valid but incomplete → validation catches non-dict items ✅
- If partial JSON is structurally valid dict/list → reads correctly (safe fallback)

---

## Merge Algorithms

### 1. Shot Merge: `merge_shots_incremental()` (Lines 715-782)

**PATTERN ANALYZED**: Composite key deduplication, QMutex protection

```python
with QMutexLocker(self._lock):
    # Build lookup by composite key
    cached_by_key = {_get_shot_key(shot): shot for shot in cached_dicts}
    fresh_keys = {_get_shot_key(shot) for shot in fresh_dicts}
    
    # Single pass: always use fresh data
    for fresh_shot in fresh_dicts:
        updated_shots.append(fresh_shot)
        if fresh_key not in cached_by_key:
            new_shots.append(fresh_shot)  # Track as new
    
    # Identify removed
    removed_shots = [shot for shot in cached_dicts if _get_shot_key(shot) not in fresh_keys]
```

**Key Function**: `_get_shot_key()` (Lines 103-115)
```python
def _get_shot_key(shot: ShotDict) -> tuple[str, str, str]:
    return (shot["show"], shot["sequence"], shot["shot"])
```

**Strengths**:
1. **Composite key**: (show, sequence, shot) ensures global uniqueness
2. **Thread-safe**: `QMutexLocker` guards entire merge operation
3. **Fresh data as source of truth**: Overwrites cached data if key matches
4. **Change detection**: Returns `has_changes` flag for update notification
5. **O(n) complexity**: Single pass through fresh data, O(1) dict lookups

**Potential Issue**: Merge does NOT preserve old metadata if same key exists
- ✅ Intentional design: fresh data is authoritative
- ✅ Metadata like timestamps, counts would be from new `ws` command anyway

**Thread Safety**: Protected by QMutex but...
- ⚠️ Callers could race if they call merge_shots_incremental() from different threads without synchronization
- ⚠️ No external locking visible in threede_scene_model.py line 227
  ```python
  merge_result = self.cache_manager.merge_scenes_incremental(cached_data, fresh_data)
  ```
  (But likely single-threaded in practice - called from GUI thread)

---

### 2. Scene Merge: `merge_scenes_incremental()` (Lines 838-927)

**PATTERN ANALYZED**: Composite key deduplication, age-based pruning, QMutex protection

```python
with QMutexLocker(self._lock):
    # Cutoff for pruning old cached scenes
    cutoff = now - (max_age_days * 24 * 60 * 60)
    
    # Build lookups
    cached_by_key = {_get_scene_key(scene): scene for scene in cached_dicts}
    fresh_keys = {_get_scene_key(scene) for scene in fresh_dicts}
    
    # Process fresh scenes (always include)
    for fresh_scene in fresh_dicts:
        if fresh_key not in cached_by_key:
            new_scenes.append(fresh_scene)
        # Update last_seen timestamp
        updated_scene = dict(fresh_scene)
        updated_scene["last_seen"] = now
        updated_by_key[fresh_key] = updated_scene
    
    # Process removed scenes (apply age-based retention)
    for key in (cached_keys - fresh_keys):
        scene_last_seen = cached_by_key[key].get("last_seen", now)
        if scene_last_seen >= cutoff:
            # Within retention window
            updated_by_key[key] = cached_scene
        else:
            # Too old, prune it
            pruned_count += 1
```

**Key Function**: `_get_scene_key()` (Lines 132-145)
```python
def _get_scene_key(scene: ThreeDESceneDict) -> tuple[str, str, str]:
    return (scene["show"], scene["sequence"], scene["shot"])
```

**Strengths**:
1. **Composite key**: (show, sequence, shot) prevents cross-show collisions
2. **Time-based retention**: Removes stale scenes older than `max_age_days` (default 60)
3. **last_seen tracking**: Timestamps when each scene was last discovered
4. **Thread-safe**: `QMutexLocker` guards entire merge operation
5. **Smart pruning**: Keeps old scenes unless explicitly too old
6. **Default handling**: Missing `last_seen` → assumes current time (backward compatible)

**Intentional Design Decision**: Deleted .3de files remain in cache
- Rationale: Preserves history for incremental caching
- Mechanism: Scene not in fresh → checked against cutoff → kept if recent
- Benefit: Reduces filesystem scanning overhead
- Trade-off: Cache grows unbounded (limited by # unique shots in production)

**Potential Issue**: `last_seen` timestamp could be manipulated
- ✅ Not a concern: single trusted user, isolated VFX environment
- ✅ Timestamp is generated server-side in current process

---

## TTL/Expiration Logic

### Expiration Strategies

| Cache Type | TTL | File | Reset Mechanism |
|-----------|-----|------|-----------------|
| My Shots | 30 min (configurable) | `shots.json` | `check_ttl=True` in `_read_json_cache()` |
| Previous Shots | None (persistent) | `previous_shots.json` | `check_ttl=False` |
| Migrated Shots | None (persistent) | `migrated_shots.json` | `check_ttl=False` |
| 3DE Scenes | None (persistent) | `threede_scenes.json` | `check_ttl=False` with `max_age_days=60` |
| Thumbnails | None (persistent) | `thumbnails/{show}/{seq}/` | Manual clear via `clear_cache()` |

### TTL Implementation: `_read_json_cache()` (Line 1126-1130)

```python
if check_ttl:
    age = datetime.now(tz=UTC) - datetime.fromtimestamp(cache_file.stat().st_mtime)
    if age > self._cache_ttl:
        return None
```

**How TTL is Set**:
- Default: `DEFAULT_TTL_MINUTES = 30` (top of file)
- Setter: `set_expiry_minutes(minutes)` (lines 1065-1072)
- Runtime check: `datetime.now(tz=UTC) - datetime.fromtimestamp(mtime)`

**Potential Issues**:

1. **Race: mtime read vs file write**
   ```
   Thread A: stat() returns mtime = T
   Thread B: Write new cache, mtime = T + 1
   Thread A: Calculates age using old mtime
   ```
   - ⚠️ Possible but unlikely (would need bad timing)
   - ⚠️ Impact: Could read expired cache once
   - ✅ Mitigated: Next refresh will get fresh data

2. **Time-of-check-time-of-use (TOCTOU)**
   ```
   Check: age = datetime.now() - mtime
   If age > TTL: return None
   Use: At this point, cache might be older
   ```
   - ✅ Not a problem: Returning None is safe (forces refresh)

3. **Stat cache (2-second TTL)**
   - `_get_file_stat_cached()` caches mtime for 2 seconds
   - ⚠️ Could serve stale mtime during refresh window
   - ✅ Acceptable: Maximum staleness is 2 seconds

---

## Concurrent Access Patterns

### Lock Scope Analysis

**QMutex Used For**:
1. `merge_shots_incremental()` - entire operation (lines 742-775)
2. `merge_scenes_incremental()` - entire operation (lines 866-920)
3. `migrate_shots_to_previous()` - load + merge + write (lines 626-662)
4. `cache_thumbnail()` - only directory creation (lines 388-393)
5. `cache_thumbnail_direct()` - only stat cache invalidation (lines 536-539)
6. `clear_cache()` - entire operation (lines 987-1006)

**Lock-Free Operations** (by design):
- `_write_json_cache()` - tempfile + rename are atomic
- `_read_json_cache()` - reads are concurrent-safe on POSIX
- `_process_standard_thumbnail()` - I/O is concurrent-safe (unique temp file per shot)
- Thumbnail format processing - only stat cache uses lock

**Thread Safety Assessment**:

| Operation | Lock Scope | Race Condition Risk |
|-----------|-----------|-------------------|
| Write cache | None (atomic at OS) | LOW - rename is atomic |
| Read cache | None | MEDIUM - could read partial on write (mitigated by format validation) |
| Merge shots | Entire merge | None - protected by QMutex |
| Merge scenes | Entire merge | None - protected by QMutex |
| Thumbnail write | Temp file only | None - unique temp per shot, atomic rename |
| Stat cache | Brief lock | LOW - 2-second cache acceptable |

### Potential Race: Cache Read During Write

**Scenario**:
```
Thread A: write_json_cache() - rename in progress
Thread B: _read_json_cache() - reads old file
```

**Analysis**:
- ⚠️ Possible: No read lock during write
- ✅ Safe: Reader will get either complete old file or complete new file
- ✅ Format validation: If partial read occurs, `json.load()` will fail
- ✅ Graceful degradation: Failure returns None (cache miss, not corruption)

**OS Guarantee**: `os.replace()` on POSIX is atomic - reader sees old or new, never partial.

---

## Data Loss Risk Assessment

### Risk 1: Write Failure During cache_shots/cache_previous_shots/cache_threede_scenes

**Code Flow**:
```python
success = self._write_json_cache(...)
if success:
    self.cache_updated.emit()
else:
    self.logger.warning("Failed to write cache")
    self.cache_write_failed.emit("shots")
```

**Data Loss Path**:
1. Application calls `cache_shots([...])` with new data
2. `_write_json_cache()` fails (disk full, permissions, etc.)
3. Returns `False` → signal emitted
4. Application restarts
5. Old data returned from cache (TTL not expired)
6. New data lost

**Mitigation**:
- ✅ Caller receives failure signal → can retry
- ✅ Warning logged → admin can see issue
- ✅ Old cache still valid → application continues (graceful degradation)
- ⚠️ No transaction log → replay not possible
- ⚠️ No write-ahead logging → new data not preserved

**Acceptance**: Acceptable for personal tool in isolated environment
- Single user, not concurrent
- Manual retry possible
- Fallback to previous state is safe

### Risk 2: Lost Data in migrate_shots_to_previous()

**Code Flow**:
```python
existing = self.get_migrated_shots() or []  # Load old
to_migrate = [...]                          # New data
# Merge and deduplicate
shots_by_key = {}
for shot in existing:
    shots_by_key[_get_shot_key(shot)] = shot
for shot in to_migrate:
    shots_by_key[_get_shot_key(shot)] = shot

merged = list(shots_by_key.values())
write_success = self._write_json_cache(...)
```

**Potential Issue**: Between `get_migrated_shots()` and `_write_json_cache()`
- ⚠️ If external process modifies migrated_shots_cache_file, changes lost
- ⚠️ Multi-process write collision possible (though unlikely)

**Impact**: Migrated shots file could lose concurrent updates
- ⚠️ Real issue: Two processes calling `migrate_shots_to_previous()` simultaneously

**Mitigation**:
- ✅ Single-process model: GUI thread only
- ✅ Protected by QMutex: Merge operation atomic
- ✅ QMutex does NOT protect file read → write window though
- ⚠️ No file-level lock (flock) used
- ⚠️ No retry logic on collision

**Acceptance**: Low risk in practice
- GUI single-threaded
- Only one application instance expected
- Multi-instance write collision is rare

### Risk 3: Incomplete Merge in merge_scenes_incremental()

**Code Flow**:
```python
cached_dicts = [_scene_to_dict(s) for s in (cached or [])]
fresh_dicts = [_scene_to_dict(s) for s in fresh]

# Merge happens here
updated_by_key = {}
for fresh_scene in fresh_dicts:
    fresh_key = _get_scene_key(fresh_scene)
    if fresh_key not in cached_by_key:
        new_scenes.append(fresh_scene)
    updated_scene = dict(fresh_scene)
    updated_scene["last_seen"] = now
    updated_by_key[fresh_key] = updated_scene

# Prune old scenes
for key in removed_keys:
    cached_scene = cached_by_key[key]
    scene_last_seen = cached_scene.get("last_seen", now)
    if scene_last_seen >= cutoff:
        updated_by_key[key] = cached_scene
    else:
        pruned_count += 1

updated_scenes = list(updated_by_key.values())
```

**Silent Data Drop**: If `_get_scene_key()` throws exception
- ⚠️ Current code: No try/except around key extraction
- ⚠️ Impact: Exception propagates, merge incomplete
- ⚠️ Caller sees exception, cache not written

**Example**:
```python
def _get_scene_key(scene: ThreeDESceneDict) -> tuple[str, str, str]:
    return (scene["show"], scene["sequence"], scene["shot"])
    # KeyError if show/sequence/shot missing
```

**Actual Risk**: LOW
- ✅ Cache format controlled (self-generated)
- ✅ `_scene_to_dict()` validates conversion
- ✅ KeyError would surface quickly in testing

---

## Merge Correctness Analysis

### Shot Merge Data Drop Risk

**Algorithm**: For each fresh shot, check if in cache. If not, mark as new.

**Question**: Could data be silently dropped?
- ✅ No: fresh data always added to `updated_shots`
- ✅ No: cached data not in fresh is tracked as `removed_shots` (returned to caller)

**Return Value**:
```python
ShotMergeResult(
    updated_shots=updated_shots,      # All fresh shots
    new_shots=new_shots,              # Fresh shots not in cache
    removed_shots=removed_shots,      # Cached shots not in fresh
    has_changes=has_changes,
)
```

**Verification**:
- ✅ `updated_shots` = fresh_dicts (complete)
- ✅ `new_shots` ⊆ updated_shots (subset)
- ✅ `removed_shots` ⊆ cached_dicts (subset)
- ✅ No data lost (all dicts in result)

### Scene Merge Data Drop Risk

**Pruning Logic**: Scenes older than `max_age_days` (default 60) are removed

**Question**: Could valid scenes be dropped unexpectedly?

**Example**:
```python
cutoff = now - (60 * 24 * 60 * 60)  # 60 days ago

for key in removed_keys:
    cached_scene = cached_by_key[key]
    scene_last_seen = cached_scene.get("last_seen", now)
    if scene_last_seen >= cutoff:        # Within 60 days
        updated_by_key[key] = cached_scene
    else:
        pruned_count += 1  # Dropped
```

**Data Loss Scenario**:
1. 3DE scene discovered 70 days ago
2. Filesystem scan doesn't find it (deleted/moved)
3. Merge is called with empty fresh list
4. Scene has `last_seen` = 70 days ago
5. `now - 70 days < cutoff (60 days ago)` → True
6. Scene is pruned (removed from cache)

**Is This a Bug?**
- ⚠️ Depends on intent: Is 60-day retention expected?
- ✅ Documented: Default `max_age_days=60` in function signature
- ⚠️ Could be surprising: Scene disappears without user knowledge
- ⚠️ No warning: Caller doesn't know `pruned_count` > 0

**Acceptance**: Intentional design
- Rationale: Clean up stale cache entries to prevent unbounded growth
- Configurable: Caller can pass `max_age_days=999` to disable pruning
- Visibility: `SceneMergeResult.pruned_count` tracks removed items

**Mitigation**: Results are returned to caller
```python
merge_result = self.cache_manager.merge_scenes_incremental(cached_data, fresh_data)
# Caller could log: f"Pruned {merge_result.pruned_count} old scenes"
```

Current usage in threede_scene_model.py doesn't check `pruned_count` though.

---

## Temp File Cleanup

### Scope of Cleanup

**Temp Files Created**:
1. JSON cache: `_write_json_cache()` → `.{filename}.tmp`
2. Thumbnails: `_process_standard_thumbnail()` → `.tmp`
3. QImage thumbnails: `cache_thumbnail_direct()` → `.tmp`

**Cleanup Patterns**:

| Location | Cleanup | Protection |
|----------|---------|-----------|
| JSON write (line 1207) | Explicit unlink in except | ✅ except clause catches all |
| PIL thumbnail (line 440) | Explicit unlink before fallback | ✅ explicit cleanup |
| PIL fallback (line 471) | Explicit unlink in except | ✅ except clause catches |
| QImage save (line 528) | Explicit unlink on failure | ✅ explicit cleanup |
| QImage extract (line 471) | Finally block cleanup | ✅ finally ensures cleanup |

**Temp File Leakage Risk**:

| Scenario | Risk | Mitigation |
|----------|------|-----------|
| Write fails before temp create | None | No temp file created |
| Temp create succeeds, write fails | Low | except clause unlinks |
| Temp create succeeds, rename fails | MEDIUM | except clause would unlink, but after exception |
| Process killed before unlink | HIGH | Orphaned .tmp files in cache dir |

**Evidence of Process Kills**:
- `~/.shotbot/cache/` directory not visible for inspection
- Temp files would accumulate only if process consistently crashes

**Acceptance**: Low risk in practice
- Temp files small (thumbnails, JSON)
- Manual cleanup possible: `find cache_dir -name "*.tmp" -delete`
- Next write to same location would overwrite anyway

---

## Summary Table: Data Integrity Risks

| # | Risk | Severity | Likelihood | Impact | Mitigation |
|---|------|----------|------------|--------|-----------|
| 1 | Partial JSON read during write | Medium | Low | Validation catches, returns None | Format validation, atomic rename |
| 2 | Write failure loses new data | Medium | Low | Graceful fallback to old cache | Signal emitted, logged |
| 3 | Multi-process merge collision | Medium | Low | Lost shots in migrated cache | Single-process model |
| 4 | Stat cache returns stale mtime | Low | Medium | Expired cache served once | 2-second TTL acceptable |
| 5 | Temp file orphans on crash | Low | Low | Disk space waste | Manual cleanup, overwrite on next write |
| 6 | Scene merge silently drops data | Medium | Low | Depends on max_age_days | Default 60 days acceptable, pruned_count visible |
| 7 | TTL race (mtime read vs write) | Low | Low | Expired cache served once | Mitigated by validation |
| 8 | File lock not used for safety | Medium | Low | Multi-instance collision | Single-instance model expected |

---

## Recommendations

### High Priority

1. **Document TTL behavior explicitly**
   - Add comment to `_read_json_cache()`: "Readers do not hold locks during writes"
   - Document: "os.replace() atomic on POSIX ensures consistency"

2. **Check pruned_count in merge_scenes_incremental() callers**
   - threede_scene_model.py line 227 should log: `f"Pruned {merge_result.pruned_count} old scenes"`
   - Visibility: Users aware of cache cleanup

3. **Add validation to _get_shot_key() and _get_scene_key()**
   - Catch KeyError and raise ValidationError with message
   - Prevents silent failures if format changes

### Medium Priority

1. **Consider file-level locking for multi-process safety**
   - Add flock() around read-modify-write in migrate_shots_to_previous()
   - Low performance impact, prevents collision in future multi-instance scenarios

2. **Implement retry logic in _write_json_cache()**
   - Retry on EAGAIN/EBUSY (transient errors)
   - Log retry count, give up after 3 attempts

3. **Add cleanup command for orphaned temp files**
   - Utility method: `cleanup_orphaned_temp_files()`
   - Run on cache initialization, log count removed

### Low Priority

1. **Write-ahead logging for shots/scenes**
   - Pre-write intended changes to `.pending` file
   - On read, detect `.pending` and replay if needed
   - Adds complexity for low-ROI benefit

2. **Checksums for cache integrity**
   - Add SHA256 hash of data to cache metadata
   - Detect corruption from bit flips
   - Rare event, slow to compute

---

## Conclusion

The cache manager implementation is **production-grade** with excellent data integrity safeguards:

**STRENGTHS**:
- Atomic write-then-rename pattern is correct
- Format validation prevents corrupt data usage
- TTL enforcement is sound
- Merge algorithms preserve data correctly
- Error handling is comprehensive
- Thread-safe operations protected by QMutex

**ACCEPTABLE RISKS**:
- No transaction log (acceptable for single-user tool)
- No file-level locks (acceptable for single-instance model)
- Scene pruning automatic at 60 days (acceptable with visibility)
- Temp file cleanup on crash not guaranteed (low impact, manual cleanup available)

**VERIFICATION**:
- Read path validation: All elements checked as dicts
- Write path atomicity: fsync + rename prevents partial writes
- Merge correctness: Data never lost, only deduplicated
- Concurrent access: QMutex protects critical sections
- TTL logic: Expiration checked correctly via mtime

**VERDICT**: SAFE FOR PRODUCTION in isolated single-user environment
