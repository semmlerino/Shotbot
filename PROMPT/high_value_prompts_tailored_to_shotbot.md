# High-Value Prompts Tailored To Shotbot

These are tailored to the fault lines that show up in this repo: startup/cache orchestration, launcher state machines, Qt threading, thumbnail/scrub pipelines, persistent cache semantics, and the boundary between mock mode and the real VFX environment in `controllers/startup_orchestrator.py`, `launch/command_launcher.py`, `workers/thread_safe_worker.py`, `scrub/scrub_preview_manager.py`, `cache/coordinator.py`, and `tests/integration/test_cache_architecture_seams.py`.

## Prompt Set

1. `Map the full startup path from process launch to first interactive frame. Identify where cache restoration, background refresh, session warming, and UI painting are coupled too tightly. Propose a simpler startup state machine with explicit phases, ownership, and failure handling.`
Why it’s valuable: Startup is already doing several things at once, and this repo clearly cares about perceived responsiveness and background work ordering.
Expected output or impact: A concrete phase diagram, a list of hidden couplings, and a refactor plan that reduces “works most of the time” startup behavior into explicit states and invariants.

2. `Audit every place where Shotbot returns cached data immediately and refreshes later. Find cases where the UI can temporarily show stale, contradictory, or partially migrated truth across shots, previous shots, 3DE scenes, latest files, and thumbnails.`
Why it’s valuable: The cache architecture is layered and intentionally mixes TTL caches, persistent caches, and incremental accumulation, which is fertile ground for subtle correctness bugs.
Expected output or impact: A cross-cache consistency matrix, concrete stale-data scenarios, and a shortlist of fixes such as versioned cache keys, freshness markers, or atomic refresh boundaries.

3. `Review the launch flow as a state machine rather than a set of methods. Starting at CommandLauncher, enumerate every launch phase, async branch, cancellation path, and timeout path for nuke, 3de, maya, rv, and file-opening launches. Find states that can leak, double-complete, or leave the UI believing the wrong thing happened.`
Why it’s valuable: Launching external DCCs is core product value here, and the code already has async verification, file search, timeout handling, and headless warnings.
Expected output or impact: A formalized transition table, identified illegal states, and targeted changes or regression tests around cancellation, duplicate completion, and error recovery.

4. `Stress-test the threading architecture by looking for mismatches between the documented invariants and the actual controller usage. Focus on worker lifecycle ownership, signal delivery after disconnect, object deletion timing, and shutdown sequencing across QThread workers, QRunnables, and ProcessPoolManager tasks.`
Why it’s valuable: This codebase already has strong threading infrastructure, which usually means the remaining bugs are integration bugs at the edges, not simple missing mutexes.
Expected output or impact: A small set of high-confidence race or lifecycle risks, plus concrete tests that try to reproduce them under forced delays, reordered signals, and repeated startup/shutdown.

5. `Treat scrub preview and thumbnail loading as one shared media-delivery pipeline. Analyze whether they should remain separate systems or converge on shared caching, scheduling, prioritization, and visibility heuristics.`
Why it’s valuable: Both subsystems are latency-sensitive, cache-heavy, and UI-adjacent, which makes duplicated logic and competing resource usage likely.
Expected output or impact: Either a defensible argument for keeping them separate, or a design proposal for a unified media pipeline that reduces duplicated work and improves perceived responsiveness.

6. `Find assumptions that only hold in mock mode or only hold in the real VFX environment. Compare code paths, env checks, workspace validation, and filesystem expectations to surface behavior that tests are masking.`
Why it’s valuable: The repo explicitly supports both mock and production-style execution, and those dual modes often drift until the test suite validates the wrong reality.
Expected output or impact: A list of mock/production divergences, missing integration seams, and recommendations for “contract tests” that keep mock mode honest.

7. `Analyze the repository’s current test suite for blind spots caused by over-isolation. Identify behaviors that are well-covered in unit tests but under-covered as end-to-end state transitions across MainWindow, controllers, caches, and workers.`
Why it’s valuable: This project already has a substantial test suite, so the highest-value move is to find the important interactions that still slip between test layers.
Expected output or impact: A heat map of over-tested vs under-tested areas and a short list of new integration or regression tests that buy disproportionate confidence.

