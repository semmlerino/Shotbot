# Test Fixtures Guide

This guide documents the modular test fixture system in `tests/fixtures/`.

## Architecture Overview

Test fixtures are organized into focused modules under `tests/fixtures/`:

```
tests/fixtures/
├── __init__.py                    # Module marker
├── caching.py                     # Cache isolation and behavior testing
├── data_factories.py              # Data creation factories
├── determinism.py                 # Random seed control
├── filesystem_scanner_doubles.py  # Subprocess polling doubles for FilesystemScanner
├── qt_cleanup.py                  # Qt state cleanup (autouse)
├── qt_safety.py                   # Qt safety fixtures (autouse)
├── singleton_isolation.py         # Singleton reset (autouse)
├── singleton_registry.py          # Central registry for singleton cleanup
├── subprocess_mocking.py          # Subprocess safety (autouse)
├── temp_directories.py            # Temporary directory fixtures
└── test_doubles.py                # Test doubles (fakes, stubs)
```

**Note:** Qt bootstrap (`qapp`, `_patch_qtbot_short_waits`) is in `tests/conftest.py` directly, not a separate fixture module.

Fixtures are loaded via `pytest_plugins` in the root `conftest.py`:

```python
pytest_plugins = [
    # NOTE: Qt fixtures (qapp, _patch_qtbot_short_waits) are in conftest.py directly
    "tests.fixtures.determinism",
    "tests.fixtures.temp_directories",
    "tests.fixtures.test_doubles",
    "tests.fixtures.subprocess_mocking",
    "tests.fixtures.qt_safety",
    "tests.fixtures.qt_cleanup",
    "tests.fixtures.singleton_isolation",
    "tests.fixtures.caching",
    "tests.fixtures.data_factories",
]
```

**Note:** `singleton_registry.py` and `filesystem_scanner_doubles.py` are helper modules imported by other fixtures, not loaded directly via `pytest_plugins`.

## Module Reference

### Qt Bootstrap (in conftest.py)

Creates QApplication at import time before any widget imports.

**Fixtures:**
- `qapp` (session) - The global QApplication instance
- `_patch_qtbot_short_waits` (session, autouse) - Patches qtbot.wait() for <5ms calls

**Why it matters:** QApplication must exist before importing any widget classes to prevent crashes. These fixtures are in `tests/conftest.py` (not a separate module) to ensure they have access to the global QApplication instance.

### caching.py

Cache isolation and behavior testing fixtures.

**Fixtures:**
- `isolated_cache` - Provides isolated cache directory for test
- `cache_behavior` - Controls cache behavior during tests

### determinism.py

Controls random number generation for reproducible tests.

**Fixtures:**
- `stable_random_seed` - Fixes random.seed() and numpy.random.seed() to 12345

**Usage:**
```python
@pytest.mark.usefixtures("stable_random_seed")
def test_something_random():
    # Random values are now deterministic
    ...
```

**Note:** NOT autouse. Opt-in via marker or fixture request.

### temp_directories.py

Provides isolated temporary directories for tests.

**Fixtures:**
- `temp_shows_root` - Temporary shows directory
- `temp_cache_dir` - Temporary cache directory
- `cache_manager` - CacheManager with temp directory
- `real_cache_manager` - Alias for cache_manager

### test_doubles.py

Test doubles for complex dependencies.

**Classes:**
- `TestProcessPool` - Fake ProcessPoolManager for subprocess isolation

**Fixtures:**
- `test_process_pool` - TestProcessPool instance
- `make_test_launcher` - Factory for CustomLauncher instances

### subprocess_mocking.py (AUTOUSE)

Global subprocess mocking for parallel test execution safety.

**Fixtures:**
- `mock_process_pool_manager` (autouse) - Patches ProcessPoolManager singleton
- `mock_subprocess_popen` (autouse) - Patches subprocess.Popen globally

**Opt-out:** Use `@pytest.mark.real_subprocess` marker.

### qt_safety.py (AUTOUSE)

Prevents Qt-related test failures.

