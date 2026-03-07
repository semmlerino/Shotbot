# Shotbot Architecture - Quick Reference

> See `CLAUDE.md` for project overview, commands, and matchmove pipeline context.
> This memory provides architectural patterns and structure for AI context loading.
> Last Updated: March 2026

## Layer Breakdown

### 1. PRESENTATION (Qt UI)
- **MainWindow** — Central orchestrator, signal routing
- **3 Grid Systems** — Independent data pipelines with views/delegates (shots, 3DE scenes, previous shots)
- **Panels & Dialogs** — Info display, launch controls, settings
- **DesignSystem** — Centralized theming (colors, typography, spacing, borders, shadows, animations)
- **ScrubPreview** — Hover-to-scrub thumbnail preview (ScrubEventFilter, ScrubPreviewManager, ScrubFrameCache)
- **AccessibilityManager** — Qt accessibility setup for main window

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

### 4. DATA MANAGEMENT (Persistence)
- **PinManager** — Shot-level pinning (by show/seq/shot key)
- **FilePinManager** — File-level pinning with comments
- **NotesManager** — Shot notes with debounced save
- **CacheManager** — Multi-level caching (memory + disk) with TTL strategies

### 5. SYSTEM INTEGRATION (I/O & Execution)
- **ProcessPoolManager** — Singleton subprocess pool, command caching, round-robin load balancing
- **PlateDiscovery** — Plate file discovery, script directory resolution
- **PlateFrameProvider** — Async EXR frame extraction via QThreadPool
- **NukeMediaDetector** — Frame range, colorspace, resolution detection
- **NukeLaunchRouter** — Routes Nuke launches (simple vs full pipeline)
- **NukeScriptGenerator** — Programmatic .nk script creation
- **RefreshOrchestrator** — Periodic refresh coordination

### 6. LIFECYCLE (Startup & Shutdown)
- **StartupCoordinator** — Orchestrates initial load with paint yields
- **SessionWarmer** — Pre-warms process pool at startup
- **CleanupManager** — Structured shutdown (controllers, models, managers)

### 7. INFRASTRUCTURE (Support)
- **Mixins**: LoggingMixin, ErrorHandlingMixin, QtWidgetMixin, ProgressReportingMixin, VersionHandlingMixin
- **Configuration**: Config, SettingsManager, EnvironmentManager
- **Managers**: NotificationManager, ProgressManager, FilesystemCoordinator
- **Threading**: ThreadSafeWorker, signal/slot coordination, RunnableTracker

## Dependency Hierarchy

```
TIER 1: Entry Point
  shotbot.py → MainWindow

TIER 2: Orchestration
  MainWindow → StartupCoordinator, CleanupManager → (everything below)

TIER 3: Coordination
  Controllers → Managers
  Models → ProcessPoolManager, CacheManager

TIER 4: Core Services
  ProcessPoolManager → ThreadPool
  CacheManager → File I/O, PIL
  PlateFrameProvider → ScrubFrameCache, QThreadPool

TIER 5: Generic Infrastructure
  BaseItemModel[T], BaseShotModel, BaseGridView

TIER 6: Support
  Mixins, Configuration, Utilities, DesignSystem
```

## Key Design Patterns

| Pattern | Usage |
|---------|-------|
| **MVC** | Core architecture |
| **Singleton** | ProcessPoolManager, FilesystemCoordinator, RunnableTracker, NotificationManager, DesignSystem |
| **Factory** | Object creation in models |
| **Observer** | Qt signals for loose coupling |
| **Strategy** | Pluggable finders (scene, thumbnail, latest file) |
| **Template Method** | Base classes (70-80% code reuse) |
| **Facade** | Simplified public APIs on managers |
| **Lazy Init** | Process pools, thumbnails |
| **Event Filter** | ScrubEventFilter on grid views for hover-to-scrub |
| **Debounce** | NotesManager save scheduling |

## Complexity Hotspots

1. **MainWindow** (`main_window.py`) — Central orchestrator depending on 15+ components. Changes can cascade.
2. **CacheManager** (`cache_manager.py`) — 4 cache types with different TTL, single QMutex for thread safety, incremental merge logic for scenes.
3. **ProcessPoolManager** (`process_pool_manager.py`) — Singleton with double-checked locking, session pooling, round-robin balancing, command caching.
4. **ScrubPreviewManager** — Coordinates between event filter, frame provider, frame cache, and grid delegate rendering.

## Cache Architecture

```
Memory: _pixmap_cache (thumbnails), _stat_cache (file stats, 60s TTL), ScrubFrameCache (LRU per-shot)
Disk:   shots.json (30min TTL), previous_shots.json (persistent),
        threede_scenes.json (persistent + incremental merge), thumbnails/ (persistent JPGs),
        pinned_shots.json, pinned_files.json, shot_notes.json
```

## Extensibility Points

1. **New Tab/Data Source** — Implement Model, ItemModel, GridView; register in MainWindow
2. **Custom Launchers** — Add to config or implement custom finder
3. **New Cache Type** — Add to CacheManager; define TTL + merge strategy
4. **New Controller** — Create controller class; register signals in MainWindow
