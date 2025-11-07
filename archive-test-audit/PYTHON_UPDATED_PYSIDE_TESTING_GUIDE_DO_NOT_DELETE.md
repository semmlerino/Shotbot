# Universal Python/PySide6 Testing Guide
*Optimized for LLM usage - Production-tested patterns with 2024+ best practices*

## 🚀 QUICK START

### What Are You Testing? (Decision Tree)
```
IF testing Qt widget → Jump to "Qt Widget Pattern" (line 85)
ELIF testing worker thread → Jump to "Worker Thread Pattern" (line 102)  
ELIF testing async operations → Jump to "Async Pattern" (line 138)
ELIF testing signals → Jump to "Signal Testing" (line 122)
ELIF testing file operations → Jump to "File Operations" (line 185)
ELIF testing with parameters → Jump to "Modern Parametrization" (line 165)
ELIF testing dialogs → Jump to "Dialog Testing" (line 205)
ELSE → Check Quick Lookup Table (line 380)
```

### Most Common Pattern (Copy & Paste)
```python
def test_widget(qtbot):
    widget = MyWidget()
    qtbot.addWidget(widget)  # CRITICAL: Register for cleanup
    
    qtbot.mouseClick(widget.button, Qt.LeftButton)
    assert widget.label.text() == "Expected"
```

### Factory Fixture Pattern (Modern Best Practice)
```python
@pytest.fixture
def make_model():
    """Factory fixture - returns a callable to create models with custom parameters."""
    def _make(name="test", size=100, **kwargs):
        return DataModel(name=name, size=size, **kwargs)
    return _make

def test_with_factory(make_model):
    # Create multiple instances with different parameters
    model1 = make_model()
    model2 = make_model(name="custom", size=200)
    model3 = make_model(name="special", enabled=False)
```

## 📋 CORE PRINCIPLES

### Three Fundamental Rules
1. **Test Behavior, Not Implementation**
   ❌ mock.assert_called_once()  # Who cares?
   ✅ assert result.success       # Actual outcome

2. **Real Components Over Mocks**
   ❌ controller = Mock(spec=Controller)
   ✅ controller = Controller(test_backend=TestBackend())

3. **Mock Only at System Boundaries**
   - External APIs, Network calls
   - Subprocess calls
   - System time
   - NOT internal methods

### Mocking Decision Algorithm
```
FOR each dependency:
    IF crosses process boundary → Mock/TestDouble
    ELIF network/external API → Mock
    ELIF database → Use test database or in-memory
    ELIF Qt widget/signal → Use real with qtbot
    ELIF internal method → Use real
```

## 🎯 COMMON PATTERNS

### Unit Test Pattern
```python
def test_pure_logic():
    # No mocks needed for pure functions
    result = calculate_something(input_data)
    assert result == expected
```

### Qt Widget Pattern
```python
def test_widget(qtbot):
    widget = MyWidget()
    qtbot.addWidget(widget)  # CRITICAL: Always register widgets
    widget.show()
    qtbot.waitExposed(widget, timeout=5000)  # Wait for widget to be visible
    
    # Modern signal waiting (set up BEFORE triggering)
    with qtbot.waitSignal(widget.finished, timeout=5000):
        widget.start_operation()
    
    # Condition waiting (2024+)
    qtbot.waitUntil(lambda: widget.isReady(), timeout=5000)
    
    # Custom cleanup function (optional)
    def cleanup(w):
        w.cancel_operation()
        print(f"Cleaned up {w.__class__.__name__}")
    
    qtbot.addWidget(complex_widget, before_close_func=cleanup)
```

### Worker Thread Pattern (CRITICAL - Thread Safety)
```python
def test_worker(qtbot):
    # ⚠️ NEVER use QPixmap in worker threads!
    worker = ImageWorker()
    
    # Use QImage for thread-safe image operations
    image = QImage(100, 100, QImage.Format.Format_RGB32)
    worker.set_image(image)
    
    with qtbot.waitSignal(worker.finished):
        worker.start()
    
    # Cleanup
    if worker.isRunning():
        worker.quit()
        worker.wait(1000)
```

