# ShotBot Bug Fix and Performance Optimization Plan

**Date**: 2025-10-27
**Version**: 1.0
**Status**: DRAFT
**Estimated Total Effort**: 8-12 hours

---

## Executive Summary

This document outlines a systematic plan to address 6 identified issues in the ShotBot application, ranging from critical correctness bugs to performance optimizations. Issues are prioritized by impact and risk, with detailed implementation steps, verification criteria, and rollback procedures.

**Critical Path Items** (Must Fix):
- Issue #1: Duplicate signal connections (correctness bug)
- Issue #2: Case inconsistency in plate IDs (silent failure risk)

**High-Value Optimizations** (Should Fix):
- Issue #3: Excessive thumbnail polling (performance)
- Issue #4: Over-frequent settings saves (I/O waste)

**Low-Priority Items** (Nice-to-Have):
- Issue #5: Item→shot ID mismatch investigation
- Issue #6: ProcessPool size optimization

---

## Issue Inventory

| # | Issue | Severity | Impact | Effort | Priority |
|---|-------|----------|--------|--------|----------|
| 1 | Duplicate Signal Connections | 🔴 HIGH | Slots fire multiple times | 2h | P0 |
| 2 | Case Inconsistency (PL01/pl01) | 🟠 MEDIUM | Silent thumbnail failures | 3h | P0 |
| 3 | Chatty Thumbnail Polling | 🟡 MEDIUM | CPU/log noise | 2h | P1 |
| 4 | Over-Frequent Settings Saves | 🟡 MEDIUM | Disk I/O waste | 1.5h | P1 |
| 5 | Item→Shot ID Mismatch | 🟡 LOW | Possible index bug | 2h | P2 |
| 6 | Fixed ProcessPool Size | 🔵 LOW | Suboptimal parallelism | 0.5h | P3 |

---

## Issue #1: Duplicate Signal Connections 🔴

### Problem Statement

**Symptom**: Log shows 8 identical "Connected signal with ConnectionType.QueuedConnection" messages and duplicate progress operations.

**Root Cause**: `safe_connect()` in `thread_safe_worker.py` doesn't prevent duplicate connections. If `_setup_worker_signals()` is called twice (e.g., during worker restart), all slots will fire multiple times per signal emission.

**Risk**:
- High - Causes slots to execute 2-8x per emission
- Can trigger race conditions in state management
- Progress operations started multiple times
- Memory leaks from accumulated connections

### Evidence

```
2025-10-27 09:42:24 - threede_scene_worker.ThreeDESceneWorker - DEBUG - Worker 139634543181120: Connected signal with ConnectionType.QueuedConnection
... (repeated 8 times)

2025-10-27 09:42:24 - progress_manager - DEBUG - Started progress operation: Scanning for 3DE scenes (type: STATUS_BAR)
... (appears twice)
```

### Implementation Plan

#### Step 1: Add Connection Deduplication (thread_safe_worker.py)

**File**: `thread_safe_worker.py`
**Method**: `safe_connect()` (line ~245)

**Current Code**:
```python
def safe_connect(
    self,
    signal: SignalInstance,
    slot: Callable[..., object],
    connection_type: Qt.ConnectionType = Qt.ConnectionType.QueuedConnection,
) -> None:
    connection = (signal, slot)
    self._connections.append(connection)
    signal.connect(slot, connection_type)
    self.logger.debug(f"Worker {id(self)}: Connected signal with {connection_type}")
```

**New Code**:
```python
def safe_connect(
    self,
    signal: SignalInstance,
    slot: Callable[..., object],
    connection_type: Qt.ConnectionType = Qt.ConnectionType.QueuedConnection,
) -> None:
    """Track signal connections for safe cleanup.

    This method ensures connections are unique - calling it multiple times
    with the same signal/slot pair will not create duplicate connections.

    Args:
        signal: Signal to connect (runtime SignalInstance)
        slot: Slot to connect to
        connection_type: Qt connection type (default: QueuedConnection for thread safety)
    """
    connection = (signal, slot)

    # Prevent duplicate connections
    if connection in self._connections:
        self.logger.debug(
            f"Worker {id(self)}: Connection already exists for {slot.__name__}, skipping"
        )
        return

    self._connections.append(connection)

    # Use UniqueConnection flag to prevent Qt-level duplicates
    unique_type = connection_type | Qt.ConnectionType.UniqueConnection
    signal.connect(slot, unique_type)

    self.logger.debug(
        f"Worker {id(self)}: Connected signal with {connection_type} (unique)"
    )
```

**Changes**:
1. Check if connection already exists in `_connections` list
2. Add `UniqueConnection` flag to Qt connection type
3. Update logging to indicate unique connections
4. Add docstring explaining deduplication behavior

