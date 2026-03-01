# Shotbot Testing Guide

## Quick Start

```bash
uv run pytest tests/                             # Default suite, serial (primary gate)
uv run pytest tests/ -n auto --dist=loadgroup   # Parallel isolation check (secondary gate)
uv run pytest tests/ tests/performance/ -m "" -n auto --dist=loadgroup   # Comprehensive (includes legacy + performance tests)
uv run pytest tests/ -k "test_cache" -v          # Subset
uv run pytest --lf                               # Re-run last failed
uv run pytest -m "not performance"               # Skip perf tests
```

CI policy:
- Serial is the primary correctness gate and the default expectation for local runs.
- Parallel is retained as a secondary isolation check for shared-state, teardown, and xdist grouping bugs.
- A test that only fails in parallel is still a real failure unless it is intentionally excluded with a documented reason.

---

## Qt Widget Rules (Non-Negotiable)

### Parent parameter — ALL widgets MUST have it

```python
# CORRECT
def __init__(self, cache_manager: CacheManager | None = None, parent: QWidget | None = None) -> None:
    super().__init__(parent)
```

Missing parent causes Qt C++ crashes (`Fatal Python error: Aborted`).

### Always register with qtbot

```python
def test_widget(qtbot):
    widget = MyWidget()
    qtbot.addWidget(widget)  # Required — Qt owns cleanup
```

### Qt resources need try/finally

```python
timer = QTimer()
try:
    timer.start(50)
    qtbot.waitUntil(lambda: condition)
finally:
    timer.stop()
    timer.deleteLater()
```

### Signal mocking — patch.object does NOT disconnect Qt signals

```python
original_slot = controller.launch_app
panel.app_launch_requested.disconnect(original_slot)
panel.app_launch_requested.connect(mock_launch)
try:
    button.click()
finally:
    panel.app_launch_requested.disconnect(mock_launch)
    panel.app_launch_requested.connect(original_slot)
```

### Use qtbot.waitSignal / waitUntil, never time.sleep()

```python
with qtbot.waitSignal(worker.finished, timeout=5000):
    worker.start()
```

### Dialog suppression is STRICT — tests fail if dialogs are triggered without acknowledgment

Auto-returning `Yes/Ok` bypasses `Cancel/No` code paths. Be explicit:

```python
@pytest.mark.allow_dialogs          # Dialog is expected side-effect
def test_error_shows_warning(): ...

def test_confirm_dialog(expect_dialog):
    confirm_action()
    expect_dialog.assert_shown("question", "Are you sure?")

def test_quiet_operation(expect_no_dialogs):
    perform_operation()             # Auto-checked on teardown
```

---

## Subprocess Mock Pattern (TestProcessPool)

**Subprocess calls fail by default** — `ProcessPoolManager` is a singleton; without global mocking, multiple xdist workers running real `ws -sg` commands crash at the C level and contend for singleton state.

`subprocess_mocking.py` is `autouse=True`. It replaces `ProcessPoolManager` with `TestProcessPool` and patches `subprocess.Popen` and `subprocess.run` globally for every test.

**Controllable mock** — use `subprocess_mock` fixture for error paths:

```python
def test_launcher_handles_failure(subprocess_mock):
    subprocess_mock.set_output("", stderr="command not found")
    subprocess_mock.set_return_code(127)
    result = launcher.run_command()
    assert result.success is False
    assert "ws" in subprocess_mock.calls[0]
```

Available methods: `set_output(stdout, stderr="")`, `set_return_code(code)`, `set_exception(exc)`, `reset()`, `calls` list.

**Opt out** for tests that genuinely need real subprocess:

```python
@pytest.mark.real_subprocess
def test_real_echo():
    result = subprocess.run(["echo", "hi"], capture_output=True, text=True)
    assert result.stdout.strip() == "hi"
```

---

## Parallel Execution (xdist)

Parallel runs are a **secondary validation mode**, not the primary gate. Keep them
because they catch isolation bugs that serial runs can miss, not because they are
necessarily much faster.

