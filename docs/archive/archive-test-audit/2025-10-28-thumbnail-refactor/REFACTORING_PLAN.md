# ShotBot Refactoring Plan
## Comprehensive KISS/DRY Violation Resolution

**Generated:** 2025-10-11
**Based on:** Dual-agent code review (code-refactoring-expert + python-code-reviewer)
**Total Estimated Effort:** 55 hours (7 working days)

---

## Executive Summary

Two independent code review agents analyzed the ShotBot codebase for KISS (Keep It Simple, Stupid) and DRY (Don't Repeat Yourself) violations. The analysis revealed:

### Critical Findings
- **3 Race Conditions** in thread-safe code that could cause production crashes
- **2 God Classes** (MainWindow: 1,413 lines, CacheManager: 729 lines)
- **~250 lines of duplicate code** across multiple modules
- **710 lines of overly complex thumbnail discovery logic**
- **Multiple SOLID principle violations**

### Overall Assessment
The codebase demonstrates **good architectural foundations** with:
- ✅ Model/View separation with Qt patterns
- ✅ Dependency injection via ProcessPoolFactory
- ✅ Comprehensive type hints (Python 3.11+)
- ✅ Intentional tab architecture separation (NOT a violation)

However, technical debt has accumulated that affects maintainability and reliability. This plan provides a structured approach to address all identified issues.

---

## Prioritized Issues (15 Total)

### Critical Priority (Must Fix) 🔴
1. Race condition: Thumbnail loading (base_item_model.py)
2. Race condition: Selection tracking (base_item_model.py)
3. Race condition: Thread-safe flag pattern (previous_shots_model.py)
4. God class: MainWindow (1,413 lines)
5. God class: CacheManager (729 lines)

### High Priority (Should Fix) 🟡
6. DRY: Duplicate filtering logic (~59 lines)
7. DRY: Duplicate cleanup() methods (~90 lines)
8. DRY: Context manager duplication (~30 lines)
9. KISS: Overly complex thumbnail discovery (710 lines)
10. KISS: Complex logging decorator (117 lines)
11. Long method: BaseItemModel.data() (66 lines)
12. Long method: BaseItemModel._load_thumbnail_async() (86 lines)

### Medium Priority (Maintainability) 🟢
13. Magic numbers scattered throughout codebase
14. Feature flags not centralized
15. 130-line embedded CSS in MainWindow

---

## Phase 1: Critical Fixes & Quick Wins (Week 1)
**Estimated Time:** 10 hours
**Risk Level:** Low-Medium

### 1.1 Fix Race Condition: Thumbnail Loading
**File:** `base_item_model.py:320-350`
**Time:** 2 hours
**Risk:** Medium

**Problem:**
```python
# Check OUTSIDE mutex (line 320-328)
with QMutexLocker(self._cache_mutex):
    if item.full_name in self._thumbnail_cache:
        continue
    state = self._loading_states.get(item.full_name)
    if state in ("loading", "failed"):
        continue

# Mark as loading INSIDE mutex (line 349) - DIFFERENT SCOPE!
with QMutexLocker(self._cache_mutex):
    self._loading_states[item.full_name] = "loading"
```

**Issue:** Window between check and mark allows duplicate thumbnail loads from different threads, leading to wasted resources and potential crashes.

**Solution:**
```python
def _load_visible_thumbnails(self) -> None:
    """Load thumbnails for visible items only."""
    items_to_load: list[tuple[int, T]] = []

    # Atomically check and mark ALL items in one lock acquisition
    with QMutexLocker(self._cache_mutex):
        for row in range(start, end):
            item = self._items[row]

            # Skip if already cached or being loaded
            if item.full_name in self._thumbnail_cache:
                continue

            state = self._loading_states.get(item.full_name)
            if state in ("loading", "failed"):
                continue

            # Mark as loading while we still hold the lock
            self._loading_states[item.full_name] = "loading"
            items_to_load.append((row, item))

    # Now load outside the lock
    for row, item in items_to_load:
        self._load_thumbnail_async(row, item)
```

**Testing:**
1. Add threading test that triggers race condition
2. Run with ThreadSanitizer if available
3. Stress test with rapid scrolling in UI
4. Verify no duplicate loads in logs

---

### 1.2 Fix Race Condition: Selection Tracking
**File:** `base_item_model.py:125, 264-270`
**Time:** 1 hour
**Risk:** Low

**Problem:**
```python
# Line 125: Not protected by mutex
self._selected_item: T | None = None

# Lines 264-270: Modified without mutex protection
if role == BaseItemRole.IsSelectedRole:
    if value:
        self._selected_index = QPersistentModelIndex(index)
        self._selected_item = item  # RACE CONDITION!
```

**Issue:** If selection changes from multiple threads (e.g., user clicks while background refresh occurs), `_selected_item` could be corrupted or reference a deleted object.

**Solution:**
```python
class BaseItemModel(LoggingMixin, QAbstractListModel, Generic[T]):
    def __init__(self, cache_manager, parent):
        super().__init__(parent)
        # ... existing code ...
        self._cache_mutex = QMutex()  # Protect ALL shared state
        self._selected_item: T | None = None
        self._selected_index = QPersistentModelIndex()

    def setData(self, index, value, role):
        if not index.isValid():
            return False

        if role == BaseItemRole.IsSelectedRole:
            item = self._items[index.row()]

            # Protect selection state with mutex
            with QMutexLocker(self._cache_mutex):
                if value:
                    self._selected_index = QPersistentModelIndex(index)
                    self._selected_item = item
                else:
                    self._selected_index = QPersistentModelIndex()
                    self._selected_item = None

            # Emit signals outside lock
            self.selection_changed.emit(index)
            self.dataChanged.emit(index, index, [BaseItemRole.IsSelectedRole])
            return True

        return False

    def get_selected_item(self) -> T | None:
        """Thread-safe getter for selected item."""
        with QMutexLocker(self._cache_mutex):
            return self._selected_item
```

**Testing:**
1. Add test with concurrent selection changes
2. Verify selection integrity under load
3. Check signal emission order

---

### 1.3 Fix Race Condition: Thread-Safe Flag Pattern
**File:** `previous_shots_model.py` (5 locations)
**Time:** 1 hour
**Risk:** Low

**Problem:** Pattern repeated 5 times without abstraction:
```python
with QMutexLocker(self._scan_lock):
    if self._is_scanning:
        return False
    self._is_scanning = True
```

**Solution:**
```python
class PreviousShotsModel(LoggingMixin, QObject):
    """Model for discovering and managing user's previous shots."""

    def _acquire_scan_lock(self) -> bool:
        """Acquire scanning lock if not already scanning.

        Returns:
            True if lock acquired, False if already scanning
        """
        with QMutexLocker(self._scan_lock):
            if self._is_scanning:
                self.logger.debug("Already scanning for previous shots")
                return False
            self._is_scanning = True
            return True

    def _release_scan_lock(self) -> None:
        """Release scanning lock."""
        with QMutexLocker(self._scan_lock):
            self._is_scanning = False

    def _check_scanning_state(self) -> bool:
        """Check if currently scanning (thread-safe).

        Returns:
            True if scanning in progress
        """
        with QMutexLocker(self._scan_lock):
            return self._is_scanning

    # Usage examples:
    def refresh_shots(self) -> bool:
        """Refresh previous shots list."""
        if not self._acquire_scan_lock():
            return False

        try:
            # ... scanning logic ...
            return True
        except Exception as e:
            self.logger.error(f"Failed to refresh previous shots: {e}")
            self._release_scan_lock()
            return False

    def _on_scan_finished(self, approved_shots: list[dict[str, str]]) -> None:
        """Handle scan completion."""
        try:
            # ... process results ...
        finally:
            self._release_scan_lock()
            # ... cleanup ...

    def is_scanning(self) -> bool:
        """Check if currently scanning."""
        return self._check_scanning_state()
```

**Benefits:**
- Eliminates 5 repetitions of mutex pattern
- Centralizes lock management
- Easier to audit thread safety
- Single point for debugging/logging

**Testing:**
1. Verify all existing tests still pass
2. Add test for concurrent refresh_shots() calls
3. Check lock is always released (even on exceptions)

---

### 1.4 Quick Win: Extract CSS to External File
**File:** `main_window.py:919-1025`
**Time:** 15 minutes
**Risk:** Very Low

**Problem:** 130 lines of CSS embedded in Python file makes both harder to maintain.

**Solution:**

**Step 1:** Create stylesheet file:
```bash
mkdir -p styles
```

**Step 2:** Create `styles/tab_widget.qss`:
```css
/* Tab bar - disable focus indicators */
QTabBar {
    qproperty-drawBase: 0;
}

/* Base tab styling - professional proportions */
QTabBar::tab {
    min-width: 120px;
    font-size: 14px;
    font-weight: 400;
    border: none;
    outline: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {accent_light},
        stop:1 {accent_base}
    );
    color: white;
    font-weight: 500;
}

QTabBar::tab:!selected {
    background: #f5f5f5;
    color: #666;
    margin-top: 2px;
}

QTabBar::tab:!selected:hover {
    background: #e8e8e8;
    color: #333;
}

/* Focus state - subtle glow instead of dotted outline */
QTabBar::tab:focus {
    outline: none;
    border: none;
    box-shadow: 0 0 0 2px {accent_light}40;
}

/* Tab content area */
QTabWidget::pane {
    border: none;
    background-color: white;
}
```

**Step 3:** Update `main_window.py`:
```python
def _update_tab_accent_color(self, index: int) -> None:
    """Update tab styling based on selected tab."""
    accent_colors = {
        0: ("#2196F3", "#1976D2"),  # My Shots - Blue
        1: ("#9C27B0", "#7B1FA2"),  # Other 3DE Scenes - Purple
        2: ("#FF9800", "#F57C00"),  # Previous Shots - Orange
    }

    accent_base, accent_light = accent_colors.get(index, ("#2196F3", "#1976D2"))

    # Load stylesheet from file
    style_path = Path(__file__).parent / "styles" / "tab_widget.qss"
    with open(style_path, encoding="utf-8") as f:
        template = f.read()

    # Replace color placeholders
    stylesheet = template.format(
        accent_base=accent_base,
        accent_light=accent_light
    )

    self.tab_widget.tabBar().setStyleSheet(stylesheet)
```

**Benefits:**
- Separates concerns (styling vs logic)
- Syntax highlighting in QSS files
- Easier to modify styles
- Could be hot-reloaded during development

**Testing:**
1. Visual verification: tabs look identical
2. Check all 3 tabs have correct accent colors
3. Verify hover/focus states work

---

### 1.5 Quick Win: Consolidate cleanup() Methods
**Files:** `shot_item_model.py:194-219`, `threede_item_model.py:231-261`, `previous_shots_item_model.py:224-258`
**Time:** 30 minutes
**Risk:** Low

**Problem:** Nearly identical `cleanup()` method duplicated in 3 subclasses (~90 lines total).

**Solution:**

**Step 1:** Add to `base_item_model.py`:
```python
class BaseItemModel(LoggingMixin, QAbstractListModel, Generic[T]):
    """Base class for list-based item models with lazy thumbnail loading."""

    # ... existing code ...

    def cleanup(self) -> None:
        """Clean up resources before deletion.

        Stops timers, clears caches, disconnects signals.
        Subclasses should override _cleanup_subclass_resources() for additional cleanup.
        """
        self.logger.debug(f"Cleaning up {self.__class__.__name__}")

        # Stop and delete thumbnail timer
        if hasattr(self, "_thumbnail_timer") and self._thumbnail_timer is not None:
            self._thumbnail_timer.stop()
            self._thumbnail_timer.deleteLater()
            self._thumbnail_timer = None

        # Clear thumbnail cache
        self.clear_thumbnail_cache()

        # Clear selection
        self._selected_index = QPersistentModelIndex()
        with QMutexLocker(self._cache_mutex):
            self._selected_item = None

        # Disconnect base signals safely
        self._disconnect_signals([
            self.items_updated,
            self.thumbnail_loaded,
            self.selection_changed,
            self.show_filter_changed,
        ])

        # Let subclasses clean up their specific resources
        self._cleanup_subclass_resources()

        self.logger.debug(f"{self.__class__.__name__} cleanup complete")

    def _cleanup_subclass_resources(self) -> None:
        """Override in subclasses for additional cleanup.

        Called after base cleanup completes.
        """
        pass

    def _disconnect_signals(self, signals: list[Signal]) -> None:
        """Safely disconnect list of signals.

        Args:
            signals: List of Signal objects to disconnect
        """
        for signal in signals:
            try:
                signal.disconnect()
            except (RuntimeError, TypeError) as e:
                # Signal already disconnected or never connected
                self.logger.debug(f"Could not disconnect signal {signal}: {e}")
```

**Step 2:** Simplify subclasses:
```python
# shot_item_model.py
class ShotItemModel(BaseItemModel[Shot]):
    """Item model for shot grid display."""

    def _cleanup_subclass_resources(self) -> None:
        """Clean up shot-specific resources."""
        # Any shot-specific cleanup would go here
        # (currently none needed)
        pass

# threede_item_model.py
class ThreeDEItemModel(BaseItemModel[ThreeDEScene]):
    """Item model for 3DE scene grid display."""

    def _cleanup_subclass_resources(self) -> None:
        """Clean up 3DE-specific resources."""
        try:
            self.loading_progress.disconnect()
        except (RuntimeError, TypeError):
            pass

# previous_shots_item_model.py
class PreviousShotsItemModel(BaseItemModel[Shot]):
    """Item model for previous shots with active shot filtering."""

    def _cleanup_subclass_resources(self) -> None:
        """Clean up previous shots-specific resources."""
        # Any previous-shots-specific cleanup would go here
        # (currently none needed)
        pass
```

**Benefits:**
- Eliminates ~90 lines of duplication
- Single source of truth for cleanup logic
- Template Method pattern ensures consistent cleanup
- Easy to extend with subclass-specific cleanup

**Testing:**
1. Run all existing cleanup tests
2. Verify no memory leaks after cleanup
3. Check all timers stopped
4. Verify signals disconnected

---

### 1.6 Quick Win: Centralize Feature Flags
**File:** `main_window.py` (lines 269, 312, 329, 675)
**Time:** 30 minutes
**Risk:** Very Low

**Problem:** Feature flags scattered across codebase make them hard to find and manage.

**Solution:**

**Step 1:** Add to `config.py`:
```python
"""Configuration constants for ShotBot application."""

import os
from pathlib import Path


class FeatureFlags:
    """Application feature flags and environment checks.

    Centralizes all environment variable checks for easier management
    and documentation.
    """

    @staticmethod
    def use_simplified_launcher() -> bool:
        """Check if simplified launcher should be used.

        Set via: EXPORT USE_SIMPLIFIED_LAUNCHER=true
        Default: false
        """
        return os.environ.get("USE_SIMPLIFIED_LAUNCHER", "false").lower() == "true"

    @staticmethod
    def is_test_environment() -> bool:
        """Check if running in pytest test environment.

        Auto-detected by pytest setting PYTEST_CURRENT_TEST.
        """
        return "PYTEST_CURRENT_TEST" in os.environ

    @staticmethod
    def skip_initial_load() -> bool:
        """Check if initial data load should be skipped.

        Set via: EXPORT SHOTBOT_NO_INITIAL_LOAD=1
        Useful for: UI testing, screenshot capture, performance testing
        Default: false
        """
        return "SHOTBOT_NO_INITIAL_LOAD" in os.environ

    @staticmethod
    def is_debug_mode() -> bool:
        """Check if debug mode is enabled.

        Set via: EXPORT SHOTBOT_DEBUG=1
        Enables: Verbose logging, performance metrics, debug UI
        Default: false
        """
        return os.environ.get("SHOTBOT_DEBUG", "").strip() == "1"

    @staticmethod
    def is_mock_mode() -> bool:
        """Check if running in mock mode.

        Auto-detected via: --mock CLI flag setting SHOTBOT_MODE=mock
        """
        return os.environ.get("SHOTBOT_MODE") == "mock"


class ThumbnailConfig:
    """Thumbnail loading configuration."""

    # Delay before starting lazy thumbnail load after scroll (ms)
    LAZY_LOAD_DELAY_MS = 100

    # Extra items to load beyond visible range
    SCROLL_BUFFER_SIZE = 5

    # Maximum thumbnail size for display
    MAX_THUMBNAIL_SIZE = 512

    # Default thumbnail size
    DEFAULT_THUMBNAIL_SIZE = 256


# ... rest of config.py ...
```

**Step 2:** Update `main_window.py`:
```python
from config import FeatureFlags, ThumbnailConfig

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)

        # ... existing setup ...

        # Use centralized feature flags
        if FeatureFlags.use_simplified_launcher():
            self.command_launcher = SimplifiedLauncher()
        else:
            self.command_launcher = LauncherDialog(self)

        # ... more setup ...

        # Conditionally create 3DE controller
        if not FeatureFlags.is_test_environment():
            self.threede_controller = ThreeDEController(self)
            self.threede_controller.initialize()

        # Initial data load
        if not FeatureFlags.skip_initial_load():
            self._load_initial_data()
```

**Step 3:** Update `base_item_model.py`:
```python
from config import ThumbnailConfig

class BaseItemModel(LoggingMixin, QAbstractListModel, Generic[T]):
    def __init__(self, cache_manager, parent):
        # ... existing code ...

        # Use config constants instead of magic numbers
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setInterval(ThumbnailConfig.LAZY_LOAD_DELAY_MS)
        self._thumbnail_timer.setSingleShot(True)

    def _load_visible_thumbnails(self) -> None:
        """Load thumbnails for visible items only."""
        # ... existing code ...

        # Use config constant
        buffer_size = ThumbnailConfig.SCROLL_BUFFER_SIZE
        start = max(0, first_visible - buffer_size)
        end = min(len(self._items), last_visible + buffer_size + 1)
```

**Benefits:**
- Single source of truth for all feature flags
- Self-documenting with docstrings
- Easy to add new flags
- Grep-friendly: all flags in one place

**Testing:**
1. Test with each flag enabled/disabled
2. Verify flag combinations work
3. Check docstrings are accurate

---

### 1.7 Quick Win: Remove Dead Code and Stubs
**Files:** `main_window.py:915`, `cache_manager.py:66-78`
**Time:** 10 minutes
**Risk:** Very Low

**Problem:** Dead code and stub classes clutter the codebase.

**Solution:**

**Step 1:** Remove from `main_window.py` (lines 909-915):
```python
# DELETE THIS:
def _update_tab_accent_color(self, index: int) -> None:
    """Update tab styling based on selected tab."""
    tab_colors = {
        0: ("#2196F3", "#1976D2"),  # My Shots - Blue
        1: ("#9C27B0", "#7B1FA2"),  # Other 3DE Scenes - Purple
        2: ("#FF9800", "#F57C00"),  # Previous Shots - Orange
    }
    _ = tab_colors.get(index, ("#2196F3", "#1976D2"))  # DELETE: unused
    # ... rest of method ...
```

**Step 2:** Remove from `cache_manager.py` (lines 66-78):
```python
# DELETE THESE CLASSES:
class ThumbnailCacheResult:
    """Stub for backward compatibility - no longer used."""
    def __init__(self) -> None:
        self.future = None
        self.path = None
        self.is_complete = False


class ThumbnailCacheLoader:
    """Stub for backward compatibility - no longer used."""
    pass
```

**Step 3:** Check for any imports:
```bash
# Search for usage
grep -r "ThumbnailCacheResult" .
grep -r "ThumbnailCacheLoader" .
```

**Step 4:** Remove any imports found (if any).

**Testing:**
1. Run full test suite
2. Verify no import errors
3. Check application starts normally

---

## Phase 2: High-Impact DRY Violations (Week 2)
**Estimated Time:** 15 hours
**Risk Level:** Low

### 2.1 Extract ShotFilterMixin
**Files:** `base_shot_model.py:283-341`, `previous_shots_model.py:308-366`
**Time:** 3 hours
**Risk:** Low

**Problem:** 59 lines of identical filtering logic duplicated between two models.

**Solution:**

**Step 1:** Create `filter_mixin.py`:
```python
"""Mixin providing shot filtering functionality."""

from abc import abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from type_definitions import Shot
    from logging_mixin import ContextualLogger


class ShotFilterMixin:
    """Mixin providing shot filtering functionality.

    Classes using this mixin must provide:
    - _get_shot_list() -> list[Shot]: Return the list to filter
    - logger: LoggingMixin logger

    Example:
        class MyModel(LoggingMixin, ShotFilterMixin, QObject):
            def _get_shot_list(self) -> list[Shot]:
                return self._shots
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._filter_show: str | None = None
        self._filter_text: str | None = None

    @abstractmethod
    def _get_shot_list(self) -> list["Shot"]:
        """Get the shot list to filter.

        Must be implemented by subclass.

        Returns:
            List of shots to apply filters to
        """
        pass

    @property
    @abstractmethod
    def logger(self) -> "ContextualLogger":
        """Logger instance from LoggingMixin.

        Must be provided by subclass (typically via LoggingMixin).
        """
        pass

    def set_show_filter(self, show: str | None) -> None:
        """Set the show filter.

        Args:
            show: Show name to filter by, or None for all shows
        """
        self._filter_show = show
        self.logger.info(f"Show filter set to: {show if show else 'All Shows'}")

    def get_show_filter(self) -> str | None:
        """Get the current show filter.

        Returns:
            Current show filter, or None if no filter active
        """
        return self._filter_show

    def set_text_filter(self, text: str | None) -> None:
        """Set the text filter for real-time search.

        Args:
            text: Text to filter by (searches in shot full_name), or None to clear
        """
        self._filter_text = text
        self.logger.info(f"Text filter set to: '{text if text else ''}'")

    def get_text_filter(self) -> str | None:
        """Get the current text filter.

        Returns:
            Current text filter, or None if no filter active
        """
        return self._filter_text

    def clear_filters(self) -> None:
        """Clear all filters."""
        self._filter_show = None
        self._filter_text = None
        self.logger.info("All filters cleared")

    def get_filtered_shots(self) -> list["Shot"]:
        """Get shots filtered by show and text filters.

        Returns:
            Filtered list of shots
        """
        shots = self._get_shot_list()

        # Apply show filter
        if self._filter_show is not None:
            shots = [shot for shot in shots if shot.show == self._filter_show]

        # Apply text filter (case-insensitive substring match)
        if self._filter_text:
            filter_lower = self._filter_text.lower()
            shots = [shot for shot in shots if filter_lower in shot.full_name.lower()]

        return shots

    def get_available_shows(self) -> set[str]:
        """Get all unique show names from current shots.

        Returns:
            Set of unique show names
        """
        return set(shot.show for shot in self._get_shot_list())

    def has_active_filters(self) -> bool:
        """Check if any filters are currently active.

        Returns:
            True if show or text filter is active
        """
        return self._filter_show is not None or bool(self._filter_text)
```

**Step 2:** Update `base_shot_model.py`:
```python
from filter_mixin import ShotFilterMixin

class BaseShotModel(LoggingMixin, ShotFilterMixin, QObject):
    """Abstract base class for shot data sources."""

    def __init__(self, cache_manager: CacheManager | None = None):
        super().__init__()
        self._cache_manager = cache_manager or CacheManager()
        self._shots: list[Shot] = []
        # Note: _filter_show and _filter_text now from ShotFilterMixin

    def _get_shot_list(self) -> list[Shot]:
        """Implementation of ShotFilterMixin requirement."""
        return self._shots

    # DELETE lines 283-341 (now in ShotFilterMixin)
    # Keep all other methods...
```

**Step 3:** Update `previous_shots_model.py`:
```python
from filter_mixin import ShotFilterMixin

class PreviousShotsModel(LoggingMixin, ShotFilterMixin, QObject):
    """Model for discovering and managing user's previous shots."""

    def __init__(self, cache_manager: CacheManager | None = None):
        super().__init__()
        self._cache_manager = cache_manager or CacheManager()
        self._previous_shots: list[Shot] = []
        # Note: _filter_show and _filter_text now from ShotFilterMixin

    def _get_shot_list(self) -> list[Shot]:
        """Implementation of ShotFilterMixin requirement."""
        return self._previous_shots

    # DELETE lines 308-366 (now in ShotFilterMixin)
    # Keep all other methods...
```

**Benefits:**
- Eliminates 59 lines of duplication (2x59 = 118 total)
- Single source of truth for filtering logic
- Easy to extend with new filter types
- Follows existing mixin pattern in codebase
- Type-safe with abstract method enforcement

**Testing:**
1. Run all existing filter tests (should pass unchanged)
2. Test show filter on both My Shots and Previous Shots tabs
3. Test text filter with various search terms
4. Test `get_available_shows()` accuracy
5. Test `has_active_filters()` correctness
6. Test filter combinations

**Migration Checklist:**
- [ ] Create `filter_mixin.py`
- [ ] Update `base_shot_model.py` to use mixin
- [ ] Update `previous_shots_model.py` to use mixin
- [ ] Run test suite
- [ ] Manual UI testing of all filter functionality
- [ ] Update type checking (if needed)

---

### 2.2 Extract Context Manager Logic
**File:** `logging_mixin.py:96-126, 312-342`
**Time:** 1 hour
**Risk:** Very Low

**Problem:** Context manager logic duplicated between `ContextualLogger.context()` and global `log_context()` function.

**Solution:**
```python
# logging_mixin.py

def _manage_log_context(**kwargs: str) -> Generator[None, None, None]:
    """Internal context manager for logging context.

    Manages context storage on thread-local storage, ensuring proper
    cleanup even on exceptions.

    Args:
        **kwargs: Key-value pairs to add to logging context

    Yields:
        None (context manager)
    """
    # Preserve current context
    current_context = getattr(_context_storage, "context", {})
    new_context = {**current_context, **kwargs}
    old_context = getattr(_context_storage, "context", None)

    try:
        # Set new context
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


class ContextualLogger:
    """Logger with structured context support."""

    @contextmanager
    def context(self, **kwargs: str) -> Generator[None, None, None]:
        """Add structured context to log messages.

        Args:
            **kwargs: Key-value pairs to add to context

        Yields:
            None (context manager)

        Example:
            with logger.context(user="alice", action="login"):
                logger.info("User action")  # Logs with context
        """
        yield from _manage_log_context(**kwargs)


@contextmanager
def log_context(**kwargs: str) -> Generator[None, None, None]:
    """Global context manager for structured logging.

    Args:
        **kwargs: Key-value pairs to add to logging context

    Yields:
        None (context manager)

    Example:
        with log_context(request_id="123"):
            logger.info("Processing")  # Logs with context
    """
    yield from _manage_log_context(**kwargs)
```

**Benefits:**
- Eliminates ~30 lines of duplication
- Single implementation of context management logic
- Easier to debug and enhance
- Both APIs remain unchanged

**Testing:**
1. Run existing logging tests
2. Test nested contexts
3. Test exception handling
4. Verify thread safety

---

### 2.3 Simplify Logging Decorator
**File:** `logging_mixin.py:171-287`
**Time:** 4 hours
**Risk:** Low

**Problem:** 117 lines with 4-5 levels of nesting for different logging configurations.

**Solution:**

```python
"""Simplified logging decorator with extracted helpers."""

import functools
import logging
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, cast

P = ParamSpec("P")
T = TypeVar("T")


def log_execution(
    func: Callable[P, T] | None = None,
    *,
    include_args: bool = False,
    include_result: bool = False,
    log_level: int = logging.INFO,
) -> Callable[[Callable[P, T]], Callable[P, T]] | Callable[P, T]:
    """Decorator to log function execution with timing.

    Args:
        func: Function to decorate (when used without parentheses)
        include_args: Whether to include function arguments in logs
        include_result: Whether to include return value in logs
        log_level: Logging level to use (DEBUG, INFO, etc.)

    Returns:
        Decorated function

    Example:
        @log_execution
        def my_func(): ...

        @log_execution(include_args=True, log_level=logging.DEBUG)
        def my_func(x, y): ...
    """

    def decorator(inner_func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(inner_func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            logger = _get_logger_for_func(args, inner_func)
            func_name = inner_func.__qualname__
            start_time = time.time()

            # Log function start
            _log_function_start(logger, func_name, log_level, include_args, args, kwargs)

            try:
                # Execute function
                result = inner_func(*args, **kwargs)
                execution_time = time.time() - start_time

                # Log success
                _log_function_success(
                    logger, func_name, log_level,
                    execution_time, include_result, result
                )

                return result

            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(
                    f"{func_name} failed after {execution_time:.3f}s: {type(e).__name__}: {e}"
                )
                raise

        return wrapper

    # Handle both @log_execution and @log_execution() syntax
    return decorator if func is None else decorator(func)


def _get_logger_for_func(args: tuple, func: Callable) -> ContextualLogger:
    """Extract logger from instance or create module logger.

    Args:
        args: Function arguments (check first for self.logger)
        func: Function being decorated

    Returns:
        Logger instance to use
    """
    # Check if first arg has a logger attribute (instance method)
    if args and hasattr(args[0], "logger") and hasattr(args[0].logger, "info"):
        return cast("ContextualLogger", args[0].logger)

    # Fall back to module logger
    return ContextualLogger(logging.getLogger(func.__module__))


def _log_function_start(
    logger: ContextualLogger,
    func_name: str,
    log_level: int,
    include_args: bool,
    args: tuple,
    kwargs: dict,
) -> None:
    """Log function start with appropriate detail level.

    Args:
        logger: Logger instance
        func_name: Qualified function name
        log_level: Logging level
        include_args: Whether to include arguments
        args: Function positional arguments
        kwargs: Function keyword arguments
    """
    # Skip logging if level too high
    if log_level > logging.INFO:
        return

    # Format message based on configuration
    if log_level <= logging.DEBUG and include_args:
        args_str = _format_args_safely(args)
        kwargs_str = _format_kwargs_safely(kwargs)
        message = f"Starting {func_name}({args_str}{', ' if args_str and kwargs_str else ''}{kwargs_str})"
        logger.debug(message)
    elif log_level == logging.DEBUG:
        logger.debug(f"Starting {func_name}")
    elif log_level == logging.INFO:
        logger.info(f"Starting {func_name}")


def _log_function_success(
    logger: ContextualLogger,
    func_name: str,
    log_level: int,
    execution_time: float,
    include_result: bool,
    result: Any,
) -> None:
    """Log successful function execution.

    Args:
        logger: Logger instance
        func_name: Qualified function name
        log_level: Logging level
        execution_time: Execution time in seconds
        include_result: Whether to include return value
        result: Function return value
    """
    # Skip logging if level too high
    if log_level > logging.INFO:
        return

    # Build message
    time_str = f"{execution_time:.3f}s"
    result_str = ""
    if include_result and result is not None:
        result_str = f" -> {_format_value_safely(result)}"

    message = f"{func_name} completed in {time_str}{result_str}"

    # Log at appropriate level
    if log_level == logging.DEBUG:
        logger.debug(message)
    elif log_level == logging.INFO:
        logger.info(message)


def _format_args_safely(args: tuple) -> str:
    """Format function arguments safely for logging.

    Args:
        args: Function positional arguments

    Returns:
        Formatted argument string
    """
    # Skip self/cls if present (first arg with logger attribute)
    args_to_format = args[1:] if args and hasattr(args[0], "logger") else args
    return ", ".join(_format_value_safely(arg) for arg in args_to_format)


def _format_kwargs_safely(kwargs: dict) -> str:
    """Format keyword arguments safely for logging.

    Args:
        kwargs: Function keyword arguments

    Returns:
        Formatted keyword argument string
    """
    return ", ".join(f"{k}={_format_value_safely(v)}" for k, v in kwargs.items())


def _format_value_safely(value: Any) -> str:
    """Format a value safely for logging.

    Handles basic types with repr(), complex types with type name.

    Args:
        value: Value to format

    Returns:
        Formatted string representation
    """
    if isinstance(value, str | int | float | bool | type(None)):
        return repr(value)
    return f"<{type(value).__name__}>"
```

**Benefits:**
- Reduces nesting from 4-5 levels to 1-2 levels
- Each helper has single responsibility
- Easier to test individual functions
- More readable main decorator logic
- Better error messages

**Testing:**
1. Test decorator without args: `@log_execution`
2. Test decorator with args: `@log_execution(include_args=True)`
3. Test all log levels
4. Test with instance methods (self.logger)
5. Test with module functions
6. Test exception handling
7. Verify performance overhead is minimal

---

## Phase 3: Complexity Reduction (Week 3-4)
**Estimated Time:** 20 hours
**Risk Level:** Medium

### 3.1 Refactor Thumbnail Discovery System
**File:** `utils.py:163-873`
**Time:** 12 hours (2 days)
**Risk:** Medium

**Problem:** 710 lines of deeply nested thumbnail discovery logic across 5 functions.

**Current Functions:**
- `find_turnover_plate_thumbnail()`: 141 lines
- `find_undistorted_jpeg_thumbnail()`: 78 lines
- `find_user_workspace_jpeg_thumbnail()`: 98 lines
- `find_any_publish_thumbnail()`: 112 lines
- `find_shot_thumbnail()`: 82 lines (orchestrator)

**Solution: Configuration-Driven Strategy Pattern**

**Step 1:** Create `thumbnail_strategies.py`:
```python
"""Configuration-driven thumbnail discovery strategies."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class ThumbnailSearchStrategy:
    """Configuration for a thumbnail search strategy.

    Attributes:
        name: Human-readable strategy name
        priority: Lower number = higher priority (try first)
        path_pattern: Path pattern with {show}, {sequence}, {shot} placeholders
        extensions: List of file extensions to search for
        recursive: Whether to search recursively
        max_depth: Maximum recursion depth (if recursive=True)
        validator: Optional function to validate candidate files
    """
    name: str
    priority: int
    path_pattern: str
    extensions: list[str]
    recursive: bool = False
    max_depth: int = 3
    validator: Callable[[Path], bool] | None = None


def _validate_turnover_exr(path: Path) -> bool:
    """Validate turnover EXR file.

    Args:
        path: Path to potential EXR file

    Returns:
        True if file is a valid turnover EXR
    """
    try:
        # Check file size (skip if > 50MB)
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > 50:
            return False

        # Check filename has frame number
        return any(char.isdigit() for char in path.stem)

    except (OSError, IOError):
        return False


def _validate_first_frame(path: Path) -> bool:
    """Validate file is likely a first frame.

    Args:
        path: Path to potential image file

    Returns:
        True if filename suggests first frame (1001, 0001, etc.)
    """
    return any(pattern in path.name.lower() for pattern in ["1001", "0001", ".1.", "_1."])


# Strategy configuration
THUMBNAIL_STRATEGIES = [
    ThumbnailSearchStrategy(
        name="editorial_cutref",
        priority=1,
        path_pattern="{shows_root}/{show}/shots/{sequence}/{sequence}_{shot}/publish/editorial/cutref",
        extensions=[".jpg", ".jpeg", ".png"],
        recursive=False,
    ),
    ThumbnailSearchStrategy(
        name="undistorted_jpeg",
        priority=2,
        path_pattern="{shows_root}/{show}/shots/{sequence}/{sequence}_{shot}/publish/mm/default/*/undistorted_plate/*/jpeg",
        extensions=[".jpg", ".jpeg"],
        recursive=False,
    ),
    ThumbnailSearchStrategy(
        name="user_workspace_jpeg",
        priority=3,
        path_pattern="{shows_root}/{show}/shots/{sequence}/{sequence}_{shot}/user/*/mm/nuke/outputs/mm-default/*/*/undistorted_plate/*/*/jpeg",
        extensions=[".jpg", ".jpeg"],
        recursive=False,
    ),
    ThumbnailSearchStrategy(
        name="turnover_exr",
        priority=4,
        path_pattern="{shows_root}/{show}/shots/{sequence}/{sequence}_{shot}/publish/turnover/plate/*/*/v001/exr",
        extensions=[".exr"],
        recursive=False,
        validator=_validate_turnover_exr,
    ),
    ThumbnailSearchStrategy(
        name="any_publish_image",
        priority=5,
        path_pattern="{shows_root}/{show}/shots/{sequence}/{sequence}_{shot}/publish",
        extensions=[".jpg", ".jpeg", ".png", ".exr"],
        recursive=True,
        max_depth=5,
        validator=_validate_first_frame,
    ),
]
```

**Step 2:** Create simplified search engine:
```python
# thumbnail_discovery.py
"""Simplified thumbnail discovery engine."""

import logging
from glob import glob
from pathlib import Path

from thumbnail_strategies import THUMBNAIL_STRATEGIES, ThumbnailSearchStrategy

logger = logging.getLogger(__name__)


def find_shot_thumbnail(
    shows_root: str,
    show: str,
    sequence: str,
    shot: str,
) -> Path | None:
    """Find thumbnail for a shot using configured strategies.

    Args:
        shows_root: Root directory for all shows
        show: Show name
        sequence: Sequence name
        shot: Shot name

    Returns:
        Path to thumbnail file, or None if not found
    """
    context = {
        "shows_root": shows_root,
        "show": show,
        "sequence": sequence,
        "shot": shot,
    }

    # Try each strategy in priority order
    for strategy in sorted(THUMBNAIL_STRATEGIES, key=lambda s: s.priority):
        logger.debug(f"Trying thumbnail strategy: {strategy.name}")

        thumbnail = _search_with_strategy(strategy, context)

        if thumbnail:
            logger.info(
                f"Found thumbnail using {strategy.name}: {thumbnail.name} "
                f"({thumbnail.stat().st_size / 1024:.1f} KB)"
            )
            return thumbnail

    logger.warning(f"No thumbnail found for {show}/{sequence}/{shot}")
    return None


def _search_with_strategy(
    strategy: ThumbnailSearchStrategy,
    context: dict[str, str],
) -> Path | None:
    """Execute a thumbnail search strategy.

    Args:
        strategy: Search strategy configuration
        context: Path substitution context (show, sequence, shot, etc.)

    Returns:
        Path to thumbnail file, or None if not found
    """
    # Expand path pattern with context
    search_path = strategy.path_pattern.format(**context)

    # Handle glob patterns (with wildcards)
    if "*" in search_path:
        return _search_glob_pattern(
            search_path,
            strategy.extensions,
            strategy.recursive,
            strategy.max_depth,
            strategy.validator,
        )

    # Handle direct paths
    return _search_direct_path(
        Path(search_path),
        strategy.extensions,
        strategy.validator,
    )


def _search_glob_pattern(
    pattern: str,
    extensions: list[str],
    recursive: bool,
    max_depth: int,
    validator: Callable[[Path], bool] | None,
) -> Path | None:
    """Search using glob pattern.

    Args:
        pattern: Glob pattern (may contain wildcards)
        extensions: File extensions to search for
        recursive: Whether to search recursively
        max_depth: Maximum recursion depth
        validator: Optional validation function

    Returns:
        First matching path, or None
    """
    # Expand glob pattern
    for path_str in glob(pattern, recursive=recursive):
        path = Path(path_str)

        if path.is_dir():
            # Search directory for image files
            for ext in extensions:
                # Limit recursion depth
                search_pattern = f"**/*{ext}" if recursive else f"*{ext}"

                for file in path.glob(search_pattern):
                    if validator is None or validator(file):
                        return file

        elif path.is_file() and path.suffix.lower() in extensions:
            # Direct file match
            if validator is None or validator(path):
                return path

    return None


def _search_direct_path(
    path: Path,
    extensions: list[str],
    validator: Callable[[Path], bool] | None,
) -> Path | None:
    """Search a direct path (no wildcards).

    Args:
        path: Directory path to search
        extensions: File extensions to search for
        validator: Optional validation function

    Returns:
        First matching file, or None
    """
    if not path.exists() or not path.is_dir():
        return None

    # Search for files with matching extensions
    for ext in extensions:
        for file in path.glob(f"*{ext}"):
            if file.is_file() and (validator is None or validator(file)):
                return file

    return None
```

**Step 3:** Update `utils.py`:
```python
# utils.py (simplified)
"""Utility functions for ShotBot."""

from thumbnail_discovery import find_shot_thumbnail

# Re-export for backward compatibility
__all__ = ["find_shot_thumbnail"]

# DELETE lines 163-873 (old implementation)
```

**Benefits:**
- **Reduces from 710 lines to ~200 lines** (72% reduction)
- Configuration-driven: easy to add/modify strategies
- Each strategy is declarative and self-documenting
- Single generic search engine
- Eliminates deeply nested conditionals
- Validator functions are testable in isolation
- Strategy priority is explicit and configurable

**Migration Plan:**
1. Implement new system alongside old code
2. Add feature flag: `USE_NEW_THUMBNAIL_DISCOVERY`
3. Run both implementations in parallel, compare results
4. Fix any discrepancies
5. Switch default to new implementation
6. Remove old code after validation period

**Testing Strategy:**
```python
# test_thumbnail_discovery.py
import pytest
from thumbnail_discovery import find_shot_thumbnail
from thumbnail_strategies import THUMBNAIL_STRATEGIES

def test_editorial_cutref_priority():
    """Editorial cutref should be tried first."""
    assert THUMBNAIL_STRATEGIES[0].name == "editorial_cutref"
    assert THUMBNAIL_STRATEGIES[0].priority == 1

def test_strategy_priorities_unique():
    """Each strategy should have unique priority."""
    priorities = [s.priority for s in THUMBNAIL_STRATEGIES]
    assert len(priorities) == len(set(priorities))

def test_find_thumbnail_real_shot(mock_vfx_env):
    """Test thumbnail discovery on real shot structure."""
    thumbnail = find_shot_thumbnail(
        mock_vfx_env.root,
        "broken_eggs",
        "be",
        "0010",
    )
    assert thumbnail is not None
    assert thumbnail.exists()

def test_find_thumbnail_fallback_chain(mock_vfx_env):
    """Test fallback to lower-priority strategies."""
    # Remove high-priority options, verify fallback works
    ...

@pytest.mark.parametrize("strategy", THUMBNAIL_STRATEGIES)
def test_strategy_path_patterns(strategy, mock_vfx_env):
    """Verify all strategy path patterns are valid."""
    context = {
        "shows_root": mock_vfx_env.root,
        "show": "broken_eggs",
        "sequence": "be",
        "shot": "0010",
    }
    path = strategy.path_pattern.format(**context)
    # Verify path format is reasonable
    assert "{" not in path  # All placeholders expanded
```

**Estimated Breakdown:**
- Design and implement strategy system: 4 hours
- Implement search engine: 3 hours
- Testing and validation: 3 hours
- Migration and cleanup: 2 hours

---

### 3.2 Split MainWindow into Focused Classes
**File:** `main_window.py` (1,413 lines)
**Time:** 8 hours (1 day)
**Risk:** Medium

**Problem:** MainWindow has too many responsibilities, making it hard to test and maintain.

**Current Responsibilities:**
- UI layout and widget creation (126 lines in `_setup_ui`)
- Menu bar construction (94 lines in `_setup_menu`)
- Signal routing (66 lines in `_connect_signals`)
- Tab management and switching
- Show filtering coordination
- Shot selection handling
- Launcher integration
- Settings persistence
- CSS styling (now external after Phase 1)

**Solution: Extract Focused Classes**

**Step 1:** Create `tab_coordinator.py`:
```python
"""Coordinates tab-specific operations and filtering."""

from typing import cast

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox, QTabWidget

from base_item_model import BaseItemModel
from base_shot_model import BaseShotModel
from logging_mixin import LoggingMixin


class TabCoordinator(LoggingMixin, QObject):
    """Coordinates tab switching, filtering, and per-tab state.

    Responsibilities:
    - Track current tab state
    - Coordinate show filter updates across tabs
    - Coordinate text filter updates across tabs
    - Manage per-tab filter UI state

    Signals:
        tab_changed: Emitted when active tab changes (index, tab_name)
    """

    tab_changed = Signal(int, str)  # index, name

    def __init__(
        self,
        tab_widget: QTabWidget,
        parent: QObject | None = None,
    ):
        """Initialize tab coordinator.

        Args:
            tab_widget: Main tab widget to coordinate
            parent: Parent QObject
        """
        super().__init__(parent)
        self._tab_widget = tab_widget
        self._tab_configs: dict[int, TabConfig] = {}

        # Connect tab change signal
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

    def register_tab(
        self,
        index: int,
        name: str,
        item_model: BaseItemModel,
        data_model: BaseShotModel | None,
        show_filter_combo: QComboBox | None,
    ) -> None:
        """Register a tab for coordination.

        Args:
            index: Tab index
            name: Tab display name
            item_model: Item model for this tab
            data_model: Data model for this tab (if applicable)
            show_filter_combo: Show filter combo box (if applicable)
        """
        config = TabConfig(
            index=index,
            name=name,
            item_model=item_model,
            data_model=data_model,
            show_filter_combo=show_filter_combo,
        )
        self._tab_configs[index] = config
        self.logger.debug(f"Registered tab: {name} (index {index})")

    def apply_show_filter(self, tab_index: int, show: str) -> None:
        """Apply show filter to specified tab.

        Args:
            tab_index: Index of tab to filter
            show: Show name to filter by ("All Shows" for no filter)
        """
        config = self._tab_configs.get(tab_index)
        if not config:
            self.logger.warning(f"Unknown tab index: {tab_index}")
            return

        if not config.data_model:
            self.logger.warning(f"Tab {config.name} has no data model")
            return

        # Apply filter
        filter_value = None if show == "All Shows" else show
        config.data_model.set_show_filter(filter_value)
        filtered_items = config.data_model.get_filtered_shots()
        config.item_model.set_items(filtered_items)

        self.logger.info(
            f"{config.name} show filter: {show} ({len(filtered_items)} items)"
        )

    def apply_text_filter(self, tab_index: int, text: str) -> None:
        """Apply text filter to specified tab.

        Args:
            tab_index: Index of tab to filter
            text: Text to filter by (empty string for no filter)
        """
        config = self._tab_configs.get(tab_index)
        if not config:
            self.logger.warning(f"Unknown tab index: {tab_index}")
            return

        if not config.data_model:
            self.logger.warning(f"Tab {config.name} has no data model")
            return

        # Apply filter
        filter_value = text.strip() if text else None
        config.data_model.set_text_filter(filter_value)
        filtered_items = config.data_model.get_filtered_shots()
        config.item_model.set_items(filtered_items)

        self.logger.debug(
            f"{config.name} text filter: '{filter_value}' ({len(filtered_items)} items)"
        )

    def update_show_filter_combo(self, tab_index: int, available_shows: set[str]) -> None:
        """Update show filter combo box for specified tab.

        Args:
            tab_index: Index of tab to update
            available_shows: Set of available show names
        """
        config = self._tab_configs.get(tab_index)
        if not config or not config.show_filter_combo:
            return

        combo = config.show_filter_combo
        current_filter = combo.currentText()

        # Update combo items
        combo.clear()
        combo.addItem("All Shows")
        combo.addItems(sorted(available_shows))

        # Restore selection if still valid
        index = combo.findText(current_filter)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change.

        Args:
            index: New tab index
        """
        config = self._tab_configs.get(index)
        if config:
            self.logger.debug(f"Tab changed to: {config.name}")
            self.tab_changed.emit(index, config.name)


@dataclass
class TabConfig:
    """Configuration for a single tab."""
    index: int
    name: str
    item_model: BaseItemModel
    data_model: BaseShotModel | None
    show_filter_combo: QComboBox | None
```

**Step 2:** Create `menu_builder.py`:
```python
"""Builds application menu bar."""

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMenu

from logging_mixin import LoggingMixin


class MenuBuilder(LoggingMixin):
    """Builds and manages application menu bar.

    Responsibilities:
    - Create menu structure
    - Connect menu actions to handlers
    - Update menu state based on application state
    """

    def __init__(self, main_window: QMainWindow):
        """Initialize menu builder.

        Args:
            main_window: Main window to build menu for
        """
        super().__init__()
        self._main_window = main_window
        self._actions: dict[str, QAction] = {}

    def build_menu(self) -> None:
        """Build complete menu bar."""
        menu_bar = self._main_window.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")
        self._build_file_menu(file_menu)

        # Edit menu
        edit_menu = menu_bar.addMenu("&Edit")
        self._build_edit_menu(edit_menu)

        # View menu
        view_menu = menu_bar.addMenu("&View")
        self._build_view_menu(view_menu)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        self._build_help_menu(help_menu)

        self.logger.debug("Menu bar built successfully")

    def _build_file_menu(self, menu: QMenu) -> None:
        """Build File menu.

        Args:
            menu: File menu to populate
        """
        # Refresh action
        refresh_action = QAction("&Refresh All", self._main_window)
        refresh_action.setShortcut("Ctrl+R")
        refresh_action.setStatusTip("Refresh all data")
        refresh_action.triggered.connect(self._main_window.refresh_all_data)
        menu.addAction(refresh_action)
        self._actions["refresh_all"] = refresh_action

        menu.addSeparator()

        # Exit action
        exit_action = QAction("E&xit", self._main_window)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.setStatusTip("Exit application")
        exit_action.triggered.connect(self._main_window.close)
        menu.addAction(exit_action)
        self._actions["exit"] = exit_action

    def _build_edit_menu(self, menu: QMenu) -> None:
        """Build Edit menu."""
        # Clear cache action
        clear_cache_action = QAction("Clear &Cache", self._main_window)
        clear_cache_action.setStatusTip("Clear all cached data")
        clear_cache_action.triggered.connect(self._main_window.clear_all_caches)
        menu.addAction(clear_cache_action)
        self._actions["clear_cache"] = clear_cache_action

    def _build_view_menu(self, menu: QMenu) -> None:
        """Build View menu."""
        # Toggle fullscreen
        fullscreen_action = QAction("&Fullscreen", self._main_window)
        fullscreen_action.setShortcut("F11")
        fullscreen_action.setCheckable(True)
        fullscreen_action.triggered.connect(self._main_window.toggle_fullscreen)
        menu.addAction(fullscreen_action)
        self._actions["fullscreen"] = fullscreen_action

    def _build_help_menu(self, menu: QMenu) -> None:
        """Build Help menu."""
        # About action
        about_action = QAction("&About", self._main_window)
        about_action.setStatusTip("About ShotBot")
        about_action.triggered.connect(self._main_window.show_about_dialog)
        menu.addAction(about_action)
        self._actions["about"] = about_action

    def get_action(self, name: str) -> QAction | None:
        """Get action by name.

        Args:
            name: Action name

        Returns:
            QAction if found, None otherwise
        """
        return self._actions.get(name)
```

**Step 3:** Create `signal_router.py`:
```python
"""Routes signals between components."""

from PySide6.QtCore import QObject, Qt

from logging_mixin import LoggingMixin


class SignalRouter(LoggingMixin, QObject):
    """Centralized signal connection management.

    Responsibilities:
    - Connect signals between components
    - Document signal flow
    - Make signal connections explicit and discoverable
    """

    def __init__(self, parent: QObject | None = None):
        """Initialize signal router.

        Args:
            parent: Parent QObject
        """
        super().__init__(parent)
        self._connections: list[tuple[str, str]] = []

    def connect_shot_model_signals(self, shot_model, shot_item_model) -> None:
        """Connect shot model to item model.

        Args:
            shot_model: Shot data model
            shot_item_model: Shot item model
        """
        shot_model.shots_updated.connect(
            shot_item_model.on_shots_updated,
            Qt.ConnectionType.QueuedConnection
        )
        self._log_connection("shot_model.shots_updated", "shot_item_model.on_shots_updated")

    def connect_threede_signals(self, threede_model, threede_item_model) -> None:
        """Connect 3DE model to item model.

        Args:
            threede_model: 3DE scene model
            threede_item_model: 3DE item model
        """
        threede_model.scenes_updated.connect(
            threede_item_model.on_scenes_updated,
            Qt.ConnectionType.QueuedConnection
        )
        self._log_connection("threede_model.scenes_updated", "threede_item_model.on_scenes_updated")

    def connect_grid_view_signals(self, grid_view, slot_handler) -> None:
        """Connect grid view signals to handler.

        Args:
            grid_view: Grid view widget
            slot_handler: Object with handler methods
        """
        if hasattr(grid_view, "show_filter_requested"):
            grid_view.show_filter_requested.connect(slot_handler)
            self._log_connection(f"{grid_view.__class__.__name__}.show_filter_requested", "handler")

        if hasattr(grid_view, "text_filter_requested"):
            grid_view.text_filter_requested.connect(slot_handler)
            self._log_connection(f"{grid_view.__class__.__name__}.text_filter_requested", "handler")

    def _log_connection(self, source: str, target: str) -> None:
        """Log signal connection.

        Args:
            source: Source signal description
            target: Target slot description
        """
        self._connections.append((source, target))
        self.logger.debug(f"Connected: {source} -> {target}")

    def get_connections(self) -> list[tuple[str, str]]:
        """Get list of all registered connections.

        Returns:
            List of (source, target) tuples
        """
        return self._connections.copy()
```

**Step 4:** Refactor `main_window.py`:
```python
"""Simplified main window using coordinators."""

from PySide6.QtWidgets import QMainWindow

from logging_mixin import LoggingMixin
from tab_coordinator import TabCoordinator
from menu_builder import MenuBuilder
from signal_router import SignalRouter


class MainWindow(LoggingMixin, QMainWindow):
    """Simplified main window with delegated responsibilities."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Initialize coordinators
        self._tab_coordinator = TabCoordinator(self.tab_widget, self)
        self._menu_builder = MenuBuilder(self)
        self._signal_router = SignalRouter(self)

        # Setup UI
        self._setup_ui()
        self._menu_builder.build_menu()

        # Register tabs
        self._register_tabs()

        # Connect signals
        self._connect_signals()

    def _register_tabs(self) -> None:
        """Register all tabs with coordinator."""
        self._tab_coordinator.register_tab(
            index=0,
            name="My Shots",
            item_model=self.shot_item_model,
            data_model=self.shot_model,
            show_filter_combo=self.shot_show_filter_combo,
        )

        self._tab_coordinator.register_tab(
            index=1,
            name="Other 3DE Scenes",
            item_model=self.threede_item_model,
            data_model=self.threede_scene_model,
            show_filter_combo=self.threede_show_filter_combo,
        )

        self._tab_coordinator.register_tab(
            index=2,
            name="Previous Shots",
            item_model=self.previous_shots_item_model,
            data_model=self.previous_shots_model,
            show_filter_combo=self.previous_show_filter_combo,
        )

    def _connect_signals(self) -> None:
        """Connect signals using signal router."""
        # Shot model signals
        self._signal_router.connect_shot_model_signals(
            self.shot_model,
            self.shot_item_model
        )

        # 3DE model signals
        self._signal_router.connect_threede_signals(
            self.threede_scene_model,
            self.threede_item_model
        )

        # Grid view signals
        self._signal_router.connect_grid_view_signals(
            self.shot_grid,
            self._on_shot_show_filter_requested
        )

    def _on_shot_show_filter_requested(self, show: str) -> None:
        """Handle show filter request from My Shots tab."""
        self._tab_coordinator.apply_show_filter(0, show)

    # ... other handlers delegate to coordinators ...
```

**Benefits:**
- MainWindow reduced from 1,413 lines to ~400 lines
- Each coordinator has single responsibility
- Easier to test each component
- Signal flow is explicit and documented
- Menu building is isolated
- Tab coordination logic is reusable

**Testing:**
```python
# test_tab_coordinator.py
def test_register_tab():
    """Test tab registration."""
    coordinator = TabCoordinator(QTabWidget())
    coordinator.register_tab(0, "Test Tab", mock_item_model, mock_data_model, None)
    assert 0 in coordinator._tab_configs

def test_apply_show_filter():
    """Test show filter application."""
    coordinator = TabCoordinator(QTabWidget())
    # ... setup ...
    coordinator.apply_show_filter(0, "test_show")
    assert mock_data_model.get_show_filter() == "test_show"

# test_menu_builder.py
def test_build_menu():
    """Test menu construction."""
    window = QMainWindow()
    builder = MenuBuilder(window)
    builder.build_menu()
    assert window.menuBar().actions()  # Menu created

# test_signal_router.py
def test_connect_signals():
    """Test signal connection."""
    router = SignalRouter()
    router.connect_shot_model_signals(mock_shot_model, mock_item_model)
    assert len(router.get_connections()) > 0
```

**Estimated Breakdown:**
- Design coordinator interfaces: 1 hour
- Implement TabCoordinator: 2 hours
- Implement MenuBuilder: 1 hour
- Implement SignalRouter: 1 hour
- Refactor MainWindow: 2 hours
- Testing: 1 hour

---

## Phase 4: Final Cleanup (Week 5)
**Estimated Time:** 10 hours
**Risk Level:** Low-Medium

### 4.1 Split CacheManager
**File:** `cache_manager.py` (729 lines)
**Time:** 6 hours
**Risk:** Medium

**Problem:** CacheManager mixes multiple responsibilities.

**Current Responsibilities:**
1. Thumbnail caching (lines 154-322) - 168 lines
2. Shot data caching (lines 327-376) - 49 lines
3. 3DE scene caching (lines 378-410) - 32 lines
4. Generic data caching (lines 416-462) - 46 lines
5. Cache management (lines 468-530) - 62 lines

**Solution: Split into Focused Classes**

**Step 1:** Create `thumbnail_cache.py`:
```python
"""Thumbnail caching implementation."""

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from logging_mixin import LoggingMixin


class ThumbnailCache(LoggingMixin, QObject):
    """Manages thumbnail caching.

    Responsibilities:
    - Cache thumbnails from various sources
    - Support multiple formats (PIL, Qt, OpenEXR)
    - Handle HDR images for VFX workflows
    """

    thumbnail_cached = Signal(Path)  # Emitted when thumbnail cached

    def __init__(self, cache_dir: Path, parent: QObject | None = None):
        """Initialize thumbnail cache.

        Args:
            cache_dir: Directory for thumbnail cache
            parent: Parent QObject
        """
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cached_thumbnail(
        self,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Get cached thumbnail path if exists.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to cached thumbnail, or None if not cached
        """
        cache_path = self._get_thumbnail_cache_path(show, sequence, shot)
        return cache_path if cache_path.exists() else None

    def cache_thumbnail(
        self,
        source_path: Path,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path | None:
        """Cache thumbnail from source file.

        Args:
            source_path: Path to source image
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to cached thumbnail, or None on error
        """
        try:
            cache_path = self._get_thumbnail_cache_path(show, sequence, shot)

            # Convert and cache
            self._convert_and_cache(source_path, cache_path)

            self.logger.info(f"Cached thumbnail: {cache_path.name}")
            self.thumbnail_cached.emit(cache_path)
            return cache_path

        except Exception as e:
            self.logger.error(f"Failed to cache thumbnail: {e}")
            return None

    def _get_thumbnail_cache_path(
        self,
        show: str,
        sequence: str,
        shot: str,
    ) -> Path:
        """Get cache path for thumbnail.

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path where thumbnail should be cached
        """
        filename = f"{show}_{sequence}_{shot}.jpg"
        return self._cache_dir / filename

    def _convert_and_cache(self, source: Path, dest: Path) -> None:
        """Convert image and save to cache.

        Args:
            source: Source image path
            dest: Destination cache path
        """
        # Implementation from current CacheManager
        # ... (PIL/OpenEXR conversion logic) ...
        pass
```

**Step 2:** Create `data_cache.py`:
```python
"""JSON data caching implementation."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypeVar, Generic

from PySide6.QtCore import QObject

from logging_mixin import LoggingMixin

T = TypeVar("T")


class DataCache(LoggingMixin, QObject, Generic[T]):
    """Manages JSON data caching with TTL.

    Generic cache for any JSON-serializable data.
    """

    CACHE_FORMAT_VERSION = 1

    def __init__(
        self,
        cache_dir: Path,
        cache_name: str,
        ttl_minutes: int = 30,
        parent: QObject | None = None,
    ):
        """Initialize data cache.

        Args:
            cache_dir: Directory for cache files
            cache_name: Name for this cache (used in filename)
            ttl_minutes: Time-to-live in minutes
            parent: Parent QObject
        """
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._cache_name = cache_name
        self._ttl = timedelta(minutes=ttl_minutes)
        self._cache_file = cache_dir / f"{cache_name}.json"

        cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self) -> list[T] | None:
        """Get cached data if valid.

        Returns:
            Cached data if valid, None if expired or missing
        """
        if not self._cache_file.exists():
            return None

        try:
            with open(self._cache_file) as f:
                raw_data = json.load(f)

            # Validate version
            version = raw_data.get("version", 0)
            if version != self.CACHE_FORMAT_VERSION:
                self.logger.warning(f"Cache format mismatch: {self._cache_file}")
                return None

            # Check TTL
            cached_at_str = raw_data.get("cached_at")
            if cached_at_str:
                cached_at = datetime.fromisoformat(cached_at_str)
                age = datetime.now() - cached_at
                if age > self._ttl:
                    self.logger.debug(f"Cache expired: {self._cache_name} (age: {age})")
                    return None

            # Extract data
            data = raw_data.get("data", [])
            self.logger.debug(f"Cache hit: {self._cache_name} ({len(data)} items)")
            return data

        except (json.JSONDecodeError, KeyError) as e:
            self.logger.warning(f"Invalid cache file: {e}")
            return None

    def set(self, data: list[T]) -> None:
        """Cache data.

        Args:
            data: Data to cache
        """
        try:
            cache_data = {
                "version": self.CACHE_FORMAT_VERSION,
                "data": data,
                "cached_at": datetime.now().isoformat(),
            }

            with open(self._cache_file, "w") as f:
                json.dump(cache_data, f, indent=2)

            self.logger.info(f"Cached {len(data)} items: {self._cache_name}")

        except (OSError, IOError) as e:
            self.logger.error(f"Failed to write cache: {e}")

    def invalidate(self) -> None:
        """Invalidate (delete) cached data."""
        if self._cache_file.exists():
            self._cache_file.unlink()
            self.logger.info(f"Cache invalidated: {self._cache_name}")
```

**Step 3:** Create `cache_manager.py` facade:
```python
"""Cache manager facade for backward compatibility."""

from pathlib import Path

from PySide6.QtCore import QObject

from logging_mixin import LoggingMixin
from thumbnail_cache import ThumbnailCache
from data_cache import DataCache
from type_definitions import ShotDict, ThreeDESceneDict


class CacheManager(LoggingMixin, QObject):
    """Facade coordinating thumbnail and data caches.

    Provides backward-compatible API while delegating to specialized caches.
    """

    def __init__(self, cache_root: Path | None = None, parent: QObject | None = None):
        """Initialize cache manager.

        Args:
            cache_root: Root directory for all caches
            parent: Parent QObject
        """
        super().__init__(parent)

        # Determine cache root
        if cache_root is None:
            cache_root = self._get_default_cache_root()

        # Initialize specialized caches
        self.thumbnails = ThumbnailCache(cache_root / "thumbnails", self)
        self.shots = DataCache[ShotDict](cache_root, "shots", ttl_minutes=30, parent=self)
        self.threede_scenes = DataCache[ThreeDESceneDict](
            cache_root, "threede_scenes", ttl_minutes=30, parent=self
        )
        self.previous_shots = DataCache[ShotDict](
            cache_root, "previous_shots", ttl_minutes=30, parent=self
        )

    # Delegate methods for backward compatibility

    def get_cached_thumbnail(self, show: str, sequence: str, shot: str) -> Path | None:
        """Get cached thumbnail (delegates to ThumbnailCache)."""
        return self.thumbnails.get_cached_thumbnail(show, sequence, shot)

    def cache_thumbnail(
        self, source_path: Path, show: str, sequence: str, shot: str
    ) -> Path | None:
        """Cache thumbnail (delegates to ThumbnailCache)."""
        return self.thumbnails.cache_thumbnail(source_path, show, sequence, shot)

    def get_cached_shots(self) -> list[ShotDict] | None:
        """Get cached shots (delegates to DataCache)."""
        return self.shots.get()

    def cache_shots(self, shots: list[ShotDict]) -> None:
        """Cache shots (delegates to DataCache)."""
        self.shots.set(shots)

    def get_cached_threede_scenes(self) -> list[ThreeDESceneDict] | None:
        """Get cached 3DE scenes (delegates to DataCache)."""
        return self.threede_scenes.get()

    def cache_threede_scenes(self, scenes: list[ThreeDESceneDict]) -> None:
        """Cache 3DE scenes (delegates to DataCache)."""
        self.threede_scenes.set(scenes)

    def clear_all_caches(self) -> None:
        """Clear all caches."""
        self.shots.invalidate()
        self.threede_scenes.invalidate()
        self.previous_shots.invalidate()
        self.logger.info("All caches cleared")

    def _get_default_cache_root(self) -> Path:
        """Get default cache root based on mode."""
        # Implementation from current CacheManager
        pass
```

**Benefits:**
- Each cache type has focused responsibility
- ThumbnailCache: 200 lines (was 168 lines mixed with others)
- DataCache: 150 lines (reusable for all JSON data)
- CacheManager facade: 100 lines (was 729 lines)
- Easier to test each cache type independently
- Backward compatible API

**Testing:**
```python
# test_thumbnail_cache.py
def test_cache_thumbnail(tmp_path):
    """Test thumbnail caching."""
    cache = ThumbnailCache(tmp_path)
    result = cache.cache_thumbnail(source_image, "show", "seq", "shot")
    assert result is not None
    assert result.exists()

# test_data_cache.py
def test_cache_with_ttl(tmp_path):
    """Test TTL expiration."""
    cache = DataCache(tmp_path, "test", ttl_minutes=0)
    cache.set([{"test": "data"}])
    time.sleep(1)
    assert cache.get() is None  # Expired

# test_cache_manager.py
def test_backward_compatibility():
    """Test facade maintains old API."""
    manager = CacheManager()
    manager.cache_shots([{"show": "test"}])
    shots = manager.get_cached_shots()
    assert shots is not None
```

**Estimated Breakdown:**
- Design cache interfaces: 1 hour
- Implement ThumbnailCache: 1.5 hours
- Implement DataCache: 1.5 hours
- Create CacheManager facade: 1 hour
- Testing: 1 hour

---

### 4.2 Refactor BaseItemModel.data() and _load_thumbnail_async()
**File:** `base_item_model.py`
**Time:** 4 hours
**Risk:** Low

**Problem:** Long methods with complex conditional logic.

**Solution 1: Dispatch Table for data()**
```python
# base_item_model.py

class BaseItemModel(LoggingMixin, QAbstractListModel, Generic[T]):
    """Base class for list-based item models."""

    def __init__(self, cache_manager, parent):
        super().__init__(parent)
        # ... existing code ...

        # Role dispatch table
        self._role_handlers = {
            Qt.ItemDataRole.DisplayRole: self._handle_display_role,
            Qt.ItemDataRole.ToolTipRole: self._handle_tooltip_role,
            Qt.ItemDataRole.SizeHintRole: self._handle_size_hint_role,
            Qt.ItemDataRole.DecorationRole: self._handle_decoration_role,
            BaseItemRole.ObjectRole: lambda item: item,
            BaseItemRole.ShowRole: lambda item: item.show,
            BaseItemRole.SequenceRole: lambda item: item.sequence,
            BaseItemRole.FullNameRole: lambda item: item.full_name,
            BaseItemRole.WorkspacePathRole: lambda item: item.workspace_path,
            BaseItemRole.ThumbnailPathRole: self._handle_thumbnail_path_role,
            BaseItemRole.ThumbnailPixmapRole: self._handle_thumbnail_pixmap_role,
            BaseItemRole.LoadingStateRole: self._handle_loading_state_role,
            BaseItemRole.IsSelectedRole: self._handle_is_selected_role,
        }

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """Get data for the given index and role.

        Uses dispatch table for role handling.
        """
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None

        item = self._items[index.row()]

        # Use dispatch table
        handler = self._role_handlers.get(role)
        if handler:
            try:
                return handler(item)
            except Exception as e:
                self.logger.error(f"Error handling role {role}: {e}")
                return None

        # Fall back to custom roles (for subclasses)
        return self.get_custom_role_data(item, role)

    # Role handlers (simple, focused methods)

    def _handle_display_role(self, item: T) -> str:
        """Handle DisplayRole."""
        return self.get_display_role_data(item)

    def _handle_tooltip_role(self, item: T) -> str:
        """Handle ToolTipRole."""
        return self.get_tooltip_data(item)

    def _handle_size_hint_role(self, item: T) -> QSize:
        """Handle SizeHintRole."""
        return QSize(self._thumbnail_size, self._thumbnail_size)

    def _handle_decoration_role(self, item: T) -> QIcon | None:
        """Handle DecorationRole."""
        pixmap = self._get_thumbnail_pixmap(item)
        return QIcon(pixmap) if pixmap else None

    def _handle_thumbnail_path_role(self, item: T) -> Path | None:
        """Handle ThumbnailPathRole."""
        path = item.get_thumbnail_path()
        return path if path and path.exists() else None

    def _handle_thumbnail_pixmap_role(self, item: T) -> QPixmap | None:
        """Handle ThumbnailPixmapRole."""
        return self._get_thumbnail_pixmap(item)

    def _handle_loading_state_role(self, item: T) -> str:
        """Handle LoadingStateRole."""
        with QMutexLocker(self._cache_mutex):
            return self._loading_states.get(item.full_name, "not_loaded")

    def _handle_is_selected_role(self, item: T) -> bool:
        """Handle IsSelectedRole."""
        with QMutexLocker(self._cache_mutex):
            return self._selected_item == item
```

**Solution 2: Extract Thumbnail Loading Helpers**
```python
def _load_thumbnail_async(self, row: int, item: T) -> None:
    """Start async thumbnail loading for an item."""
    thumbnail_path = item.get_thumbnail_path()

    if not thumbnail_path or not thumbnail_path.exists():
        self._mark_thumbnail_failed(item, row)
        return

    # Mark as loading
    self._mark_thumbnail_loading(item, row)

    # Load via appropriate method
    if self._cache_manager:
        self._load_via_cache_manager(thumbnail_path, item, row)
    else:
        self._load_direct(thumbnail_path, item, row)

def _mark_thumbnail_loading(self, item: T, row: int) -> None:
    """Mark thumbnail as loading."""
    with QMutexLocker(self._cache_mutex):
        self._loading_states[item.full_name] = "loading"

    index = self.index(row, 0)
    self.dataChanged.emit(index, index, [BaseItemRole.LoadingStateRole])

def _mark_thumbnail_failed(self, item: T, row: int) -> None:
    """Mark thumbnail as failed."""
    with QMutexLocker(self._cache_mutex):
        self._loading_states[item.full_name] = "failed"

    index = self.index(row, 0)
    self.dataChanged.emit(index, index, [BaseItemRole.LoadingStateRole])

def _mark_thumbnail_loaded(self, item: T, row: int) -> None:
    """Mark thumbnail as successfully loaded."""
    with QMutexLocker(self._cache_mutex):
        self._loading_states[item.full_name] = "loaded"

    index = self.index(row, 0)
    self.dataChanged.emit(
        index, index,
        [BaseItemRole.LoadingStateRole, BaseItemRole.ThumbnailPixmapRole]
    )

def _load_via_cache_manager(self, path: Path, item: T, row: int) -> None:
    """Load thumbnail via cache manager."""
    try:
        cached_path = self._cache_manager.cache_thumbnail(
            path, item.show, item.sequence, item.shot
        )

        if cached_path and cached_path.exists():
            self._load_cached_pixmap(cached_path, row, item, self.index(row, 0))
        else:
            self.logger.warning(f"Failed to cache thumbnail: {path}")
            self._mark_thumbnail_failed(item, row)

    except Exception as e:
        self.logger.error(f"Cache manager error: {e}")
        self._mark_thumbnail_failed(item, row)

def _load_direct(self, path: Path, item: T, row: int) -> None:
    """Load thumbnail directly without cache manager."""
    try:
        # Load image
        from PIL import Image
        img = Image.open(path)
        img.thumbnail((self._thumbnail_size, self._thumbnail_size))

        # Convert to QImage
        qimage = self._pil_to_qimage(img)

        # Cache and emit
        with QMutexLocker(self._cache_mutex):
            self._thumbnail_cache[item.full_name] = qimage

        self._mark_thumbnail_loaded(item, row)
        self.thumbnail_loaded.emit(self.index(row, 0))

    except Exception as e:
        self.logger.error(f"Failed to load thumbnail directly: {e}")
        self._mark_thumbnail_failed(item, row)
```

**Benefits:**
- data() reduced from 66 lines to ~30 lines
- _load_thumbnail_async() split into 7 focused methods
- Each method has single responsibility
- Easier to test individual operations
- Clearer error handling

**Testing:**
1. Run all existing tests
2. Add tests for each role handler
3. Test thumbnail loading edge cases
4. Verify no performance regression

---

## Testing Strategy

### General Testing Approach

For each refactoring:
1. **Pre-refactoring baseline**: Run full test suite, document results
2. **Implement refactoring**: Make changes
3. **Post-refactoring validation**: Run test suite again, compare results
4. **Add focused tests**: Test new extracted components
5. **Manual UI testing**: Verify no visual changes or regressions

### Phase-Specific Testing

**Phase 1 (Critical Fixes):**
- Threading stress tests for race conditions
- Memory leak detection with valgrind/memcheck
- UI responsiveness testing with rapid interactions

**Phase 2 (DRY Violations):**
- Filter functionality tests (all combinations)
- Logging output validation
- Context manager nesting tests

**Phase 3 (Complexity Reduction):**
- Thumbnail discovery with all shot types
- MainWindow integration tests
- Signal flow verification

**Phase 4 (Final Cleanup):**
- Cache TTL behavior
- BaseItemModel role handling
- Backward compatibility validation

### Automated Testing

Add to CI/CD pipeline:
```bash
# Run full test suite with coverage
~/.local/bin/uv run pytest tests/unit/ -n auto --cov=. --cov-report=html

# Check for race conditions with ThreadSanitizer
~/.local/bin/uv run pytest tests/unit/ --sanitize-threads

# Performance regression tests
~/.local/bin/uv run pytest tests/performance/ -v
```

---

## Risk Mitigation

### High-Risk Changes (Race Conditions, MainWindow Split)

1. **Feature Flags**: Add environment variables to toggle new/old implementations
2. **Parallel Running**: Run both implementations, compare results
3. **Gradual Rollout**: Enable for specific users/scenarios first
4. **Rollback Plan**: Keep old code commented for quick revert

### Medium-Risk Changes (Thumbnail Discovery, CacheManager Split)

1. **Extensive Testing**: Focus on edge cases and error paths
2. **Backward Compatibility**: Maintain existing APIs
3. **Code Review**: Get second pair of eyes on complex logic

### Low-Risk Changes (Quick Wins, Extraction Refactoring)

1. **Standard Testing**: Existing test suite sufficient
2. **Visual Verification**: Quick manual check

---

## Success Metrics

### Code Quality Metrics

**Before Refactoring:**
- Total lines: ~15,000
- God classes: 2 (1,413 + 729 lines)
- Duplicate code: ~250 lines
- Race conditions: 3 identified
- Longest method: 130 lines

**After Refactoring:**
- God classes: 0 (all under 500 lines)
- Duplicate code: <20 lines
- Race conditions: 0
- Longest method: <50 lines
- Code reduction: ~800 lines eliminated

### Performance Metrics

- No regression in app startup time
- No regression in shot loading time
- No regression in thumbnail loading time
- Reduced memory usage (cleaner resource management)

### Maintainability Metrics

- Reduced cyclomatic complexity
- Improved test coverage (easier to test focused classes)
- Faster onboarding for new developers
- Easier to add new features

---

## Timeline Summary

| Phase | Duration | Focus | Risk |
|-------|----------|-------|------|
| Phase 1 | 1 week (10 hours) | Critical fixes + quick wins | Low-Medium |
| Phase 2 | 1 week (15 hours) | DRY violations | Low |
| Phase 3 | 2 weeks (20 hours) | Complexity reduction | Medium |
| Phase 4 | 1 week (10 hours) | Final cleanup | Low-Medium |
| **Total** | **5 weeks (55 hours)** | **Complete refactoring** | **Managed** |

---

## Conclusion

This refactoring plan addresses all identified KISS and DRY violations in the ShotBot codebase. The phased approach allows for:

1. **Immediate Impact**: Phase 1 quick wins and critical fixes
2. **Incremental Progress**: Each phase delivers value
3. **Manageable Risk**: Testing and validation at each step
4. **Preserves Functionality**: No user-facing changes
5. **Improves Maintainability**: Cleaner, more focused code

The plan respects the existing architecture's strengths (intentional tab separation, Model/View patterns, dependency injection) while eliminating technical debt that has accumulated.

**Next Steps:**
1. Review and approve this plan
2. Create tracking issues for each phase
3. Begin Phase 1 implementation
4. Schedule regular progress reviews

**Questions?** Contact the development team for clarification on any aspect of this plan.
