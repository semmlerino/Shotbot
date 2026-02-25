# Shotbot Complexity Hotspots - Detailed Analysis

> **Note**: Line numbers in this document are approximate and may drift as code evolves. Use symbol names for navigation.
> **Last Updated**: December 2025

## Overview

Shotbot has 3 central complexity hotspots that require careful attention during modifications. This document provides line-by-line analysis of these critical components.

---

## 1. MainWindow (main_window.py)

### Complexity Profile
- **Total LOC**: 1,800 (including docstrings)
- **Methods**: 62
- **Signal Connections**: 15+
- **Instance Variables**: 35+
- **Complexity Score**: ⚠️⚠️⚠️ CRITICAL

### Key Methods Breakdown

#### Constructor (`__init__`, lines 180-378)
- **Complexity**: HIGH
- **Purpose**: Initialize all UI components and managers
- **Operations**:
  ```python
  # Core initialization flow
  1. Create cache_manager (singleton pattern)
  2. Create 3 models (ShotModel, ThreeDESceneModel, PreviousShotsModel)
  3. Create 2 controllers (SettingsController, ThreeDEController)
  4. Create 3 item models + grid views
  5. Create panels and dialogs
  6. Setup menu bar and status bar
  7. Setup accessibility
  8. Connect all signals (15+ connections)
  9. Start initial load
  10. Start session warmer
  11. Emit model updates
  ```
- **Risk**: Any error in initialization cascades to all systems
- **Testing**: Requires comprehensive mocking of all dependencies

#### Signal Routing Methods

**`_on_tab_changed(index)` (lines 912-955)**
- **Purpose**: Handle tab switching between 3 pipelines
- **Complexity**: MEDIUM-HIGH
- **Logic Flow**:
  ```
  1. Detect which tab is active (index 0, 1, or 2)
  2. Load data for that tab if not already loaded
  3. Update visibility of related panels
  4. Update color scheme (accent color per tab)
  5. Trigger thumbnail loading for visible items
  6. Update filter UI for current tab
  ```
- **Issues**:
  - Each tab switch may trigger background loading
  - Filter state must be isolated per tab
  - Need to prevent duplicate loading

**`_on_shot_selected(shot)` (lines 1089-1160)**
- **Purpose**: Handle shot selection in My Shots tab
- **Complexity**: MEDIUM
- **Logic Flow**:
  ```
  1. Update shot info panel with metadata
  2. Set current shot in controllers
  3. Update launcher options
  4. Check for associated 3DE scenes
  5. Trigger related operations (thumbnails, etc.)
  ```

#### Data Flow Coordination

**`_on_shots_loaded(shots)` (lines 837-844)**
- Receives: ShotModel signal with loaded shots
- Updates: ShotItemModel with new data
- Emits: View update signals

**`_on_shots_changed(added, removed)` (lines 846-853)**
- Receives: ShotModel signal with changes
- Updates: Previous shots if shots migrated
- Triggers: Cache refresh if needed

**`_on_refresh_started()` / `_on_refresh_finished()` (lines 855-868)**
- Receives: RefreshOrchestrator signals
- Updates: Status bar
- Prevents: Multiple concurrent refreshes

#### Filter & Search Methods

**`_apply_show_filter(show)` (lines 1184-1207)**
- Filters grid by selected show
- Applies across both shot tabs
- State must be maintained during tab switch

**`_on_shot_text_filter_requested(text)` (lines 1213-1227)**
- Real-time text search filtering
- Applied to current tab's model
- Debounced to avoid excessive updates

#### Complex Operations

**`_on_shot_recover_crashes_requested()` (lines 1229-1330)**
- Handles 3DE crash file recovery
- Complex dialog interaction
- File system operations
- Model updates after recovery

**`_sync_thumbnail_sizes()` (lines 1401-1434)**
- Synchronizes thumbnail size across all 3 tabs
- Coordinates view updates
- Must handle concurrent scroll events

### Instance Variables (35 Total)

