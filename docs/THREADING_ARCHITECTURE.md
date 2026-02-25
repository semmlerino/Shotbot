# Shotbot Threading Architecture Review

## 1. Concurrency Models

The project employs a multi-layered concurrency architecture, selecting the appropriate model based on the nature of the task (stateful vs. stateless, long-running vs. short-lived).

### A. `QThread` (Stateful, Long-Running Tasks)
-   **Usage:** Application-level background tasks that require state management, lifecycle control (start/stop/pause/resume), and tight integration with the Qt event loop.
-   **Implementation:** `ThreadSafeWorker` (inherits `QThread`) is the base class for all workers.
-   **Key Components:**
    -   `ThreeDEController` (`controllers/threede_controller.py`): Manages the lifecycle of `ThreeDESceneWorker` — creating, stopping, and cleaning up the worker thread, and routing all its signals to handler slots.
    -   `ThreeDESceneWorker`: A concrete `ThreadSafeWorker` subclass that performs 3DE scene discovery in the background.
    -   `AsyncShotLoader` (`shot_model.py`): A concrete `ThreadSafeWorker` subclass that loads shot data from the `ws -sg` command without blocking the UI.
-   **Lifecycle:** Workers follow a strict state machine (`CREATED` -> `STARTING` -> `RUNNING` -> `STOPPING` -> `STOPPED` -> `DELETED`).

### B. `ThreadPoolExecutor` (Stateless, I/O Parallelism)
The project uses `concurrent.futures.ThreadPoolExecutor` in two distinct contexts:

1.  **Global Shell Command Execution:**
    -   **Manager:** `ProcessPoolManager` (Singleton).
    -   **Purpose:** Runs blocking `subprocess.run` calls for external commands (e.g., `execute_workspace_command`).
    -   **Configuration:** Default `max_workers=4`.
    -   **Optimization:** Includes `CommandCache` to deduplicate expensive shell calls.

2.  **Local Filesystem Scanning:**
    -   **Manager:** `SceneDiscoveryCoordinator` (via `find_all_scenes_in_shows_truly_efficient_parallel`).
    -   **Purpose:** Scans multiple show directories in parallel during scene discovery.
    -   **Configuration:** Local instance with `max_workers=min(len(shows), 3)`.
    -   **Constraint:** Intentionally limited to 3 workers to prevent network filesystem saturation.

### C. Hybrid Model
-   **Pattern:** `ThreeDESceneWorker` (`QThread`) orchestrates the discovery process but delegates the heavy lifting to `SceneDiscoveryCoordinator`, which spawns its own `ThreadPoolExecutor`.
-   **Bridge:** `QtProgressReporter` bridges the gap between the thread pool and the `QThread`, using `Qt.QueuedConnection` to safely funnel progress events back to the worker's event loop.

---

## 2. Threading Components Reference

### Core Components

| Component | File | Role |
|-----------|------|------|
| `ThreadSafeWorker` | `thread_safe_worker.py` | Base `QThread` with state machine, `safe_connect()`, zombie protection |
| `ThreeDEController` | `controllers/threede_controller.py` | Lifecycle manager for `ThreeDESceneWorker`; connects and routes all worker signals |
| `ThreeDESceneWorker` | `threede_scene_worker.py` | `QThread` worker for background 3DE scene discovery |
| `AsyncShotLoader` | `shot_model.py` | `QThread` worker for background shot loading via `ws -sg` |
| `SceneDiscoveryCoordinator` | `scene_discovery_coordinator.py` | Orchestrates scene discovery using Template Method pattern; delegates to `FileSystemScanner` via `ThreadPoolExecutor` |
| `ProcessPoolManager` | `process_pool_manager.py` | Singleton `ThreadPoolExecutor` (4 workers) for shell command execution |
| `RefreshOrchestrator` | `refresh_orchestrator.py` | Coordinates refresh operations across tabs; acts as intermediary between `ShotModel` signals and UI updates |

