# Test Fixtures

Fixtures are organized by category and auto-loaded via `pytest_plugins` in `tests/conftest.py`.
For the canonical test execution policy and common commands, see `tests/README.md`.

## Fixture Index

| Module | Autouse | Key Fixtures | Purpose |
|--------|---------|-------------|---------|
| `qt_fixtures.py` | No (via dispatcher) | `suppress_qmessagebox`, `prevent_qapp_exit`, `qt_cleanup`, `expect_dialog`, `expect_no_dialogs` | Qt safety (prevent modal dialogs/app-exit), Qt cleanup, dialog assertion helpers |
| `process_fixtures.py` | No (via Qt dispatcher) | `subprocess_mock`, `mock_process_pool_manager`, `mock_subprocess_popen`, `subprocess_error_mock`, test doubles: `TestProcessPool`, `TestSubprocess`, `PopenDouble` | Subprocess interception, process pool mocking, and test doubles for DI integration testing |
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

`mock_subprocess_popen` (strict mode) is auto-injected for all Qt tests via `_qt_auto_fixtures`.
Non-Qt tests that call subprocess must use `subprocess_mock`, `fp` (pytest-subprocess), or request `mock_subprocess_popen` explicitly.

### Unit Tests: `subprocess_mock` fixture or `fp` (pytest-subprocess)

**`subprocess_mock`** — monkeypatches `subprocess.Popen` and `subprocess.run` with controllable output.

- Configure expected behavior via `set_output(stdout, stderr="")`, `set_return_code(code)`, `set_exception(exc)`, `reset()`
- Disables strict mode so Qt-test subprocess calls won't raise

```python
def test_launcher_builds_command(subprocess_mock):
    subprocess_mock.set_output("OK")
    subprocess_mock.set_return_code(0)
    launcher.launch()
    assert len(subprocess_mock.calls) == 1
```

**`fp`** (pytest-subprocess) — registers fake process invocations per-command.

- Strict-by-default: unregistered commands raise `ProcessNotRegisteredError`
- Preferred for new tests; use `fp.register(cmd, stdout=..., returncode=...)`, check calls via `fp.calls`

```python
def test_launches_correct_command(fp):
    fp.register(["my-tool", "--flag"])
    code_under_test()
    assert list(fp.calls[0]) == ["my-tool", "--flag"]
```

### Integration Tests: `TestSubprocess` / `PopenDouble` (injection)

Use test doubles from `process_fixtures.py` when the component accepts a subprocess executor via constructor/parameter.

- Explicit test doubles — no monkeypatching
- `TestSubprocess` wraps `TestCompletedProcess` for `subprocess.run()`-style interfaces
- `PopenDouble` provides a mock `Popen` interface for streaming output

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
| Unit test, need to verify exact command args | `subprocess_mock` or `fp` |
| Unit test, fine-grained per-command faking | `fp` (pytest-subprocess) |
| Integration test, DI available | `TestSubprocess` / `PopenDouble` |
| Need streaming Popen behavior | `PopenDouble` |
| Test needs real subprocess | Request nothing (non-Qt) or don't use `mock_subprocess_popen` |