### Signal Testing Pattern
```python
# Parameter checking with callback (2024+)
def check_progress_complete(percentage):
    """Only accept signal if progress is 100%"""
    return percentage == 100

with qtbot.waitSignal(worker.progress_updated, 
                     check_params_cb=check_progress_complete,
                     timeout=10000):
    worker.start_long_task()

# Multiple signals with parameter validation
def check_status_50(status):
    return status == 50

def check_status_100(status):
    return status == 100

signals = [worker.status_changed, worker.status_changed, worker.finished]
callbacks = [check_status_50, check_status_100, None]

with qtbot.waitSignals(signals, check_params_cbs=callbacks, timeout=15000):
    worker.start_process()

# Negative testing with asynchronous wait (2024+)
with qtbot.assertNotEmitted(worker.error_occurred, wait=500):
    worker.safe_operation()

# Access signal arguments after emission
with qtbot.waitSignal(data_loader.data_ready) as blocker:
    data_loader.load("test_file.json")

# Check what arguments were passed
data = blocker.args[0]  # First argument
assert isinstance(data, dict)
assert "key" in data
```

### Async Operations Pattern
```python
def test_async_operation(qtbot):
    loader = AsyncDataLoader()
    
    # Use QSignalSpy for detailed signal inspection
    spy = QSignalSpy(loader.data_loaded)
    
    with qtbot.waitSignal(loader.data_loaded, timeout=5000) as blocker:
        loader.load_data()
    
    # Modern approach: use blocker for signal info
    assert blocker.signal_triggered
    data = blocker.args[0]  # More intuitive than spy.at(0)[0]
    assert len(data) > 0
    
    # QSignalSpy still useful for multiple emissions
    assert spy.count() == 1
    # CRITICAL: Use count()-1, never negative indexing (causes segfault)
    last_signal = spy.at(spy.count() - 1)
    assert last_signal[0] == data

def test_callback_based_async(qtbot):
    """Test async operations that use callbacks instead of signals"""
    api_client = AsyncAPIClient()
    
    with qtbot.waitCallback() as callback:
        api_client.fetch_data(callback=callback)
    
    # Verify callback was called with expected data
    callback.assert_called_with({"status": "success", "data": []})
```

### Modern Parametrization (2024+)
```python
# Basic parametrization with descriptive IDs
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (3, 4),
], ids=["simple_case", "another_case"])

# Advanced with marks and custom IDs
@pytest.mark.parametrize("count,expected", [
    (10, True),
    pytest.param(1000, True, marks=pytest.mark.slow, id="large_dataset"),
    pytest.param(50000, True, marks=[pytest.mark.slow, pytest.mark.stress], id="stress_test"),
])

# Indirect fixture parametrization
@pytest.fixture
def database(request):
    """Fixture that creates different database types based on parameter"""
    db_type = request.param
    if db_type == "sqlite":
        return SQLiteDB(":memory:")
    elif db_type == "postgres":
        return PostgresDB("postgresql://localhost/test")
    raise ValueError(f"Unknown database type: {db_type}")

@pytest.mark.parametrize("database", ["sqlite", "postgres"], indirect=True)
def test_database_operations(database):
    """Test runs twice: once with SQLite, once with PostgreSQL"""
    result = database.query("SELECT 1 as test")
    assert result[0]["test"] == 1

# Conditional parametrization with skip marks
@pytest.mark.parametrize("platform,command", [
    ("linux", "ls"),
    pytest.param("windows", "dir", 
                marks=pytest.mark.skipif(sys.platform != "win32", 
                                        reason="Windows-only test")),
])
def test_platform_specific(platform, command):
    result = subprocess.run(command, shell=True, capture_output=True)
    assert result.returncode == 0
```

### Fixture Scope Optimization (NEW)
```python
@pytest.fixture(scope="session")  # Expensive, reuse
def database():
    return setup_test_database()

@pytest.fixture(scope="function")  # Default, isolated
def test_data():
    return {"key": "value"}
```

