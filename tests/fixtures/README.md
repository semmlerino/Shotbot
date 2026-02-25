# Test Fixtures

Fixtures are organized by category and auto-loaded via `pytest_plugins` in `tests/conftest.py`.

## Fixture Index

| Module | Autouse | Key Fixtures | Purpose |
|--------|---------|-------------|---------|
| `determinism.py` | No | `stable_random_seed` | Reproducible random seed control |
| `temp_directories.py` | No | `temp_shows_root`, `temp_cache_dir`, `cache_manager` | Temporary paths and cache instances |
| `test_doubles.py` | No | `TestProcessPool`, `test_process_pool`, `make_test_launcher` | Test doubles for system boundaries |
| `subprocess_mocking.py` | Yes | `mock_process_pool_manager`, `mock_subprocess_popen`, `subprocess_mock` | Global subprocess interception; `subprocess_mock` for controllable error paths |
| `qt_safety.py` | Yes | `suppress_qmessagebox`, `prevent_qapp_exit` | Prevent modal dialogs and app-exit from blocking tests |
| `qt_cleanup.py` | Qt tests only | `qt_cleanup` | Clears Qt event queue, QThreadPool, QPixmapCache between tests |
| `singleton_isolation.py` | Yes (lite) / Qt only (heavy) | `cleanup_state_lite`, `cleanup_state_heavy` | Resets singleton state; lite runs for all tests, heavy for Qt tests only |
| `data_factories.py` | No | `make_test_shot`, `make_real_3de_file`, `sample_shot_data` | Factories for building test data objects |

## Session-Scoped (in conftest.py)

- `qapp` — session-scoped `QApplication`; must exist before `pytest_plugins` loads
- `_patch_qtbot_short_waits` — intercepts `qtbot.wait()` for tiny delays to prevent re-entrancy crashes

## Opt-Out Markers

- `@pytest.mark.real_subprocess` — bypass autouse subprocess mocking
- `@pytest.mark.allow_dialogs` — suppress strict dialog failure for a test
- `@pytest.mark.real_timing` — bypass the short-wait patch for tests with genuine QTimer dependencies

## Adding a Fixture

1. Put it in the right module (data? → `data_factories.py`; subprocess? → `subprocess_mocking.py`; Qt? → `qt_safety.py` or `qt_cleanup.py`)
2. Default scope is `function`; use `session` only for expensive immutable fixtures
3. New singletons: inherit `SingletonMixin`, register in `singleton_registry.py`
4. Update this table
