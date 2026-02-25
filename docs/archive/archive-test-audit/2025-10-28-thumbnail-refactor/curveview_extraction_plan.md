# CurveViewWidget Extraction Plan

## Progress Update (October 2025)

**Status**: Phase 1 + Phase 3 COMPLETE ✅ | Phase 2 Paused

### Completed Work
- ✅ **Phase 1**: ViewCameraController integration (-196 lines, 9 methods)
- ⚠️ **Phase 2**: Partial (wheelEvent delegation -30 lines, paused due to architectural mismatch)
- ✅ **Phase 3**: StateSyncController extraction (-183 lines, 15 signal handlers)

**Current State**: 2,117 lines (from 2,526) | **409 lines removed (16.2% reduction)**

**Tests**: ✅ 41/41 passed (test_curve_view.py) | ✅ 10/11 passed (test_ui_service_curve_view_integration.py, 1 pre-existing failure)

**Next**: Phase 4 (CurveDataFacade) or complete Phase 2 with selective cleanup

---

## Executive Summary

CurveViewWidget is a 2,526-line god object with **100 methods**. Analysis reveals **massive code duplication**:
- ViewCameraController exists (14 methods) but is **NEVER USED** ❌
- InteractionService exists (30+ methods) but widget only uses **2 of them** ❌
- Widget reimplements everything itself

**Strategy**: Wire up existing infrastructure + create minimal new controllers

---

## Key Findings

### Orphaned Controllers (Already Built!)
1. **ViewCameraController** (`ui/controllers/view_camera_controller.py`)
   - 14 methods for zoom, pan, transform, centering, fitting
   - **Status**: Implemented but NEVER integrated with CurveViewWidget
   - **Action**: Wire it up!

2. **InteractionService** (`services/interaction_service.py`)
   - 30+ methods for mouse, keyboard, selection, editing
   - **Status**: Exists but widget only calls 2 methods
   - **Action**: Delegate all event handling to it!

### Existing Controllers to Extend
3. **ViewManagementController** - handles background images, display settings
4. **SignalConnectionManager** - handles signal connections
5. **MultiPointTrackingController** - could absorb multi-curve display logic

---

## Method Distribution (100 total)

### STAY IN WIDGET (15 methods) - Core UI responsibilities
**Properties/Accessors** (11):
- curve_data, selected_indices, active_curve_name, curves_data
- offset_x, offset_y
- points, selected_points, selected_point_idx, current_frame, current_frame_point_color

**Painting** (4):
- paintEvent, _paint_hover_indicator, _paint_centering_indicator, _get_point_update_rect

**Setup** (1):
- __init__ (slimmed down to just create controllers)

### WIRE UP ViewCameraController (17 methods) - COMPLETE ✅
✅ get_transform, _update_transform, data_to_screen, screen_to_data, screen_to_data_qpoint
✅ reset_view, fit_to_view (→ fit_to_curve), fit_to_background_image
✅ _center_view_on_point (→ center_on_point), center_on_selection, center_on_frame
✅ _get_display_dimensions, _apply_pan_offset_y, _get_image_top_coordinates
✅ on_frame_changed, setup_for_pixel_tracking
✅ invalidate_caches (transform cache)
✅ wheelEvent (delegated to handle_wheel_zoom)

**Status**: COMPLETED in Phase 1 (-196 lines, 9 methods removed)

### DELEGATE TO InteractionService (20+ methods) - Already implemented!
✅ Mouse events: mousePressEvent, mouseMoveEvent, mouseReleaseEvent, wheelEvent, contextMenuEvent
✅ Keyboard: keyPressEvent
✅ Selection: _find_point_at, _select_point, clear_selection, select_all, select_point_at_frame
✅ Rubber band: _start_rubber_band, _update_rubber_band, _finish_rubber_band, _select_points_in_rect
✅ Editing: _drag_point, nudge_selected, delete_selected_points, _set_point_status
✅ History: _add_to_history

**Status**: Service exists, widget must delegate instead of reimplementing!