### File Operations Pattern
```python
def test_file_operations(tmp_path):
    """tmp_path is a pathlib.Path object (preferred over tmpdir)"""
    # Create test files with pathlib
    config_file = tmp_path / "config.json"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    config_file.write_text('{"setting": "value"}')
    (data_dir / "sample.txt").write_text("test data")
    
    # Test your file operations
    result = process_directory(tmp_path)
    assert result.success
    assert result.files_processed == 1
    
    # Verify output files were created
    output_file = tmp_path / "output.json"
    assert output_file.exists()
    
    # tmp_path is automatically cleaned up after test

# Session-scoped temporary directory for expensive setup
@pytest.fixture(scope="session")
def shared_test_data(tmp_path_factory):
    """Create shared test data that persists across all tests in session"""
    shared_dir = tmp_path_factory.mktemp("shared")
    large_file = shared_dir / "large_dataset.csv"
    
    # Create expensive test data once
    with large_file.open("w") as f:
        for i in range(10000):
            f.write(f"row{i},data{i}\n")
    
    return shared_dir
```

### Dialog Testing Pattern (2024+)
```python
def test_dialog_with_mock(qtbot, monkeypatch):
    """Mock dialog interactions for predictable testing"""
    from PySide6.QtWidgets import QMessageBox, QFileDialog
    
    # Mock QMessageBox.question to always return Yes
    monkeypatch.setattr(QMessageBox, "question", 
                       lambda parent, title, text, buttons, default: QMessageBox.Yes)
    
    # Mock QFileDialog.getOpenFileName to return test file
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                       lambda parent, title, dir, filter: ("/test/file.txt", "Text files (*.txt)"))
    
    widget = FileProcessor()
    qtbot.addWidget(widget)
    
    # Test dialog-dependent functionality
    widget.open_file_button.click()  # Would normally show file dialog
    assert widget.current_file == "/test/file.txt"
    
    widget.confirm_action_button.click()  # Would normally show confirmation
    assert widget.action_confirmed

# Custom dialog testing
class CustomDialog(QDialog):
    @classmethod
    def ask_user_input(cls, parent=None, title="Input", label="Enter value:"):
        """Convenience method for easier testing"""
        dialog = cls(parent)
        dialog.setWindowTitle(title)
        dialog.label.setText(label)
        if dialog.exec() == QDialog.Accepted:
            return dialog.input_field.text()
        return None

def test_custom_dialog(qtbot, monkeypatch):
    # Mock the convenience method
    monkeypatch.setattr(CustomDialog, "ask_user_input", 
                       lambda *args, **kwargs: "test_input")
    
    form = UserForm()
    qtbot.addWidget(form)
    
    form.get_input_button.click()
    assert form.user_input == "test_input"
```

### Integration Test Pattern
```python
def test_workflow_integration(qtbot, tmp_path):
    # Use real components with test doubles at boundaries
    model = DataModel()
    view = DataView()
    controller = Controller(model, view)
    
    # Only mock external dependencies
    controller.api_client = MockAPIClient()
    controller.file_system = tmp_path
    
    # Test real behavior
    with qtbot.waitSignal(controller.workflow_complete):
        controller.start_workflow()
    
    assert model.state == "completed"
    assert view.status_label.text() == "Success"
```

## ⚠️ CRITICAL RULES

### Qt Threading Rule (FATAL if violated)
**QPixmap = Main Thread ONLY | QImage = Any Thread**

❌ **CRASHES PYTHON**:
```python
def worker():
    pixmap = QPixmap(100, 100)  # Fatal Python error: Aborted
threading.Thread(target=worker).start()
```

✅ **SAFE**:
```python
def worker():
    image = QImage(100, 100, QImage.Format.Format_RGB32)
threading.Thread(target=worker).start()
```

### Signal Race Conditions
❌ **RACE CONDITION**:
```python
worker.start()  # Signal might emit before setup!
with qtbot.waitSignal(worker.started):
    pass
```

✅ **SAFE**:
```python
with qtbot.waitSignal(worker.started):
    worker.start()  # Signal captured correctly
```

