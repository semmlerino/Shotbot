# Shotbot Testing Guide

## Quick Start

```bash
# Development: parallel for speed
uv run pytest -n 2 --dist=loadgroup

# CI: parallel with fail-fast
uv run pytest -n auto --dist=loadgroup --maxfail=1

# Re-run last failed
uv run pytest --lf

# Skip performance tests on WSL/CI
uv run pytest -m "not performance"
```

---

## Test Layering Strategy

**Structure your tests by isolation requirements:**

| Layer | Location | Qt? | Disk/IO? | Speed | Purpose |
|-------|----------|-----|----------|-------|---------|
| **Unit** | `tests/unit/` | No | No | <1ms/test | Pure logic, algorithms, data transforms |
| **Qt** | `tests/unit/` (with `qtbot`) | Yes | Minimal | 10-50ms/test | Widget behavior, signals, UI state |
| **Integration** | `tests/integration/` | Maybe | Yes | 50-500ms/test | Real cache, config files, cross-module flows |

> **Note:** We keep light Qt widget tests in `tests/unit/` alongside pure logic tests. If this becomes confusing, we can split to `tests/qt/`.

**Guidelines:**
- **Unit tests** should be the bulk of your suite (70%+). No Qt, no filesystem, no network. These run fastest and catch logic bugs early.
- **Qt tests** use `qtbot` fixture and may touch widgets, but avoid real disk operations. Use `tmp_path` for any file needs.
- **Integration tests** exercise real subsystems together. Accept slower speed for realistic validation.

**What goes where:**

```python
# tests/unit/test_shot_validator.py - Pure logic, no Qt
def test_shot_name_validation_rejects_spaces():
    assert not is_valid_shot_name("shot 001")

# tests/unit/test_shot_widget.py - Qt widget, but isolated
def test_shot_widget_emits_selection_signal(qtbot):
    widget = ShotWidget()
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.shot_selected):
        widget.select_shot("ABC_010")

# tests/integration/test_cache_persistence.py - Real filesystem
def test_cache_survives_restart(tmp_path):
    cache = CacheManager(cache_dir=tmp_path)
    cache.save_shots([shot1, shot2])

    # Simulate restart
    cache2 = CacheManager(cache_dir=tmp_path)
    assert cache2.load_shots() == [shot1, shot2]
```

---

## 5 Non-Negotiable Qt Rules

### 1. Use pytest-qt's `qapp` fixture
**Never create your own QApplication.** This prevents module-level Qt app conflicts.
```python
def test_widget(qapp, qtbot):
    widget = MyWidget()
    qtbot.addWidget(widget)
```

### 2. Always use try/finally for Qt resources
```python
timer = QTimer()
try:
    timer.start(50)
    qtbot.waitUntil(lambda: condition)
finally:
    timer.stop()
    timer.deleteLater()
```

### 3. Use qtbot.waitSignal/waitUntil, never time.sleep()
```python
with qtbot.waitSignal(worker.finished, timeout=5000):
    worker.start()

# Or use helper
from tests.helpers.synchronization import wait_for_condition
wait_for_condition(lambda: widget.is_ready, timeout_ms=2000)
```

### 4. Always use tmp_path for filesystem tests
```python
def test_file_creation(tmp_path):
    test_file = tmp_path / "data.json"
    test_file.write_text('{"key": "value"}')
```

### 5. Use monkeypatch for state isolation
```python
def test_config_path(tmp_path, monkeypatch):
    monkeypatch.setattr("config.Config.SHOWS_ROOT", str(tmp_path))
```

---

## The Golden Isolation Rule

**Every test must be runnable:**
- Alone (in isolation)
- In any order
- On any worker (in parallel)
- Multiple times consecutively

**If tests pass serially but crash in parallel, assume it's a test hygiene bug first** (dangling signals, shared caches, lingering threads). Only after exhausting those should you suspect Qt/platform issues—real bugs in GPU drivers, QPA plugins, or CI environments do exist but are rare.

---

## Fixture Design

### Scope Selection

