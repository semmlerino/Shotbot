# Caching Architecture

Shotbot uses layered caches (disk + memory) with different lifecycles by data type.
This document captures behavior and invariants, not full API listings.

## Persistent Caches (Disk)

| Cache | Location | Lifecycle | Strategy |
|------|----------|-----------|----------|
| My Shots | `~/.shotbot/cache/production/shots.json` | TTL-based (30 min) | Replaced on refresh |
| Previous Shots | `~/.shotbot/cache/production/previous_shots.json` | Persistent | Incremental accumulation |
| Other 3DE Scenes | `~/.shotbot/cache/production/threede_scenes.json` | Persistent | Replaced on refresh; dedupe best scene per shot |
| Latest Files | `~/.shotbot/cache/production/latest_files.json` | TTL-based (5 min) | Workspace/file-type lookup for latest Maya/3DE path |
| Migrated Shots | `~/.shotbot/cache/production/migrated_shots.json` | Persistent | Tracks shot migration history for Previous Shots sync |
| Thumbnails | `~/.shotbot/cache/production/thumbnails/...` | Persistent | Reuse cached JPEG thumbnails |

## In-Memory Caches

- `FilesystemCoordinator._directory_cache`: in-memory directory-listing cache used to reduce repeated filesystem metadata reads.

## Key Invariants

1. 3DE scene cache write is orchestrated by `ThreeDEController`, which deduplicates scenes and passes them to `SceneDiskCache.cache_threede_scenes()` for a replace write.
2. Deduplication occurs after merge so best available scene survives.
3. Thumbnail cache writes are non-blocking in UI paths.
4. TTL caches may return stale/empty results by design; callers must handle cache miss paths.

## Signals

`ShotDataCache` and `SceneDiskCache` notify UI flows through signals including:

- cache update events (`cache_updated`)
- shot migration events (`shots_migrated` on `ShotDataCache`)

Changes to cache write paths should preserve these signals.

## Clearing Cache

Use `CacheCoordinator.clear_cache()` to clear managed caches.

## Configuration

- `SHOTBOT_FILE_LOCKING=disabled` — Opt out of file locking for cache writes. Enabled by default. Defined in `cache/_json_store.py`.