### QSignalSpy Indexing
❌ **SEGFAULT**:
```python
# QSignalSpy doesn't support negative indexing!
signal_data = spy.at(-1)  # Segmentation fault in Qt
```

✅ **SAFE**:
```python
# Use count() - 1 for last signal
signal_data = spy.at(spy.count() - 1)
```

### Qt Container Truthiness
❌ **BUG**:
```python
if self.layout:  # False for empty QVBoxLayout!
    self.layout.addWidget(widget)
```

✅ **CORRECT**:
```python
if self.layout is not None:
    self.layout.addWidget(widget)
```

### Never Mock Class Under Test
❌ **POINTLESS**:
```python
controller = Mock(spec=Controller)
controller.process.return_value = "result"
# Testing the mock, not the controller!
```

✅ **MEANINGFUL**:
```python
controller = Controller(backend=TestBackend())
result = controller.process()
assert result == expected
```

### QApplication Singleton
❌ **MULTIPLE QAPP INSTANCES**:
```python
def test_something():
    app = QApplication([])  # Error if app already exists!
```

✅ **SAFE**:
```python
def test_something(qapp):  # pytest-qt provides qapp fixture
    # Use existing QApplication instance
    assert qapp is not None

# Custom QApplication for testing
@pytest.fixture(scope="session")
def qapp_cls():
    """Override to use custom QApplication subclass"""
    class TestApplication(QApplication):
        def __init__(self, *args):
            super().__init__(*args)
            self.test_mode = True
            self.theme = "dark"
        
        def custom_method(self):
            return "test_result"
    
    return TestApplication

def test_custom_app(qapp):
    assert qapp.test_mode is True
    assert qapp.custom_method() == "test_result"
```

## 🎯 MODERN PATTERNS (2024+)

### Debugging with Screenshots
```python
def test_visual_component(qtbot):
    widget = ComplexVisualizationWidget()
    qtbot.addWidget(widget)
    widget.load_data([1, 2, 3, 4, 5])
    
    # Take screenshot for debugging
    screenshot_path = qtbot.screenshot(widget, suffix="after_load")
    
    # Assert visual elements
    assert widget.chart.isVisible()
    
    # On failure, screenshot path is shown for manual inspection
    if not widget.chart.hasData():
        pytest.fail(f"Chart has no data. Screenshot: {screenshot_path}")
```

### Qt Logging Configuration
```python
# In pytest.ini
[pytest]
qt_api = pyside6
qt_log_level_fail = CRITICAL  # Fail tests on critical Qt messages
qt_log_ignore =
    .*destroyed while thread.*
    QApplication: invalid style override.*

# In test files
@pytest.mark.qt_log_ignore("Custom warning pattern", extend=True)
def test_with_expected_warnings(qtbot):
    # Test that might emit expected Qt warnings
    pass

@pytest.mark.qt_log_level_fail("WARNING")
def test_strict_logging(qtbot):
    # This test will fail on any Qt WARNING or above
    pass

# Programmatic log checking
def test_qt_messages(qtbot, qtlog):
    widget = MyWidget()
    qtbot.addWidget(widget)
    
    widget.trigger_warning()  # Emits Qt warning
    
    # Check captured messages
    assert len(qtlog.records) == 1
    assert "expected warning" in qtlog.records[0].message
```

