# Test Fixtures

Fixtures are organized by category and auto-loaded via `pytest_plugins` in `tests/conftest.py`.

## Fixture Index

| Module | Autouse | Key Fixtures | Purpose |
|--------|---------|-------------|---------|
| `qt_fixtures.py` | Yes | `suppress_qmessagebox`, `prevent_qapp_exit`, `cleanup_qt_state` | Qt safety (prevent modal dialogs/app-exit), Qt cleanup (event queue, pixmap cache) |
| `process_fixtures.py` | Yes | `subprocess_mock`, `mock_process_pool_manager` | Subprocess interception and process pool mocking |
| `singleton_fixtures.py` | Yes | `reset_caches`, `cleanup_state_heavy` | Reset singleton state; lite runs for all tests, heavy for Qt tests only |
| `environment_fixtures.py` | No | `temp_shows_root`, `isolated_cache_manager` | Temporary paths and isolated cache instances |
| `model_fixtures.py` | No | `make_test_shot`, `sample_shot_data`, `test_thde_scene` | Factories for building test data objects |
| `test_doubles.py` | No | `TestProcessPool`, `TestSubprocess`, `PopenDouble` | Test doubles for subprocess and process pool |

## Session-Scoped (in conftest.py)

- `qapp` — session-scoped `QApplication`; must exist before `pytest_plugins` loads
- `_patch_qtbot_short_waits` — intercepts `qtbot.wait()` for tiny delays to prevent re-entrancy crashes

## Test Behavior Markers

- `@pytest.mark.real_subprocess` — bypass autouse subprocess mocking
- `@pytest.mark.permissive_process_pool` — disable strict `ProcessPoolManager` mock mode for a test
- `@pytest.mark.enforce_thread_guard` — make `TestProcessPool` reject main-thread calls for contract testing
- `@pytest.mark.allow_main_thread` — allow main-thread calls through the test process pool when intentional
- `@pytest.mark.persistent_cache` — preserve disk cache files for tests that validate cache persistence or recovery
- `@pytest.mark.thread_leak_ok` — suppress thread-leak failure for an explicitly accepted leak case
- `@pytest.mark.allow_dialogs` — suppress strict dialog failure for a test
- `@pytest.mark.real_timing` — bypass the short-wait patch for tests with genuine QTimer dependencies

## Adding a Fixture

1. Put it in the right module (data? → `model_fixtures.py`; subprocess? → `process_fixtures.py`; Qt? → `qt_fixtures.py`; environment? → `environment_fixtures.py`)
2. Default scope is `function`; use `session` only for expensive immutable fixtures
3. New singletons: inherit `SingletonMixin`, register in `singleton_fixtures.py`
4. Update this table

## Subprocess Mocking Strategy

### Unit Tests: `subprocess_mock` fixture (monkeypatch)

Use `subprocess_mock` from `process_fixtures.py`.

- **Strict-by-default**: Any unpatched `subprocess.run()` or `subprocess.Popen()` call raises `AssertionError`
- Catches accidental real subprocess calls
- Configure expected commands via `subprocess_mock.set_output(stdout, stderr="")`, `subprocess_mock.set_return_code(code)`, `subprocess_mock.set_exception(exc)`, `subprocess_mock.reset()`

```python
def test_launcher_builds_command(subprocess_mock):
    subprocess_mock.set_output("OK")
    subprocess_mock.set_return_code(0)
    launcher.launch()
    assert len(subprocess_mock.calls) == 1
```

### Integration Tests: `TestSubprocess` / `PopenDouble` (injection)

Use test doubles from `test_doubles.py` when the component accepts a subprocess executor via constructor/parameter.

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
| Unit test, no DI for subprocess | `subprocess_mock` fixture |
| Integration test, DI available | `TestSubprocess` / `PopenDouble` |
| Need to verify exact command args | `subprocess_mock` (captures calls) |
| Need streaming Popen behavior | `PopenDouble` |

**Do NOT merge these two systems.** They serve different purposes — monkeypatch-based safety net vs. explicit test doubles for composed components.
