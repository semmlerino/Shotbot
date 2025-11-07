# UNIFIED_TESTING_GUIDE

*Optimized for LLM consumption - comprehensive pytest patterns for ShotBot VFX application*

This document establishes consistent testing patterns and principles for the ShotBot VFX application test suite.

## Core Testing Philosophy

### 1. Test Behavior, Not Implementation
- Focus on what the code does, not how it does it
- Test public interfaces and observable outcomes
- Avoid testing private methods or internal state directly
- Write tests that remain stable when refactoring implementation

### 2. Use Real Components Where Possible
- Prefer real instances over mocks for better integration testing
- Use actual Qt widgets, file systems, and network connections when feasible
- Mock only at system boundaries (time, external APIs, hardware)
- Real components provide better confidence in actual behavior

### 3. Strategic Use of Test Doubles
- **Test Doubles**: Use for behavior verification and isolation
- **Mocks**: Only for external dependencies and system boundaries
- **Stubs**: For predictable responses from complex dependencies
- **Fakes**: For lightweight implementations of heavy dependencies

### 4. Thread Safety in Tests
- All tests must handle Qt's threading model correctly
- Use proper Qt test fixtures for GUI components
- Implement thread-safe cleanup patterns
- Test concurrent operations where applicable

## Quick Diagnostic Reference

Fast lookup for common test failures and issues:

| Issue | Likely Cause | Solution Section |
|-------|--------------|------------------|
| Test hangs indefinitely | Missing qtbot timeout | Qt GUI Components |
| Coverage below 80% fails CI | Missing test cases or branches | pyproject.toml Setup |
| Tests pass individually, fail in parallel | Shared state leakage between tests | Parallel Test Execution |
| Memory leak in test suite | Fixture scope too broad (session/module) | Fixture Scopes |
| Import errors in test discovery | Wrong file naming pattern | File Organization Standards |
| Mock not working as expected | Mocking wrong component | Mock Usage Guidelines |
| Thread safety test fails randomly | Race condition or missing synchronization | Thread Safety Testing |

## Testing Patterns by Component Type

### Qt GUI Components
```python
# GOOD: Real Qt components with proper fixtures
from typing import Iterator
from pytestqt.qtbot import QtBot
from PySide6.QtCore import Qt

@pytest.fixture
def main_window(qtbot: QtBot) -> MainWindow:
    """Create MainWindow with Qt lifecycle management."""
    window = MainWindow()
    qtbot.addWidget(window)
    return window

def test_window_behavior(main_window: MainWindow, qtbot: QtBot) -> None:
    """Test actual user interactions with typed parameters."""
    # Test actual user interactions
    qtbot.mouseClick(main_window.button, Qt.LeftButton)
    assert main_window.status_label.text() == "Clicked"
```

### Cache Components
```python
# GOOD: Real cache with temporary directories
from typing import Callable
from pathlib import Path

@pytest.fixture
def cache_manager(tmp_path: Path) -> CacheManager:
    """Create CacheManager with temporary directory."""
    return CacheManager(cache_dir=tmp_path / "cache")

def test_cache_behavior(cache_manager: CacheManager) -> None:
    """Test actual caching operations with type safety."""
    # Test actual caching operations
    result: str = cache_manager.get_or_create("key", lambda: "value")
    assert result == "value"
    assert cache_manager.contains("key")
```

### Process Management
```python
# GOOD: Mock at system boundary
from typing import Any
from unittest.mock import MagicMock

def test_process_execution(mock_subprocess: MagicMock) -> None:
    """Test process execution with mocked subprocess."""
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "success"

    manager = ProcessManager()
    result: ProcessResult = manager.execute(["echo", "test"])
    assert result.success
```

## File Organization Standards

### Test File Structure
```
tests/
├── unit/                    # Pure unit tests
│   ├── test_cache_manager.py
│   ├── test_shot_model.py
│   └── test_thumbnail_processor.py
├── integration/             # Component integration tests
│   ├── test_cache_integration.py
│   └── test_ui_workflow.py
├── fixtures/               # Shared test fixtures
│   ├── conftest.py
│   └── test_data/
└── utilities/              # Test utilities and helpers
    ├── qt_helpers.py
    └── mock_factories.py
```