#### Step 2: Add Connection Audit Method

**Add new method** to `ThreadSafeWorkerBase` class:

```python
def get_connection_count(self) -> int:
    """Get the number of tracked connections.

    Returns:
        Number of connections tracked by this worker
    """
    return len(self._connections)

def audit_connections(self) -> dict[str, int]:
    """Audit connections for debugging duplicate connection issues.

    Returns:
        Dictionary mapping slot names to connection counts
    """
    slot_counts: dict[str, int] = {}
    for signal, slot in self._connections:
        slot_name = slot.__name__
        slot_counts[slot_name] = slot_counts.get(slot_name, 0) + 1

    # Log any duplicates found
    duplicates = {k: v for k, v in slot_counts.items() if v > 1}
    if duplicates:
        self.logger.warning(f"Found duplicate connections: {duplicates}")

    return slot_counts
```

#### Step 3: Add Verification Logging

**File**: `controllers/threede_controller.py`
**Method**: `_setup_worker_signals()` (line ~630)

**Add at the end of the method**:
```python
def _setup_worker_signals(self, worker: ThreeDESceneWorker) -> None:
    # ... existing connection code ...

    # Audit connections for debugging
    connection_count = worker.get_connection_count()
    self.logger.debug(f"Connected all worker signals to controller ({connection_count} total connections)")

    # In debug mode, audit for duplicates
    if os.getenv("SHOTBOT_DEBUG"):
        worker.audit_connections()
```

### Success Metrics

1. **Log Output**: Only ONE "Connected signal" message per signal type (8 total, not 8×8)
2. **Progress Operations**: Only ONE "Started progress operation" per worker start
3. **Connection Count**: `get_connection_count()` returns 8 (not 64+)
4. **Audit Clean**: `audit_connections()` reports no duplicates

### Verification Steps

1. **Unit Test**:
```python
def test_safe_connect_prevents_duplicates():
    """Test that safe_connect prevents duplicate connections."""
    worker = ThreeDESceneWorker(shots=[], enable_progressive=False)

    # Connect same slot twice
    call_count = 0
    def test_slot():
        nonlocal call_count
        call_count += 1

    worker.safe_connect(worker.started, test_slot)
    worker.safe_connect(worker.started, test_slot)  # Should be ignored

    # Verify only one connection tracked
    assert worker.get_connection_count() == 1

    # Emit signal - should only fire once
    worker.started.emit()
    assert call_count == 1
```

2. **Integration Test**: Run app with `SHOTBOT_DEBUG=1`, refresh 3DE scenes 3 times, verify logs show:
   - First refresh: 8 "Connected signal" messages
   - Second refresh: 0 "Connected signal" messages (worker reused or properly cleaned up)
   - Third refresh: 8 "Connected signal" messages (new worker)

3. **Manual Test**: Open app, switch between tabs multiple times, verify no duplicate UI updates

### Rollback Procedure

If issues arise:
1. Revert `thread_safe_worker.py` changes
2. Remove `UniqueConnection` flag (Qt might reject it for some signal types)
3. Keep audit methods for future debugging
4. Document as "known issue - connection pooling needed"

---

## Issue #2: Case Inconsistency in Plate IDs 🟠

### Problem Statement

**Symptom**: Logs show both `PL01` and `pl01` for the same plate in different contexts.

**Root Cause**: Inconsistent case handling when constructing paths, extracting plate IDs from filenames, and storing plate references.

**Risk**:
- Medium/High - On Linux (production VFX environment), paths are case-sensitive
- Thumbnail lookups may fail silently if case doesn't match filesystem
- Show/plate filters may miss items due to case mismatch
- Cache keys may differ from filesystem reality

**Platform Impact**:
- Linux/WSL: HIGH risk (case-sensitive)
- Windows: LOW risk (case-insensitive)
- macOS: MEDIUM risk (case-preserving but insensitive by default)

### Evidence

```
2025-10-27 09:42:09 - utils - DEBUG - Found plate: FG01 (type: FG, priority: 0)
2025-10-27 09:42:10 - utils - DEBUG - Found plate: PL01 (type: PL, priority: 0.5)
2025-10-27 09:42:10 - utils - DEBUG - Found plate: pl01 (type: PL, priority: 0.5)  # ← inconsistent!
```

### Implementation Plan

#### Step 1: Audit Current Case Handling

**Search for plate ID usage**:
```bash
grep -r "plate" --include="*.py" | grep -E "(upper|lower|casefold)" | wc -l
```

**Key areas to audit**:
1. Plate extraction from filenames (`utils.py`, `plate_discovery.py`)
2. Path construction (`get_thumbnail_path()`, workspace paths)
3. Cache keys (`cache_manager.py`)
4. Show/plate filters (`shot_filter.py`)
5. 3DE scene parsing (`threede_scene_model.py`)