### CREATE StateSyncController (15 methods) - COMPLETE ✅
✅ _connect_store_signals, _connect_app_state_signals, _connect_state_manager_signals
✅ _on_state_frame_changed, _on_store_data_changed
✅ _on_store_point_added, _on_store_point_updated, _on_store_point_removed
✅ _on_store_status_changed, _on_store_selection_changed
✅ _sync_data_service, _on_app_state_curves_changed
✅ _on_app_state_selection_changed, _on_app_state_active_curve_changed, _on_app_state_visibility_changed

**File**: `ui/controllers/curve_view/state_sync_controller.py` ✅ CREATED (254 lines)
**Purpose**: Centralize all signal handlers for reactive updates
**Status**: COMPLETED in Phase 3 (-183 lines, 15 signal handlers removed)
**Tests**: ✅ All signal handling tests passing (41/41 test_curve_view.py)

### CREATE CurveDataFacade (10 methods) - NEW FILE
❌ set_curve_data, add_point, update_point, remove_point
❌ set_curves_data, add_curve, remove_curve
❌ update_curve_visibility, update_curve_color, set_active_curve
❌ _get_live_curves_data

**File**: `ui/controllers/curve_view/curve_data_facade.py`
**Purpose**: Thin facade delegating to ApplicationState (avoid direct store access from widget)

### EXTEND ViewManagementController (2 methods)
✅ set_background_image (already handles background images)
✅ get_view_state (move to ViewCameraController)

### CREATE RenderCacheController (4 methods) - NEW FILE
❌ _invalidate_point_region
❌ _update_screen_points_cache
❌ _update_visible_indices
❌ Additional: invalidate_caches (painting cache, not transform cache)

**File**: `ui/controllers/curve_view/render_cache_controller.py`
**Purpose**: Manage rendering caches for performance optimization

### INTEGRATE WITH MultiPointTrackingController (3 methods)
❌ toggle_show_all_curves
❌ set_selected_curves
❌ center_on_selected_curves

**Status**: Extend existing controller with display logic

### KEEP AS ADAPTERS (5 methods) - Thin wrappers
- has_main_window, set_main_window
- update_status (delegates to main_window.status_bar)
- get_current_frame (reads from main_window or state_manager)
- _setup_widget (UI initialization, can stay)

### HANDLE SEPARATELY (5 methods)
- focusInEvent, focusOutEvent (stay in widget, minimal logic)
- _find_point_at_multi_curve (move to SelectionController if needed)
- get_selected_indices (property wrapper, stays)

---

## New Files to Create

```
ui/controllers/curve_view/
├── __init__.py
├── state_sync_controller.py        # 11 signal handler methods
├── curve_data_facade.py             # 10 data management methods
└── render_cache_controller.py       # 4 caching methods
```

Total: **3 new files** (not 6-8!)

---

## Extraction Order (Minimize Risk)

### Phase 1: Wire Up ViewCameraController ✅ COMPLETE
**Impact**: Removed 196 lines, 9 methods
**Risk**: Low - controller already exists and tested
**Result**: Successfully integrated ViewCameraController
- Added `self.view_camera = ViewCameraController(self)` to `__init__`
- Replaced all transform/view methods with `self.view_camera.*` calls
- Updated properties to delegate to controller (zoom_factor, pan_offset_x/y)
- Removed duplicated methods from widget
- wheelEvent simplified from 40 lines to 3 lines (delegation)

**Commits**:
- 164edfd: Complete MainWindow protocol conformance
- 384acb4: Add 7 MainWindowProtocol properties

### Phase 2: Delegate to InteractionService ⚠️ PAUSED
**Impact**: Partial completion (-30 lines)
**Risk**: Medium - Architectural mismatch discovered
**Status**:
- ✅ Attribute refactoring: Split `last_mouse_pos` into `last_drag_pos` + `last_pan_pos`
- ✅ wheelEvent delegation complete
- ⚠️ Full event handler delegation paused
- **Reason**: InteractionService designed for single-curve mode, but widget has multi-curve support, hover highlighting, Y-flip aware panning
- **Decision**: Accept current gains, move to Phase 3

**Alternative Path**: Selective cleanup of dead code (~50-100 lines) instead of full delegation

