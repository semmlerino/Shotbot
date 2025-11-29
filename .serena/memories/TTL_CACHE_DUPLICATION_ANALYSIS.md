# TTL Cache Implementations Analysis

## Overview

Found **5 independent TTL-based cache implementations** across the codebase with significant duplication in core functionality. This analysis documents each cache and consolidation opportunities.

---

## Cache 1: CommandCache (process_pool_manager.py: lines 81-220)

### Purpose
TTL-based cache for command execution results with LRU eviction.

### Key Methods
- **`__init__(default_ttl: int = 30)`** (lines 87-101)
  - Stores: `dict[str, tuple[str, float, int, str]]` → (result, timestamp, ttl, original_command)
  - Uses QMutex for thread safety
  - Default TTL: 30 seconds
  
- **`get(command: str) -> str | None`** (lines 103-124)
  - Returns cached result if not expired
  - Checks expiration: `time.time() - timestamp < ttl`
  - Updates `_hits` and `_misses` stats
  - Removes expired entries on read

- **`set(command: str, result: str, ttl: int | None = None)`** (lines 126-141)
  - Caches result with timestamp
  - Calls `_cleanup_expired()` after each set
  - Stores original command for pattern matching

- **`invalidate(pattern: str | None = None)`** (lines 143-163)
  - Pattern-based invalidation (matches against 4th tuple element)
  - Full cache clear if pattern=None

- **`_cleanup_expired()`** (lines 194-220)
  - Two-phase cleanup:
    1. Removes expired entries (TTL check)
    2. LRU eviction if size > 500 (sorts by timestamp, removes oldest)
  - Logs eviction metrics

- **`get_stats()`** (lines 165-181)
  - Returns: `{hits, misses, hit_rate%, size, total_requests}`

### Thread Safety
- **QMutex** with `QMutexLocker` context manager
- Consistent locking for all operations

### Stats Tracking
- `_hits`: Cache hits
- `_misses`: Cache misses
- Computed: hit_rate = hits / (hits + misses)
- Size tracking

### Unique Features
- **Hash-based keys** (SHA256 of command)
- **LRU eviction** with configurable max size (500)
- **Pattern matching** invalidation for command substrings
- **Tuple storage** with command preservation for pattern matching

---

## Cache 2: DirectoryCache (filesystem_scanner.py: lines 37-141)

### Purpose
Thread-safe directory listing cache with optional TTL and auto-expiry flag.

### Key Methods
- **`__init__(ttl_seconds: int = 300, enable_auto_expiry: bool = False)`** (lines 44-59)
  - Stores: `dict[str, list[tuple[str, bool, bool]]]`
  - Timestamps: `dict[str, float]`
  - Uses `threading.RLock()` for thread safety
  - TTL: 300 seconds (5 minutes)
  - Enable_auto_expiry flag: Controls whether TTL is checked

- **`get_listing(path: Path) -> list[tuple[str, bool, bool]] | None`** (lines 61-82)
  - Returns cached listing or None
  - TTL check only if `enable_auto_expiry=True`
  - Removes entry if expired
  - Updates hits/misses/evictions stats

- **`set_listing(path: Path, listing: list[tuple[str, bool, bool]])`** (lines 84-103)
  - Caches directory listing with timestamp
  - Lazy cleanup: Removes expired entries if cache > 1000 items (only if auto_expiry enabled)

- **`get_stats()`** (lines 105-118)
  - Returns: `{hit_rate_percent, total_entries, hits, misses, evictions}`

- **`clear_cache()` / `refresh_cache()`** (lines 120-141)
  - Both clear all entries
  - Returns number of entries cleared

### Thread Safety
- **threading.RLock()** (reentrant lock)
- Consistent locking for all operations

### Stats Tracking
- `stats`: `{hits, misses, evictions}`
- Computed: hit_rate_percent (as integer)
- Size tracking

### Unique Features
- **Optional auto-expiry** (controlled by flag)
- **Lazy cleanup** (only on set, not on get)
- **Manual refresh** via `refresh_cache()`
- **Directory listing format**: List of tuples (name, is_file, is_dir)
- **Reentrant locking** (allows nested acquisition)

---

## Cache 3: FilesystemCoordinator (filesystem_coordinator.py: lines 11-245)

### Purpose
Singleton cache for filesystem operations with TTL-based directory listing cache.

