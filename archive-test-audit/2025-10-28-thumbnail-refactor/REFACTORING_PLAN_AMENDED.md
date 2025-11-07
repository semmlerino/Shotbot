# ShotBot Refactoring Plan (Amended)

**Version**: 2.0 (Revised 2025-10-11)
**Previous Version**: 1.0 (Original from dual-agent review)
**Status**: Ready for Implementation

---

## Executive Summary

This amended plan corrects critical flaws identified in the original refactoring proposal:

**Key Changes from v1.0:**
- ❌ **REMOVED** Phase 1.2 (Selection tracking race condition - false positive)
- ❌ **REMOVED** SignalRouter class (over-engineering)
- 🔧 **REDESIGNED** Phase 3.1 (Thumbnail discovery - Template Method, not config-driven)
- 🔧 **MODIFIED** Phase 1.3 (Context manager pattern, not helper methods)
- 🔧 **MODIFIED** Phase 2.1 (Composition-based ShotFilter, not mixin)
- ⏱️ **REVISED** estimates (85-95 hours total, including adequate testing)

**Confidence Level**: High - all proposals verified through code inspection

---

## Phase 1: Critical Fixes (Week 1) - 6 hours

### 1.1 Race Condition: Thumbnail Loading ✅

**Priority**: CRITICAL
**Risk**: Medium
**Time**: 2 hours

**Issue:**
Race condition in `base_item_model.py` lines 320-332 where check-and-mark operations are not atomic:

```python
# PROBLEM: Check OUTSIDE lock, mark INSIDE different lock scope
for row in range(start, end):
    item = self._items[row]

    with QMutexLocker(self._cache_mutex):
        if item.full_name in self._thumbnail_cache:
            continue
        state = self._loading_states.get(item.full_name)
        if state in ("loading", "failed"):
            continue

    # Gap here - another thread could start loading

    with QMutexLocker(self._cache_mutex):
        self._loading_states[item.full_name] = "loading"
```

**Solution:**
Per-item atomic check-and-mark to minimize lock duration:

```python
def _load_visible_thumbnails(self) -> None:
    """Load thumbnails with minimal mutex hold time."""
    buffer_size = 5
    start = max(0, self._visible_start - buffer_size)
    end = min(len(self._items), self._visible_end + buffer_size)

    items_to_load: list[tuple[int, T]] = []

    for row in range(start, end):
        item = self._items[row]

        # Atomic check-and-mark in single lock acquisition
        should_load = False
        with QMutexLocker(self._cache_mutex):
            if item.full_name not in self._thumbnail_cache:
                state = self._loading_states.get(item.full_name)
                if state not in ("loading", "failed"):
                    self._loading_states[item.full_name] = "loading"
                    should_load = True

        if should_load:
            items_to_load.append((row, item))

    # Load thumbnails outside lock
    for row, item in items_to_load:
        self._load_thumbnail_async(row, item)

    # Stop timer if all loaded
    all_loaded = all(
        self._items[i].full_name in self._thumbnail_cache
        for i in range(start, end)
    )
    if all_loaded:
        self._thumbnail_timer.stop()
```

**Benefits:**
- Eliminates race condition (atomic check-and-mark)
- Minimizes lock duration (per-item, not bulk)
- Prevents UI stuttering (short lock acquisitions)

**Testing:**
```python
# Stress test with concurrent access
def test_concurrent_thumbnail_loading(model, qtbot):
    """Verify no duplicate loads with concurrent access."""
    load_counts = {}

    def track_load(row, item):
        load_counts[item.full_name] = load_counts.get(item.full_name, 0) + 1

    # Mock _load_thumbnail_async to track calls
    with patch.object(model, '_load_thumbnail_async', side_effect=track_load):
        # Trigger loading from multiple "threads"
        for _ in range(10):
            model.set_visible_range(0, 10)
            QApplication.processEvents()

    # Each item should be loaded exactly once
    assert all(count == 1 for count in load_counts.values())
```

---

### 1.3 Thread-Safe Flag Pattern - Context Manager ✅

**Priority**: HIGH
**Risk**: Low
**Time**: 1.5 hours

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
            yield False
            return
        self._is_scanning = True

    try:
        yield True
    finally:
        # Guaranteed cleanup even on exceptions
        with QMutexLocker(self._scan_lock):
            self._is_scanning = False
