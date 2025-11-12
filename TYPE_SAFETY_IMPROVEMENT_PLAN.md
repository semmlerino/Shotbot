# Type Safety Improvement Implementation Plan

## Overview

This document provides a detailed, step-by-step implementation guide for improving type safety from the current 57 warnings to near-zero warnings.

**Effort Estimate**: 3-5 hours total
**Risk Level**: Low (all changes are additive, no behavior changes)
**Value**: Improved code clarity and reduced potential bugs

---

## Phase 1: Quick Wins (1-1.5 hours)

### Task 1.1: Fix filesystem_scanner.py List Type Inference

**File**: `/home/gabrielh/projects/shotbot/filesystem_scanner.py`
**Warnings Fixed**: 4
**Effort**: 15 minutes

**Current Code** (lines 797-805):
```python
prune_expr = []  # ⚠️ list[Any]
for i, dir_name in enumerate(prune_dirs):
    if i > 0:
        prune_expr.extend(["-o"])
    prune_expr.extend(["-path", f"*/{dir_name}"])

# Prune unwanted directories first
find_cmd_user = [
    "find", str(shots_dir),
    "(",
    *prune_expr,
```

**Recommended Fix**:
```python
prune_expr: list[str] = []  # ✅ Explicit type annotation
for i, dir_name in enumerate(prune_dirs):
    if i > 0:
        prune_expr.append("-o")
    prune_expr.extend(["-path", f"*/{dir_name}"])

# Prune unwanted directories first
find_cmd_user = [
    "find", str(shots_dir),
    "(",
    *prune_expr,
```

**Expected Warnings Eliminated**: 4 (lines 799, 800, 804, 836/840)

---

### Task 1.2: Fix ui_update_manager.py Dictionary Types

**File**: `/home/gabrielh/projects/shotbot/ui_update_manager.py`
**Warnings Fixed**: 3
**Effort**: 20 minutes

**Current Code** (lines 100-107):
```python
components_to_update = [
    component
    for component, dirty in self.dirty_flags.items()
    if dirty and component in self.last_update_time
]
updates_to_perform = {}  # ⚠️ dict[Unknown, Unknown]
for component in components_to_update:
    updates_to_perform[component] = self.pending_updates[component]
```

**Recommended Fix**:
```python
components_to_update: list[str] = [
    component
    for component, dirty in self.dirty_flags.items()
    if dirty and component in self.last_update_time
]
updates_to_perform: dict[str, object] = {}  # ✅ Explicit types
for component in components_to_update:
    if component in self.pending_updates:
        updates_to_perform[component] = self.pending_updates[component]
```

**Also Update** (line 196):
```python
# Current:
def get_update_stats(self) -> dict[str, dict[str, float]]:
    stats = {}  # ⚠️ dict[Unknown, Unknown]

# Recommended:
def get_update_stats(self) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}  # ✅ Explicit return type
```

**Expected Warnings Eliminated**: 3 (lines 105, 111, 196)

---

### Task 1.3: Add Type Annotations to threede_grid_view.py

**File**: `/home/gabrielh/projects/shotbot/threede_grid_view.py`
**Warnings Fixed**: 1
**Effort**: 10 minutes

**Current Code** (line 196):
```python
shows_list = self.available_shows  # ⚠️ list[str] | list[Unknown]
```

**Recommended Fix**:
```python
shows_list: list[str] = self.available_shows  # ✅ Explicit type
```

**Expected Warnings Eliminated**: 1

---

### Task 1.4: Fix thread_safe_worker.py List Operations

**File**: `/home/gabrielh/projects/shotbot/thread_safe_worker.py`
**Warnings Fixed**: 2
**Effort**: 10 minutes

**Current Code** (lines 622, 625):
```python
# ⚠️ Type of "append" is partially unknown
results.append(line)
output_lines.append(line)
```

**Recommended Fix**:
```python
# Add explicit type at initialization
results: list[str] = []
output_lines: list[str] = []

# Later in function:
results.append(line)    # ✅ Type is now clear
output_lines.append(line)
```

**Expected Warnings Eliminated**: 2

---

## Phase 2: Type Definition Improvements (1-1.5 hours)

