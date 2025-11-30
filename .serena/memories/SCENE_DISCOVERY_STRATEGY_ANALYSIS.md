# Scene Discovery Strategy Module Analysis

**Module**: `scene_discovery_strategy.py` (666 LOC, **UNTESTED**)
**Related Modules**: scene_discovery_coordinator.py (744 LOC, tested), scene_cache.py (427 LOC), scene_parser.py (356 LOC), scene_file.py (192 LOC)
**Total Subsystem**: ~2,385 LOC

---

## 1. Strategy Pattern Implementation

### Abstract Base Class: SceneDiscoveryStrategy
- **File**: scene_discovery_strategy.py, lines 34-107
- **Purpose**: Defines interface for all discovery strategies
- **Pattern**: Template Method + Strategy patterns
- **Key Abstract Methods**:
  - `find_scenes_for_shot()` - Find scenes for specific shot
  - `find_all_scenes_in_show()` - Find all scenes in show
  - `get_strategy_name()` - Return strategy identifier

### Lazy Initialization Pattern
- **Rationale**: Breaks circular dependency cycle:
  - `scene_cache → threede_scene_model → threede_scene_finder → threede_scene_finder_optimized → scene_discovery_coordinator → scene_discovery_strategy → scene_cache`
- **Implementation**: In `__init__()` (lines 47-64), imports are done lazily inside method
- **Lazy Imports**:
  - `FileSystemScanner` - for file discovery
  - `SceneParser` - for .3de file parsing
  - `SceneCache` - for caching layer

---

## 2. Concrete Strategy Implementations

### LocalFileSystemStrategy (@final, lines 110-332)
- **Primary implementation** - baseline strategy
- **Methods**:
  - `find_scenes_for_shot()` (lines 118-217)
    - Checks cache first
    - Validates shot components
    - Scans both `user/` and `publish/` directories
    - Uses progressive discovery via scanner
    - Extracts plate from path
    - Creates ThreeDEScene objects
    - Returns ~20-100 lines of core logic with error handling
  
  - `find_all_scenes_in_show()` (lines 219-277)
    - Checks cache for show-level results
    - Calls `scanner.find_all_3de_files_in_show_targeted()`
    - Converts results to ThreeDEScene objects via parser
    - Caches results
  
  - `_scan_publish_directory()` (lines 279-332) - Private helper
    - Scans publish/version directories
    - Handles multiple publish versions

### ParallelFileSystemStrategy (@final, lines 335-434)
- **Optimization variant** - parallel worker support
- **Constructor**: Accepts `num_workers` parameter
- **Status**: Currently delegates to LocalFileSystemStrategy
- **TODO Comment**: "Implement parallel version in filesystem_scanner" (line 381)
- **Methods**:
  - `find_scenes_for_shot()` - Creates LocalFileSystemStrategy instance, delegates
  - `find_all_scenes_in_show()` - Same delegation pattern

### ProgressiveDiscoveryStrategy (@final, lines 437-568)
- **Streaming variant** - batch processing with callbacks
- **Use Case**: Large-scale discovery with progress updates
- **Methods**:
  - `find_scenes_for_shot()` - Delegates to LocalFileSystemStrategy
  - `find_all_scenes_in_show()` - Delegates to LocalFileSystemStrategy
  - `find_scenes_progressive()` - Actual streaming implementation (lines 485-568)
    - Accepts callback for batch processing
    - Batch size parameter
    - Yields results progressively

### NetworkAwareStrategy (@final, lines 571-618)
- **Future-proofing variant** - network-specific optimizations
- **Constructor**: Accepts `network_timeout` parameter (default 30s)
- **Status**: Currently delegates to LocalFileSystemStrategy
- **Use Case**: For future multi-machine/NFS scenarios
- **Methods**:
  - Both public methods delegate to LocalFileSystemStrategy with potential for network optimizations

---

## 3. Merge/Deduplication Algorithm

**Location**: NOT in `scene_discovery_strategy.py` - located in `cache_manager.py`

### merge_scenes_incremental() (cache_manager.py, lines 853-942)
- **Input**: cached scenes, fresh scenes, max_age_days (60 default)
- **Algorithm Steps**:
  1. Convert to dicts for consistent handling
  2. Build lookup: `cached_by_key[(show, sequence, shot)] = scene`
  3. Build set: `fresh_keys = {(show, sequence, shot)}`
  4. **Merge Phase**: For each fresh scene:
     - If in cached: UPDATE with fresh data
     - If not in cached: ADD as new
     - Update `last_seen` timestamp
  5. **Age-Based Pruning**: For cached scenes NOT in fresh data:
     - If `last_seen >= cutoff`: KEEP (preserve history)
     - If `last_seen < cutoff`: PRUNE (too old)
  6. Return merged list with statistics