```

**Usage:**
```python
def refresh_shots(self) -> bool:
    """Refresh with guaranteed lock cleanup."""
    with self._scanning_lock() as acquired:
        if not acquired:
            self.logger.debug("Already scanning")
            return False

        # Emit signal
        self.scan_started.emit()

        # Clear caches
        self._clear_caches_for_refresh()

        # Create and start worker
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
Template Method in `base_item_model.py`:

```python
def cleanup(self) -> None:
    """Clean up resources with guaranteed order.

    Template method that ensures consistent cleanup across all models:
    1. Stop timers
    2. Clear caches
    3. Disconnect signals (model-specific)
    4. Clear selection
    5. Additional cleanup (model-specific)
    """
    # 1. Stop timers
    if hasattr(self, "_thumbnail_timer") and self._thumbnail_timer is not None:
        self._thumbnail_timer.stop()
        self._thumbnail_timer.deleteLater()

    # 2. Clear caches
    self.clear_thumbnail_cache()

    # 3. Let subclass disconnect its signals
    self._disconnect_signals()

    # 4. Clear selection
    self._selected_index = QPersistentModelIndex()
    self._selected_item = None

    # 5. Let subclass do additional cleanup
    self._cleanup_additional()

    self.logger.info(f"{self.__class__.__name__} cleanup complete")

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
            # Already disconnected or destroyed
            pass

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

# previous_shots_item_model.py
@override
def _disconnect_signals(self) -> None:
    """Disconnect previous shots signals."""
    super()._disconnect_signals()

    try:
        self.shots_updated.disconnect()
    except (RuntimeError, TypeError):
        pass

    # Disconnect from underlying model
    if hasattr(self._underlying_model, "shots_updated"):
        try:
            self._underlying_model.shots_updated.disconnect(
                self._on_underlying_shots_updated
            )
        except (RuntimeError, TypeError):
            pass

@override
def _cleanup_additional(self) -> None:
    """Additional cleanup for previous shots."""
    # Clear reference to underlying model
    self._underlying_model = None  # type: ignore[assignment]
```

**Benefits:**
- Eliminates ~90 lines of duplication
- Guarantees consistent cleanup order
- Makes it impossible to forget cleanup steps
- Clear extension points for subclasses

---

## Phase 2: DRY Violations (Week 2) - 10 hours

### 2.1 Shot Filter - Composition over Inheritance 🔧

**Priority**: HIGH
**Risk**: Medium
**Time**: 3 hours

**Issue:**
59 lines of filtering logic duplicated between:
- `base_shot_model.py` lines 283-341
- `previous_shots_model.py` lines 179-237

**Original Plan Problem:**
Proposed using mixin with abstract properties, creating multiple inheritance complexity.

**Solution:**
Composition-based `ShotFilter` class:

```python
# shot_filter.py (new file)
from dataclasses import dataclass, field

@dataclass
class ShotFilter:
    """Reusable shot filter with composition pattern.

    No inheritance required - can be used with any shot collection.

    Example:
        filter = ShotFilter(logger)
        filter.set_show_filter("gator")
        filtered = filter.apply(shots)
    """

    logger: ContextualLogger
    show_filter: str | None = None
    text_filter: str | None = None

    def set_show_filter(self, show: str | None) -> None:
        """Set show filter.

        Args:
            show: Show name or None for all shows
        """
        self.show_filter = show
        filter_display = show if show else "All Shows"
        self.logger.info(f"Show filter: {filter_display}")

    def set_text_filter(self, text: str | None) -> None:
        """Set text filter for substring matching.

        Args:
            text: Text to filter by (case-insensitive) or None
        """
        self.text_filter = text.strip() if text else None
        self.logger.info(f"Text filter: '{self.text_filter or ''}'")

    def apply(self, shots: list[Shot]) -> list[Shot]:
        """Apply all active filters to shot list.

        Args:
            shots: List of shots to filter

        Returns:
            Filtered list of shots
        """
        filtered = shots

        # Apply show filter
        if self.show_filter is not None:
            filtered = [s for s in filtered if s.show == self.show_filter]

        # Apply text filter (case-insensitive substring match)
        if self.text_filter:
            filter_lower = self.text_filter.lower()
            filtered = [
                s for s in filtered
                if filter_lower in s.full_name.lower()
            ]

        self.logger.debug(
            f"Filtered {len(shots)} → {len(filtered)} shots "
            f"(show={self.show_filter}, text='{self.text_filter}')"
        )

        return filtered

    def get_available_shows(self, shots: list[Shot]) -> set[str]:
        """Extract unique shows from shot list.

        Args:
            shots: List of shots

        Returns:
            Set of unique show names
        """
        return {shot.show for shot in shots}

    def clear(self) -> None:
        """Clear all filters."""
        self.show_filter = None
        self.text_filter = None
        self.logger.info("Cleared all filters")
```

