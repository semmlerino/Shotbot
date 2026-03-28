# Original Request

Review this codebase and generate a set of high-quality prompts that could be used with an LLM to improve, extend, or analyze it.

Focus on prompts for:
- debugging and bug detection
- refactoring and simplification
- performance optimization
- feature expansion
- testing and validation

For each prompt:
- make it specific to this codebase (not generic)
- include enough context so it can be used directly
- state the expected output clearly

Return them grouped by purpose.

---

# Generated Prompts

Here is a set of high-quality, targeted prompts designed to be used with an LLM to work on the **ShotBot** codebase. They are grouped by purpose and include necessary context and expected outputs.

### 🐛 Debugging and Bug Detection

**Prompt 1: Fixing Qt Thread-Safety and Zombie Workers**
> **Context:** The ShotBot codebase heavily relies on a custom `ThreadSafeWorker` and `TrackedQRunnable` for background processing (e.g., `threede_scene_worker.py`, `ThumbnailLoader`). We have a recurring issue where UI models do not receive the `finished` signal when a worker thread is abruptly interrupted via `requestInterruption()`, leading to zombie threads and blocked UI states.
> **Task:** Review `workers/thread_safe_worker.py` and `threede_scene_worker.py`. Identify why the `QMutex`-protected `_finished_emitted` flag is failing to trigger the final signal emission during a thread interruption or application shutdown. 
> **Expected Output:** 
> 1. A root-cause analysis of the thread lifecycle issue.
> 2. The corrected code snippet for the `run()` and `stop()` methods utilizing `QMutexLocker` safely without causing deadlocks with the main Qt thread.

**Prompt 2: Debugging Thumbnail Batching Deadlocks**
> **Context:** In `cache/thumbnail_loader.py`, we use `_emit_batched_updates` to prevent UI thread blocking when loading hundreds of thumbnails simultaneously. However, occasionally the main `MainWindow` UI freezes when `ThumbnailLoader` attempts to flush its batched updates to the proxy models.
> **Task:** Analyze the signal emission pattern between `_ThumbnailLoaderRunnable`, `_ThumbnailLoaderSignals`, and the main thread slots. Determine if we are accidentally synchronously waiting on a `QMutex` inside a slot connected via `Qt.BlockingQueuedConnection` or `Qt.DirectConnection`.
> **Expected Output:** A step-by-step trace of the deadlock and a refactored `_emit_batched_updates` implementation using `QTimer.singleShot` or `Qt.QueuedConnection` to ensure strictly asynchronous execution.

---

### ♻️ Refactoring and Simplification

**Prompt 3: Decoupling the App Services Factory**
> **Context:** Currently, `app_services.py` contains monolithic factory functions like `build_infrastructure()` and `build_models()` that manually wire up the `ProcessPoolManager`, `ShotDataCache`, `ThumbnailCache`, and various controllers. As ShotBot grows, this file is becoming a bottleneck and violates the Open/Closed Principle.
> **Task:** Refactor `app_services.py` to implement a lightweight Dependency Injection (DI) container or a more modular Provider pattern. The solution must remain purely Pythonic (no external heavy frameworks) and preserve the existing singleton lifecycle of the cache and worker managers.
> **Expected Output:** The refactored `app_services.py` file code, accompanied by a brief explanation of how new controllers or services should be registered in the new architecture.