### Test Naming Conventions
```python
# Test class names: Test + ComponentName
class TestShotModel:
    pass

# Test method names: test_ + behavior_description
def test_shot_loading_updates_model_correctly(self):
    pass

def test_thumbnail_cache_evicts_old_entries_under_pressure(self):
    pass

# Fixture names: component_name or descriptive_purpose
@pytest.fixture
def shot_model():
    pass

@pytest.fixture
def sample_thumbnail_files():
    pass
```

## pytest Configuration

### pyproject.toml Setup

Configure pytest in `pyproject.toml` for consistent test behavior across environments:

```toml
[tool.pytest.ini_options]
# Test discovery
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]

# Runtime options
addopts = [
    "--strict-markers",          # Enforce marker registration
    "--strict-config",           # Enforce configuration validation
    "-ra",                       # Show summary of all test outcomes
    "--cov=shotbot",             # Coverage for source package
    "--cov-report=html",         # HTML coverage report in htmlcov/
    "--cov-report=term-missing", # Terminal report with missing lines
    "--cov-fail-under=80",       # Minimum 80% coverage required
]

# Custom markers (must be registered)
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks tests requiring external resources",
    "unit: fast isolated unit tests",
    "qt: tests requiring Qt application",
]

# Minimum Python version
minversion = "7.0"
```

### Running Tests with Configuration

```bash
# Run all tests with coverage
uv run pytest

# Run only unit tests
uv run pytest -m unit

# Run excluding slow tests
uv run pytest -m "not slow"

# Run specific test file
uv run pytest tests/unit/test_cache_manager.py

# Run in parallel (requires pytest-xdist)
uv run pytest -n auto
```

## conftest.py Structure

Shared fixtures belong in `tests/conftest.py` for automatic discovery across all test files:

```python
# tests/conftest.py - Shared fixtures for entire ShotBot test suite
import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from shotbot.cache import CacheManager
from shotbot.models import ShotModel

@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication instance for all Qt tests."""
    app = QApplication.instance() or QApplication([])
    yield app
    app.quit()

@pytest.fixture
def cache_manager(tmp_path: Path) -> CacheManager:
    """Function-scope cache with temporary directory - fresh for each test."""
    return CacheManager(cache_dir=tmp_path / "cache")

@pytest.fixture
def sample_shots_data():
    """Reusable test data - immutable so safe to share."""
    return [
        {"name": "shot_010", "status": "approved", "frames": 120},
        {"name": "shot_020", "status": "in_progress", "frames": 240},
    ]
```

## Fixture Scopes

Understanding fixture scopes is critical for test performance and isolation.

### Scope Comparison

| Scope | Lifetime | Runs For | Best Use Case | Isolation Risk |
|-------|----------|----------|---------------|----------------|
| **function** (default) | Per test | 100 tests = 100 runs | Mutable state, safest choice | None |
| **class** | Per test class | 5 classes = 5 runs | Expensive setup, read-only | Low |
| **module** | Per file | 1 module = 1 run | Very expensive, immutable | Medium |
| **session** | Entire run | All tests = 1 run | Global constants only | High |

### Function Scope - Safest Default

```python
from pathlib import Path

@pytest.fixture  # scope="function" is default
def temp_cache(tmp_path: Path) -> CacheManager:
    """Created fresh for each test - best isolation."""
    return CacheManager(cache_dir=tmp_path / "cache")

def test_cache_set(temp_cache: CacheManager) -> None:
    temp_cache.set("key", "value")
    assert temp_cache.get("key") == "value"

def test_cache_clear(temp_cache: CacheManager) -> None:
    # Gets NEW cache instance, previous test's data is gone
    assert temp_cache.is_empty()
```

### Session Scope - Performance Critical

```python
from typing import Any

@pytest.fixture(scope="session")
def application_config() -> dict[str, Any]:
    """Created once for entire pytest session.

    Use ONLY for: Truly immutable data needed across all tests.
    Warning: Mutable state will leak between tests!
    """
    return load_application_config()
```

### Best Practices

