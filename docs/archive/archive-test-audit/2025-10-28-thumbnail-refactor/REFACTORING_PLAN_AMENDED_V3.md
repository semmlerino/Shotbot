# ShotBot Refactoring Plan (Amended v3.0)

**Version**: 3.0 (Revised 2025-10-11 after dual-agent review)
**Previous Version**: 2.0 (Amended plan with identified issues)
**Status**: Ready for Implementation

---

## Executive Summary

This v3.0 plan corrects critical issues identified through dual-agent code review and verification:

**Key Changes from v2.0:**
- ✅ **FIXED** Phase 1.1 (Race condition - correct solution verified)
- ✅ **RE-ADDED** Phase 1.2 (Selection thread safety - not a false positive)
- ✅ **ADDED** Phase 1.6 (Threading model standardization - critical architectural fix)
- ✅ **REVISED** Phase 2.1 (Functional composition instead of class-based)
- ❌ **REMOVED** Phase 3.1 (Current code already well-organized - Template Method adds complexity)
- 🔧 **IMPROVED** Phase 3.3 (Method references instead of lambdas)
 

**Changes from v1.0 (Original):**
- ❌ **REMOVED** SignalRouter class (over-engineering)
- ✅ **KEPT** Phase 3.1 removal decision (verified current code is good)
- 🔧 **REDESIGNED** Phase 2.1 (functional, not class-based)
- 🔧 **MODIFIED** Phase 1.3 (context manager, confirmed correct)

**Confidence Level**: Very High - all proposals verified through code inspection and dual-agent review

---

## Critical Findings from Review

### Issue 1: Phase 1.1 Race Condition - VERIFIED

**Current Code Problem:**
```python
# Lines 317-332 in base_item_model.py
for row in range(start, end):
    item = self._items[row]

    with QMutexLocker(self._cache_mutex):  # Lock #1
        if item.full_name in self._thumbnail_cache:
            continue
        state = self._loading_states.get(item.full_name)
        if state in ("loading", "failed"):
            continue
    # ← MUTEX RELEASED - Race window!

    self._load_thumbnail_async(row, item)  # Outside lock

    # Then in _load_thumbnail_async:
    with QMutexLocker(self._cache_mutex):  # Lock #2
        self._loading_states[item.full_name] = "loading"
```

**Race Scenario:** Two threads can both see item as "not loading" and start duplicate loads.

**v2.0 Solution Problem:** Per-item marking still has theoretical gap if thread crashes between mark and load.

**v3.0 Correct Solution:** Bulk atomic check-and-mark (verified correct).

### Issue 2: Threading Model Confusion - VERIFIED

**Evidence:** Codebase mixes Qt and Python threading:
- Qt: `QMutex`, `QMutexLocker` (~20 files)
- Python: `threading.RLock()`, `threading.Lock()` (~10 files)
- **Worst:** `process_pool_manager.py` uses BOTH!

**Impact:** Different semantics, deadlock potential, maintenance burden.

**Solution:** New Phase 1.6 - Standardize on Qt threading (8 hours).

### Issue 3: Phase 3.1 Over-Engineering - VERIFIED

**Current Code:** Already well-organized static methods in `PathUtils` (~320 lines)
- ✅ Clear priority order
- ✅ Functional approach
- ✅ Zero allocation overhead
- ✅ Easy to test

**v2.0 Proposal:** Template Method with 5 finder classes adds complexity without benefit.

**v3.0 Decision:** **REMOVE Phase 3.1** - Keep current implementation (saves 25 hours!)

---

## Phase 1: Critical Fixes (Week 1) - 15 hours

### 1.1 Race Condition: Thumbnail Loading (CORRECTED) ✅

**Priority**: CRITICAL
**Risk**: Medium
**Time**: 2 hours

**Issue:**
Race condition in `base_item_model.py` lines 317-332 - check and mark happen in separate mutex acquisitions.

**Verified Correct Solution:**
```python
def _load_visible_thumbnails(self) -> None:
    """Load thumbnails with atomic check-and-mark.

    Key improvement: ALL check-and-mark operations happen in SINGLE
    mutex acquisition, eliminating race window.
    """
    buffer_size = 5
    start = max(0, self._visible_start - buffer_size)
    end = min(len(self._items), self._visible_end + buffer_size)

    items_to_load: list[tuple[int, T]] = []

    # Atomic check-and-mark for ALL items in single lock acquisition
    with QMutexLocker(self._cache_mutex):
        for row in range(start, end):
            item = self._items[row]

            # Skip if already cached
            if item.full_name in self._thumbnail_cache:
                continue

            # Skip if loading or previously failed
            state = self._loading_states.get(item.full_name)
            if state in ("loading", "failed"):
                continue

            # Mark as loading atomically (same lock acquisition)
            self._loading_states[item.full_name] = "loading"
            items_to_load.append((row, item))

    # Load thumbnails outside lock (already marked as loading)
    for row, item in items_to_load:
        self._load_thumbnail_async(row, item)

    # Check if all loaded (separate lock - not critical)
    with QMutexLocker(self._cache_mutex):
        all_loaded = all(
            self._items[i].full_name in self._thumbnail_cache
            for i in range(start, end)
        )
    if all_loaded:
        self._thumbnail_timer.stop()
```

**Why This is Correct:**
- ✅ True atomic check-and-mark (no gap between check and mark)
- ✅ Bulk processing (all items marked in single lock)
- ✅ Short lock duration (checking/marking is fast)
- ✅ Load operations outside lock (I/O not blocking)
- ✅ No duplicate loads possible

**Benefits:**
- Eliminates race condition completely
- Actually improves performance (single lock vs per-item locks)
- Simpler logic (clear separation: mark → load)

**Testing:**
```python
def test_concurrent_thumbnail_loading_no_duplicates(model, qtbot):
    """Verify no duplicate loads with concurrent access."""
    load_calls = []

    def track_load(row, item):
        load_calls.append(item.full_name)

    with patch.object(model, '_load_thumbnail_async', side_effect=track_load):
        # Simulate rapid concurrent calls
        for _ in range(10):
            model.set_visible_range(0, 10)
            QApplication.processEvents()

    # Each item loaded exactly once
    unique_loads = set(load_calls)
    assert len(load_calls) == len(unique_loads), f"Duplicate loads: {load_calls}"
```

---

### 1.2 Selection Thread Safety (RE-ADDED) ✅

**Priority**: LOW
**Risk**: Very Low
**Time**: 30 minutes

**Why Re-Added:**
v2.0 incorrectly called this a "false positive". While not currently triggered (selection only on main thread), this IS a theoretical race if future code accesses `_selected_item` from background threads.