### Deduplication Strategy
- **Key**: `(show, sequence, shot)` - shot-level composite key
- **Dedup Timing**: AFTER merge (line 873-874 comment)
- **Retention Policy**: Persistent incremental caching
  - New scenes added automatically
  - Previously cached scenes preserved (even if not in fresh data)
  - Timestamp-based cleanup after 60 days

### SceneMergeResult (cache_manager.py, lines 95-102)
- `updated_scenes`: All scenes (kept + new)
- `new_scenes`: Just new additions
- `removed_scenes`: No longer in fresh but retained
- `has_changes`: Detection flag
- `pruned_count`: Age-based removals

**Thread Safety**: Protected by QMutexLocker

---

## 4. Dependencies and Integration Points

### Direct Dependencies (in scene_discovery_strategy.py)
```
FileSystemScanner (lazy import)
  - find_all_3de_files_in_show_targeted()
  - find_3de_files_progressive()
  - verify_scene_exists()

SceneParser (lazy import)
  - extract_plate_from_path()
  - create_scene_from_file_info()
  - parse_3de_file_path()

SceneCache (lazy import)
  - get_scenes_for_shot()
  - cache_scenes_for_shot()
  - get_scenes_for_show()
  - cache_scenes_for_show()
```

### Integration Points
1. **SceneDiscoveryCoordinator** (scene_discovery_coordinator.py, 744 LOC)
   - Creates strategies via `create_discovery_strategy()`
   - Delegates to strategy implementation
   - Handles validation, filtering, statistics

2. **CacheManager** (cache_manager.py)
   - Provides `merge_scenes_incremental()` for advanced merging
   - Thread-safe scene merging with age-based pruning

3. **ThreeDEScene Model** (threede_scene_model.py)
   - Return type for all discovery methods
   - Contains: path, show, sequence, shot, user, plate, workspace_path, etc.

### Related Scene* Modules (Cohesive Subsystem)
- **scene_file.py** (192 LOC) - SceneFile/ImageSequence data classes
  - Properties: path, file_type, modified_time, user, version
  - Methods: name, app_name, display_name, relative_age, formatted_time, color
  
- **scene_parser.py** (356 LOC) - SceneParser for .3de file analysis
  - Plate extraction logic (BG/FG patterns, plate patterns)
  - Scene creation from file info
  - Shot/workspace path parsing
  
- **scene_cache.py** (427 LOC) - In-memory LRU cache for scenes
  - Separate from CacheManager (persistent disk cache)
  - TTL support (default 30 min for shots)
  - Shot-level and show-level caching
  - Thread-safe with RwLock
  
- **scene_discovery_coordinator.py** (744 LOC) - Orchestrator/Facade
  - Strategy management
  - Input validation and filtering
  - Multi-show discovery
  - Progressive discovery support

---

## 5. Key Public Interfaces

### SceneDiscoveryStrategy Interface
```python
def find_scenes_for_shot(
    shot_workspace_path: str,
    show: str,
    sequence: str,
    shot: str,
    excluded_users: set[str] | None = None,
) -> list[ThreeDEScene]

def find_all_scenes_in_show(
    show_root: str,
    show: str,
    excluded_users: set[str] | None = None,
) -> list[ThreeDEScene]

def get_strategy_name() -> str
```

### Factory Function
```python
def create_discovery_strategy(
    strategy_type: str = "local",
    **kwargs: Unpack[StrategyKwargs]
) -> SceneDiscoveryStrategy
```
- Supported types: "local", "parallel", "progressive", "network"
- Kwargs: `num_workers` (int), `network_timeout` (int)

### Type-Safe Kwargs
```python
class StrategyKwargs(TypedDict, total=False):
    num_workers: int | None
    network_timeout: int
```

---

## 6. Testing Priorities

### HIGH PRIORITY (Core Logic)
1. **LocalFileSystemStrategy** (lines 110-332) - Primary implementation
   - `find_scenes_for_shot()` with various directory structures
   - `find_all_scenes_in_show()` with multi-sequence shows
   - `_scan_publish_directory()` helper
   - Error handling for missing directories
   - Cache integration

