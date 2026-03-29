# Caching Architecture

Shotbot uses layered caches (disk + memory) with different lifecycles by data type.
This document captures behavior and invariants, not full API listings.

## Default Cache Roots

The paths below use the production cache root as the concrete example.
The default resolver also supports mode-specific roots:

- Production: `~/.shotbot/cache/production`
- Test: `~/.shotbot/cache_test` when running under `pytest` or `SHOTBOT_MODE=test`
- Mock: `~/.shotbot/cache/mock` when mock mode is active
- Explicit test override: `SHOTBOT_TEST_CACHE_DIR`

## Persistent Caches (Disk)

| Cache | Location | Lifecycle | Strategy |
|------|----------|-----------|----------|
| My Shots | `~/.shotbot/cache/production/shots.json` | TTL-based (30 min) | Replaced on refresh |
| Previous Shots | `~/.shotbot/cache/production/previous_shots.json` | Persistent | Incremental accumulation |
| Other 3DE Scenes | `~/.shotbot/cache/production/threede_scenes.json` | Persistent | Replaced on refresh; dedupe best scene per shot |
| Latest Files | `~/.shotbot/cache/production/latest_files.json` | TTL-based (5 min) | Tri-state lookup (hit/miss/not_found); "not_found" = cached negative confirming no file exists |
| Migrated Shots | `~/.shotbot/cache/production/migrated_shots.json` | Persistent | Tracks shot migration history for Previous Shots sync |
| Thumbnails | `~/.shotbot/cache/production/thumbnails/...` | Persistent | Reuse cached JPEG thumbnails |

## In-Memory Caches

- `FilesystemCoordinator._directory_cache`: in-memory directory-listing cache used to reduce repeated filesystem metadata reads.

## Key Invariants

1. 3DE scene cache write is orchestrated by `ThreeDEController`, which deduplicates scenes and passes them to `SceneDiskCache.cache_threede_scenes()` for a replace write.
2. Deduplication occurs after merge so best available scene survives.
3. Thumbnail cache writes are non-blocking in UI paths.
4. TTL caches may return stale/empty results by design; callers must handle cache miss paths.
5. Incremental scene merge (`SceneDiskCache.merge_scenes_incremental()`) prunes entries older than 60 days by default. Missing scenes may be an age-based prune, not a bug.

## Signals

`ShotDataCache` and `SceneDiskCache` notify UI flows through signals including:

- cache update events (`cache_updated`)
- shot migration events (`shots_migrated` on `ShotDataCache`)

Changes to cache write paths should preserve these signals.
LatestFileCache and ThumbnailCache do not emit signals; they are consumed directly by callers.

## Clearing Cache

Use `ShotDataCache.clear_cache()` and `SceneDiskCache.clear_cache()` individually to clear managed caches. Note: `migrated_shots.json` is explicitly preserved across cache clears to maintain Previous Shots migration history.

## Configuration

- `SHOTBOT_FILE_LOCKING=disabled` — Opt out of file locking for cache writes. Enabled by default. Defined in `cache/_json_store.py`.
