# reportAttributeAccessIssue Ignore Comment Audit Report

**Date**: 2025-10-20
**Total Instances Audited**: 11 (reduced from 12 after fixing threede_grid_delegate.py bug)

## Executive Summary

- **3 BUGS FIXED**: Missing stub file declarations (cache_manager.pyi, utils.pyi)
- **6 LEGITIMATE**: Required for Qt framework quirks and private API access
- **2 UNNECESSARY**: Removed after adding proper stub declarations

## Detailed Findings

### 🐛 BUGS FIXED (3)

#### 1. `cache_manager.pyi` - Missing `has_valid_threede_cache()` method
**Files affected**: `main_window.py:770`

**Issue**: The stub file was missing the `has_valid_threede_cache()` method that exists in the implementation.

**Fix**: Added method signature to `cache_manager.pyi`:
```python
def has_valid_threede_cache(self) -> bool: ...
```

**Impact**: Removed 1 unnecessary ignore comment in `main_window.py`

---

#### 2. `utils.pyi` - Missing `PathUtils.find_shot_thumbnail()` method
**Files affected**:
- `type_definitions.py:152`
- `threede_scene_model.py:89`

**Issue**: The stub file was missing `find_shot_thumbnail()` which exists in the implementation.

**Fix**: Added method signature to `utils.pyi`:
```python
@staticmethod
def find_shot_thumbnail(
    shows_root: str,
    show: str,
    sequence: str,
    shot: str,
) -> Path | None: ...
```

**Impact**: Removed 2 unnecessary ignore comments and removed unnecessary casts

---

#### 3. `utils.pyi` - Missing `ImageUtils.is_image_too_large_for_thumbnail()` method
**Files affected**: `shot_info_panel.py:362`

**Issue**: The stub file was missing `is_image_too_large_for_thumbnail()`.

**Fix**: Added method signature to `utils.pyi`:
```python
@staticmethod
def is_image_too_large_for_thumbnail(
    size: object,  # QSize or compatible object with width()/height()
    max_dimension: int,
) -> bool: ...
```

**Impact**: Removed 1 unnecessary ignore comment

---

### ✅ LEGITIMATE IGNORES (6)

#### 1-2. `base_thumbnail_delegate.py:196-197` - PySide6 incomplete type stubs
**Why legitimate**: PySide6's type stubs are missing `.rect` and `.state` attributes on `QStyleOptionViewItem`, but these attributes exist at runtime and are documented in Qt API.

**Comment improved**:
```python
# PySide6 type stubs missing .rect and .state attributes on QStyleOptionViewItem
# These attributes exist at runtime and are documented in Qt API
rect = cast("QRect", option.rect)  # pyright: ignore[reportAttributeAccessIssue]
state = cast("QStyle.StateFlag", option.state)  # pyright: ignore[reportAttributeAccessIssue]
```

---

#### 3-4. `main_window.py:1190` and `controllers/threede_controller.py:620` - Generic handlers with varying signatures
**Why legitimate**: Different item models have different `set_show_filter()` signatures. The code uses `object` types for generic handling across all tabs. This is a deliberate design pattern for flexibility.

**Signatures vary**:
- `ShotItemModel.set_show_filter(BaseShotModel, str | None)`
- `PreviousShotsItemModel.set_show_filter(PreviousShotsModel, str | None)`
- `ThreeDEItemModel.set_show_filter(ThreeDESceneModel, str | None)`

**Comment improved**:
```python
# Different item models have varying set_show_filter signatures:
# - ShotItemModel.set_show_filter(BaseShotModel, str | None)
# - PreviousShotsItemModel.set_show_filter(PreviousShotsModel, str | None)
# We use object types for generic handling across all tabs
item_model.set_show_filter(model, show_filter)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
```

---

#### 5. `previous_shots_model.py:157` - Dynamic attribute with hasattr check
**Why legitimate**: Runtime polymorphism - `PreviousShotsWorker` uses `scan_progress`, while `ThreeDESceneWorker` uses `progress`. The `hasattr` check handles this at runtime.

**Comment improved**:
```python
# Runtime hasattr check handles polymorphism - attribute may not exist
if hasattr(worker, "progress"):
    worker.progress.disconnect()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
```

---

#### 6-7. `process_pool_manager.py:551` and `563` - ThreadPoolExecutor private API
**Why legitimate**: Accessing `ThreadPoolExecutor._pending_work_items` and `work_item.future` (private internals) is required for proper cleanup of pending futures during shutdown. This is not part of the public API but is stable across Python versions.

**Comment improved**:
```python
# Access ThreadPoolExecutor._pending_work_items (private API)
# Required for proper cleanup of pending futures on shutdown
# Type checking disabled: not in public API but stable across Python versions
pending_items_raw = self._executor._pending_work_items  # type: ignore[attr-defined]  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAttributeAccessIssue]
```

---

## Impact Summary

| Category | Count | Action Taken |
|----------|-------|--------------|
| Bugs Fixed | 3 | Added missing stub declarations |
| Legitimate Ignores | 6 | Improved explanatory comments |
| Unnecessary Ignores | 2 | Removed after stub fixes |
| **Total** | **11** | |

## Verification

All changes verified with basedpyright:
```bash
~/.local/bin/uv run basedpyright
# Result: 0 errors, 0 warnings, 0 notes
```

## Lessons Learned

1. **Incomplete stub files are a common source of false type errors** - Always check if the method exists in the implementation before adding an ignore.

2. **The previous ModifiedTimeRole bug was caught because the enum value didn't exist** - That was a real bug hiding behind an ignore comment. The bugs we found today were different: the methods DID exist, but were missing from stub files.

3. **Strategic use of `object` types for generic handlers is legitimate** - When you have multiple implementations with different signatures, using `object` and runtime type safety is acceptable.

4. **Private API access requires clear justification** - The ThreadPoolExecutor cases are legitimate because they're required for proper cleanup, but the comments now clearly explain WHY.

5. **Qt framework quirks (incomplete type stubs) are unavoidable** - PySide6's type stubs are maintained separately from Qt and sometimes lag behind.

## Recommendations

1. **Regular stub file audits**: Periodically check that stub files (`.pyi`) are kept in sync with implementations.

2. **Prefer Protocol over object types**: For cases 3-4, we could define a Protocol with `set_show_filter()` to get better type safety, but the current design choice is still valid.

3. **Document stub file maintenance**: Add a note in CLAUDE.md about keeping stub files synchronized.

4. **Consider contributing to PySide6-stubs**: The missing `.rect` and `.state` attributes could be reported upstream.