```python
# Managers & Controllers (5)
self._process_pool = ProcessPoolManager.get_instance()  # line 229
self.cache_manager = CacheManager()  # line 242
self.refresh_orchestrator = None  # line 248
self.settings_manager = SettingsManager()  # line 251
self.settings_controller = SettingsController(self)  # line 259

# Models (6)
self.shot_model = None  # line 266
self.threede_scene_model = None  # line 289
self.previous_shots_model = None  # line 291
self.threede_item_model = None  # line 262
self.command_launcher = CommandLauncher(...)  # line 309

# UI Components (15+)
self.tab_widget = QTabWidget()  # line 411
self.shot_grid = ShotGridView(...)  # line 420
self.threede_shot_grid = ThreeDEGridView(...)  # line 424
self.previous_shots_grid = None  # line 431
self.shot_info_panel = ShotInfoPanel(...)  # line 446
self.launcher_panel = LauncherPanel(...)  # line 450
self.log_viewer = LogViewer(...)  # line 467
self.status_bar = QStatusBar()  # line 478
# ... 7 more widgets

# State Variables (5)
self._closing = False  # line 335
self._launcher_dialog = None  # line 336
self._session_warmer = None  # line 337
self._last_selected_shot_name = ""  # line 338
# ... 1 more
```

### Dependency Web

```
MainWindow depends on:
├─ 3 Models
│  ├─ ShotModel (depends on ProcessPoolManager, CacheManager)
│  ├─ ThreeDESceneModel (depends on ThreadPool, CacheManager)
│  └─ PreviousShotsModel (depends on ProcessPoolManager)
├─ 3 Item Models (depends on Models)
├─ 3 Grid Views (depends on Item Models)
├─ 3 Controllers
│  ├─ SettingsController (depends on SettingsManager)
│  └─ ThreeDEController (depends on ThreeDESceneModel)
├─ 8 Panels/Dialogs
├─ Managers (ProcessPoolManager, CacheManager, SettingsManager)
└─ Support (NotificationManager, ProgressManager, SettingsManager)

INCOMING: 0 (entry point)
OUTGOING: 15+
```

### Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Circular signal routing | HIGH | Document signal flow, use debugging tools |
| State synchronization across tabs | HIGH | Unit tests for tab switching |
| Memory leaks in cleanup | MEDIUM | Ensure all signals disconnected in cleanup() |
| Performance: too many signals | MEDIUM | Batch updates, debounce rapid changes |
| Difficult to test | MEDIUM | Mock all dependencies, test signals |

### Recommended Refactoring

**Extract 3 Helper Classes**:
1. `FilterCoordinator` - Handles all filter/search logic
2. `ThumbnailSizeManager` - Handles size synchronization
3. `TabCoordinator` - Handles tab switching logic

**After Refactoring**:
- MainWindow LOC: 1,800 → ~1,300
- Methods: 62 → ~40
- Testability: Improved (each coordinator testable independently)

---

## 2. CacheManager (cache_manager.py)

### Complexity Profile
- **Total LOC**: 1,544 (including docstrings)
- **Methods**: 49
- **Cache Types**: 4 (shots, previous shots, 3DE scenes, thumbnails)
- **Thread Safety**: QMutex protecting all shared state
- **Complexity Score**: ⚠️⚠️ HIGH

### Cache Architecture

```
Memory Layer (Runtime):
├─ _pixmap_cache (dict[str, QPixmap])
│  └─ Lazy-loaded, cleared on app exit
└─ _stat_cache (dict[Path, stat])
   └─ File stat caching (60s TTL)

Disk Layer (Persistent):
├─ ~/.shotbot/cache/production/shots.json
│  └─ TTL: 30 minutes
├─ ~/.shotbot/cache/production/previous_shots.json
│  └─ TTL: None (persistent)
├─ ~/.shotbot/cache/production/threede_scenes.json
│  └─ TTL: None (persistent, incremental merge)
└─ ~/.shotbot/cache/thumbnails/
   └─ JPG files, no expiration
```

### Core Methods Breakdown

#### Thumbnail Operations

**`cache_thumbnail(shot, pixmap)` (lines 580-630)**
- **Complexity**: MEDIUM
- **Operations**:
  1. Generate cache path from shot metadata
  2. Convert pixmap to JPG (PIL)
  3. Write to disk atomically (temp → replace)
  4. Cache in memory (_pixmap_cache)
  5. Handle errors gracefully
- **Lock**: Held during entire operation
- **Risk**: PIL conversion can be slow for large images