#### Step 2: Establish Canonical Form

**Decision**: Use **UPPERCASE** as canonical form for plate IDs
- Matches VFX industry convention (PL01, FG01, BG02)
- Matches majority of existing codebase usage
- Easier to read in logs and UI

**Exception**: File paths follow filesystem case
- Don't rename files on disk
- Use case-insensitive matching for lookups
- Normalize only for display/storage

#### Step 3: Create Normalization Utility

**File**: `utils.py`
**Add new function**:

```python
def normalize_plate_id(plate_id: str | None) -> str | None:
    """Normalize plate ID to canonical uppercase form.

    VFX industry convention uses uppercase plate IDs (PL01, FG01, BG02).
    This function ensures consistency across the application.

    Args:
        plate_id: Plate identifier (may be None, uppercase, lowercase, or mixed)

    Returns:
        Uppercase plate ID, or None if input was None

    Examples:
        >>> normalize_plate_id("pl01")
        "PL01"
        >>> normalize_plate_id("FG01")
        "FG01"
        >>> normalize_plate_id(None)
        None
    """
    if plate_id is None:
        return None
    return plate_id.upper()


def normalize_plate_for_path(plate_id: str) -> str:
    """Normalize plate ID for filesystem path lookups.

    Returns lowercase version for case-insensitive path matching.
    Use this when searching for files that may have been created
    with inconsistent casing.

    Args:
        plate_id: Plate identifier

    Returns:
        Lowercase plate ID for path matching

    Examples:
        >>> normalize_plate_for_path("PL01")
        "pl01"
    """
    return plate_id.lower()
```

#### Step 4: Update Plate Extraction

**File**: `utils.py`
**Function**: `extract_plate_from_path()` (find with grep)

**Add normalization**:
```python
def extract_plate_from_path(path: Path) -> str | None:
    """Extract plate ID from path and normalize to uppercase."""
    # ... existing regex extraction code ...

    if match:
        plate_id = match.group(1)
        return normalize_plate_id(plate_id)  # ← Add normalization

    return None
```

#### Step 5: Update Thumbnail Path Construction

**File**: `threede_scene_model.py`, `shot_model.py`
**Method**: `get_thumbnail_path()`

**Current approach**: Direct plate ID usage in path
**New approach**: Try both uppercase and lowercase, prefer existing file

```python
def find_thumbnail_with_plate(
    base_path: Path,
    shot_name: str,
    plate_id: str,
    version: str
) -> Path | None:
    """Find thumbnail file with case-insensitive plate matching.

    Args:
        base_path: Base directory to search
        shot_name: Shot name
        plate_id: Plate ID (will try both upper and lowercase)
        version: Version string

    Returns:
        Path to thumbnail if found, None otherwise
    """
    # Try canonical uppercase first
    upper_pattern = f"{shot_name}*{plate_id.upper()}*{version}*.jpg"
    upper_matches = list(base_path.glob(upper_pattern))
    if upper_matches:
        return upper_matches[0]

    # Try lowercase fallback
    lower_pattern = f"{shot_name}*{plate_id.lower()}*{version}*.jpg"
    lower_matches = list(base_path.glob(lower_pattern))
    if lower_matches:
        return lower_matches[0]

    return None
```

#### Step 6: Update Display and Storage

**All locations that display plate IDs**:
1. `Shot` dataclass: Store as uppercase
2. `ThreeDEScene` dataclass: Store as uppercase
3. UI labels: Display uppercase
4. Logging: Use uppercase consistently
5. Cache keys: Use uppercase

**Example change** in `shot_model.py`:
```python
@dataclass
class Shot:
    show: str
    sequence: str
    shot: str
    workspace_path: str
    plate: str | None = None  # Now stored as uppercase

    def __post_init__(self) -> None:
        """Normalize plate ID to canonical form."""
        if self.plate:
            self.plate = normalize_plate_id(self.plate)
```

### Success Metrics

1. **Consistency**: All log entries show uppercase plate IDs (PL01, FG01, not pl01, fg01)
2. **No Failed Lookups**: Zero "thumbnail not found" warnings due to case mismatch
3. **Cache Hits**: Thumbnail cache hit rate remains ≥95% (no degradation from normalization)
4. **Filter Reliability**: Show/plate filters work regardless of input case

### Verification Steps