**Usage in BaseShotModel:**
```python
# base_shot_model.py
class BaseShotModel(LoggingMixin, QObject):
    def __init__(self, cache_manager: CacheManager | None = None):
        super().__init__()
        self._shots: list[Shot] = []
        self._filter = ShotFilter(logger=self.logger)  # Composition

    def set_show_filter(self, show: str | None) -> None:
        """Delegate to filter object."""
        self._filter.set_show_filter(show)

    def get_show_filter(self) -> str | None:
        """Get current show filter."""
        return self._filter.show_filter

    def set_text_filter(self, text: str | None) -> None:
        """Delegate to filter object."""
        self._filter.set_text_filter(text)

    def get_text_filter(self) -> str | None:
        """Get current text filter."""
        return self._filter.text_filter

    def get_filtered_shots(self) -> list[Shot]:
        """Apply filter to shots."""
        return self._filter.apply(self._shots)

    def get_available_shows(self) -> set[str]:
        """Get available shows."""
        return self._filter.get_available_shows(self._shots)
```

**Benefits:**
- ✅ No multiple inheritance complexity
- ✅ Testable in complete isolation
- ✅ Reusable with ANY shot collection
- ✅ No coupling to LoggingMixin
- ✅ Clear, single responsibility

**Testing:**
```python
def test_shot_filter_composition():
    """Verify filter works independently."""
    logger = get_module_logger("test")
    filter = ShotFilter(logger)

    shots = [
        Shot("show1", "seq1", "shot1", "/path1"),
        Shot("show2", "seq1", "shot2", "/path2"),
        Shot("show1", "seq2", "shot3", "/path3"),
    ]

    # Test show filter
    filter.set_show_filter("show1")
    filtered = filter.apply(shots)
    assert len(filtered) == 2
    assert all(s.show == "show1" for s in filtered)

    # Test text filter
    filter.clear()
    filter.set_text_filter("shot1")
    filtered = filter.apply(shots)
    assert len(filtered) == 1
    assert filtered[0].shot == "shot1"

    # Test combined filters
    filter.set_show_filter("show1")
    filter.set_text_filter("shot")
    filtered = filter.apply(shots)
    assert len(filtered) == 2  # Both show1 shots contain "shot"
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
**Time**: 1 hour

**Issue:**
Feature flags scattered across `main_window.py` (lines 269, 312, 329, 675).

**Solution:**
```python
# feature_flags.py (new file)
import os

class FeatureFlags:
    """Centralized feature flag management.

    All feature flags read from environment variables.
    """

    @staticmethod
    def use_simplified_launcher() -> bool:
        """Use simplified launcher panel (testing feature)."""
        return os.environ.get("USE_SIMPLIFIED_LAUNCHER", "false").lower() == "true"

    @staticmethod
    def use_threede_controller() -> bool:
        """Use ThreeDEController for enhanced functionality."""
        return os.environ.get("USE_THREEDE_CONTROLLER", "false").lower() == "true"

    @staticmethod
    def enable_debug_logging() -> bool:
        """Enable verbose debug logging."""
        return os.environ.get("SHOTBOT_DEBUG", "false").lower() == "true"

    @staticmethod
    def is_mock_mode() -> bool:
        """Check if running in mock mode."""
        return os.environ.get("SHOTBOT_MOCK", "false").lower() in ("1", "true", "yes")

# Usage in main_window.py
if FeatureFlags.use_simplified_launcher():
    # Simplified launcher code
else:
    # Standard launcher code
