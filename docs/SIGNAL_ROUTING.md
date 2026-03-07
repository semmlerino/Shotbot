# MainWindow Signal Routing

This file documents signal-routing invariants that should remain stable during refactors.
It intentionally avoids line-by-line connection inventories.

## Critical Invariants

If any route below is removed or changed, core behavior breaks.

| Route | Required behavior |
|-------|-------------------|
| `shot_model.shots_loaded` → `refresh_orchestrator.handle_shots_loaded` | Initial data display and downstream previous-shots refresh |
| `shot_model.shots_changed` → `refresh_orchestrator.handle_shots_changed` | UI update after background refresh delta |
| `cache_manager.shots_migrated` -> MainWindow handler | Previous-shots tab stays in sync after migration |
| `tab_widget.currentChanged` -> tab-change handler | Tab data loading and tab-specific visual state |
| `shot_grid.app_launch_requested` -> launcher | My Shots launches in shot context |
| `threede_shot_grid.app_launch_requested` -> scene-aware launch path | 3DE launches with selected scene file |
| `previous_shots_grid.app_launch_requested` -> launcher | Previous Shots launches correctly |

> **Scope note:** This table lists the primary data-flow routes critical for core behavior.
> MainWindow wires additional connections (error handling, cache events, launch lifecycle, sort sync)
> that are covered by integration tests but not individually documented here.
> Run `rg -n "\.connect\(" main_window.py` to discover the full set.

## Secondary Invariants

These are not usually app-breaking, but regressions are user-visible:

- Right panel launch request wiring
- Thumbnail size synchronization across tabs
- Sort-order synchronization between related views
- Log viewer visibility toggle
- Menu action wiring (refresh/settings/help actions)

## Ownership Boundaries

- MainWindow owns top-level cross-component routing.
- `RefreshOrchestrator` owns shot refresh handling (`shots_loaded`, `shots_changed`, `refresh_started`, `refresh_finished`).
- `FilterCoordinator` owns show/text filter signals.
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

## High-Risk Changes

- Reworking shot refresh handlers (`shots_loaded` / `shots_changed`)
- Modifying launch-request paths
- Changing tab-switch flow
- Changing cross-thread signal behavior for cache migration

## Low-Risk Changes

- Cosmetic menu wiring (if handlers remain reachable)
- Log viewer toggle details
- Optional visual sync behavior that does not affect data flow