**`get_cached_thumbnail(shot)` (lines 632-720)**
- **Complexity**: MEDIUM-HIGH
- **Operations**:
  1. Check memory cache (fast path)
  2. Check disk cache with stat (respect THUMBNAIL_TTL)
  3. Try to load from multiple formats (JPG, PNG, EXR)
  4. Fall back to placeholder if not found
  5. Cache loaded pixmap in memory
- **Logic Flow**:
  ```
  Try Memory Cache
    ↓ (miss)
  Try Disk Cache
    ├─ Check stat timestamp
    ├─ Compare with file mtime
    └─ Load JPG if valid
    ↓ (miss)
  Try Source Images
    ├─ Path 1: JPEG
    ├─ Path 2: PNG
    └─ Path 3: EXR
    ↓ (all miss)
  Return Placeholder
  ```

#### Shot Data Caching

**`cache_shots(shots)` (lines 360-380)**
- Serializes list of Shot objects to JSON
- Adds metadata (timestamp, version)
- Writes atomically
- Simple, straightforward operation

**`get_cached_shots()` (lines 382-410)**
- Complexity: MEDIUM
- Operations:
  1. Check if cache file exists
  2. Verify cache age against TTL (30 minutes)
  3. Parse JSON
  4. Reconstruct Shot objects
  5. Handle deserialization errors
- **Key Detail**: TTL check happens BEFORE deserialization

#### Scene Data Caching (Complex!)

**`get_persistent_threede_scenes()` (lines 470-480)**
- Loads 3DE scenes WITHOUT TTL check (persistent)
- Used for scene discovery from previous sessions

**`merge_scenes_incremental(cached, fresh)` (lines 482-525)**
- **Complexity**: HIGH 🔴
- **Purpose**: Merge cached scenes with newly discovered scenes
- **Algorithm**:
  ```
  1. Build lookup by composite key (show, sequence, shot)
  2. For each fresh scene:
     a. Check if we have it cached
     b. If yes: keep fresh (updated)
     c. If no: add as new
  3. For each cached scene NOT in fresh:
     a. Check if deleted (optional)
     b. Keep if not deleted (preserves history)
  4. Deduplicate: keep best scene per shot
     a. Prefer higher mtime (newer file)
     b. Prefer plate scenes over others
  5. Sort by composite key
  6. Return merged result with stats
  ```
- **Data Structures**:
  ```python
  # Input
  cached: List[ThreeDEScene]  # From previous session
  fresh: List[ThreeDEScene]   # From filesystem scan
  
  # Processing
  cached_by_key: dict[tuple, ThreeDEScene]
  fresh_by_key: dict[tuple, ThreeDEScene]
  
  # Output
  SceneMergeResult(
    merged: List[ThreeDEScene],  # Combined + deduped
    added: int,      # Count of new scenes
    removed: int,    # Count of deleted scenes
    updated: int,    # Count of modified scenes
  )
  ```
- **Risk**: Deduplication logic can hide deleted scenes

#### Incremental Data Merging

**`merge_shots_incremental(cached, fresh)` (lines 440-468)**
- Similar pattern to scenes but simpler
- Preserves deleted shots (keeps in previous shots)
- Returns merge stats

### Thread Safety Implementation

**QMutex Pattern**:
```python
def _read_json_cache(self, cache_file: Path) -> dict | None:
    with QMutexLocker(self._lock):
        # CRITICAL SECTION
        # Only one thread can read/write cache simultaneously
        if not cache_file.exists():
            return None
        return json.load(open(cache_file))
```

**Lock Contention Risk**:
- All cache operations lock same mutex
- Thumbnail loading + shot cache access can contend
- Single lock for all operations (not granular per-cache-type)

### Instance Variables

```python
# Caching state
self._cache_dir = Path.home() / ".shotbot/cache"  # line 94
self._shots_cache_file = None  # line 97
self._previous_shots_cache_file = None  # line 98
self._threede_cache_file = None  # line 99

# Memory caches
self._pixmap_cache: dict[str, QPixmap] = {}  # line 112
self._stat_cache: dict[Path, stat_result] = {}  # line 113

# Thread safety
self._lock = QMutex()  # line 115

# Configuration
THUMBNAIL_SIZE = 350  # line 63
THUMBNAIL_QUALITY = 85  # line 64
DEFAULT_TTL_MINUTES = 30  # line 58
```