### Key Methods
- **`__init__()`** (lines 30-50)
  - Stores: `dict[Path, tuple[list[Path], float]]` → (listing, timestamp)
  - Uses QMutex for thread safety
  - TTL: 300 seconds (5 minutes, hardcoded)
  - Singleton pattern with `__new__` override

- **`get_directory_listing(path: Path) -> list[Path]`** (lines 52-97)
  - Returns cached listing or scans directory
  - TTL check: `now - timestamp < self._ttl_seconds`
  - Updates `_cache_hits` and `_cache_misses`
  - Returns copy to prevent mutation
  - Removes expired on read

- **`set_ttl(seconds: int)`** (lines 199-206)
  - Allows runtime TTL modification
  - Logs change

- **`cleanup_expired()`** (lines 208-231)
  - Single-phase cleanup: Removes expired entries only
  - Returns count removed
  - Logs removal count

- **`get_cache_stats()`** (lines 175-192)
  - Returns: `{ttl_seconds, total_requests, hit_rate, remaining_requests}`

- **`invalidate_path(path)` / `invalidate_all()`** (lines 131-151)
  - Path-specific or full cache invalidation

### Thread Safety
- **QMutex** with context manager
- Singleton pattern ensures single instance

### Stats Tracking
- `_cache_hits` and `_cache_misses` (integers)
- Computed: hit_rate percentage
- TTL reporting

### Unique Features
- **Singleton pattern** (single shared instance)
- **QMutex usage** (Qt framework consistency)
- **Configurable TTL** via `set_ttl()`
- **Listing format**: List of Path objects
- **Copy-on-read** (returns copy to prevent mutation)
- **Hardcoded TTL default** (300s, only changeable via method)

---

## Cache 4: SceneCache (scene_cache.py: lines 74-426)

### Purpose
High-level cache for ThreeDEScene discovery results with TTL, LRU eviction, and shot/show-level keys.

### Key Methods
- **`__init__(default_ttl: int = 1800, max_entries: int = 1000)`** (lines 82-102)
  - Stores: `dict[str, SceneCacheEntry]` (uses SceneCacheEntry objects)
  - Uses `threading.Lock()` for thread safety
  - TTL: 1800 seconds (30 minutes)
  - Max entries: 1000

- **`get_scenes_for_shot(show, sequence, shot) -> list[ThreeDEScene] | None`** (lines 123-153)
  - Checks entry expiration via `entry.is_expired()`
  - Tracks access statistics (access_count, last_access)
  - Returns scenes list or None
  - Calls `entry.touch()` on access

- **`cache_scenes_for_shot(show, sequence, shot, scenes, ttl=None)`** (lines 184-212)
  - Creates SceneCacheEntry with custom or default TTL
  - Calls `_evict_lru()` if at max capacity
  - Logs with TTL value

- **`cleanup_expired()`** (lines 329-351)
  - Single-phase cleanup: Removes expired entries
  - Returns count removed
  - Calls `entry.is_expired()`

- **`_evict_lru()`** (lines 318-327)
  - Removes oldest entry by timestamp when at max
  - Updates evictions stat

- **`get_cache_stats()`** (lines 353-381)
  - Returns comprehensive stats including entry details

- **`invalidate_shot()` / `invalidate_show()`** (lines 239-286)
  - Pattern-based invalidation using key prefixes

### Thread Safety
- **threading.Lock()** (non-reentrant)
- Consistent locking for all operations

### Stats Tracking
- Per-entry: access_count, last_access, is_expired, ttl_seconds, age_seconds
- Global: hits, misses, evictions
- Computed: hit_rate_percent

### Unique Features
- **SceneCacheEntry objects** (wrapper class with metadata)
- **Custom entry TTL** (can set per-entry)
- **Access tracking** (access_count, last_access per entry)
- **Entry metadata** (age_seconds, is_valid, touch() method)
- **Hierarchical keys** (show/sequence/shot composition)
- **LRU eviction** at max capacity (1000 entries)
- **Pattern-based invalidation** by show/sequence/shot prefix

---

## Cache 5: Path Validation Cache (path_validators.py: lines 20-120)

### Purpose
Module-level cache for path existence checks with optional TTL.

### Key Methods
- **Module globals** (lines 20-24)
  - `_path_cache: dict[str, tuple[bool, float]]` → (exists, timestamp)
  - `_PATH_CACHE_TTL = 0.0` (0 = manual refresh only, no auto-expiry)
  - Uses `threading.Lock()` for thread safety

- **`clear_path_cache()`** (lines 27-31)
  - Manual cache clearing

- **`get_cache_stats()`** (lines 49-56)
  - Returns: `{path_cache_size}`

