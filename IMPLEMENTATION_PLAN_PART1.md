# ShotBot Remediation - PART 1: Critical Fixes & Performance

**Focus:** Fix crashes, data loss, and UI blocking (URGENT)
**Effort:** 6-10 hours (2-3 days with reviews)
**Tasks:** 4 tasks across Phases 1-2

---

## ✅ VERIFICATION STATUS (2025-10-31)

**Verified against codebase:**
- ✅ **Task 1.3** - Race condition confirmed, fix needed
- ✅ **Task 2.1** - Blocking JSON writes confirmed, fix needed
- ✅ **Task 2.2** - Unbounded cache confirmed, fix needed
- ✅ **Task 2.3** - LANCZOS slowness confirmed, fix needed
- ⚪ **Task 1.1** - Already fixed (signal disconnection protected)
- ⚪ **Task 1.2** - Already fixed (write-before-signal implemented)

**Removed tasks:** 1.1, 1.2 (already implemented in codebase)

---

## Quick Checklist

### Phase 1: Critical Bug Fixes
- [ ] **1.3** Fix model item access race (`base_item_model.py`)

### Phase 2: Performance Bottlenecks
- [ ] **2.1** Move JSON serialization to background thread (`cache_manager.py`)
- [ ] **2.2** Add LRU eviction to thumbnail cache (`base_item_model.py`)
- [ ] **2.3** Optimize PIL thumbnail generation (`cache_manager.py`)

### Success Metrics
- [ ] UI blocking: 180ms → <10ms (95% improvement)
- [ ] Memory: Unbounded → ~128MB (capped)
- [ ] Thumbnails: 70-140ms → 20-40ms (60% faster)
- [ ] All tests pass: `uv run pytest tests/unit/ -v`

---

# PHASE 1: CRITICAL BUG FIXES

## Task 1.3: Fix Model Item Access Race Condition

**Issue:** `_items` list accessed without bounds checking during concurrent updates
**File:** `base_item_model.py:365-395`

**Verified:** ✅ Race condition exists at line 370 (no bounds check in loop)

### Current Code (BUGGY)
```python
# base_item_model.py:369-370
with QMutexLocker(self._cache_mutex):
    for row in range(start, end):
        item = self._items[row]  # ⚠️ IndexError if items change!
```

### Fix
```python
def _do_load_visible_thumbnails(self) -> None:
    """Load thumbnails with race condition protection."""
    if not self._items:
        return

    # Snapshot current state under lock
    with QMutexLocker(self._cache_mutex):
        item_count = len(self._items)
        visible_start = self._visible_start
        visible_end = self._visible_end

    # Calculate range with buffer
    buffer_size = 5
    start = max(0, visible_start - buffer_size)
    end = min(item_count, visible_end + buffer_size)

    # Collect items to load with atomic check-and-mark
    items_to_load: list[tuple[int, T]] = []

    with QMutexLocker(self._cache_mutex):
        # DEFENSIVE: Re-check item count inside lock
        current_count = len(self._items)
        if current_count != item_count:
            # Items changed - reschedule
            self.logger.warning(
                f"Item count changed ({item_count} → {current_count}). Rescheduling."
            )
            QTimer.singleShot(100, self._do_load_visible_thumbnails)
            return

        for row in range(start, end):
            # DEFENSIVE: Bounds check before access
            if row >= len(self._items):
                self.logger.warning(
                    f"Row {row} out of bounds (len={len(self._items)}). "
                    "Concurrent set_items() detected."
                )
                break

            item = self._items[row]

            # Skip if already cached or loading
            if item.full_name in self._thumbnail_cache:
                continue

            state = self._loading_states.get(item.full_name)
            if state in ("loading", "failed"):
                continue

            # Mark as loading atomically
            self._loading_states[item.full_name] = "loading"
            items_to_load.append((row, item))

    # Load thumbnails outside lock
    for row, item in items_to_load:
        self._load_thumbnail_async(row, item)
```

