# Test Fixtures

This directory contains reusable test fixtures organized by category. Fixtures are automatically loaded via `pytest_plugins` in `tests/conftest.py`.

## Loaded Fixture Modules

| Module | Purpose | Key Fixtures |
|--------|---------|--------------|
| `determinism.py` | Reproducible random seed control | `stable_random_seed` |
| `temp_directories.py` | Temporary path/cache fixtures | `temp_shows_root`, `temp_cache_dir`, `cache_manager` |
| `test_doubles.py` | Test doubles for system boundaries | `TestProcessPool`, `test_process_pool`, `make_test_launcher` |
| `subprocess_mocking.py` | **Autouse** subprocess mocking + controllable mock | `mock_process_pool_manager`, `mock_subprocess_popen`, `subprocess_mock` |
| `qt_safety.py` | **Autouse** Qt safety fixtures | `suppress_qmessagebox`, `prevent_qapp_exit` |
| `qt_cleanup.py` | Qt state cleanup (auto-applied to Qt tests) | `qt_cleanup` |
| `singleton_isolation.py` | **Autouse** lightweight cleanup + heavy cleanup for Qt | `cleanup_state_lite`, `cleanup_state_heavy` |
| `data_factories.py` | Test data factories | `make_test_shot`, `make_real_3de_file`, `sample_shot_data` |

## Autouse Fixtures

The following fixtures run automatically for **every test** (opt-out patterns available):

### Subprocess Mocking (`subprocess_mocking.py`)
- `mock_process_pool_manager`: Replaces `ProcessPoolManager` singleton with `TestProcessPool`
- `mock_subprocess_popen`: Replaces `subprocess.Popen` with a mock

**Opt-out**: Add `@pytest.mark.real_subprocess` to run with real subprocess.

### Qt Safety (`qt_safety.py`)
- `suppress_qmessagebox`: Prevents modal dialogs from blocking tests
- `prevent_qapp_exit`: Prevents `QApplication.quit()` from terminating the test session

### Singleton Isolation (`singleton_isolation.py`)
- `cleanup_state_lite`: (autouse) Clears caches, disables caching, resets Config.SHOWS_ROOT

## Conditionally Applied Fixtures

The following fixtures are **auto-applied to Qt tests** (tests using `qtbot` or marked `@pytest.mark.qt`) via `pytest_collection_modifyitems`:

### Qt Cleanup (`qt_cleanup.py`)
- `qt_cleanup`: Clears Qt event queue, QThreadPool, and QPixmapCache between tests

### Heavy Singleton Cleanup (`singleton_isolation.py`)
- `cleanup_state_heavy`: Resets Qt-dependent singletons (NotificationManager, ProgressManager, ProcessPoolManager, etc.)

**Why conditional?** Pure logic tests (data parsing, validation) don't need 0.5s+ of Qt/singleton cleanup overhead.

## Usage Examples

### Using a Factory Fixture
```python
def test_shot_creation(make_test_shot):
    shot = make_test_shot(show="TestShow", sequence="SEQ001", shot="0010")
    assert shot.show == "TestShow"
```

### Using Test Process Pool
```python
def test_with_process_pool(test_process_pool):
    test_process_pool.set_outputs("workspace /shows/test/shots/010/0010")
    # ... test code that uses ProcessPoolManager
    assert test_process_pool.commands  # Verify what was called
```

### Using Controllable Subprocess Mock
```python
def test_command_parsing(subprocess_mock):
    """Test with controllable subprocess output."""
    subprocess_mock.set_output("workspace /shows/test/shots/010/0010")
    subprocess_mock.set_return_code(0)
    # ... test code that calls subprocess ...
    assert subprocess_mock.calls  # Verify commands were called
```

### Opting Out of Subprocess Mocking
```python
@pytest.mark.real_subprocess
def test_real_shell_command():
    """This test uses real subprocess execution."""
    import subprocess
    result = subprocess.run(["echo", "test"], capture_output=True, text=True)
    assert result.stdout.strip() == "test"
```

## Session-Scoped Fixtures (in conftest.py)

The following fixtures are in `tests/conftest.py` (not in this directory) because they need special handling:

- `qapp`: Session-scoped QApplication instance (created before pytest_plugins loads)
- `_patch_qtbot_short_waits`: Intercepts `qtbot.wait()` for tiny delays to prevent re-entrancy crashes

## Guidelines for Adding Fixtures

1. **Choose the right module**:
   - Data creation? → `data_factories.py`
   - Test doubles? → `test_doubles.py`
   - Temp directories? → `temp_directories.py`
   - Qt-related? → `qt_cleanup.py` or `qt_safety.py`
   - Subprocess-related? → `subprocess_mocking.py`

2. **Naming conventions**:
   - Factory fixtures: `make_*` (e.g., `make_test_shot`)
   - Sample data: `sample_*` (e.g., `sample_shot_data`)
   - Test doubles: Use class name (e.g., `TestProcessPool`)

3. **Fixture scope**:
   - Default: `scope="function"` for isolation
   - Use `scope="session"` only for expensive, immutable fixtures
   - Use `scope="module"` for shared state within a test module

4. **Documentation**:
   - Add docstrings with usage examples
   - Update this README when adding new fixtures