### Task 2.1: Create TypedDict for UI Update Data

**File**: `/home/gabrielh/projects/shotbot/type_definitions.py`
**Location**: After line 510 (before end of file)
**Effort**: 20 minutes

**Add**:
```python
class UIUpdateData(TypedDict, total=False):
    """UI component update data structure."""

    progress: int
    status: str
    eta: float
    file_list: list[str]
    log_output: str
    fps: float


class PendingComponentUpdate(TypedDict, total=False):
    """Pending UI update for a specific component."""

    component: str
    data: UIUpdateData
    timestamp: float
```

**Update ui_update_manager.py**:
```python
from type_definitions import PendingComponentUpdate

class UIUpdateManager:
    def __init__(self) -> None:
        # Use proper type instead of plain dict
        self.pending_updates: dict[str, UIUpdateData] = {}
```

**Expected Warnings Eliminated**: 1-2

---

### Task 2.2: Define TypeGuard for Scene Data Validation

**File**: `/home/gabrielh/projects/shotbot/type_definitions.py`
**Location**: End of file (add to imports and functions)
**Effort**: 15 minutes

**Add to imports** (line 13):
```python
from typing import Literal, Protocol, TypedDict, TypeVar, TypeGuard, cast
```

**Add after TypeVar definitions** (after line 282):
```python
def is_shot(obj: object) -> TypeGuard[Shot]:
    """Type guard for checking if object is a Shot."""
    return isinstance(obj, Shot)


def is_valid_shot_dict(data: object) -> TypeGuard[ShotDict]:
    """Type guard for validating ShotDict structure."""
    if not isinstance(data, dict):
        return False
    required_keys = {"show", "sequence", "shot", "workspace_path"}
    return all(key in data for key in required_keys)


def is_threede_scene(data: object) -> TypeGuard[ThreeDESceneDict]:
    """Type guard for validating ThreeDESceneDict structure."""
    if not isinstance(data, dict):
        return False
    required_keys = {"filepath", "show", "sequence", "shot"}
    return all(key in data for key in required_keys)
```

**Usage in code**:
```python
from type_definitions import is_shot

def process_items(items: list[object]) -> list[Shot]:
    shots: list[Shot] = []
    for item in items:
        if is_shot(item):  # ✅ Type narrowing
            shots.append(item)
    return shots
```

**Expected Warnings Eliminated**: 0 (no direct warnings, but improves type safety)

---

### Task 2.3: Add Bounds to FinderProtocol TypeVar

**File**: `/home/gabrielh/projects/shotbot/type_definitions.py`
**Location**: Line 282
**Effort**: 10 minutes

**Current**:
```python
T = TypeVar("T")

class FinderProtocol(Protocol[T]):
    """Protocol for file/scene finders."""
    def find_all(self) -> list[T]: ...
```

**Recommended**:
```python
# Create a union of finder result types
FinderResult = Shot | ThreeDESceneDict

T = TypeVar("T", bound=FinderResult)

class FinderProtocol(Protocol[T]):
    """Protocol for file/scene finders with typed results."""
    def find_all(self) -> list[T]: ...
    def find_for_shot(self, show: str, sequence: str, shot: str) -> list[T]: ...
```

**Expected Warnings Eliminated**: 0 (improves type safety for future)

---

## Phase 3: Qt API Typing Workarounds (30 minutes - 1 hour)

### Task 3.1: Create PySide6 Typing Stubs

**File**: Create `/home/gabrielh/projects/shotbot/pyside6_stubs.pyi`
**Effort**: 30 minutes

**Content**:
```python
"""Type stubs for PySide6 untyped methods."""

from typing import Callable, Any

class SignalInstance:
    """Type stub for Signal instances to add receivers() typing."""

    def receivers(self, slot: Callable[..., Any] | None) -> int:
        """Return number of connected slots."""
        ...

    def connect(self, slot: Callable[..., Any]) -> None:
        """Connect a slot to signal."""
        ...

    def disconnect(self, slot: Callable[..., Any] | None = None) -> None:
        """Disconnect a slot from signal."""
        ...

    def emit(self, *args: Any, **kwargs: Any) -> None:
        """Emit signal with arguments."""
        ...
```

