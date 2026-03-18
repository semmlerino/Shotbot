# Shotbot Threading Architecture

This document captures threading design intent and safety guardrails.
It does not mirror implementation details line-by-line.

## Concurrency Model

Shotbot uses three mechanisms:

1. `QThread` (`ThreadSafeWorker` subclasses) for long-lived, cancellable background work.
2. `ThreadPoolExecutor` (`ProcessPoolManager` and local scanning pools) for pure-Python I/O parallelism.
3. `QRunnable` for lightweight fire-and-forget Qt-adjacent tasks.

## Core Components

- `ThreadSafeWorker`: lifecycle/state machine, safe signal connection helpers, stop/terminate safety.
  - Subclasses: `AsyncShotLoader`, `ThreeDESceneWorker`, `LatestFileFinderWorker`, `PreviousShotsWorker`, `StartupCoordinator`.
- `ThreeDEWorkerManager`: owns `ThreeDESceneWorker` lifecycle (created by `ThreeDEController`).
- `ProcessPoolManager`: singleton executor for subprocess-heavy operations.
- `SceneDiscoveryCoordinator`: parallel filesystem scanning orchestration.
- `ThreadDiagnostics`: thread state capture, stack trace logging, and abandonment reporting used by `ThreadSafeWorker.safe_terminate()`.

## Invariants

1. UI thread owns Qt widgets; worker threads do not mutate UI directly.
2. Cross-thread communication uses signals/slots (queued where required).
3. Worker shutdown must be explicit and bounded by timeout paths.
4. Signal wiring for worker objects should use worker-safe connection utilities.
5. Executor-backed tasks must avoid Qt API access.

## Deadlock and Race Guardrails

- Do not hold mutexes while emitting signals.
- Do not wait on worker shutdown while holding ownership locks.
- Protect singleton initialization and worker-reference swaps with locks/mutexes.
- Keep lock scope minimal around state transitions and connection tracking.

## Choosing a Mechanism

| Mechanism | When to Use | Codebase Examples |
|-----------|-------------|-------------------|
| `QThread` via `ThreadSafeWorker` | Long-lived, cancellable work needing Qt signal integration and lifecycle control (start/stop/pause) | `AsyncShotLoader` (shot data refresh), `ThreeDESceneWorker` (scene discovery), `LatestFileFinderWorker` (file search), `PreviousShotsWorker` (approved shot scan), `StartupCoordinator` (startup preloading) |
| `ThreadPoolExecutor` via `ProcessPoolManager` | Subprocess execution and filesystem I/O parallelism; no Qt object access allowed | `ws -sg` command execution, parallel show scanning in `SceneDiscoveryCoordinator`, process verification |
| `QRunnable` via `TrackedQRunnable` | Short, fire-and-forget Qt-adjacent tasks dispatched to `QThreadPool.globalInstance()` | `_ThumbnailLoaderRunnable` (background image loading), `ThumbnailCacheLoader` (cache warming), `FrameExtractionRunnable` (scrub frame loading), and others (see `TrackedQRunnable` subclasses) |

**Decision checklist:**
1. Does the task need to be cancelled mid-execution? → `QThread` (`ThreadSafeWorker`)
2. Does the task need to emit Qt signals during execution? → `QThread` (`ThreadSafeWorker`)
3. Is it a subprocess call or pure I/O with no Qt dependency? → `ThreadPoolExecutor`
4. Is it a short task (< 1 second) with no cancellation need? → `QRunnable`
5. Does it need to run multiple parallel instances? → `ThreadPoolExecutor` (pool) or `QRunnable` (thread pool)

## QRunnable Tracking

`TrackedQRunnable` (`runnable_tracker.py`) is the base class for QRunnable tasks dispatched to `QThreadPool.globalInstance()`. The companion `QRunnableTracker` singleton tracks active runnables, enabling graceful shutdown and leak detection in tests.

## Testing Expectations

Run targeted threading checks when changing worker lifecycle, locking, or cross-thread routing:

```bash
uv run pytest tests/unit/test_zombie_thread_lifecycle.py -v
uv run pytest tests/integration/test_shutdown_sequence.py -v
uv run pytest tests/regression/test_process_pool_race.py -v
uv run pytest tests/regression/test_subprocess_no_deadlock.py -v
```

For broader confidence:

```bash
uv run pytest tests/ -k "thread or concurrent or race or zombie" -v
```

## Operational Notes

- Thread leak diagnostics and strict cleanup behavior are governed by test fixtures under `tests/fixtures/`.
- If you change lifecycle/shutdown behavior, update both integration tests and fixture cleanup assumptions.