- **`PathValidators.validate_path_exists(path, description)`** (lines 62-120)
  - Checks cache with lock
  - TTL check: `_PATH_CACHE_TTL == 0 or current_time - timestamp < _PATH_CACHE_TTL`
  - Lazy cleanup: Removes old entries if cache > 5000 items
  - Returns cached result if valid

### Thread Safety
- **threading.Lock()** (non-reentrant)
- Two-phase locking (check with lock, verify outside lock)

### Stats Tracking
- Size only: `{path_cache_size}`

### Unique Features
- **Module-level cache** (not class-based)
- **TTL = 0 default** (no automatic expiry, manual refresh only)
- **Lazy cleanup** (>5000 items threshold)
- **Static method interface** (PathValidators.validate_path_exists)
- **Test isolation** (`_cache_disabled` flag)
- **Two-phase locking** (read outside lock for performance)

---

## Consolidation Analysis

### Common Patterns Identified

| Aspect | CommandCache | DirectoryCache | FilesystemCoordinator | SceneCache | PathCache |
|--------|--------------|-----------------|----------------------|------------|-----------|
| **Expiration Check** | `time.time() - timestamp < ttl` | Same | Same | `entry.is_expired()` (wrapper) | Same |
| **Cleanup Strategy** | On every set + LRU | Lazy (>1000 items) | On cleanup_expired() | On cleanup_expired() + LRU | Lazy (>5000 items) |
| **Key Type** | String (sha256) | Path | Path | String (composite) | String |
| **Value Type** | Tuple (result, ts, ttl, cmd) | List of tuples | List of Path | SceneCacheEntry object | Tuple (bool, timestamp) |
| **Thread Safety** | QMutex | RLock | QMutex | Lock | Lock |
| **Stats Tracking** | hits, misses, size | hits, misses, evictions | hits, misses | hits, misses, evictions | size only |
| **TTL Configuration** | Constructor arg | Constructor arg | `set_ttl()` method | Constructor arg | Module global |
| **LRU Eviction** | Yes (500 max) | No | No | Yes (1000 max) | No (lazy cleanup) |
| **Pattern Invalidation** | Yes | No | Yes | Yes (hierarchical) | No |

### Base Class Candidates

A unified `TTLCache[K, V]` base class would need:

```python
class TTLCacheBase(Generic[K, V], LoggingMixin):
    """Abstract base for TTL-based caches."""
    
    def __init__(
        self,
        default_ttl: int,
        max_entries: int | None = None,
        enable_auto_expiry: bool = True,
    ) -> None:
        """Initialize cache with common parameters."""
        self._cache: dict[K, tuple[V, float]] = {}  # value, timestamp
        self._lock: threading.Lock | QMutex = ...  # Subclass chooses
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._enable_auto_expiry = enable_auto_expiry
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}
    
    def get(self, key: K) -> V | None:
        """Get cached value if not expired."""
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if not self._is_expired(timestamp):
                    self._stats["hits"] += 1
                    return value
                del self._cache[key]
        
        self._stats["misses"] += 1
        return None
    
    def set(self, key: K, value: V, ttl: int | None = None) -> None:
        """Cache value with TTL."""
        with self._lock:
            self._cache[key] = (value, time.time())
            self._cleanup_expired()
            self._enforce_max_size()
    
    def _is_expired(self, timestamp: float) -> bool:
        """Check if timestamp has exceeded TTL."""
        if not self._enable_auto_expiry:
            return False
        return time.time() - timestamp >= self._default_ttl
    
    def cleanup_expired(self) -> int:
        """Remove expired entries. Return count."""
        with self._lock:
            expired_keys = [
                k for k, (_, ts) in self._cache.items()
                if self._is_expired(ts)
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)
    
    def get_stats(self) -> dict[str, int | float]:
        """Get cache statistics."""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
            return {
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "evictions": self._stats["evictions"],
                "size": len(self._cache),
                "hit_rate_percent": hit_rate,
            }
```

### Cache-Specific Behaviors (Must Remain Separate)

1. **CommandCache specific**:
   - SHA256 key hashing
   - LRU eviction with 500 max
   - Pattern matching on original command (4th tuple element)
   - Tuple-based storage with command preservation

2. **DirectoryCache specific**:
   - Optional auto-expiry flag
   - Lazy cleanup threshold (1000 items)
   - Directory listing format (tuples with is_file/is_dir flags)
   - RLock usage (reentrant)