**Register in pyproject.toml**:
```toml
[tool.basedpyright]
# ... existing config ...
stubPath = "./pyside6_stubs"
```

**Update receiver() calls** (launcher_dialog.py, shot_item_model.py, threede_item_model.py):
```python
# Remove pyright: ignore comments if stubs are created
if self.items_updated.receivers(None) > 0:
    self.items_updated.disconnect()
```

**Expected Warnings Eliminated**: 3 (launcher_dialog lines 819, 821; shot_item_model lines 220, 223)

---

### Task 3.2: Create External VFX API Stubs

**File**: Create `/home/gabrielh/projects/shotbot/vfx_stubs.pyi`
**Effort**: 20 minutes (if used)

**Content** (if 3DE API is imported):
```python
"""Type stubs for 3D Equalizer Python API."""

from typing import Any

class Scene3DE:
    filepath: str

    def __init__(self, filepath: str) -> None: ...
    def get_shot_name(self) -> str: ...
    def get_user(self) -> str: ...
    @property
    def plates(self) -> list[Plate3DE]: ...

class Plate3DE:
    name: str

    def get_resolution(self) -> tuple[int, int]: ...

def open_scene(filepath: str) -> Scene3DE: ...
```

**Register in pyproject.toml**:
```toml
[tool.basedpyright]
stubPath = "./pyside6_stubs:./vfx_stubs"
```

**Expected Warnings Eliminated**: 2-3 (external API calls)

---

## Phase 4: Import Organization (15-30 minutes)

### Task 4.1: Move Type-Only Imports to TYPE_CHECKING Blocks

**File**: `/home/gabrielh/projects/shotbot/filesystem_coordinator.py`
**Warnings Fixed**: 0 (ruff TCH003)
**Effort**: 10 minutes

**Current** (lines 1-10):
```python
import time
from pathlib import Path
from threading import Lock

class FilesystemCoordinator:
    def scan(self, path: Path) -> None:
        ...
```

**Recommended**:
```python
from __future__ import annotations

import time
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

class FilesystemCoordinator:
    def scan(self, path: Path) -> None:
        # Type annotation works at type-check time
        # Runtime doesn't import Path here
        ...
```

**Affected Files** (ruff TCH003 findings):
- `filesystem_coordinator.py` - Move Path import
- `controllers/launcher_controller.py` - Move Callable import

**Expected Warnings Eliminated**: 0 (ruff-level, improves startup time)

---

## Phase 5: Strategic Enhancements (1-2 hours)

### Task 5.1: Define Result TypedDict for Cache Operations

**File**: `/home/gabrielh/projects/shotbot/type_definitions.py`
**Effort**: 20 minutes

**Add**:
```python
class RefreshMetrics(TypedDict):
    """Metrics from a refresh operation."""

    duration: float
    items_loaded: int
    items_added: int
    items_removed: int
    cache_hit: bool


class CacheRefreshResult(TypedDict):
    """Result of a cache refresh operation."""

    success: bool
    data: list[ShotDict] | list[ThreeDESceneDict]
    metrics: RefreshMetrics
    error: str | None
```

**Update cache_manager.py**:
```python
def refresh_shots(self) -> CacheRefreshResult:
    """Refresh shot cache from workspace."""
    ...
```

**Expected Warnings Eliminated**: 0 (improves clarity for future)

---

### Task 5.2: Create Literal Types for Common Strings

**File**: `/home/gabrielh/projects/shotbot/type_definitions.py`
**Effort**: 15 minutes

**Add**:
```python
# Process states
ProcessState = Literal["running", "finished", "error"]

# Component names for UI updates
ComponentName = Literal[
    "progress_bar",
    "status_label",
    "fps_display",
    "eta_display",
    "log_display",
    "file_list",
]

# Cache types
CacheType = Literal["shots", "scenes", "thumbnails", "previous_shots"]
```

**Usage**:
```python
def update_component(component: ComponentName, data: object) -> None:
    """Update UI component with type-safe names."""
    self.pending_updates[component] = data
```

**Expected Warnings Eliminated**: 0 (improves type safety)

---

## Verification Steps

### After Each Phase

