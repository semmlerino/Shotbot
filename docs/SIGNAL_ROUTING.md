# MainWindow Signal Routing

> **Purpose**: Document all Qt signal connections in MainWindow to reduce surprise breakage during refactoring.
>
> **Last Updated**: February 2026

## Overview

MainWindow has **~40 signal connections** making it the central coupling hub. This document groups connections by subsystem and marks which are critical for app functionality.

---

## Signal Connection Summary

| Category | Count | Critical | Owner |
|----------|-------|----------|-------|
| Shot Model Signals | 9 | Yes | MainWindow |
| Cache Manager | 1 | Yes | MainWindow |
| Grid View Signals | 9 | Yes | MainWindow |
| Tab Widget | 2 | Yes | MainWindow |
| Right Panel | 3 | No | MainWindow |
| Menu Actions | 6 | No | MainWindow |
| Sort Sync | 2 | No | MainWindow |
| Filter Signals | 5 | No | FilterCoordinator |
| Size Sync | 3 | No | ThumbnailSizeManager |
| **Total** | **40** | **21** | **Various** |

---

## Critical Signal Routes (App Breaks Without These)

### Shot Loading Pipeline

```
ShotModel                              MainWindow                        RefreshOrchestrator          ShotItemModel
    │                                      │                                   │                          │
    ├─ shots_loaded ──────────────────────>│ _on_shots_loaded()                │                          │
    │                                      │   ├─> orchestrator.handle_shots_loaded() ─────────────────>│ set_shots()
    │                                      │   └─> _trigger_previous_shots_refresh()                    │
    │                                      │         └─> orchestrator.trigger_previous_shots_refresh()  │
    │                                      │                                   │                          │
    ├─ shots_changed ─────────────────────>│ _on_shots_changed()               │                          │
    │                                      │   ├─> orchestrator.handle_shots_changed() ────────────────>│ set_shots()
    │                                      │   └─> _trigger_previous_shots_refresh()                    │
    │                                      │                                   │                          │
    ├─ background_load_started ───────────>│ _on_background_load_started()     │                          │
    │                                      │     └─> status bar update         │                          │
    │                                      │                                   │                          │
    ├─ background_load_finished ──────────>│ _on_background_load_finished()    │                          │
    │                                      │     (status update via shots_loaded/shots_changed)           │
    │                                      │                                   │                          │
    ├─ refresh_started ───────────────────>│ _on_refresh_started()             │                          │
    │                                      │   └─> orchestrator.handle_refresh_started()                 │
    │                                      │         └─> status bar update     │                          │
    │                                      │                                   │                          │
    ├─ refresh_finished ──────────────────>│ _on_refresh_finished()            │                          │
    │                                      │   └─> orchestrator.handle_refresh_finished()                │
    │                                      │         └─> close progress dialog, restore shot selection   │
    │                                      │                                   │                          │
    ├─ error_occurred ────────────────────>│ _on_shot_error()                  │                          │
    │                                      │     └─> show error notification   │                          │
    │                                      │                                   │                          │
    ├─ cache_updated ─────────────────────>│ _on_cache_updated()               │                          │
    │                                      │     └─> log cache update          │                          │
    │                                      │                                   │                          │
    └─ data_recovery_occurred ────────────>│ _on_data_recovery()               │                          │
                                           │     └─> show recovery notification│                          │
```

**Location**: `main_window.py:617-634`

**Note on `_on_shots_loaded` side-effect**: Both `_on_shots_loaded` and `_on_shots_changed` also call `_trigger_previous_shots_refresh(shots)` (delegated to `RefreshOrchestrator.trigger_previous_shots_refresh()`), which starts a `PreviousShotsModel` refresh only when active shots are available. This prevents the "No target shows found" warning on startup when shots have not yet loaded.

**Note on `shots_changed`**: Emitted by `ShotModel` when a background refresh completes and the shot list has changed from the cached version. Unlike `shots_loaded` (which fires first with cached data), `shots_changed` fires when fresh data differs from what was already displayed.

### Cache Migration

```
CacheManager                           MainWindow
    │                                      │
    └─ shots_migrated ────────────────────>│ _on_shots_migrated()
                                           │     └─> update previous shots model
```

**Location**: `main_window.py:637-639`
**Connection Type**: `Qt.ConnectionType.QueuedConnection` (cross-thread safe)

### Tab Switching

```
QTabWidget                             MainWindow
    │                                      │
    ├─ currentChanged ────────────────────>│ _on_tab_changed()
    │                                      │     ├─> load data for tab
    │                                      │     ├─> update right panel
    │                                      │     └─> update filters
    │                                      │
    └─ currentChanged ────────────────────>│ _update_tab_accent_color()
                                           │     └─> apply tab-specific styling
```

**Location**: `main_window.py:453, 667`
**Note**: Two separate connections to the same signal.

### Grid Launch Requests

```
ShotGridView                           CommandLauncher
    │                                      │
    └─ app_launch_requested ──────────────>│ launch_app()
                                           │     └─> spawn DCC application

ThreeDEGridView                        MainWindow
    │                                      │
    └─ app_launch_requested ──────────────>│ _launch_app_with_scene_context()
                                           │     └─> launch with scene file

PreviousShotsView                      CommandLauncher
    │                                      │
    └─ app_launch_requested ──────────────>│ launch_app()
```

**Location**: `main_window.py:644-664`

---

## Non-Critical Signal Routes

### Filter Signals (FilterCoordinator)

**Moved to `controllers/filter_coordinator.py`** - No longer in MainWindow.