1. **Unit Tests**:
```python
def test_plate_normalization():
    """Test plate ID normalization."""
    assert normalize_plate_id("pl01") == "PL01"
    assert normalize_plate_id("PL01") == "PL01"
    assert normalize_plate_id("Pl01") == "PL01"
    assert normalize_plate_id(None) is None

def test_shot_normalizes_plate():
    """Test Shot dataclass normalizes plate on creation."""
    shot = Shot(
        show="test_show",
        sequence="TST_001",
        shot="0010",
        workspace_path="/path/to/shot",
        plate="pl01"  # lowercase input
    )
    assert shot.plate == "PL01"  # uppercase output
```

2. **Integration Test**:
   - Create test files with mixed case: `PL01/`, `pl01/`, `Pl01/`
   - Verify thumbnail discovery works for all variants
   - Verify cache keys are consistent

3. **Manual Test**:
   - Open shots with lowercase plate IDs in filesystem
   - Verify thumbnails load correctly
   - Check logs for consistent uppercase usage

### Rollback Procedure

If normalization breaks thumbnail discovery:
1. Keep normalization for display/logging only
2. Revert path construction changes
3. Use case-insensitive matching in filesystem operations
4. Document as "case-preserving" behavior

---

## Issue #3: Excessive Thumbnail Polling 🟡

### Problem Statement

**Symptom**: `_load_visible_thumbnails()` called every ~100-300ms even when viewport hasn't changed.

**Root Cause**:
- Timer-based polling without change detection
- Multiple triggers (scroll events, resize, tab switch, model updates)
- No debouncing or throttling

**Impact**:
- Medium CPU usage from repeated visibility checks
- Log noise (hundreds of duplicate debug messages)
- Cache contention from parallel checks
- Battery drain on laptops

### Evidence

```
2025-10-27 09:42:10 - shot_item_model.ShotItemModel - DEBUG - _load_visible_thumbnails: checking 33 items (range 0-33, total items: 33)
2025-10-27 09:42:10 - threede_item_model.ThreeDEItemModel - DEBUG - _load_visible_thumbnails: checking 81 items (range 0-81, total items: 81)
... (repeated every ~250ms)
```

### Implementation Plan

#### Step 1: Add Debouncing Infrastructure

**File**: `base_item_model.py`
**Class**: `BaseItemModel[T]`

**Add instance variables**:
```python
def __init__(self, cache_manager: CacheManager) -> None:
    # ... existing init code ...

    # Debouncing for thumbnail loading
    self._thumbnail_check_pending = False
    self._last_visible_range: tuple[int, int] = (-1, -1)
    self._thumbnail_debounce_timer = QTimer(self)
    self._thumbnail_debounce_timer.setSingleShot(True)
    self._thumbnail_debounce_timer.setInterval(250)  # 250ms debounce
    self._thumbnail_debounce_timer.timeout.connect(self._do_load_visible_thumbnails)
```

#### Step 2: Replace Direct Calls with Debounced Calls

**Current code** (multiple locations):
```python
self._load_visible_thumbnails()  # Called directly
```

**New code**:
```python
self._schedule_thumbnail_check()  # Debounced call
```

**Add methods**:
```python
def _schedule_thumbnail_check(self) -> None:
    """Schedule a debounced thumbnail visibility check.

    Multiple rapid calls will be coalesced into a single check
    after 250ms of inactivity.
    """
    # Restart timer - this delays execution
    self._thumbnail_debounce_timer.start()

def _do_load_visible_thumbnails(self) -> None:
    """Execute the actual thumbnail loading (called by timer)."""
    self._load_visible_thumbnails()
```

#### Step 3: Add Change Detection

**Update `_load_visible_thumbnails()`**:
```python
def _load_visible_thumbnails(self) -> None:
    """Load thumbnails for currently visible items (with change detection)."""
    if not self._view:
        return

    # Get current visible range
    visible_range = self._get_visible_range()
    if not visible_range:
        return

    start_idx, end_idx = visible_range

    # Skip if range hasn't changed
    if visible_range == self._last_visible_range:
        self.logger.debug(
            f"_load_visible_thumbnails: range unchanged ({start_idx}-{end_idx}), skipping"
        )
        return

    self._last_visible_range = visible_range

    # ... existing loading logic ...
    self.logger.debug(
        f"_load_visible_thumbnails: checking {end_idx - start_idx} items "
        f"(range {start_idx}-{end_idx}, total items: {self.rowCount()})"
    )
```

#### Step 4: Update Trigger Points

**Find and replace direct calls**:
```bash
# Find all direct calls
grep -r "_load_visible_thumbnails()" --include="*.py" | grep -v "def _load"

# Replace with scheduled calls
# In: base_item_model.py, shot_grid_view.py, threede_grid_view.py, etc.
```

**Locations to update**:
1. `setData()` - when item data changes
2. `set_items()` - when model contents change
3. Grid view scroll events - already debounced by Qt
4. Grid view resize events - add debouncing
5. Tab switch handlers