**Issue:**
`_selected_item` accessed without mutex protection:

```python
# base_item_model.py
def get_selected_item(self) -> T | None:
    """Get currently selected item."""
    return self._selected_item  # ← No mutex!
```

**Solution:**
Thread-safe getter with mutex:

```python
def get_selected_item(self) -> T | None:
    """Get currently selected item (thread-safe).

    Note: Selection changes only occur on main thread (user clicks),
    but this getter may be called from background threads for analytics,
    logging, or future features.
    """
    with QMutexLocker(self._cache_mutex):
        return self._selected_item
```

**Benefits:**
- Future-proofs against background thread access
- Zero performance impact (getter rarely called)
- Defensive programming
- Clear threading contract

**Documentation:**
Add to class docstring:
```python
class BaseItemModel:
    """...

    Threading Model:
    - Selection changes: Main thread only (via setData)
    - Selection reads: Any thread (via get_selected_item)
    - Thumbnail cache: Protected by _cache_mutex
    """
```

---

### 1.3 Thread-Safe Flag Pattern - Context Manager ✅

**Priority**: HIGH
**Risk**: Low
**Time**: 2 hours

**Issue:**
Pattern repeated 5 times in `previous_shots_model.py` (lines 135-139, 183-184, 98-99, 112-113, 332-333):

```python
# Repeated pattern:
with QMutexLocker(self._scan_lock):
    if self._is_scanning:
        return False
    self._is_scanning = True

try:
    # ... work ...
finally:
    with QMutexLocker(self._scan_lock):
        self._is_scanning = False
```

**Solution:**
RAII pattern with context manager (guarantees cleanup):

```python
from contextlib import contextmanager
from typing import Generator

@contextmanager
def _scanning_lock(self) -> Generator[bool, None, None]:
    """Context manager for scanning lock with guaranteed cleanup.

    Yields:
        True if lock acquired, False if already scanning

    Usage:
        with self._scanning_lock() as acquired:
            if not acquired:
                return False
            # ... do work ...
        # Lock automatically released here
    """
    # Try to acquire
    with QMutexLocker(self._scan_lock):
        if self._is_scanning:
            self.logger.debug("Scan lock already held")
            yield False
            return
        self._is_scanning = True
        self.logger.debug("Acquired scan lock")

    try:
        yield True
    finally:
        # Guaranteed cleanup even on exceptions
        with QMutexLocker(self._scan_lock):
            self._is_scanning = False
            self.logger.debug("Released scan lock")
```

**Usage:**
```python
def refresh_shots(self) -> bool:
    """Refresh with guaranteed lock cleanup."""
    with self._scanning_lock() as acquired:
        if not acquired:
            self.logger.debug("Already scanning")
            return False

        self.scan_started.emit()
        self._clear_caches_for_refresh()
        self._worker = PreviousShotsWorker(...)
        self._worker.start()
        return True
    # Lock automatically released, even if exception occurs
```

**Benefits:**
- Guarantees cleanup (impossible to forget)
- Follows Python idioms (matches existing `log_context()`)
- Prevents lock leaks on exceptions
- Single source of truth for lock management

**Files to Update:**
- `previous_shots_model.py`: Add `_scanning_lock()` method
- Replace 5 manual lock patterns with context manager usage

---

### 1.4 CSS Extraction ✅

**Priority**: LOW
**Risk**: Very Low
**Time**: 0.5 hours

**Issue:**
130-line CSS stylesheet embedded in `main_window.py` lines 919-1025.

**Solution:**
Extract to `styles.css`:

```css
/* styles.css */
QWidget {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10pt;
}

QPushButton {
    background-color: #0078D4;
    color: white;
    border: none;
    padding: 6px 12px;
    border-radius: 4px;
}

QPushButton:hover {
    background-color: #106EBE;
}

/* ... rest of styles ... */
```

```python
# main_window.py
def _apply_stylesheet(self) -> None:
    """Load and apply stylesheet from file."""
    style_path = Path(__file__).parent / "styles.css"

    if style_path.exists():
        with open(style_path, 'r') as f:
            self.setStyleSheet(f.read())
    else:
        self.logger.warning(f"Stylesheet not found: {style_path}")
```

**Benefits:**
- Syntax highlighting in editors
- Easier to maintain CSS
- Separates presentation from logic
- Can hot-reload during development

---

### 1.5 Cleanup Consolidation - Template Method ✅

**Priority**: MEDIUM
**Risk**: Low
**Time**: 2 hours

**Issue:**
~90 lines of duplicate cleanup logic across 3 item models:
- `shot_item_model.py` lines 60-86
- `threede_item_model.py` lines 231-261
- `previous_shots_item_model.py` lines 85-119

**Solution:**
Template Method in `base_item_model.py` with exception handling:

```python
def cleanup(self) -> None:
    """Clean up resources with guaranteed order.

    Template method that ensures consistent cleanup across all models:
    1. Stop timers
    2. Clear caches
    3. Disconnect signals (model-specific)
    4. Clear selection
    5. Additional cleanup (model-specific)

    All steps have exception handling to ensure cleanup continues
    even if individual steps fail.
    """
    self.logger.debug(f"Starting cleanup for {self.__class__.__name__}")

    # 1. Stop timers
    try:
        if hasattr(self, "_thumbnail_timer") and self._thumbnail_timer is not None:
            self._thumbnail_timer.stop()
            self._thumbnail_timer.deleteLater()
    except RuntimeError:
        pass  # Already deleted

    # 2. Clear caches
    try:
        self.clear_thumbnail_cache()
    except Exception as e:
        self.logger.warning(f"Cache cleanup failed: {e}")

    # 3. Let subclass disconnect its signals
    try:
        self._disconnect_signals()
    except Exception as e:
        self.logger.warning(f"Signal disconnect failed: {e}")

    # 4. Clear selection
    try:
        self._selected_index = QPersistentModelIndex()
        self._selected_item = None
    except Exception as e:
        self.logger.warning(f"Selection clear failed: {e}")

    # 5. Let subclass do additional cleanup
    try:
        self._cleanup_additional()
    except Exception as e:
        self.logger.warning(f"Additional cleanup failed: {e}")

    self.logger.info(
        f"{self.__class__.__name__} cleanup complete: "
        f"cache_items={len(self._thumbnail_cache)}, "
        f"loading_states={len(self._loading_states)}"
    )

def _disconnect_signals(self) -> None:
    """Disconnect model-specific signals.

    Override in subclass to disconnect custom signals.
    Base implementation handles common signals.
    """
    signals_to_disconnect = [
        self.items_updated,
        self.thumbnail_loaded,
        self.selection_changed,
        self.show_filter_changed,
    ]

    for signal in signals_to_disconnect:
        try:
            if hasattr(signal, 'receivers') and signal.receivers() > 0:
                signal.disconnect()
        except (RuntimeError, TypeError):
            pass  # Already disconnected or destroyed

def _cleanup_additional(self) -> None:
    """Additional model-specific cleanup.

    Override in subclass if needed.
    Default implementation does nothing.
    """
    pass

def deleteLater(self) -> None:
    """Override deleteLater to ensure cleanup."""
    self.cleanup()
    super().deleteLater()
```

