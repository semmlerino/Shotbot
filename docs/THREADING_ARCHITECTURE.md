# Shotbot Threading Architecture Review

## 1. Concurrency Models

The project employs a multi-layered concurrency architecture, selecting the appropriate model based on the nature of the task (stateful vs. stateless, long-running vs. short-lived).

### A. `QThread` (Stateful, Long-Running Tasks)
-   **Usage:** Application-level background tasks that require state management, lifecycle control (start/stop/pause/resume), and tight integration with the Qt event loop.
-   **Implementation:** `ThreadSafeWorker` (inherits `QThread`) is the base class for all workers.
-   **Key Components:**
    -   `ThreadingManager`: Orchestrates worker creation, lifecycle, and cleanup.
    -   `ThreeDESceneWorker`: A concrete implementation for scene discovery.
-   **Lifecycle:** Workers follow a strict state machine (`CREATED` -> `STARTING` -> `RUNNING` -> `STOPPING` -> `STOPPED` -> `DELETED`).

### B. `ThreadPoolExecutor` (Stateless, I/O Parallelism)
The project uses `concurrent.futures.ThreadPoolExecutor` in two distinct contexts:

1.  **Global Shell Command Execution:**
    -   **Manager:** `ProcessPoolManager` (Singleton).
    -   **Purpose:** Runs blocking `subprocess.run` calls for external commands (e.g., `execute_workspace_command`).
    -   **Configuration:** Default `max_workers=4`.
    -   **Optimization:** Includes `CommandCache` to deduplicate expensive shell calls.

2.  **Local Filesystem Scanning:**
    -   **Manager:** `ThreeDESceneFinder` (via `SceneDiscoveryCoordinator`).
    -   **Purpose:** Scans multiple show directories in parallel during scene discovery.
    -   **Configuration:** Local instance with `max_workers=min(len(shows), 3)`.
    -   **Constraint:** Intentionally limited to 3 workers to prevent network filesystem saturation.

### C. Hybrid Model
-   **Pattern:** `ThreeDESceneWorker` (`QThread`) orchestrates the discovery process but delegates the heavy lifting to `ThreeDESceneFinder`, which spawns its own `ThreadPoolExecutor`.
-   **Bridge:** `QtProgressReporter` bridges the gap between the thread pool and the `QThread`, using `Qt.QueuedConnection` to safely funnel progress events back to the worker's event loop.

---

## 2. Task Dispatch and Management

### Dispatching
-   **QThreads:** Dispatched via `ThreadingManager.start_threede_discovery()`. This method handles strict ownership, ensuring only one discovery thread runs at a time and cleaning up previous instances.
-   **Shell Commands:** Dispatched via `ProcessPoolManager.get_instance().execute_workspace_command()`.
-   **Filesystem Tasks:** Dispatched internally by `ThreeDESceneFinder` within the context of a parent `QThread`.

### Management & Cleanup
-   **Zombie Protection:** `ThreadSafeWorker` implements a "Zombie Thread" mechanism. If a thread fails to stop gracefully within a timeout (300s), it is abandoned (not terminated unsafe-ly) and added to a static `_zombie_threads` list to prevent garbage collection crashes. A periodic timer cleans up finished zombies.
-   **Graceful Shutdown:** `ThreadingManager` implements a two-phase shutdown:
    1.  Acquire lock, flag all workers to stop.
    2.  Release lock, wait for workers to finish (preventing UI freezes).

---

## 3. Synchronization Primitives

### Mutexes
-   **`QMutex`:** Used extensively for thread safety.
    -   `ThreadingManager._mutex`: Protects worker registry and state flags.
    -   `ThreadSafeWorker._state_mutex`: Protects state transitions and signal connection lists.
    -   `ThreeDESceneWorker._pause_mutex`: Protects pause/resume state.
    -   `ProcessPoolManager._mutex`: Protects the singleton instance state.
-   **`threading.Lock`:** Used in `ThreeDESceneFinder` (`results_lock`) to safely aggregate results from parallel filesystem scans.