**Prompt 4: Unifying the Caching Subsystem**
> **Context:** ShotBot implements multiple specialized caches: `ShotDataCache` (metadata), `ThumbnailCache` (images), and `SceneDiskCache` (discovery results). They all duplicate similar mechanisms for max-size bounding, expiration, and disk-syncing via `_json_store.py`.
> **Task:** Design a unified base class `AbstractCacheManager` (using Python's `abc`) that encapsulates the disk-syncing, cache invalidation, and maximum capacity logic. Then, rewrite `ThumbnailCache` to inherit from this new base class.
> **Expected Output:** 
> 1. The code for the new `AbstractCacheManager`.
> 2. The updated `cache/thumbnail_cache.py` demonstrating the simplification.

---

### ⚡ Performance Optimization

**Prompt 5: Optimizing File Discovery Heuristics**
> **Context:** The pipeline discovery system (`discovery/thumbnail_finders.py` and `maya_latest_finder.py`) currently performs sequential `Path.exists()` and `Path.glob()` checks across multiple network drives to find DCC scenes and plates. This is creating a massive bottleneck when initializing the `ThreeDESceneModel`.
> **Task:** Optimize the file discovery logic by implementing asynchronous path checking using `asyncio` combined with `os.scandir()` (which is significantly faster than `glob` for checking file attributes). Integrate this so it plays nicely with our `ThreadSafeWorker` execution layer.
> **Expected Output:** An optimized version of the finder methods, utilizing `os.scandir` and a thread-pool or asyncio event loop, showing benchmarking metrics (Big-O or estimated IO wait reduction) in the code comments.

---

### 🚀 Feature Expansion

**Prompt 6: Adding Houdini Support to Command Launcher**
> **Context:** ShotBot currently integrates with Maya, Nuke, and 3DEquality via `launch/command_launcher.py` and specialized AppHandlers. We need to add support for SideFX Houdini.
> **Task:** Create a new `HoudiniAppHandler` in the `launch/` (or `dcc/`) directory. It needs to:
> 1. Inherit from the base application handler protocol.
> 2. Implement the environment bootstrapping (similar to the existing Rez integration logic).
> 3. Construct the specific CLI arguments to launch `houdini` or `hython` within the context of a given `Shot` object.
> **Expected Output:** The complete Python class for the `HoudiniAppHandler` and the necessary modification snippet for `command_launcher.py` to register the new DCC.

**Prompt 7: Implementing a "Favorites" Tab UI**
> **Context:** Users want a way to pin specific shots. We have `main_window.py` managing tabs (My Shots, 3DE Scenes) and `shots/shot_model.py` containing all shot data.
> **Task:** Extend the UI to include a "Favorite Shots" tab. You must:
> 1. Add a boolean `is_favorite` property to the `Shot` data class in `type_definitions.py`.
> 2. Create a new `QSortFilterProxyModel` in `controllers/` that filters the central `ShotModel` to only show favorites.
> 3. Update `main_window.py` to instantiate this tab and connect the proxy model.
> **Expected Output:** The modified code for `type_definitions.py`, the new proxy model class, and the specific UI generation code for `main_window.py`.

---

### 🧪 Testing and Validation

**Prompt 8: Ensuring Parallel Test Safety for Singletons**
> **Context:** We run tests using `pytest-xdist` for parallel execution. However, some tests in `tests/` occasionally fail due to state leakage from singletons like `ProcessPoolManager` or unclosed Qt threads from `AsyncShotLoader`.
> **Task:** Write a robust Pytest fixture in `tests/conftest.py` that guarantees the strict reset of the `ProcessPoolManager` singleton and forcefully joins or terminates any active `TrackedQRunnable` instances after every single test.
> **Expected Output:** The Pytest fixture code utilizing `yield` for teardown, including offscreen UI safe assertions to verify no threads are leaked, preventing `QThread: Destroyed while thread is still running` errors.

**Prompt 9: Mocking the ThumbnailLoader for Model Tests**
> **Context:** When testing the `ShotModel` sorting and filtering logic, the tests are inadvertently triggering the `ThumbnailLoader` to touch the disk and spawn threads, slowing down the test suite significantly.
> **Task:** Create a test utilizing `unittest.mock.patch` that injects a dummy `ThumbnailLoader` into the `ShotModel` during initialization. The test should verify that the proxy model correctly sorts shots by frame range without ever initiating a real `QRunnable`.
> **Expected Output:** A fully functional `pytest` function demonstrating the mock injection, the sorting execution, and the assertions to validate the mocked loader was never called for disk I/O.