8. `Profile the expensive paths in 3DE discovery and previous-shots refresh, then ask whether the current optimizations are aimed at the right bottlenecks. Distinguish algorithmic wins from cache illusions and parallelism overhead.`
Why it’s valuable: The performance suite shows this repo already enforces budgets for scene discovery, but budget compliance can still hide poor scaling or brittle assumptions.
Expected output or impact: A bottleneck ranking, evidence of whether CPU, filesystem traversal, subprocesses, or Qt scheduling dominate, and specific performance ideas with expected payoff and tradeoffs.

9. `Challenge the current persistent-manager pattern for pins, notes, and hidden shots. Evaluate whether these managers should remain separate JSON-backed silos or move toward a unified persistence layer with schema/versioning, transaction semantics, and sync hooks.`
Why it’s valuable: These features look small individually but they shape day-to-day UX, and siloed persistence tends to accumulate schema drift and awkward coordination logic.
Expected output or impact: A design memo weighing simplicity against long-term maintainability, plus a migration path if unification would materially reduce duplication or corruption risk.

10. `Search for negative caches and “not found” states that can become correctness bugs. Focus on latest-file caching, scene discovery misses, and thumbnail absence. Ask where Shotbot may remember absence longer than it should, or fail to distinguish “missing now” from “missing forever.”`
Why it’s valuable: This repo explicitly uses tri-state cache semantics, and negative caching is powerful but dangerous in active production directories.
Expected output or impact: A list of stale-negative-cache risks, recommendations for TTL tuning or invalidation triggers, and test cases that simulate files appearing after a cached miss.

11. `Propose one genuinely new user-facing capability that the current architecture almost supports already, but not quite. Base it on existing primitives such as cached latest files, scrub previews, launch context, previous shots, notes, or hidden/pinned state.`
Why it’s valuable: The codebase already contains rich primitives; a good product move may be composition rather than net-new infrastructure.
Expected output or impact: One or two feature concepts with low-to-medium implementation cost, a dependency map, and an argument for why the feature would feel native rather than bolted on.

12. `Perform an “assumption inversion” review: for each major subsystem, assume its happiest-path premise is false. Examples: the cache is corrupt, the workspace moved, the process pool is half-shutdown, a worker finishes after its owner died, a plate source exists but frame ranges are wrong, the user changes tabs mid-refresh. What breaks first?`
Why it’s valuable: This repo’s real risks are operational weirdness and ordering failures, not toy logic errors.
Expected output or impact: A prioritized resilience report, explicit failure modes, and a short list of defensive changes that improve recovery without making the code much more complex.

13. `Review the controller layer for architectural drift. Decide whether controllers like RefreshCoordinator, StartupOrchestrator, and ThreeDEWorkerManager are true orchestration boundaries or are becoming hidden service locators with too much knowledge of UI internals.`
Why it’s valuable: The current architecture is already organized around controllers, which means the next major design win is tightening their contracts before they become ambiguous.
Expected output or impact: A boundary map, proposed controller responsibilities, and a refactor sequence that makes dependencies more legible and easier to test.

14. `Design a developer-experience pass aimed at shortening feedback loops for the kinds of bugs this repo actually gets: race conditions, cache seam regressions, launch-state bugs, and environment-specific failures. Don’t optimize generic linting; optimize diagnosis.`
Why it’s valuable: This codebase already has strong lint/type/test tooling, so the bigger DX win is making hard failures faster to reproduce and localize.
Expected output or impact: Concrete tooling ideas such as deterministic race injectors, startup/launch trace capture, synthetic cache corruption fixtures, or focused “scenario runners” for the highest-friction workflows.

15. `Audit where Shotbot’s design choices are documented in docs but not enforced in code. For each architectural rule in the docs, determine whether the repository has an automated guard, a test, a linter rule, or nothing.`
Why it’s valuable: This repo has unusually strong documentation for threading, caching, signal routing, and environment contracts; the next leverage point is converting prose invariants into executable safeguards.
Expected output or impact: A docs-to-enforcement gap analysis and a shortlist of lightweight checks that prevent architectural regressions.

## Optional Follow-Up

If useful, these can be consolidated into a single reusable review brief or split into themed prompt packs for architecture, resilience, performance, and product exploration.