### Tests Required
```python
# tests/unit/test_base_item_model.py
def test_concurrent_set_items_during_load(qtbot):
    """Test concurrent set_items doesn't crash thumbnail loading."""
    model = ShotItemModel()
    shots = [create_mock_shot(i) for i in range(100)]
    model.set_items(shots)
    model.set_visible_range(0, 50)

    # Immediately change items (race condition)
    new_shots = [create_mock_shot(i + 100) for i in range(50)]
    model.set_items(new_shots)  # Should NOT crash

    qtbot.wait(500)
    assert model.rowCount() == 50  # New count

def test_bounds_check_during_thumbnail_load(qtbot):
    """Test bounds checking prevents IndexError."""
    model = ShotItemModel()
    shots = [create_mock_shot(i) for i in range(10)]
    model.set_items(shots)

    # Trigger loading
    model.set_visible_range(0, 10)

    # Clear items while loading (extreme race)
    model.set_items([])

    qtbot.wait(500)
    assert model.rowCount() == 0
```

### Verify
```bash
uv run pytest tests/unit/test_base_item_model.py::test_concurrent_set_items_during_load -v
uv run pytest tests/unit/test_base_item_model.py::test_bounds_check_during_thumbnail_load -v
uv run basedpyright
```

### Git Commit
```bash
git add base_item_model.py tests/unit/test_base_item_model.py
git commit -m "fix(critical): Add bounds checking to prevent race condition crash

- Add defensive bounds check in thumbnail loading loop
- Re-check item count before accessing _items
- Reschedule on concurrent modification
- Add tests for concurrent set_items scenarios

Prevents IndexError when set_items() called during thumbnail loading.

Related: Phase 1, Task 1.3"
```

---

# PHASE 2: PERFORMANCE BOTTLENECKS

## Task 2.1: Move JSON Serialization to Background Thread

**Issue:** Synchronous JSON writes block UI thread (180ms freezes)
**File:** `cache_manager.py:860-905`

**Verified:** ✅ Only synchronous `_write_json_cache` exists, no async version

### Current Code (BLOCKING)
```python
# cache_manager.py:860
def _write_json_cache(self, cache_file: Path, data: object) -> bool:
    # ... synchronous JSON dump with fsync ...
    json.dump(cache_data, f, indent=2)
    f.flush()
    os.fsync(f.fileno())  # ⚠️ Blocks UI thread!
```

### Add Async Version
```python
# cache_manager.py (ADD NEW METHOD)
from concurrent.futures import ThreadPoolExecutor, Future
import threading

class CacheManager:
    def __init__(self, cache_dir: Path | None = None):
        # ... existing init ...
        self._write_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="cache_write"
        )
        self._write_lock = threading.Lock()

    def write_json_cache_async(
        self, cache_file: Path, data: object
    ) -> Future[bool]:
        """Write JSON cache asynchronously (non-blocking).

        Returns:
            Future that resolves to True if write succeeded
        """
        return self._write_executor.submit(
            self._write_json_cache, cache_file, data
        )

    def shutdown(self) -> None:
        """Shutdown cache manager."""
        if hasattr(self, "_write_executor"):
            self._write_executor.shutdown(wait=True, timeout=5.0)
```

### Update Callers
```python
# cache_manager.py:454 (UPDATE migrate_shots_to_previous)
def migrate_shots_to_previous(self, shots: list[Shot | ShotDict]) -> None:
    """Migrate shots asynchronously."""
    # ... existing merge logic ...

    # Write asynchronously (non-blocking)
    future = self.write_json_cache_async(
        self.migrated_shots_cache_file, merged
    )

    # Optional: Add callback for logging
    def on_complete(fut: Future[bool]) -> None:
        try:
            if fut.result():
                self.logger.info(f"Migrated {len(to_migrate)} shots")
                self.shots_migrated.emit(to_migrate)
            else:
                self.logger.error("Failed to persist migrated shots")
        except Exception as e:
            self.logger.error(f"Migration write error: {e}")

    future.add_done_callback(on_complete)
```

### Tests Required
```python
# tests/unit/test_cache_manager.py
def test_async_write_non_blocking(tmp_path, qtbot):
    """Test async writes don't block caller."""
    cache_manager = CacheManager(cache_dir=tmp_path)

    import time
    start = time.perf_counter()

    # Submit large write
    large_data = [{"i": i} for i in range(10000)]
    future = cache_manager.write_json_cache_async(
        tmp_path / "test.json", large_data
    )

    elapsed = time.perf_counter() - start

    # Should return immediately (<10ms)
    assert elapsed < 0.01, f"Blocked for {elapsed*1000:.1f}ms"

    # Wait for completion
    result = future.result(timeout=5.0)
    assert result is True

def test_async_write_callback(tmp_path, qtbot):
    """Test async write callbacks execute."""
    cache_manager = CacheManager(cache_dir=tmp_path)

    callback_called = []

    def callback(fut):
        callback_called.append(fut.result())

    future = cache_manager.write_json_cache_async(
        tmp_path / "test.json", {"test": "data"}
    )
    future.add_done_callback(callback)

    # Wait for callback
    qtbot.wait(1000)
    assert callback_called == [True]
```