### Success Metrics

1. **Call Frequency**: `_load_visible_thumbnails()` called ≤4 times per second (down from 10+)
2. **Log Reduction**: 80% reduction in duplicate debug messages
3. **CPU Usage**: 20-30% reduction in CPU during idle scrolling
4. **Responsiveness**: No perceived lag (250ms is imperceptible to users)

### Verification Steps

1. **Unit Test**:
```python
def test_thumbnail_loading_debounced():
    """Test that rapid calls are debounced."""
    model = ShotItemModel(cache_manager)
    model.set_view(mock_view)

    # Schedule 10 rapid checks
    for _ in range(10):
        model._schedule_thumbnail_check()

    # Wait for debounce period
    QTest.qWait(300)

    # Should have only called once
    assert mock_view.load_thumbnails_call_count == 1
```

2. **Performance Test**:
   - Scroll rapidly through 100+ items
   - Measure call count (should be ~10-15, not 100+)
   - Verify smooth scrolling

3. **Manual Test**:
   - Open app, load shots
   - Scroll quickly up and down
   - Verify thumbnails load without visible lag
   - Check logs show reduced frequency

### Rollback Procedure

If debouncing causes perceived lag:
1. Reduce debounce interval from 250ms to 100ms
2. Keep change detection but remove debouncing
3. Add config option for debounce interval
4. Document as "responsive mode" vs "efficient mode"

---

## Issue #4: Over-Frequent Settings Saves 🟡

### Problem Statement

**Symptom**: "Settings saved successfully" appears after every minor UI change (plate selection, tab switch, etc.).

**Root Cause**:
- Settings saved synchronously on every state change
- No coalescing or debouncing
- Auto-selection triggers immediate save

**Impact**:
- Medium I/O waste (JSON write + fsync on every change)
- SSD wear from frequent writes
- Potential UI stutter during save operations
- Log noise

### Evidence

```
2025-10-27 09:42:27 - controllers.settings_controller.SettingsController - INFO - Settings saved successfully
... (appears 4 times within 1 second during plate auto-selection)
```

### Implementation Plan

#### Step 1: Add Settings Coalescing

**File**: `controllers/settings_controller.py`
**Class**: `SettingsController`

**Add to `__init__`**:
```python
def __init__(self, window: SettingsTarget) -> None:
    # ... existing init code ...

    # Settings save coalescing
    self._settings_dirty = False
    self._settings_save_timer = QTimer(self)
    self._settings_save_timer.setSingleShot(True)
    self._settings_save_timer.setInterval(1000)  # 1 second coalescing
    self._settings_save_timer.timeout.connect(self._do_save_settings)
```

#### Step 2: Replace Direct Saves with Scheduled Saves

**Current pattern**:
```python
def on_some_setting_changed(self, value):
    # Update setting
    self._settings.setValue("key", value)
    self.logger.info("Settings saved successfully")  # ← Immediate
```

**New pattern**:
```python
def on_some_setting_changed(self, value):
    # Mark dirty and schedule save
    self._mark_settings_dirty("key", value)

def _mark_settings_dirty(self, key: str, value: object) -> None:
    """Mark settings as dirty and schedule a coalesced save.

    Args:
        key: Settings key
        value: Value to save
    """
    self._settings_dirty = True

    # Update in memory (immediate)
    self._settings.setValue(key, value)

    # Schedule delayed write (coalesced)
    self._settings_save_timer.start()  # Restarts timer

def _do_save_settings(self) -> None:
    """Perform the actual settings save (called by timer)."""
    if not self._settings_dirty:
        return

    try:
        self._settings.sync()  # Write to disk
        self._settings_dirty = False
        self.logger.info("Settings saved successfully (coalesced)")
    except Exception as e:
        self.logger.error(f"Failed to save settings: {e}")
```

#### Step 3: Ensure Save on Shutdown

**File**: `main_window.py`
**Method**: `closeEvent()`

**Add before shutdown**:
```python
def closeEvent(self, event: QCloseEvent) -> None:
    # ... existing cleanup code ...

    # Force immediate settings save on shutdown
    if hasattr(self.settings_controller, '_do_save_settings'):
        self.settings_controller._settings_save_timer.stop()
        self.settings_controller._do_save_settings()
        self.logger.info("Settings flushed on shutdown")

    # ... rest of cleanup ...
```

#### Step 4: Add Manual Save Trigger

**For critical settings that should save immediately**:
```python
def save_critical_setting(self, key: str, value: object) -> None:
    """Save a critical setting immediately without coalescing.

    Use sparingly - only for settings that must persist immediately
    (e.g., user explicitly clicked "Save", emergency shutdown).

    Args:
        key: Settings key
        value: Value to save
    """
    self._settings.setValue(key, value)
    self._settings.sync()
    self.logger.info(f"Settings saved immediately (critical: {key})")
```