### Complexity Risk Matrix

| Operation | Lock Held | Duration | Risk |
|-----------|-----------|----------|------|
| Load thumbnail (disk) | YES | 50-200ms | Lock contention |
| Convert pixmap (PIL) | YES | 100-500ms | Lock contention |
| Parse JSON cache | YES | 10-50ms | Acceptable |
| Merge scenes | YES | 50-200ms | Lock contention |
| Write cache (atomic) | YES | 5-20ms | Acceptable |

**Recommendation**: Consider splitting into per-cache-type locks

### Error Handling Patterns

**Graceful Degradation**:
```python
# If cache is corrupted, return None
try:
    return json.load(cache_file)
except json.JSONDecodeError:
    self.logger.error(f"Corrupted cache: {cache_file}")
    return None  # Fall back to re-fetch
```

**Atomic Writes**:
```python
# Write to temp file, then replace (atomic on POSIX)
with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False) as tmp:
    json.dump(data, tmp)
    tmp.flush()
os.replace(tmp.name, target_file)  # Atomic
```

---

## 3. ProcessPoolManager (process_pool_manager.py)

### Complexity Profile
- **Total LOC**: 1,073
- **Methods**: 26
- **Pattern**: Singleton with thread-safe double-checked locking
- **Key Components**: ThreadPoolExecutor, CommandCache, SessionPool management
- **Complexity Score**: ⚠️⚠️ HIGH

### Singleton Implementation (COMPLEX!)

**`__new__` Method (lines 215-234)**
```python
def __new__(cls):
    # Double-checked locking pattern
    if cls._instance is None:
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                cls._instance = instance
    return cls._instance
```

**Complexity**: 
- Race condition if not carefully implemented
- Second check inside lock is essential
- Ensures only one instance even with concurrent access

### Session Pool Management

**Session Pool Architecture**:
```
ProcessPoolManager (Singleton)
├─ _executor: ThreadPoolExecutor (Python threadpool)
├─ _session_pools: dict[str, list[WorkspaceSession]]
│  ├─ Key: session type (e.g., "default")
│  └─ Value: list of reusable sessions
├─ _session_round_robin: dict[str, int]
│  └─ Tracks which session to use next (round-robin)
└─ _cache: CommandCache
   └─ Caches command results
```

**Round-Robin Load Balancing**:
```python
def _get_session_for_type(self, session_type: str):
    sessions = self._session_pools[session_type]
    idx = self._session_round_robin[session_type]
    
    # Get session
    session = sessions[idx % len(sessions)]
    
    # Advance counter
    self._session_round_robin[session_type] = (idx + 1) % len(sessions)
    
    return session  # Simple, effective
```

### Command Execution Flow

**`execute_workspace_command(cmd)` (lines 290-362)**
- **Complexity**: HIGH
- **Steps**:
  1. Check if result in CommandCache
  2. If cache hit: return immediately
  3. If cache miss:
     a. Get available session (round-robin)
     b. Submit to executor
     c. Wait for result
     d. Store in cache
     e. Return result
- **Metrics Tracking**:
  - Track cache hit/miss
  - Track execution time
  - Track queue depth

**CommandCache Implementation**:
```python
class CommandCache:
    def __init__(self):
        self._cache: dict[str, CommandResult] = {}
        self._timestamps: dict[str, float] = {}
    
    def get(self, cmd: str) -> str | None:
        # Check TTL before returning
        if cmd in self._cache:
            age = time.time() - self._timestamps[cmd]
            if age < COMMAND_CACHE_TTL:
                return self._cache[cmd]
            else:
                del self._cache[cmd]
        return None
    
    def set(self, cmd: str, result: str) -> None:
        self._cache[cmd] = result
        self._timestamps[cmd] = time.time()
```

### Session Pool Lifecycle

**Session Creation (Lazy)**:
```python
def _get_or_create_session_pool(self, session_type: str):
    # Called on first command execution
    # Sessions are NOT created during __init__
    
    if session_type not in self._session_pools:
        # Create new pool
        sessions = []
        for i in range(self._sessions_per_type):
            session = WorkspaceSession(...)
            sessions.append(session)
        self._session_pools[session_type] = sessions
    
    return self._session_pools[session_type]
```

**Session Reuse**:
- Sessions are created once, reused indefinitely
- Each command execution reuses same session
- No recreation overhead

