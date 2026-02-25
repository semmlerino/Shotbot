# Caching Architecture

Shotbot uses persistent caching for performance optimization, with different strategies for different data types.

## My Shots Cache

- **File**: `~/.shotbot/cache/production/shots.json`
- **TTL**: 30 minutes (configurable)
- **Behavior**: Time-based expiration with manual refresh
- **Strategy**: Complete replacement on refresh

## Previous Shots Cache

- **File**: `~/.shotbot/cache/production/previous_shots.json`
- **TTL**: None (persistent)
- **Behavior**: Incremental accumulation
- **Strategy**: New shots added, old shots preserved indefinitely

## Other 3DE Scenes Cache

- **File**: `~/.shotbot/cache/production/threede_scenes.json`
- **TTL**: None (persistent) - Changed from 30 minutes
- **Behavior**: Persistent incremental caching
- **Strategy**:
  - Discovers all .3de files from all users across all shows
  - New scenes are added to cache
  - Previously cached scenes are preserved (even if not found in current scan)
  - Deduplication keeps one scene per shot (best by mtime + plate priority)
  - Deleted .3de files remain in cache (preserves history)

### Implementation Details

- Uses `CacheManager.get_persistent_threede_scenes()` - no TTL check
- Uses `CacheManager.merge_scenes_incremental()` - merges cached + fresh data
- Deduplication applied AFTER merge (ensures latest/best scene wins)
- Shot-level key `(show, sequence, shot)` for uniqueness
- Age-based pruning: scenes not seen in 60 days are removed (`max_age_days=60` in `merge_scenes_incremental()`). `SceneMergeResult.pruned_count` reports how many were pruned each merge.

### Cache Workflow

1. Load persistent cache (no expiration)
2. Discover fresh scenes from filesystem
3. Merge: cached scenes + fresh scenes
4. Deduplicate: keep best scene per shot
5. Cache merged result (refreshes file timestamp)

### Benefits

- Faster startup (scenes load from cache immediately)
- Preserves scene history (deleted files remain visible)
- Incremental updates (only new discoveries processed)
- No cache expiration (persistent across restarts)

## Latest Files Cache

- **File**: `~/.shotbot/cache/production/latest_files.json`
- **TTL**: 5 minutes (`LATEST_FILES_TTL_MINUTES = 5`)
- **Behavior**: Time-based expiration; expired entries return `None` without removing from disk
- **Strategy**: Stores most-recently-used Maya/3DE file paths per workspace, keyed by `workspace_path:file_type`

### API

- `get_cached_latest_file(workspace_path, file_type)` → `Path | None` — returns cached path or `None` if missing/expired
- `cache_latest_file(workspace_path, file_type, file_path)` — writes entry with current timestamp
- `clear_latest_files_cache(workspace_path=None)` — clears one workspace entry or entire file

The composite key is `"{workspace_path}:{file_type}"` where `file_type` is `"maya"` or `"threede"`.

## Thumbnail Cache

- **Directory**: `~/.shotbot/cache/production/thumbnails/<show>/<sequence>/<shot>_thumb.jpg`
- **TTL**: None (persistent, manual clear only)
- **Format**: JPEG, resized to fit within a fixed square (PIL `LANCZOS` resampling)
- **Strategy**: Write-once; existing files are reused without reprocessing

### API

- `get_cached_thumbnail(show, sequence, shot)` → `Path | None` — returns path if cached file exists on disk
- `cache_thumbnail(source_path, show, sequence, shot)` → `Path | None` — resizes source image and writes to cache
- `cache_thumbnail_direct(qimage, show, sequence, shot)` → `Path | None` — caches a `QImage` directly

### Background Loading

`ThumbnailCacheLoader` (a `QRunnable`) wraps `cache_thumbnail()` for non-blocking use. It emits:
- `signals.loaded(show, sequence, shot, cache_path)` on success
- `signals.failed(show, sequence, shot, error_message)` on failure

## Runtime / In-Memory Caches

These caches exist only in process memory and are not persisted to disk.

### SceneCache (`scene_cache.py`)

In-memory store for 3DE scene discovery results at the shot/show level.

- **TTL**: 30 minutes per entry (configurable per-entry)
- **Capacity**: Up to 1000 entries; LRU eviction when full
- **Keyed by**: `show`, `show/sequence`, or `show/sequence/shot`
- **API**: `get_scenes_for_shot()`, `cache_scenes_for_shot()`, `invalidate_shot()`, `invalidate_show()`, `cleanup_expired()`
- **Statistics**: tracks hits, misses, evictions, invalidations, cache warmings via `get_cache_stats()`

### DirectoryCache (`filesystem_scanner.py`)

Thread-safe cache of directory listings to reduce repeated `os.listdir()` calls during scene discovery.

- **TTL**: 300 seconds when `enable_auto_expiry=True`; manual-refresh-only when `False` (default for the module-level instance)
- **Capacity**: Unbounded by default; expired entries pruned if count exceeds 1000 (auto-expiry mode only)
- **Entry format**: `list[tuple[name, is_dir, is_file]]`
- **API**: `get_listing(path)`, `set_listing(path, listing)`, `clear_cache()`

## Signals

`CacheManager` emits the following Qt signals:

- `cache_updated` — emitted after any successful cache write
- `shots_migrated(list)` — emitted when shots are moved to the Previous Shots cache
- `cache_write_failed(str)` — emitted with the cache name (e.g. `"threede_scenes"`) when a write fails; callers can surface an error to the user without crashing

## Clearing Cache

```python
cache_manager.clear_cache()  # Clears all caches including 3DE scenes
```
