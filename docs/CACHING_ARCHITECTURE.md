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
- Cache grows unbounded (limited by # of unique shots in production)

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

## Clearing Cache

```python
cache_manager.clear_cache()  # Clears all caches including 3DE scenes
```