**Fixtures:**
- `suppress_qmessagebox` (autouse) - Auto-dismisses modal dialogs
- `prevent_qapp_exit` (autouse) - Prevents QApplication.exit() calls

### qt_cleanup.py (AUTOUSE)

Ensures Qt state cleanup between tests.

**Fixtures:**
- `qt_cleanup` (autouse) - Flushes events, clears caches, waits for threads

### singleton_isolation.py (AUTOUSE)

Resets singleton state between tests.

**Fixtures:**
- `cleanup_state` (autouse) - Resets all singleton managers

**Resets:**
- NotificationManager
- ProgressManager
- ProcessPoolManager
- QRunnableTracker
- ThreadSafeWorker
- FilesystemCoordinator

### data_factories.py

Factories for creating test data.

**Fixtures:**
- `sample_shot_data` - Sample shot dictionary
- `sample_threede_scene_data` - Sample 3DE scene dictionary
- `make_test_shot` - Factory for Shot instances
- `make_test_filesystem` - Factory for TestFileSystem instances
- `make_real_3de_file` - Factory for 3DE files
- `real_shot_model` - ShotModel with test dependencies
- `mock_subprocess_workspace` - Mock for VFX workspace commands
- `mock_environment` - Mock environment variables
- `isolated_test_environment` - Cache-clearing environment

### filesystem_scanner_doubles.py

Specialized test doubles for FilesystemScanner subprocess testing.

**Classes:**
- `PollingProcessDouble` - Subprocess.Popen double with configurable poll() sequences
- `TimeControlledPollingProcess` - Extended double with simulated elapsed time

**Fixtures:**
- `polling_process` - PollingProcessDouble instance
- `time_controlled_process` - TimeControlledPollingProcess instance

**Usage:**
```python
def test_timeout_handling(polling_process, monkeypatch):
    polling_process.set_poll_sequence([None] * 100)  # Never complete
    polling_process.stdout_data = "/path/to/file.3de"
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: polling_process)
    # Test timeout logic...
```

### singleton_registry.py

Central registry for singleton cleanup between tests.

**Purpose:** Provides a single source of truth for all singletons that need to be reset between tests. Used by `singleton_isolation.py` to ensure consistent cleanup.

**Functions:**
- `get_all_singletons()` - Returns list of all registered singleton classes
- `reset_all_singletons()` - Resets all registered singletons

## Fixture Dependencies

```
qapp
 └── qt_cleanup
 └── qt_safety.prevent_qapp_exit
 └── qt_safety.suppress_qmessagebox

test_process_pool
 └── subprocess_mocking.mock_process_pool_manager

temp_cache_dir
 └── cache_manager
     └── data_factories.real_shot_model
```

## Autouse Fixtures Summary

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `_patch_qtbot_short_waits` | session | Prevent re-entrancy crashes |
| `mock_process_pool_manager` | function | Subprocess isolation |
| `mock_subprocess_popen` | function | Subprocess isolation |
| `suppress_qmessagebox` | function | Prevent dialog blocking |
| `prevent_qapp_exit` | function | Prevent event loop corruption |
| `qt_cleanup` | function | Qt state cleanup |
| `cleanup_state` | function | Singleton isolation |

## Opt-Out Markers

- `@pytest.mark.real_subprocess` - Skip subprocess mocking for tests that need real processes

## Best Practices

1. **Use factories over raw data:**
   ```python
   def test_shot(make_test_shot):
       shot = make_test_shot(show="TestShow")
   ```

2. **Request only what you need:**
   ```python
   def test_simple(tmp_path):  # pytest built-in
       ...

   def test_with_cache(cache_manager):  # our fixture
       ...
   ```

3. **Use markers for opt-in fixtures:**
   ```python
   @pytest.mark.usefixtures("stable_random_seed")
   def test_deterministic():
       ...
   ```

4. **Trust autouse fixtures:** Don't manually reset singletons - `cleanup_state` handles it.

## Migration from Old Fixtures

If you have tests importing from `tests.conftest`, update to use the fixture system:

```python
# OLD (don't do this)
from tests.conftest import some_fixture

# NEW (fixtures auto-available)
def test_something(some_fixture):
    ...
```