```

**Benefits:**
- Single source of truth for flags
- Easy to discover all feature flags
- Testable with environment mocking
- Self-documenting

---

## Phase 3: Complexity Reduction (Weeks 3-4) - 45 hours

### 3.1 Thumbnail Discovery - Template Method Pattern 🔧

**Priority**: MEDIUM
**Risk**: Medium-High
**Time**: 25 hours (revised from 12 hours)

**Issue:**
522 lines of complex thumbnail discovery logic in `utils.py` with sophisticated VFX pipeline features:
- Plate priority sorting (FG > BG > others)
- Frame number extraction with regex
- File size validation
- Variable directory structures
- Recursive search with format preferences

**Original Plan Problem:**
Proposed config-driven Strategy pattern that cannot express algorithms (sorting, extraction, validation).

**Solution:**
Template Method pattern with shared traversal logic:

```python
# thumbnail_finder.py (new file)
from abc import ABC, abstractmethod
from pathlib import Path
import re

class ThumbnailFinderBase(ABC):
    """Base class for thumbnail discovery strategies.

    Template Method pattern:
    - Base class defines algorithm structure
    - Subclasses implement specific search strategies
    """

    def __init__(self, logger: ContextualLogger):
        self.logger = logger

    def find(self, show: str, sequence: str, shot: str) -> Path | None:
        """Template method - defines discovery algorithm.

        Algorithm:
        1. Get search paths from subclass
        2. For each path, find candidates
        3. Select best candidate using subclass logic

        Args:
            show: Show name
            sequence: Sequence name
            shot: Shot name

        Returns:
            Path to thumbnail or None
        """
        search_paths = self.get_search_paths(show, sequence, shot)

        for path in search_paths:
            if not path.exists():
                self.logger.debug(f"Path does not exist: {path}")
                continue

            candidates = self.find_candidates(path)
            if not candidates:
                continue

            best = self.select_best_candidate(candidates)
            if best:
                self.logger.info(
                    f"{self.__class__.__name__} found: {best.name}"
                )
                return best

        return None

    @abstractmethod
    def get_search_paths(
        self, show: str, sequence: str, shot: str
    ) -> list[Path]:
        """Return paths to search in priority order.

        Subclass implements specific path construction logic.
        """
        pass

    @abstractmethod
    def find_candidates(self, path: Path) -> list[Path]:
        """Find candidate files in given path.

        Subclass implements specific discovery logic.
        """
        pass

    def select_best_candidate(self, candidates: list[Path]) -> Path | None:
        """Select best candidate from list.

        Default: return first candidate.
        Subclass can override for custom selection logic.
        """
        return candidates[0] if candidates else None

    # Shared utility methods
    def _build_shot_path(self, show: str, sequence: str, shot: str) -> Path:
        """Build base shot directory path."""
        shot_dir = f"{sequence}_{shot}"
        return (
            Path(Config.SHOWS_ROOT)
            / show / "shots" / sequence / shot_dir
        )

    def _find_files_by_extension(
        self, directory: Path, extensions: list[str], limit: int | None = None
    ) -> list[Path]:
        """Find files with given extensions."""
        files = []
        ext_set = {ext.lower() for ext in extensions}

        try:
            for file_path in directory.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in ext_set:
                    files.append(file_path)
                    if limit and len(files) >= limit:
                        break
        except (OSError, PermissionError) as e:
            self.logger.debug(f"Error scanning {directory}: {e}")

        return files


class EditorialFinder(ThumbnailFinderBase):
    """Find editorial JPEGs - simplest case."""

    def get_search_paths(self, show: str, sequence: str, shot: str) -> list[Path]:
        shot_path = self._build_shot_path(show, sequence, shot)
        return [shot_path / "publish" / "editorial" / "cutref"]

    def find_candidates(self, path: Path) -> list[Path]:
        return self._find_files_by_extension(path, [".jpg", ".jpeg"])