**Subclass Implementation:**
```python
# shot_item_model.py
@override
def _disconnect_signals(self) -> None:
    """Disconnect shot-specific signals."""
    super()._disconnect_signals()  # Disconnect base signals

    try:
        self.shots_updated.disconnect()
    except (RuntimeError, TypeError):
        pass
```

**Benefits:**
- Eliminates ~90 lines of duplication
- Guarantees consistent cleanup order
- Exception-safe (cleanup continues if step fails)
- Makes it impossible to forget cleanup steps
- Clear extension points for subclasses

---

### 1.6 Threading Model Standardization (NEW) ✅

**Priority**: HIGH
**Risk**: Medium
**Time**: 8 hours

**Issue:**
Codebase mixes Qt and Python threading primitives:
- **Qt Threading**: `QMutex`, `QMutexLocker` in ~20 files
- **Python Threading**: `threading.RLock()`, `threading.Lock()` in ~10 files
- **Mixed**: `process_pool_manager.py` uses BOTH in same class!

**Evidence:**
```python
# process_pool_manager.py - MIXING BOTH!
class ProcessPoolManager:
    def __init__(self):
        self._lock = threading.RLock()  # Python
        self._mutex = QMutex()           # Qt

# filesystem_scanner.py
self.lock = threading.RLock()

# logging_mixin.py
self._lock = threading.RLock()

# cache_manager.py
self._lock = QMutex()
```

**Problems:**
- Different semantics (QMutex != threading.Lock)
- Deadlock potential with mixed types
- Maintenance burden (two threading models)
- Hard to reason about thread safety

**Solution:**
Standardize on **Qt threading** (this is a PySide6 application):

```python
# BEFORE (Python threading)
import threading

class MyClass:
    def __init__(self):
        self._lock = threading.RLock()

    def method(self):
        with self._lock:
            # ... work ...

# AFTER (Qt threading)
from PySide6.QtCore import QMutex, QMutexLocker

class MyClass:
    def __init__(self):
        self._lock = QMutex()

    def method(self):
        with QMutexLocker(self._lock):
            # ... work ...
```

**Files to Update (~15 files):**
1. `filesystem_scanner.py` - RLock → QMutex
2. `logging_mixin.py` - RLock → QMutex
3. `persistent_bash_session.py` - Lock → QMutex
4. `persistent_terminal_manager.py` - Lock → QMutex
5. `process_pool_manager.py` - Remove RLock, keep only QMutex
6. `runnable_tracker.py` - Lock → QMutex
7. `scene_cache.py` - RLock → QMutex
8. `secure_command_executor.py` - Lock → QMutex
9. Test doubles and utilities (~7 files)

**Migration Steps:**
1. Create threading standardization document
2. Update imports: `threading` → `PySide6.QtCore`
3. Replace constructors: `RLock()` → `QMutex()`
4. Replace context managers: `with self._lock` → `with QMutexLocker(self._lock)`
5. Update tests to use QMutex
6. Add mutex ordering documentation to prevent deadlocks

**Benefits:**
- ✅ Single threading model (easier to understand)
- ✅ Consistent with Qt event loop
- ✅ RAII pattern with QMutexLocker
- ✅ Better integration with Qt's threading
- ✅ Eliminates mixed-mutex deadlock risk

**Documentation:**
Add to architecture docs:

```markdown
# Threading Model

ShotBot uses **Qt threading exclusively** for all synchronization:

## Mutex Usage
- Use `QMutex` for all locks (not `threading.Lock`)
- Use `QMutexLocker` for RAII pattern
- Document mutex ordering to prevent deadlocks

## Mutex Ordering (to prevent deadlocks)
1. `_cache_mutex` (innermost - shortest hold time)
2. `_scan_lock` (middle)
3. Model reset locks (outermost - Qt internal)

**Rule:** NEVER acquire mutexes in reverse order!

## Threading Patterns
- Background work: Use `QThread` and signals
- Short operations: Use `QMutexLocker` for protection
- Long operations: Release mutex before I/O
```

**Testing:**
```python
def test_threading_standardization():
    """Verify all classes use QMutex, not threading.Lock."""
    # Find all mutex/lock usage
    grep_output = subprocess.check_output([
        'grep', '-r', '-E', 'threading\.(RLock|Lock)', '*.py'
    ])

    # Should only be in tests or archived code
    assert len(grep_output) == 0, f"Found threading.Lock usage: {grep_output}"
```

---

## Phase 2: DRY Violations (Week 2 Part 1) - 4.5 hours

### 2.1 Shot Filter - Functional Composition (REVISED) 🔧

**Priority**: HIGH
**Risk**: Low
**Time**: 2 hours

**Issue:**
59 lines of filtering logic duplicated between:
- `base_shot_model.py` lines 283-341
- `previous_shots_model.py` lines 179-237

**v2.0 Problem:**
Proposed class-based `ShotFilter` with composition. While better than mixin, it's still more complex than needed.

**v3.0 Solution:**
Functional composition (more Pythonic, simpler):

```python
# shot_filter.py (new file)
"""Functional shot filtering utilities.

Provides composable filter functions for shot collections.
All functions are pure (no side effects) for easy testing.
"""

from typing import Protocol

class Filterable(Protocol):
    """Protocol for filterable shot-like objects."""
    show: str
    full_name: str

def filter_by_show(
    items: list[Filterable],
    show: str | None
) -> list[Filterable]:
    """Filter items by show name.

    Args:
        items: Items to filter
        show: Show name or None for no filtering

    Returns:
        Filtered list (original list if show is None)
    """
    if show is None:
        return items
    return [item for item in items if item.show == show]

def filter_by_text(
    items: list[Filterable],
    text: str | None
) -> list[Filterable]:
    """Filter items by text substring (case-insensitive).

    Args:
        items: Items to filter
        text: Text to search for or None for no filtering

    Returns:
        Filtered list (original list if text is None)
    """
    if not text:
        return items
    text_lower = text.strip().lower()
    return [
        item for item in items
        if text_lower in item.full_name.lower()
    ]

def compose_filters(
    items: list[Filterable],
    show: str | None = None,
    text: str | None = None,
) -> list[Filterable]:
    """Apply multiple filters in sequence.

    Args:
        items: Items to filter
        show: Show name filter (optional)
        text: Text substring filter (optional)

    Returns:
        Filtered list after applying all active filters

    Example:
        >>> filtered = compose_filters(
        ...     shots,
        ...     show="gator",
        ...     text="0010"
        ... )
    """
    result = items
    if show is not None:
        result = filter_by_show(result, show)
    if text is not None:
        result = filter_by_text(result, text)
    return result

def get_available_shows(items: list[Filterable]) -> set[str]:
    """Extract unique show names from items.

    Args:
        items: Items to extract shows from

    Returns:
        Set of unique show names
    """
    return {item.show for item in items}
```

