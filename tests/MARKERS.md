# Test Markers Reference

This document describes all custom pytest markers used in the Shotbot test suite.

## Quick Reference

| Marker | Purpose | When to Use |
|--------|---------|-------------|
| `@pytest.mark.qt` | Force Qt cleanup fixtures | Non-qtbot tests that use Qt |
| `@pytest.mark.qt_heavy` | Isolate on single worker | Resource-intensive Qt tests |
| `@pytest.mark.real_timing` | Bypass qtbot.wait() patch | Timing-sensitive tests |
| `@pytest.mark.real_subprocess` | Use real subprocess | Integration tests with actual process execution |
| `@pytest.mark.permissive_subprocess` | Legacy opt-out (DISCOURAGED) | Tests not yet migrated to subprocess_mock |
| `@pytest.mark.permissive_process_pool` | Disable strict pool mode | Tests that don't need pool contract enforcement |
| `@pytest.mark.allow_main_thread` | Allow main thread pool calls | Tests that intentionally call from main thread |
| `@pytest.mark.enforce_thread_guard` | Enable main-thread rejection | Contract testing for thread boundaries |
| `@pytest.mark.persistent_cache` | Skip disk cache clearing | Tests for cache loading/migration |
| `@pytest.mark.legacy` | Exclude from default runs | Historical or overlapping coverage suites |
| `@pytest.mark.performance_like` | Exclude from default runs | Timing-sensitive behavioral checks |
| `@pytest.mark.tutorial` | Exclude from default runs | Reference/example tests |
| `@pytest.mark.allow_dialogs` | Suppress dialog detection | Tests where dialogs are expected |
| `@pytest.mark.thread_leak_ok` | Suppress thread leak failure | Tests with expected thread leaks |
| `@pytest.mark.enforce_unique_connections` | Enforce UniqueConnection | Signal connection contract tests |
| `@pytest.mark.slow` | Mark slow tests | Tests that take >1s |
| `@pytest.mark.gui_mainwindow` | Full GUI tests | Tests using real MainWindow |
| `@pytest.mark.integration_unsafe` | Unsafe for parallel | Tests that must run serially |

---

## Qt-Related Markers

### `@pytest.mark.qt`

Force Qt cleanup fixtures on a test that doesn't use `qtbot`.

**When to use**: Tests that use Qt objects (QWidget, QObject, signals) but don't request the `qtbot` fixture.

**Effect**: Applies `qt_cleanup` and `reset_singletons` fixtures automatically.

```python
@pytest.mark.qt
def test_qt_signal_without_qtbot():
    """Test that uses Qt but not qtbot."""
    signal = MySignal()
    # Qt cleanup will happen after test
```

**Note**: Tests using `qtbot` fixture get Qt cleanup automatically - no marker needed.

---

### `@pytest.mark.qt_heavy`

Isolate test on a dedicated worker group for resource-intensive Qt operations.

**When to use**: Tests that:
- Create many widgets
- Run long Qt event loops
- Have complex signal/slot chains
- Cause test failures when running in parallel

**Effect**: Forces test into `qt_heavy` xdist worker group, ensuring isolation.

```python
@pytest.mark.qt_heavy
def test_complex_mainwindow_workflow(qtbot):
    """Heavy test that needs isolation."""
    window = MainWindow()
    # Complex operations that shouldn't interfere with other tests
```

---

### `@pytest.mark.real_timing`

Bypass the `qtbot.wait()` patch for timing-sensitive tests.

**When to use**: Tests that:
- Measure actual timing/performance
- Need precise wait durations
- Test timeout behavior

**Effect**: `qtbot.wait(ms)` waits for full duration instead of minimum 1ms.

```python
@pytest.mark.real_timing
def test_timeout_behavior(qtbot):
    """Test that needs accurate timing."""
    start = time.time()
    qtbot.wait(100)  # Actually waits 100ms
    elapsed = time.time() - start
    assert elapsed >= 0.1
```

**Alternative**: Set `SHOTBOT_TEST_NO_WAIT_PATCH=1` environment variable.

---

## Subprocess/Process Pool Markers

### `@pytest.mark.real_subprocess`

Execute tests with real subprocess calls instead of mocks.

**When to use**: Integration tests that need actual process execution.

**Effect**: Skips the autouse `subprocess_mock` fixture entirely.

```python
@pytest.mark.real_subprocess
def test_actual_command_execution():
    """Test that runs real shell commands."""
    result = subprocess.run(["echo", "hello"], capture_output=True)
    assert result.returncode == 0
```

---

### `@pytest.mark.permissive_subprocess`

**DISCOURAGED** - Legacy opt-out from strict subprocess mocking.

**When to use**: Legacy tests not yet migrated to `subprocess_mock` fixture.

**Effect**: Allows subprocess calls without explicit mocking (silent pass-through).

**Migration path**: Convert to use `subprocess_mock` fixture instead.

```python
# DISCOURAGED - migrate to subprocess_mock
@pytest.mark.permissive_subprocess
def test_legacy_subprocess_usage():
    ...

# PREFERRED
def test_proper_subprocess_usage(subprocess_mock):
    subprocess_mock.register("ls", exit_code=0, stdout="file1\nfile2")
    ...
```

