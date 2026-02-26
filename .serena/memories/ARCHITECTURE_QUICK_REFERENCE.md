# Shotbot Architecture - Quick Reference

> See `CLAUDE.md` for project overview, commands, and matchmove pipeline context.
> This memory provides architectural patterns and structure for AI context loading.
> Last Updated: February 2026

## Layer Breakdown

### 1. PRESENTATION (Qt UI)
- **MainWindow** — Central orchestrator, signal routing
- **3 Grid Systems** — Independent data pipelines with views/delegates (shots, 3DE scenes, previous shots)
- **Panels & Dialogs** — Info display, launch controls, settings

### 2. CONTROLLERS (Coordination)
- **SettingsController** — Preferences management
- **ThreeDEController** — 3DE scene operations
- **FilterCoordinator** — Cross-tab filter/search logic
- **ShotSelectionController** — Shot selection state
- **ThumbnailSizeManager** — Thumbnail size sync across tabs

### 3. MODELS (Data & Logic)
Three parallel pipelines:
- **ShotModel** — Workspace integration + async loading
- **ThreeDESceneModel** — Filesystem discovery + incremental cache
- **PreviousShotsModel** — Historical data

Generic infrastructure:
- **BaseShotModel** — Shared shot parsing
- **BaseItemModel[T]** — Generic Qt model with lazy loading
- **BaseGridView** — Common grid functionality

### 4. SYSTEM INTEGRATION (I/O & Execution)
- **ProcessPoolManager** — Singleton subprocess pool, command caching, round-robin load balancing
- **CacheManager** — Multi-level caching (memory + disk) with TTL strategies
- **RefreshOrchestrator** — Periodic refresh coordination

### 5. INFRASTRUCTURE (Support)
- **Mixins**: LoggingMixin, ErrorHandlingMixin, QtWidgetMixin, ProgressReportingMixin, VersionHandlingMixin
- **Configuration**: Config, SettingsManager, EnvironmentManager
- **Managers**: NotificationManager, ProgressManager, FilesystemCoordinator
- **Threading**: ThreadSafeWorker, signal/slot coordination, ThreeDEController

## Dependency Hierarchy

```
TIER 1: Entry Point
  shotbot.py → MainWindow

TIER 2: Orchestration
  MainWindow → (everything below)

TIER 3: Coordination
  Controllers → Managers
  Models → ProcessPoolManager, CacheManager

TIER 4: Core Services
  ProcessPoolManager → ThreadPool
  CacheManager → File I/O, PIL

TIER 5: Generic Infrastructure
  BaseItemModel[T], BaseShotModel, BaseGridView

TIER 6: Support
  Mixins, Configuration, Utilities
```

## Key Design Patterns

| Pattern | Usage |
|---------|-------|
| **MVC** | Core architecture |
| **Singleton** | ProcessPoolManager, FilesystemCoordinator, RunnableTracker, NotificationManager |
| **Factory** | Object creation in models |
| **Observer** | Qt signals for loose coupling |
| **Strategy** | Pluggable finders (scene, thumbnail, latest file) |
| **Template Method** | Base classes (70-80% code reuse) |
| **Facade** | Simplified public APIs on managers |
| **Lazy Init** | Process pools, thumbnails |

## Complexity Hotspots

The 3 most complex components to be careful with:

1. **MainWindow** (`main_window.py`) — Central orchestrator depending on 15+ components. Changes can cascade.
2. **CacheManager** (`cache_manager.py`) — 4 cache types with different TTL, single QMutex for thread safety, incremental merge logic for scenes.
3. **ProcessPoolManager** (`process_pool_manager.py`) — Singleton with double-checked locking, session pooling, round-robin balancing, command caching.

## Cache Architecture

```
Memory: _pixmap_cache (thumbnails), _stat_cache (file stats, 60s TTL)
Disk:   shots.json (30min TTL), previous_shots.json (persistent),
        threede_scenes.json (persistent + incremental merge), thumbnails/ (persistent JPGs)
```

## Extensibility Points

1. **New Tab/Data Source** — Implement Model, ItemModel, GridView; register in MainWindow
2. **Custom Launchers** — Add to config or implement custom finder
3. **New Cache Type** — Add to CacheManager; define TTL + merge strategy
4. **New Controller** — Create controller class; register signals in MainWindow