1. **Default to function scope** - safest choice
2. **Use session scope** only for immutable config/constants
3. **Never share mutable state** in scopes broader than function
4. **Use class/module scopes** sparingly - they can hide test coupling

## Fixture Patterns

### Qt Component Fixtures
```python
@pytest.fixture
def shot_grid_view(qtbot):
    """Create ShotGridView with proper Qt lifecycle management."""
    view = ShotGridView()
    qtbot.addWidget(view)
    yield view
    # Cleanup handled by qtbot

@pytest.fixture
def thumbnail_widget(qtbot, tmp_path):
    """Create ThumbnailWidget with temporary cache directory."""
    cache_dir = tmp_path / "thumbnails"
    cache_dir.mkdir()

    widget = ThumbnailWidget(cache_directory=cache_dir)
    qtbot.addWidget(widget)
    return widget
```

### Data Fixtures
```python
@pytest.fixture
def sample_shots_data():
    """Provide realistic shot data for testing."""
    return [
        {"name": "shot_010", "status": "approved", "frames": 120},
        {"name": "shot_020", "status": "in_progress", "frames": 240},
        {"name": "shot_030", "status": "pending", "frames": 180},
    ]

@pytest.fixture
def mock_workspace_response():
    """Provide mock response for workspace command."""
    return {
        "shots": sample_shots_data(),
        "shows": ["test_show"],
        "timestamp": "2024-01-01T12:00:00Z"
    }
```

### Temporary File Fixtures
```python
@pytest.fixture
def thumbnail_files(tmp_path):
    """Create temporary thumbnail files for testing."""
    thumb_dir = tmp_path / "thumbnails"
    thumb_dir.mkdir()

    files = []
    for i in range(5):
        thumb_file = thumb_dir / f"thumb_{i}.jpg"
        # Create minimal valid JPEG
        thumb_file.write_bytes(
            b"\xff\xd8\xff\xe0" + b"x" * 1000 + b"\xff\xd9"
        )
        files.append(thumb_file)

    return files
```

## Parametrization Patterns

Parametrization allows testing multiple scenarios efficiently without code duplication.

### Basic Parametrization

```python
import pytest

@pytest.mark.parametrize("status,expected_color", [
    ("approved", "green"),
    ("in_progress", "yellow"),
    ("pending", "gray"),
    ("rejected", "red"),
])
def test_shot_status_color(status: str, expected_color: str) -> None:
    """Test status-to-color mapping for all possible statuses."""
    shot = Shot(status=status)
    assert shot.status_color == expected_color
```

### Parametrization with IDs for Readable Output

Use `ids` parameter for descriptive test names in output:

```python
from typing import Any

@pytest.mark.parametrize(
    "shot_data,expected_valid",
    [
        ({"name": "sh010", "status": "approved", "frames": 120}, True),
        ({"name": "", "status": "approved", "frames": 120}, False),
        ({"name": "sh010", "status": "invalid", "frames": 120}, False),
        ({"name": "sh010", "status": "approved", "frames": -10}, False),
    ],
    ids=["valid", "no_name", "bad_status", "negative_frames"]
)
def test_shot_validation(
    shot_data: dict[str, Any],
    expected_valid: bool
) -> None:
    """Test shot data validation with descriptive test IDs.

    Test output will show: test_shot_validation[valid], test_shot_validation[no_name], etc.
    """
    shot = Shot(**shot_data)
    assert shot.is_valid() == expected_valid
```

## Assertion Patterns

### Behavior Verification
```python
# GOOD: Test observable behavior
def test_shot_refresh_updates_view(shot_model: ShotModel, shot_view: ShotView) -> None:
    shot_model.add_shot("new_shot")
    shot_view.refresh()

    # Verify behavior through public interface
    assert shot_view.shot_count == 1
    assert "new_shot" in shot_view.visible_shots

# AVOID: Testing implementation details
def test_shot_refresh_calls_internal_method(shot_model: ShotModel) -> None:
    # Don't test private method calls
    with patch.object(shot_model, '_update_internal_cache'):
        shot_model.refresh()
        shot_model._update_internal_cache.assert_called_once()
```