**Always use `--dist=loadgroup`** — `--dist=worksteal` ignores `xdist_group` markers and causes Qt fixture serialization failures. Using wrong dist mode with `-n` raises `UsageError`.

```bash
pytest -n auto --dist=loadgroup   # Correct
pytest -n auto --dist=worksteal   # Fails with UsageError
```

Session-scoped Qt fixtures (`qapp`, `_patch_qtbot_short_waits`) live in `tests/conftest.py` and must share the serialized worker. `--dist=loadgroup` ensures Qt tests are grouped correctly.

**Every test must be runnable:** alone, in any order, on any worker, multiple times.

If tests pass serially but crash in parallel, assume test hygiene first (dangling signals, shared caches, lingering threads) before suspecting platform bugs.

---

## Singleton Reset Pattern

All singletons support `ClassName.reset()` for test isolation. Centralized in `tests/fixtures/singleton_registry.py`.

- **SingletonMixin** (preferred for new code): Inherit, implement `_initialize()`, optionally override `_cleanup_instance()`. Register in `singleton_registry.py`.
- **Legacy pattern**: `ProcessPoolManager`, `NotificationManager`, `ProgressManager` each have a compatible `reset()` method.

Isolation is split by cost:
- `reset_caches` (autouse, all tests): Clears caches, disables caching, resets `Config.SHOWS_ROOT`
- `cleanup_state_heavy` (auto-applied to Qt tests only): Resets Qt-dependent singletons — skipped for pure logic tests to avoid 0.5s+ overhead per test

---

## Flaky Test Debugging Checklist

Work through in order:

1. **Run alone to confirm it's not an ordering issue:**
   ```bash
   uv run pytest path/to/test.py::test_name -vv
   ```

2. **Run 20x to confirm flakiness:**
   ```bash
   for i in {1..20}; do uv run pytest path/to/test.py::test_name -x || break; done
   ```

3. **Disable parallel:**
   ```bash
   uv run pytest path/to/test.py -n 0 -vv
   ```

4. **Single worker (isolates xdist grouping issues):**
   ```bash
   uv run pytest path/to/test.py -n 1 -vv
   ```

5. **Qt warnings (surfaces resource leaks, deleted-object access):**
   ```bash
   QT_LOGGING_RULES="*.warning=true" uv run pytest path/to/test.py -vv
   QT_FATAL_WARNINGS=1 uv run pytest path/to/test.py -vv
   ```

6. **Reproduce with the exact random seed from failure output:**
   ```bash
   uv run pytest --randomly-seed=XXXXX path/to/test.py -vv
   ```

**Common causes by symptom:**

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Pass alone, fail in parallel | Qt resource leak | try/finally for cleanup |
| Unexpected values across workers | Global state | monkeypatch |
| Pass alone, fail in full suite | Shared cache dir | Use `tmp_path` for cache_dir |
| Full suite crashes | Module-level Qt app | Use `qapp` fixture only |
| Data cleared during `qtbot.wait()` | Background loader | Stop background workers before waiting |

Thread leak detection is **on by default** (`SHOTBOT_TEST_FAIL_ON_THREAD_LEAK=1`).
To suppress thread leak failures for quick local runs, set `SHOTBOT_TEST_ALLOW_THREAD_LEAKS=1`.
`SHOTBOT_TEST_STRICT_CLEANUP=1` controls cleanup exception handling (not thread leaks).

When a Qt or thread-heavy test repeatedly causes native crashes, prefer deleting a
low-level stress test if it duplicates safer behavior coverage elsewhere. Do not
keep crash-prone micro-tests just to preserve redundant coverage.

---

## Timing Tests

Tests with real QTimer callbacks use `@pytest.mark.real_timing` to bypass the short-wait patch:

```python
@pytest.mark.real_timing
def test_debounce_behavior(qtbot):
    trigger_rapid_calls()
    qtbot.wait(200)     # Real delay, not patched to 0
    assert calls_debounced()
```

Use `process_qt_events()` from `tests.test_helpers` (not `qtbot.wait(1)`) for event flushing without timing dependency.

---

## Related Documentation

- **Project Guide**: [CLAUDE.md](CLAUDE.md)