class TurnoverPlateFinder(ThumbnailFinderBase):
    """Find turnover plates with FG/BG priority sorting."""

    def get_search_paths(self, show: str, sequence: str, shot: str) -> list[Path]:
        shot_path = self._build_shot_path(show, sequence, shot)
        base = shot_path / "publish" / "turnover" / "plate"

        # Try both with and without input_plate subdirectory
        return [
            base / "input_plate",
            base,
        ]

    def find_candidates(self, path: Path) -> list[Path]:
        """Find EXR plates with priority sorting."""
        # Get plate directories
        try:
            plate_dirs = [d for d in path.iterdir() if d.is_dir()]
        except (OSError, PermissionError):
            return []

        # Sort by priority (FG > BG > others)
        def plate_priority(plate_dir: Path) -> tuple[int, str]:
            name = plate_dir.name.upper()
            if name.startswith("FG"):
                return (0, name)
            if name.startswith("BG"):
                return (1, name)
            return (2, name)

        sorted_plates = sorted(plate_dirs, key=plate_priority)

        # Find EXR files in each plate
        candidates = []
        for plate_dir in sorted_plates:
            version_path = plate_dir / "v001" / "exr"
            if not version_path.exists():
                continue

            # Find resolution directories
            try:
                resolution_dirs = [d for d in version_path.iterdir() if d.is_dir()]
            except (OSError, PermissionError):
                continue

            for res_dir in resolution_dirs:
                exr_files = self._find_files_by_extension(res_dir, [".exr"], limit=10)
                if exr_files:
                    # Sort by frame number
                    first_frame = self._select_first_frame(exr_files)
                    if first_frame:
                        candidates.append(first_frame)

        return candidates

    def _select_first_frame(self, exr_files: list[Path]) -> Path | None:
        """Extract frame numbers and return lowest."""
        def extract_frame_number(path: Path) -> int:
            match = re.search(r"\.(\d{4})\.exr$", path.name, re.IGNORECASE)
            return int(match.group(1)) if match else 99999

        sorted_frames = sorted(exr_files, key=extract_frame_number)
        return sorted_frames[0] if sorted_frames else None


class UndistortedJPEGFinder(ThumbnailFinderBase):
    """Find undistorted JPEGs from publish/mm structure."""

    def get_search_paths(self, show: str, sequence: str, shot: str) -> list[Path]:
        shot_path = self._build_shot_path(show, sequence, shot)
        return [shot_path / "publish" / "mm" / "default"]

    def find_candidates(self, path: Path) -> list[Path]:
        """Find JPEGs in mm/default camera directories."""
        candidates = []

        # Discover plate directories with priority
        plate_dirs = self._discover_plate_directories(path)

        for plate_name, _priority in plate_dirs:
            plate_path = path / plate_name / "undistorted_plate"
            if not plate_path.exists():
                continue

            # Find latest version
            latest_version = self._get_latest_version(plate_path)
            if not latest_version:
                continue

            # Look for jpeg subdirectory
            jpeg_base = plate_path / latest_version / "jpeg"
            if not jpeg_base.exists():
                continue

            # Find JPEGs in resolution directories
            try:
                for res_dir in jpeg_base.iterdir():
                    if res_dir.is_dir():
                        jpegs = self._find_files_by_extension(
                            res_dir, [".jpg", ".jpeg"], limit=1
                        )
                        if jpegs:
                            candidates.append(jpegs[0])
                            break
            except (OSError, PermissionError):
                continue

        return candidates

    def _discover_plate_directories(self, path: Path) -> list[tuple[str, int]]:
        """Discover plate directories with priority."""
        found_plates = []
        plate_patterns = {
            r'^FG\d+$': 0,   # FG plates highest
            r'^BG\d+$': 1,   # BG plates second
            r'^PL\d+$': 2,   # PL plates third
            r'^EL\d+$': 3,   # Element plates
        }

        try:
            for item in path.iterdir():
                if not item.is_dir():
                    continue

                for pattern, priority in plate_patterns.items():
                    if re.match(pattern, item.name, re.IGNORECASE):
                        found_plates.append((item.name, priority))
                        break
        except (OSError, PermissionError):
            pass

        # Sort by priority (lower number = higher priority)
        found_plates.sort(key=lambda x: x[1])
        return found_plates

    def _get_latest_version(self, path: Path) -> str | None:
        """Find latest version directory."""
        version_pattern = re.compile(r"^v(\d{3})$")
        versions = []

        try:
            for item in path.iterdir():
                if item.is_dir():
                    match = version_pattern.match(item.name)
                    if match:
                        versions.append((int(match.group(1)), item.name))
        except (OSError, PermissionError):
            return None

        if not versions:
            return None

        versions.sort()
        return versions[-1][1]