### Error Condition Testing
```python
def test_thumbnail_loading_handles_missing_file(thumbnail_manager: ThumbnailManager) -> None:
    """Test graceful handling of missing thumbnail files."""
    missing_path = Path("/nonexistent/file.jpg")

    result = thumbnail_manager.load_thumbnail(missing_path)

    # Verify graceful failure
    assert result.success is False
    assert "not found" in result.error_message.lower()
    assert result.thumbnail is None
```

### Thread Safety Testing
```python
def test_concurrent_cache_access_thread_safe(cache_manager: CacheManager) -> None:
    """Test thread safety with concurrent operations."""
    import concurrent.futures

    def cache_operation(thread_id: int) -> None:
        for i in range(100):
            key = f"thread_{thread_id}_item_{i}"
            cache_manager.set(key, f"value_{i}")
            assert cache_manager.get(key) == f"value_{i}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(cache_operation, i) for i in range(5)]
        for future in concurrent.futures.as_completed(futures):
            future.result()  # Raises if any assertions failed
```

## Test Smells - Warning Signs

Patterns that indicate poorly designed tests:

❌ **Test depends on execution order**
```python
# BAD: test_02 depends on test_01 running first
class TestShotLoading:
    shots = []  # Shared state!

    def test_01_load_shots(self):
        self.shots = load_shots()

    def test_02_process_shots(self):  # Breaks if run alone!
        process(self.shots)
```

❌ **Test modifies global/shared state**
```python
# BAD: Modifies module-level config
def test_cache_with_custom_size():
    config.CACHE_SIZE = 1000  # Leaks to other tests!
    cache = CacheManager()
    assert cache.max_size == 1000
    # Forgot to restore config.CACHE_SIZE
```

❌ **Over-mocking - Testing mocks instead of real code**
```python
# BAD: Everything is mocked, testing nothing
def test_shot_processing():
    mock_shot = Mock()
    mock_processor = Mock()
    mock_processor.process.return_value = Mock()
    result = mock_processor.process(mock_shot)
    # We're only testing that mocks work!
```

❌ **No assertions - Test that doesn't verify anything**
```python
# BAD: No verification
def test_shot_loading():
    shot_model = ShotModel()
    shot_model.load_shots()  # Did it work? No idea!
```

❌ **Multiple concepts - Should be separate tests**
```python
# BAD: Testing loading, filtering, and sorting together
def test_shot_operations():
    shots = load_shots()
    filtered = filter_shots(shots)
    sorted_shots = sort_shots(filtered)
    # Which operation failed?
```

❌ **Unclear names - Doesn't describe expected behavior**
```python
# BAD: What does this test verify?
def test_shot_1():
    ...

# GOOD: Clear expected behavior
def test_shot_loading_handles_network_timeout_gracefully():
    ...
```

✅ **Good test characteristics:**
- Independent (can run in any order)
- Isolated (no shared mutable state)
- Repeatable (same result every time)
- Self-validating (clear pass/fail)
- Timely (fast execution)
- Clear naming (describes expected behavior)

## Mock Usage Guidelines

### Mocking Decision Function

Use executable logic to decide when to mock:

```python
from typing import Literal

def should_mock_component(
    component_type: str,
    context: Literal["unit", "integration"] = "unit"
) -> tuple[bool, str]:
    """Executable decision logic for mocking strategy.

    Returns: (should_mock, reason)

    Example:
        should_mock, reason = should_mock_component("network")
        # Returns: (True, "External dependency - mock at system boundary")
    """
    # External boundaries - always mock
    external_systems = {
        "file_system", "network", "database", "external_api",
        "subprocess", "http_client", "smtp_server"
    }
    if component_type in external_systems:
        return (True, "External dependency - mock at system boundary")

    # Time/randomness - mock for determinism
    non_deterministic = {"datetime", "random", "time", "uuid"}
    if component_type in non_deterministic:
        return (True, "Non-deterministic - mock for reproducibility")

    # Hardware - mock unless integration testing
    hardware = {"gpu", "cuda", "system_resources", "display"}
    if component_type in hardware:
        if context == "integration":
            return (False, "Integration test - use real hardware")
        return (True, "Hardware dependency - mock for portability")

    # Qt widgets - use real components with qtbot
    qt_components = {"qt_widget", "qt_dialog", "qt_model", "qt_view"}
    if component_type in qt_components:
        return (False, "Qt component - use real with qtbot fixtures")

    # Business logic - never mock
    if context == "business_logic" or component_type in {"algorithm", "calculation", "validation"}:
        return (False, "Core logic - test real implementation")

    # Data structures - use real
    if component_type in {"list", "dict", "dataclass", "model"}:
        return (False, "Simple data structure - use real")

    # Default: prefer real components
    return (False, "Default to real components for better integration confidence")


# Usage examples:
should_mock, reason = should_mock_component("network")
# (True, "External dependency - mock at system boundary")

should_mock, reason = should_mock_component("qt_widget")
# (False, "Qt component - use real with qtbot fixtures")

should_mock, reason = should_mock_component("gpu", context="integration")
# (False, "Integration test - use real hardware")
```

