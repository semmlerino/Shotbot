# QWidget Compliance Violations - Quick Reference

## Summary
- **Total Violations**: 34
- **Critical (Main Code)**: 4
- **Non-Critical (Tests)**: 30
- **Class Definitions**: 100% Compliant

## Critical Violations (Fix Immediately)

### 1. main_window.py:438
**File**: `/home/gabrielh/projects/shotbot/main_window.py`  
**Line**: 438  
**Widget**: ShotInfoPanel

```python
# BEFORE
self.shot_info_panel = ShotInfoPanel(self.cache_manager)

# AFTER
self.shot_info_panel = ShotInfoPanel(self.cache_manager, parent=self)
```

### 2. main_window.py:442
**File**: `/home/gabrielh/projects/shotbot/main_window.py`  
**Line**: 442  
**Widget**: LauncherPanel

```python
# BEFORE
self.launcher_panel = LauncherPanel()

# AFTER
self.launcher_panel = LauncherPanel(parent=self)
```

### 3. main_window.py:459
**File**: `/home/gabrielh/projects/shotbot/main_window.py`  
**Line**: 459  
**Widget**: LogViewer

```python
# BEFORE
self.log_viewer = LogViewer()

# AFTER
self.log_viewer = LogViewer(parent=self)
```

### 4. ui_components.py:334
**File**: `/home/gabrielh/projects/shotbot/ui_components.py`  
**Line**: 334  
**Widget**: LoadingSpinner

```python
# BEFORE
self.spinner: LoadingSpinner = LoadingSpinner(40)

# AFTER (Option A - Recommended)
self.spinner: LoadingSpinner = LoadingSpinner(40, parent=card)

# AFTER (Option B)
self.spinner: LoadingSpinner = LoadingSpinner(40, parent=self)
```

---

## Test Code Violations

### tests/unit/test_log_viewer.py (18 violations)
**Lines**: 52, 66, 84, 104, 123, 142, 168, 184, 204, 226, 248, 270, 301, 318, 338, 353, 365, 384

Pattern: `log_viewer = LogViewer()` → `log_viewer = LogViewer(parent=None)`

### tests/unit/test_shot_info_panel_comprehensive.py (3 violations)
**Lines**: 62, 236, 393

Pattern: `panel = ShotInfoPanel()` → `panel = ShotInfoPanel(parent=None)`  
Pattern: `panel = ShotInfoPanel(cache)` → `panel = ShotInfoPanel(cache, parent=None)`

### tests/integration/test_async_workflow_integration.py (2 violations)
**Lines**: 104, 444

Pattern: `ShotInfoPanel(cache_manager)` → `ShotInfoPanel(cache_manager, parent=None)`

### tests/unit/test_ui_components.py (7 violations)
**Lines**: 26, 45, 53, 61, 90, 113, 121

- Line 26: `ModernButton("Test Button")` → `ModernButton("Test Button", parent=None)`
- Line 45: `ModernButton("Delete", variant="danger")` → `ModernButton("Delete", variant="danger", parent=None)`
- Line 53: `ModernButton("Save", variant="primary")` → `ModernButton("Save", variant="primary", parent=None)`
- Line 61: `ModernButton("Click Me")` → `ModernButton("Click Me", parent=None)`
- Line 90: `EmptyStateWidget(...)` → `EmptyStateWidget(..., parent=None)`
- Line 113: `ThumbnailPlaceholder()` → `ThumbnailPlaceholder(parent=None)`
- Line 121: `ThumbnailPlaceholder(size=150)` → `ThumbnailPlaceholder(size=150, parent=None)`

---

## Compliance Status by File

### Main Code (Production)
- ✓ launcher_dialog.py (4 classes) - Compliant
- ✓ shot_info_panel.py (1 class) - Compliant
- ✓ ui_components.py (7 classes) - 1 violation at line 334
- ✓ main_window.py (1 class) - 3 violations at lines 438, 442, 459
- ✓ main_window_refactored.py (1 class) - Compliant
- ✓ base_grid_view.py (1 class) - Compliant
- ✓ threede_recovery_dialog.py (2 classes) - Compliant
- ✓ thumbnail_loading_indicator.py (2 classes) - Compliant
- ✓ settings_dialog.py (1 class) - Compliant
- ✓ launcher_panel.py (1 class) - Compliant
- ✓ log_viewer.py (1 class) - Compliant

### Test Code
- tests/unit/test_log_viewer.py - 18 violations
- tests/unit/test_shot_info_panel_comprehensive.py - 3 violations
- tests/integration/test_async_workflow_integration.py - 2 violations
- tests/unit/test_ui_components.py - 7 violations

---

## Why This Matters

From CLAUDE.md:

> ALL QWidget subclasses MUST accept an optional parent parameter and pass it to super().__init__()
> 
> Missing parent parameter causes Qt C++ crashes during initialization, even in serial test execution.
> Error manifests as 'Fatal Python error: Aborted' at logging_mixin.py:269 → qt_widget_mixin.py:63 → Qt C++

### Qt Ownership Rules
- Parent parameter controls Qt C++ object ownership
- Missing parent = ownership ambiguity
- Python GC and Qt C++ ownership can diverge
- Result: Double-free, use-after-free, or orphaned objects

### Risk Triggers
- Rapid widget creation/destruction
- Memory pressure scenarios  
- Specific Qt event loop timing
- Complex parent-child hierarchies

---

## Effort Estimate

- **Critical fixes**: ~10 minutes (4 violations)
- **Test fixes**: ~20 minutes (30 violations)
- **Total**: ~30 minutes

---

## For More Details
See: `QWIDGET_COMPLIANCE_AUDIT.txt` (24KB comprehensive report)
