# Universal Python/PySide6 Testing Guide
*Optimized for LLM usage - Production-tested patterns*

## 🚀 QUICK START

### What Are You Testing? (Decision Tree)
```
IF testing Qt widget → Jump to "Qt Widget Pattern" (line 80)
ELIF testing worker thread → Jump to "Worker Thread Pattern" (line 96)  
ELIF testing async operations → Jump to "Async Pattern" (line 130)
ELIF testing signals → Jump to "Signal Testing" (line 115)
ELIF testing file operations → Jump to "File Operations" (line 175)
ELSE → Check Quick Lookup Table (line 320)
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
    def _make(name="test", size=100):
        return DataModel(name=name, size=size)
    return _make

def test_with_factory(make_model):
    model1 = make_model()
    model2 = make_model(name="custom", size=200)
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
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    
    # Modern signal waiting
    with qtbot.waitSignal(widget.finished, timeout=1000):
        widget.start_operation()
    
    # Condition waiting (NEW)
    qtbot.waitUntil(lambda: widget.isReady(), timeout=1000)
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
# Modern parameter checking (NEW)
def check_value(val):
    return val > 100

with qtbot.waitSignal(signal, check_params_cb=check_value):
    trigger_action()

# Negative testing with wait (NEW)
with qtbot.assertNotEmitted(signal, wait=100):
    other_action()
```

### Async Operations Pattern
```python
def test_async_operation(qtbot):
    loader = AsyncDataLoader()
    
    # Use QSignalSpy for detailed signal inspection
    spy = QSignalSpy(loader.data_loaded)
    
    with qtbot.waitSignal(loader.data_loaded, timeout=5000):
        loader.load_data()
    
    # Check signal parameters
    assert spy.count() == 1
    data = spy.at(0)[0]  # First argument of first emission
    assert len(data) > 0
```

### Parametrization Patterns (Modern)
```python
# Basic parametrization
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (3, 4),
])
def test_calculation(input, expected):
    assert process(input) == expected

# With marks (NEW)
@pytest.mark.parametrize("count,expected", [
    (10, True),
    pytest.param(1000, True, marks=pytest.mark.slow),
])
def test_performance(count, expected):
    result = heavy_operation(count)
    assert result == expected

# Indirect fixture parametrization (NEW)
@pytest.mark.parametrize("backend", ["sqlite", "postgres"], indirect=True)
def test_with_backend(backend):
    assert backend.is_connected()
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
    # tmp_path is a pathlib.Path object
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")
    
    # Test your file operations
    result = process_file(test_file)
    assert result.success
    
    # tmp_path is automatically cleaned up
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
```

## 📊 QUICK REFERENCE

### Lookup Table
| Scenario | Solution |
|----------|----------|
| Testing Qt widgets | qtbot fixture with addWidget() |
| Testing worker threads | QThread with proper cleanup |
| Testing async operations | QSignalSpy + waitSignal |
| Testing signal emission | waitSignal BEFORE action |
| Testing conditions | qtbot.waitUntil() |
| Testing file operations | tmp_path fixture |
| Testing with database | Test database or in-memory |
| Testing network calls | Mock at boundary only |
| Testing timers | qtbot.wait() or time mock |
| Testing dialogs | Mock exec() return value |

### Complete Marker Strategy
```python
# In pytest.ini or conftest.py
markers = [
    "unit: Pure logic tests",
    "integration: Component integration",
    "qt: Qt-specific tests",
    "slow: Tests >1s",
    "performance: Benchmark tests", 
    "stress: Load tests",
    "gui: Requires display",
    "flaky: Known intermittent issues",
]
```

### Essential Fixtures
```python
@pytest.fixture
def qtbot(): ...           # Qt test interface
@pytest.fixture
def qapp(): ...            # QApplication instance
@pytest.fixture
def tmp_path(): ...        # Temp directory (pathlib.Path)
@pytest.fixture
def monkeypatch(): ...     # Modify attributes
@pytest.fixture
def caplog(): ...          # Capture log output
@pytest.fixture(scope="session")
def expensive_setup(): ... # Session-scoped
```

### Commands
```bash
# Run tests
pytest

# Fast tests only
pytest -m "not slow"

# With coverage
pytest --cov=. --cov-report=html

# Parallel execution
pytest -n auto

# Stop on first failure
pytest -x

# Run last failed
pytest --lf

# Verbose output
pytest -v

# Show print statements
pytest -s
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

### Testing Best Practices
1. **AAA Pattern**: Arrange, Act, Assert
2. **One assertion per test** (when practical)
3. **Descriptive test names**: `test_widget_emits_signal_on_button_click`
4. **Use fixtures for setup**: Don't repeat setup code
5. **Test edge cases**: Empty, None, boundaries
6. **Test error conditions**: Invalid input, exceptions
7. **Keep tests fast**: Mock slow operations
8. **Make tests deterministic**: No random, no time-dependent
9. **Test public API**: Not implementation details
10. **Document why, not what**: Comments for complex test logic

### Anti-Patterns Summary
```python
# ❌ These will cause problems:
threading.Thread(target=lambda: QPixmap(100, 100)).start()  # CRASHES
spy = QSignalSpy(mock.signal)                               # TypeError  
if self.layout:                                             # Falsy when empty
worker.start(); with qtbot.waitSignal(worker.signal): pass # Race condition
controller = Mock(spec=Controller)                          # Testing mock
mock.assert_called_once()                                   # Testing implementation
spy.at(-1)                                                  # Segfault in Qt
class TestHelper:  # without __test__ = False              # Collection warning
app = QApplication([])                                      # Multiple instances

# ✅ Use these instead:
QImage(100, 100, QImage.Format.Format_RGB32)               # Thread-safe
QSignalSpy(real_widget.real_signal)                        # Real signals only
if self.layout is not None:                                # Explicit check
with qtbot.waitSignal(signal): worker.start()              # Signal first
Controller(backend=TestBackend())                          # Real with test doubles
assert result.success                                       # Test behavior
spy.at(spy.count() - 1)                                   # Safe indexing
class TestHelper: __test__ = False                         # Prevent collection
qapp fixture from pytest-qt                                # Singleton QApp
```

### Testing Checklist
- [ ] Use real components where possible
- [ ] Mock only external dependencies
- [ ] Use `qtbot.addWidget()` for all widgets
- [ ] Check `is not None` for Qt containers
- [ ] Use QImage instead of QPixmap in worker threads
- [ ] Set up qtbot.waitSignal() BEFORE starting operations
- [ ] Use factory fixtures for flexible test data
- [ ] Test behavior, not implementation
- [ ] Add `__test__ = False` to all test double classes
- [ ] Use `spy.at(spy.count() - 1)` not `spy.at(-1)` for QSignalSpy
- [ ] Clean up QThreads with quit() and wait()
- [ ] Use tmp_path for file operations
- [ ] Add appropriate test markers (unit, integration, slow, etc.)

---

*This guide provides universal testing patterns for Python/PySide6 applications. Use the decision tree and lookup table to quickly find the right approach for your testing scenario.*

**Key Features**:
- Zero project-specific references
- Universal patterns applicable to any PySide6 project
- Production-tested anti-patterns and solutions
- LLM-optimized with line numbers and decision trees
- Modern pytest patterns (factory fixtures, parametrization, markers)

*Last Updated: 2025-02-01 | Based on production experience*