# Coordinator function
def find_shot_thumbnail(show: str, sequence: str, shot: str) -> Path | None:
    """Find thumbnail using priority-ordered finders.

    Priority order:
    1. Editorial JPEGs (highest quality, curated)
    2. Undistorted JPEGs (published matchmove)
    3. User workspace JPEGs (artist-generated)
    4. Turnover plate EXRs (may be large)
    5. Any publish with 1001 (last resort)

    Args:
        show: Show name
        sequence: Sequence name
        shot: Shot name

    Returns:
        Path to thumbnail or None
    """
    logger = get_module_logger(__name__)

    finders: list[ThumbnailFinderBase] = [
        EditorialFinder(logger),
        UndistortedJPEGFinder(logger),
        # UserWorkspaceJPEGFinder(logger),  # Implementation similar
        TurnoverPlateFinder(logger),
        # AnyPublishFinder(logger),  # Implementation similar
    ]

    for finder in finders:
        result = finder.find(show, sequence, shot)
        if result:
            return result

    logger.debug(f"No thumbnail found for {show}/{sequence}/{shot}")
    return None
```

**What Gets Reduced:**
- ✅ Duplicate path construction (5 functions → base class)
- ✅ Duplicate directory traversal logic
- ✅ Duplicate error handling
- ✅ Common validation patterns

**What Stays (Essential Complexity):**
- ✅ Plate priority sorting (VFX workflow requirement)
- ✅ Frame extraction with regex (necessary for finding first frame)
- ✅ File size validation (performance requirement)
- ✅ Format preference logic (reliability requirement)

**Line Count:**
- Current: 522 lines
- After refactoring: ~300 lines
- **Reduction: 42%** (realistic, not 72%)

**Testing Strategy:**
```python
def test_editorial_finder():
    """Test simplest finder."""
    finder = EditorialFinder(get_module_logger("test"))

    # Test with mock filesystem
    with temp_dir_structure({
        "gator/shots/000/000_0010/publish/editorial/cutref": {
            "frame.1001.jpg": b"fake jpeg data"
        }
    }) as root:
        result = finder.find("gator", "000", "0010")
        assert result is not None
        assert result.name == "frame.1001.jpg"

def test_turnover_finder_priority():
    """Test plate priority sorting."""
    finder = TurnoverPlateFinder(get_module_logger("test"))

    with temp_dir_structure({
        "show/shots/seq/seq_shot/publish/turnover/plate/input_plate": {
            "EL01/v001/exr/4096x2160": {"frame.1001.exr": b"data"},
            "BG01/v001/exr/4096x2160": {"frame.1001.exr": b"data"},
            "FG01/v001/exr/4096x2160": {"frame.1001.exr": b"data"},
        }
    }) as root:
        result = finder.find("show", "seq", "shot")
        # Should select FG01, not first alphabetically
        assert "FG01" in str(result)

def test_coordinator_priority():
    """Test that coordinator tries finders in order."""
    # Only create turnover plates (3rd priority)
    with temp_dir_structure({
        "show/shots/seq/seq_shot/publish/turnover/plate/FG01/v001/exr/res": {
            "frame.1001.exr": b"data"
        }
    }) as root:
        result = find_shot_thumbnail("show", "seq", "shot")
        assert result is not None
```

**Migration Path:**
1. Create `thumbnail_finder.py` with base class and finders
2. Add tests for each finder
3. Update `utils.py` to use new finders (keep old functions temporarily)
4. Run full test suite
5. If tests pass, remove old implementations
6. If tests fail, rollback and debug

---

### 3.2 MainWindow Simplification 🔧

**Priority**: MEDIUM
**Risk**: High
**Time**: 15 hours

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
        """Get action by name for programmatic access."""
        return self._actions.get(name)


# main_window.py
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self._setup_ui()
        self._menu_builder = MenuBuilder(self)
        self._menu_builder.build_menus()
        self._connect_signals()
```

**Why NOT TabCoordinator:**
- Qt's Model/View already handles tabs
- Would just move complexity, not reduce it
- Current signal connections are already clear with comments

**Benefits:**
- Cleaner menu management (115 lines → 80 lines in MenuBuilder)
- Reusable action creation logic
- Easy to add new menus
- MainWindow reduced by ~100 lines

**Don't Extract:**
- Signal connections (already clear with good comments)
- Tab management (Qt already provides this)
- UI layout (needs context of MainWindow)

---

### 3.3 Dispatch Table for data() Method ✅

