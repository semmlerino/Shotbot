# Shotbot Test Infrastructure

> See `CLAUDE.md` for test commands and `UNIFIED_TESTING_V2.md` for full testing guidance.
> Last Updated: March 2026

## Test Suite Overview

- **~2,650 tests** across ~127 test files (~105 unit + ~15 integration)
- **0 errors, 0 warnings** on basedpyright strict
- Parallel execution: `pytest -n auto --dist=loadgroup`

## Coverage Profile

**Well-tested (core business logic, 90%+):**
- Data models & parsing (shot_model, previous_shots_model, threede_scene_model, shot_parser, scene_parser)
- Caching & storage (cache_manager, filesystem_coordinator, process_pool_manager)
- Launching & execution (command_launcher, command_builder, environment_manager, process_executor)
- Controllers (settings, threede, filter_coordinator, shot_selection, thumbnail_size_manager)
- Threading (thread_safe_worker, threading_manager, runnable_tracker)
- Pin/Notes (pin_manager, file_pin_manager, notes_manager)

**Intentionally excluded (GUI/visual + VFX integrations):**
- Widget rendering (delegates, grid views, dialogs, thumbnail widgets)
- VFX tool integrations (nuke_*, maya_*, 3de-specific modules)
- Development utilities (debug_utils, auto_screenshot, headless_mode)
- These are tested indirectly via integration tests and manual QA

## Available Test Fixtures (`tests/fixtures/`)

| Fixture Module | Purpose |
|---------------|---------|
| `qt_cleanup.py` | Qt event loop cleanup, thread leak detection (100ms timeout) |
| `qt_safety.py` | Qt state safety for parallel execution |
| `singleton_registry.py` | Centralized singleton reset between tests |
| `singleton_isolation.py` | Auto-reset singletons per test |
| `subprocess_mocking.py` | Workspace command mocking, process pool isolation |
| `test_doubles.py` | Re-exports from all `*_doubles.py` modules (see note below) |
| `data_factories.py` | `make_shot()`, `make_scene()` etc. for reproducible data |
| `temp_directories.py` | Cache directory isolation with auto-cleanup |
| `caching.py` | Cache-specific test fixtures |

**Note on doubles:** `test_doubles.py` is a convenience re-export of `cache_doubles.py`, `model_doubles.py`, `integration_doubles.py`, `signal_doubles.py`, and `process_doubles.py`. Import from the specific module or from `test_doubles` interchangeably.

## Qt Test Quirks

- **Auto-attachment**: `qt_cleanup` fixture is auto-applied to tests that request `qtbot`, `qapp`, or use `@pytest.mark.qt`. Tests importing PySide6 without fixtures skip cleanup (rare gap, low risk).
- **Short-wait patch**: Session-scoped patch replaces `qtbot.wait(0)` and `qtbot.wait(1)` with `process_qt_events()`. Waits of 2ms+ use real timing. Disable with `SHOTBOT_TEST_NO_WAIT_PATCH=1`.
- **Thread leak failures**: `FAIL_ON_THREAD_LEAK` defaults to enabled everywhere (opt out with `SHOTBOT_TEST_ALLOW_THREAD_LEAKS=1`). Thread leaks fail tests immediately. `STRICT_CLEANUP` (auto-enabled in CI via `CI=true`) adds extra diagnostic logging on top but does not itself cause failures.
- **`real_timing` marker**: Fully implemented — bypasses the short-wait patch for the marked test. Use for tests with genuine timing dependencies.
- **`process_qt_events()`**: Use instead of `qtbot.wait(1)` for Qt state cleanup in tests.

## Test Markers

`@pytest.mark.unit`, `integration`, `qt`, `concurrency`, `slow`, `performance`, `real_timing`