**Session Cleanup (on shutdown)**:
```python
def shutdown(self):
    # Close all sessions in pools
    for session_list in self._session_pools.values():
        for session in session_list:
            session.close()
    
    # Shut down thread executor
    self._executor.shutdown(wait=True)
```

### Thread Safety

**Locks Used**:
```python
self._session_lock = threading.Lock()  # Protects session pools
self._mutex = QMutex()                 # Qt integration (for signals)
```

**Lock Held During**:
1. Session pool access (~5-10ms)
2. Metrics update (~1ms)
3. Cache access (~1ms)

**NOT held during**:
- Command execution (delegated to executor)
- File I/O (subprocess handles)

### Key Optimizations

1. **Command Caching**: Avoid redundant workspace executions
2. **Session Pooling**: Reuse sessions (creation expensive)
3. **Round-Robin**: Spread load evenly
4. **Lazy Initialization**: Sessions created on-demand
5. **Metrics Tracking**: Monitor pool efficiency

### Risks & Issues

| Risk | Severity | Details |
|------|----------|---------|
| Session Leak | MEDIUM | If session not properly closed, resource leak |
| Deadlock | MEDIUM | Circular dependencies in locks |
| Cache Stale Data | LOW | Commands return cached old data for TTL duration |
| Memory Growth | LOW | Executor queue can grow unbounded |
| Reset in Tests | HIGH | Singleton state difficult to reset between tests |

**Test Mitigation**:
```python
@classmethod
def reset(cls):
    """Reset singleton for testing."""
    if cls._instance:
        cls._instance.shutdown()
    cls._instance = None
```

---

## Cross-Component Interaction

### Data Flow: Shot Loading

```
User Tab Switch
    ↓
MainWindow._on_tab_changed()
    ↓
ShotModel.load_shots()
    ↓
CacheManager.get_cached_shots()
    ├─ Cache hit: Return cached data
    ├─ Cache miss: Continue
    └─ Check TTL: If expired, continue
    ↓
ProcessPoolManager.execute_workspace_command("ws -sg")
    ├─ Check command cache
    ├─ Command cache miss: Execute
    ├─ Get session from pool (round-robin)
    └─ Session executes workspace command
    ↓
OptimizedShotParser.parse_shots(ws_output)
    └─ Extract shot metadata, return Shot objects
    ↓
CacheManager.cache_shots(shots)
    └─ Write to disk cache (JSON)
    ↓
ShotModel emits: background_load_finished(shots)
    ↓
MainWindow._on_shots_loaded(shots)
    ├─ Update ShotItemModel
    ├─ Emit signals to grid view
    └─ Grid view renders
    ↓
BaseItemModel.set_visible_range(0, 20)
    └─ Trigger lazy thumbnail loading for visible items
    ↓
ThumbnailCacheLoader loads thumbnails
    ├─ Check memory cache (fast)
    ├─ Check disk cache (medium)
    └─ Load source images (slow)
```

### Thread Safety: Signals & Slots

```
Worker Thread (background loader)
    │
    ├─ Loads data (blocking I/O)
    │
    └─ Emits signal (thread-safe)
        │
        ├─ Signal queued to main thread
        │
        └─ Main thread processes signal in event loop
            │
            └─ Slot updates UI (safe, main thread only)
```

---

## Summary Table

| Component | LOC | Methods | Hotspot | Issue |
|-----------|-----|---------|---------|-------|
| **MainWindow** | 1,800 | 62 | Central orchestrator | Too many responsibilities |
| **CacheManager** | 1,544 | 49 | Multi-strategy caching | Multiple lock holders |
| **ProcessPoolManager** | 1,073 | 26 | Session management | Singleton complexity |

**Total Complexity**: 4,417 LOC (7.3% of 60K codebase) = core orchestration layer

---

## Recommendations

### High Priority
1. Extract MainWindow helpers (FilterCoordinator, etc.)
2. Split CacheManager by strategy
3. Add integration tests for all 3 hotspots

### Medium Priority
1. Extract SessionPool from ProcessPoolManager
2. Add performance benchmarks
3. Document signal routing

### Low Priority
1. Add complexity metrics to CI/CD
2. Refactor metrics tracking
3. Add architecture diagrams to docs