### When to Mock
1. **External Systems**: File systems, networks, databases
2. **Time Dependencies**: datetime.now(), time.sleep()
3. **Hardware**: GPU detection, system resources
4. **Expensive Operations**: Large file processing, network calls

### When NOT to Mock
1. **Business Logic**: Core application algorithms
2. **Qt Components**: Use real widgets with qtbot
3. **Data Structures**: Lists, dicts, custom classes
4. **Simple Dependencies**: Math operations, string processing

### Mock Examples
```python
# GOOD: Mock external system boundary
def test_shot_loading_handles_network_failure() -> None:
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("Network unreachable")

        shot_loader = ShotLoader()
        result = shot_loader.load_shots_from_server()

        assert result.success is False
        assert "network" in result.error_message.lower()

# GOOD: Mock time for deterministic testing
def test_cache_expiration() -> None:
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000

        cache = TTLCache(ttl_seconds=300)
        cache.set("key", "value")

        # Advance time past expiration
        mock_time.return_value = 1500
        assert cache.get("key") is None
```

## Performance Testing

### Memory Usage Testing
```python
def test_thumbnail_cache_memory_limit_respected(thumbnail_manager: ThumbnailManager) -> None:
    """Verify memory limits are enforced."""
    initial_memory = thumbnail_manager.memory_usage_bytes

    # Load thumbnails until near limit
    for i in range(100):
        thumbnail_manager.load_thumbnail(create_test_image(size_mb=1))

    final_memory = thumbnail_manager.memory_usage_bytes
    max_memory = thumbnail_manager.max_memory_bytes

    # Should stay within configured limit
    assert final_memory <= max_memory
    assert final_memory > initial_memory
```

### Timing and Performance
```python
def test_shot_loading_performance_acceptable() -> None:
    """Verify shot loading meets performance requirements."""
    shot_model = ShotModel()

    start_time = time.time()
    shot_model.load_shots(count=1000)
    end_time = time.time()

    load_time = end_time - start_time

    # Should load 1000 shots in under 5 seconds
    assert load_time < 5.0
    assert shot_model.shot_count == 1000
```

## Interpreting Test Failures

Understanding pytest output helps debug failures quickly.

### Common AssertionError Patterns

```
FAILED tests/test_cache.py::test_cache_set - AssertionError: assert None == 'value'
```
**Meaning:** `get()` returned `None` instead of expected `'value'`
**Likely causes:**
1. `set()` didn't actually store the value
2. Key mismatch (typo: `"key"` vs `"Key"`)
3. Cache was cleared between `set()` and `get()`

```
FAILED tests/test_shot.py::test_status - AssertionError: assert 'pending' == 'approved'
```
**Meaning:** Status is `'pending'` but test expected `'approved'`
**Likely causes:**
1. Status update method wasn't called
2. Update method has a bug
3. Test is checking wrong object

```
FAILED tests/test_list.py::test_count - AssertionError: assert 3 == 5
```
**Meaning:** Collection has 3 items but test expected 5
**Likely causes:**
1. Some items weren't added
2. Items were filtered out
3. Wrong collection being counted

### Common pytest Errors

```
ERROR tests/test_ui.py - fixture 'qtbot' not found
```
**Solution:** `uv add --dev pytest-qt`

