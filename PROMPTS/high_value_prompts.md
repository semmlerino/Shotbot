# High-Value Prompts for ShotBot

## Original Request

> Propose a set of high-value prompts tailored to this codebase.
> 
> Go beyond basic maintenance tasks — include prompts for:
> - improving architecture and design decisions
> - uncovering hidden bugs or edge cases
> - enhancing developer experience and workflows
> - exploring performance optimizations
> - enabling new or unexpected features
> - stress-testing assumptions in the current implementation
> 
> Prioritize prompts that would lead to meaningful insights, not trivial checks.
> 
> For each prompt:
> - explain why it’s valuable
> - describe what kind of output or impact it should produce
> 
> Aim for prompts that are practical, but also creative and thought-provoking.

## Proposed Prompts

Here is a set of high-value, tailored prompts designed to push the boundaries of the **Shotbot** codebase. I've designed these to leverage the Gemini CLI's context-awareness, focusing on the specific architectural patterns (PySide6, DCC launching, network caching) and historical pain points (threading, test isolation) present in your workspace.

You can paste these directly into the CLI.

---

### 1. Improving Architecture and Design Decisions
**The Prompt:**
> "Analyze the state management and cross-thread communication between `ThreeDEController`, `CacheCoordinator`, and the UI components in `main_window.py`. Are there any PySide6 signal/slot anti-patterns present? Specifically, look for implicit blocking calls, unsafe cross-thread UI mutations, or instances where background workers (like `ThreeDEWorkerManager` or `LatestFileFinderWorker`) might leak memory if the UI is abruptly closed."

* **Why it’s valuable:** The presence of `dev-tools/apply_threading_fixes.py` indicates that Qt threading has been a historical pain point. Mixing disk-bound cache operations with PySide6 UI events is a common source of micro-stutters and crashes.
* **Expected Impact:** A detailed architectural review highlighting potential deadlocks, memory leaks, and a refactoring plan to ensure a strictly unidirectional, thread-safe data flow using Qt's queued connections.

### 2. Uncovering Hidden Bugs or Edge Cases
**The Prompt:**
> "Investigate the implementation of `cache/_json_store.py`, `LatestFileCache`, and `FilesystemCoordinator._directory_cache`. How does the system behave if the underlying VFX network share (`ws`) experiences severe latency, drops mid-read, or if POSIX file locking (`SHOTBOT_FILE_LOCKING`) silently fails over the network? Specifically, trace the 'not_found' tri-state logic: what happens if a network timeout causes a false 'not_found' to be cached for 5 minutes?"

* **Why it’s valuable:** VFX network drives (Isilon, Qumulo) are notoriously flaky under heavy farm load. If Shotbot caches a "file not found" due to a 5-second network drop, it could block an artist from opening their Nuke script for the duration of the TTL.
* **Expected Impact:** Identification of race conditions and false-negative caching states, leading to recommendations for more resilient network-agnostic caching (e.g., stale-while-revalidate patterns or safer lock-free writing).

### 3. Enhancing Developer Experience and Workflows
**The Prompt:**
> "Review the current test setup in `pyproject.toml`, the `tests/` directory, and the isolated execution policy (`pytest -n auto`). The README states parallel execution is just a 'secondary isolation check for shared-state'. Create a comprehensive plan to modernize the test fixtures to completely eliminate shared-state leakage (especially around `QSettings` and singletons). How can we make parallel tests the default, reliable CI gate rather than just a secondary check?"

* **Why it’s valuable:** If parallel tests are flaky or only used to catch leaks, it means the test suite's teardown logic is untrustworthy. Fixing this makes CI significantly faster and local development less frustrating.
* **Expected Impact:** A concrete refactoring strategy for `conftest.py` and mock environments (like `mock_workspace_pool.py`), ensuring perfect isolation and faster feedback loops for developers.

### 4. Exploring Performance Optimizations
**The Prompt:**
> "Analyze the thumbnail discovery and loading pipeline spanning `discovery/thumbnail_finders.py`, `cache/thumbnail_loader.py`, and `controllers/thumbnail_size_manager.py`. Given the existence of `thumbnail_bottleneck_profiler.py`, propose an architectural shift to handle browsing a show with 2,000+ shots simultaneously. Should we move to a background thread pool, implement memory-mapped files, use PySide6's `QImageReader` optimizations, or implement aggressive UI virtualization/culling?"

* **Why it’s valuable:** Loading hundreds of JPEGs/EXRs over a network share will choke the main Qt thread if not handled perfectly. Artists judge tools by their UI responsiveness.
* **Expected Impact:** A high-level blueprint and proof-of-concept for implementing zero-blocking image loading and rendering, ensuring a buttery-smooth scrolling experience regardless of shot count.

### 5. Enabling New or Unexpected Features
**The Prompt:**
> "Explore the feasibility of adding 'Predictive Pre-fetching' to Shotbot. Based on the `discovery/` module and the caching architecture, how could we design a background heuristic that preemptively caches plates, thumbnails, or DCC paths for shots the artist is *likely* to click next (e.g., adjacent shots in a sequence), rather than waiting for explicit UI selection?"

* **Why it’s valuable:** Artists often work sequentially through a sequence. If Shotbot pre-warms the cache for `sh020` while the artist is looking at `sh010`, DCC launching becomes virtually instantaneous.
* **Expected Impact:** A speculative design document detailing how to add an AI-lite or heuristic-based predictive background worker without thrashing the studio's network or the user's disk I/O.

### 6. Stress-Testing Assumptions in the Current Implementation
**The Prompt:**
> "Stress-test the assumption that Shotbot can seamlessly handle environment handoffs to DCCs (`commands/maya_commands.py`, `commands/nuke_commands.py`). Walk through the exact execution chain from clicking 'Launch Nuke' to the moment the SGTK bootstrap takes over. What happens if the `REZ_MODE` environment is partially corrupted, or if `SHOTBOT_SCRIPTS_DIR` is inaccessible during the subprocess spawn? Does Shotbot swallow the error, leave a zombie process, or surface a highly visible Qt error dialog to the user?"

* **Why it’s valuable:** Process spawning in VFX pipelines is incredibly brittle. A silent failure when launching Maya leads to artist confusion and IT support tickets. 
* **Expected Impact:** Exposing blind spots in the subprocess management and error-handling code (`exceptions.py`), leading to better user-facing diagnostics and cleaner zombie-process prevention.