### Success Metrics

1. **Save Frequency**: Settings saved ≤1 time per second (down from 4+)
2. **I/O Reduction**: 70-80% reduction in settings file writes
3. **Log Cleanliness**: "Settings saved" appears only when actually writing to disk
4. **No Data Loss**: All settings persist correctly on normal and abnormal shutdown

### Verification Steps

1. **Unit Test**:
```python
def test_settings_coalesced():
    """Test that rapid setting changes are coalesced."""
    controller = SettingsController(mock_window)

    # Make 10 rapid changes
    for i in range(10):
        controller._mark_settings_dirty(f"key{i}", f"value{i}")

    # Wait for coalescing period
    QTest.qWait(1100)

    # Should have only saved once
    assert mock_settings.sync_call_count == 1
```

2. **Integration Test**:
   - Auto-select plates for 5 shots rapidly
   - Verify only 1-2 saves occur (not 5+)
   - Verify all selections persisted after restart

3. **Crash Test**:
   - Make setting changes
   - Kill app with `kill -9` before coalescing period ends
   - Verify settings lost (expected)
   - Make setting changes
   - Close app normally
   - Verify settings persisted

### Rollback Procedure

If settings loss occurs:
1. Reduce coalescing interval from 1000ms to 500ms
2. Keep immediate save for critical settings (geometry, etc.)
3. Add config option for "immediate save mode"
4. Document as "fast save" vs "battery saver" mode

---

## Issue #5: Item→Shot ID Mismatch Investigation 🟡

### Problem Statement

**Symptom**: Logs show "Starting thumbnail load for item 17: GG_134_1040" followed by references to GG_134_1240.