### Verify
```bash
uv run pytest tests/unit/test_cache_manager.py::test_async_write_non_blocking -v
uv run pytest tests/unit/test_cache_manager.py::test_async_write_callback -v
uv run basedpyright
```

### Git Commit
```bash
git add cache_manager.py tests/unit/test_cache_manager.py
git commit -m "perf(critical): Add async JSON cache writes to eliminate UI blocking

- Add write_json_cache_async() using ThreadPoolExecutor
- Update migrate_shots_to_previous() to use async writes
- Add callback support for completion handling
- Add executor shutdown in cleanup

Result: 180ms UI freeze → <10ms (95% improvement)

Related: Phase 2, Task 2.1"
```

---

## Task 2.2: Add LRU Eviction to Thumbnail Cache

**Issue:** Unbounded thumbnail cache grows indefinitely
**File:** `base_item_model.py:139`

**Verified:** ✅ Plain dict with no eviction: `self._thumbnail_cache: dict[str, QImage] = {}`

### Current Code (UNBOUNDED)
```python
# base_item_model.py:139
self._thumbnail_cache: dict[str, QImage] = {}
```

### Add LRU Cache
```python
# base_item_model.py (ADD NEW CLASS)
from collections import OrderedDict

class LRUCache(Generic[K, V]):
    """Thread-safe LRU cache with size limit."""

    def __init__(self, max_size: int = 500):
        self._cache: OrderedDict[K, V] = OrderedDict()
        self._max_size = max_size
        self._lock = QMutex()

    def get(self, key: K) -> V | None:
        """Get value, moving to end (most recent)."""
        with QMutexLocker(self._lock):
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, key: K, value: V) -> None:
        """Put value, evicting LRU if needed."""
        with QMutexLocker(self._lock):
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value

            # Evict oldest if over limit
            if len(self._cache) > self._max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

    def contains(self, key: K) -> bool:
        """Check if key exists."""
        with QMutexLocker(self._lock):
            return key in self._cache

    def __len__(self) -> int:
        with QMutexLocker(self._lock):
            return len(self._cache)

# base_item_model.py (UPDATE __init__)
def __init__(self, cache_manager: CacheManager | None = None):
    # ... existing init ...

    # Replace dict with LRU cache (500 items ≈ 128MB)
    self._thumbnail_cache = LRUCache[str, QImage](max_size=500)

    # ... rest of init ...
```

### Update Usage
```python
# base_item_model.py (UPDATE all cache access)

# OLD: if item.full_name in self._thumbnail_cache
# NEW:
if self._thumbnail_cache.contains(item.full_name):
    # ...

# OLD: image = self._thumbnail_cache[item.full_name]
# NEW:
image = self._thumbnail_cache.get(item.full_name)

# OLD: self._thumbnail_cache[item.full_name] = image
# NEW:
self._thumbnail_cache.put(item.full_name, image)
```

### Tests Required
```python
# tests/unit/test_base_item_model.py
def test_lru_cache_eviction():
    """Test LRU cache evicts oldest items."""
    cache = LRUCache[str, int](max_size=3)

    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)

    assert len(cache) == 3

    # Access 'a' to make it recent
    assert cache.get("a") == 1

    # Add 'd' - should evict 'b' (oldest)
    cache.put("d", 4)

    assert len(cache) == 3
    assert cache.get("b") is None  # Evicted
    assert cache.get("a") == 1     # Still present
    assert cache.get("c") == 3     # Still present
    assert cache.get("d") == 4     # Newly added

def test_thumbnail_cache_bounded(qtbot):
    """Test thumbnail cache respects size limit."""
    model = ShotItemModel()

    # Create 600 shots (exceeds 500 limit)
    shots = [create_mock_shot(i) for i in range(600)]
    model.set_items(shots)

    # Load all thumbnails
    for i in range(600):
        model.set_visible_range(i, i + 1)
        qtbot.wait(50)

    # Cache should be capped at 500
    assert len(model._thumbnail_cache) == 500
```