```bash
# Run type check
~/.local/bin/uv run basedpyright .

# Run linting
~/.local/bin/uv run ruff check --select UP,TCH,ANN .

# Run tests
~/.local/bin/uv run pytest tests/ -q
```

### Expected Results

**Phase 1**: 57 → 50 warnings (-7)
**Phase 2**: 50 → 48 warnings (-2)
**Phase 3**: 48 → 45 warnings (-3)
**Phase 4**: 45 → 45 warnings (0, ruff only)
**Phase 5**: 45 → 45 warnings (0, clarity)

**Final Goal**: 0-5 warnings (all Qt/unavoidable)

---

## Implementation Checklist

### Pre-Implementation
- [ ] Read current analysis (TYPE_SAFETY_ANALYSIS.md)
- [ ] Create feature branch: `git checkout -b type-safety-improvements`
- [ ] Run baseline: `~/.local/bin/uv run basedpyright . --outputjson > baseline.json`

### Phase 1 Tasks
- [ ] Task 1.1: Fix filesystem_scanner.py
- [ ] Task 1.2: Fix ui_update_manager.py
- [ ] Task 1.3: Fix threede_grid_view.py
- [ ] Task 1.4: Fix thread_safe_worker.py
- [ ] Verify: `basedpyright . | tail -3`

### Phase 2 Tasks
- [ ] Task 2.1: Add UI TypedDict
- [ ] Task 2.2: Add TypeGuard functions
- [ ] Task 2.3: Update FinderProtocol TypeVar
- [ ] Verify: `basedpyright . | tail -3`

### Phase 3 Tasks
- [ ] Task 3.1: Create PySide6 stubs (if receivers() still warned)
- [ ] Task 3.2: Create VFX API stubs (if external APIs warned)
- [ ] Verify: `basedpyright . | tail -3`

### Phase 4 Tasks
- [ ] Task 4.1: Move type imports to TYPE_CHECKING
- [ ] Verify: `ruff check --select TCH .`

### Phase 5 Tasks
- [ ] Task 5.1: Define Result TypedDict
- [ ] Task 5.2: Create Literal types
- [ ] Verify: Run full test suite

### Post-Implementation
- [ ] Run final baseline: `~/.local/bin/uv run basedpyright . --outputjson > final.json`
- [ ] Verify no test failures: `~/.local/bin/uv run pytest tests/ -q`
- [ ] Create pull request with changes
- [ ] Update TYPE_SAFETY_ANALYSIS.md with final metrics

---

## Rollback Strategy

Each task is independent and safe to rollback:

```bash
# If Phase 1.1 breaks something:
git checkout filesystem_scanner.py
# Or just remove the type annotation:
prune_expr = []  # Back to original
```

**No breaking changes expected** - all modifications are additive type annotations.

---

## Effort Summary

| Phase | Tasks | Effort | Warnings Reduced |
|-------|-------|--------|-----------------|
| 1 | 4 | 55 min | 10 |
| 2 | 3 | 45 min | 2 |
| 3 | 2 | 50 min | 3 |
| 4 | 1 | 10 min | 0 |
| 5 | 2 | 30 min | 0 |
| **Total** | **12** | **3h 10min** | **15** |

**Remaining warnings** after all phases: ~42 (mostly Qt signal Any types, information-level)

---

## Success Criteria

- [ ] 0 type errors (already achieved)
- [ ] 40-45 warnings (down from 57)
- [ ] All high-value type annotations in place
- [ ] No test failures
- [ ] Code is more maintainable

---

## Notes

1. **Qt Signal Handlers**: The 30 "Any" notes are information-level and don't indicate errors. They're from Qt's @Slot() decorator and are acceptable.

2. **External APIs**: Without stubs, external VFX library calls will show warnings. Creating stubs (Phase 3) is optional but valuable.

3. **Prioritization**: Phase 1 should be done immediately (high ROI). Phases 2-5 can be spread over multiple commits.

4. **Testing**: Each change is safe - type annotations don't change runtime behavior.

5. **Future Maintenance**: Once improvements are in place, adding new code with proper types will be straightforward (use existing patterns as reference).

---

## Questions/Notes

- Add notes here during implementation
- Track any unexpected issues
- Document any deviations from plan