### Supporting Components

| Component | File | Role |
|-----------|------|------|
| `FileSystemScanner` | `filesystem_scanner.py` | Low-level filesystem scan logic used by `SceneDiscoveryCoordinator` |
| `SceneCache` | `scene_cache.py` | In-process cache for discovered scenes, used inside `SceneDiscoveryCoordinator` |
| `QRunnableTracker` | `runnable_tracker.py` | Tracks `QRunnable` instances for proper cleanup |
| `ThreadDiagnostics` | `thread_diagnostics.py` | Captures thread state for debugging zombie abandonment |

---

## 3. Task Dispatch and Management

### Dispatching
-   **QThreads:** Dispatched via `ThreeDEController.refresh_threede_scenes()`. This method handles strict ownership — it checks for an already-running worker, debounces rapid repeat calls (30-second minimum interval), stops any existing worker gracefully before creating a new one, and uses `QMutex` to protect the worker reference.
-   **Shot Loading:** Dispatched via `ShotModel._start_background_refresh()`, which creates an `AsyncShotLoader` and starts it as a background `QThread`.
-   **Shell Commands:** Dispatched via `ProcessPoolManager.get_instance().execute_workspace_command()`.
-   **Filesystem Tasks:** Dispatched internally by `SceneDiscoveryCoordinator` within the context of a parent `QThread`.

### Management & Cleanup
-   **Zombie Protection:** `ThreadSafeWorker` implements a "Zombie Thread" mechanism. If a thread fails to stop gracefully within the timeout defined by `ThreadingConfig`, it is abandoned (not terminated unsafely) and added to a static `_zombie_threads` list to prevent garbage collection crashes. A periodic timer (`_ZOMBIE_CLEANUP_INTERVAL_MS` = 60s) calls `cleanup_old_zombies()` which applies an escalating policy:
    1. Threads that finished naturally are removed immediately.
    2. After `_MAX_ZOMBIE_AGE_SECONDS` (60s), a warning is logged.
    3. After `_ZOMBIE_TERMINATE_AGE_SECONDS` (300s), force-terminate is applied in test mode (`SHOTBOT_TEST_MODE=1`); in production, the zombie is left for process exit to clean up.
-   **Graceful Shutdown:** `ThreeDEController.cleanup_worker()` implements a two-phase shutdown:
    1.  Call `worker.stop()` to set the stop flag.
    2.  Wait up to `Config.WORKER_STOP_TIMEOUT_MS` for the worker to finish; fall back to `safe_terminate()` if it does not.
    3.  Orphaned progress operations are explicitly finished during cleanup to avoid stack corruption.

---

## 4. Synchronization Primitives

### Mutexes
-   **`QMutex`:** Used extensively for thread safety.
    -   `ThreeDEController._worker_mutex`: Protects the `_threede_worker` reference during creation, replacement, and cleanup.
    -   `ThreadSafeWorker._state_mutex`: Protects state transitions, the `_connections` list used by `safe_connect()`, and the stop flag.
    -   `ThreadSafeWorker._zombie_mutex` (class-level): Protects the shared `_zombie_threads` list and zombie timestamps.
    -   `ThreeDESceneWorker._pause_mutex`: Protects pause/resume state.
    -   `ProcessPoolManager._mutex`: Protects the singleton instance state.
-   **`threading.Lock`:** Used in `SceneDiscoveryCoordinator` (`results_lock`) to safely aggregate results from parallel filesystem scans.

### Signals & Slots
-   **`Qt.QueuedConnection`:** The primary mechanism for inter-thread communication. Worker signals are connected to controller slots using `QueuedConnection` so that slots execute in the main thread's event loop, not the worker thread.
-   **`ThreadSafeWorker.safe_connect(signal, slot, connection_type)`:** The canonical way to connect worker signals. It tracks all connections in `_connections` (protected by `_state_mutex`) to deduplicate and enable bulk disconnection via `disconnect_all()` when the thread finishes. Deduplication is handled at the application level because `Qt.UniqueConnection` does not work reliably with Python callables.