```
ERROR collecting tests/test_shots.py - ModuleNotFoundError: No module named 'shotbot'
```
**Solution:** Ensure dependencies are installed: `uv sync` or fix `PYTHONPATH`

```
warning: no tests collected
```
**Likely causes:**
1. Wrong file naming (use `test_*.py` or `*_test.py`)
2. Wrong function naming (use `test_*`)
3. Tests are in wrong directory (check `testpaths` in `pyproject.toml`)

### Debugging Workflow

1. **Read the error message** - pytest shows the exact assertion that failed
2. **Check the line number** - jump directly to failing assertion
3. **Use `-vv` for more detail** - shows full diff for complex objects
4. **Use `--pdb` to debug** - drops into debugger on failure
5. **Use `-l` to show locals** - displays local variables at failure point

```bash
# Show full diff for failed assertions
uv run pytest -vv

# Drop into debugger on first failure
uv run pytest --pdb -x

# Show local variables on failure
uv run pytest -l
```

## Error Handling Testing

### Exception Testing with match Parameter

Use `match` to verify specific error messages with regex:

```python
import pytest

def test_invalid_shot_data_with_specific_message() -> None:
    """Test error handling with precise error message validation."""
    shot_model = ShotModel()
    invalid_data = {"missing_required_fields": True}

    # Use regex pattern to match error message
    with pytest.raises(
        ValidationError,
        match=r"required fields.*missing|missing.*required fields"
    ) as exc_info:
        shot_model.add_shot_data(invalid_data)

    # Access exception for additional checks
    assert exc_info.value.field_name == "name"
```

### Testing Exception Notes (Python 3.11+, PEP 678)

Modern Python supports adding contextual notes to exceptions:

```python
def test_exception_with_notes() -> None:
    """Test that exceptions include helpful context notes (PEP 678)."""
    shot_model = ShotModel()
    invalid_data = {"name": "sh010", "status": "invalid_status"}

    with pytest.raises(ValidationError) as exc_info:
        shot_model.add_shot_data(invalid_data)

    # Check exception notes added via exc.add_note()
    if hasattr(exc_info.value, '__notes__'):
        notes = exc_info.value.__notes__
        assert any("valid statuses" in note for note in notes)
        assert any("approved" in note or "pending" in note for note in notes)
```

### Parametrized Exception Testing

Test multiple error conditions efficiently:

```python
from typing import Any

@pytest.mark.parametrize("invalid_data,expected_exception", [
    ({"frames": -10}, ValueError),
    ({"status": "invalid"}, ValidationError),
    ({}, KeyError),
])
def test_various_error_conditions(
    invalid_data: dict[str, Any],
    expected_exception: type[Exception]
) -> None:
    """Test that different invalid data raises appropriate exceptions."""
    shot_model = ShotModel()
    with pytest.raises(expected_exception):
        shot_model.add_shot_data(invalid_data)
```

## Test Data Management

### Realistic Test Data
```python
# Use realistic data that matches production
SAMPLE_SHOT_DATA = [
    {
        "name": "sh010_comp_v003",
        "status": "approved",
        "frames": {"start": 1001, "end": 1120},
        "resolution": {"width": 2048, "height": 1556},
        "path": "/shows/test_show/sequences/seq010/shots/sh010",
    },
    # More realistic entries...
]
```

### Test Data Factories
```python
def create_test_shot(name=None, status="in_progress", frame_count=120):
    """Factory function for creating test shot data."""
    if name is None:
        name = f"test_shot_{uuid.uuid4().hex[:8]}"

    return {
        "name": name,
        "status": status,
        "frames": {"start": 1001, "end": 1001 + frame_count - 1},
        "path": f"/test/path/{name}",
        "created": datetime.now().isoformat(),
    }
```

## Recommended Pytest Plugins

Leverage the pytest ecosystem to enhance testing capabilities.

### Plugin Overview

