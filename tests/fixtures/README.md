# Test Fixtures

Fixtures are organized by category and auto-loaded via `pytest_plugins` in `tests/conftest.py`.
For the canonical test execution policy and common commands, see `tests/README.md`.

## Fixture Index

| Module | Autouse | Key Fixtures | Purpose |
|--------|---------|-------------|---------|
| `qt_fixtures.py` | No (via dispatcher) | `suppress_qmessagebox`, `prevent_qapp_exit`, `qt_cleanup`, `expect_dialog`, `expect_no_dialogs` | Qt safety (prevent modal dialogs/app-exit), Qt cleanup, dialog assertion helpers |
| `process_fixtures.py` | No (via Qt dispatcher) | `mock_process_pool_manager`, `mock_subprocess_popen`, test doubles: `TestProcessPool`, `TestCompletedProcess`, `PopenDouble` | Subprocess interception, process pool mocking, and test doubles for DI integration testing |
| `singleton_fixtures.py` | Yes | `reset_caches`, `reset_singletons` | Reset singleton state; lite runs for all tests, heavy for Qt tests only |
| `environment_fixtures.py` | No | `caching_enabled`, `temp_cache_dir`, `cache_manager`, `shot_cache`, `scene_disk_cache`, `make_test_shot`, `make_test_filesystem`, `make_real_3de_file`, `real_shot_model` | Isolated cache instances, cache-enabled test environments, shot/filesystem factories |
| `model_fixtures.py` | No | `TestShot`, `TestShotModel`, `TestCacheManager`, `create_test_shot` | Test double classes and factory functions for shot data objects |
| `mock_workspace_pool.py` (project root) | No | `MockWorkspacePool`, `create_mock_pool_from_filesystem` | Mock VFX workspace pool for `--mock` mode; imported by `app_services.py` at runtime, not a pytest fixture |

## Session-Scoped (in conftest.py)

- `qapp` — session-scoped `QApplication`; must exist before `pytest_plugins` loads

## Test Behavior Markers

- `@pytest.mark.real_subprocess` — group tests that use real subprocess for xdist isolation (no longer used for fixture opt-out)
- `@pytest.mark.permissive_process_pool` — disable strict `ProcessPoolManager` mock mode for a test
- `@pytest.mark.enforce_thread_guard` — make `TestProcessPool` reject main-thread calls for contract testing
- `@pytest.mark.allow_main_thread` — allow main-thread calls through the test process pool when intentional
- `@pytest.mark.persistent_cache` — preserve disk cache files for tests that validate cache persistence or recovery
- `@pytest.mark.thread_leak_ok` — suppress thread-leak failure for an explicitly accepted leak case
- `@pytest.mark.allow_dialogs` — suppress strict dialog failure for a test

Category markers (`unit`, `integration`, `qt`, `slow`, `fast`, `concurrency`, `regression`, `performance`, `gui_mainwindow`, `qt_heavy`, `smoke`, etc.) are defined in `pyproject.toml` and used for test selection — not listed here as they don't modify fixture behavior.

## Adding a Fixture

1. Put it in the right module (data? → `model_fixtures.py`; subprocess? → `process_fixtures.py`; Qt? → `qt_fixtures.py`; environment? → `environment_fixtures.py`)
2. Default scope is `function`; use `session` only for expensive immutable fixtures
3. New singletons: inherit `SingletonMixin`, register in `singleton_fixtures.py`
4. Update this table

## Subprocess Mocking Strategy

Shotbot uses a three-layer subprocess mocking architecture:

### Layer 1: Global Safety Net — `mock_subprocess_popen`

**`mock_subprocess_popen`** (process_fixtures.py) is auto-injected for all Qt tests via `_qt_auto_fixtures`.
Non-Qt tests that call subprocess must request it explicitly.

- **Purpose:** Prevent accidental real subprocess calls in the test environment.
- **Behavior:** Returns a benign `MagicMock` that does not simulate any specific command behavior.
- **NOT a test API:** This fixture is a safety guard, not a mocking framework for asserting subprocess behavior. Use Layer 2 or 3 when you need to test specific subprocess interactions.

```python
# mock_subprocess_popen prevents real subprocess calls, that's all
def test_something_that_calls_subprocess(mock_subprocess_popen):
    code_under_test()  # safe; any subprocess.Popen call is caught
```

### Layer 2: Application-Level Mocking — `ProcessPoolManager` Mocks

Mock `ProcessPoolManager` (or other application-level executors) when testing scheduling, callbacks, and lifecycle.

- Mocks at the application boundary, not at `subprocess.Popen`.
- `TestProcessPool` is a test double for `ProcessPoolManager` that enforces threading contracts.
- Use this when your code goes through application-level abstractions (e.g., `controller.launch()`).

```python
def test_controller_delegates_to_pool(mock_process_pool_manager):
    controller = MyController(pool=mock_process_pool_manager)
    controller.launch("command")
    assert mock_process_pool_manager.submit.called
```

### Layer 3: Per-Command Testing — `fp` (pytest-subprocess)

**`fp`** (pytest-subprocess) — registers fake process invocations per-command for fine-grained testing.

- Strict-by-default: unregistered commands raise `ProcessNotRegisteredError`.
- **Preferred for new tests** that need per-command control.
- Use `fp.register(cmd, stdout=..., returncode=...)` to define expected commands and their outputs.
- Check calls via `fp.calls`.

```python
def test_launches_correct_command(fp):
    fp.register(["my-tool", "--flag"], stdout="success")
    code_under_test()
    assert list(fp.calls[0]) == ["my-tool", "--flag"]
```

### Test Doubles: `TestSubprocess`, `TestCompletedProcess`, `PopenDouble`

Use test doubles from `process_fixtures.py` when the component accepts a subprocess executor via constructor/parameter (dependency injection).

- `TestCompletedProcess` — mock return value for `subprocess.run()`-style interfaces.
- `PopenDouble` — mock `Popen` for streaming output tests.
- No monkeypatching; explicit injection.

```python
def test_executor_handles_failure():
    test_subprocess = TestSubprocess(returncode=1, stderr="error")
    executor = ProcessExecutor(subprocess_runner=test_subprocess)
    result = executor.run("command")
    assert result.failed
```

### When to use which

| Scenario | Use |
|----------|-----|
| Prevent accidental real subprocess calls (Qt tests) | `mock_subprocess_popen` (auto-injected) |
| Test scheduler/pool delegation and lifecycle | Mock `ProcessPoolManager` or use `TestProcessPool` |
| Unit test, fine-grained per-command behavior | `fp` (pytest-subprocess) |
| Integration test with DI available | `TestCompletedProcess` / `PopenDouble` |
| Need streaming Popen behavior | `PopenDouble` |
| Test needs real subprocess | Request nothing (non-Qt) or don't use `mock_subprocess_popen` |

### Migration Notes

- **Existing tests** using `mock_subprocess_popen` do NOT need migration — the fixture serves as a safety net, not a test API.
- **New tests** needing subprocess behavior should use `fp` (pytest-subprocess) for precise per-command control.
- **Tests mocking `ProcessPoolManager`** should continue mocking at the application level — `fp` cannot replace these.
