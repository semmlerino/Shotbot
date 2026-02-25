# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Shotbot is a PySide6-based GUI application for **a single Matchmove artist at BlueBolt**. It provides shot browsing, DCC launching, and workflow automation tailored to the matchmove pipeline.

### Matchmove Workflow Context

The tool supports this specific pipeline:

```
3DEqualizer (tracking) → Maya (finalize/playblast) → Nuke (review) → Nuke (publish)
```

1. **3DEqualizer**: Camera tracking and point cloud generation
2. **Maya**: Import tracked camera, finalize scene, create playblasts
3. **Nuke**: Review playblasts, comp checks, final adjustments
4. **Publish**: Export deliverables from Nuke

**Design implications:**
- 3DE is the primary entry point (most used launcher)
- "Other 3DE scenes" tab lets the artist see what colleagues are working on
- Maya/Nuke launchers include options to open latest scenes from the pipeline
- RV is for quick plate review (no scene files, just playback)

## Security Posture

Single-user tool on an isolated VFX server. Do NOT flag security issues (`shell=True`, `eval()`, path traversal, command injection, etc.) — all acceptable trade-offs. Focus reviews on correctness, performance, maintainability, and Qt thread safety.

## Development Environment

- **Dev location**: `~/projects/shotbot` (Linux filesystem, ~7.5x faster than `/mnt/c`)
- **Production**: `/nethome/gabriel-h/Python/Shotbot/` (remote VFX server)
- **Deployment**: Encoded bundle via `encoded-releases` branch — see [docs/DEPLOYMENT_SYSTEM.md](./docs/DEPLOYMENT_SYSTEM.md)
- **Dependencies**: Python 3.11+, PySide6, Pillow, psutil
- **Install**: `~/.local/bin/uv pip install -r requirements.txt`

## Development Commands

```bash
# Run the application
~/.local/bin/uv run python shotbot.py

# Type checking
~/.local/bin/uv run basedpyright

# Linting
~/.local/bin/uv run ruff check .

# Tests (serial — quick local loop)
~/.local/bin/uv run pytest tests/

# Tests (parallel — full regression, recommended before deployment)
~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup
```

**Parallel test notes**: Use `--dist=loadgroup` for whole-suite runs so Qt fixtures share the serialized worker. Individual files generally don't need it. Cap workers with `-n 4` if you need deterministic timing.

## Project Structure

```
shotbot/
├── controllers/       # Application controllers
├── launch/           # Process execution (command building, env management)
├── type_definitions.py # Core type definitions (ShotData, ShotStatus, etc.)
├── tests/            # Test suite
│   ├── advanced/     # Advanced integration tests
│   ├── fixtures/     # Modular test fixtures
│   ├── integration/  # Integration tests
│   ├── performance/  # Performance benchmarks
│   ├── regression/   # Regression tests
│   └── unit/         # Unit tests
├── docs/             # Documentation
├── .git/hooks/       # Git hooks for auto-push
├── shotbot.py        # Main entry point
├── main_window.py    # Main application window
├── command_launcher.py # Production app launcher
├── cache_manager.py  # Persistent caching system
├── singleton_mixin.py # Thread-safe singleton base class
├── bundle_app.py     # Bundle encoding script
├── decode_app.py     # Bundle decoding script
├── transfer_config.json  # Bundle configuration
└── encoded_releases/ # Local copy of encoded bundles
```

## Threading Architecture

See [docs/THREADING_ARCHITECTURE.md](./docs/THREADING_ARCHITECTURE.md) for details.

Key components:
- **QThread workers**: `ThreadSafeWorker`, `ThreeDESceneWorker` for background tasks
- **ThreadPoolExecutor**: `ProcessPoolManager` for shell commands, filesystem scanning
- **Synchronization**: QMutex, threading.Lock, QWaitCondition for thread safety

## Type Safety

The project uses basedpyright with strict settings. Configuration in `pyproject.toml`.

Current status: **0 errors, 0 warnings, 0 notes**

## Singleton Pattern & Test Isolation

Two singleton patterns exist:

- **SingletonMixin** (preferred): Inherit, implement `_initialize()`, optionally override `_cleanup_instance()`. Used by `FilesystemCoordinator`, `QRunnableTracker`.
- **Legacy custom pattern**: `ProcessPoolManager`, `NotificationManager`, `ProgressManager` — each has a compatible `reset()` method.

All singletons support `ClassName.reset()` for test isolation (parallel execution, preventing state contamination). Centralized in `tests/fixtures/singleton_registry.py`.

**New singletons**: Inherit `SingletonMixin`, implement `_initialize()`, register in `singleton_registry.py`.

Additional registered singletons include `DesignSystem`, `TimeoutConfig`, and `ThreadSafeWorker`.

## Qt Widget Guidelines

**Parent parameter rule**: ALL QWidget subclasses MUST accept `parent: QWidget | None = None` and pass it to `super().__init__(parent)`. Missing parent causes Qt C++ crashes (`Fatal Python error: Aborted`).

```python
# ✅ CORRECT
def __init__(self, cache_manager: CacheManager | None = None, parent: QWidget | None = None) -> None:
    super().__init__(parent)
```

**Qt state cleanup**: Use `process_qt_events()` from `tests.test_helpers` instead of `qtbot.wait(1)`.

## Testing

**See [UNIFIED_TESTING_V2.md](./UNIFIED_TESTING_V2.md) for comprehensive testing guidance** (Qt hygiene rules, isolation patterns, debugging workflows).

```bash
# Full regression (Qt-safe parallel)
~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup

# Serial (quick local loop)
~/.local/bin/uv run pytest tests/

# Single test / subset
~/.local/bin/uv run pytest tests/unit/test_shot_model.py -v
~/.local/bin/uv run pytest tests/ -k "test_cache" -v
```

- **2,500+ tests passing** with parallel execution
- Coverage: overall % is low due to excluded VFX/GUI code; core business logic is 70-90%+
- Session-scoped Qt fixtures (`qapp`, `_patch_qtbot_short_waits`) live in `tests/conftest.py`

## Caching System

See [docs/CACHING_ARCHITECTURE.md](./docs/CACHING_ARCHITECTURE.md) for cache strategies, TTLs, and the incremental merge workflow.

## Launcher System & VFX Environment

See [docs/LAUNCHER_AND_VFX_ENVIRONMENT.md](./docs/LAUNCHER_AND_VFX_ENVIRONMENT.md) for CommandLauncher, shell initialization chain, `ws` command, Rez modes, and debugging.
