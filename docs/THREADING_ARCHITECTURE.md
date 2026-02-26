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
- `ThreeDEController`: owns `ThreeDESceneWorker` lifecycle.
- `AsyncShotLoader`: background shot loading worker.
- `ProcessPoolManager`: singleton executor for subprocess-heavy operations.
- `SceneDiscoveryCoordinator`: parallel filesystem scanning orchestration.

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

- Use `QThread` when you need lifecycle control (`start/stop/pause`) and Qt signal integration.
- Use `ThreadPoolExecutor` for blocking subprocess and filesystem tasks without Qt object access.
- Use `QRunnable` for short tasks that benefit from pooled execution.

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