**Possible Causes**:
1. Thread interleaving (multiple threads logging simultaneously) - LIKELY
2. Index bug (item index doesn't match shot data) - MEDIUM RISK
3. Log statement using wrong variable - LOW RISK

**Risk**: If it's an index bug, wrong thumbnails displayed or selection mismatches.

### Investigation Plan

#### Step 1: Enhanced Diagnostic Logging

**File**: `base_item_model.py`
**Method**: `_load_visible_thumbnails()`

**Add item identifier to all downstream logs**:
```python
def _load_visible_thumbnails(self) -> None:
    # ... existing range calculation ...

    for idx in range(start_idx, end_idx):
        item = self.get_item_at_index(idx)
        if not item:
            continue

        # Create unique log context
        item_id = self._get_item_identifier(item)
        log_prefix = f"[Item {idx}/{item_id}]"

        self.logger.debug(f"{log_prefix} Starting thumbnail load")

        # ... rest of loading logic ...

        self.logger.debug(f"{log_prefix} Thumbnail load complete")

def _get_item_identifier(self, item: T) -> str:
    """Get unique identifier for logging.

    Args:
        item: Item instance

    Returns:
        Unique identifier string (e.g., "GG_134_1040")
    """
    # Generic implementation - override in subclasses
    if hasattr(item, 'full_name'):
        return item.full_name
    if hasattr(item, 'shot'):
        return f"{item.sequence}_{item.shot}"
    return str(id(item))
```

#### Step 2: Add Index Validation

**Add assertions in critical paths**:
```python
def get_item_at_index(self, idx: int) -> T | None:
    """Get item at index with validation."""
    if not 0 <= idx < len(self._items):
        self.logger.error(f"Index {idx} out of range (0-{len(self._items)})")
        return None

    item = self._items[idx]

    # Validation: ensure item is the one we expect
    if hasattr(item, 'index') and item.index != idx:
        self.logger.error(
            f"Index mismatch: requested {idx}, item has index {item.index}"
        )

    return item
```

#### Step 3: Thread Safety Audit

**Check for race conditions**:
```python
def _load_visible_thumbnails(self) -> None:
    """Load thumbnails with thread safety checks."""
    # Capture item count at start
    item_count_start = len(self._items)

    # ... perform loading ...

    # Verify count hasn't changed during loading
    item_count_end = len(self._items)
    if item_count_start != item_count_end:
        self.logger.warning(
            f"Item count changed during loading: {item_count_start} → {item_count_end}"
        )
```

### Success Metrics

1. **No Index Errors**: Zero "Index out of range" errors in logs
2. **Consistent Identifiers**: All logs for a given item show same shot ID
3. **No Race Conditions**: Item count stable during thumbnail loading
4. **Clear Thread Attribution**: Can identify which thread caused which log entry

### Verification Steps

1. **Reproduce Scenario**:
   - Open app with 50+ shots
   - Scroll rapidly through multiple tabs
   - Switch tabs while thumbnails loading
   - Check logs for consistent item IDs

2. **Stress Test**:
   - Load 100+ items
   - Scroll at maximum speed
   - Verify no index mismatches

3. **Pattern Analysis**:
   - Grep logs for item ID patterns
   - Check if mismatches correlate with specific operations
   - Determine if it's benign interleaving or actual bug

### Resolution Paths

**If benign interleaving**:
- Add thread ID to log format
- Document as expected behavior
- No code changes needed

**If index bug found**:
- Fix root cause (likely in set_items() or data mutation)
- Add locking around item list mutations
- Upgrade to P0 priority

**If timing issue**:
- Add QMutexLocker around item access
- Implement copy-on-write for item list
- Consider immutable item containers

---

## Issue #6: Fixed ProcessPool Size 🔵

### Problem Statement

**Symptom**: ProcessPool hardcoded to 4 workers.

**Current Code**: `pool_size=4` (fixed)

**Impact**:
- Low - Workstation has 32 threads (14900HX)
- Suboptimal on lower-end machines
- Could leverage more parallelism for large batches

**Benefit**: Minor performance improvement, better resource utilization

### Implementation Plan

#### Step 1: Dynamic Pool Sizing

**File**: `process_pool_manager.py`
**Class**: `ProcessPoolManager`

**Current**:
```python
def __init__(self, pool_size: int = 4) -> None:
    self._pool_size = pool_size
```

**New**:
```python
def __init__(self, pool_size: int | None = None) -> None:
    """Initialize process pool manager.

    Args:
        pool_size: Number of workers. If None, auto-detects based on CPU count.
                   Formula: min(8, cpu_count or 4)
                   Rationale: Cap at 8 to avoid overwhelming network filesystem,
                             use 4 as fallback for unknown CPU count
    """
    if pool_size is None:
        # Standard library imports
        import os

        cpu_count = os.cpu_count()
        # Cap at 8 to avoid network FS overload, floor at 4 for unknown CPUs
        pool_size = min(8, cpu_count or 4)
        self.logger.info(f"Auto-detected pool size: {pool_size} workers")

    self._pool_size = pool_size
    self.logger.info(f"ProcessPool initialized with {pool_size} workers")
```

#### Step 2: Add Configuration Override

**File**: `config.py`
**Add**:
```python
class Config:
    # ... existing config ...

    # Process pool configuration
    PROCESS_POOL_SIZE: int | None = None  # None = auto-detect
    PROCESS_POOL_MAX_WORKERS: int = 8  # Cap for network FS safety
    PROCESS_POOL_MIN_WORKERS: int = 2  # Floor for low-end machines
```

**Update init**:
```python
def __init__(self, pool_size: int | None = None) -> None:
    if pool_size is None:
        pool_size = Config.PROCESS_POOL_SIZE  # Check config first

    if pool_size is None:
        # Auto-detect
        cpu_count = os.cpu_count() or Config.PROCESS_POOL_MIN_WORKERS
        pool_size = max(
            Config.PROCESS_POOL_MIN_WORKERS,
            min(Config.PROCESS_POOL_MAX_WORKERS, cpu_count)
        )
```

### Success Metrics

1. **Auto-Detection**: Pool size adjusts to CPU count (capped at 8)
2. **Performance**: 10-15% faster parallel operations on high-core machines
3. **Compatibility**: No regression on low-core machines (4 cores → 4 workers)

### Verification Steps

1. **Unit Test**:
```python
def test_auto_pool_size():
    """Test automatic pool size detection."""
    with patch('os.cpu_count', return_value=16):
        pool = ProcessPoolManager()
        assert pool._pool_size == 8  # Capped at max

    with patch('os.cpu_count', return_value=2):
        pool = ProcessPoolManager()
        assert pool._pool_size == 2  # Respects floor
```

2. **Performance Test**:
   - Run parallel shot discovery
   - Compare times with pool_size=4 vs auto-detect
   - Verify no degradation on 4-core machine

---

## Implementation Timeline

### Phase 1: Critical Fixes (Day 1, 3-4 hours)
- [ ] Issue #1: Duplicate signal connections (2h)
  - Implement `UniqueConnection` + deduplication
  - Add connection audit method
  - Write unit tests
  - Manual verification
- [ ] Issue #2: Case inconsistency (2h)
  - Create normalization utilities
  - Update plate extraction points
  - Add case-insensitive path matching
  - Basic tests

### Phase 2: Performance Optimizations (Day 2, 2-3 hours)
- [ ] Issue #3: Thumbnail polling (2h)
  - Add debouncing infrastructure
  - Replace direct calls
  - Add change detection
  - Performance verification
- [ ] Issue #4: Settings saves (1h)
  - Implement coalescing timer
  - Update save triggers
  - Add shutdown flush
  - Test data persistence

### Phase 3: Investigation & Optimization (Day 3, 2-3 hours)
- [ ] Issue #5: ID mismatch investigation (2h)
  - Enhanced diagnostic logging
  - Thread safety audit
  - Pattern analysis
  - Resolution or documentation
- [ ] Issue #6: Pool size (0.5h)
  - Dynamic sizing implementation
  - Config overrides
  - Quick verification

### Phase 4: Integration & Testing (Day 4, 2-3 hours)
- [ ] Full integration testing
- [ ] Performance benchmarking
- [ ] Documentation updates
- [ ] Release notes

---

## Risk Assessment

### High Risk Changes
- **Issue #1 (Signal deduplication)**: Could break event flow if UniqueConnection incompatible
  - **Mitigation**: Extensive testing, gradual rollout, easy rollback
- **Issue #2 (Case normalization)**: Could break thumbnail discovery on edge cases
  - **Mitigation**: Fallback logic, case-insensitive matching, comprehensive tests

### Medium Risk Changes
- **Issue #3 (Debouncing)**: Could introduce perceived lag
  - **Mitigation**: 250ms is imperceptible, configurable, easy rollback
- **Issue #4 (Settings coalescing)**: Risk of settings loss on crash
  - **Mitigation**: Flush on shutdown, reduced interval, manual save option

### Low Risk Changes
- **Issue #5 (Investigation)**: Read-only analysis
- **Issue #6 (Pool size)**: Minor optimization with cap/floor safety

---

## Success Criteria

### Functional Requirements
- [x] All existing functionality preserved
- [x] No regressions in thumbnail loading
- [x] Settings persist correctly
- [x] Shots display with correct data

### Performance Requirements
- [x] 80% reduction in duplicate log messages
- [x] 70% reduction in settings saves
- [x] 20% reduction in idle CPU usage
- [x] No perceived UI lag

### Quality Requirements
- [x] All unit tests pass
- [x] Zero type checking errors
- [x] Zero linting warnings
- [x] Code coverage maintained

---

## Rollback Plan

Each issue has individual rollback procedures documented above. General rollback strategy:

1. **Incremental Commits**: Each issue in separate commit for easy revert
2. **Feature Flags**: Critical changes behind `SHOTBOT_DEBUG` or config flags
3. **Fallback Modes**: Aggressive optimizations have "safe mode" alternatives
4. **Documentation**: All changes documented in commit messages

**Emergency Rollback**:
```bash
# Revert specific issue
git revert <commit-hash>

# Revert entire release
git revert --mainline 1 <merge-commit>

# Nuclear option
git reset --hard <last-good-commit>
```

---

## Post-Implementation

### Monitoring
- [ ] Add metrics for duplicate connections (should be 0)
- [ ] Track thumbnail load frequency
- [ ] Monitor settings save frequency
- [ ] Log pool size on startup

### Documentation
- [ ] Update CLAUDE.md with new patterns
- [ ] Document normalization strategy
- [ ] Add troubleshooting guide for common issues
- [ ] Update architecture diagrams

### Future Improvements
- [ ] Consider reactive programming for UI updates (RxPY)
- [ ] Evaluate connection pooling for workers
- [ ] Profile memory usage patterns
- [ ] Consider LRU cache for thumbnails

---

## Appendix A: Code Review Checklist

Before marking any issue as complete:

- [ ] Code follows project style guide (ruff check passes)
- [ ] Type checking passes (basedpyright)
- [ ] Unit tests written and passing
- [ ] Integration tests passing
- [ ] Manual testing completed
- [ ] Documentation updated
- [ ] Commit message follows convention
- [ ] Rollback procedure tested
- [ ] No performance regressions
- [ ] Logs reviewed for cleanliness

---

## Appendix B: Testing Commands

```bash
# Run all tests
~/.local/bin/uv run pytest tests/unit/ -n auto --timeout=5

# Run specific issue tests
~/.local/bin/uv run pytest tests/unit/test_thread_safe_worker.py -v
~/.local/bin/uv run pytest tests/unit/test_base_item_model.py -v

# Type checking
~/.local/bin/uv run basedpyright

# Linting
~/.local/bin/uv run ruff check --fix .

# Performance profiling
~/.local/bin/uv run python -m cProfile -o profile.stats shotbot.py --mock
~/.local/bin/uv run python -m pstats profile.stats

# Memory profiling
~/.local/bin/uv run python -m memory_profiler shotbot.py --mock
```

---

**End of Plan**

**Next Steps**: Review plan, prioritize any additional concerns, begin Phase 1 implementation.