| Scope | Lifecycle | Use When |
|-------|-----------|----------|
| `function` (default) | Per test | Most cases. Ensures isolation. |
| `class` | Per test class | Shared setup for related tests (rare) |
| `module` | Per test file | Expensive setup reused across file (e.g., large test data) |
| `session` | Entire run | Very expensive, truly immutable resources (e.g., compiled extensions) |

**Default to `function` scope.** Only broaden scope when you have a **measured performance reason** and the fixture is **truly stateless**.

```python
# ✅ GOOD - function scope for mutable state
@pytest.fixture
def cache_manager(tmp_path):
    """Fresh cache for each test."""
    return CacheManager(cache_dir=tmp_path)

# ✅ GOOD - session scope for immutable, expensive setup
@pytest.fixture(scope="session")
def compiled_shader():
    """Compile once, reuse everywhere (immutable)."""
    return compile_shader("standard.glsl")

# ❌ BAD - session scope for mutable state
@pytest.fixture(scope="session")
def shared_cache():  # Tests will contaminate each other!
    return CacheManager()
```

### Avoid Mega-Fixtures

**Problem:** Fixtures that know too much create hidden coupling and slow tests.

```python
# ❌ BAD - Mega-fixture that does everything
@pytest.fixture
def full_app_context(tmp_path, qtbot, monkeypatch):
    """Sets up entire app with all managers, widgets, config..."""
    config = Config(...)
    cache = CacheManager(...)
    settings = SettingsManager(...)
    main_window = MainWindow(config, cache, settings, ...)
    # 50 more lines...
    return AppContext(config, cache, settings, main_window, ...)

# ✅ GOOD - Composable, focused fixtures
@pytest.fixture
def config(tmp_path):
    return Config(config_dir=tmp_path)

@pytest.fixture
def cache_manager(tmp_path):
    return CacheManager(cache_dir=tmp_path)

@pytest.fixture
def main_window(qtbot, config, cache_manager):
    """Only composes what it needs."""
    window = MainWindow(config, cache_manager)
    qtbot.addWidget(window)
    return window
```

### `autouse` vs `@pytest.mark.usefixtures`

```python
# autouse=True: Runs for EVERY test in scope (use sparingly)
@pytest.fixture(autouse=True)
def cleanup_qt_state(qtbot):
    """Runs after every test - use only for critical cleanup."""
    yield
    process_qt_events()

# usefixtures: Explicit opt-in for specific tests/classes
@pytest.mark.usefixtures("mock_filesystem")
class TestFileOperations:
    def test_read(self): ...
    def test_write(self): ...
```

**Rule of thumb:**
- `autouse=True` only for **cleanup** that must always run
- `@pytest.mark.usefixtures` for **setup** that groups of tests share
- Explicit fixture parameters for **data** that tests consume

---

## Test Naming & Structure

### Naming Convention

Use `test_<unit>_<scenario>_<expected>` pattern:

```python
# ✅ GOOD - Clear what's tested, condition, and expectation
def test_shot_validator_empty_name_returns_false(): ...
def test_cache_manager_expired_ttl_triggers_refresh(): ...
def test_launcher_missing_rez_env_raises_configuration_error(): ...

# ❌ BAD - Vague, doesn't describe scenario or expectation
def test_validator(): ...
def test_cache(): ...
def test_error(): ...
```

### AAA Pattern (Arrange-Act-Assert)

Structure every test with clear phases:

```python
def test_cache_returns_none_for_expired_entry():
    # Arrange - Set up preconditions
    cache = CacheManager(ttl_seconds=60)
    cache.set("key", "value")

    # Act - Perform the action under test
    with time_machine.travel(datetime.now() + timedelta(seconds=120)):
        result = cache.get("key")

    # Assert - Verify the outcome
    assert result is None
```

**Avoid giant mushy tests:**

```python
# ❌ BAD - Mixed concerns, unclear what's being tested
def test_everything():
    cache = CacheManager()
    cache.set("a", 1)
    assert cache.get("a") == 1
    cache.set("b", 2)
    cache.delete("a")
    assert cache.get("a") is None
    assert cache.get("b") == 2
    cache.clear()
    assert len(cache) == 0

# ✅ GOOD - Split into focused tests
def test_get_returns_set_value(): ...
def test_delete_removes_entry(): ...
def test_clear_empties_cache(): ...
```