### Advanced Worker Thread Testing
```python
from PySide6.QtCore import QThread, QObject, Signal

class DataProcessor(QObject):
    progress_updated = Signal(int)
    data_ready = Signal(object)
    error_occurred = Signal(str)
    
    def process_data(self, data):
        try:
            for i, item in enumerate(data):
                # Simulate processing
                processed = self.process_item(item)
                progress = int((i + 1) / len(data) * 100)
                self.progress_updated.emit(progress)
            
            self.data_ready.emit(processed_data)
        except Exception as e:
            self.error_occurred.emit(str(e))

def test_worker_success_path(qtbot):
    """Test successful data processing with progress tracking"""
    processor = DataProcessor()
    thread = QThread()
    processor.moveToThread(thread)
    
    # Track progress updates
    progress_values = []
    processor.progress_updated.connect(progress_values.append)
    
    # Wait for completion
    with qtbot.waitSignal(processor.data_ready, timeout=10000) as blocker:
        thread.started.connect(lambda: processor.process_data([1, 2, 3, 4]))
        thread.start()
    
    # Verify results
    result = blocker.args[0]
    assert result is not None
    assert progress_values == [25, 50, 75, 100]
    
    # Clean up
    thread.quit()
    thread.wait(5000)

def test_worker_error_handling(qtbot):
    """Test error handling in worker thread"""
    processor = DataProcessor()
    thread = QThread()
    processor.moveToThread(thread)
    
    # Expect error signal
    with qtbot.waitSignal(processor.error_occurred, timeout=5000) as blocker:
        thread.started.connect(lambda: processor.process_data(None))  # Invalid data
        thread.start()
    
    # Verify error message
    error_msg = blocker.args[0]
    assert "cannot process None" in error_msg.lower()
    
    # Clean up
    thread.quit()
    thread.wait(5000)
```

## 📊 QUICK REFERENCE

### Lookup Table
| Scenario | Solution |
|----------|----------|
| Testing Qt widgets | qtbot fixture with addWidget() |
| Testing worker threads | QThread with proper cleanup + waitSignal |
| Testing async operations | qtbot.waitSignal with check_params_cb |
| Testing signal emission | waitSignal BEFORE action (avoid race conditions) |
| Testing conditions | qtbot.waitUntil() |
| Testing file operations | tmp_path fixture (pathlib.Path) |
| Testing with database | Test database or in-memory |
| Testing network calls | Mock at boundary only |
| Testing timers | qtbot.wait() or time mock |
| Testing dialogs | Mock exec() return value or convenience methods |
| Testing callbacks | qtbot.waitCallback() |
| Visual debugging | qtbot.screenshot() |
| Qt log messages | qtlog fixture + qt_log_level_fail config |
| Custom QApplication | Override qapp_cls fixture |
| Parametrized tests | pytest.param with marks and IDs |
| Factory fixtures | _make pattern with **kwargs |

### Complete Marker Strategy (2024+)
```python
# In pytest.ini
[pytest]
markers =
    unit: Pure logic tests without Qt dependencies
    integration: Component integration tests
    qt: Qt-specific tests requiring qtbot
    gui: Tests requiring display (may fail in headless environment)
    slow: Tests taking >1 second
    performance: Benchmark and performance tests
    stress: Load and stress tests with large datasets
    flaky: Known intermittent issues (use sparingly)
    network: Tests requiring network access
    database: Tests requiring database connection
    external: Tests requiring external services
    windows: Windows-specific tests
    linux: Linux-specific tests
    macos: macOS-specific tests
    smoke: Critical functionality smoke tests
    regression: Tests for specific bug fixes

# In conftest.py - auto-apply markers based on test names
def pytest_collection_modifyitems(config, items):
    for item in items:
        # Auto-mark Qt tests
        if "qtbot" in item.fixturenames:
            item.add_marker("qt")
        
        # Auto-mark based on test name patterns
        if "test_performance" in item.name or "benchmark" in item.name:
            item.add_marker("performance")
        if "integration" in item.name:
            item.add_marker("integration")
        if "gui" in item.name or "visual" in item.name:
            item.add_marker("gui")
```

### Essential Fixtures (2024+)
```python
# Built-in pytest-qt fixtures
@pytest.fixture
def qtbot(): ...           # Qt test interface with widget management
@pytest.fixture
def qapp(): ...            # QApplication instance
@pytest.fixture
def qtlog(): ...           # Qt message logging capture
@pytest.fixture
def qtmodeltester(): ...   # QAbstractItemModel testing

# Built-in pytest fixtures
@pytest.fixture
def tmp_path(): ...        # Temp directory (pathlib.Path)
@pytest.fixture
def monkeypatch(): ...     # Modify attributes and methods
@pytest.fixture
def caplog(): ...          # Capture Python logging output
@pytest.fixture
def capsys(): ...          # Capture stdout/stderr

# Custom application fixtures
@pytest.fixture(scope="session")
def qapp_cls():
    """Override to use custom QApplication subclass"""
    return QApplication  # Default

@pytest.fixture(scope="session")
def qapp_args():
    """Arguments passed to QApplication constructor"""
    return []  # Default empty args

# Performance optimization fixtures
@pytest.fixture(scope="session")
def expensive_database_setup(): 
    """Session-scoped for expensive setup"""
    pass

@pytest.fixture(scope="module") 
def shared_widget_config():
    """Module-scoped for shared test configuration"""
    pass
```

