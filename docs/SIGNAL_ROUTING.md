# MainWindow Signal Routing

This file documents signal-routing invariants that should remain stable during refactors.
It intentionally avoids line-by-line connection inventories.

## Critical Invariants

If any route below is removed or changed, core behavior breaks.

| Route | Required behavior |
|-------|-------------------|
| `shot_model.shots_loaded` → `refresh_coordinator.handle_shots_loaded` | Initial data display and downstream previous-shots refresh |
| `shot_model.shots_changed` → `refresh_coordinator.handle_shots_changed` | UI update after background refresh delta |
| `shot_model.shots_loaded` / `shots_changed` → `refresh_coordinator.trigger_previous_shots_refresh` | Cascading previous-shots refresh after shot data changes |
| `ShotDataCache.shots_migrated` -> `PreviousShotsModel._on_cache_shots_migrated` | Previous-shots tab stays in sync after migration (direct connection, bypasses MainWindow) |
| `tab_widget.currentChanged` -> `shot_selection_controller.on_tab_activated` + `threede_controller.on_tab_activated` | Tab data loading and tab-specific visual state |
| `shot_grid.app_launch_requested` -> launcher | My Shots launches in shot context |
| `threede_shot_grid.app_launch_requested` -> scene-aware launch path | 3DE opens the selected `.3de` file; Maya/Nuke/RV must use the selected scene's workspace/context unless a DCC-native file was explicitly chosen |
| `previous_shots_grid.app_launch_requested` -> launcher | Previous Shots launches correctly |

> **Scope note:** This table lists the primary data-flow routes critical for core behavior.
> MainWindow wires additional connections (error handling, cache events, launch lifecycle, sort sync)
> that are covered by integration tests but not individually documented here.
> Run `rg -n "\.connect\(" main_window.py` to discover the full set.

## Secondary Invariants

These are not usually app-breaking, but regressions are user-visible:

- Right panel launch request wiring
- 3DE-grid launch semantics: file-open for `3de`, context-only for other DCCs
- Thumbnail size synchronization across tabs
- Sort-order synchronization between related views
- Log viewer visibility toggle
- Menu action wiring (refresh/settings/help actions)

## Ownership Boundaries

- MainWindow owns top-level cross-component routing.
- `RefreshCoordinator` owns the *handling* of shot refresh signals (`refresh_started`, `refresh_finished`); signal *definitions* live on `BaseShotModel` alongside `shots_loaded` and `shots_changed`.
- `BaseGridView` owns show/text filter signals (`show_filter_requested`, `text_filter_requested`); MainWindow routes them directly.
- `ThumbnailSizeManager` owns size-slider synchronization.
- `ThreeDEController` owns worker lifecycle and worker signal setup.

Do not move signals across these boundaries without updating tests and docs.

## Change Checklist

1. Search for all affected connections:

   ```bash
   rg -n "\.connect\(" main_window.py controllers/
   ```

2. Confirm each removed connection has a replacement route.
3. Verify signal emissions still happen in model/controller code.
4. Run integration tests touching MainWindow coordination:

   ```bash
   uv run pytest tests/integration/test_main_window_integration.py -v
   uv run pytest tests/integration/test_threede_launch_integration.py -v
   uv run pytest tests/integration/test_shutdown_sequence.py -v
   ```
5. When the launch source is a `ThreeDEScene`, verify that non-3DE apps do not
   receive the `.3de` file path as their scene/workfile argument.