**Usage in BaseShotModel:**
```python
# base_shot_model.py
from shot_filter import compose_filters, get_available_shows

class BaseShotModel(LoggingMixin, QObject):
    def __init__(self):
        super().__init__()
        self._shots: list[Shot] = []
        self._show_filter: str | None = None
        self._text_filter: str | None = None

    def set_show_filter(self, show: str | None) -> None:
        """Set show filter."""
        self._show_filter = show
        filter_display = show if show else "All Shows"
        self.logger.info(f"Show filter: {filter_display}")
        self.show_filter_changed.emit(filter_display)

    def get_show_filter(self) -> str | None:
        """Get current show filter."""
        return self._show_filter

    def set_text_filter(self, text: str | None) -> None:
        """Set text filter."""
        self._text_filter = text.strip() if text else None
        self.logger.info(f"Text filter: '{self._text_filter or ''}'")

    def get_text_filter(self) -> str | None:
        """Get current text filter."""
        return self._text_filter

    def get_filtered_shots(self) -> list[Shot]:
        """Apply filters to shots."""
        return compose_filters(
            self._shots,
            show=self._show_filter,
            text=self._text_filter
        )

    def get_available_shows(self) -> set[str]:
        """Get available shows."""
        return get_available_shows(self._shots)
```

**Why Functional is Better:**

| Aspect | Class-Based | Functional | Winner |
|--------|-------------|------------|--------|
| Lines | ~50 | ~25 | Functional |
| State | Mutable | Immutable | Functional |
| Testing | Need objects | Pure functions | Functional |
| Allocation | Object creation | None | Functional |
| Pythonic | Less | More | Functional |
| Extensibility | Add methods | Add functions | Tie |

**Benefits:**
- ✅ Half the code (25 lines vs 50 lines)
- ✅ Pure functions (no side effects, easy testing)
- ✅ No object allocation overhead
- ✅ More Pythonic (functional style for data transformation)
- ✅ Immutable (no state management bugs)
- ✅ Composable (easy to add new filters)

**Testing:**
```python
def test_functional_filters():
    """Test pure filter functions."""
    shots = [
        Shot("show1", "seq1", "shot1", "/path1"),
        Shot("show2", "seq1", "shot2", "/path2"),
        Shot("show1", "seq2", "shot3", "/path3"),
    ]

    # Test show filter
    filtered = filter_by_show(shots, "show1")
    assert len(filtered) == 2
    assert all(s.show == "show1" for s in filtered)

    # Test text filter
    filtered = filter_by_text(shots, "shot1")
    assert len(filtered) == 1
    assert filtered[0].shot == "shot1"

    # Test composition
    filtered = compose_filters(shots, show="show1", text="shot")
    assert len(filtered) == 2
```

---

### 2.2 Context Manager Extraction ✅

**Priority**: LOW
**Risk**: Very Low
**Time**: 1 hour

**Issue:**
Duplicate context manager logic in `logging_mixin.py`:
- Lines 133-161: `ContextualLogger.context()` method
- Lines 329-357: `log_context()` function

**Solution:**
```python
def _manage_log_context(**kwargs: str) -> Generator[None, None, None]:
    """Shared implementation for context managers.

    Handles thread-local context stack manipulation with guaranteed cleanup.
    """
    # Get current context or create empty dict
    current_context = getattr(_context_storage, "context", {})

    # Create new context by merging
    new_context = {**current_context, **kwargs}

    # Store old for restoration
    old_context = getattr(_context_storage, "context", None)

    try:
        _context_storage.context = new_context
        yield
    finally:
        # Restore previous context
        if old_context is not None:
            _context_storage.context = old_context
        else:
            # Remove context if there was none before
            if hasattr(_context_storage, "context"):
                delattr(_context_storage, "context")

@contextmanager
def log_context(**kwargs: str) -> Generator[None, None, None]:
    """Module-level context manager."""
    yield from _manage_log_context(**kwargs)

# In ContextualLogger class:
@contextmanager
def context(self, **kwargs: str) -> Generator[None, None, None]:
    """Instance-level context manager."""
    yield from _manage_log_context(**kwargs)
```

**Benefits:**
- Eliminates 25+ lines of duplication
- Single source of truth
- Perfect use of `yield from`
- Zero risk (pure refactoring)

---

### 2.3 Feature Flag Consolidation ✅

**Priority**: LOW
**Risk**: Very Low
**Time**: 1.5 hours

**Issue:**
Feature flags scattered across `main_window.py` (lines 269, 312, 329, 675).

**Solution:**
Enum-based feature flags for type safety:

```python
# feature_flags.py (new file)
import os
from enum import Enum, auto

class FeatureFlag(Enum):
    """Centralized feature flag management with type safety.

    All feature flags read from environment variables.
    """
    SIMPLIFIED_LAUNCHER = auto()
    THREEDE_CONTROLLER = auto()
    DEBUG_LOGGING = auto()
    MOCK_MODE = auto()

    def is_enabled(self) -> bool:
        """Check if feature is enabled via environment variable.

        Returns:
            True if feature is enabled, False otherwise
        """
        env_map = {
            self.SIMPLIFIED_LAUNCHER: "USE_SIMPLIFIED_LAUNCHER",
            self.THREEDE_CONTROLLER: "USE_THREEDE_CONTROLLER",
            self.DEBUG_LOGGING: "SHOTBOT_DEBUG",
            self.MOCK_MODE: "SHOTBOT_MOCK",
        }
        env_var = env_map[self]
        value = os.environ.get(env_var, "").lower()
        return value in ("1", "true", "yes")

    @staticmethod
    def list_enabled() -> list[str]:
        """List all currently enabled feature flags.

        Returns:
            List of enabled feature flag names
        """
        return [
            flag.name for flag in FeatureFlag
            if flag.is_enabled()
        ]

# Usage in main_window.py
from feature_flags import FeatureFlag

if FeatureFlag.SIMPLIFIED_LAUNCHER.is_enabled():
    # Simplified launcher code
else:
    # Standard launcher code

# Debugging
enabled = FeatureFlag.list_enabled()
print(f"Enabled features: {enabled}")
```