### Commands (2024+)
```bash
# Basic test execution
pytest                              # Run all tests
pytest -v                          # Verbose output
pytest -s                          # Show print statements
pytest -x                          # Stop on first failure

# Marker-based filtering
pytest -m "not slow"               # Skip slow tests
pytest -m "qt and not gui"         # Qt tests that don't need display
pytest -m "unit or integration"    # Multiple marker selection
pytest -m "smoke"                  # Run only smoke tests

# Performance and parallel execution
pytest -n auto                     # Parallel execution (pytest-xdist)
pytest -n 4                        # Use 4 CPU cores
pytest --dist=worksteal            # Advanced load balancing

# Coverage reporting
pytest --cov=src --cov-report=html --cov-report=term
pytest --cov-fail-under=80         # Fail if coverage below 80%

# Qt-specific options
pytest --qt-api=pyside6            # Force specific Qt binding
pytest --no-qt-log                 # Disable Qt log capture

# Debugging and development
pytest --lf                        # Run last failed tests
pytest --ff                        # Run failed tests first
pytest --tb=short                  # Shorter tracebacks
pytest --tb=line                   # Single line tracebacks
pytest --pdb                       # Drop into debugger on failure
pytest --pdbcls=IPython.terminal.debugger:Pdb  # Use IPython debugger

# Test discovery and collection
pytest --collect-only              # Show what tests would run
pytest --co -q                     # Quiet collection output

# CI/CD optimizations
pytest --maxfail=3                 # Stop after 3 failures
pytest --duration=10               # Show 10 slowest tests
pytest --strict-markers            # Fail on unknown markers
```

## 📚 APPENDIX

### Test Doubles Library
```python
class TestBackend:
    """Generic test double for backend services"""
    
    __test__ = False  # CRITICAL: Prevents pytest collection warning
    
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.should_fail = False
    
    def set_response(self, method, response):
        self.responses[method] = response
    
    def call(self, method, *args, **kwargs):
        self.calls.append((method, args, kwargs))
        if self.should_fail:
            raise Exception("Test failure")
        return self.responses.get(method, None)

class TestSignal:
    """Lightweight signal double for non-Qt code"""
    def __init__(self):
        self.emissions = []
        self.callbacks = []
    
    def emit(self, *args):
        self.emissions.append(args)
        for callback in self.callbacks:
            callback(*args)
    
    def connect(self, callback):
        self.callbacks.append(callback)
    
    @property
    def was_emitted(self):
        return len(self.emissions) > 0

class ThreadSafeTestImage:
    """Thread-safe image for testing"""
    def __init__(self, width=100, height=100):
        self._image = QImage(width, height, QImage.Format.Format_RGB32)
        self._image.fill(QColor(255, 255, 255))
    
    def size(self):
        return self._image.size()
    
    def isNull(self):
        return self._image.isNull()
```

### CI/CD Setup for Headless Testing
```yaml
# GitHub Actions example
name: Qt Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.8", "3.9", "3.10", "3.11", "3.12"]
        qt-version: ["pyside6", "pyqt6"]
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Install Qt dependencies (Linux)
      run: |
        sudo apt-get update
        sudo apt-get install -y \
          xvfb libxkbcommon-x11-0 libxcb-icccm4 \
          libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
          libxcb-render-util0 libxcb-xinerama0 libxcb-xinput0 \
          libxcb-xfixes0 libxcb-shape0 libgl1-mesa-dev
    
    - name: Install Python dependencies
      run: |
        python -m pip install --upgrade pip
        pip install ${{ matrix.qt-version }}
        pip install pytest pytest-qt pytest-cov pytest-xdist
        pip install -r requirements.txt
    
    - name: Run tests with virtual display
      run: |
        export DISPLAY=:99
        Xvfb :99 -screen 0 1920x1200x24 > /dev/null 2>&1 &
        sleep 3
        pytest tests/ -v --qt-api=${{ matrix.qt-version }} \
          --cov=src --cov-report=xml -n auto
      env:
        PYTHONFAULTHANDLER: 1
        QT_QPA_PLATFORM: offscreen
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
```