### Condition Variables
-   **`QWaitCondition`:** Used in two places:
    -   `ThreadSafeWorker._state_condition`: Wakes threads waiting on state transitions (used by `safe_stop()` and `safe_terminate()`).
    -   `ThreeDESceneWorker._pause_condition`: Implements pause/resume functionality (`_pause_condition.wait()`).

---

## 5. Deadlock & Race Condition Analysis

### Deadlock Prevention
-   **Lock Granularity:** Locks are generally held for short durations (checking state, updating lists).
-   **Signal Emission Outside Locks:** A critical pattern in `ThreadSafeWorker` and `ThreeDEController` is that signals are emitted *after* releasing the mutex. This prevents the classic deadlock scenario where a slot tries to re-acquire the lock held by the emitter.
-   **Shutdown Logic:** `ThreeDEController.cleanup_worker()` captures the worker reference under the mutex, then stops and waits for it *outside* the mutex to avoid blocking the lock during a potentially long wait.
-   **Zombie Cleanup Separation:** `cleanup_old_zombies()` must never be called from within `_zombie_mutex` because `QMutex` is not recursive — calling it from within the mutex section would deadlock.

### Race Condition Safety
-   **Atomic Transitions:** `ThreadSafeWorker` state transitions are atomic under `_state_mutex`.
-   **Singleton Initialization:** `ProcessPoolManager` uses a double-check locking pattern with `threading.Lock` in `__new__` to ensure safe singleton creation.
-   **Zombie Collection:** Access to the static `_zombie_threads` list is protected by `_zombie_mutex`.
-   **`safe_connect()` Deduplication:** The check-and-add in `safe_connect()` is atomic under `_state_mutex` to prevent a TOCTOU race between checking for a duplicate and appending the new connection.

---

## 6. Thread Pool Utilization

### Configuration
-   **ProcessPoolManager:** Defaults to 4 workers. This is suitable for shell commands which are often CPU-light but latency-heavy (waiting on process startup).
-   **Filesystem Scanner:** Hardcoded limit of 3 workers (`min(len(shows), 3)` in `SceneDiscoveryCoordinator`). This is a deliberate design choice to avoid "thundering herd" problems on network shares (e.g., NFS/SMB), where too many concurrent metadata operations can degrade performance for everyone.

### Optimization
-   **Caching:**
    -   `CommandCache`: Caches shell command results (TTL 30s) to avoid unnecessary subprocess spawning.
    -   `SceneCache`: In-process cache for discovered scenes (TTL 30 minutes by default).
    -   `CacheManager.get_persistent_threede_scenes()`: Persistent on-disk cache loaded at startup for instant UI display before background scan completes.
-   **Hybrid Approach:** By combining `QThread` for the UI/Control layer and `ThreadPoolExecutor` for the I/O layer, the application remains responsive while maximizing throughput.

---

## 7. Test Coverage for Threading

### Dedicated Threading Test Files

| Test File | Purpose | Key Scenarios |
|-----------|---------|---------------|
| `tests/unit/test_zombie_thread_lifecycle.py` | Zombie thread mechanism | Creation, recovery, force-termination, metrics |
| `tests/integration/test_shutdown_sequence.py` | Shutdown coordination | Timeout handling, signal safety, singleton ordering |
| `tests/regression/test_concurrent_thumbnail_race_conditions.py` | Cache race conditions | Path corruption, version cache, double-checked locking |
| `tests/regression/test_process_pool_race.py` | Singleton race conditions | Concurrent initialization |
| `tests/regression/test_subprocess_no_deadlock.py` | Pipe buffer deadlock | Large output handling |

### Thread Leak Detection

The test infrastructure includes automatic thread leak detection (see `tests/fixtures/qt_cleanup.py`):