**Priority**: LOW
**Risk**: Low
**Time**: 5 hours

**Issue:**
66-line if/elif chain in `base_item_model.py` data() method (lines 177-223).

**Solution:**
Class-level dispatch table with hot-path optimization:

```python
class BaseItemModel(QAbstractListModel, Generic[T]):
    # Class-level dispatch (shared by all instances - saves memory)
    _ROLE_HANDLERS: ClassVar[dict[int, Callable[[BaseItemModel, T], object]]] = {
        BaseItemRole.ObjectRole: lambda self, item: item,
        BaseItemRole.ShowRole: lambda self, item: item.show,
        BaseItemRole.SequenceRole: lambda self, item: item.sequence,
        BaseItemRole.FullNameRole: lambda self, item: item.full_name,
        BaseItemRole.WorkspacePathRole: lambda self, item: item.workspace_path,
        BaseItemRole.ThumbnailPathRole: lambda self, item: (
            str(p) if (p := item.get_thumbnail_path()) else None
        ),
        Qt.ItemDataRole.ToolTipRole: lambda self, item: self.get_tooltip_data(item),
        Qt.ItemDataRole.SizeHintRole: lambda self, item: self.get_size_hint(),
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

        # Hot path optimization - DisplayRole is most common (avoid dict lookup)
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

        # Dispatch table for other roles
        handler = self._ROLE_HANDLERS.get(role)
        if handler:
            return handler(self, item)

        # Fall back to subclass implementation
        return self.get_custom_role_data(item, role)
```

**Benefits:**
- Eliminates 45-line if/elif chain
- O(1) lookup for dispatched roles
- Hot-path optimization for common roles
- Class-level dispatch saves memory
- Independently testable handlers

**Performance Note:**
`data()` is called thousands of times during scrolling, so hot-path optimization for DisplayRole and ThumbnailPixmapRole is critical.

---

## Phase 4: Final Cleanup (Week 5) - 14 hours

### 4.1 CacheManager Split - Facade Pattern ✅

**Priority**: MEDIUM
**Risk**: Medium
**Time**: 10 hours

**Issue:**
729-line CacheManager mixing thumbnail, shot, and 3DE scene caching.

**Solution:**
Split into focused classes with dependency injection:

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
        """Cache thumbnail with format conversion."""
        # Implementation from existing cache_manager.py
        pass


# data_cache.py (new file)
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


# cache_manager.py (simplified facade)
class CacheManager:
    """Facade providing backward-compatible API."""

    def __init__(self):
        cache_dir = self._get_cache_dir()

        self._thumbnail_cache = ThumbnailCache(cache_dir / "thumbnails")
        self._shot_cache = DataCache[list[ShotDict]](cache_dir, "shots")
        self._threede_cache = DataCache[list[ThreeDESceneDict]](cache_dir, "threede_scenes")
        self._previous_cache = DataCache[list[ShotDict]](cache_dir, "previous_shots")

    # Delegate to specialized caches
    def cache_thumbnail(self, *args, **kwargs) -> Path | None:
        return self._thumbnail_cache.cache_thumbnail(*args, **kwargs)

    def get_cached_shots(self) -> list[ShotDict] | None:
        return self._shot_cache.get()

    def cache_shots(self, shots: list[ShotDict]) -> None:
        self._shot_cache.set(shots)
```

**Benefits:**
- Single responsibility per class
- Type-safe generic caching
- Easy to test in isolation
- Dependency injection ready
- Backward compatible

**Usage with DI:**
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
**Time**: 4 hours

**Add to each refactored module:**

```python
"""Module documentation.

Architecture:
    Brief description of design pattern used

Thread Safety:
    Description of threading model

Performance:
    Any performance considerations

Example:
    Basic usage example
"""
```

**Testing Requirements:**
- Unit tests for all new classes
- Integration tests for Phase 3.1 (thumbnail discovery)
- Performance benchmarks for Phase 1.1 (thumbnail loading)
- Mock environment tests (432-shot fixture)

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
- Memory usage (should decrease with class-level dispatch)
- UI responsiveness during scrolling

### UI Regression Testing

```bash
# Run with mock environment
SHOTBOT_MOCK=1 ~/.local/bin/uv run pytest tests/ui/ -v