### Common Issues & Solutions
| Issue | Solution |
|-------|----------|
| "Fatal Python error: Aborted" | Using QPixmap in thread - use QImage |
| Collection warnings | Classes starting with Test need `__test__ = False` |
| Signal not received | Set up waitSignal before triggering |
| Empty Qt container is falsy | Use `is not None` check |
| Tests hang | Add timeout to waitSignal/waitUntil |
| Mock everything pattern | Use real components with test doubles at boundaries |
| QSignalSpy segfault | Use `spy.at(spy.count() - 1)` not `spy.at(-1)` |
| Multiple QApplication | Use qapp fixture from pytest-qt |
| Resource warnings | Ensure proper cleanup in teardown |

### pytest-qt Configuration
```python
# conftest.py
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def qapp_args():
    """Arguments for QApplication"""
    return []

@pytest.fixture(scope="session")
def qapp(qapp_args):
    """Session-wide QApplication"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(qapp_args)
    yield app
    app.quit()
```

### Testing Best Practices (2024+)
1. **AAA Pattern**: Arrange, Act, Assert - clear test structure
2. **Descriptive test names**: `test_user_profile_updates_when_save_button_clicked`
3. **One concept per test**: Test one behavior, not multiple
4. **Fast by default**: Use marks for slow tests, optimize for quick feedback
5. **Deterministic**: No random values, fixed time, predictable behavior
6. **Independent**: Tests should not depend on each other's state
7. **Maintainable**: Use factory fixtures, avoid code duplication
8. **Realistic**: Test real user workflows, not just unit functions
9. **Error cases**: Test unhappy paths, edge cases, and error conditions
10. **Documentation**: Test names and factory fixtures are documentation
11. **Clean up**: Always register Qt widgets with qtbot.addWidget()
12. **Signal testing**: Set up waitSignal BEFORE triggering actions
13. **Thread safety**: Use QImage in threads, never QPixmap
14. **Debugging**: Use qtbot.screenshot() for visual debugging
15. **Configuration**: Use pytest.ini for consistent test environment

### Anti-Patterns Summary (2024+)
```python
# ❌ These will cause problems:
threading.Thread(target=lambda: QPixmap(100, 100)).start()  # CRASHES PYTHON
spy = QSignalSpy(mock.signal)                               # TypeError with mocks
if self.layout:                                             # Falsy when empty
worker.start(); with qtbot.waitSignal(worker.signal): pass # Race condition
with qtbot.waitSignal(s, timeout=1000): pass               # Missing action
controller = Mock(spec=Controller)                          # Testing mock not code
mock.assert_called_once()                                   # Testing implementation
spy.at(-1)                                                  # Segfault in Qt
class TestHelper:  # without __test__ = False              # Collection warning
app = QApplication([])                                      # Multiple instances
widget = MyWidget(); widget.show()  # No qtbot.addWidget   # Resource leak
qtbot.waitSignal(s).connect(other_s)  # Wrong syntax       # API misuse
pytest.param(val, mark=pytest.mark.slow)  # Wrong syntax   # Use marks=[...]

# ✅ Use these instead:
QImage(100, 100, QImage.Format.Format_RGB32)               # Thread-safe
QSignalSpy(real_widget.real_signal)                        # Real signals only
if self.layout is not None:                                # Explicit check
with qtbot.waitSignal(signal): worker.start()              # Signal setup first
with qtbot.waitSignal(s): trigger_action()                 # Include action
Controller(backend=TestBackend())                          # Real with test doubles
assert result.success                                       # Test behavior
spy.at(spy.count() - 1)                                   # Safe indexing
class TestHelper: __test__ = False                         # Prevent collection
qapp fixture from pytest-qt                                # Singleton QApp
widget = MyWidget(); qtbot.addWidget(widget)               # Proper registration
with qtbot.waitSignal(s) as blocker: blocker.connect(other_s)  # Correct API
pytest.param(val, marks=[pytest.mark.slow])               # Use marks list

# ❌ Outdated patterns (pre-2024):
tmpdir instead of tmp_path                                  # Use pathlib.Path
qtbot.waitForWindowShown()                                 # Use qtbot.waitExposed()
SignalTimeoutError                                          # Use qtbot.TimeoutError
qt_wait_signal_raising config                              # Use qt_default_raising
@pytest.mark.usefixtures in fixture                        # Deprecated pattern
```