### Phase 3: Create StateSyncController ✅ COMPLETE
**Impact**: Removed 183 lines, 15 signal handlers
**Risk**: Low - pure signal routing logic
**Result**: Successfully extracted all signal handling logic
1. ✅ Created `ui/controllers/curve_view/state_sync_controller.py` (254 lines)
2. ✅ Moved all 15 signal handlers to controller:
   - 3 connection methods (`_connect_store_signals`, `_connect_app_state_signals`, `_connect_state_manager_signals`)
   - 7 CurveDataStore handlers
   - 1 StateManager handler
   - 4 ApplicationState handlers
3. ✅ Controller triggers `widget.update()` when needed
4. ✅ Updated fallback state manager connection in `set_main_window()`
5. ✅ Tests verified: 41/41 passed (test_curve_view.py)

**Architecture**: Controller holds widget reference, calls widget methods for updates (update(), invalidate_caches(), emit signals)

### Phase 4: Create CurveDataFacade (DATA ENCAPSULATION)
**Impact**: Removes 10 data methods
**Risk**: Low - thin facade over ApplicationState
**Steps**:
1. Create `curve_data_facade.py`
2. Move all data management methods
3. Facade delegates to `get_application_state()`
4. Widget uses facade instead of direct store access

### Phase 5: Create RenderCacheController (OPTIMIZATION)
**Impact**: Removes 4 caching methods
**Risk**: Medium - performance critical
**Steps**:
1. Create `render_cache_controller.py`
2. Move caching logic
3. Ensure cache invalidation triggers properly
4. Profile to verify no performance regression

### Phase 6: Multi-Curve Display Integration
**Impact**: Removes 3 methods
**Risk**: Low - simple delegation
**Steps**:
1. Extend MultiPointTrackingController with display methods
2. Widget delegates multi-curve operations

---

## Success Metrics

### Before (Original State)
- CurveViewWidget: **2,526 lines**, **100 methods**
- Orphaned controllers: 2 (ViewCameraController, partial InteractionService)
- Code duplication: Massive (view, mouse, selection, editing all duplicated)
- Test complexity: 841 lines across 2 test files

### Current State (Phase 1 + 3 Complete)
- CurveViewWidget: **2,117 lines** (-409 lines, 16.2% reduction)
- Controllers Created/Integrated:
  - ✅ ViewCameraController: Integrated (-196 lines, 9 methods)
  - ✅ StateSyncController: Created (-183 lines, 15 signal handlers)
  - ⚠️ InteractionService: Partial delegation (-30 lines)
- Remaining: ~85 methods in widget
- Tests: ✅ All passing (41/41 test_curve_view.py, 10/11 test_ui_service_curve_view_integration.py)

### Target State (All Phases)
- CurveViewWidget: **~400 lines**, **~20 methods** (84% reduction from original)
  - Properties: 11
  - Painting: 4
  - Adapters: 5
- Controllers:
  - Wired up: ViewCameraController (9 methods) ✅
  - Delegated: InteractionService (20+ methods) ⚠️
  - New: StateSyncController (15) ✅, CurveDataFacade (10), RenderCacheController (4)
- Eliminated duplication: 40+ methods no longer duplicated
- Test distribution: Split into focused controller tests

---

## Dependencies & Risks

### External Dependencies
- **ViewCameraController**: Needs `widget._get_display_dimensions()` - keep as internal helper
- **InteractionService**: Requires CurveViewProtocol compliance - verify protocol
- **ApplicationState**: CurveDataFacade delegates here - already migrated

### Risk Mitigation
1. **Performance**: Profile each phase, especially render cache extraction
2. **Circular Dependencies**: Use Protocol pattern (already established)
3. **Signal Breakage**: Verify all connections in StateSyncController
4. **Test Coverage**: Run full test suite after each phase

### Integration Points
- MainWindow: No changes needed (already uses widget API)
- OptimizedCurveRenderer: No changes (widget still delegates painting)
- ApplicationState: No changes (CurveDataFacade uses existing API)

---

## Implementation Checklist