# Smoke tests
SHOTBOT_MOCK=1 ~/.local/bin/uv run python shotbot.py --headless --test-mode
```

**Test Cases:**
- All tabs load correctly
- Thumbnails display
- Filtering works
- Selection works
- Launcher integration works

### Thread Safety Validation

```bash
# Run with thread sanitizer (if available in WSL)
~/.local/bin/uv run pytest tests/threading/ -v --timeout=10

# Stress tests
~/.local/bin/uv run pytest tests/unit/ -n 8 --count=100
```

---

## Revised Effort Estimates

| Phase | Original Estimate | Revised Estimate | Difference |
|-------|------------------|------------------|------------|
| Phase 1 | 10 hours | 6 hours | -4 hours (removed 1.2) |
| Phase 2 | 15 hours | 10 hours | -5 hours (simplified) |
| Phase 3 | 20 hours | 45 hours | +25 hours (realistic thumbnail) |
| Phase 4 | 10 hours | 14 hours | +4 hours (added docs) |
| **Dev Total** | **55 hours** | **75 hours** | **+20 hours** |
| Testing | ~6 hours (10%) | 20 hours (27%) | +14 hours (adequate) |
| **Grand Total** | **~60 hours** | **~95 hours** | **+35 hours** |

---

## Revised Phasing

### Week 1 (6 hours): Critical Only
- ✅ Thumbnail loading race fix (1.1) - **2 hours**
- ✅ Thread-safe flag context manager (1.3) - **1.5 hours**
- ✅ CSS extraction (1.4) - **0.5 hours**
- ✅ Cleanup consolidation (1.5) - **2 hours**

### Week 2 (10 hours): Low-Risk, High-Value
- ✅ Shot filter composition (2.1) - **3 hours**
- ✅ Context manager extraction (2.2) - **1 hour**
- ✅ Feature flag consolidation (2.3) - **1 hour**
- ✅ Comprehensive testing - **5 hours**

### Weeks 3-4 (45 hours): High-Risk Changes
- 🔧 Thumbnail discovery Template Method (3.1) - **25 hours**
- 🔧 MainWindow MenuBuilder (3.2) - **15 hours**
- 🔧 Testing and validation - **5 hours**

### Week 5 (14 hours): Polish
- ✅ Dispatch table (3.3) - **5 hours**
- ✅ CacheManager split (4.1) - **10 hours**
- ✅ Documentation - **4 hours**

---

## Migration Checklist

**Before Starting:**
- [ ] Create feature branch
- [ ] Run full test suite (baseline)
- [ ] Run performance benchmarks (baseline)
- [ ] Commit current state

**Per Phase:**
- [ ] Implement changes
- [ ] Run unit tests
- [ ] Run integration tests
- [ ] Performance check (no regression)
- [ ] Code review
- [ ] Commit with descriptive message

**Before Merging:**
- [ ] Full test suite passes
- [ ] Performance benchmarks acceptable
- [ ] Manual UI testing with mock environment
- [ ] Documentation updated
- [ ] No regressions in functionality

---

## Rollback Procedures

**If Phase Fails:**
1. Document the failure (tests, errors, issues)
2. Revert branch to pre-phase state
3. Analyze root cause
4. Update plan with lessons learned
5. Retry or skip phase

**Red Flags to Abort:**
- >10% performance regression
- >3 new failing tests
- Memory leaks
- UI hangs or crashes
- Data corruption

---

## Success Criteria

**Code Quality:**
- [ ] 0 basedpyright errors
- [ ] 0 ruff errors
- [ ] Test coverage >90% for modified code

**Performance:**
- [ ] Thumbnail loading time unchanged or improved
- [ ] Memory usage unchanged or improved
- [ ] No UI responsiveness degradation

**Maintainability:**
- [ ] ~250 lines eliminated through DRY
- [ ] Clear documentation for new patterns
- [ ] Easier to add new thumbnail sources
- [ ] Easier to understand signal flow

---

## Conclusion

This amended plan:
- ✅ Removes false positives (Phase 1.2)
- ✅ Removes over-engineering (SignalRouter, TabCoordinator)
- ✅ Realistic estimates (95 hours vs 60 hours)
- ✅ Adequate testing (27% vs 10%)
- ✅ Risk-aware phasing (fail-fast approach)
- ✅ Verified through code inspection

**Confidence**: High - ready for implementation with proper safeguards.
