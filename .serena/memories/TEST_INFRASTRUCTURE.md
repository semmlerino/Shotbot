# Shotbot Test Infrastructure

> See `CLAUDE.md` for test commands and `UNIFIED_TESTING_V2.md` for full testing guidance.
> Last Updated: February 2026

## Test Suite Overview

- **~3,200 tests** across ~140 test files (119 unit + 20 integration)
- **0 errors, 0 warnings** on basedpyright strict
- Parallel execution: `pytest -n auto --dist=loadgroup`

## Coverage Profile

**Well-tested (core business logic, 90%+):**
- Data models & parsing (shot_model, previous_shots_model, threede_scene_model, shot_parser, scene_parser)
- Caching & storage (cache_manager, filesystem_coordinator, process_pool_manager)
- Launching & execution (command_launcher, command_builder, environment_manager, process_executor)
- Controllers (settings, threede, filter_coordinator, shot_selection, thumbnail_size_manager)
- Threading (thread_safe_worker, threading_manager, runnable_tracker)

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
| `test_doubles.py` | Mock managers, fake finders, test data builders |
| `data_factories.py` | `make_shot()`, `make_scene()` etc. for reproducible data |
| `temp_directories.py` | Cache directory isolation with auto-cleanup |
| `caching.py` | Cache-specific test fixtures |
| `determinism.py` | Random seed control for reproducibility |

## Qt Test Quirks

- **Auto-attachment**: `qt_cleanup` fixture is auto-applied to tests that request `qtbot`, `qapp`, or use `@pytest.mark.qt`. Tests importing PySide6 without fixtures skip cleanup (rare gap, low risk).
- **Short-wait patch**: Session-scoped patch replaces `qtbot.wait(0-5ms)` with `process_qt_events()`. Waits >5ms use real timing. Disable with `SHOTBOT_TEST_NO_WAIT_PATCH=1`.
- **STRICT_CLEANUP**: Auto-enabled in CI (`CI=true`). Logs thread leak warnings but doesn't fail tests.
- **`real_timing` marker**: Registered but not implemented as a per-test override. Doesn't matter in practice — marked tests use waits >5ms already.
- **`process_qt_events()`**: Use instead of `qtbot.wait(1)` for Qt state cleanup in tests.

## Test Markers

`@pytest.mark.unit`, `integration`, `qt`, `concurrency`, `slow`, `performance`, `real_timing`