### Signals & Slots
-   **`Qt.QueuedConnection`:** The primary mechanism for inter-thread communication.
    -   Used by `SignalManager.connect_safely`.
    -   Explicitly used by `QtProgressReporter` to safely emit signals from thread pool threads.
-   **`SignalManager`:** A utility class that wraps connection logic, ensuring all connections are tracked and can be cleanly disconnected to prevent memory leaks and "signal spam" after object destruction.

### Condition Variables
-   **`QWaitCondition`:** Used in `ThreeDESceneWorker` to implement pause/resume functionality (`_pause_condition.wait()`).

---

## 4. Deadlock & Race Condition Analysis

### Deadlock Prevention
-   **Lock Granularity:** Locks are generally held for short durations (checking state, updating lists).
-   **Signal Emission Outside Locks:** A critical pattern observed in `ThreadSafeWorker` and `ThreadingManager` is that signals are emitted *after* releasing the mutex. This prevents the classic deadlock scenario where a slot tries to re-acquire the lock held by the emitter.
-   **Shutdown Logic:** `ThreadingManager.shutdown_all_threads` releases the main lock before blocking on `worker.wait()`.

### Race Condition Safety
-   **Atomic Transitions:** `ThreadSafeWorker` state transitions are atomic under `_state_mutex`.
-   **Singleton Initialization:** `ProcessPoolManager` uses a double-check locking pattern with `threading.Lock` in `__new__` to ensure safe singleton creation.
-   **Zombie Collection:** Access to the static `_zombie_threads` list is protected by `_zombie_mutex`. Note: The code specifically avoids calling the cleanup method from within the mutex to avoid recursion deadlocks.

---

## 5. Thread Pool Utilization

### Configuration
-   **ProcessPoolManager:** Defaults to 4 workers. This is suitable for shell commands which are often CPU-light but latency-heavy (waiting on process startup).
-   **Filesystem Scanner:** Hardcoded limit of 3 workers. This is a deliberate design choice to avoid "thundering herd" problems on network shares (e.g., NFS/SMB), where too many concurrent metadata operations can degrade performance for everyone.

### Optimization
-   **Caching:**
    -   `CommandCache`: Caches shell command results (TTL 30s) to avoid unnecessary subprocess spawning.
    -   `DirectoryCache`: Caches directory listings (TTL 300s) to reduce filesystem hits.
-   **Hybrid Approach:** By combining `QThread` for the UI/Control layer and `ThreadPoolExecutor` for the I/O layer, the application remains responsive while maximizing throughput.

---

## 6. Test Coverage for Threading

### Dedicated Threading Test Files

| Test File | Purpose | Key Scenarios |
|-----------|---------|---------------|
| `tests/unit/test_zombie_thread_lifecycle.py` | Zombie thread mechanism | Creation, recovery, force-termination, metrics |
| `tests/unit/test_cancellation_robustness.py` | CancellationEvent edge cases | Exception isolation, concurrent cancel, idempotent behavior |
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
2.  **Unified Executor (Consideration):** Currently, there are two separate thread pools (`ProcessPoolManager` and the local one in `ThreeDESceneFinder`). While their purposes differ, high load on both simultaneously could create `4 + 3 = 7` active threads + the `QThread`. This is likely fine, but if more parallel components are added, a centralized `ThreadPoolManager` that vends executors or manages a global pool might be cleaner.
3.  **Monitor Zombie Metrics in Production:** Consider periodically logging `ThreadSafeWorker.get_zombie_metrics()` to detect threads that consistently fail to stop gracefully.

---

## 7. When to Use Which Threading Mechanism

### Decision Tree

```
Need to run background work?
├── Is it a long-lived, cancellable task with lifecycle management?
│   └── YES → Use QThread (via ThreadSafeWorker)
│       Examples: ThreeDESceneWorker, shot refresh workers
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
- **ThreadingManager** manages ONLY the ThreeDESceneWorker lifecycle (not a general-purpose threading hub)
- **ProcessPoolManager** has a built-in 30-second CommandCache — call `invalidate_cache()` when data staleness matters
- **QRunnable tasks** should register with QRunnableTracker for proper cleanup tracking