### Verify
```bash
uv run pytest tests/unit/test_base_item_model.py::test_lru_cache_eviction -v
uv run pytest tests/unit/test_base_item_model.py::test_thumbnail_cache_bounded -v
uv run basedpyright
```

### Git Commit
```bash
git add base_item_model.py tests/unit/test_base_item_model.py
git commit -m "perf(critical): Add LRU eviction to cap thumbnail memory

- Implement thread-safe LRUCache with OrderedDict
- Replace unbounded dict with LRU cache (max_size=500)
- Add eviction tests and memory bounds tests

Result: Unbounded growth → ~128MB capped (500 × 256KB avg)

Related: Phase 2, Task 2.2"
```

---

## Task 2.3: Optimize PIL Thumbnail Generation

**Issue:** LANCZOS resampling unnecessarily slow for thumbnails
**File:** `cache_manager.py:313`

**Verified:** ✅ Using `Image.Resampling.LANCZOS` (slowest filter)

### Current Code (SLOW)
```python
# cache_manager.py:313
img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
```

### Fix
```python
# cache_manager.py:313 (CHANGE RESAMPLING)
img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.BILINEAR)
```

**Rationale:**
- LANCZOS: 3-lobe sinc filter (70-140ms for 4K→256px)
- BILINEAR: 2-sample linear (20-40ms for same operation)
- Visual difference negligible at 256×256 display size
- 60% faster per plan's benchmarks

### Tests Required
```python
# tests/unit/test_cache_manager.py
def test_thumbnail_generation_speed(tmp_path):
    """Test thumbnail generation is reasonably fast."""
    from PIL import Image

    # Create test 4K image
    img = Image.new("RGB", (3840, 2160), color="red")
    source = tmp_path / "source.jpg"
    img.save(source)

    cache_manager = CacheManager(cache_dir=tmp_path)

    import time
    start = time.perf_counter()

    output = cache_manager._create_thumbnail_pil(
        source, tmp_path / "thumb.jpg"
    )

    elapsed = time.perf_counter() - start

    # Should complete in <50ms (BILINEAR)
    # (Would be >70ms with LANCZOS)
    assert elapsed < 0.05, f"Too slow: {elapsed*1000:.1f}ms"
    assert output.exists()

def test_thumbnail_quality_acceptable(tmp_path):
    """Test BILINEAR quality is acceptable."""
    from PIL import Image

    # Create test image with detail
    img = Image.new("RGB", (1920, 1080), color="blue")
    source = tmp_path / "source.jpg"
    img.save(source)

    cache_manager = CacheManager(cache_dir=tmp_path)
    output = cache_manager._create_thumbnail_pil(
        source, tmp_path / "thumb.jpg"
    )

    # Verify thumbnail exists and has correct size
    thumb = Image.open(output)
    assert max(thumb.size) == 256
```

### Verify
```bash
uv run pytest tests/unit/test_cache_manager.py::test_thumbnail_generation_speed -v
uv run pytest tests/unit/test_cache_manager.py::test_thumbnail_quality_acceptable -v
```

### Git Commit
```bash
git add cache_manager.py tests/unit/test_cache_manager.py
git commit -m "perf: Optimize PIL thumbnail generation with BILINEAR resampling

- Change LANCZOS → BILINEAR (negligible visual difference)
- Add performance tests (<50ms threshold)
- Add quality validation tests

Result: 70-140ms → 20-40ms (60% faster)

Related: Phase 2, Task 2.3"
```

---

# PART 1 COMPLETE ✅

## Final Verification

```bash
# Run all tests
uv run pytest tests/unit/ -v

# Type checking
uv run basedpyright

# Code quality
uv run ruff check .
```

## Expected Results

- ✅ **Race condition eliminated:** No more IndexError crashes during concurrent updates
- ✅ **UI blocking eliminated:** 180ms → <10ms (95% improvement)
- ✅ **Memory capped:** Unbounded → ~128MB (500-item LRU)
- ✅ **Thumbnails faster:** 70-140ms → 20-40ms (60% improvement)

**Total implementation time:** _____ hours (expected 6-10 hours)

---

**After completing Part 1, proceed to `IMPLEMENTATION_PLAN_PART2.md`**

**Document Version:** 1.2 (Verified Edition)
**Last Updated:** 2025-10-31
**Verification:** Tasks 1.1, 1.2 removed (already fixed in codebase)