2. **Cache Integration** (all strategies)
   - Cache hit/miss behavior
   - Cache invalidation on errors
   - TTL expiration
   - Thread safety during discovery

### MEDIUM PRIORITY (Alternative Strategies)
3. **ParallelFileSystemStrategy** (lines 335-434)
   - Delegation to LocalFileSystemStrategy works
   - TODO: Implement actual parallel scanning
   - Test worker pool behavior when implemented

4. **ProgressiveDiscoveryStrategy** (lines 437-568)
   - Callback-based batch processing
   - Batch size boundaries
   - Early termination scenarios

### LOWER PRIORITY (Future Features)
5. **NetworkAwareStrategy** (lines 571-618)
   - Currently delegates to LocalFileSystemStrategy
   - Network timeout handling (future)
   - NFS/remote path support (future)

6. **Factory Function & Strategy Selection**
   - create_discovery_strategy() with all types
   - Invalid strategy type handling
   - Kwargs validation

---

## 7. Should Related Scene_* Modules Be Tested Together?

### Answer: PARTIAL YES

**Test Together**:
- ✅ **LocalFileSystemStrategy + SceneParser + SceneCache** 
  - Parser is called directly by strategy to extract plates/metadata
  - Cache is checked/updated by strategy
  - These form the "hot path" for scene discovery
  - **Recommendation**: Unit tests for strategy with mocked dependencies, integration tests for full pipeline

- ✅ **SceneDiscoveryCoordinator + Strategy**
  - Already tested together (test_scene_discovery_coordinator.py)
  - Coordinator orchestrates strategy selection
  - Already has test doubles for scanner/parser/cache

**Test Separately**:
- ❌ **SceneParser** - Can be tested independently
  - Pure file parsing logic
  - No external dependencies
  - Test data: fixture .3de files and paths
  
- ❌ **SceneCache** - Can be tested independently
  - Generic LRU TTL cache
  - Thread-safe operations
  - No scene-specific logic
  
- ❌ **SceneFile** - Can be tested independently
  - Data class with property methods
  - File type mappings, relative age calculation
  - Time formatting logic

**Integration Test Strategy**:
1. Unit tests for each module (parser, cache, file, strategy implementations)
2. Integration tests combining strategy + parser + cache
3. End-to-end tests with SceneDiscoveryCoordinator

---

## 8. Critical Testing Gaps

### Currently Untested (scene_discovery_strategy.py)
1. ❌ LocalFileSystemStrategy.find_scenes_for_shot() - Core discovery
2. ❌ LocalFileSystemStrategy.find_all_scenes_in_show() - Show-level discovery
3. ❌ LocalFileSystemStrategy._scan_publish_directory() - Publish scanning
4. ❌ ParallelFileSystemStrategy (full implementation pending)
5. ❌ ProgressiveDiscoveryStrategy.find_scenes_progressive() - Batch callback logic
6. ❌ NetworkAwareStrategy (future feature)
7. ❌ create_discovery_strategy() factory function
8. ❌ Cache integration in all strategies
9. ❌ Error scenarios (missing directories, permission denied, etc.)
10. ❌ Excluded users filtering

### Coverage Blind Spots
- Shot workspace path validation
- Multi-version publish directory handling
- Progressive discovery batch boundaries
- Circular dependency breaking verification
- Memory leaks in lazy imports

### Test Data Requirements
- Fixture .3de files with metadata
- Multi-user shot directories
- Publish/version directory structures
- 3DE scene model instances
- Cache state scenarios (empty, stale, fresh)

---

## Summary Table

| Aspect | Details |
|--------|---------|
| **Module Size** | 666 LOC (untested), 2,385 LOC subsystem total |
| **Strategy Pattern** | 4 concrete implementations + 1 abstract base |
| **Dependencies** | FileSystemScanner, SceneParser, SceneCache (lazy imports) |
| **Circular Dependencies** | Broken via lazy imports in __init__() |
| **Merge Algorithm** | cache_manager.merge_scenes_incremental() - shot-level dedup with age pruning |
| **Dedup Key** | (show, sequence, shot) tuple |
| **Caching Strategy** | Persistent incremental with 60-day TTL for age-based pruning |
| **Thread Safety** | QMutexLocker in merge operations |
| **Test Coverage** | Coordinator tested; Strategy implementations UNTESTED |
| **Cohesion** | Tight coupling: Strategy ↔ Parser ↔ Cache ↔ Coordinator |
| **Testing Approach** | Recommend unit tests with mocked deps + integration tests |