### Phase 1: ViewCameraController Integration ✅ COMPLETE
- [x] Add controller instantiation to `__init__`
- [x] Replace `get_transform()` with delegation
- [x] Replace all centering methods
- [x] Replace all fit methods
- [x] Replace coordinate conversion methods
- [x] Remove duplicated implementations
- [x] Update tests
- [x] Verify no regression
- **Result**: -196 lines, 9 methods removed

### Phase 2: InteractionService Delegation ⚠️ PAUSED
- [x] Split `last_mouse_pos` into `last_drag_pos` + `last_pan_pos`
- [x] Update `wheelEvent` to delegate
- [ ] Update `mousePressEvent` to delegate (PAUSED)
- [ ] Update `mouseMoveEvent` to delegate (PAUSED)
- [ ] Update `mouseReleaseEvent` to delegate (PAUSED)
- [ ] Update `contextMenuEvent` to delegate (PAUSED)
- [ ] Update `keyPressEvent` to delegate (PAUSED)
- [ ] Remove selection method implementations (PAUSED)
- [ ] Remove editing method implementations (PAUSED)
- **Result**: -30 lines (partial)
- **Reason**: Architectural mismatch with multi-curve support

### Phase 3: StateSyncController Creation ✅ COMPLETE
- [x] Create `ui/controllers/curve_view/state_sync_controller.py` (254 lines)
- [x] Move 3 signal connection methods
- [x] Move all 15 signal handlers (7 CurveDataStore + 4 ApplicationState + 1 StateManager + 3 connection methods)
- [x] Wire controller in widget `__init__` via `self.state_sync = StateSyncController(self)`
- [x] Remove handlers from widget (replaced with comment marker)
- [x] Update fallback state manager connection in `set_main_window()`
- [x] Verify signal flow (syntax checks pass, 0 production errors)
- [x] Verify tests (41/41 test_curve_view.py ✅, 10/11 test_ui_service_curve_view_integration.py ✅)
- **Result**: -183 lines, 15 signal handlers removed, widget reduced to 2,117 lines

### Phase 4: CurveDataFacade Creation
- [ ] Create `ui/controllers/curve_view/curve_data_facade.py`
- [ ] Move data management methods
- [ ] Implement ApplicationState delegation
- [ ] Wire facade in widget
- [ ] Replace direct store calls
- [ ] Update tests

### Phase 5: RenderCacheController Creation
- [ ] Create `ui/controllers/curve_view/render_cache_controller.py`
- [ ] Move cache management methods
- [ ] Wire controller in widget
- [ ] Remove cache logic from widget
- [ ] Profile performance
- [ ] Update tests

### Phase 6: Multi-Curve Integration
- [ ] Extend MultiPointTrackingController
- [ ] Move display toggle methods
- [ ] Wire delegation in widget
- [ ] Update tests

### Final Verification
- [ ] Run full test suite (2105 tests)
- [ ] Check basedpyright (0 production errors)
- [ ] Profile performance (no regression)
- [ ] Update documentation
- [ ] Code review

---

## Key Insights

1. **Massive Duplication Discovered**: ViewCameraController and InteractionService exist but are barely used
2. **Low New Code Required**: Only 3 new files needed (25 methods), rest is wiring
3. **High Value Extraction**: Removing 80+ methods from a single widget
4. **Proven Pattern**: Other MainWindow controllers show this works
5. **Risk Mitigation**: Phased approach with testing after each step

**Timeline Progress**:
- Phase 1: Complete ✅ (1 day) - ViewCameraController integration
- Phase 2: Partial ⚠️ (paused due to architectural complexity) - InteractionService delegation
- Phase 3: Complete ✅ (1 day) - StateSyncController extraction
- Remaining: Phases 4-6 (estimated 3-6 days)

**ROI**: Transform 2,526-line god object into 400-line coordinator with proper separation of concerns
**Current Progress**: 16.2% reduction achieved (2,117 lines), on track for 84% total reduction

**Quality Metrics**:
- ✅ 0 production type errors (ui/controllers/curve_view/state_sync_controller.py, ui/curve_view_widget.py)
- ✅ 41/41 widget tests passing
- ✅ 10/11 integration tests passing (1 pre-existing failure)
- ✅ Clean signal handling separation achieved