---

## Property-Based Testing with Hypothesis

For non-trivial logic (path handling, config merging, sorting rules), use [Hypothesis](https://hypothesis.readthedocs.io/) to test **invariants** rather than specific examples.

### Installation
```bash
uv add hypothesis --dev
```

### Example: Testing Shot Name Validation

```python
from hypothesis import given, strategies as st, assume

@given(st.text())
def test_shot_name_validation_never_crashes(name):
    """Validator handles any string without raising."""
    # Should return bool, never raise
    result = is_valid_shot_name(name)
    assert isinstance(result, bool)

@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1))
def test_valid_shot_names_accepted(name):
    """Alphanumeric + underscore names are always valid."""
    assume(not name.startswith("_"))  # Exclude leading underscore
    assert is_valid_shot_name(name) is True

@given(st.text())
def test_shot_name_with_spaces_rejected(name):
    """Any name containing spaces is invalid."""
    assume(" " in name)
    assert is_valid_shot_name(name) is False
```

### Example: Testing Sort Stability

```python
from hypothesis import given, strategies as st

@given(st.lists(st.builds(
    Shot,
    name=st.text(min_size=1, max_size=10),
    priority=st.integers(1, 5),
    mtime=st.floats(0, 1e9)
)))
def test_sort_by_priority_is_stable(shots):
    """Shots with equal priority maintain relative order."""
    sorted_shots = sort_shots_by_priority(shots)

    # Group by priority
    by_priority = defaultdict(list)
    for shot in shots:
        by_priority[shot.priority].append(shot)

    # Within each priority group, original order preserved
    for priority, original_group in by_priority.items():
        sorted_group = [s for s in sorted_shots if s.priority == priority]
        assert sorted_group == original_group
```

### When to Use Hypothesis

| Use Hypothesis | Use Example-Based |
|----------------|-------------------|
| Parsing/validation functions | UI interaction flows |
| Data transformations | Integration with external systems |
| Sorting/filtering logic | Tests requiring specific fixtures |
| Config merging rules | Tests with complex setup |

---

## Time Control

### Two Different Concerns

1. **Waiting on async/UI operations** → Use `qtbot.waitSignal()` / `waitUntil()`
2. **Testing time-dependent logic** → Use `time-machine` / `freezegun`

**Never mix them:** Don't use `time.sleep()` for either purpose.

### For UI/Async Waiting

```python
# ✅ GOOD - Wait for Qt signal
with qtbot.waitSignal(worker.finished, timeout=5000):
    worker.start()

# ✅ GOOD - Wait for condition
qtbot.waitUntil(lambda: widget.is_loaded, timeout=3000)

# ❌ BAD - Never sleep in tests
time.sleep(1)  # Flaky, slow, hides race conditions
```

### For Time-Dependent Business Logic

```python
import time_machine
from datetime import datetime, timedelta

def test_cache_expiration():
    """Test TTL without actual waiting."""
    cache = CacheManager(ttl_seconds=300)

    # Freeze time at a known point
    with time_machine.travel(datetime(2024, 1, 1, 12, 0, 0)):
        cache.set("key", "value")

    # Jump forward past TTL - no actual sleep!
    with time_machine.travel(datetime(2024, 1, 1, 12, 10, 0)):
        assert cache.is_expired("key") is True

def test_rate_limiter():
    """Test rate limiting without waiting."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)

    with time_machine.travel(datetime(2024, 1, 1, 12, 0, 0)) as traveler:
        # Use up quota
        for _ in range(5):
            assert limiter.allow_request() is True
        assert limiter.allow_request() is False  # Exhausted

        # Jump past window
        traveler.shift(timedelta(seconds=61))
        assert limiter.allow_request() is True  # Reset
```

---

## CI/Merge Policy

### Gates Before Merging

| Check | Command | Required |
|-------|---------|----------|
| **Tests pass** | `uv run pytest -n auto --dist=loadgroup` | Yes |
| **Type check clean** | `uv run basedpyright` | Yes |
| **Lint clean** | `uv run ruff check .` | Yes |
| **Coverage report** | `uv run pytest --cov --cov-report=term-missing` | Advisory |

### Coverage Policy

**We do not enforce a global coverage threshold in CI.** Coverage is advisory; we focus on testing critical paths.

**Current approach:**
- Overall coverage % is informational (includes excluded GUI/VFX code)
- Core business logic: aim for **70%+** but not enforced
- New code: **should include tests** (exceptions require justification in PR)

**What's excluded from coverage** (see `pyproject.toml`):
- VFX integrations (`nuke_*.py`, `maya_*.py`) - require external software
- GUI-heavy components - tested manually
- Legacy/deprecated code paths

### Type Checking Policy

- **Zero errors required** before merge
- `basedpyright` with strict settings
- `reportOptionalMemberAccess` enabled (no suppressions)

---

## Common Isolation Failures

| Problem | Symptom | Fix |
|---------|---------|-----|
| **Qt resource leaks** | Pass alone, fail in parallel | try/finally for cleanup |
| **Global state** | Unexpected values from other workers | monkeypatch |
| **Shared cache dirs** | Pass alone, fail in full suite | Use `tmp_path` for cache_dir |
| **Module-level Qt app** | Full suite crashes | Use `qapp` fixture only |
| **Background loaders** | Data cleared during qtbot.wait() | `defer_background_loads=True` |

**Detailed debugging:** See [Test Isolation Case Studies](docs/TEST_ISOLATION_CASE_STUDIES.md)

---

## Subprocess Testing Strategy

### Why Subprocess Mocking is Autouse

**Exception to normal guidance:** Subprocess mocking is `autouse=True` in `tests/fixtures/subprocess_mocking.py`.

**Why?** `ProcessPoolManager` is a singleton used throughout the codebase. Without global mocking:
- Multiple xdist workers running real `ws -sg` commands crash at the C level
- Workers contend for the same singleton state
- Test isolation becomes impossible

This is the pragmatic choice for a singleton dependency that spawns processes.

### Opt-Out: Real Subprocess Testing

Use `@pytest.mark.real_subprocess` when you need actual subprocess execution:

```python
@pytest.mark.real_subprocess
def test_echo_command_actually_runs():
    """Verify real shell commands work."""
    import subprocess
    result = subprocess.run(["echo", "hello"], capture_output=True, text=True)
    assert result.stdout.strip() == "hello"
```

### Controllable Subprocess Mock

For fine-grained control over subprocess behavior, use the `subprocess_mock` fixture:

```python
def test_launcher_handles_failure(subprocess_mock):
    """Test error handling when command fails."""
    subprocess_mock.set_output("", stderr="command not found")
    subprocess_mock.set_return_code(127)

    launcher = Launcher()
    result = launcher.run_command()

    assert result.success is False
    assert "ws" in subprocess_mock.calls[0]  # Verify command was called
```

**Available methods:**
- `set_output(stdout, stderr="")` - Configure command output
- `set_return_code(code)` - Configure exit code
- `set_exception(exc)` - Make subprocess raise an exception
- `calls` - List of commands that were called
- `reset()` - Clear state between calls

---

## How to Debug a Flaky Test

When a test fails intermittently, work through this checklist in order:

1. **Re-run the failing test alone:**
   ```bash
   uv run pytest path/to/test.py::test_name -vv
   ```

2. **Run it 20x to confirm flakiness:**
   ```bash
   uv run pytest path/to/test.py::test_name -vv --count=20
   ```
   (Requires `pytest-repeat`: `uv add pytest-repeat --dev`)

3. **Disable parallel execution:**
   ```bash
   uv run pytest path/to/test.py -n 0 -vv
   ```

4. **Re-enable parallel with single worker:**
   ```bash
   uv run pytest path/to/test.py -n 1 -vv
   ```

5. **For Qt-related flakiness, enable Qt warnings:**
   ```bash
   QT_LOGGING_RULES="*.warning=true" uv run pytest path/to/test.py -vv
   # Or make warnings fatal:
   QT_FATAL_WARNINGS=1 uv run pytest path/to/test.py -vv
   ```

6. **Reproduce with the random seed from failure output:**
   ```bash
   uv run pytest --randomly-seed=XXXXX path/to/test.py -vv
   ```

---

## Essential conftest.py Setup

```python
import os
from pathlib import Path

# MUST be at TOP, before any Qt imports
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Unique XDG per worker (prevents Qt6 warnings/races)
run_id = os.environ.get("PYTEST_XDIST_TESTRUNUID", "solo")
worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
xdg = f"/tmp/xdg-{run_id}-{worker}"
os.makedirs(xdg, mode=0o700, exist_ok=True)
os.environ.setdefault("XDG_RUNTIME_DIR", xdg)
```

### Timeout and Randomization Configuration

```ini
# pyproject.toml
[tool.pytest.ini_options]
timeout = 120
timeout_method = "thread"  # Works on all platforms
# Note: On Linux, "signal" method can be cleaner for thread/Qt debugging
# but "thread" is more portable and works reliably on Windows/WSL
```

---

## Testing Principles

1. **Test behavior, not implementation** — Focus on what code does, not how
2. **Use real components for integration tests** — `tmp_path`, real managers
3. **Use pure unit tests for algorithms** — No mocks needed for logic-only code
4. **Mock at boundaries only** — Network, subprocess, external APIs
5. **Use `@pytest.mark.parametrize`** — Cheapest way to improve coverage
6. **Use `caplog` for log-driven assertions** — Avoid printing to stdout as your primary debug tool

---

## Qt Signal Mocking

**Problem**: `patch.object(..., side_effect=mock)` doesn't disconnect Qt signals — still calls original.

**Solution**: Disconnect/reconnect signals directly:
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

---

## Qt-Specific Debugging

### QPixmapCache Cleanup

**When to use:** Only if you have **demonstrated memory pressure** from pixmap churn in tests (e.g., thumbnail-heavy test suites). This is NOT routine cleanup.

```python
# Only in tests with heavy thumbnail/image churn
@pytest.fixture
def cleanup_pixmap_cache():
    """Use sparingly - only for image-heavy test suites."""
    yield
    from PySide6.QtGui import QPixmapCache
    QPixmapCache.clear()
```

### QT_FATAL_WARNINGS

**Recommended approach:** Start with logging, graduate to fatal.

```python
# conftest.py - Phase 1: Log warnings, don't fail
import os
os.environ.setdefault("QT_LOGGING_RULES", "*.warning=true")

# Phase 2: Once suite is clean, make warnings fatal in CI
# os.environ.setdefault("QT_FATAL_WARNINGS", "1")
```

**Caution:** `QT_FATAL_WARNINGS=1` can be too strict with third-party widgets or noisy platforms. Consider:
- Enabling only in a separate CI job ("strict Qt mode")
- Using `QT_MESSAGE_PATTERN` to filter specific warnings first

---

## Best Practices Summary

### DO
- Use `-n auto --dist=loadgroup` for parallel execution (REQUIRED for Qt test grouping)
- Set `QT_QPA_PLATFORM` at TOP of conftest.py before Qt imports
- Use try/finally for Qt resources
- Use `tmp_path` for cache directories in tests
- Use `qtbot.waitSignal()` for async Qt testing
- Ensure `pytest-timeout` is configured (already in `pyproject.toml`)
- Use Hypothesis for validation/transformation logic
- Follow AAA pattern (Arrange-Act-Assert)
- Name tests descriptively: `test_<unit>_<scenario>_<expected>`

### DON'T
- Use `time.sleep()` or bare `processEvents()`
- Create Qt apps at module level
- Use `--dist=worksteal` (it ignores xdist_group markers - use `--dist=loadgroup`)
- Use `xdist_group` as a band-aid for isolation issues
- Use `@pytest.mark.flaky` to mask problems — fix root cause. If you must mark something flaky (external service, OS bug), add a comment linking to the underlying issue (ticket/upstream bug)
- Mock internals — only mock at system boundaries
- Create mega-fixtures that set up the entire world
- Use `autouse=True` for anything except critical cleanup

---

## Related Documentation

- **Case Studies**: [docs/TEST_ISOLATION_CASE_STUDIES.md](docs/TEST_ISOLATION_CASE_STUDIES.md) — Debugging workflows, Qt suite stability
- **Project Guide**: [CLAUDE.md](CLAUDE.md) — Full test coverage breakdown