```
ShotGridView                           FilterCoordinator
    ├─ show_filter_requested ─────────────>│ _on_shot_show_filter_requested()
    └─ text_filter_requested ─────────────>│ _on_shot_text_filter_requested()

PreviousShotsView                      FilterCoordinator
    ├─ show_filter_requested ─────────────>│ _on_previous_show_filter_requested()
    └─ text_filter_requested ─────────────>│ _on_previous_text_filter_requested()

PreviousShotsItemModel                 FilterCoordinator
    └─ shots_updated ────────────────────>│ _on_previous_shots_updated()
```

**Location**: `controllers/filter_coordinator.py:83-100`

### Right Panel

```
RightPanelWidget                       MainWindow
    └─ launch_requested ──────────────────>│ _on_right_panel_launch()

CommandLauncher                        RightPanelWidget
    ├─ launch_pending ────────────────────>│ set_search_pending(True)
    └─ launch_ready ──────────────────────>│ set_search_pending(False)
```

**Location**: `main_window.py:670-678`

### Size Synchronization (ThumbnailSizeManager)

**Moved to `controllers/thumbnail_size_manager.py`** - No longer in MainWindow.

```
ShotGridView.size_slider               ThumbnailSizeManager
    └─ valueChanged ──────────────────────>│ _sync_thumbnail_sizes()

ThreeDEGridView.size_slider            ThumbnailSizeManager
    └─ valueChanged ──────────────────────>│ _sync_thumbnail_sizes()

PreviousShotsView.size_slider          ThumbnailSizeManager
    └─ valueChanged ──────────────────────>│ _sync_thumbnail_sizes()
```

**Location**: `controllers/thumbnail_size_manager.py:75-82`

### Sort Order Synchronization (MainWindow)

```
ThreeDEGridView                        MainWindow
    └─ sort_order_changed ────────────────>│ _on_threede_sort_order_changed()

PreviousShotsView                      MainWindow
    └─ sort_order_changed ────────────────>│ _on_previous_shots_sort_order_changed()
```

**Location**: `main_window.py:683-688`

### Menu Actions

| Action | Signal | Handler |
|--------|--------|---------|
| Refresh | `triggered` | `_refresh_shots()` |
| Import Settings | `triggered` | `settings_controller.import_settings()` |
| Export Settings | `triggered` | `settings_controller.export_settings()` |
| Exit | `triggered` | `close()` |
| Increase Size | `triggered` | `thumbnail_size_manager.increase_size()` |
| Decrease Size | `triggered` | `thumbnail_size_manager.decrease_size()` |
| Reset Layout | `triggered` | `settings_controller.reset_layout()` |
| Preferences | `triggered` | `settings_controller.show_preferences()` |
| Shortcuts | `triggered` | `_show_shortcuts()` |
| About | `triggered` | `_show_about()` |

**Location**: `main_window.py:511-576`

### Log Viewer

```
QGroupBox (log_group)                  LogViewer
    └─ toggled ───────────────────────────>│ setVisible()
```

**Location**: `main_window.py:474`

---

## Controller-Managed Signals

These signals are **not** connected in MainWindow. Controllers manage them internally:

### ShotSelectionController
- `shot_grid.shot_selected`
- `shot_grid.shot_double_clicked`
- `shot_grid.recover_crashes_requested`
- `previous_shots_grid.shot_selected`
- `previous_shots_grid.shot_double_clicked`

### ThreeDEController
- `threede_shot_grid.scene_selected`
- `threede_shot_grid.scene_double_clicked`
- `threede_shot_grid.recover_crashes_requested`
- `threede_shot_grid.show_filter_requested`
- `threede_shot_grid.text_filter_requested`

All ThreeDEController signal connections use `ThreadSafeWorker.safe_connect()` (via `_setup_worker_signals`) to ensure deduplication and automatic cleanup when the worker thread finishes.

### FilterCoordinator
- `shot_grid.show_filter_requested`
- `shot_grid.text_filter_requested`
- `previous_shots_grid.show_filter_requested`
- `previous_shots_grid.text_filter_requested`
- `previous_shots_item_model.shots_updated`

### ThumbnailSizeManager
- `shot_grid.size_slider.valueChanged`
- `threede_shot_grid.size_slider.valueChanged`
- `previous_shots_grid.size_slider.valueChanged`

---

## Refactoring Guidelines

### Before Changing Any Model Signal

1. Check this document for all handlers
2. Verify handler still exists in MainWindow
3. Run affected integration tests

### Before Removing a Handler

1. Grep for all `.connect(self._handler_name)` calls
2. Check if controller also uses the handler
3. Verify no other component expects the side effect

### Safe to Modify

- Menu action handlers (isolated)
- Size/sort sync (cosmetic)
- Log viewer toggle (cosmetic)

### High Risk to Modify

- `shots_loaded` → breaks data display and previous shots trigger
- `shots_changed` → breaks refresh display update
- `shots_migrated` → breaks previous shots
- `currentChanged` → breaks tab switching
- `app_launch_requested` → breaks DCC launching

---

## Testing Signal Connections

```python
# Verify critical connections exist
def test_critical_signals_connected(main_window):
    """All critical signals must be connected."""
    # Shot model signals
    assert main_window.shot_model.shots_loaded.receivers() > 0
    assert main_window.shot_model.shots_changed.receivers() > 0
    assert main_window.shot_model.error_occurred.receivers() > 0

    # Cache manager
    assert main_window.cache_manager.shots_migrated.receivers() > 0

    # Tab widget
    assert main_window.tab_widget.currentChanged.receivers() >= 2

    # Grid launch
    assert main_window.shot_grid.app_launch_requested.receivers() > 0
```