### Testing Checklist (2024+)
**Pre-Test Setup:**
- [ ] Configure pytest.ini with qt_api, markers, and log settings
- [ ] Set up conftest.py with shared fixtures and marker auto-application
- [ ] Install pytest-qt, pytest-xdist for parallel execution
- [ ] Configure CI/CD with xvfb for headless testing

**Writing Tests:**
- [ ] Use descriptive test names that explain the behavior being tested
- [ ] Use factory fixtures with `_make` pattern for flexible test data
- [ ] Prefer `tmp_path` (pathlib.Path) over deprecated `tmpdir`
- [ ] Use `pytest.param` with marks and IDs for clear parametrization
- [ ] Mock only at system boundaries (external APIs, databases, network)
- [ ] Use real components internally with test doubles for dependencies

**Qt-Specific Rules:**
- [ ] ALWAYS use `qtbot.addWidget()` for ALL widgets (critical for cleanup)
- [ ] Set up `qtbot.waitSignal()` BEFORE triggering actions (avoid race conditions)
- [ ] Use QImage instead of QPixmap in worker threads (prevents crashes)
- [ ] Check `is not None` for Qt containers (they're falsy when empty)
- [ ] Use `qtbot.waitUntil()` for condition-based waiting
- [ ] Use `check_params_cb` for signal parameter validation
- [ ] Take screenshots with `qtbot.screenshot()` for visual debugging
- [ ] Configure Qt logging with `qt_log_level_fail` and `qt_log_ignore`

**QSignalSpy Safety:**
- [ ] Use `spy.at(spy.count() - 1)` not `spy.at(-1)` (prevents segfault)
- [ ] Only use QSignalSpy with real Qt signals, never mocks
- [ ] Prefer `blocker.args` over QSignalSpy for single signal testing

**Thread and Resource Management:**
- [ ] Clean up QThreads with `quit()` and `wait(timeout)`
- [ ] Add `__test__ = False` to test helper classes
- [ ] Use session/module scoped fixtures for expensive setup
- [ ] Use `before_close_func` for custom widget cleanup

**Testing Patterns:**
- [ ] Test behavior and outcomes, not implementation details
- [ ] Include error cases and edge conditions
- [ ] Use appropriate markers: unit, integration, qt, slow, gui, etc.
- [ ] Make tests deterministic (no random values, fixed time)
- [ ] Keep tests independent (no shared state between tests)

**Modern Best Practices:**
- [ ] Use `qtbot.waitCallback()` for callback-based async operations
- [ ] Mock dialogs using `monkeypatch` with convenience methods
- [ ] Use `qtlog` fixture for programmatic log message checking
- [ ] Override `qapp_cls` fixture for custom QApplication testing
- [ ] Use `indirect=True` parametrization for fixture-based test variations

---

*This guide provides universal testing patterns for Python/PySide6 applications. Use the decision tree and lookup table to quickly find the right approach for your testing scenario.*

**Key Features**:
- Zero project-specific references
- Universal patterns applicable to any PySide6 project
- Production-tested anti-patterns and solutions
- LLM-optimized with line numbers and decision trees
- Modern pytest patterns (factory fixtures, parametrization, markers)
- 2024+ best practices from pytest and pytest-qt documentation

*Last Updated: 2025-02-01 | Enhanced with latest pytest and pytest-qt patterns*