3. **FilesystemCoordinator specific**:
   - Singleton pattern
   - QMutex usage
   - Path type (Path objects)
   - Configurable TTL via method
   - Copy-on-read semantics
   - Hierarchical invalidation (parent/child paths)

4. **SceneCache specific**:
   - SceneCacheEntry wrapper objects
   - Per-entry TTL customization
   - Access tracking (access_count, last_access)
   - LRU eviction (1000 max)
   - Hierarchical keys (show/sequence/shot)
   - Pattern-based show/sequence invalidation

5. **PathValidators specific**:
   - Module-level cache (not class-based)
   - Test isolation via _cache_disabled flag
   - Lazy cleanup (5000 items)
   - Boolean cached value (exists: bool)

### Code Savings Estimate

**Duplicated code reduction if base class extracted:**
- Expiration check logic: ~5 lines × 5 = 25 lines
- TTL validation pattern: ~10 lines × 5 = 50 lines
- Stats tracking: ~15 lines × 5 = 75 lines
- Lock management: ~5 lines × 5 = 25 lines
- Cleanup loops: ~8 lines × 5 = 40 lines

**Total duplicated: ~215 lines**

**Potential savings: ~40-50%** of cache implementation code (base class adds ~100 lines, subclasses reduce by ~50-80 lines each).

**Not recommended to consolidate because:**
1. Each cache has fundamentally different storage strategies (tuples vs objects vs Path)
2. Different lock types (QMutex vs threading.Lock vs RLock)
3. Different eviction policies (LRU, lazy cleanup, no cleanup)
4. Different invalidation strategies (pattern matching, hierarchical, none)
5. Different TTL configurations (constructor, method, module-level)
6. DirectoryCache has optional auto-expiry flag (conditional TTL checks)
7. SceneCache uses wrapper objects vs raw tuples
8. Path cache is module-level, others are class-based

**Better approach:**
- Extract **common utility functions** for TTL checking and stats calculation
- Create a **mixin class** for stats tracking
- Create an **abstract base** for reference, but allow subclasses full flexibility
- Consolidate **only** identical loop patterns (e.g., `cleanup_expired()`)

---

## Recommendations

### 1. Create TTLExpiration Utility
Extract time-based expiration logic into a reusable function.

**File location**: `cache_utils.py` (new)

```python
def is_expired(timestamp: float, ttl_seconds: int) -> bool:
    """Check if timestamp has exceeded TTL."""
    return time.time() - timestamp >= ttl_seconds

def cleanup_expired_entries(
    cache: dict[K, tuple[V, float]],
    ttl_seconds: int,
) -> list[K]:
    """Find expired keys in cache."""
    return [
        k for k, (_, ts) in cache.items()
        if is_expired(ts, ttl_seconds)
    ]
```

### 2. Create CacheStats Mixin
Extract statistics tracking into reusable mixin.

```python
class CacheStatsMixin:
    """Mixin for cache statistics."""
    
    def __init__(self) -> None:
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}
    
    def _record_hit(self) -> None:
        self._stats["hits"] += 1
    
    def _record_miss(self) -> None:
        self._stats["misses"] += 1
    
    def _record_eviction(self, count: int = 1) -> None:
        self._stats["evictions"] += count
    
    def get_hit_rate(self, total: int) -> float:
        """Compute hit rate percentage."""
        return (self._stats["hits"] / total * 100) if total > 0 else 0
```

### 3. Document Lock Choices
Each cache chose different lock types for valid reasons:
- **QMutex**: Qt GUI integration (CommandCache, FilesystemCoordinator)
- **RLock**: Reentrant requirements (DirectoryCache)
- **Lock**: Simple, thread-safe requirements (SceneCache, PathValidators)

Document this explicitly in each class.

### 4. Standardize Stats Interface
All caches should return `get_stats()` with consistent fields where applicable:
- `hits`, `misses` (always)
- `evictions` (if applicable)
- `size` (cache entry count)
- `hit_rate_percent` (computed)
- `ttl_seconds` (if configurable)

---

## Conclusion

While the 5 TTL caches share ~215 lines of common patterns, consolidation is **not recommended** due to fundamental architectural differences. Instead, recommend:

1. Extract **3 utility/mixin modules** for shared patterns
2. Keep caches as-is for maximum flexibility
3. Document lock choices and design decisions in each cache
4. Standardize stats interface across all caches
5. Add type hints for cache entry structures

This approach provides **code clarity** and **maintenance benefits** without forcing incompatible caches into a single abstraction.