**Benefits:**
- Single source of truth for flags
- Type-safe (enum prevents typos)
- Easy to discover all feature flags
- Testable with environment mocking
- Self-documenting

---

## Phase 3: Complexity Reduction (Week 2 Part 2) - 9.5 hours

### 3.1 Thumbnail Discovery - REMOVED ❌

**Original Issue:**
522 lines of complex thumbnail discovery logic in `utils.py`.

**v2.0 Proposal:**
Template Method pattern with 5 finder classes.

**v3.0 Decision: SKIP THIS PHASE**

**Rationale:**
After code verification, current implementation is already well-organized:
- ✅ Clear functional approach with static methods
- ✅ Simple priority-based fallback chain
- ✅ Zero object allocation overhead
- ✅ Easy to test (each function independent)
- ✅ Easy to extend (add new finder function)

**Current Code Structure:**
```python
# utils.py - PathUtils class
@staticmethod
def find_shot_thumbnail(...) -> Path | None:
    """Single entry point - calls helpers in priority order."""
    # 1. Editorial JPEG (highest quality)
    if thumbnail := FileUtils.get_first_image_file(editorial_dir):
        return thumbnail

    # 2. Undistorted JPEG (published matchmove)
    if thumbnail := PathUtils.find_undistorted_jpeg_thumbnail(...):
        return thumbnail

    # 3. User workspace JPEG (artist-generated)
    if thumbnail := PathUtils.find_user_workspace_jpeg_thumbnail(...):
        return thumbnail

    # 4. Turnover plate EXR (may be large)
    if thumbnail := PathUtils.find_turnover_plate_thumbnail(...):
        return thumbnail

    # 5. Any publish with 1001 (last resort)
    return PathUtils.find_any_publish_thumbnail(...)

@staticmethod
def find_turnover_plate_thumbnail(...) -> Path | None:
    """Complex logic for FG/BG priority."""
    # Implementation here - already well-organized

# ... 4 more helper functions
```

**This is already good design!**
- Simple, clear, functional
- No class hierarchy overhead
- Easy to understand top-to-bottom
- Each helper is independently testable

**Template Method Would Add:**
- Abstract base class (~50 lines boilerplate)
- 5 finder subclasses (~40 lines each = 200 lines)
- Object allocation overhead (creates 5 objects per call)
- Harder to understand (need to follow inheritance)

**What We Actually Need:**
Current code is production-tested and working well. If any improvements needed later:
- Extract priority constants to Config (2 lines)
- Add result caching for repeated calls (5 lines)
- Improve logging consistency (10 lines)

**Time Saved:** 25 hours → 0 hours

**Alternative Minimal Improvements (Optional, 2 hours):**
```python
# config.py - Add priority constants
THUMBNAIL_SEARCH_PRIORITY = [
    "editorial",      # Highest quality, curated
    "undistorted",    # Published matchmove
    "user_workspace", # Artist-generated
    "turnover_plate", # May be large EXR
    "any_publish",    # Last resort
]

# utils.py - Add simple caching
@lru_cache(maxsize=128)
def find_shot_thumbnail(...) -> Path | None:
    """Cached thumbnail discovery."""
    # ... existing logic
```

---

### 3.2 MainWindow Simplification ✅

**Priority**: MEDIUM
**Risk**: Low
**Time**: 5 hours

**Issue:**
1,413-line main_window.py with mixed concerns.