---

### `@pytest.mark.permissive_process_pool`

Disable strict mode for `TestProcessPool`.

**When to use**: Tests that don't need process pool contract enforcement.

**Effect**: Unconfigured pool commands return empty results instead of failing.

```python
@pytest.mark.permissive_process_pool
def test_without_pool_contract():
    """Test that doesn't care about pool output."""
    # Pool calls won't fail even if not registered
```

---

### `@pytest.mark.allow_main_thread`

Allow ProcessPoolManager calls from main/UI thread.

**When to use**: Tests that intentionally call pool from main thread (e.g., synchronous refresh tests).

**Effect**: Suppresses main-thread rejection in thread guard.

```python
@pytest.mark.allow_main_thread
def test_synchronous_refresh():
    """Test that calls pool from main thread."""
    model.refresh_shots()  # Won't fail thread guard
```

---

### `@pytest.mark.enforce_thread_guard`

Enable strict main-thread rejection for contract testing.

**When to use**: Tests verifying that code properly delegates to background threads.

**Effect**: ProcessPoolManager calls from main thread raise AssertionError.

```python
@pytest.mark.enforce_thread_guard
def test_async_implementation():
    """Verify work is delegated to background thread."""
    # Main thread pool calls will fail
```

---

## Cache Markers

### `@pytest.mark.persistent_cache`

Skip disk cache clearing for this test.

**When to use**: Tests for:
- Cache loading on startup
- Cache migration between versions
- Cache corruption handling

**Effect**: `reset_caches` fixture won't clear disk cache files.

```python
@pytest.mark.persistent_cache
def test_cache_migration(pre_populated_cache):
    """Test loading cache from previous version."""
    manager = CacheManager()
    # Cache files are preserved, not cleared
```

---

### `@pytest.mark.legacy`

Mark lower-signal or duplicate historical suites that should not run in default CI/local quick runs.

---

### `@pytest.mark.performance_like`

Mark tests with timing-sensitive thresholds or scenario-level performance checks.

---

### `@pytest.mark.tutorial`

Mark educational/reference tests that demonstrate patterns but are not primary regression protection.

---

## UI/Dialog Markers

### `@pytest.mark.allow_dialogs`

Suppress the leaked dialog detection check.

**When to use**: Tests where dialogs are expected to remain open.

**Effect**: Test won't fail if QDialog instances exist after test.

```python
@pytest.mark.allow_dialogs
def test_dialog_creation():
    """Test that intentionally leaves dialog open."""
    dialog = MyDialog()
    dialog.show()
    # Won't fail dialog leak check
```

---

## Thread Markers

### `@pytest.mark.thread_leak_ok`

Suppress thread leak detection failure.

**When to use**: Tests with expected background threads that outlive the test.

**Effect**: Test won't fail if thread count increases.

```python
@pytest.mark.thread_leak_ok
def test_long_running_worker():
    """Test that spawns persistent thread."""
    worker = BackgroundWorker()
    worker.start()
    # Won't fail thread leak check
```

---

### `@pytest.mark.enforce_unique_connections`

Enforce UniqueConnection flag for Qt signal connections.

**When to use**: Contract tests verifying no duplicate signal connections.

**Effect**: Validates signal connections use UniqueConnection flag.

```python
@pytest.mark.enforce_unique_connections
def test_signal_connection_contract(qtbot):
    """Verify signals use UniqueConnection."""
    widget = MyWidget()
    # Duplicate connections will fail
```

---

## Test Classification Markers

### `@pytest.mark.slow`

Mark tests that take more than 1 second.

**When to use**: Long-running tests that might be skipped in quick CI runs.

```python
@pytest.mark.slow
def test_full_workflow():
    """Complete end-to-end test (~5 seconds)."""
    ...
```

---

### `@pytest.mark.gui_mainwindow`

Mark tests that create full MainWindow GUI.

**When to use**: Tests using real MainWindow (resource-intensive).

```python
@pytest.mark.gui_mainwindow
def test_mainwindow_initialization(qtbot):
    """Test full MainWindow creation."""
    window = MainWindow()
    ...
```

---

### `@pytest.mark.integration_unsafe`

Mark tests unsafe for parallel execution.

**When to use**: Tests that must run serially due to global state dependencies.

```python
@pytest.mark.integration_unsafe
def test_global_state_modification():
    """Test that modifies global state."""
    ...
```

---

## Built-in Markers (pytest)

These are standard pytest markers also used in the test suite:

- `@pytest.mark.parametrize` - Parameterized test cases
- `@pytest.mark.skipif` - Conditional skip
- `@pytest.mark.usefixtures` - Apply fixtures without using their values
- `@pytest.mark.performance` - Performance/benchmark tests

---

## Registering New Markers

All custom markers should be registered in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "qt: Mark test as using Qt (triggers cleanup fixtures)",
    "qt_heavy: Resource-intensive Qt test (isolated worker)",
    "real_timing: Bypass qtbot.wait() patch",
    # ... etc
]
```

Unregistered markers will cause pytest warnings in strict mode.