-   **Thread Allowlist**: Known harmless threads (pytest_timeout, QDBusConnection, etc.) are filtered
-   **CI Strict Mode**: Auto-enabled in CI via `SHOTBOT_TEST_FAIL_ON_THREAD_LEAK=1`
-   **Session Summary**: Thread leaks are aggregated and reported at session end
-   **Configurable Timeout**: `SHOTBOT_TEST_THREAD_WAIT_MS` (default 500ms) for slow CI runners

### Running Threading Tests

```bash
# Run all threading-related tests
~/.local/bin/uv run pytest tests/ -k "thread or concurrent or race or zombie" -v

# Run with strict thread leak detection
SHOTBOT_TEST_FAIL_ON_THREAD_LEAK=1 ~/.local/bin/uv run pytest tests/ -v

# Run with extended thread wait (slow CI)
SHOTBOT_TEST_THREAD_WAIT_MS=1000 ~/.local/bin/uv run pytest tests/ -v
```

### Debugging Threading Issues

1. **Enable thread tracking**: `SHOTBOT_TEST_TRACK_POPEN=1` for subprocess call tracking
2. **Enable strict cleanup**: `SHOTBOT_TEST_STRICT_CLEANUP=1` for cleanup exception visibility
3. **Check zombie metrics**: Use `ThreadSafeWorker.get_zombie_metrics()` to monitor zombie thread counts
4. **Session-level summary**: Thread leak summary printed at end of test session with thread names

---

## Recommendations

1.  **Configurable Scanner Limits:** The `max_workers=3` limit in `scene_discovery_coordinator.py` works well for network drives but might be conservative for local SSDs. Consider moving this to `Config`.
2.  **Unified Executor (Consideration):** Currently, there are two separate thread pools (`ProcessPoolManager` and the local one in `SceneDiscoveryCoordinator`). While their purposes differ, high load on both simultaneously could create `4 + 3 = 7` active threads + the `QThread`. This is likely fine, but if more parallel components are added, a centralized `ThreadPoolManager` that vends executors or manages a global pool might be cleaner.
3.  **Monitor Zombie Metrics in Production:** Consider periodically logging `ThreadSafeWorker.get_zombie_metrics()` to detect threads that consistently fail to stop gracefully.

---

## 8. When to Use Which Threading Mechanism

### Decision Tree

```
Need to run background work?
├── Is it a long-lived, cancellable task with lifecycle management?
│   └── YES → Use QThread (via ThreadSafeWorker)
│       Examples: ThreeDESceneWorker, AsyncShotLoader
│       Key features: start/stop/pause, state machine, Qt signal integration
│
├── Is it a short, fire-and-forget task that needs Qt signal emission?
│   └── YES → Use QRunnable with QThreadPool
│       Examples: TrackedQRunnable subclasses
│       Key features: auto-cleanup, lightweight, no lifecycle management
│
├── Is it pure-Python parallel work with NO Qt API calls?
│   └── YES → Use ThreadPoolExecutor (via ProcessPoolManager)
│       Examples: subprocess execution, filesystem scanning
│       Key features: Future-based, command caching, pool management
│
└── Is it a one-off blocking call that needs a result?
    └── YES → Use ProcessPoolManager.execute_command()
        Wraps subprocess.run in ThreadPoolExecutor automatically
```

### Important Constraints

- **Never call Qt API from ThreadPoolExecutor threads** — Qt objects have thread affinity
- **ThreeDEController** manages ONLY the `ThreeDESceneWorker` lifecycle (not a general-purpose threading hub)
- **ProcessPoolManager** has a built-in 30-second CommandCache — call `invalidate_cache()` when data staleness matters
- **QRunnable tasks** should register with `QRunnableTracker` for proper cleanup tracking
- **Always use `safe_connect()`** on `ThreadSafeWorker` subclasses — direct `signal.connect()` calls bypass deduplication and cleanup tracking