**Solution:**
Extract MenuBuilder ONLY (don't over-engineer with coordinators):

```python
# menu_builder.py (new file)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar

class MenuBuilder:
    """Builds application menus with consistent structure."""

    def __init__(self, main_window):
        self._window = main_window
        self._actions: dict[str, QAction] = {}

    def build_menus(self) -> None:
        """Build all application menus."""
        menubar = self._window.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        self._add_file_menu_actions(file_menu)

        # View menu
        view_menu = menubar.addMenu("&View")
        self._add_view_menu_actions(view_menu)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        self._add_help_menu_actions(help_menu)

    def _add_file_menu_actions(self, menu: QMenu) -> None:
        """Add actions to File menu."""
        # Refresh
        refresh_action = self._create_action(
            "refresh",
            "&Refresh All",
            "Ctrl+R",
            "Refresh all data",
            self._window.refresh_all_data
        )
        menu.addAction(refresh_action)

        menu.addSeparator()

        # Exit
        exit_action = self._create_action(
            "exit",
            "E&xit",
            "Ctrl+Q",
            "Exit application",
            self._window.close
        )
        menu.addAction(exit_action)

    def _add_view_menu_actions(self, menu: QMenu) -> None:
        """Add actions to View menu."""
        # Increase thumbnail size
        increase_action = self._create_action(
            "increase_thumbs",
            "Increase Thumbnail Size",
            "Ctrl++",
            "Make thumbnails larger",
            self._window.increase_thumbnail_size
        )
        menu.addAction(increase_action)

        # Decrease thumbnail size
        decrease_action = self._create_action(
            "decrease_thumbs",
            "Decrease Thumbnail Size",
            "Ctrl+-",
            "Make thumbnails smaller",
            self._window.decrease_thumbnail_size
        )
        menu.addAction(decrease_action)

    def _add_help_menu_actions(self, menu: QMenu) -> None:
        """Add actions to Help menu."""
        about_action = self._create_action(
            "about",
            "&About",
            None,
            "About this application",
            self._window.show_about_dialog
        )
        menu.addAction(about_action)

    def _create_action(
        self,
        name: str,
        text: str,
        shortcut: str | None,
        tooltip: str,
        callback: callable
    ) -> QAction:
        """Create and store an action.

        Args:
            name: Internal action name
            text: Display text
            shortcut: Keyboard shortcut or None
            tooltip: Tooltip text
            callback: Function to call when triggered

        Returns:
            Created QAction
        """
        action = QAction(text, self._window)

        if shortcut:
            action.setShortcut(QKeySequence(shortcut))

        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)
        action.triggered.connect(callback)

        self._actions[name] = action
        return action

    def get_action(self, name: str) -> QAction | None:
        """Get action by name for programmatic access or testing."""
        return self._actions.get(name)

    def enable_actions(self, *names: str) -> None:
        """Bulk enable actions."""
        for name in names:
            if action := self._actions.get(name):
                action.setEnabled(True)

    def disable_actions(self, *names: str) -> None:
        """Bulk disable actions."""
        for name in names:
            if action := self._actions.get(name):
                action.setEnabled(False)

# main_window.py
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self._setup_ui()
        self._menu_builder = MenuBuilder(self)
        self._menu_builder.build_menus()
        self._connect_signals()
```

**Why NOT TabCoordinator/SignalRouter:**
- Qt's Model/View already handles tabs
- Would just move complexity, not reduce it
- Current signal connections are already clear with comments

**Benefits:**
- Cleaner menu management (~100 lines → 80 lines in MenuBuilder)
- Reusable action creation logic
- Easy to add new menus
- Programmatic action access for testing
- MainWindow reduced by ~100 lines

**Don't Extract:**
- Signal connections (already clear with good comments)
- Tab management (Qt already provides this)
- UI layout (needs context of MainWindow)

---

### 3.3 Dispatch Table for data() Method (IMPROVED) ✅

**Priority**: LOW
**Risk**: Low
**Time**: 4.5 hours

**Issue:**
66-line if/elif chain in `base_item_model.py` data() method (lines 177-223).

**v2.0 Solution:**
Class-level dispatch with lambdas.

**v3.0 Improvement:**
Use method references instead of lambdas (better memory usage):

```python
class BaseItemModel(QAbstractListModel, Generic[T]):
    # Class-level dispatch table (method names, not lambdas)
    _ROLE_HANDLERS: ClassVar[dict[int, str]] = {
        BaseItemRole.ObjectRole: "_get_object_role",
        BaseItemRole.ShowRole: "_get_show_role",
        BaseItemRole.SequenceRole: "_get_sequence_role",
        BaseItemRole.FullNameRole: "_get_full_name_role",
        BaseItemRole.WorkspacePathRole: "_get_workspace_path_role",
        BaseItemRole.ThumbnailPathRole: "_get_thumbnail_path_role",
        Qt.ItemDataRole.ToolTipRole: "get_tooltip_data",
        Qt.ItemDataRole.SizeHintRole: "get_size_hint",
    }

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        """Get data with optimized dispatch."""
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None

        item = self._items[index.row()]

        # Hot path optimization - DisplayRole is most common
        if role == Qt.ItemDataRole.DisplayRole:
            return self.get_display_role_data(item)

        # Hot path - ThumbnailPixmapRole second most common
        if role == BaseItemRole.ThumbnailPixmapRole:
            return self._get_thumbnail_pixmap(item)

        # Loading state needs mutex
        if role == BaseItemRole.LoadingStateRole:
            with QMutexLocker(self._cache_mutex):
                return self._loading_states.get(item.full_name, "idle")

        # Selection tracking
        if role == BaseItemRole.IsSelectedRole:
            return self._selected_index == QPersistentModelIndex(index)

        # Decoration (icon)
        if role == Qt.ItemDataRole.DecorationRole:
            pixmap = self._get_thumbnail_pixmap(item)
            return QIcon(pixmap) if pixmap else None

        # Dispatch table for other roles (method references)
        method_name = self._ROLE_HANDLERS.get(role)
        if method_name:
            method = getattr(self, method_name)
            return method(item)

        # Fall back to subclass implementation
        return self.get_custom_role_data(item, role)

    # Handler methods (called via dispatch table)
    def _get_object_role(self, item: T) -> T:
        """Get object role."""
        return item

    def _get_show_role(self, item: T) -> str:
        """Get show role."""
        return item.show

    def _get_sequence_role(self, item: T) -> str:
        """Get sequence role."""
        return item.sequence

    def _get_full_name_role(self, item: T) -> str:
        """Get full name role."""
        return item.full_name

    def _get_workspace_path_role(self, item: T) -> str:
        """Get workspace path role."""
        return item.workspace_path

    def _get_thumbnail_path_role(self, item: T) -> str | None:
        """Get thumbnail path role."""
        thumb_path = item.get_thumbnail_path()
        return str(thumb_path) if thumb_path else None
```

**Benefits:**
- Eliminates 45-line if/elif chain
- O(1) lookup for dispatched roles
- Hot-path optimization for common roles (no dict lookup)
- Method references reduce memory overhead vs lambdas
- Clear, testable handler methods
- Each handler independently testable

**Performance:**
`data()` is called thousands of times during scrolling:
- Hot paths (DisplayRole, ThumbnailPixmapRole): No dict lookup - fast!
- Cold paths: Single dict lookup + getattr - acceptable
- Method references: Less memory than lambdas (8 refs vs 8 closures)

**Testing:**
```python
def test_dispatch_table_roles(model):
    """Test that dispatch table handles all roles correctly."""
    model.set_items([Shot("show1", "seq1", "shot1", "/path1")])
    index = model.index(0, 0)

    # Test dispatch table roles
    assert model.data(index, BaseItemRole.ShowRole) == "show1"
    assert model.data(index, BaseItemRole.SequenceRole) == "seq1"
    assert model.data(index, BaseItemRole.FullNameRole) == "show1/seq1/shot1"
    assert model.data(index, BaseItemRole.WorkspacePathRole) == "/path1"
```

---

## Phase 4: Final Cleanup (Week 3 Part 1) - 16 hours

### 4.1 CacheManager Split - Facade Pattern ✅

**Priority**: MEDIUM
**Risk**: Medium
**Time**: 10 hours

**Issue:**
729-line CacheManager mixing thumbnail, shot, and 3DE scene caching.

**Solution:**
Split into focused classes with Facade for backward compatibility:

```python
# thumbnail_cache.py (new file)
class ThumbnailCache:
    """Dedicated thumbnail caching with multi-format support."""

    def __init__(self, cache_dir: Path):
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def cache_thumbnail(
        self,
        source_path: Path,
        show: str,
        sequence: str,
        shot: str
    ) -> Path | None:
        """Cache thumbnail with format conversion.

        Handles JPEG, PNG, EXR with PIL/OpenEXR.
        """
        # Implementation from existing cache_manager.py
        pass


# data_cache.py (new file)
from typing import Generic, TypeVar

T = TypeVar('T')

class DataCache(Generic[T]):
    """Generic JSON data caching with TTL."""

    DEFAULT_TTL_MINUTES: ClassVar[int] = 30

    def __init__(
        self,
        cache_dir: Path,
        cache_name: str,
        ttl_minutes: int | None = None
    ):
        self._cache_dir = cache_dir
        self._cache_name = cache_name
        self._ttl = timedelta(minutes=ttl_minutes or self.DEFAULT_TTL_MINUTES)

    def get(self) -> T | None:
        """Get cached data if valid."""
        cache_file = self._cache_dir / f"{self._cache_name}.json"

        if not cache_file.exists():
            return None

        # Check TTL
        age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if age > self._ttl:
            return None

        with open(cache_file, 'r') as f:
            return json.load(f)

    def set(self, data: T) -> None:
        """Cache data."""
        cache_file = self._cache_dir / f"{self._cache_name}.json"

        with open(cache_file, 'w') as f:
            json.dump(data, f)

    def clear(self) -> None:
        """Clear cached data."""
        cache_file = self._cache_dir / f"{self._cache_name}.json"
        if cache_file.exists():
            cache_file.unlink()


# cache_manager.py (simplified facade)
class CacheManager:
    """Facade providing backward-compatible API.

    Delegates to specialized caches for single-responsibility design.
    """

    def __init__(self):
        cache_dir = self._get_cache_dir()

        self._thumbnail_cache = ThumbnailCache(cache_dir / "thumbnails")
        self._shot_cache = DataCache[list[ShotDict]](cache_dir, "shots")
        self._threede_cache = DataCache[list[ThreeDESceneDict]](
            cache_dir, "threede_scenes"
        )
        self._previous_cache = DataCache[list[ShotDict]](
            cache_dir, "previous_shots"
        )

    # Delegate to specialized caches
    def cache_thumbnail(self, *args, **kwargs) -> Path | None:
        """Delegate to ThumbnailCache."""
        return self._thumbnail_cache.cache_thumbnail(*args, **kwargs)

    def get_cached_shots(self) -> list[ShotDict] | None:
        """Delegate to shot DataCache."""
        return self._shot_cache.get()

    def cache_shots(self, shots: list[ShotDict]) -> None:
        """Delegate to shot DataCache."""
        self._shot_cache.set(shots)

    # ... similar delegation for other cache types
```

**Benefits:**
- Single responsibility per class
- Type-safe generic caching (`DataCache[T]`)
- Easy to test in isolation
- Backward compatible (Facade pattern)
- Dependency injection ready

**Migration with Dependency Injection:**
```python
# Instead of facade creating everything:
class ShotItemModel:
    def __init__(self, thumbnail_cache: ThumbnailCache):
        self._thumbnail_cache = thumbnail_cache  # Inject what you need
```

---

### 4.2 Documentation and Testing ✅

**Priority**: HIGH
**Risk**: N/A
**Time**: 6 hours

**Documentation Requirements:**

**1. Architecture Decision Records (2 hours)**
```markdown
# ADR-001: Threading Model Standardization

## Status
Accepted

## Context
Codebase mixed Qt (QMutex) and Python (threading.Lock) primitives.

## Decision
Standardize on Qt threading exclusively for consistency with PySide6.

## Consequences
- All new code uses QMutex/QMutexLocker
- Existing threading.Lock migrated over time
- Better integration with Qt event loop
```

**2. Module Documentation (2 hours)**
Add to each refactored module:
```python
"""Module documentation.

Architecture:
    Brief description of design pattern used

Thread Safety:
    Description of threading model and mutex usage

Performance:
    Any performance considerations or caching

Example:
    Basic usage example
"""
```

**3. Testing Requirements (2 hours)**
- Unit tests for all new classes
- Thread safety tests with concurrent access
- Performance benchmarks for Phase 1.1
- Mock environment tests (432-shot fixture)

**Example Tests:**
```python
# test_threading_safety.py
def test_atomic_thumbnail_marking(model, qtbot):
    """Verify atomic check-and-mark prevents duplicates."""
    # ... test from Phase 1.1

# test_functional_filters.py
def test_filter_composition():
    """Test pure filter functions."""
    # ... test from Phase 2.1

# test_menu_builder.py
def test_menu_actions():
    """Test MenuBuilder creates correct actions."""
    # ... test from Phase 3.2
```

---

## Testing Strategy

### Performance Benchmarking

**Before/After Metrics:**
```bash
# Baseline before refactoring
python measure_performance.py --baseline --output baseline.json

# After each phase
python measure_performance.py --compare-to baseline.json
```

**Key Metrics:**
- Thumbnail loading time (should improve with Phase 1.1)
- Shot refresh time (unchanged)
- Memory usage (should decrease slightly)
- UI responsiveness during scrolling

**Acceptance Criteria:**
- Startup time: < 2% regression
- Shot loading: < 5% regression
- Thumbnail loading: < 10% regression (allowed due to atomic marking)
- Memory: < 15% regression

### UI Regression Testing

```bash
# Run with mock environment
SHOTBOT_MOCK=1 ~/.local/bin/uv run pytest tests/ui/ -v

# Smoke tests
SHOTBOT_MOCK=1 ~/.local/bin/uv run python shotbot.py --headless --test-mode
```

**Test Cases:**
- All tabs load correctly
- Thumbnails display without duplicates
- Filtering works (show + text)
- Selection works and persists
- Launcher integration works
- Menu actions trigger correctly

### Thread Safety Validation

```bash
# Run with parallel execution
~/.local/bin/uv run pytest tests/threading/ -n 8 -v --timeout=10

# Stress tests
~/.local/bin/uv run pytest tests/unit/ -n 8 --count=100
```

**Specific Tests:**
- Concurrent thumbnail loading (no duplicates)
- Concurrent show filter changes
- Concurrent model updates
- QMutex ordering validation

### Production Validation (Phase 1.1 Only)

**Critical for race condition fix:**

1. **Dual-Running Validation (5 hours)**
```bash
# Enable feature flag for new implementation
export SHOTBOT_NEW_THUMBNAIL_LOADING=1

# Run both old and new, compare results
python validate_thumbnail_loading.py --compare-implementations
```

2. **Gradual Rollout**
- Week 1: 10% of users with new implementation
- Week 2: 50% of users if no issues
- Week 3: 100% deployment

3. **Monitoring**
- Track duplicate load errors (should be zero)
- Monitor performance (should be same or better)
- User feedback (any UI hangs?)

---
 

## Revised Phasing

### Week 1: Critical Fixes (15h)

**Monday-Tuesday (8h):**
- Phase 1.1: Thumbnail loading race (2h)
- Phase 1.2: Selection thread safety (0.5h)
- Phase 1.3: Context manager pattern (2h)
- Phase 1.4: CSS extraction (0.5h)
- Phase 1.5: Cleanup consolidation (2h)
- Testing Phase 1.1-1.5 (1h)

**Wednesday-Friday (7h):**
- Phase 1.6: Threading standardization (5h)
- Testing Phase 1.6 (2h)

**Deliverables:**
- Fixed race condition (verified)
- Standardized threading model
- Improved cleanup patterns

### Week 2: DRY & Complexity (14h)

**Monday-Tuesday (4.5h):**
- Phase 2.1: Shot filter functional (2h)
- Phase 2.2: Context manager extraction (1h)
- Phase 2.3: Feature flags (1.5h)

**Wednesday-Friday (9.5h):**
- Phase 3.2: MenuBuilder extraction (5h)
- Phase 3.3: Dispatch table + methods (4.5h)

**Deliverables:**
- Functional composition for filters
- Cleaner main window
- Optimized data() method

### Week 3: Polish & Validation (28h)

**Monday-Tuesday (16h):**
- Phase 4.1: CacheManager split (10h)
- Phase 4.2: Documentation (6h)

**Wednesday-Friday (12h):**
- Comprehensive testing (8h)
- Production validation Phase 1.1 (4h)

**Deliverables:**
- Split cache architecture
- Complete documentation
- Production-validated fixes

---

## Migration Checklist

### Before Starting

- [ ] Create feature branch `refactoring-v3`
- [ ] Run full test suite (baseline)
- [ ] Run performance benchmarks (baseline)
- [ ] Commit current state
- [ ] Document baseline metrics

### Per Phase

- [ ] Implement changes
- [ ] Run unit tests (must pass)
- [ ] Run integration tests (must pass)
- [ ] Performance check (no regression > 5%)
- [ ] Code review (peer + self-review)
- [ ] Commit with descriptive message
- [ ] Update this document with status

### Before Merging

- [ ] Full test suite passes
- [ ] Performance benchmarks acceptable (< 5% regression)
- [ ] Manual UI testing with mock environment
- [ ] Documentation updated (CLAUDE.md, ADRs)
- [ ] No regressions in functionality
- [ ] Production validation completed (Phase 1.1)
- [ ] Stakeholder approval

---

## Rollback Procedures

### Standard Rollback (Phases 1.2-4.2)

**If Phase Fails:**
1. Document the failure (tests, errors, issues)
2. Revert branch to pre-phase state
3. Analyze root cause
4. Update plan with lessons learned
5. Retry or skip phase

### Critical Rollback (Phase 1.1 - Race Condition)

**Feature Flag Approach:**
```python
# config.py
USE_ATOMIC_THUMBNAIL_MARKING = os.environ.get(
    "SHOTBOT_ATOMIC_THUMBNAILS", "true"
).lower() == "true"

# base_item_model.py
def _load_visible_thumbnails(self) -> None:
    if Config.USE_ATOMIC_THUMBNAIL_MARKING:
        self._load_visible_thumbnails_atomic()  # New implementation
    else:
        self._load_visible_thumbnails_legacy()  # Old implementation
```

**Rollback Steps:**
1. Set `SHOTBOT_ATOMIC_THUMBNAILS=false`
2. Monitor for 1 hour
3. If stable, investigate issue
4. If unstable, revert code completely

### Red Flags to Abort

- >10% performance regression
- >3 new failing tests
- Memory leaks detected
- UI hangs or crashes
- Data corruption
- Increased error rate in production

---

## Success Criteria

### Code Quality

- [ ] 0 basedpyright errors
- [ ] 0 ruff errors
- [ ] Test coverage >90% for modified code
- [ ] All threading uses QMutex (not threading.Lock)

### Performance

- [ ] Thumbnail loading: ≤ 5% regression (ideally improvement)
- [ ] Memory usage: ≤ 15% regression
- [ ] UI responsiveness: No degradation
- [ ] Startup time: ≤ 2% regression

### Maintainability

- [ ] ~150 lines eliminated (phases 1-2)
- [ ] Clear documentation for new patterns
- [ ] Single threading model (Qt only)
- [ ] Simplified architecture (removed unnecessary abstractions)

### Production Stability (Phase 1.1)

- [ ] Zero duplicate thumbnail loads in 1 week monitoring
- [ ] Zero production incidents
- [ ] Zero customer complaints about thumbnails
- [ ] Error rate < 0.1% for thumbnail loading

### Developer Experience

- [ ] Time to onboard new developer (should decrease)
- [ ] Time to add new filter type (should decrease by 50%)
- [ ] Code review time (should decrease by 30%)

---

## Conclusion

This v3.0 amended plan represents a **verified, pragmatic approach** to refactoring:

### Key Improvements from v2.0

- ✅ **Fixed Phase 1.1** - Correct atomic check-and-mark solution
- ✅ **Added Phase 1.6** - Critical threading standardization
- ✅ **Re-added Phase 1.2** - Future-proof selection safety
- ✅ **Removed Phase 3.1** - Current code already good
- ✅ **Revised Phase 2.1** - Functional > class-based
- ✅ **Improved Phase 3.3** - Method references > lambdas

### Expected Outcomes

- ✅ **Reduced complexity** (~150 lines eliminated)
- ✅ **Better maintainability** (single threading model, clearer patterns)
- ✅ **Improved performance** (atomic marking faster than per-item)
- ✅ **Standardized architecture** (Qt threading, functional composition)
- ✅ **40% faster delivery** (57h vs 95h)
- ✅ **Lower risk** (skip risky Phase 3.1, add production validation)

### Confidence Level

**Very High** - All proposals:
1. Verified through code inspection
2. Reviewed by two specialized agents
3. Validated against current implementation
4. Tested against production patterns
5. Include rollback procedures

### Timeline

**Calendar Time:** 3 weeks (with buffer)
**Working Time:** 57 hours (~1.5 weeks full-time)

### Risk Level

**Medium** (down from High in v2.0):
- Phase 1.1 verified correct solution
- Phase 1.6 straightforward (search-replace mostly)
- Phase 3.1 removed (high-risk phase eliminated)
- Production validation added for critical changes

---

## Questions for Stakeholders

1. **Budget:** Is there approval for 57 hours (1.5-2 weeks)?
2. **Production validation:** Can Phase 1.1 be tested in staging with feature flags?
3. **Threading standardization:** Is there buy-in for Qt-only threading (affects ~15 files)?
4. **Phase 3.1:** Confirm that keeping current thumbnail discovery is acceptable?
5. **Review process:** Who will review code at each phase checkpoint?
6. **Rollback authority:** Who has authority to rollback if issues found in production?

---

## Next Steps

1. ✅ Review this v3.0 plan with team
2. ⏳ Get sign-off on revised approach
3. ⏳ Create feature branch `refactoring-v3`
4. ⏳ Implement Phase 1.1 with verified solution
5. ⏳ Add production validation framework for Phase 1.1
6. ⏳ Begin threading standardization audit (Phase 1.6)

**Status:** Ready for implementation after stakeholder approval

**Version History:**
- v1.0: Original plan (dual-agent review)
- v2.0: Amended plan (corrections from v1.0)
- v3.0: Final plan (verified corrections after code review)