| Plugin | Purpose | Priority | Installation |
|--------|---------|----------|--------------|
| **pytest-cov** | Code coverage reporting | ⭐ Essential | `uv add --dev pytest-cov` |
| **pytest-mock** | Enhanced mocking syntax | ⭐ Essential | `uv add --dev pytest-mock` |
| **pytest-qt** | Qt application testing | ⭐ Required for Qt | `uv add --dev pytest-qt` |
| **pytest-xdist** | Parallel test execution | Recommended | `uv add --dev pytest-xdist` |
| **pytest-benchmark** | Performance testing | Optional | `uv add --dev pytest-benchmark` |
| **pytest-timeout** | Prevent hanging tests | Optional | `uv add --dev pytest-timeout` |

### pytest-cov: Coverage Reporting

```bash
# Run with coverage
uv run pytest --cov=shotbot --cov-report=html --cov-report=term-missing
```

Configuration in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
addopts = [
    "--cov=shotbot",
    "--cov-report=html",
    "--cov-report=term-missing",
    "--cov-fail-under=80",  # Fail if coverage < 80%
]
```

### pytest-mock: Enhanced Mocking

Cleaner syntax than `unittest.mock`:

```python
from pytest_mock import MockerFixture

def test_with_mocker(mocker: MockerFixture) -> None:
    """Use pytest-mock for cleaner mocking syntax."""
    mock_get = mocker.patch("requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"data": "value"}

    result = fetch_data()
    assert result == {"data": "value"}
    mock_get.assert_called_once()
```

## Continuous Integration Considerations

### Test Isolation
- Each test should be completely independent
- No shared state between tests
- Proper setup and teardown for each test

### Resource Cleanup
```python
@pytest.fixture
def resource_manager():
    """Example of proper resource management in fixtures."""
    manager = ResourceManager()
    try:
        yield manager
    finally:
        manager.cleanup_all_resources()
```

### Deterministic Testing
- Use fixed seeds for random operations
- Mock time-dependent functionality
- Ensure tests pass consistently across environments

## Parallel Test Execution with pytest-xdist

Run tests faster using parallel execution: `uv run pytest -n auto`

### Critical Qt Patterns for Parallel Execution

**QApplication Isolation:**
```python
@pytest.fixture
def qapp(qapp, request):
    """Enhance qapp with worker-specific cleanup to prevent state leakage."""
    try:
        from xdist import is_xdist_worker
        in_worker = is_xdist_worker(request)
    except (ImportError, TypeError):
        in_worker = False

    yield qapp

    if in_worker:
        qapp.processEvents()
        QTimer.singleShot(0, lambda: None)
        qapp.processEvents()
```

**Dynamic Timeouts for Resource Contention:**
```python
def test_worker_operation(qtbot):
    try:
        from xdist import is_xdist_worker
        timeout = 60000 if is_xdist_worker(qtbot._request) else 30000
    except (ImportError, TypeError, AttributeError):
        timeout = 30000

    with qtbot.waitSignal(worker.finished, timeout=timeout):
        worker.start()
```

### Common Issues

| Issue | Solution |
|-------|----------|
| QApplication conflicts | Use enhanced `qapp` fixture above |
| Timeout failures in parallel only | Use dynamic timeouts |
| Shared state leaks | Use `tmp_path`, never share mutable fixtures |

### Best Practices

✅ **DO:** Use `tmp_path`, enhance `qapp` fixture, use dynamic timeouts
❌ **DON'T:** Share mutable state, use session-scoped Qt fixtures, rely on execution order

## Essential References

**Core Documentation:**
- **[Pytest Documentation](https://docs.pytest.org)** - Official pytest reference
- **[pytest-qt Documentation](https://pytest-qt.readthedocs.io/)** - Qt testing guide
- **[PySide6 Documentation](https://doc.qt.io/qtforpython-6/)** - Official PySide6 docs
- **[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)** - Python best practices

**Key PEPs:**
- **[PEP 484](https://peps.python.org/pep-0484/)** - Type Hints
- **[PEP 678](https://peps.python.org/pep-0678/)** - Exception Notes (Python 3.11+)

This guide incorporates best practices from these authoritative sources to ensure your ShotBot test suite follows industry standards and modern Python conventions.

---
*Version 2025.01 - Last updated: January 2025*
*Comprehensive testing guide for ShotBot VFX application pytest suite*